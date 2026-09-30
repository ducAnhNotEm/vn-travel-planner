import math
import sqlite3
import json
import re
import os
from typing import List, Dict, Any, Tuple, Optional, Union

# ==============================================================================
# 0. IN-MEMORY CACHE CHO GIỜ MỞ CỬA CRAWLED GOOGLE PLACES
# ==============================================================================
_OPENING_HOURS_CACHE: Optional[Dict[str, Any]] = None

def _get_opening_hours_cache() -> Dict[str, Any]:
    global _OPENING_HOURS_CACHE
    if _OPENING_HOURS_CACHE is not None:
        return _OPENING_HOURS_CACHE
    cache = {}
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cache_files = [
        os.path.join(base_dir, "data", "crawled_google_places_cache.json"),
        os.path.join(base_dir, "data", "crawled_major_cities_cache.json")
    ]
    for fn in cache_files:
        if os.path.exists(fn):
            try:
                with open(fn, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for item in data:
                            pid = item.get("placeId")
                            if pid and "openingHours" in item and item["openingHours"]:
                                cache[pid] = item["openingHours"]
            except Exception:
                pass
    _OPENING_HOURS_CACHE = cache
    return _OPENING_HOURS_CACHE

# ==============================================================================
# 1. CÔNG THỨC HAVERSINE & MA TRẬN ĐỊA HÌNH VIỆT NAM (K_TOPO, V_AVG)
# ==============================================================================
def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0  # Bán kính Trái Đất (km)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def get_terrain_factor(province: Any = None, category: Optional[str] = None) -> float:
    """
    Trả về Hệ số Uốn lượn Địa hình (K_topo):
    - Đèo dốc Vùng cao / Tây Bắc / Tây Nguyên: 1.75 (V_avg = 30-40 km/h)
    - Duyên hải / Bán sơn địa / Đồi thấp: 1.35 (V_avg = 55-65 km/h)
    - Đồng bằng / Đô thị lớn / Cao tốc: 1.25 (V_avg = 70-90 km/h)
    """
    if province is not None:
        p_str = str(province).strip().lower()
        if any(k in p_str for k in [
            "hà giang", "lào cai", "sa pa", "sapa", "mộc châu", "sơn la", "lai châu",
            "điện biên", "cao bằng", "yên bái", "lâm đồng", "đà lạt", "đắk lắk",
            "buôn ma thuột", "gia lai", "kon tum", "đắk nông", "bắc kạn"
        ]):
            return 1.75
        if any(k in p_str for k in [
            "thanh hóa", "nghệ an", "hà tĩnh", "quảng bình", "quảng trị", "huế",
            "thừa thiên", "đà nẵng", "quảng nam", "hội an", "quảng ngãi", "bình định",
            "quy nhơn", "phú yên", "khánh hòa", "nha trang", "ninh thuận", "bình thuận",
            "phan thiết", "vũng tàu", "bà rịa", "kiên giang", "phú quốc", "quảng ninh",
            "hạ long", "hải phòng", "cát bà"
        ]):
            return 1.35
    return 1.25

def get_terrain_parameters(places: List[Dict[str, Any]]) -> Tuple[float, float]:
    """
    Nhận diện địa hình của cụm địa điểm trong ngày và trả về (K_topo, V_avg).
    """
    if not places:
        return 1.25, 45.0
    full_text = " ".join([
        f"{p.get('name', '')} {p.get('address', '')} {p.get('province', '')} {p.get('category', '')}"
        for p in places
    ]).lower()

    if any(k in full_text for k in [
        "đà lạt", "sa pa", "sapa", "mộc châu", "tam đảo", "hà giang", "đèo", "thác", "núi",
        "đỉnh", "buôn ma thuột", "pleiku", "fansipan", "mã pí lèng", "yên bái", "cao bằng",
        "lâm đồng", "lào cai", "sơn la", "điện biên", "lai châu", "kon tum", "gia lai"
    ]):
        return 1.75, 35.0

    if any(k in full_text for k in [
        "biển", "bãi tắm", "bãi biển", "mỹ khê", "sầm sơn", "cửa lò", "nha trang", "hòn", "vịnh",
        "hạ long", "vân đồn", "cát bà", "đồ sơn", "quy nhơn", "phú quốc", "côn đảo", "beach",
        "đà nẵng", "khánh hòa", "bình định", "quảng ninh", "kiên giang", "thanh hóa", "nghệ an",
        "vũng tàu", "bình thuận", "phan thiết"
    ]):
        return 1.35, 55.0

    return 1.25, 45.0

def compute_travel_time(
    lat1: float,
    lng1: float,
    lat2: float,
    lng2: float,
    k_topo: float = 1.25,
    v_avg: float = 45.0
) -> int:
    """
    Tính thời gian di chuyển làm tròn phút nguyên theo mục 2.2 SPEC-TSPTW:
    T_ij = ceil((D_haversine * K_topo / V_avg) * 60)
    Cự ly < 500m có thời gian tối thiểu 3 phút (thời gian lên/xuống xe).
    """
    d_hav = haversine_distance(lat1, lng1, lat2, lng2)
    if d_hav < 0.001:
        return 0
    if d_hav < 0.5:
        return 3
    d_road = d_hav * k_topo
    time_min = (d_road / max(1.0, v_avg)) * 60.0
    return max(3, math.ceil(time_min))

# ==============================================================================
# 2. XỬ LÝ DWELL TIME & KHUNG GIỜ HOẠT ĐỘNG (OPERATING HOURS RESOLUTION)
# ==============================================================================
def parse_dwell_time(typical_time_spent: Optional[str], category: str = "ATTRACTION") -> int:
    """
    Chuyển đổi typical_time_spent sang số phút nguyên theo chuẩn Mục 3.2 & 3.3 SPEC-TSPTW.
    """
    cat = str(category).upper() if category else "ATTRACTION"
    cat_fallback = {
        "TEMPLE": 90,
        "HISTORICAL_SITE": 90,
        "MUSEUM": 90,
        "RESTAURANT": 75,
        "SEAFOOD_RESTAURANT": 75,
        "SPECIALTY_FOOD": 75,
        "HOTEL": 105,
        "MARKET": 60,
        "NIGHT_MARKET": 60,
        "ATTRACTION": 60,
        "ACTIVITY": 75,
        "CAFE": 45
    }
    if not typical_time_spent:
        return cat_fallback.get(cat, 60)

    val = str(typical_time_spent).strip().lower()
    if any(k in val for k in ["overnight", "lưu trú", "nghỉ đêm"]):
        return 105

    # 1h - 2h, 1 - 2 giờ, 1h-2h
    m_h_range = re.search(r'(\d+(?:\.\d+)?)\s*(?:h|giờ)?\s*(?:-|đến|to)\s*(\d+(?:\.\d+)?)\s*(?:giờ|h)', val)
    if m_h_range:
        h1 = float(m_h_range.group(1))
        h2 = float(m_h_range.group(2))
        return int((h1 + h2) / 2.0 * 60)

    # 30 phút - 1 giờ
    m_min_hr = re.search(r'(\d+)\s*(?:phút|ph|min).*?(\d+)\s*(?:giờ|h)', val)
    if m_min_hr:
        m1 = float(m_min_hr.group(1))
        m2 = float(m_min_hr.group(2)) * 60.0
        return int((m1 + m2) / 2.0)

    # 30 - 45 phút
    m_min_range = re.search(r'(\d+)\s*(?:phút|ph|min)?\s*(?:-|đến|to)\s*(\d+)\s*(?:phút|ph|min)', val)
    if m_min_range:
        return int((int(m_min_range.group(1)) + int(m_min_range.group(2))) / 2.0)

    # N giờ / N h
    m_h = re.search(r'(\d+(?:\.\d+)?)\s*(?:giờ|h\b|hour)', val)
    if m_h:
        return int(float(m_h.group(1)) * 60)

    # N phút
    m_m = re.search(r'(\d+)\s*(?:phút|ph|min|pht|phut|phát)', val)
    if m_m:
        return int(m_m.group(1))

    m_any = re.search(r'(\d+)', val)
    if m_any:
        n = int(m_any.group(1))
        return n * 60 if n <= 6 else n

    return cat_fallback.get(cat, 60)

def parse_time_str(t_str: str) -> int:
    """Chuyển chuỗi HH:MM hoặc H:MM thành số phút từ nửa đêm."""
    if not t_str:
        return 0
    t_clean = str(t_str).strip().lower()
    m = re.match(r'(\d{1,2})(?:[:h](\d{2}))?', t_clean)
    if not m:
        return 0
    h = int(m.group(1))
    m_val = int(m.group(2)) if m.group(2) else 0
    return (h * 60 + m_val) % 1440

def format_time_hhmm(minutes: int) -> str:
    """Chuyển số phút từ nửa đêm thành chuỗi định dạng HH:MM."""
    minutes = max(0, minutes) % 1440
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"

def parse_working_hours(hours_str: str) -> List[Tuple[int, int]]:
    """
    Phân tích cú pháp giờ mở cửa thành danh sách các khoảng [(open_min, close_min)].
    Hỗ trợ nhiều ca (ví dụ: '07:30 to 11:30, 13:30 to 17:30') và mở cả ngày.
    """
    if not hours_str:
        return []
    s = hours_str.strip().lower()
    if any(k in s for k in ['cả ngày', '24/7', '24 hours', '24/24', 'suốt ngày']):
        return [(0, 1440)]

    segments = re.split(r'[,;\n]+', hours_str)
    intervals = []
    pattern = re.compile(r'(\d{1,2}(?:[:h]\d{2})?)\s*(?:to|-|đến)\s*(\d{1,2}(?:[:h]\d{2})?)', re.IGNORECASE)

    for seg in segments:
        matches = pattern.findall(seg)
        for t1, t2 in matches:
            o = parse_time_str(t1)
            c = parse_time_str(t2)
            if c <= o:
                if c == 0 or c <= 180:
                    c = 1440
            if o < c:
                intervals.append((o, c))
    return intervals

def resolve_place_working_hours(
    place: Dict[str, Any],
    day_of_week: str = "Monday"
) -> List[Tuple[int, int]]:
    """
    Xác định các khoảng mở cửa hợp lệ của một địa điểm từ working_hours,
    openingHours, Google Places Cache hoặc Heuristic Fallback danh mục.
    """
    cat = str(place.get("category", "ATTRACTION")).upper()
    name = str(place.get("name", "")).lower()

    # 1. Thuộc tính trực tiếp working_hours
    wh = place.get("working_hours")
    if wh:
        if isinstance(wh, list):
            res = []
            for item in wh:
                if isinstance(item, tuple) and len(item) == 2:
                    res.append(item)
                elif isinstance(item, str):
                    res.extend(parse_working_hours(item))
            if res:
                return _apply_category_meal_window(res, cat)
        elif isinstance(wh, str):
            res = parse_working_hours(wh)
            if res:
                return _apply_category_meal_window(res, cat)

    # 2. Thuộc tính trực tiếp openingHours
    oh = place.get("openingHours")
    if oh:
        res = _parse_opening_hours_list(oh, day_of_week)
        if res:
            return _apply_category_meal_window(res, cat)

    # 3. Tra cứu cache Google Places theo google_place_id
    cache = _get_opening_hours_cache()
    g_pid = place.get("google_place_id") or place.get("source_place_id")
    if g_pid and g_pid in cache:
        res = _parse_opening_hours_list(cache[g_pid], day_of_week)
        if res:
            return _apply_category_meal_window(res, cat)

    # 4. Fallback heuristics theo loại hình và tên
    if "đêm" in name or "night" in name or cat == "NIGHT_MARKET":
        return [(1050, 1425)]  # 17:30 - 23:45
    if cat == "MARKET":
        return [(360, 1140)]   # 06:00 - 19:00
    if cat in ["TEMPLE", "HISTORICAL_SITE", "MUSEUM"]:
        if any(k in name for k in ["chùa", "đền", "quán sứ", "miếu"]):
            return [(450, 690), (810, 1050)]  # 07:30 - 11:30, 13:30 - 17:30 (Nghỉ trưa)
        return [(480, 1020)]  # 08:00 - 17:00
    if cat in ["RESTAURANT", "SEAFOOD_RESTAURANT", "SPECIALTY_FOOD"]:
        return [(690, 840), (1080, 1320)]  # 11:30 - 14:00, 18:00 - 22:00
    if cat == "HOTEL":
        return [(0, 1440)]
    if cat == "CAFE":
        return [(420, 1320)]  # 07:00 - 22:00
    if cat in ["ATTRACTION", "ACTIVITY"]:
        return [(480, 1080)]  # 08:00 - 18:00

    return [(480, 1200)]  # 08:00 - 20:00

def _parse_opening_hours_list(oh_data: Any, day_of_week: str) -> List[Tuple[int, int]]:
    if isinstance(oh_data, str):
        return parse_working_hours(oh_data)
    if isinstance(oh_data, list):
        for item in oh_data:
            if isinstance(item, dict) and "hours" in item:
                h_str = item["hours"]
                parsed = parse_working_hours(h_str)
                if parsed:
                    return parsed
    return []

def _apply_category_meal_window(
    intervals: List[Tuple[int, int]],
    category: str
) -> List[Tuple[int, int]]:
    if category not in ["RESTAURANT", "SEAFOOD_RESTAURANT", "SPECIALTY_FOOD"]:
        return intervals

    if len(intervals) >= 2:
        return intervals

    o, c = intervals[0]
    lunch_window = (max(o, 690), min(c, 840))     # 11:30 - 14:00
    dinner_window = (max(o, 1080), min(c, 1320))  # 18:00 - 22:00

    res = []
    if lunch_window[0] < lunch_window[1]:
        res.append(lunch_window)
    if dinner_window[0] < dinner_window[1]:
        res.append(dinner_window)
    return res if res else intervals

def format_intervals_display(intervals: List[Tuple[int, int]]) -> str:
    """Tạo chuỗi hiển thị khung giờ hoạt động cho UI."""
    if not intervals or intervals == [(0, 1440)]:
        return "Mở cửa cả ngày (24/7)"
    parts = []
    for o, c in intervals:
        parts.append(f"{format_time_hhmm(o)} - {format_time_hhmm(c)}")
    return ", ".join(parts)

def evaluate_intervals_for_visit(
    est_arr: int,
    dwell: int,
    intervals: List[Tuple[int, int]]
) -> Tuple[int, int, int, Tuple[int, int], int]:
    """
    Xác định ca tham quan tối ưu nhất trong danh sách các khoảng mở cửa:
    Trả về: (arrival_min, departure_min, wait_time_min, active_interval, lateness_min)
    """
    if not intervals:
        intervals = [(0, 1440)]

    feasible = []
    for (o, c) in intervals:
        arr = max(est_arr, o)
        dep = arr + dwell
        if dep <= c:
            wait = max(0, o - est_arr)
            feasible.append((arr, dep, wait, (o, c), 0))

    if feasible:
        feasible.sort(key=lambda x: (x[0], x[2]))
        return feasible[0]

    candidates = []
    for (o, c) in intervals:
        arr = max(est_arr, o)
        dep = arr + dwell
        lateness = max(0, dep - c)
        wait = max(0, o - est_arr)
        candidates.append((arr, dep, wait, (o, c), lateness))
    candidates.sort(key=lambda x: (x[4], x[0]))
    return candidates[0]

def get_biological_period(arrival_min: int, rhythm_type: str = "urban") -> Tuple[str, str]:
    """Trả về (period_name, period_icon) tương ứng với mốc thời gian đến thực tế."""
    if rhythm_type == "coastal":
        if arrival_min < 450:
            return "Đón bình minh & Tắm sớm", "🌅"
        elif arrival_min < 540:
            return "Ăn sáng đặc sản", "🍜"
        elif arrival_min < 690:
            return "Đi dạo / Check-in mát mẻ", "🚶"
        elif arrival_min < 780:
            return "Ăn trưa hải sản", "🍲"
        elif arrival_min < 960:
            return "Nghỉ trưa tránh nắng (Khách sạn)", "🏨"
        elif arrival_min < 1110:
            return "Ngắm hoàng hôn & Tắm chiều", "🌇"
        elif arrival_min < 1230:
            return "Ăn tối hải sản bờ biển", "🦀"
        else:
            return "Dạo biển đêm / Chợ đêm", "🌊"
    elif rhythm_type == "mountain":
        if arrival_min < 450:
            return "Săn mây & Đón bình minh", "☁️"
        elif arrival_min < 540:
            return "Ăn sáng & Cafe nóng", "☕"
        elif arrival_min < 690:
            return "Thác nước / Trekking / Bản làng", "🚶"
        elif arrival_min < 810:
            return "Ăn trưa gà đồi / Cơm lam", "🍲"
        elif arrival_min < 900:
            return "Nghỉ ngơi homestay", "🏨"
        elif arrival_min < 1110:
            return "Đồi thông / Vườn hoa", "🌸"
        elif arrival_min < 1230:
            return "Tiệc nướng than hoa / Lẩu nóng", "🔥"
        else:
            return "Dạo chợ đêm & Sữa nóng", "🧣"
    else:  # urban / heritage
        if arrival_min < 510:
            return "Ăn sáng đặc sản", "🍜"
        elif arrival_min < 690:
            return "Danh thắng / Di tích sáng mát", "🏛️"
        elif arrival_min < 780:
            return "Ăn trưa đặc sản vùng miền", "🍲"
        elif arrival_min < 885:
            return "Nghỉ trưa tránh nắng", "🏨"
        elif arrival_min < 1035:
            return "Làng nghề / Thuyền sinh thái", "🛶"
        elif arrival_min < 1140:
            return "Cafe view hoàng hôn / Dạo hồ", "☕"
        elif arrival_min < 1245:
            return "Ăn tối nhà hàng đặc sản", "🍲"
        else:
            return "Phố đi bộ / Chợ đêm", "🏮"

# ==============================================================================
# 3. BỘ MÁY MÔ PHỎNG XUÔI DÒNG THỜI GIAN (FORWARD TIME-WINDOW SIMULATION ENGINE)
# ==============================================================================
def simulate_route(
    places: List[Dict[str, Any]],
    start_time_minutes: Optional[int] = None,
    k_topo: Optional[float] = None,
    v_avg: Optional[float] = None
) -> Tuple[List[Dict[str, Any]], bool, float]:
    """
    Mô phỏng chuỗi thời gian xuôi dòng qua từng địa điểm trong ngày:
    - Tính thời gian di chuyển, thời gian chờ mở cửa, thời gian tham quan
    - Thẩm định tính hợp lệ khung giờ và kích hoạt Smart Advisory nếu có xung đột
    """
    if not places:
        return [], True, 0.0

    if k_topo is None or v_avg is None:
        k_topo, v_avg = get_terrain_parameters(places)

    full_text = " ".join([f"{p.get('name', '')} {p.get('address', '')}" for p in places]).lower()
    if any(k in full_text for k in ["biển", "bãi tắm", "bãi biển", "mỹ khê", "nha trang", "hạ long", "phú quốc", "quy nhơn"]):
        rhythm_type = "coastal"
        default_start = 330  # 05:30
    elif any(k in full_text for k in ["đà lạt", "sa pa", "sapa", "mộc châu", "hà giang", "đèo", "thác"]):
        rhythm_type = "mountain"
        default_start = 360  # 06:00
    else:
        rhythm_type = "urban"
        default_start = 480  # 08:00

    if places[0].get("pin_time"):
        default_start = parse_time_str(places[0]["pin_time"])
    elif places[0].get("suggested_time") and places[0].get("is_pinned"):
        default_start = parse_time_str(places[0]["suggested_time"])

    current_time = start_time_minutes if start_time_minutes is not None else default_start

    simulated = []
    all_valid = True
    total_dist = 0.0

    for idx, p in enumerate(places):
        dwell = parse_dwell_time(p.get("typical_time_spent"), p.get("category", "ATTRACTION"))
        intervals = resolve_place_working_hours(p)

        if idx == 0:
            est_arr = current_time
            if p.get("pin_time"):
                est_arr = max(est_arr, parse_time_str(p["pin_time"]))
        else:
            prev = places[idx - 1]
            leg_dist = haversine_distance(prev["lat"], prev["lng"], p["lat"], p["lng"])
            total_dist += leg_dist
            t_leg = compute_travel_time(prev["lat"], prev["lng"], p["lat"], p["lng"], k_topo, v_avg)
            est_arr = current_time + t_leg
            if p.get("pin_time"):
                est_arr = max(est_arr, parse_time_str(p["pin_time"]))

        arr, dep, wait, active_int, lateness = evaluate_intervals_for_visit(est_arr, dwell, intervals)
        is_step_valid = (lateness == 0)
        if not is_step_valid:
            all_valid = False

        advisory = None
        if not is_step_valid:
            close_str = format_time_hhmm(active_int[1])
            arr_str = format_time_hhmm(arr)
            late_m = arr - active_int[1] if arr > active_int[1] else dep - active_int[1]
            p_name = p.get("name", "Địa điểm")
            advisory = (
                f"⚠️ Xung đột thời gian: {p_name} đóng cửa lúc {close_str}, "
                f"nhưng theo lộ trình bạn sẽ đến lúc {arr_str} (quá giờ {late_m} phút). "
                f"Khuyên bạn nên đổi {p_name} lên buổi sáng hoặc chuyển sang ngày khác."
            )

        p_period_name, p_period_icon = get_biological_period(arr, rhythm_type)

        step_dict = p.copy()
        step_dict.update({
            "step": idx + 1,
            "arrival_time": format_time_hhmm(arr),
            "departure_time": format_time_hhmm(dep),
            "suggested_time": format_time_hhmm(arr),
            "time": format_time_hhmm(arr),
            "dwell_time_minutes": dwell,
            "wait_time_minutes": wait,
            "is_time_window_valid": is_step_valid,
            "time_window_display": format_intervals_display(intervals),
            "time_window_advisory": advisory,
            "period_name": p.get("period_name") or p_period_name,
            "period_icon": p.get("period_icon") or p_period_icon,
            "open_time": format_time_hhmm(intervals[0][0]) if intervals else "00:00",
            "close_time": format_time_hhmm(intervals[-1][1]) if intervals else "23:59"
        })

        simulated.append(step_dict)
        current_time = dep

    return simulated, all_valid, round(total_dist, 2)

# ==============================================================================
# 4. GIẢI THUẬT 2-OPT LOCAL SEARCH & HARD TIME-WINDOW TSPTW
# ==============================================================================
def optimize_route(places: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], float]:
    """
    Sắp xếp đường đi ngắn nhất đơn ngày bằng thuật toán 2-Opt Local Search:
    - Loại bỏ triệt để các cung đường cắt chéo chữ X (crossing edges)
    - Tương thích ngược 100% với hàm optimize_route cũ
    """
    if not places:
        return [], 0.0
    if len(places) == 1:
        return places, 0.0

    # Khởi tạo tuyến sơ bộ: Nearest Neighbor xuất phát từ places[0]
    unvisited = places.copy()
    current = unvisited.pop(0)
    route = [current]
    while unvisited:
        nearest = min(
            unvisited,
            key=lambda p: haversine_distance(current["lat"], current["lng"], p["lat"], p["lng"])
        )
        current = nearest
        route.append(current)
        unvisited.remove(nearest)

    # 2-Opt Local Search
    def route_distance(r):
        return sum(haversine_distance(r[k]["lat"], r[k]["lng"], r[k+1]["lat"], r[k+1]["lng"]) for k in range(len(r)-1))

    best_route = route[:]
    best_dist = route_distance(best_route)

    improved = True
    for _ in range(50):
        if not improved:
            break
        improved = False
        n = len(best_route)
        for i in range(1, n - 1):
            for j in range(i + 1, n):
                if any(best_route[k].get("is_pinned") for k in range(i, j + 1)):
                    continue
                cand = best_route[:i] + best_route[i:j+1][::-1] + best_route[j+1:]
                d = route_distance(cand)
                if d < best_dist - 1e-4:
                    best_route = cand
                    best_dist = d
                    improved = True
                    break
            if improved:
                break

    return best_route, round(best_dist, 2)

