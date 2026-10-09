"""
app/services/llm_service.py
═══════════════════════════════════════════════════════════════════════════════
Dịch vụ tích hợp LLM — VNTravel AI (AI Sandwich Pattern, Defensive Fallback, Zero-Crash).

  TẦNG 1 (PRIMARY)  : Claude Sonnet 4.6 qua VyceAI (OpenAI-compatible /chat/completions)
  TẦNG 2 (LOCAL)    : Ollama (vn-travel-qwen:7b @ localhost:11434)
  TẦNG 3 (XÁC ĐỊNH) : trả "" -> caller dùng text mẫu (explain_* tự trả *_fallback)

THIẾT KẾ v2
  • Total Time Budget: MỘT ngân sách thời gian cho cả lần gọi (mặc định 5 s, trần 6 s) chia sẻ giữa
    Claude và Ollama. Claude được tối đa PRIMARY_SHARE (70%) ngân sách để Ollama luôn còn thời gian;
    nếu Claude lỗi sớm (401, 5xx, mất mạng) thì Ollama nhận toàn bộ phần còn lại.
    -> worst case một worker bị giữ ≈ 5 s thay vì 4 + 4 (hoặc 8 + 4 = 12 s) như bản cũ.
  • Cache: LRU giới hạn (mặc định 1024 mục), khóa SHA-256 gồm model + system prompt + prompt +
    temperature + max_tokens, an toàn luồng. Chỉ cache kết quả của tầng PRIMARY.
  • Bảo mật log: mọi thông điệp lỗi/body đi qua _redact() (api key, Bearer token, sk-...).

API công khai (giữ nguyên tên/chữ ký):
  call_llm, explain_hotel_tradeoff, explain_roadtrip_tradeoff,
  hotel_tradeoff_fallback, roadtrip_tradeoff_fallback
Tiện ích mới (tùy chọn): llm_cache_stats(), clear_llm_cache()
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("llm_service")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return float(default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return int(default)


# ── Cấu hình ────────────────────────────────────────────────────────────────
VYCEAI_API_KEY = (os.getenv("VYCEAI_API_KEY") or "").strip() or None
VYCEAI_BASE_URL = os.getenv("VYCEAI_BASE_URL", "https://vyceai.com/v1").rstrip("/")
PRIMARY_MODEL = "claude-sonnet-4-6"

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "vn-travel-qwen:7b")

TOTAL_BUDGET_S = _env_float("LLM_TOTAL_BUDGET_S", 5.0)        # ngân sách mặc định cho 1 lần call_llm
BUDGET_HARD_CAP_S = _env_float("LLM_BUDGET_HARD_CAP_S", 6.0)  # trần tuyệt đối (kể cả caller truyền timeout lớn)
PRIMARY_SHARE = min(max(_env_float("LLM_PRIMARY_SHARE", 0.7), 0.1), 1.0)
CONNECT_TIMEOUT_S = 1.0                                       # kết nối thất bại phải thất bại nhanh
MIN_ATTEMPT_S = 0.3                                           # còn ít hơn mức này thì không đáng thử tầng kế
CACHE_MAX = max(1, _env_int("LLM_CACHE_MAX", 1024))

DEFAULT_SYSTEM_PROMPT = (
    "Bạn là VNTravel AI - Cố vấn du lịch Việt Nam chuyên nghiệp. "
    "Nhiệm vụ của bạn là đưa ra lời khuyên thực tế, trung thực dựa trên cự ly đường bộ, "
    "nhịp sinh học và an toàn giao thông, văn phong ngắn gọn, tinh tế và lịch sự."
)


# ── Che bí mật trong log ────────────────────────────────────────────────────
_SECRET_PATTERNS = (
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-~+/=]+"), r"\1***"),
    (re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|token|authorization)(\s*[=:]\s*)[^\s,;&\"']+"), r"\1\2***"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), "sk-***"),
)


def _redact(value: Any) -> str:
    """Chuyển về str và che api key / Bearer token. Luôn dùng trước khi ghi log lỗi hoặc body phản hồi."""
    s = str(value)
    if VYCEAI_API_KEY:
        s = s.replace(VYCEAI_API_KEY, "***")
    for pat, repl in _SECRET_PATTERNS:
        s = pat.sub(repl, s)
    return s


# ── LRU cache an toàn luồng ─────────────────────────────────────────────────
class _LRUCache:
    def __init__(self, max_size: int):
        self._max = max(1, int(max_size))
        self._data: "OrderedDict[str, str]" = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            val = self._data.get(key)
            if val is None:
                self._misses += 1
                return None
            self._data.move_to_end(key)
            self._hits += 1
            return val

    def put(self, key: str, value: str) -> None:
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)          # loại mục ít dùng gần đây nhất

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._hits = self._misses = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {"size": len(self._data), "max": self._max, "hits": self._hits, "misses": self._misses}


_LLM_CACHE = _LRUCache(CACHE_MAX)


def llm_cache_stats() -> Dict[str, int]:
    return _LLM_CACHE.stats()


def clear_llm_cache() -> None:
    _LLM_CACHE.clear()


def _cache_key(system_prompt: str, prompt: str, temperature: float, max_tokens: int) -> str:
    raw = json.dumps([PRIMARY_MODEL, system_prompt, prompt.strip(), round(float(temperature), 4), int(max_tokens)],
                     ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _resolve_budget(timeout: Optional[float]) -> float:
    """`timeout` (tham số cũ) nay là TỔNG ngân sách cho cả hai tầng, bị chặn bởi BUDGET_HARD_CAP_S."""
    try:
        b = TOTAL_BUDGET_S if timeout is None else float(timeout)
    except (TypeError, ValueError):
        b = TOTAL_BUDGET_S
    return max(0.5, min(b, BUDGET_HARD_CAP_S))


# ── Các tầng gọi ────────────────────────────────────────────────────────────
def _call_primary(system_prompt: str, prompt: str, temperature: float, max_tokens: int, budget_s: float) -> str:
    """Claude qua VyceAI. Trả "" nếu lỗi/rỗng. Không bao giờ ném exception, không ghi key vào log."""
    try:
        resp = requests.post(
            f"{VYCEAI_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {VYCEAI_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": PRIMARY_MODEL,
                "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=(min(CONNECT_TIMEOUT_S, budget_s), budget_s),
        )
        if resp.status_code != 200:
            logger.warning("[LLM] VyceAI Claude trả status %s: %s", resp.status_code, _redact(resp.text)[:120])
            return ""
        choices = resp.json().get("choices") or [{}]
        return ((choices[0].get("message") or {}).get("content") or "").strip()
    except Exception as e:  # noqa: BLE001 — Zero-Crash
        logger.warning("[LLM] VyceAI Claude lỗi %s: %s -> chuyển Fallback", type(e).__name__, _redact(e)[:160])
        return ""


def _call_ollama(system_prompt: str, prompt: str, temperature: float, max_tokens: int, budget_s: float) -> str:
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            },
            timeout=(min(CONNECT_TIMEOUT_S, budget_s), budget_s),
        )
        if resp.status_code != 200:
            logger.info("[LLM] Ollama trả status %s", resp.status_code)
            return ""
        return ((resp.json().get("message") or {}).get("content") or "").strip()
    except Exception as e:  # noqa: BLE001 — Ollama tắt là tình huống bình thường
        logger.info("[LLM] Ollama không khả dụng (%s)", type(e).__name__)
        return ""


def call_llm(
    prompt: str,
    system_prompt: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 800,
    timeout: Optional[float] = None,
) -> str:
    """
    Gọi LLM với phòng thủ nhiều tầng dưới MỘT ngân sách thời gian chung:
      0. LRU cache  ->  1. Claude (VyceAI, tối đa PRIMARY_SHARE ngân sách)
      ->  2. Ollama (phần ngân sách còn lại)  ->  3. "" (caller dùng text xác định).

    `timeout` giữ nguyên tên tham số cũ nhưng nay là TỔNG ngân sách (giây) cho cả hai tầng;
    None -> LLM_TOTAL_BUDGET_S (mặc định 5 s); luôn bị chặn bởi LLM_BUDGET_HARD_CAP_S (mặc định 6 s).
    Không bao giờ ném exception.
    """
    sys_p = system_prompt or DEFAULT_SYSTEM_PROMPT
    key = _cache_key(sys_p, prompt, temperature, max_tokens)
    cached = _LLM_CACHE.get(key)
    if cached is not None:
        return cached

    budget = _resolve_budget(timeout)
    deadline = time.monotonic() + budget

    # TẦNG 1: Claude — không được ăn quá PRIMARY_SHARE ngân sách để chừa chỗ cho Ollama
    if VYCEAI_API_KEY:
        t = min(deadline - time.monotonic(), budget * PRIMARY_SHARE)
        if t >= MIN_ATTEMPT_S:
            content = _call_primary(sys_p, prompt, temperature, max_tokens, t)
            if content:
                _LLM_CACHE.put(key, content)
                return content

    # TẦNG 2: Ollama — nhận mọi thứ còn lại của ngân sách
    t = deadline - time.monotonic()
    if t >= MIN_ATTEMPT_S:
        content = _call_ollama(sys_p, prompt, temperature, max_tokens, t)
        if content:
            return content                      # không cache: lần sau vẫn thử lại Claude

    # TẦNG 3: xác định
    return ""


# ── Lời khuyên: khách sạn ───────────────────────────────────────────────────
def hotel_tradeoff_fallback(
    hotel_name: str,
    day_num: int,
    cluster_name: str,
    distance_km: float,
    commute_mins: int,
    alt_hotel_name: Optional[str] = None,
) -> str:
    """Text xác định (không gọi mạng). Chữ ký trùng explain_hotel_tradeoff để router gọi bằng cùng kwargs."""
    alt = f" như {alt_hotel_name}" if alt_hotel_name else ""
    return (
        f"Khách sạn {hotel_name} cách cụm tham quan Ngày {day_num} khoảng {distance_km:.0f} km "
        f"(mất ~{commute_mins} phút di chuyển khứ hồi). "
        f"Bạn có thể giữ nguyên khách sạn để không phải chuyển hành lý (nhưng cần xuất phát sớm), "
        f"hoặc cân nhắc đổi sang khu vực gần hơn{alt} để tiết kiệm thời gian ngồi xe."
    )


def explain_hotel_tradeoff(
    hotel_name: str,
    day_num: int,
    cluster_name: str,
    distance_km: float,
    commute_mins: int,
    alt_hotel_name: Optional[str] = None,
) -> str:
    """Claude giải thích ngắn gọn khi khách sạn xa cụm tham quan; lỗi -> hotel_tradeoff_fallback."""
    alt_hint = f"Gợi ý thay thế gần cụm này: {alt_hotel_name}. " if alt_hotel_name else ""
    prompt = (
        f"Khách du lịch đã chọn nghỉ tại khách sạn '{hotel_name}'. "
        f"Tuy nhiên vào Ngày {day_num}, các điểm tham quan nằm ở khu vực '{cluster_name}', "
        f"cách khách sạn khoảng {distance_km:.1f} km một chiều (ước tính mất ~{commute_mins} phút di chuyển khứ hồi). "
        f"{alt_hint}"
        f"Hãy viết một đoạn tư vấn đúng 2-3 câu ngắn gọn: "
        f"Nêu rõ thời gian ngồi xe thực tế và đưa ra 2 lựa chọn "
        f"(A: đổi phòng gần hơn để đỡ mệt; B: giữ nguyên phòng nhưng dậy sớm hơn)."
    )
    return call_llm(prompt) or hotel_tradeoff_fallback(
        hotel_name, day_num, cluster_name, distance_km, commute_mins, alt_hotel_name)


# ── Lời khuyên: road trip ───────────────────────────────────────────────────
def roadtrip_tradeoff_fallback(
    origin: str,
    dest: str,
    days: int,
    needed_days: int,
    one_way_km: float,
    vehicle: str = "ô tô",
) -> str:
    """Text xác định (không gọi mạng). Chữ ký trùng explain_roadtrip_tradeoff."""
    return (
        f"Hành trình {origin} ➔ {dest} dài khoảng {one_way_km:.0f} km. "
        f"Để đảm bảo an toàn không lái xe quá 8 tiếng mỗi ngày, bạn cần tối thiểu {needed_days} ngày khứ hồi. "
        f"Với quỹ thời gian {days} ngày, chúng tôi khuyên bạn nên: (1) Tăng thời gian chuyến đi, "
        f"(2) Chuyển sang đi máy bay để tiết kiệm thời gian, hoặc (3) Chọn điểm đến gần hơn trong bán kính 400 km."
    )


def explain_roadtrip_tradeoff(
    origin: str,
    dest: str,
    days: int,
    needed_days: int,
    one_way_km: float,
    vehicle: str = "ô tô",
) -> str:
    """Claude giải thích vì sao số ngày không đủ cho road trip; lỗi -> roadtrip_tradeoff_fallback."""
    prompt = (
        f"Du khách muốn đi từ {origin} đến {dest} bằng {vehicle} trong {days} ngày. "
        f"Quãng đường thực tế khoảng {one_way_km:.0f} km mỗi chiều. "
        f"Theo quy chuẩn an toàn lái xe (không quá 8h/ngày, cự ly an toàn 400km/ngày), "
        f"chuyến đi cần tối thiểu {needed_days} ngày. "
        f"Hãy viết lời khuyên chân thành, ngắn gọn (3 câu): giải thích tại sao không khả thi và gợi ý 3 hướng giải quyết: "
        f"1. Tăng số ngày lên ≥ {needed_days} ngày; 2. Đổi sang đi máy bay; 3. Chọn điểm đến gần hơn trong bán kính 300-400km."
    )
    return call_llm(prompt) or roadtrip_tradeoff_fallback(origin, dest, days, needed_days, one_way_km, vehicle)
