import math
import sqlite3
import json
from typing import List, Dict, Any, Tuple, Optional

# ==============================================================================
# 1. CÔNG THỨC HAVERSINE TÍNH KHOẢNG CÁCH GPS (KM)
# ==============================================================================
def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0  # Bán kính Trái Đất (km)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# ==============================================================================
# 2. THUẬT TOÁN SẮP XẾP ĐƯỜNG ĐI NGẮN NHẤT ĐƠN NGÀY (TSP / NEAREST NEIGHBOR)
# ==============================================================================
def optimize_route(places: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], float]:
    if not places:
        return [], 0.0
    
    unvisited = places.copy()
    current = unvisited.pop(0)
    route = [current]
    total_distance = 0.0

    while unvisited:
        nearest = min(
            unvisited,
            key=lambda p: haversine_distance(current["lat"], current["lng"], p["lat"], p["lng"])
        )
        dist = haversine_distance(current["lat"], current["lng"], nearest["lat"], nearest["lng"])
        total_distance += dist
        current = nearest
        route.append(current)
        unvisited.remove(nearest)

    return route, round(total_distance, 2)

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
    """
    slot_priority = {
        "ATTRACTION": 1,
        "TEMPLE": 1,
        "MUSEUM": 1,
        "RESTAURANT": 2,
        "SEAFOOD_RESTAURANT": 2,
        "SPECIALTY_FOOD": 2,
        "ACTIVITY": 3,
        "CAFE": 3,
        "HOTEL": 4,
        "MARKET": 5,
        "NIGHT_MARKET": 5
    }

    # Sắp xếp sơ bộ theo loại hình
    sorted_places = sorted(
        day_places,
        key=lambda p: slot_priority.get(p.get("category", "ATTRACTION").upper(), 3)
    )

    # Phân loại nhịp sinh học theo tính chất địa lý
    full_text = " ".join([f"{p.get('name', '')} {p.get('address', '')} {p.get('category', '')}" for p in day_places]).lower()
    
    is_coastal = any(k in full_text for k in [
        "biển", "bãi tắm", "bãi biển", "mỹ khê", "sầm sơn", "cửa lò", "nha trang", "hòn", "vịnh", 
        "hạ long", "vân đồn", "cát bà", "đồ sơn", "quy nhơn", "phú quốc", "côn đảo", "beach"
    ])
    is_mountain = any(k in full_text for k in [
        "đà lạt", "sa pa", "sapa", "mộc châu", "tam đảo", "hà giang", "đèo", "thác", "núi", 
        "đỉnh", "buôn ma thuột", "pleiku", "fansipan", "mã pí lèng", "yên bái", "cao bằng"
    ])

    # Sắp xếp theo thứ tự tối ưu đường đi ngắn nhất
    optimized, _ = optimize_route(sorted_places)

    if is_coastal:
        # 🌊 NHỊP SINH HỌC DU LỊCH BIỂN (COASTAL RHYTHM)
        time_slots = [
            {"time": "05:30", "period": "Đón bình minh & Tắm sớm", "icon": "🌅"},
            {"time": "07:30", "period": "Ăn sáng đặc sản", "icon": "🍜"},
            {"time": "09:30", "period": "Đi dạo / Check-in mát mẻ", "icon": "🚶"},
            {"time": "11:45", "period": "Ăn trưa hải sản", "icon": "🍲"},
            {"time": "13:00", "period": "Nghỉ trưa tránh nắng (Khách sạn)", "icon": "🏨"},
            {"time": "16:00", "period": "Ngắm hoàng hôn & Tắm chiều", "icon": "🌇"},
            {"time": "19:00", "period": "Ăn tối hải sản bờ biển", "icon": "🦀"},
            {"time": "20:45", "period": "Dạo biển đêm / Chợ đêm", "icon": "🌊"}
        ]
    elif is_mountain:
        # 🌲 NHỊP SINH HỌC ĐỒI NÚI & CAO NGUYÊN (MOUNTAIN RHYTHM)
        time_slots = [
            {"time": "06:00", "period": "Săn mây & Đón bình minh", "icon": "☁️"},
            {"time": "07:45", "period": "Ăn sáng & Cafe nóng", "icon": "☕"},
            {"time": "09:00", "period": "Thác nước / Trekking / Bản làng", "icon": "🚶"},
            {"time": "11:45", "period": "Ăn trưa gà đồi / Cơm lam", "icon": "🍲"},
            {"time": "13:30", "period": "Nghỉ ngơi homestay", "icon": "🏨"},
            {"time": "15:00", "period": "Đồi thông / Vườn hoa", "icon": "🌸"},
            {"time": "18:30", "period": "Tiệc nướng than hoa / Lẩu nóng", "icon": "🔥"},
            {"time": "20:45", "period": "Dạo chợ đêm & Sữa nóng", "icon": "🧣"}
        ]
    else:
        # 🏛️ NHỊP SINH HỌC DI TÍCH, VĂN HÓA & ĐÔ THỊ (HERITAGE & URBAN RHYTHM)
        time_slots = [
            {"time": "07:30", "period": "Ăn sáng đặc sản", "icon": "🍜"},
            {"time": "08:30", "period": "Danh thắng / Di tích sáng mát", "icon": "🏛️"},
            {"time": "11:45", "period": "Ăn trưa đặc sản vùng miền", "icon": "🍲"},
            {"time": "13:00", "period": "Nghỉ trưa tránh nắng", "icon": "🏨"},
            {"time": "14:45", "period": "Làng nghề / Thuyền sinh thái", "icon": "🛶"},
            {"time": "17:15", "period": "Cafe view hoàng hôn / Dạo hồ", "icon": "☕"},
            {"time": "19:00", "period": "Ăn tối nhà hàng đặc sản", "icon": "🍲"},
            {"time": "20:45", "period": "Phố đi bộ / Chợ đêm", "icon": "🏮"}
        ]

    for idx, p in enumerate(optimized):
        slot = time_slots[min(idx, len(time_slots) - 1)]
        p["suggested_time"] = slot["time"]
        p["period_name"] = slot["period"]
        p["period_icon"] = slot["icon"]

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
               phone_number, website, image_url, google_maps_url
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
                "google_maps_url": r[12]
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
                   phone_number, website, image_url, google_maps_url 
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
                    "google_maps_url": row[12]
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

        # Đo tổng quãng đường ngày hôm đó
        _, day_km = optimize_route(sequenced)
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
            price_info = format_place_price(p["category"], p.get("price_range_db"), p.get("prices_json_db"))
            day_steps.append({
                "step": step_idx,
                "name": p["name"],
                "category": p["category"],
                "suggested_time": p.get("suggested_time", "09:00"),
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
