"""
app/services/map_service.py  (v2 — drop-in, giữ nguyên API công khai cũ)
═══════════════════════════════════════════════════════════════════════════════
Thay đổi so với bản gốc (mỗi mục là một lỗi/điểm nghẽn có thật trong code cũ):

 1. requests.get() trần  -> requests.Session dùng chung (keep-alive). Bản cũ mở TCP+TLS MỚI cho
    từng chặng; ở RTT vài trăm ms, handshake chiếm một phần lớn "~290 ms/chặng" bạn đo được.
 2. Gọi tuần tự từng ngày, từng chặng -> fan-out TOÀN CHUYẾN (mọi chặng của mọi ngày) lên một
    ThreadPoolExecutor DÙNG CHUNG toàn process. Executor này đồng thời là giới hạn concurrency
    toàn cục (không phải "mỗi request 15 luồng" rồi nhân với số request).
 3. Single-flight: cùng một chặng đang bay -> mọi caller dùng chung một Future (không bắn 2 lần).
 4. Token-bucket QPS thích ứng (AIMD): gặp 429 -> giảm một nửa tốc độ; thành công -> tăng dần.
    Tôn trọng header Retry-After. Backoff = Full Jitter, có trần theo deadline của chặng.
 5. Circuit breaker (closed/open/half-open): Goong sập -> fail-fast về đường thẳng, không để
    3.5 s timeout × N chặng treo request.
 6. SỬA LỖI: bản cũ CACHE VĨNH VIỄN kết quả "geodesic_fallback" khi lỗi tạm thời (429/timeout)
    -> một lần Goong chập chờn là chặng đó thành đường thẳng đến khi restart. Bản này KHÔNG cache lỗi
    (chỉ cache âm 1h cho trường hợp Goong trả routes=[] thật sự).
 7. SỬA LỖI: cache RAM dict không giới hạn (docstring ghi LRU nhưng không phải) -> LRU thật, có khóa.
 8. SỬA LỖI: ghi cache đĩa không nguyên tử -> ghi tmp + os.replace.
 9. SỬA LỖI BẢO MẬT: log `{e}` của requests có thể chứa URL kèm api_key -> chỉ log tên lớp lỗi;
    api_key đi qua params=, không nối vào URL.
10. API mới plan_routes(): trả DayRoute có thể "partial" khi quá ngân sách chờ, phần còn lại hoàn tất
    nền và được đẩy qua SSE (xem advisory_stream.py).
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import random
import re
import threading
import time
import urllib.request
from collections import OrderedDict
from concurrent.futures import Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter

from app.services.polyline_codec import decode_polyline, rdp_simplify  # noqa: F401  (decode_polyline re-export)

load_dotenv()

_KEY_RE = re.compile(r"(api_key=)[^&\s'\")]+", re.IGNORECASE)


class _RedactKeyFilter(logging.Filter):
    """Che api_key trong MỌI bản ghi log (kể cả message chứa URL từ requests/urllib3 và traceback)."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            red = _KEY_RE.sub(r"\1***", msg)
            key = os.getenv("GOONG_API_KEY")
            if key:
                red = red.replace(key, "***")
            if red != msg:
                record.msg, record.args = red, ()
            if record.exc_info and record.exc_info[1] is not None:       # không để traceback lộ URL
                record.exc_text = _KEY_RE.sub(r"\1***", "".join(logging.Formatter().formatException(record.exc_info)))
                record.exc_info = None
        except Exception:
            pass
        return True


logger = logging.getLogger("map_service")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
for _name in ("map_service", "urllib3", "urllib3.connectionpool", "requests"):
    _lg = logging.getLogger(_name)
    if not any(isinstance(f, _RedactKeyFilter) for f in _lg.filters):
        _lg.addFilter(_RedactKeyFilter())