def solve_day_tsptw_2opt(
    places: List[Dict[str, Any]],
    start_time_str: Optional[str] = None,
    k_topo: Optional[float] = None,
    v_avg: Optional[float] = None,
    max_iterations: int = 50
) -> Tuple[List[Dict[str, Any]], float]:
    """
    Bộ giải TSPTW với 2-Opt Local Search và cơ chế chấp thuận hai cổng:
    - Cổng 1: Giảm cự ly di chuyển hoặc thời gian chờ
    - Cổng 2: Không vi phạm giờ đóng cửa (Close_k) hay giờ nghỉ trưa
    - Thời gian thực thi < 15ms trên CPU cho N <= 10
    """
    if not places:
        return [], 0.0
    if len(places) == 1:
        sim, _, dist = simulate_route(places, parse_time_str(start_time_str) if start_time_str else None, k_topo, v_avg)
        return sim, dist

    if k_topo is None or v_avg is None:
        k_topo, v_avg = get_terrain_parameters(places)

    start_min = parse_time_str(start_time_str) if start_time_str else 480
    n = len(places)

    # Pre-extract dữ liệu để tăng tốc tối đa < 15ms
    dwells = [parse_dwell_time(p.get("typical_time_spent"), p.get("category", "ATTRACTION")) for p in places]
    place_intervals = [resolve_place_working_hours(p) for p in places]
    pin_times = [parse_time_str(p["pin_time"]) if p.get("pin_time") else None for p in places]
    is_pinneds = [bool(p.get("is_pinned")) for p in places]

    # Precompute ma trận khoảng cách và thời gian di chuyển
    dist_mat = [[0.0] * n for _ in range(n)]
    time_mat = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                d = haversine_distance(places[i]["lat"], places[i]["lng"], places[j]["lat"], places[j]["lng"])
                dist_mat[i][j] = d
                if d < 0.001:
                    t = 0
                elif d < 0.5:
                    t = 3
                else:
                    t = max(3, math.ceil((d * k_topo / max(1.0, v_avg)) * 60.0))
                time_mat[i][j] = t

    def _fast_eval(order: List[int]) -> Tuple[float, int, int]:
        total_d = 0.0
        total_l = 0
        total_w = 0
        curr_t = start_min
        for idx, p_idx in enumerate(order):
            dw = dwells[p_idx]
            ints = place_intervals[p_idx]
            pt = pin_times[p_idx]
            if idx == 0:
                est_arr = curr_t
                if pt is not None:
                    est_arr = max(est_arr, pt)
            else:
                prev_idx = order[idx - 1]
                total_d += dist_mat[prev_idx][p_idx]
                est_arr = curr_t + time_mat[prev_idx][p_idx]
                if pt is not None:
                    est_arr = max(est_arr, pt)

            arr, dep, wait, _, lateness = evaluate_intervals_for_visit(est_arr, dw, ints)
            total_l += lateness
            total_w += wait
            curr_t = dep
        return total_d, total_l, total_w

    current_order = list(range(n))
    curr_dist, curr_late, curr_wait = _fast_eval(current_order)

    improved = True
    for _ in range(max_iterations):
        if not improved:
            break
        improved = False
        for i in range(0, n - 1):
            for j in range(i + 1, n):
                if any(is_pinneds[current_order[k]] for k in range(i, j + 1)):
                    continue
                cand_order = current_order[:i] + current_order[i:j+1][::-1] + current_order[j+1:]
                c_dist, c_late, c_wait = _fast_eval(cand_order)

                if c_late < curr_late:
                    current_order = cand_order
                    curr_dist, curr_late, curr_wait = c_dist, c_late, c_wait
                    improved = True
                    break
                elif c_late == 0 and curr_late == 0:
                    if c_dist < curr_dist - 1e-4:
                        current_order = cand_order
                        curr_dist, curr_late, curr_wait = c_dist, c_late, c_wait
                        improved = True
                        break
                    elif abs(c_dist - curr_dist) < 1e-4 and c_wait < curr_wait - 1:
                        current_order = cand_order
                        curr_dist, curr_late, curr_wait = c_dist, c_late, c_wait
                        improved = True
                        break
            if improved:
                break

    final_places = [places[k] for k in current_order]
    final_sim, _, final_dist = simulate_route(final_places, start_min, k_topo, v_avg)
    return final_sim, round(final_dist, 2)


