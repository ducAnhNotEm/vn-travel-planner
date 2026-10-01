"""
VN Travel Planner — Elite NLU Dataset Generator v4.0 (Top 0.01% Standard)
========================================================================
Khắc phục triệt để các lỗi bộc lộ từ V1 Baseline:
1. prefer_flight: Phân bổ cân bằng 3 trạng thái (True / False / None).
   - True: Khi khách explicitly đòi bay.
   - False: Khi khách explicitly từ chối bay / chuyển từ bay sang đường bộ.
   - None: Khi khách không nhắc đến máy bay HOẶC lưỡng lự ("sao cũng được").
2. origin: Kích hoạt Reference Token 'CURRENT_LOCATION' cho các câu:
   - "từ đây", "từ chỗ tôi", "từ vị trí hiện tại", "đang đứng ở đây".
3. group_size:
   - Explicit: 1, 2, 4, 6, 12, 16...
   - Semantic-Closed: "mình với bạn gái", "2 đứa", "vợ chồng", "cặp đôi" -> 2.
   - Unresolved / Implicit: "cả nhà", "đoàn công ty", "thuê xe 7 chỗ" -> None.
4. vehicle_type:
   - Chỉ chứa phương tiện mặt đất: car, motorbike, taxi, van, hoặc None.
   - CẤM TUYỆT ĐỐI chữ 'flight' trong vehicle_type.
   - Khách nói "thuê xe 7 chỗ" -> vehicle_type: car, group_size: None.
5. excluded_activities:
   - Lọc sạch 100% transport negation (CẤM chữ "không đi máy bay" lọt vào đây).
   - Chỉ chứa domain constraints: "không leo núi", "không ăn cay", "ngại đi bộ"...
6. destination: Province Canonical Linking (Đà Lạt -> Lâm Đồng, Nha Trang -> Khánh Hòa).
"""

import sqlite3
import json
import random
import re
from pathlib import Path
from typing import List, Dict, Any, Tuple
from collections import Counter

# ── 1. KẾT NỐI DB THỰC ───────────────────────────────────────────────────────
DB_PATH = r"d:\vn-travel-planner\travel_db.db"
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.execute("""
    SELECT p.name, pr.name, p.category, p.province_code
    FROM places p
    JOIN provinces pr ON p.province_code = pr.code
""")
ALL_PLACES = cur.fetchall()

cur.execute("SELECT code, name FROM provinces WHERE is_in_project = 1")
PROVINCES = cur.fetchall()
conn.close()

def clean_province(pname: str) -> str:
    return pname.replace("Thành phố ", "").replace("Tỉnh ", "").strip()

PROV_CANONICAL = {p[1]: clean_province(p[1]) for p in PROVINCES}

# Mapping các điểm du lịch nổi tiếng về Tỉnh Hành Chính (Entity Linking Ground Truth)
CITY_TO_PROVINCE = {
    "Đà Lạt": "Lâm Đồng",
    "Bảo Lộc": "Lâm Đồng",
    "Nha Trang": "Khánh Hòa",
    "Cam Ranh": "Khánh Hòa",
    "Hạ Long": "Quảng Ninh",
    "Vân Đồn": "Quảng Ninh",
    "Cô Tô": "Quảng Ninh",
    "Sapa": "Lào Cai",
    "Sa Pa": "Lào Cai",
    "Bắc Hà": "Lào Cai",
    "Mộc Châu": "Sơn La",
    "Đồng Văn": "Hà Giang",
    "Mèo Vạc": "Hà Giang",
    "Cát Bà": "Hải Phòng",
    "Đồ Sơn": "Hải Phòng",
    "Sầm Sơn": "Thanh Hóa",
    "Cửa Lò": "Nghệ An",
    "Hội An": "Quảng Nam",
    "Bà Nà": "Đà Nẵng",
    "Phú Quốc": "Kiên Giang",
    "Vũng Tàu": "Bà Rịa - Vũng Tàu",
    "Côn Đảo": "Bà Rịa - Vũng Tàu",
    "Buôn Ma Thuột": "Đắk Lắk",
    "Pleiku": "Gia Lai"
}

ORIGIN_CITIES = ["Hà Nội", "TP.HCM", "Đà Nẵng", "Hải Phòng", "Cần Thơ", "Huế", "Nha Trang", "Vinh"]

