"""
app/services/polyline_codec.py — thuần stdlib (math/json/gzip), không numpy/scipy.

  decode_polyline(s)            -> [[lat, lng], ...]   Google/Goong polyline, precision 5; chuỗi hỏng -> []
  encode_polyline(points)       -> str                 ~5-6 byte/đỉnh (JSON mảng ~24 byte/đỉnh)
  rdp_simplify(points, eps_m)   -> [[lat, lng], ...]   Ramer-Douglas-Peucker, ε tính bằng MÉT
  adaptive_epsilon_m(points)    -> float               ε ≈ 0.75 px ở mức zoom fitBounds

RDP: khoảng cách tới ĐOẠN (không phải đường thẳng vô hạn), lặp bằng stack (không đệ quy),
luôn giữ đỉnh đầu/cuối => simplify TỪNG LEG rồi nối thì mọi waypoint được giữ nguyên.
Bảo đảm: mọi đỉnh bị loại cách đường kết quả ≤ eps_m (trong phép chiếu equirectangular).

Chạy:  python -m app.services.polyline_codec --test
       python -m app.services.polyline_codec --bench [data/map_cache]
"""
from __future__ import annotations

import math
from typing import List, Sequence

_R_M = 6_371_000.0
Point = Sequence[float]


# ── Decode / Encode (precision 5) ───────────────────────────────────────────
def decode_polyline(encoded: str, precision: int = 5) -> List[List[float]]:
    if not encoded:
        return []
    f = 10 ** precision
    out: List[List[float]] = []
    i, n, lat, lng = 0, len(encoded), 0, 0
    try:
        while i < n:
            for axis in (0, 1):
                shift = result = 0
                while True:
                    b = ord(encoded[i]) - 63
                    i += 1
                    result |= (b & 0x1F) << shift
                    shift += 5
                    if b < 0x20:
                        break
                d = ~(result >> 1) if result & 1 else result >> 1
                if axis == 0:
                    lat += d
                else:
                    lng += d
            out.append([round(lat / f, 6), round(lng / f, 6)])
    except IndexError:                      # chuỗi bị cắt cụt
        return []
    return out


def _enc(v: int, buf: List[str]) -> None:
    v <<= 1
    if v < 0:
        v = ~v
    while v >= 0x20:
        buf.append(chr((0x20 | (v & 0x1F)) + 63))
        v >>= 5
    buf.append(chr(v + 63))


def encode_polyline(points: Sequence[Point], precision: int = 5) -> str:
    f = 10 ** precision
    buf: List[str] = []
    plat = plng = 0
    for lat, lng in points:
        a, b = int(round(lat * f)), int(round(lng * f))
        _enc(a - plat, buf)
        _enc(b - plng, buf)
        plat, plng = a, b
    return "".join(buf)


# ── Ramer–Douglas–Peucker ────────────────────────────────────────────────────
def rdp_simplify(points: Sequence[Point], epsilon_m: float) -> List[List[float]]:
    n = len(points)
    if n < 3 or epsilon_m <= 0:
        return [list(p) for p in points]
    lat0 = math.radians(sum(p[0] for p in points) / n)          # chiếu equirectangular quanh vĩ độ TB
    kx, ky = math.radians(1.0) * _R_M * math.cos(lat0), math.radians(1.0) * _R_M
    xs = [p[1] * kx for p in points]
    ys = [p[0] * ky for p in points]
    eps2 = epsilon_m * epsilon_m
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        s, e = stack.pop()
        if e - s < 2:
            continue
        ax, ay, dx, dy = xs[s], ys[s], xs[e] - xs[s], ys[e] - ys[s]
        den = dx * dx + dy * dy
        best, bi = -1.0, -1
        for i in range(s + 1, e):
            px, py = xs[i] - ax, ys[i] - ay
            if den == 0.0:
                d2 = px * px + py * py
            else:
                t = (px * dx + py * dy) / den
                t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
                qx, qy = px - t * dx, py - t * dy
                d2 = qx * qx + qy * qy
            if d2 > best:
                best, bi = d2, i
        if best > eps2:
            keep[bi] = True
            stack.append((s, bi))
            stack.append((bi, e))
    return [list(points[i]) for i in range(n) if keep[i]]


def adaptive_epsilon_m(points: Sequence[Point], px_tolerance: float = 0.75, fit_px: int = 800) -> float:
    """ε ≈ px_tolerance pixel ở zoom mà fitBounds sẽ chọn; kẹp trong [5, 60] m."""
    if len(points) < 3:
        return 0.0
    span = max(max(p[0] for p in points) - min(p[0] for p in points),
               max(p[1] for p in points) - min(p[1] for p in points), 1e-6) * 111_320.0
    return min(max(span / fit_px * px_tolerance, 5.0), 60.0)