# ==============================================================================
# 3. TÍNH CHI PHÍ DI CHUYỂN TOÀN ĐOÀN VÀ BÌNH QUÂN ĐẦU NGƯỜI
# ==============================================================================
def calculate_transport_cost(distance_km: float, vehicle_type: str = "car", group_size: int = 2) -> Dict[str, Any]:
    """
    Tính chi phí di chuyển chuẩn xác cho cả chuyến đi:
    - Tiền xe/xăng/cầu đường là chi phí chia sẻ cho cả đoàn.
    - Sức chứa: Xe máy 2 người/xe; Ô tô 4-7 chỗ.
    - Tự động chia đều cho từng người trong đoàn (cost_per_person).
    """
    vehicle_type = vehicle_type.lower()
    group_size = max(1, group_size)

    if vehicle_type in ["chartered_van", "tour_bus", "van"]:
        cost = 1000000 + (distance_km * 2500)
        desc = f"Thuê xe du lịch riêng (Xe 7-16 chỗ kèm tài xế & xăng dầu trọn gói)"
    elif vehicle_type == "motorbike":
        motorbikes_count = math.ceil(group_size / 2)
        cost = motorbikes_count * (distance_km * 600 + 10000)
        desc = f"Xe máy cá nhân ({motorbikes_count} xe cho đoàn {group_size} người - ~600đ/km + gửi xe)"
    elif vehicle_type == "taxi":
        if group_size <= 4:
            cost = 12000 + (distance_km * 14000)
            desc = f"Taxi / GrabCar 4 chỗ (~14.000đ/km)"
        else:
            cost = 15000 + (distance_km * 18000)
            desc = f"Taxi / GrabCar 7 chỗ (~18.000đ/km)"
    else:  # 'car' - ô tô cá nhân
        if group_size <= 4:
            cost = (distance_km * 1800) + 30000
            desc = f"Ô tô cá nhân (4-5 chỗ - ~1.800đ/km xăng + phí gửi xe/cầu đường)"
        else:
            cost = (distance_km * 2400) + 50000
            desc = f"Ô tô cá nhân (7 chỗ - ~2.400đ/km xăng + phí gửi xe/cầu đường)"

    total_cost = round(cost, -3)
    per_person = round(total_cost / group_size, -2)

    return {
        "vehicle": desc,
        "distance_km": round(distance_km, 2),
        "total_group_cost_vnd": int(total_cost),
        "cost_per_person_vnd": int(per_person),
        "group_size": group_size,
        "estimated_cost_vnd": int(total_cost)  # Hỗ trợ backward compatibility
    }

