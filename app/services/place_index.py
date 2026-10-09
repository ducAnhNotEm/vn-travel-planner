"""
app/services/place_index.py
═══════════════════════════════════════════════════════════════════════════════
Chỉ mục không gian TRONG RAM cho bảng `places` (~1.4k dòng). Nạp 1 lần ở FastAPI lifespan
bằng `load_from_db()`; hot-path /api/plan/calculate không còn chạm SQLite.

Toán học
  Mỗi địa điểm -> vector đơn vị u=(cosφ·cosλ, cosφ·sinλ, sinφ). Khoảng cách chord ‖u−v‖ = 2·sin(θ/2) với θ là góc
  tâm => đơn điệu tăng theo θ trên [0, π] => thứ tự Euclid trên vector đơn vị TRÙNG thứ tự haversine. Đổi ngược:
  d_km = 2·R·asin(chord/2) (R = 6371.0, cùng R với haversine_distance() trong travel_calculator.py).

Backend truy vấn
  1) scipy.spatial.cKDTree (mặc định; ~50 µs/truy vấn ở 1.4k điểm)
  2) NumPy brute-force (cùng kết quả) — tự động dùng khi: không import được scipy, dựng cây lỗi, hoặc
     tree.query() ném ngoại lệ lúc chạy (cây bị vô hiệu hóa, ghi log 1 lần, truy vấn vẫn trả đúng).

An toàn dữ liệu
  Mọi hàm công khai trả về BẢN SAO dict. Giá trị trong dict chỉ là scalar bất biến (sqlite3 chỉ trả
  int/float/str/bytes/None; constructor từ chối list/dict/set) nên dict(p) là bản sao độc lập hoàn toàn —
  rẻ hơn copy.deepcopy ~10×. Nhờ vậy sequence_by_human_rhythm() gán thêm khóa không làm bẩn request khác.

Tìm từ khóa: gấp hoa/thường + bỏ dấu tiếng Việt (đ/Đ -> d), chuẩn hóa NFC/NFD, gộp khoảng trắng.

Chạy:  python -m app.services.place_index --test      (không cần DB)
       python -m app.services.place_index --bench
"""
from __future__ import annotations

import logging
import math
import os
import sqlite3
import threading
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

try:  # scipy là tùy chọn — thiếu thì tự rơi về NumPy
    from scipy.spatial import cKDTree
except Exception:  # pragma: no cover
    cKDTree = None

logger = logging.getLogger("place_index")

R_KM = 6371.0
FILL_CATEGORIES = ("RESTAURANT", "ATTRACTION", "MARKET", "ACTIVITY")
_COLS = ("id, name, category, lat, lng, address, rating, price_range, prices, phone_number, website, "
         "image_url, google_maps_url, typical_time_spent, google_place_id")
_KEYS = ("id", "name", "category", "lat", "lng", "address", "rating", "price_range_db", "prices_json_db",
         "phone_number", "website", "image_url", "google_maps_url", "typical_time_spent", "google_place_id")
_MUTABLE = (list, dict, set, bytearray)


# ── Tiện ích ────────────────────────────────────────────────────────────────
def _fold(s: Optional[str]) -> str:
    """Gấp hoa/thường + bỏ dấu tiếng Việt + gộp khoảng trắng. 'Đà Nẵng ' -> 'da nang'."""
    if not s:
        return ""
    s = unicodedata.normalize("NFD", str(s).lower().replace("đ", "d"))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.split())


def _unit(lat: float, lng: float) -> np.ndarray:
    la, lo = math.radians(lat), math.radians(lng)
    return np.array([math.cos(la) * math.cos(lo), math.cos(la) * math.sin(lo), math.sin(la)])