# ── Test & benchmark nhanh ───────────────────────────────────────────────────
def _walk(n: int = 800, seed: int = 1) -> List[List[float]]:
    import random
    random.seed(seed)
    lat, lng, h, pts = 21.0, 105.8, 0.0, []
    for _ in range(n):
        h += random.gauss(0, 0.25)
        lat += 0.0002 * math.cos(h)
        lng += 0.0002 * math.sin(h)
        pts.append([round(lat, 5), round(lng, 5)])
    return pts


def _seg_dist_m(p: Point, poly: Sequence[Point]) -> float:
    kx, ky = 111_320 * math.cos(math.radians(p[0])), 110_540.0
    best = 1e18
    for a, b in zip(poly, poly[1:]):
        ax, ay, bx, by, px, py = a[1] * kx, a[0] * ky, b[1] * kx, b[0] * ky, p[1] * kx, p[0] * ky
        dx, dy = bx - ax, by - ay
        d2 = dx * dx + dy * dy
        t = 0.0 if d2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / d2))
        best = min(best, math.hypot(px - ax - t * dx, py - ay - t * dy))
    return best


def selftest() -> None:
    pts = _walk()
    assert decode_polyline(encode_polyline(pts)) == pts, "roundtrip"
    assert decode_polyline("") == [] and decode_polyline("_p~iF~ps|U_ulL") == [], "chuỗi rỗng/cụt"
    assert decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@") == [[38.5, -120.2], [40.7, -120.95], [43.252, -126.453]], "vector chuẩn Google"
    assert rdp_simplify(pts[:2], 10) == pts[:2] and rdp_simplify(pts, 0) == pts, "biên n<3, eps<=0"
    assert rdp_simplify([[1, 1]] * 5 + [[1, 1.001]], 5)[-1] == [1, 1.001], "điểm trùng/đoạn suy biến"
    for eps in (3, 10, 30):
        s = rdp_simplify(pts, eps)
        worst = max(_seg_dist_m(p, s) for p in pts)
        assert s[0] == pts[0] and s[-1] == pts[-1] and worst <= eps * 1.02, (eps, worst)
        print(f"ε={eps:>2} m: {len(pts)} -> {len(s):>3} đỉnh ({len(s)/len(pts):.0%}), sai lệch tối đa thực đo {worst:.1f} m")
    print("selftest OK")


def bench(cache_dir: str = "") -> None:
    import glob, gzip, json, os, time
    legs = []
    for f in glob.glob(os.path.join(cache_dir, "dir_*.json")) if cache_dir else []:
        try:
            d = json.load(open(f, encoding="utf-8"))
            if d.get("success") and len(d.get("polyline", [])) >= 3:
                legs.append(d["polyline"])
        except Exception:
            pass
    src = f"{len(legs)} leg thật từ {cache_dir}" if legs else "dữ liệu TỔNG HỢP (không có cache thật)"
    legs = legs or [_walk(800, s) for s in range(20)]
    tot = sum(map(len, legs))
    print(f"{src}: {tot} đỉnh, TB {tot/len(legs):.0f}/leg\n{'ε(m)':>5} {'giữ':>6} {'JSON':>8} {'JSON+gz':>8} {'enc':>7} {'enc+gz':>7} {'ms/leg':>7}")

    def sz(P):
        j = json.dumps(P, separators=(",", ":")).encode()
        e = json.dumps([encode_polyline(p) for p in P], separators=(",", ":")).encode()
        return len(j), len(gzip.compress(j)), len(e), len(gzip.compress(e))
    b = sz(legs)
    print(f"{'raw':>5} {'100%':>6} {b[0]:8d} {b[1]:8d} {b[2]:7d} {b[3]:7d}")
    for eps in (3, 5, 10, 15, 25, 50):
        t = time.perf_counter()
        S = [rdp_simplify(p, eps) for p in legs]
        ms = (time.perf_counter() - t) * 1000 / len(legs)
        s = sz(S)
        print(f"{eps:5d} {sum(map(len, S))/tot:6.0%} {s[0]:8d} {s[1]:8d} {s[2]:7d} {s[3]:7d} {ms:7.2f}")


if __name__ == "__main__":
    import sys
    if "--test" in sys.argv:
        selftest()
    elif "--bench" in sys.argv:
        i = sys.argv.index("--bench")
        bench(sys.argv[i + 1] if len(sys.argv) > i + 1 else "")
    else:
        print(__doc__)