# ==============================================================================
# 4. ĐỊNH DẠNG GIÁ TỪ DATABASE THỰC TẾ
# ==============================================================================
def format_place_price(category: str, price_range_db: str, prices_json_db: str) -> Dict[str, Any]:
    category = category.upper() if category else "ATTRACTION"
    
    if price_range_db:
        prices_list = json.loads(prices_json_db) if prices_json_db else []
        return {
            "has_price": True,
            "display": price_range_db,
            "type_label": "Khách sạn / Lưu trú (Giá thực tế từ DB)",
            "providers_count": len(prices_list)
        }
    
    if category in ["RESTAURANT", "SEAFOOD_RESTAURANT", "SPECIALTY_FOOD"]:
        return {
            "has_price": True,
            "display": "Tham khảo: ~100.000 - 300.000 VNĐ / người",
            "type_label": "Nhà hàng / Ăn uống"
        }

    return {
        "has_price": False,
        "display": "Miễn phí vé vào / Tự do tham quan",
        "type_label": "Điểm tham quan / Chợ (Không mất vé)"
    }

# ==============================================================================
# 5. THUẬT TOÁN PHÂN CỤM ĐỊA LÝ ĐA NGÀY (MULTI-DAY CLUSTERING)
# ==============================================================================
def cluster_places_by_days(places: List[Dict[str, Any]], days: int) -> List[List[Dict[str, Any]]]:
    """
    Gom cụm các địa điểm theo K ngày dựa trên tọa độ GPS (Haversine distance).
    Thuần Python 100%, không phụ thuộc thư viện ngoài.
    """
    if days <= 1 or len(places) <= days:
        if days <= 1:
            return [places]
        return [[p] for p in places]

    # Chọn k điểm hạt nhân xa nhau nhất (K-Medoids initialization)
    centers = [places[0]]
    for _ in range(1, days):
        farthest_place = max(
            places,
            key=lambda p: min(haversine_distance(p["lat"], p["lng"], c["lat"], c["lng"]) for c in centers)
        )
        centers.append(farthest_place)

    # Phân chia các điểm về tâm gần nhất
    clusters = [[] for _ in range(days)]
    for place in places:
        nearest_idx = min(
            range(days),
            key=lambda i: haversine_distance(place["lat"], place["lng"], centers[i]["lat"], centers[i]["lng"])
        )
        clusters[nearest_idx].append(place)

    # Đảm bảo không ngày nào bị rỗng (tái cân bằng nhẹ nếu có cụm rỗng)
    for i in range(days):
        if not clusters[i]:
            max_cluster = max(clusters, key=len)
            if len(max_cluster) > 1:
                clusters[i].append(max_cluster.pop())

    return [c for c in clusters if c]