def _coord(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _chord_to_km(chord: float) -> float:
    return 2.0 * R_KM * math.asin(min(1.0, chord / 2.0))


def _km_to_chord(km: float) -> float:
    return 2.0 * math.sin(min(km / R_KM + 1e-9, math.pi) / 2.0)


class PlaceIndex:
    def __init__(self, rows: Sequence[Sequence[Any]]):
        self._places: List[Dict[str, Any]] = []
        for r in rows:
            p = dict(zip(_KEYS, r))
            if len(r) != len(_KEYS) or any(isinstance(v, _MUTABLE) for v in p.values()):
                raise TypeError("Mỗi dòng phải có đúng 15 cột scalar (id,name,category,lat,lng,...)")
            self._places.append(p)
        n = len(self._places)
        self._by_id = {p["id"]: i for i, p in enumerate(self._places)}
        self._cat_up = np.array([str(p["category"] or "").upper() for p in self._places], dtype=object)
        self._valid = np.zeros(n, dtype=bool)
        self._xyz = np.zeros((n, 3))
        for i, p in enumerate(self._places):
            la, lo = _coord(p["lat"]), _coord(p["lng"])
            if la is not None and lo is not None and -90.0 <= la <= 90.0 and -180.0 <= lo <= 180.0:
                self._valid[i] = True
                self._xyz[i] = _unit(la, lo)
        self._xyz.flags.writeable = False
        self._fold_name = [_fold(p["name"]) for p in self._places]
        self._fold_addr = [_fold(p["address"]) for p in self._places]
        self._subsets: Dict[Optional[frozenset], Tuple[Any, np.ndarray, np.ndarray]] = {}
        self._lock = threading.Lock()
        self._tree_disabled = cKDTree is None
        self._fallback_queries = 0

    # ── nạp từ SQLite (chỉ đọc) ─────────────────────────────────────────────
    @classmethod
    def load(cls, db_path: str) -> "PlaceIndex":
        path = Path(db_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Không tìm thấy travel_db.db tại: {path}")
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            rows = conn.execute(f"SELECT {_COLS} FROM places ORDER BY id").fetchall()
        finally:
            conn.close()
        return cls(rows)

    def __len__(self) -> int:
        return len(self._places)

    def stats(self) -> Dict[str, Any]:
        return {"places": len(self), "with_coords": int(self._valid.sum()),
                "backend": "numpy" if self._tree_disabled else "cKDTree",
                "numpy_fallback_queries": self._fallback_queries, "subsets_cached": len(self._subsets)}

    # ── tra cứu theo id / từ khóa ──────────────────────────────────────────
    def get(self, place_id: Any) -> Optional[Dict[str, Any]]:
        i = self._by_id.get(place_id)
        return dict(self._places[i]) if i is not None else None

    def search_keyword(self, kw: str, limit: int) -> List[Dict[str, Any]]:
        """
        Thay `WHERE name LIKE %kw% OR address LIKE %kw% LIMIT ?`; thứ tự theo id như bản SQL cũ.
        Khác SQLite LIKE (chỉ gấp hoa/thường ASCII): ở đây gấp cả dấu tiếng Việt => khớp NHIỀU hơn.
        """
        fk = _fold(kw)
        if not fk or limit <= 0:
            return []
        out: List[Dict[str, Any]] = []
        for i in range(len(self._places)):
            if fk in self._fold_name[i] or fk in self._fold_addr[i]:
                out.append(dict(self._places[i]))
                if len(out) >= limit:
                    break
        return out

    # ── k-NN ────────────────────────────────────────────────────────────────
    def _subset(self, cats: Optional[frozenset]) -> Tuple[Any, np.ndarray, np.ndarray]:
        s = self._subsets.get(cats)
        if s is not None:
            return s
        with self._lock:
            s = self._subsets.get(cats)
            if s is None:
                mask = self._valid.copy()
                if cats:
                    mask &= np.isin(self._cat_up, list(cats))
                sub = np.flatnonzero(mask)
                sub_xyz = self._xyz[sub]
                tree = None
                if cKDTree is not None and not self._tree_disabled and len(sub):
                    try:
                        tree = cKDTree(sub_xyz)
                    except Exception as e:
                        logger.warning("Dựng cKDTree lỗi (%s) -> dùng NumPy", type(e).__name__)
                s = (tree, sub, sub_xyz)
                self._subsets[cats] = s
        return s

    def _query(self, tree: Any, sub_xyz: np.ndarray, q: np.ndarray, kk: int, cap: float):
        """Trả (chord[], pos[]) tăng dần theo chord. cKDTree -> NumPy khi có sự cố."""
        if tree is not None and not self._tree_disabled:
            try:
                d, p = tree.query(q, k=kk, distance_upper_bound=cap)
                return np.atleast_1d(d), np.atleast_1d(p)
            except Exception as e:
                self._tree_disabled = True              # vô hiệu hóa cây cho tới khi reload
                logger.error("cKDTree.query lỗi (%s) -> chuyển vĩnh viễn sang NumPy", type(e).__name__)
        self._fallback_queries += 1
        chord = np.linalg.norm(sub_xyz - q, axis=1)
        order = np.argsort(chord, kind="stable")[:kk]
        return chord[order], order

    def nearest(self, lat: float, lng: float, *, k: int = 5, categories: Optional[Iterable[str]] = None,
                max_km: Optional[float] = None, exclude_ids: Iterable[Any] = ()) -> List[Tuple[float, Dict[str, Any]]]:
        """k địa điểm gần nhất [(km, place_copy)], tăng dần theo khoảng cách đại cầu."""
        la, lo = _coord(lat), _coord(lng)
        if k <= 0 or la is None or lo is None or not (-90.0 <= la <= 90.0 and -180.0 <= lo <= 180.0):
            return []
        cats = frozenset(str(c).upper() for c in categories) if categories else None
        tree, sub, sub_xyz = self._subset(cats)
        excl = set(exclude_ids)
        kk = min(len(sub), k + len(excl))
        if kk <= 0:
            return []
        cap = float("inf") if max_km is None else _km_to_chord(max(0.0, max_km))
        dist, pos = self._query(tree, sub_xyz, _unit(la, lo), kk, cap)
        out: List[Tuple[float, Dict[str, Any]]] = []
        for ch, p in zip(dist, pos):
            if not math.isfinite(ch) or ch > cap:
                break
            i = int(sub[int(p)])
            if self._places[i]["id"] in excl:
                continue
            km = _chord_to_km(float(ch))
            if max_km is not None and km > max_km + 1e-6:
                continue
            out.append((km, dict(self._places[i])))
            if len(out) >= k:
                break
        return out

    def nearest_hotel(self, lat: float, lng: float, exclude_id: Any = None) -> Optional[Dict[str, Any]]:
        r = self.nearest(lat, lng, k=1, categories=("HOTEL",),
                         exclude_ids=() if exclude_id is None else (exclude_id,))
        return r[0][1] if r else None


# ── Singleton (nạp trong lifespan; nạp lười cho test/CLI) ───────────────────
_INDEX: Optional[PlaceIndex] = None
_INDEX_LOCK = threading.Lock()


def default_db_path() -> str:
    env = os.getenv("TRAVEL_DB_PATH")
    return env if env else str(Path(__file__).resolve().parents[2] / "travel_db.db")


def set_index(idx: Optional[PlaceIndex]) -> None:
    global _INDEX
    _INDEX = idx


def load_from_db(db_path: Optional[str] = None, set_global: bool = True) -> PlaceIndex:
    """Gọi trong FastAPI lifespan:  place_index.load_from_db()  (đọc TRAVEL_DB_PATH nếu không truyền đường dẫn)."""
    import time
    t = time.perf_counter()
    idx = PlaceIndex.load(db_path or default_db_path())
    if set_global:
        set_index(idx)
    logger.info("PlaceIndex nạp %d địa điểm (%d có tọa độ) trong %.1f ms, backend=%s",
                len(idx), idx.stats()["with_coords"], (time.perf_counter() - t) * 1000, idx.stats()["backend"])
    return idx


def get_index() -> PlaceIndex:
    global _INDEX
    if _INDEX is None:
        with _INDEX_LOCK:
            if _INDEX is None:
                _INDEX = PlaceIndex.load(default_db_path())
    return _INDEX


def fill_gaps(current_places: List[Dict[str, Any]], target_count: int = 3,
              index: Optional[PlaceIndex] = None, radius_km: float = 25.0) -> List[Dict[str, Any]]:
    """Thay fill_gaps_from_db: tham chiếu = điểm đầu tiên, bán kính 25 km, 4 category, loại các id đã có."""
    if len(current_places) >= target_count or not current_places:
        return current_places
    ref = current_places[0]
    hits = (index or get_index()).nearest(
        ref["lat"], ref["lng"], k=target_count - len(current_places), categories=FILL_CATEGORIES,
        max_km=radius_km, exclude_ids={p["id"] for p in current_places})
    filled = current_places.copy()
    filled.extend(p for _, p in hits)
    return filled


# ── Self-test & benchmark (không cần DB) ────────────────────────────────────
def _synthetic(n: int = 1369, seed: int = 7) -> List[Tuple]:
    import random
    random.seed(seed)
    cats = ["RESTAURANT", "ATTRACTION", "MARKET", "ACTIVITY", "HOTEL", "CAFE"]
    centers = [(21.03, 105.85), (16.05, 108.2), (10.78, 106.7), (12.24, 109.19), (22.33, 103.84), (11.94, 108.44)]
    rows = []
    for i in range(1, n + 1):
        c = random.choice(centers)
        name = f"Phở Bò Hà Nội {i}" if i % 7 == 0 else f"Quán {i}"
        addr = f"Phố {i}, Đà Nẵng" if i % 11 == 0 else f"{i} Đường X"
        rows.append((i, name, random.choice(cats), c[0] + random.gauss(0, .15), c[1] + random.gauss(0, .15),
                     addr, 4.0, "$", "{}", "", "", "", "", "1 giờ", f"P{i}"))
    return rows


def _hav(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    dlat, dlng = math.radians(b[0] - a[0]), math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.sin(dlng / 2) ** 2
    return R_KM * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def _reference(rows, lat, lng, k, cats, max_km, excl):
    c = []
    for r in rows:
        if r[0] in excl or (cats and r[2].upper() not in cats):
            continue
        d = _hav((lat, lng), (r[3], r[4]))
        if max_km is None or d <= max_km:
            c.append((d, r[0]))
    c.sort()
    return [i for _, i in c[:k]]


def selftest() -> None:
    import random
    import sqlite3 as sq
    import tempfile
    rows = _synthetic()
    idx = PlaceIndex(rows)
    idx_np = PlaceIndex(rows)
    idx_np._tree_disabled = True
    random.seed(1)
    cat_opts = [None, ("HOTEL",), FILL_CATEGORIES, ("restaurant", "market")]
    for backend, ix in (("cKDTree", idx), ("numpy", idx_np)):
        bad = 0
        for _ in range(600):
            b = random.choice(rows)
            lat, lng = b[3] + random.uniform(-.05, .05), b[4] + random.uniform(-.05, .05)
            k, cats, mk = random.choice([1, 3, 8]), random.choice(cat_opts), random.choice([None, 5.0, 25.0])
            excl = {b[0]} if random.random() < .5 else set()
            want = _reference(rows, lat, lng, k, {c.upper() for c in cats} if cats else None, mk, excl)
            got = [p["id"] for _, p in ix.nearest(lat, lng, k=k, categories=cats, max_km=mk, exclude_ids=excl)]
            bad += want != got
        assert bad == 0, f"{backend}: {bad}/600 truy vấn lệch haversine brute-force"
        print(f"[{backend}] 600 truy vấn khớp haversine brute-force: OK")

    class _Boom:                                     # mô phỏng cKDTree hỏng lúc chạy
        def query(self, *a, **k):
            raise RuntimeError("boom")
    ix = PlaceIndex(rows)
    t, sub, xyz = ix._subset(None)
    ix._subsets[None] = (_Boom(), sub, xyz)
    ref = [p["id"] for _, p in idx.nearest(21.03, 105.85, k=5)]
    got = [p["id"] for _, p in ix.nearest(21.03, 105.85, k=5)]
    assert got == ref and ix._tree_disabled and ix.stats()["backend"] == "numpy", "fallback"
    print("[fallback] cKDTree.query ném lỗi -> NumPy trả cùng kết quả, cây bị vô hiệu hóa: OK")

    cur = [{"id": rows[0][0], "lat": rows[0][3], "lng": rows[0][4]}]
    res = fill_gaps(cur, 3, idx)
    for p in res:
        p["suggested_time"] = "X"
    assert not any("suggested_time" in p for p in fill_gaps(cur, 3, idx)[1:]) and "suggested_time" not in idx.get(1)
    assert idx.get(1) is not idx.get(1)
    print("[copy] sửa dict trả về không làm bẩn chỉ mục: OK")

    for q in ("ha noi", "HÀ NỘI", "hà  nội", "Pho Bo", "phở bò", "da nang", "ĐÀ NẴNG", "đà nẵng"):
        assert len(idx.search_keyword(q, 10_000)) > 0, q
    assert len(idx.search_keyword("ha noi", 10_000)) == len(idx.search_keyword("HÀ NỘI", 10_000)) > 0
    assert idx.search_keyword("", 5) == [] and idx.search_keyword("ha noi", 0) == []
    print("[keyword] không dấu / hoa-thường / khoảng trắng: OK")

    assert idx.nearest(float("nan"), 105, k=3) == [] and idx.nearest(21, 105, k=0) == []
    assert PlaceIndex([]).nearest(21, 105) == [] and PlaceIndex([]).nearest_hotel(21, 105) is None
    bad_rows = rows[:3] + [(9999, "X", "HOTEL", None, 105.0, "", 0, "", "", "", "", "", "", "", "P")]
    assert PlaceIndex(bad_rows).stats()["with_coords"] == 3
    try:
        PlaceIndex([(1, "x", "c", 1.0, 1.0, [], 0, "", "", "", "", "", "", "", "")])
        raise AssertionError("phải từ chối giá trị list")
    except TypeError:
        pass
    print("[biên] NaN, k=0, rỗng, tọa độ None, giá trị mutable: OK")

    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "t.db")
        c = sq.connect(db)
        c.execute("CREATE TABLE places(id INTEGER PRIMARY KEY, name TEXT, category TEXT, lat REAL, lng REAL, address TEXT, "
                  "rating REAL, price_range TEXT, prices TEXT, phone_number TEXT, website TEXT, image_url TEXT, "
                  "google_maps_url TEXT, typical_time_spent TEXT, google_place_id TEXT)")
        c.executemany("INSERT INTO places VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        c.commit(); c.close()
        li = load_from_db(db, set_global=False)
        assert len(li) == len(rows) and li.get(5)["name"] == "Quán 5"
        try:
            load_from_db(os.path.join(d, "khong_co.db"), set_global=False)
            raise AssertionError("phải báo thiếu file")
        except FileNotFoundError:
            pass
    print("[load_from_db] nạp SQLite chỉ-đọc + báo lỗi thiếu file: OK")
    print("selftest OK")


def bench() -> None:
    import statistics
    import time
    rows = _synthetic()
    t = time.perf_counter(); idx = PlaceIndex(rows); build = (time.perf_counter() - t) * 1000
    idx_np = PlaceIndex(rows); idx_np._tree_disabled = True
    qs = [[{"id": r[0], "lat": r[3], "lng": r[4]}] for r in rows[:400]]
    print(f"{len(rows)} điểm, dựng chỉ mục {build:.1f} ms (backend={idx.stats()['backend']})")
    for name, ix in (("cKDTree", idx), ("numpy", idx_np)):
        ix.nearest(21, 105, k=1, categories=FILL_CATEGORIES)          # làm nóng + dựng cây
        ts = []
        for cur in qs:
            t = time.perf_counter(); fill_gaps(cur, 3, ix); ts.append((time.perf_counter() - t) * 1e6)
        ts.sort()
        print(f"  {name:8s} fill_gaps: median {statistics.median(ts):6.1f} µs   p95 {ts[int(.95 * len(ts)) - 1]:6.1f} µs")


if __name__ == "__main__":
    import sys
    if "--test" in sys.argv:
        selftest()
    elif "--bench" in sys.argv:
        bench()
    else:
        print(__doc__)