# Kho Domain Constraints (TUYỆT ĐỐI KHÔNG CHỨA PHƯƠNG TIỆN)
CLEAN_EXCLUDED_ACTIVITIES = [
    "không leo núi", "không đi bộ nhiều", "ngại đi xa", "không thích chỗ đông người",
    "không ăn cay", "không muốn lịch trình quá dày", "tránh đi đêm", "không ăn hải sản",
    "không leo bậc thang cao", "hạn chế say xe", "không tắm biển nước sâu"
]

CLEAN_PREFERENCES = [
    "tắm biển", "ăn hải sản", "check-in sống ảo", "chụp ảnh", "văn hóa lịch sử",
    "thiên nhiên hoang sơ", "ẩm thực đường phố", "nghỉ dưỡng yên tĩnh",
    "hoạt động cho trẻ em", "săn mây ngắm cảnh", "thích đi chùa tâm linh",
    "thưởng thức cà phê chill", "khám phá làng nghề", "đi chợ đêm",
    "trải nghiệm ẩm thực bản địa", "ngắm hoàng hôn", "trekking nhẹ nhàng"
]

SYSTEM_PROMPT = """Bạn là NLU Engine chuyên dụng cho hệ thống Travel AI Việt Nam.
Nhiệm vụ: Phân tích yêu cầu của người dùng và trích xuất thành định dạng JSON chuẩn.
Quy tắc:
1. Chỉ trả về duy nhất chuỗi JSON hợp lệ bắt đầu bằng '{' và kết thúc bằng '}', không kèm markdown hay lời dẫn.
2. Xác định đúng intent trong các loại: 'plan_itinerary', 'search_place', 'ask_advisory', 'clarify_needed'.
3. Nếu người dùng không đề cập thông tin nào, trường tương ứng BẮT BUỘC để null (hoặc [] với mảng). Tuyệt đối không tự suy diễn số liệu."""

# ── 2. HỆ THỐNG SINH MẪU ĐA DẠNG CHUẨN XÁC V4 ────────────────────────────────

def gen_plan_sample(sample_subtype: str) -> Tuple[str, Dict[str, Any]]:
    # 1. Chọn điểm đến
    if random.random() < 0.45:
        # Chọn địa danh du lịch nổi tiếng cần linking về tỉnh
        city_name, prov_canonical = random.choice(list(CITY_TO_PROVINCE.items()))
        dest_in_prompt = city_name
        dest_canonical = prov_canonical
    else:
        prov_raw = random.choice(PROVINCES)[1]
        dest_in_prompt = PROV_CANONICAL[prov_raw]
        dest_canonical = dest_in_prompt

    days = random.randint(1, 5)
    day_str = random.choice([f"{days} ngày {days-1} đêm", f"{days}n{days-1}d", f"{days}N{days-1}Đ", f"{days} ngày", f"{days} hôm"])

    # 2. Xử lý ORIGIN & REFERENCE TOKEN
    ref_tokens = ["từ đây", "từ chỗ tôi", "từ chỗ mình đang đứng", "từ vị trí hiện tại", "xuất phát tại đây"]
    if sample_subtype == "current_location":
        origin_val = "CURRENT_LOCATION"
        origin_str = random.choice(ref_tokens)
    elif sample_subtype == "no_origin":
        origin_val = None
        origin_str = ""
    else:
        origin_val = random.choice(ORIGIN_CITIES)
        origin_str = f"từ {origin_val}"

    # 3. Xử lý GROUP SIZE (Phân biệt Explicit, Semantic-Closed, Unresolved)
    if sample_subtype == "semantic_couple":
        group_val = 2
        group_str = random.choice(["mình với bạn gái", "hai đứa mình", "vợ chồng mình", "mình với người yêu", "2 vợ chồng"])
    elif sample_subtype == "unresolved_group":
        group_val = None
        group_str = random.choice(["cả nhà mình", "nhóm bạn mình", "đoàn công ty", "mấy anh em", "đoàn đông người"])
    elif sample_subtype == "sparse":
        group_val = None
        group_str = ""
    else:
        group_val = random.choice([1, 2, 4, 5, 6, 8, 12, 16])
        group_str = f"đoàn {group_val} người" if group_val > 1 else "1 mình (solo)"

    # 4. Xử lý VEHICLE & PREFER_FLIGHT (Rạch ròi 3 trạng thái của prefer_flight)
    if sample_subtype == "flight_explicit":
        prefer_flight = True
        v_type = random.choice(["car", "motorbike", "taxi", None])
        flight_str = random.choice(["muốn bay", "đặt vé máy bay cho nhanh", "bay vào rồi di chuyển"])
    elif sample_subtype == "flight_rejected":
        prefer_flight = False
        v_type = "car"
        flight_str = random.choice([
            "ban đầu định đi máy bay nhưng vé đắt quá nên quyết định đi ô tô tự lái",
            "không muốn đi máy bay, thích tự lái ô tô ngắm cảnh",
            "sợ say máy bay nên chuyển sang đi ô tô",
            "định bay nhưng thôi cả nhà lái ô tô cho tiện"
        ])
    elif sample_subtype == "flight_ambiguous":
        prefer_flight = None
        v_type = None
        flight_str = random.choice([
            "ô tô hay máy bay đều được, cái nào tiện thì đi",
            "chưa biết đi máy bay hay đi xe khách, tư vấn giúp",
            "phương tiện gì cũng được miễn tiết kiệm",
            "đi xe hay máy bay đều ok nhé"
        ])
    elif sample_subtype == "seat_capacity":
        prefer_flight = None
        v_type = "car" # 7 chỗ hay 4 chỗ đều là xe con
        group_val = None # 7 chỗ là loại xe, không nói đi mấy người
        flight_str = random.choice(["thuê xe 7 chỗ tự lái", "thuê ô tô 7 chỗ", "đi xe 4 chỗ"])
    else: # ground default / no mention
        prefer_flight = None
        v_type = random.choice(["car", "motorbike", "taxi", "van", None])
        flight_str = {"car": "đi ô tô", "motorbike": "đi xe máy", "taxi": "đi taxi", "van": "thuê xe 16 chỗ", None: ""}[v_type]

    # 5. Ràng buộc & Sở thích
    n_pref = random.randint(0, 2)
    prefs = random.sample(CLEAN_PREFERENCES, n_pref) if n_pref > 0 else []

    n_excl = random.randint(0, 1) if random.random() < 0.3 else 0
    excls = random.sample(CLEAN_EXCLUDED_ACTIVITIES, n_excl) if n_excl > 0 else []

    # 6. Ghép câu tự nhiên
    parts = []
    if group_str: parts.append(group_str)
    parts.append(f"tính đi {dest_in_prompt} {day_str}")
    if origin_str: parts.append(origin_str)
    if flight_str: parts.append(flight_str)
    if prefs: parts.append(f"thích {', '.join(prefs)}")
    if excls: parts.append(f"lưu ý là {', '.join(excls)}")

    u_text = ", ".join([p for p in parts if p]).strip()
    u_text = u_text[0].upper() + u_text[1:] + "."

    json_expected = {
        "intent": "plan_itinerary",
        "destination": dest_canonical, # Đã chuẩn hóa về Province Canonical
        "origin": origin_val,
        "duration_days": days,
        "group_size": group_val,
        "vehicle_type": v_type,
        "budget_total_vnd": None,
        "preferences": prefs,
        "excluded_activities": excls,
        "hard_pinned_locations": [],
        "prefer_flight": prefer_flight
    }
    return u_text, json_expected