# ==============================================================================
# 6. SẮP XẾP THEO NHỊP SINH HỌC DU LỊCH VIỆT NAM (HUMAN BIOLOGICAL RHYTHM)
# ==============================================================================
def sequence_by_human_rhythm(day_places: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Sắp xếp các địa điểm trong ngày theo nhịp sống tự nhiên:
    Sáng (Tham quan) -> Trưa (Ăn đặc sản) -> Chiều (Trải nghiệm/Cafe) -> Tối (Ăn tối / Dạo chợ đêm)
    kết hợp giải thuật tối ưu 2-Opt Local Search và Hard Time-Window TSPTW.
    """
    if not day_places:
        return []
    if len(day_places) == 1:
        sim, _, _ = simulate_route(day_places)
        return sim

    slot_priority = {
        "ATTRACTION": 1,
        "TEMPLE": 1,
        "MUSEUM": 1,
        "HISTORICAL_SITE": 1,
        "RESTAURANT": 2,
        "SEAFOOD_RESTAURANT": 2,
        "SPECIALTY_FOOD": 2,
        "ACTIVITY": 3,
        "CAFE": 3,
        "HOTEL": 4,
        "MARKET": 5,
        "NIGHT_MARKET": 5
    }

    def get_priority(p):
        cat = str(p.get("category", "ATTRACTION")).upper()
        name = str(p.get("name", "")).lower()
        if "đêm" in name or "night" in name or cat == "NIGHT_MARKET":
            return 5
        return slot_priority.get(cat, 3)

    # Sắp xếp sơ bộ theo loại hình
    sorted_places = sorted(day_places, key=get_priority)

    # Tối ưu hóa lộ trình bằng 2-Opt TSPTW với Hard Time-Windows
    optimized, _ = solve_day_tsptw_2opt(sorted_places)
    return optimized

# ==============================================================================
# 7. ĐIỀN KHUYẾT THÔNG MINH TỪ DATABASE (SMART GAP-FILLING)
# ==============================================================================
def fill_gaps_from_db(
    current_places: List[Dict[str, Any]],
    target_count: int = 3,
    db_path: str = r"d:\vn-travel-planner\travel_db.db"
) -> List[Dict[str, Any]]:
    """
    Nếu người dùng chọn quá ít điểm, tự động truy vấn `travel_db.db`
    lấy thêm nhà hàng đặc sản hoặc điểm tham quan lân cận trong cùng khu vực.
    """
    if len(current_places) >= target_count or not current_places:
        return current_places

    ref_lat = current_places[0]["lat"]
    ref_lng = current_places[0]["lng"]
    current_ids = {p["id"] for p in current_places}

    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""
        SELECT id, name, category, lat, lng, address, rating, price_range, prices, 
               phone_number, website, image_url, google_maps_url, typical_time_spent, google_place_id
        FROM places
        WHERE category IN ('RESTAURANT', 'ATTRACTION', 'MARKET', 'ACTIVITY')
    """)
    rows = c.fetchall()
    conn.close()

    candidates = []
    for r in rows:
        if r[0] in current_ids:
            continue
        dist = haversine_distance(ref_lat, ref_lng, r[3], r[4])
        if dist <= 25.0:  # Trong bán kính 25km lân cận
            candidates.append((dist, {
                "id": r[0],
                "name": r[1],
                "category": r[2],
                "lat": r[3],
                "lng": r[4],
                "address": r[5],
                "rating": r[6],
                "price_range_db": r[7],
                "prices_json_db": r[8],
                "phone_number": r[9],
                "website": r[10],
                "image_url": r[11],
                "google_maps_url": r[12],
                "typical_time_spent": r[13],
                "google_place_id": r[14]
            }))

    candidates.sort(key=lambda x: x[0])
    needed = target_count - len(current_places)
    filled = current_places.copy()
    for _, place in candidates[:needed]:
        filled.append(place)

    return filled