# ── Cấu hình (ghi đè bằng biến môi trường) ─────────────────────────────────
def _envf(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


CACHE_DIR = Path(os.getenv("MAP_CACHE_DIR", "data/map_cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

GOONG_API_KEY = os.getenv("GOONG_API_KEY")
GOONG_DIRECTIONS_API_URL = os.getenv("GOONG_DIRECTIONS_URL", "https://rsapi.goong.io/Direction")

MAX_CONCURRENCY = int(_envf("GOONG_MAX_CONCURRENCY", 6))   # số kết nối đồng thời TOÀN process
QPS_MAX = _envf("GOONG_QPS", 10.0)                          # đặt theo quota gói Goong CỦA BẠN
CONNECT_TIMEOUT_S = _envf("GOONG_CONNECT_TIMEOUT", 1.0)
READ_TIMEOUT_S = _envf("GOONG_READ_TIMEOUT", 2.5)
MAX_RETRIES = int(_envf("GOONG_MAX_RETRIES", 2))
LEG_HARD_BUDGET_S = _envf("GOONG_LEG_BUDGET", 6.0)          # xếp hàng + retry tối đa cho 1 chặng
NEG_TTL_S = 3600.0
RAM_CACHE_MAX = 4096

_V_MAP = {"motorbike": "bike", "bike": "bike", "car": "car", "taxi": "taxi", "van": "car", "bus": "car"}


def _goong_vehicle(vehicle: str) -> str:
    return _V_MAP.get((vehicle or "car").lower(), "car")


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    dlat, dlng = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return 6371.0 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── Cache: LRU RAM (có khóa) + đĩa nguyên tử + cache âm có TTL ────────────
class _LRU:
    def __init__(self, maxsize: int):
        self._d: "OrderedDict[str, Any]" = OrderedDict()
        self._max = maxsize
        self._lock = threading.Lock()

    def get(self, k: str):
        with self._lock:
            v = self._d.get(k)
            if v is not None:
                self._d.move_to_end(k)
            return v

    def set(self, k: str, v: Any) -> None:
        with self._lock:
            self._d[k] = v
            self._d.move_to_end(k)
            while len(self._d) > self._max:
                self._d.popitem(last=False)

    def __len__(self) -> int:
        return len(self._d)


_RAM = _LRU(RAM_CACHE_MAX)
_NEG: Dict[str, Tuple[float, dict]] = {}
_NEG_LOCK = threading.Lock()


def _leg_key(o: Tuple[float, float], d: Tuple[float, float], gv: str) -> str:
    # Giữ nguyên định dạng khóa cũ -> cache đĩa hiện có vẫn dùng được.
    return f"{o[0]:.5f},{o[1]:.5f}_{d[0]:.5f},{d[1]:.5f}_{gv}"


def _disk_file(key: str) -> Path:
    return CACHE_DIR / f"dir_{hashlib.md5(key.encode()).hexdigest()}.json"


def _cache_get(key: str) -> Optional[dict]:
    v = _RAM.get(key)
    if v is not None:
        return v
    f = _disk_file(key)
    if f.exists():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("success"):          # không bao giờ nạp lại bản fallback từ đĩa cũ
                _RAM.set(key, data)
                return data
        except Exception:
            pass
    with _NEG_LOCK:
        hit = _NEG.get(key)
        if hit and hit[0] > time.monotonic():
            return hit[1]
    return None


def _cache_set(key: str, result: dict) -> None:
    _RAM.set(key, result)
    f = _disk_file(key)
    tmp = f.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, f)                    # nguyên tử: reader không bao giờ thấy file dở
    except Exception as e:
        logger.warning("Ghi cache đĩa lỗi: %s", type(e).__name__)
        try:
            tmp.unlink()
        except Exception:
            pass


def _geodesic(o: Tuple[float, float], d: Tuple[float, float]) -> dict:
    return {
        "success": False, "source": "geodesic_fallback", "degraded": True,
        "distance_km": round(_haversine_km(o[0], o[1], d[0], d[1]), 2),
        "duration_minutes": 0,
        "polyline": [[o[0], o[1]], [d[0], d[1]]],
    }


# ── Hạ tầng chống quá tải ────────────────────────────────────────────────────
class _AdaptiveBucket:
    """Token bucket + AIMD: 429 -> rate/2 ; thành công -> +0.25/s tới trần cấu hình."""

    def __init__(self, rate: float, burst: int):
        self.max_rate, self.rate, self.cap = rate, rate, float(burst)
        self.tokens, self.ts = float(burst), time.monotonic()
        self._last_pen = 0.0
        self._lock = threading.Lock()

    def acquire(self, deadline: float) -> bool:
        while True:
            with self._lock:
                now = time.monotonic()
                self.tokens = min(self.cap, self.tokens + (now - self.ts) * self.rate)
                self.ts = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return True
                wait_s = (1.0 - self.tokens) / self.rate
            if time.monotonic() + wait_s > deadline:
                return False
            time.sleep(wait_s)

    def penalize(self) -> None:
        with self._lock:
            now = time.monotonic()
            if now - self._last_pen < 0.5:       # nhiều luồng cùng nhận 429 chỉ tính 1 lần
                return
            self._last_pen = now
            self.rate = max(1.0, self.rate * 0.5)

    def reward(self) -> None:
        with self._lock:
            self.rate = min(self.max_rate, self.rate + 0.25)


class _CircuitBreaker:
    def __init__(self, threshold: int = 5, open_s: float = 15.0, probe_s: float = 5.0):
        self.threshold, self.open_s, self.probe_s = threshold, open_s, probe_s
        self.state, self.failures = "closed", 0
        self.opened_at = self.probe_at = 0.0
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            now = time.monotonic()
            if self.state == "closed":
                return True
            if self.state == "open":
                if now - self.opened_at >= self.open_s:
                    self.state, self.probe_at = "half_open", now
                    return True               # đúng 1 request thăm dò
                return False
            if now - self.probe_at >= self.probe_s:   # probe cũ biến mất -> cho thăm dò lại
                self.probe_at = now
                return True
            return False

    def is_open(self) -> bool:
        return self.state == "open"

    def success(self) -> None:
        with self._lock:
            self.state, self.failures = "closed", 0

    def failure(self) -> None:
        with self._lock:
            self.failures += 1
            if self.state == "half_open" or self.failures >= self.threshold:
                self.state, self.opened_at = "open", time.monotonic()


_BUCKET = _AdaptiveBucket(QPS_MAX, burst=max(1, MAX_CONCURRENCY))
_BREAKER = _CircuitBreaker(threshold=int(_envf("GOONG_BREAKER_THRESHOLD", max(5, MAX_CONCURRENCY + 2))))
_SESSION: Optional[requests.Session] = None
_SESSION_LOCK = threading.Lock()
_EXEC: Optional[ThreadPoolExecutor] = None
_EXEC_LOCK = threading.Lock()
_INFLIGHT: Dict[str, Future] = {}
_INFLIGHT_LOCK = threading.Lock()
_WARNED_AUTH = False


def _session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        with _SESSION_LOCK:
            if _SESSION is None:
                s = requests.Session()
                ad = HTTPAdapter(pool_connections=4, pool_maxsize=MAX_CONCURRENCY * 2, max_retries=0)
                s.mount("https://", ad)
                s.mount("http://", ad)
                s.headers.update({"User-Agent": "VNTravel/2 (+keepalive)"})
                _SESSION = s
    return _SESSION


def _executor() -> ThreadPoolExecutor:
    global _EXEC
    if _EXEC is None:
        with _EXEC_LOCK:
            if _EXEC is None:
                _EXEC = ThreadPoolExecutor(max_workers=MAX_CONCURRENCY, thread_name_prefix="goong")
    return _EXEC


def shutdown() -> None:
    """Gọi trong lifespan shutdown."""
    global _EXEC, _SESSION
    if _EXEC is not None:
        _EXEC.shutdown(wait=False, cancel_futures=True)
        _EXEC = None
    if _SESSION is not None:
        _SESSION.close()
        _SESSION = None


def stats() -> Dict[str, Any]:
    """Gắn vào /health: quan sát breaker, tốc độ thích ứng, số chặng đang bay."""
    return {
        "breaker": _BREAKER.state, "breaker_failures": _BREAKER.failures,
        "qps_now": round(_BUCKET.rate, 2), "qps_max": _BUCKET.max_rate,
        "inflight_legs": len(_INFLIGHT), "ram_cache": len(_RAM),
    }


def _sleep_backoff(attempt: int, retry_after: Optional[float], give_up_at: float) -> None:
    delay = random.uniform(0.0, min(1.0, 0.15 * (2 ** attempt)))      # Full Jitter, trần 1 s
    if retry_after is not None:
        delay = max(delay, min(retry_after, 2.0))
    delay = min(delay, max(0.0, give_up_at - time.monotonic() - 0.05))
    if delay > 0:
        time.sleep(delay)


def _retry_after(resp: requests.Response) -> Optional[float]:
    try:
        return float(resp.headers.get("Retry-After", ""))
    except ValueError:
        return None


def _fetch_network(o: Tuple[float, float], d: Tuple[float, float], gv: str, give_up_at: float) -> Optional[dict]:
    """None = lỗi tạm thời (KHÔNG cache). {'__no_route__': True} = Goong bảo không có tuyến."""
    global _WARNED_AUTH
    if not GOONG_API_KEY or not _BREAKER.allow():
        return None
    params = {"origin": f"{o[0]},{o[1]}", "destination": f"{d[0]},{d[1]}", "vehicle": gv, "api_key": GOONG_API_KEY}
    for attempt in range(MAX_RETRIES + 1):
        now = time.monotonic()
        if now >= give_up_at or (attempt > 0 and _BREAKER.is_open()) or not _BUCKET.acquire(give_up_at):
            return None                       # hết ngân sách / breaker đã mở giữa chừng -> thoát, đừng retry
        try:
            resp = _session().get(GOONG_DIRECTIONS_API_URL, params=params,
                                  timeout=(CONNECT_TIMEOUT_S, max(0.2, min(READ_TIMEOUT_S, give_up_at - now))))
        except (requests.Timeout, requests.ConnectionError) as e:
            _BREAKER.failure()
            logger.warning("Goong %s (lần %d)", type(e).__name__, attempt + 1)   # KHÔNG log str(e): chứa URL+key
            _sleep_backoff(attempt, None, give_up_at)
            continue
        except Exception as e:
            _BREAKER.failure()
            logger.warning("Goong lỗi lạ %s", type(e).__name__)
            return None

        sc = resp.status_code
        if sc == 200:
            try:
                routes = resp.json().get("routes", [])
            except ValueError:
                _BREAKER.failure()
                return None
            _BREAKER.success()
            _BUCKET.reward()
            if not routes:
                return {"__no_route__": True}
            r = routes[0]
            decoded = decode_polyline(r.get("overview_polyline", {}).get("points", ""))
            if not decoded:
                return {"__no_route__": True}
            leg = (r.get("legs") or [{}])[0]
            return {
                "success": True, "source": "goong_directions",
                "distance_km": round(leg.get("distance", {}).get("value", 0) / 1000.0, 2),
                "duration_minutes": max(1, int(round(leg.get("duration", {}).get("value", 0) / 60.0))),
                "polyline": decoded,
            }
        if sc == 429:                       # quá tải: giảm tốc, KHÔNG tính vào breaker
            _BUCKET.penalize()
            _sleep_backoff(attempt, _retry_after(resp), give_up_at)
            continue
        if sc in (500, 502, 503, 504):
            _BREAKER.failure()
            _sleep_backoff(attempt, _retry_after(resp), give_up_at)
            continue
        if sc in (401, 403):                # lỗi cấu hình/quota: retry vô ích
            _BREAKER.failure()
            if not _WARNED_AUTH:
                _WARNED_AUTH = True
                logger.error("Goong trả %d — kiểm tra GOONG_API_KEY/quota", sc)
        return None
    return None


def _leg_task(key: str, o, d, gv: str, give_up_at: float, fut: Future) -> None:
    try:
        res = _fetch_network(o, d, gv, give_up_at)
        if res is None:
            out = _geodesic(o, d)                                   # lỗi tạm: KHÔNG cache
        elif res.get("__no_route__"):
            out = _geodesic(o, d)
            with _NEG_LOCK:
                _NEG[key] = (time.monotonic() + NEG_TTL_S, out)    # cache âm có TTL
        else:
            out = res
            _cache_set(key, out)
    except BaseException as e:                                       # noqa: BLE001
        logger.warning("leg task lỗi: %s", type(e).__name__)
        out = _geodesic(o, d)
    finally:
        with _INFLIGHT_LOCK:
            _INFLIGHT.pop(key, None)
    fut.set_result(out)


def _submit_leg(o: Tuple[float, float], d: Tuple[float, float], vehicle: str) -> Future:
    gv = _goong_vehicle(vehicle)
    key = _leg_key(o, d, gv)
    f: Future = Future()
    if key.split("_")[0] == key.split("_")[1]:                       # cùng một điểm
        f.set_result({"success": True, "source": "identity", "distance_km": 0.0,
                      "duration_minutes": 0, "polyline": [[o[0], o[1]], [d[0], d[1]]]})
        return f
    hit = _cache_get(key)
    if hit is not None:
        f.set_result(hit)
        return f
    with _INFLIGHT_LOCK:                                             # single-flight
        existing = _INFLIGHT.get(key)
        if existing is not None:
            return existing
        _INFLIGHT[key] = f
    try:
        _executor().submit(_leg_task, key, o, d, gv, time.monotonic() + LEG_HARD_BUDGET_S, f)
    except RuntimeError:                                             # executor đã shutdown
        with _INFLIGHT_LOCK:
            _INFLIGHT.pop(key, None)
        f.set_result(_geodesic(o, d))
    return f


# ── API công khai (tương thích bản cũ) ───────────────────────────────────────
def get_leg_directions(origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float,
                       vehicle: str = "car") -> Dict[str, Any]:
    o, d = (origin_lat, origin_lng), (dest_lat, dest_lng)
    try:
        return _submit_leg(o, d, vehicle).result(timeout=LEG_HARD_BUDGET_S + 1.0)
    except Exception:
        return _geodesic(o, d)


class DayRoute:
    """Tuyến của 1 ngày = chuỗi Future theo chặng. Có thể 'partial' nếu quá ngân sách chờ."""

    def __init__(self, coords: List[Tuple[float, float]], futures: List[Future]):
        self.coords, self.futures = coords, futures

    @property
    def done(self) -> bool:
        return all(f.done() for f in self.futures)

    @property
    def status(self) -> str:
        if not self.done:
            return "partial"
        return "degraded" if any(f.result().get("degraded") for f in self.futures) else "complete"

    def assemble(self, epsilon_m: float = 0.0) -> Dict[str, Any]:
        poly: List[List[float]] = []
        dist, dur = 0.0, 0
        for i, f in enumerate(self.futures):
            leg = f.result() if f.done() else _geodesic(self.coords[i], self.coords[i + 1])
            pts = rdp_simplify(leg["polyline"], epsilon_m) if epsilon_m > 0 else leg["polyline"]
            poly.extend(pts if not poly else pts[1:])               # tránh trùng điểm nối
            dist += leg.get("distance_km", 0.0)
            dur += leg.get("duration_minutes", 0)
        if not self.futures:
            poly = [[c[0], c[1]] for c in self.coords]
        return {"distance_km": round(dist, 2), "duration_minutes": dur, "polyline": poly, "status": self.status}


def plan_routes(days_coords: Sequence[Sequence[Tuple[float, float]]], vehicle: str = "car",
                wait_budget_ms: Optional[float] = None) -> List[DayRoute]:
    """
    Bắn MỌI chặng của MỌI ngày cùng lúc. wait_budget_ms:
      None -> chờ tới khi xong hết (hành vi cũ) ; 0 -> chỉ bắn rồi trả về ngay ;
      N    -> chờ tối đa N ms, chặng chưa xong sẽ hoàn tất nền (DayRoute.status == 'partial').
    """
    routes = []
    for coords in days_coords:
        coords = [(float(c[0]), float(c[1])) for c in coords]
        futs = [_submit_leg(a, b, vehicle) for a, b in zip(coords, coords[1:])]
        routes.append(DayRoute(coords, futs))
    wait_routes(routes, wait_budget_ms)
    return routes


def wait_routes(routes: Sequence[DayRoute], wait_budget_ms: Optional[float]) -> None:
    allf = [f for r in routes for f in r.futures]
    if allf and (wait_budget_ms is None or wait_budget_ms > 0):
        wait(allf, timeout=None if wait_budget_ms is None else wait_budget_ms / 1000.0)


def prefetch_legs(pairs: Sequence[Tuple[Tuple[float, float], Tuple[float, float]]], vehicle: str = "car") -> List[Future]:
    """Bắn trước một nhóm chặng lên pool dùng chung (không chờ). Các lệnh get_leg_directions() sau đó
    sẽ dùng chung Future đang bay nhờ single-flight -> N chặng tuần tự trong code cũ tốn ~1 RTT thay vì N."""
    return [_submit_leg((float(a[0]), float(a[1])), (float(b[0]), float(b[1])), vehicle) for a, b in pairs]


def get_multi_stop_route(coordinates: List[Tuple[float, float]], vehicle: str = "car") -> Dict[str, Any]:
    """Tương thích ngược. Dùng plan_routes() để fan-out nhiều ngày một lúc."""
    if len(coordinates) < 2:
        return {"distance_km": 0.0, "duration_minutes": 0, "polyline": [[c[0], c[1]] for c in coordinates]}
    r = plan_routes([coordinates], vehicle, wait_budget_ms=None)[0].assemble()
    return {"distance_km": r["distance_km"], "duration_minutes": r["duration_minutes"], "polyline": r["polyline"]}


# ── Bản đồ tĩnh (giữ nguyên hành vi cũ; không nằm trong hot-path /calculate) ─
def get_static_route_image(origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float,
                           vehicle: str = "car", width: int = 600, height: int = 350) -> Optional[bytes]:
    if not GOONG_API_KEY:
        return None
    gv = _goong_vehicle(vehicle)
    cache_key = hashlib.md5(
        f"{origin_lat:.4f},{origin_lng:.4f}_{dest_lat:.4f},{dest_lng:.4f}_{gv}_{width}_{height}".encode()).hexdigest()
    cache_file = CACHE_DIR / f"{cache_key}.png"
    if cache_file.exists():
        try:
            return cache_file.read_bytes()
        except Exception:
            pass
    api_url = (f"https://rsapi.goong.io/staticmap/route?origin={origin_lat},{origin_lng}&"
               f"destination={dest_lat},{dest_lng}&vehicle={gv}&width={width}&height={height}&api_key={GOONG_API_KEY}")
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0 (Vietnam Travel Planner)"})
        with urllib.request.urlopen(req, timeout=8) as response:
            if response.status == 200:
                data = response.read()
                cache_file.write_bytes(data)
                return data
    except Exception as e:
        logger.warning("[Goong Map Service] Lỗi tải bản đồ tĩnh: %s", type(e).__name__)
    return None
