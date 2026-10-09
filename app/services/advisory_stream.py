"""
app/services/advisory_stream.py
═══════════════════════════════════════════════════════════════════════════════
Tách phần "chậm / tùy chọn" khỏi đường găng của POST /api/plan/calculate:
  • Lời khuyên Claude/Ollama (1.5–3 s)                      -> chạy nền, đẩy qua SSE
  • Chặng Goong chưa kịp xong trong ngân sách chờ           -> hoàn tất nền, đẩy qua SSE

Mỗi response /calculate mang `plan_id`. Client mở  GET /api/plan/{plan_id}/events  (SSE)
hoặc  GET /api/plan/{plan_id}/poll?after=N  (JSON — cho proxy hay đệm SSE).

HỢP ĐỒNG SỰ KIỆN (event -> data JSON). `id:` = seq tăng dần từ 0 trong phạm vi một plan_id.
  advisory : {"id","status":"done","source":"ai"|"deterministic","text"}
  day_route: {"day","status":"complete"|"degraded","distance_km","duration_minutes","format","points"}
             format="array" -> points=[[lat,lng],...] ; format="encoded" -> points="<polyline5>"
  done     : {"plan_id"}                 LUÔN là sự kiện cuối và có `id:`. Client gọi es.close().
  timeout  : {"last_seq"}                KHÔNG có `id:` (không làm đổi Last-Event-ID). Server ngắt do quá
                                         SSE_MAX_SECONDS; EventSource tự nối lại và được phát bù từ last_seq.

ĐẢM BẢO
  • Log append-only, seq = chỉ số trong log => reconnect với Last-Event-ID không mất, không lặp.
  • `done` luôn đến (watchdog AI_HARD_TIMEOUT_S), luôn là cuối cùng; sự kiện đến muộn sau `done` bị bỏ.
  • Reconnect SAU `done` -> HTTP 204 (spec SSE: 204 làm EventSource ngừng kết nối lại).
  • Thread-safe: producer là thread của executor/Goong; consumer là coroutine. Đánh thức bằng
    loop.call_soon_threadsafe -> trễ ~ms, không polling.
  • Job nằm trong RAM của process (TTL, trần số job/sự kiện). Chạy >1 worker: cần sticky theo plan_id
    hoặc thay JobStore bằng SQLite WAL (giữ nguyên create/get/emit).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from app.services.polyline_codec import encode_polyline

logger = logging.getLogger("advisory_stream")


def _envf(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


JOB_TTL_S = _envf("JOB_TTL_S", 300.0)                 # tuổi tối đa của job trong RAM
JOB_MAX = int(_envf("JOB_MAX", 1000))                 # trần số job đồng thời
JOB_MAX_EVENTS = int(_envf("JOB_MAX_EVENTS", 256))    # trần số sự kiện/job (done luôn được ghi)
STREAM_MAX_S = _envf("SSE_MAX_SECONDS", 20.0)
HEARTBEAT_S = _envf("SSE_HEARTBEAT_SECONDS", 10.0)
AI_MAX_WORKERS = int(_envf("AI_MAX_WORKERS", 4))
AI_MAX_PENDING = int(_envf("AI_MAX_PENDING", 16))     # quá tải -> bỏ qua LLM, dùng text xác định
AI_HARD_TIMEOUT_S = _envf("AI_HARD_TIMEOUT", 12.0)    # watchdog: quá hạn -> phát text xác định

EV_ADVISORY, EV_DAY_ROUTE, EV_DONE, EV_TIMEOUT = "advisory", "day_route", "done", "timeout"
Event = Tuple[int, str, Dict[str, Any]]


# ── Job: log sự kiện append-only ────────────────────────────────────────────
class PlanJob:
    def __init__(self, plan_id: str):
        self.plan_id = plan_id
        self.created = time.monotonic()
        self._events: List[Event] = []
        self._expected = 0
        self._sealed = False
        self._finished = False
        self._dropped = 0
        self._waiters: List[Tuple[asyncio.AbstractEventLoop, asyncio.Event]] = []
        self._lock = threading.Lock()

    # -- đăng ký công việc (gọi TRƯỚC seal) --
    def expect(self, n: int = 1) -> None:
        with self._lock:
            if not self._finished:
                self._expected += n

    def seal(self) -> None:
        with self._lock:
            self._sealed = True
        self._finish_if_ready()

    def task_done(self) -> None:
        with self._lock:
            if self._finished:
                return
            self._expected -= 1
        self._finish_if_ready()

    # -- ghi --
    def emit(self, event: str, data: Dict[str, Any]) -> Optional[int]:
        """Thêm sự kiện; trả seq, hoặc None nếu job đã xong (bỏ sự kiện muộn) / vượt trần."""
        with self._lock:
            if self._finished:
                return None
            if len(self._events) >= JOB_MAX_EVENTS:
                self._dropped += 1
                return None
            seq = len(self._events)
            self._events.append((seq, event, data))
            waiters = list(self._waiters)
        _notify(waiters)
        return seq

    def _finish_if_ready(self) -> None:
        with self._lock:
            if self._finished or not self._sealed or self._expected > 0:
                return
            self._finished = True
            self._events.append((len(self._events), EV_DONE, {"plan_id": self.plan_id}))   # done: không bị trần chặn
            waiters = list(self._waiters)
        _notify(waiters)

    # -- đọc --
    def events_after(self, seq: int) -> List[Event]:
        with self._lock:
            return self._events[seq + 1:]

    @property
    def finished(self) -> bool:
        return self._finished

    @property
    def last_seq(self) -> int:
        with self._lock:
            return len(self._events) - 1

    @property
    def has_work(self) -> bool:
        return self._expected > 0 or bool(self._events)

    def is_complete_for(self, last_event_id: int) -> bool:
        """True nếu client đã nhận tới `done` -> reconnect nên nhận 204."""
        with self._lock:
            return self._finished and last_event_id >= len(self._events) - 1

    # -- đánh thức consumer async --
    def subscribe(self, loop: asyncio.AbstractEventLoop, ev: asyncio.Event) -> None:
        with self._lock:
            self._waiters.append((loop, ev))

    def unsubscribe(self, ev: asyncio.Event) -> None:
        with self._lock:
            self._waiters = [w for w in self._waiters if w[1] is not ev]


def _notify(waiters: List[Tuple[asyncio.AbstractEventLoop, asyncio.Event]]) -> None:
    for loop, ev in waiters:
        try:
            loop.call_soon_threadsafe(ev.set)
        except RuntimeError:          # loop đã đóng (client rớt) — bỏ qua
            pass


# ── JobStore: TTL + trần số job, an toàn luồng ──────────────────────────────
class JobStore:
    def __init__(self):
        self._jobs: "OrderedDict[str, PlanJob]" = OrderedDict()
        self._lock = threading.Lock()

    def create(self) -> PlanJob:
        job = PlanJob("pln_" + uuid.uuid4().hex[:12])
        with self._lock:
            self._purge_locked()
            while len(self._jobs) >= JOB_MAX:                       # đầy: loại job cũ nhất
                self._jobs.popitem(last=False)
            self._jobs[job.plan_id] = job
        return job

    def get(self, plan_id: str) -> Optional[PlanJob]:
        with self._lock:
            self._purge_locked()
            return self._jobs.get(plan_id)

    def _purge_locked(self) -> None:
        now = time.monotonic()
        while self._jobs:                                           # OrderedDict theo thời điểm tạo
            k, j = next(iter(self._jobs.items()))
            if now - j.created <= JOB_TTL_S:
                break
            del self._jobs[k]

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {"jobs": len(self._jobs), "ai_pending": _ai_pending}

    def clear(self) -> None:
        with self._lock:
            self._jobs.clear()


JOBS = JobStore()

_AI_EXEC = ThreadPoolExecutor(max_workers=AI_MAX_WORKERS, thread_name_prefix="ai")
_ai_pending = 0
_ai_lock = threading.Lock()


def shutdown() -> None:
    """Gọi trong lifespan shutdown."""
    _AI_EXEC.shutdown(wait=False, cancel_futures=True)


# ── Producer: lời khuyên AI ─────────────────────────────────────────────────
def submit_advisory(job: PlanJob, advisory_id: str, fn: Callable[..., str], kwargs: Dict[str, Any],
                    fallback_text: str) -> Dict[str, Any]:
    """
    Lên lịch 1 lời khuyên AI nền. Trả mô tả ĐỒNG BỘ (text xác định) để nhét vào response ngay;
    SSE chỉ "nâng cấp". Luôn có đúng một sự kiện `advisory` cho mỗi lời khuyên (kết quả AI, lỗi hoặc quá hạn).
    """
    global _ai_pending
    desc = {"id": advisory_id, "status": "pending", "source": "deterministic", "text": fallback_text}
    with _ai_lock:
        if _ai_pending >= AI_MAX_PENDING:
            desc["status"] = "skipped"
            return desc
        _ai_pending += 1
    job.expect(1)

    state = {"done": False}
    state_lock = threading.Lock()
    timer: List[Optional[threading.Timer]] = [None]

    def complete(text: str, source: str) -> None:        # đúng 1 lần: kết quả AI HOẶC watchdog
        with state_lock:
            if state["done"]:
                return
            state["done"] = True
        if timer[0] is not None:
            timer[0].cancel()
        job.emit(EV_ADVISORY, {"id": advisory_id, "status": "done", "source": source, "text": text})
        job.task_done()

    def on_future(f) -> None:
        global _ai_pending
        with _ai_lock:
            _ai_pending -= 1                              # worker thật sự rảnh mới giảm
        try:
            text = (f.result() or "").strip()
        except Exception as e:
            logger.warning("advisory %s lỗi: %s", advisory_id, type(e).__name__)
            text = ""
        ai_ok = bool(text) and text != fallback_text
        complete(text if ai_ok else fallback_text, "ai" if ai_ok else "deterministic")

    def on_timeout() -> None:
        logger.warning("advisory %s quá %.0fs -> dùng text xác định", advisory_id, AI_HARD_TIMEOUT_S)
        complete(fallback_text, "deterministic")

    try:
        fut = _AI_EXEC.submit(fn, **kwargs)
    except RuntimeError:                                  # executor đã đóng
        with _ai_lock:
            _ai_pending -= 1
        job.task_done()
        desc["status"] = "skipped"
        return desc
    t = threading.Timer(AI_HARD_TIMEOUT_S, on_timeout)
    t.daemon = True
    timer[0] = t
    t.start()
    fut.add_done_callback(on_future)
    return desc


# ── Producer: nâng cấp polyline khi các chặng Goong hoàn tất ────────────────
def submit_route_upgrade(job: PlanJob, day_idx: int, day_route: Any, epsilon_m: float, fmt: str) -> None:
    """Khi mọi chặng của 1 ngày xong -> phát `day_route` với polyline đầy đủ (đã nén RDP nếu epsilon_m>0)."""
    pending = [f for f in day_route.futures if not f.done()]
    if not pending:
        return
    job.expect(1)
    remaining = [len(pending)]
    lock = threading.Lock()

    def _cb(_f) -> None:
        with lock:
            remaining[0] -= 1
            last = remaining[0] == 0
        if not last:
            return
        try:
            a = day_route.assemble(epsilon_m)
            pts = encode_polyline(a["polyline"]) if fmt == "encoded" else a["polyline"]
            job.emit(EV_DAY_ROUTE, {"day": day_idx, "status": a["status"], "distance_km": a["distance_km"],
                                    "duration_minutes": a["duration_minutes"], "format": fmt, "points": pts})
        except Exception as e:
            logger.warning("day_route %s lỗi: %s", day_idx, type(e).__name__)
        finally:
            job.task_done()

    for f in pending:
        f.add_done_callback(_cb)


# ── SSE ──────────────────────────────────────────────────────────────────────
def format_sse(seq: Optional[int], event: str, data: Dict[str, Any]) -> str:
    """Khung SSE chuẩn. JSON một dòng (json.dumps escape \\n,\\r) nên không phá khung. seq=None -> không có id:."""
    head = f"id: {seq}\n" if seq is not None else ""
    return f"{head}event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


async def sse_iter(job: PlanJob, last_event_id: int = -1,
                   is_disconnected: Optional[Callable[[], Awaitable[bool]]] = None,
                   max_s: float = STREAM_MAX_S, heartbeat_s: float = HEARTBEAT_S, wake_s: float = 1.0):
    """
    Async generator thuần (không phụ thuộc Starlette -> test được).
    Chống mất đánh thức: clear() -> đọc `finished` -> đọc sự kiện -> chờ. Sự kiện đến giữa lúc đọc và chờ
    sẽ set() sau clear() nên wait() trả về ngay. `finished` được đọc TRƯỚC khi đọc log để chắc chắn đã thấy `done`.
    """
    loop = asyncio.get_running_loop()
    wake = asyncio.Event()
    job.subscribe(loop, wake)
    try:
        yield "retry: 3000\n\n"
        cursor = max(-1, last_event_id)
        t0 = beat = time.monotonic()
        while True:
            wake.clear()
            fin = job.finished
            for seq, ev, data in job.events_after(cursor):
                yield format_sse(seq, ev, data)
                cursor = seq
            if fin:
                return
            now = time.monotonic()
            if now - t0 > max_s:
                yield format_sse(None, EV_TIMEOUT, {"last_seq": cursor})
                return
            if now - beat >= heartbeat_s:
                yield ": hb\n\n"
                beat = now
            if is_disconnected is not None and await is_disconnected():
                return
            try:
                await asyncio.wait_for(wake.wait(), timeout=max(0.01, min(wake_s, max_s - (now - t0))))
            except asyncio.TimeoutError:
                pass
    finally:
        job.unsubscribe(wake)


def poll_events(job: PlanJob, after: int = -1) -> Dict[str, Any]:
    evs = job.events_after(max(-1, after))
    return {"plan_id": job.plan_id, "finished": job.finished,
            "next_after": evs[-1][0] if evs else max(-1, after),
            "events": [{"seq": s, "event": e, "data": d} for s, e, d in evs]}


def _last_event_id(request: Any) -> int:
    raw = request.headers.get("last-event-id")
    if raw is None:
        raw = request.query_params.get("last_event_id")      # client dùng fetch không đặt được header
    try:
        return max(-1, int(raw))
    except (TypeError, ValueError):
        return -1


def build_router():
    """APIRouter (import FastAPI lười để module import được khi không có FastAPI, ví dụ trong test)."""
    from fastapi import APIRouter, HTTPException, Request, Response
    from fastapi.responses import StreamingResponse

    r = APIRouter()

    @r.get("/{plan_id}/events")
    async def plan_events(plan_id: str, request: Request):
        job = JOBS.get(plan_id)
        if job is None:
            raise HTTPException(status_code=404, detail="plan_id không tồn tại hoặc đã hết hạn")
        last = _last_event_id(request)
        if job.is_complete_for(last):
            return Response(status_code=204)                  # đã nhận `done`: bảo EventSource ngừng nối lại
        return StreamingResponse(
            sse_iter(job, last, request.is_disconnected), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})

    @r.get("/{plan_id}/poll")
    def plan_poll(plan_id: str, after: int = -1):
        job = JOBS.get(plan_id)
        if job is None:
            raise HTTPException(status_code=404, detail="plan_id không tồn tại hoặc đã hết hạn")
        return poll_events(job, after)

    return r