# ==============================================================================
# 8. ĐÁNH GIÁ ĐỔI KHÁCH SẠN LIÊN NGÀY (HOTEL SWITCHING EVALUATOR)
# ==============================================================================
def evaluate_hotel_switching(day_routes: List[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """
    Đánh giá khoảng cách giữa các ngày:
    - Nếu khoảng cách giữa ngày N và N+1 >= 35 km -> Cảnh báo gợi ý đổi khách sạn.
    - Nếu < 20 km -> Gợi ý giữ nguyên 1 khách sạn để đỡ mệt.
    """
    if len(day_routes) <= 1:
        return {"should_switch": False, "reason": "Chuyến đi trong ngày, không cần đổi khách sạn."}

    switches = []
    for d in range(len(day_routes) - 1):
        if not day_routes[d] or not day_routes[d+1]:
            continue
        end_p = day_routes[d][-1]
        start_p = day_routes[d+1][0]
        dist = haversine_distance(end_p["lat"], end_p["lng"], start_p["lat"], start_p["lng"])

        if dist >= 35.0:
            switches.append({
                "from_day": d + 1,
                "to_day": d + 2,
                "distance_km": round(dist, 1),
                "advice": f"Khoảng cách giữa Ngày {d+1} và Ngày {d+2} khá xa ({round(dist, 1)} km). Gợi ý đổi khách sạn sang khu vực mới để tiết kiệm hơn 1 giờ di chuyển."
            })

    if switches:
        return {
            "should_switch": True,
            "switches": switches,
            "summary": f"Phát hiện {len(switches)} chặng cách xa >= 35km. Gợi ý đổi khách sạn để chuyến đi thảnh thơi hơn."
        }

    return {
        "should_switch": False,
        "switches": [],
        "summary": "Khoảng cách giữa các ngày đều thuận tiện (< 30km). Khuyên bạn nên giữ nguyên 1 khách sạn cố định để tránh mất thời gian check-in/out."
    }

# ==============================================================================
# 9. HÀM TỔNG HỢP LẬP LỊCH TRÌNH ĐA NGÀY (MULTI-DAY TRIP PLAN GENERATOR)
# ==============================================================================
def generate_multi_day_plan(
    prompt_keywords: List[str],
    days: int = 1,
    group_size: int = 2,
    vehicle_type: str = "car",
    db_path: str = r"d:\vn-travel-planner\travel_db.db"
) -> Dict[str, Any]:
    """
    Tạo lịch trình du lịch thông minh đa ngày (1 - 5 ngày):
    - Đọc dữ liệu thực tế 100% từ travel_db.db
    - Phân cụm địa lý theo từng ngày
    - Xếp theo nhịp sinh học du lịch Việt Nam
    - Tự động điền khuyết quán ăn/danh thắng
    - Đánh giá chuyển khách sạn
    - Tạo link Goong Static Map lộ trình đường thật
    - Tính toán chi phí cả đoàn và bình quân đầu người
    """
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    valid_days = max(1, min(days, 5))
    needed_per_kw = max(1, math.ceil(valid_days / max(1, len(prompt_keywords))))
    matched_places = []
    seen_ids = set()
    for kw in prompt_keywords:
        c.execute("""
            SELECT id, name, category, lat, lng, address, rating, price_range, prices, 
                   phone_number, website, image_url, google_maps_url, typical_time_spent, google_place_id 
            FROM places 
            WHERE name LIKE ? OR address LIKE ?
            LIMIT ?
        """, (f"%{kw}%", f"%{kw}%", needed_per_kw))
        rows = c.fetchall()
        for row in rows:
            if row[0] not in seen_ids:
                seen_ids.add(row[0])
                matched_places.append({
                    "id": row[0],
                    "name": row[1],
                    "category": row[2],
                    "lat": row[3],
                    "lng": row[4],
                    "address": row[5],
                    "rating": row[6],
                    "price_range_db": row[7],
                    "prices_json_db": row[8],
                    "phone_number": row[9],
                    "website": row[10],
                    "image_url": row[11],
                    "google_maps_url": row[12],
                    "typical_time_spent": row[13],
                    "google_place_id": row[14]
                })
    conn.close()

    if not matched_places:
        return {"error": "Không tìm thấy địa điểm phù hợp trong Database."}

    days = max(1, min(days, 5))
    group_size = max(1, group_size)

    # 1. Phân cụm theo số ngày
    clusters = cluster_places_by_days(matched_places, days)

    total_trip_km = 0.0
    days_itinerary = []
    day_routes_for_eval = []

    # 2. Xử lý từng ngày theo nhịp sinh học & điền khuyết
    for day_idx, cluster in enumerate(clusters, 1):
        # Điền khuyết nếu cụm ít hơn 3 điểm
        filled_cluster = fill_gaps_from_db(cluster, target_count=3, db_path=db_path)
        
        # Sắp xếp theo nhịp sinh học
        sequenced = sequence_by_human_rhythm(filled_cluster)
        day_routes_for_eval.append(sequenced)

        # Đo tổng quãng đường ngày hôm đó theo đúng thứ tự đã định tuyến
        if len(sequenced) >= 2:
            day_km = sum(
                haversine_distance(sequenced[k]["lat"], sequenced[k]["lng"], sequenced[k+1]["lat"], sequenced[k+1]["lng"])
                for k in range(len(sequenced) - 1)
            )
        else:
            day_km = 0.0
        total_trip_km += day_km

        # Tạo link ảnh bản đồ tĩnh Goong Map qua Backend Proxy
        static_map_url = None
        if len(sequenced) >= 2:
            p_start = sequenced[0]
            p_end = sequenced[-1]
            static_map_url = (
                f"/api/map/static-route?"
                f"origin_lat={p_start['lat']}&origin_lng={p_start['lng']}&"
                f"dest_lat={p_end['lat']}&dest_lng={p_end['lng']}&"
                f"vehicle={vehicle_type}&width=600&height=350"
            )

        day_steps = []
        for step_idx, p in enumerate(sequenced, 1):
            price_info = format_place_price(p.get("category", "ATTRACTION"), p.get("price_range_db"), p.get("prices_json_db"))
            day_steps.append({
                "step": step_idx,
                "name": p["name"],
                "category": p["category"],
                "suggested_time": p.get("suggested_time", "09:00"),
                "time": p.get("time", p.get("suggested_time", "09:00")),
                "arrival_time": p.get("arrival_time", p.get("suggested_time", "09:00")),
                "departure_time": p.get("departure_time", "10:30"),
                "dwell_time_minutes": p.get("dwell_time_minutes", 60),
                "wait_time_minutes": p.get("wait_time_minutes", 0),
                "is_time_window_valid": p.get("is_time_window_valid", True),
                "time_window_display": p.get("time_window_display", "08:00 - 18:00"),
                "time_window_advisory": p.get("time_window_advisory", None),
                "open_time": p.get("open_time", "08:00"),
                "close_time": p.get("close_time", "18:00"),
                "period_name": p.get("period_name", "Tham quan"),
                "period_icon": p.get("period_icon", "📍"),
                "address": p["address"],
                "lat": p.get("lat"),
                "lng": p.get("lng"),
                "rating": p.get("rating"),
                "image_url": p.get("image_url"),
                "phone_number": p.get("phone_number"),
                "website": p.get("website"),
                "google_maps_url": p.get("google_maps_url"),
                "price_display": price_info["display"],
                "price_info": price_info
            })

        days_itinerary.append({
            "day": day_idx,
            "title": f"Ngày {day_idx}: Khám phá cụm điểm {sequenced[0]['name']}",
            "places_count": len(sequenced),
            "day_distance_km": round(day_km, 2),
            "static_map_url": static_map_url,
            "itinerary": day_steps
        })

    # 3. Tính toán chi phí di chuyển toàn chuyến đi
    transport_info = calculate_transport_cost(total_trip_km, vehicle_type, group_size)

    # 4. Tính toán chi phí phòng khách sạn (nếu đi >= 2 ngày)
    hotel_info = None
    if days > 1:
        nights = days - 1
        rooms_count = math.ceil(group_size / 2)
        room_rate_est = 750000  # Đơn giá phòng tham khảo
        total_hotel_cost = rooms_count * room_rate_est * nights
        hotel_per_person = round(total_hotel_cost / group_size, -2)
        hotel_info = {
            "nights": nights,
            "rooms_count": rooms_count,
            "estimated_room_rate_vnd": room_rate_est,
            "total_hotel_cost_vnd": total_hotel_cost,
            "cost_per_person_vnd": int(hotel_per_person),
            "formula_note": f"{rooms_count} phòng đôi ({math.ceil(group_size/2)} phòng cho đoàn {group_size} người) x {room_rate_est:,}đ/đêm x {nights} đêm"
        }

    # 5. Đánh giá đổi khách sạn
    hotel_switch_advice = evaluate_hotel_switching(day_routes_for_eval)

    # 6. Tổng hợp chi phí dự kiến cả chuyến đi
    grand_total_group = transport_info["total_group_cost_vnd"] + (hotel_info["total_hotel_cost_vnd"] if hotel_info else 0)
    grand_total_per_person = transport_info["cost_per_person_vnd"] + (hotel_info["cost_per_person_vnd"] if hotel_info else 0)

    # Hỗ trợ cấu trúc trả về đơn ngày tương thích ngược (Flat itinerary)
    flat_itinerary = []
    for d in days_itinerary:
        flat_itinerary.extend(d["itinerary"])

    return {
        "summary": {
            "total_days": days,
            "group_size": group_size,
            "vehicle": transport_info["vehicle"],
            "total_distance_km": round(total_trip_km, 2),
            "grand_total_group_vnd": grand_total_group,
            "grand_total_per_person_vnd": grand_total_per_person
        },
        "transport_cost": transport_info,
        "accommodation_cost": hotel_info,
        "hotel_switch_advice": hotel_switch_advice,
        "days": days_itinerary,
        # Giữ lại các trường cũ cho frontend hiện tại không bị lỗi
        "prompt_summary": f"Lịch trình {days} ngày ({len(flat_itinerary)} địa điểm) qua quãng đường {round(total_trip_km, 2)} km bằng {transport_info['vehicle']}",
        "total_distance_km": round(total_trip_km, 2),
        "itinerary": flat_itinerary
    }

# ==============================================================================
# 10. HÀM TƯƠNG THÍCH NGƯỢC CHO TOUR ĐƠN NGÀY
# ==============================================================================
def generate_trip_plan(
    prompt_keywords: List[str],
    vehicle_type: str = "car",
    db_path: str = r"d:\vn-travel-planner\travel_db.db"
) -> Dict[str, Any]:
    """Hàm wrapper tương thích ngược cho các gọi hàm cũ"""
    return generate_multi_day_plan(
        prompt_keywords=prompt_keywords,
        days=1,
        group_size=2,
        vehicle_type=vehicle_type,
        db_path=db_path
    )
