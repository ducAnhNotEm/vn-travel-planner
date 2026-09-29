import math
import sqlite3
import json
from typing import List, Dict, Any, Tuple

# 1. Công thức Haversine tính khoảng cách giữa 2 tọa độ GPS (km)
def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0  # Bán kính Trái Đất (km)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# 2. Thuật toán Sắp xếp Đường đi ngắn nhất (Nearest Neighbor / TSP)
def optimize_route(places: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], float]:
    if not places:
        return [], 0.0
    
    unvisited = places.copy()
    current = unvisited.pop(0)  # Bắt đầu từ điểm đầu tiên (ví dụ Khách sạn)
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

# 3. Tính Chi phí Di chuyển dựa trên Phương tiện
def calculate_transport_cost(distance_km: float, vehicle_type: str = "car") -> Dict[str, Any]:
    vehicle_type = vehicle_type.lower()
    
    if vehicle_type in ["chartered_van", "tour_bus", "van"]:
        # Thuê xe du lịch riêng cả chuyến (Xe 7-16 chỗ kèm tài xế & xăng dầu)
        cost = 1000000 + (distance_km * 2500)
        desc = f"Thuê xe du lịch riêng (Xe 7-16 chỗ trọn gói cả xe)"
    elif vehicle_type == "motorbike":
        cost = distance_km * 600 + 10000  # 600đ/km xăng + 10k gửi xe
        desc = f"Xe máy cá nhân (~600đ/km + gửi xe)"
    elif vehicle_type == "taxi":
        cost = 12000 + (distance_km * 14000)
        desc = f"Taxi / GrabCar (~14.000đ/km)"
    else:  # 'car' - ô tô cá nhân
        cost = (distance_km * 1800) + 30000  # 1.800đ/km xăng + 30k gửi xe
        desc = f"Ô tô cá nhân (~1.800đ/km + phí gửi xe/cầu đường)"

    return {
        "vehicle": desc,
        "distance_km": distance_km,
        "estimated_cost_vnd": round(cost, -3)
    }


# 4. Lấy Giá ĐỊA ĐIỂM Trực tiếp từ CƠ SỞ DỮ LIỆU (Database)
def format_place_price(category: str, price_range_db: str, prices_json_db: str) -> Dict[str, Any]:
    category = category.upper()
    
    # Nếu trong Database đã có cột price_range thực tế (như Khách sạn từ Google Places)
    if price_range_db:
        prices_list = json.loads(prices_json_db) if prices_json_db else []
        return {
            "has_price": True,
            "display": price_range_db,
            "type_label": "Khách sạn / Lưu trú (Giá thực tế từ DB)",
            "providers_count": len(prices_list)
        }
    
    # Nếu là Nhà hàng (nếu DB chưa có giá riêng thì có mức giá tiêu chuẩn)
    if category in ["RESTAURANT", "SEAFOOD_RESTAURANT", "SPECIALTY_FOOD"]:
        return {
            "has_price": True,
            "display": "Tham khảo: ~100.000 - 300.000 VNĐ / người",
            "type_label": "Nhà hàng / Ăn uống"
        }

    # BỎ QUA GIÁ CHO CHÙA, CHỢ, DANH THẮNG KHÔNG MẤT VÉ
    return {
        "has_price": False,
        "display": "Miễn phí vé vào / Tự do tham quan",
        "type_label": "Điểm tham quan / Chợ (Không mất vé)"
    }

# 5. Hàm AI Prompt Matcher & Plan Generator
def generate_trip_plan(prompt_keywords: List[str], vehicle_type: str = "car", db_path: str = r"d:\vn-travel-planner\travel_db.db") -> Dict[str, Any]:
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    matched_places = []
    for kw in prompt_keywords:
        c.execute("""
            SELECT id, name, category, lat, lng, address, rating, price_range, prices, phone_number, website, image_url 
            FROM places 
            WHERE name LIKE ? OR address LIKE ?
            LIMIT 1
        """, (f"%{kw}%", f"%{kw}%"))
        row = c.fetchone()
        if row:
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
                "image_url": row[11]
            })
    
    conn.close()

    if not matched_places:
        return {"error": "Không tìm thấy địa điểm phù hợp trong Database."}

    # Sắp xếp đường đi ngắn nhất
    route, total_km = optimize_route(matched_places)
    
    # Tính chi phí di chuyển
    transport_info = calculate_transport_cost(total_km, vehicle_type)

    itinerary_details = []
    for idx, place in enumerate(route, 1):
        price_info = format_place_price(place["category"], place["price_range_db"], place["prices_json_db"])

        itinerary_details.append({
            "step": idx,
            "name": place["name"],
            "category": place["category"],
            "address": place["address"],
            "rating": place.get("rating"),
            "image_url": place.get("image_url"),
            "phone_number": place.get("phone_number"),
            "website": place.get("website"),
            "price_display": price_info["display"],
            "price_info": price_info
        })

    return {
        "prompt_summary": f"Lịch trình {len(route)} địa điểm qua đường đi ngắn nhất ({total_km} km) bằng {transport_info['vehicle']}",
        "total_distance_km": total_km,
        "transport_cost": transport_info,
        "itinerary": itinerary_details
    }

if __name__ == "__main__":
    keywords = ["Grand Phoenix", "Chùa Dâu", "Chợ Suối Hoa", "Tân Lương Sơn"]
    
    print("=== TEST LỊCH TRÌNH ĐỌC GIÁ TRỰC TIẾP TỪ DATABASE ===")
    plan = generate_trip_plan(keywords, vehicle_type="car")
    
    print(f"Tổng quãng đường: {plan['total_distance_km']} km")
    print(f"Chi phí di chuyển ({plan['transport_cost']['vehicle']}): {plan['transport_cost']['estimated_cost_vnd']:,} VNĐ\n")
    print("Chi tiết từng chặng:")
    for step in plan['itinerary']:
        print(f"  {step['step']}. {step['name']} ({step['category']})")
        print(f"     Giá từ Database: {step['price_display']}")