# ── 3. HÀM MAIN SINH 900 MẪU V4 VÀ TÁCH TRAIN / VAL ──────────────────────────
def main():
    random.seed(2026)
    TOTAL = 900
    dataset = []
    seen = set()

    subtypes = (
        ["standard"] * 30 +
        ["semantic_couple"] * 15 +
        ["unresolved_group"] * 15 +
        ["current_location"] * 15 +
        ["no_origin"] * 10 +
        ["flight_explicit"] * 15 +
        ["flight_rejected"] * 15 +
        ["flight_ambiguous"] * 15 +
        ["seat_capacity"] * 10 +
        ["sparse"] * 15
    )

    while len(dataset) < TOTAL:
        st = random.choice(subtypes)
        u_text, j_out = gen_plan_sample(st)
        
        # Chặn duplicate tuyệt đối
        k = u_text.lower().strip()
        if k in seen: continue
        seen.add(k)

        dataset.append({
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": u_text},
                {"role": "assistant", "content": json.dumps(j_out, ensure_ascii=False)}
            ]
        })

    random.shuffle(dataset)

    # Chia 90% Train / 10% Val
    split_idx = int(TOTAL * 0.90)
    train_data = dataset[:split_idx]
    val_data = dataset[split_idx:]

    data_dir = Path(r"d:\vn-travel-planner\data")
    train_file = data_dir / "train_nlu.jsonl"
    val_file = data_dir / "val_nlu.jsonl"

    for path, d in [(train_file, train_data), (val_file, val_data)]:
        with open(path, "w", encoding="utf-8") as f:
            for item in d:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"✅ Đã tạo thành công {len(dataset)} mẫu NLU V4 (Train: {len(train_data)}, Val: {len(val_data)})")

if __name__ == "__main__":
    main()
