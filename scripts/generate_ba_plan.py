"""
scripts/generate_ba_plan.py

Milestone M1 (R1: Lead BA Planning & Strategy)
Generates comprehensive search keyword catalog and quota distribution for the 25 remaining provinces
using Claude Sonnet 4.6 via VyceAI Proxy (scripts/ba_agent.py).

Output: data/ba_remaining_provinces_plan.json
"""

import os
import sys
import json
import time
import sqlite3
from datetime import datetime, timezone
from typing import Dict, Any, List

sys.stdout.reconfigure(line_buffering=True)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scripts.ba_agent import ask_ba_json
from scripts.mapping_config import MAPPING_63_TO_34, FALLBACK_RULES

DB_PATH = os.path.join(ROOT_DIR, "travel_db.db")
DATA_DIR = os.path.join(ROOT_DIR, "data")
OUTPUT_PLAN_FILE = os.path.join(DATA_DIR, "ba_remaining_provinces_plan.json")

TARGET_PROVINCE_CODES = [
    4, 8, 11, 12, 14, 15, 19, 20, 24, 25,
    33, 37, 38, 40, 42, 44, 51, 52, 66, 75,
    80, 82, 86, 91, 96
]

CATEGORIES = ["RESTAURANT", "ACTIVITY", "MARKET", "ATTRACTION", "HOTEL"]

def get_province_metadata() -> Dict[int, Dict[str, Any]]:
    """Lấy thông tin 25 tỉnh đích từ travel_db.db và cấu hình ánh xạ 63->34."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT code, name, codename, province_type, scrape_limit
        FROM provinces
        WHERE code IN ({})
        ORDER BY code
    """.format(",".join(str(c) for c in TARGET_PROVINCE_CODES)))
    rows = cursor.fetchall()
    conn.close()

    # Nhóm các địa danh cũ cấu thành từng tỉnh mới
    sub_map: Dict[int, List[str]] = {}
    region_map: Dict[int, str] = {}
    for old_name, info in MAPPING_63_TO_34.items():
        c = info["target_code"]
        sub_map.setdefault(c, []).append(old_name)
        if c not in region_map:
            region_map[c] = info["region"]

    provinces: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        code, name, codename, p_type, limit = row
        subs = sub_map.get(code, [name.replace("Tỉnh ", "").replace("Thành phố ", "")])
        # Xác định chỉ tiêu quota (18 - 22 địa điểm tùy số tỉnh cũ cấu thành)
        if len(subs) == 1:
            total_quota = 18
            cat_quotas = {"RESTAURANT": 4, "ACTIVITY": 3, "MARKET": 3, "ATTRACTION": 4, "HOTEL": 4}
        elif len(subs) == 2:
            total_quota = 20
            cat_quotas = {"RESTAURANT": 4, "ACTIVITY": 4, "MARKET": 4, "ATTRACTION": 4, "HOTEL": 4}
        else:
            total_quota = 22
            cat_quotas = {"RESTAURANT": 5, "ACTIVITY": 4, "MARKET": 4, "ATTRACTION": 5, "HOTEL": 4}

        provinces[code] = {
            "code": code,
            "name": name,
            "codename": codename,
            "province_type": p_type,
            "region": region_map.get(code, "Việt Nam"),
            "sub_provinces": subs,
            "total_quota": total_quota,
            "category_quotas": cat_quotas
        }
    return provinces

def generate_plan_part1(p_info: Dict[str, Any], max_attempts: int = 3) -> Dict[str, Any]:
    """Sinh Phần 1: Danh lam thắng cảnh & Trải nghiệm giải trí (ATTRACTION & ACTIVITY) - 8 địa điểm."""
    code = p_info["code"]
    name = p_info["name"]
    subs = p_info["sub_provinces"]
    cat_quotas = p_info["category_quotas"]

    prompt = f"""Bạn là Lead BA của dự án VN Travel Planner. Lập danh sách {cat_quotas['ATTRACTION'] + cat_quotas['ACTIVITY']} địa điểm tiêu biểu cho {name} (sub_provinces: {json.dumps(subs, ensure_ascii=False)}) gồm:
- {cat_quotas['ATTRACTION']} ATTRACTION (danh lam thắng cảnh, check-in sáng)
- {cat_quotas['ACTIVITY']} ACTIVITY (vui chơi, trải nghiệm sinh thái, văn hóa làng nghề chiều)
Phân bổ đều cho các địa danh cũ cấu thành: {', '.join(subs)}.
Từ khóa query Google Maps phải chuẩn xác (tên địa danh + địa phương).
Trả về duy nhất JSON:
{{
  "morning_strategy": "Chiến lược tham quan sáng...",
  "afternoon_strategy": "Chiến lược hoạt động chiều...",
  "places": [
    {{"name": "...", "query": "...", "category": "ATTRACTION | ACTIVITY", "sub_province": "1 trong các sub_provinces", "rhythm_phase": "morning | afternoon"}}
  ]
}}"""

    for attempt in range(1, max_attempts + 1):
        res = ask_ba_json(prompt, model="claude-sonnet-4-6", timeout=60)
        if res and isinstance(res, dict) and "places" in res and len(res["places"]) >= 6:
            for p in res["places"]:
                p["category"] = str(p.get("category", "")).strip().upper()
            return res
        print(f"⚠️ [{code} - {name}] Lỗi Phần 1 (lần {attempt}), thử lại sau 3s...", flush=True)
        time.sleep(3)
    raise RuntimeError(f"Không thể sinh Phần 1 cho tỉnh {code} ({name})")

def generate_plan_part2(p_info: Dict[str, Any], max_attempts: int = 3) -> Dict[str, Any]:
    """Sinh Phần 2: Ẩm thực, Chợ & Khách sạn (RESTAURANT, MARKET, HOTEL) - 10-12 địa điểm."""
    code = p_info["code"]
    name = p_info["name"]
    subs = p_info["sub_provinces"]
    cat_quotas = p_info["category_quotas"]

    prompt = f"""Bạn là Lead BA của dự án VN Travel Planner. Lập danh sách {cat_quotas['RESTAURANT'] + cat_quotas['MARKET'] + cat_quotas['HOTEL']} địa điểm tiêu biểu cho {name} (sub_provinces: {json.dumps(subs, ensure_ascii=False)}) gồm:
- {cat_quotas['RESTAURANT']} RESTAURANT (ẩm thực đặc sản trưa và tối)
- {cat_quotas['MARKET']} MARKET (chợ truyền thống, chợ đêm mua đặc sản)
- {cat_quotas['HOTEL']} HOTEL (khách sạn, homestay nghỉ dưỡng check-in chiều)
Phân bổ đều cho các địa danh cũ cấu thành: {', '.join(subs)}.
Từ khóa query Google Maps phải chuẩn xác (tên địa danh + địa phương).
Trả về duy nhất JSON:
{{
  "noon_strategy": "Chiến lược ăn trưa đặc sản...",
  "evening_strategy": "Chiến lược ăn tối và dạo chợ đêm...",
  "places": [
    {{"name": "...", "query": "...", "category": "RESTAURANT | MARKET | HOTEL", "sub_province": "1 trong các sub_provinces", "rhythm_phase": "noon | afternoon | evening"}}
  ]
}}"""

    for attempt in range(1, max_attempts + 1):
        res = ask_ba_json(prompt, model="claude-sonnet-4-6", timeout=60)
        if res and isinstance(res, dict) and "places" in res and len(res["places"]) >= 8:
            for p in res["places"]:
                p["category"] = str(p.get("category", "")).strip().upper()
            return res
        print(f"⚠️ [{code} - {name}] Lỗi Phần 2 (lần {attempt}), thử lại sau 3s...", flush=True)
        time.sleep(3)
    raise RuntimeError(f"Không thể sinh Phần 2 cho tỉnh {code} ({name})")

def generate_plan_for_province(p_info: Dict[str, Any]) -> Dict[str, Any]:
    """Kết hợp Phần 1 và Phần 2 tạo thành kế hoạch hoàn chỉnh cho 1 tỉnh."""
    code = p_info["code"]
    name = p_info["name"]
    print(f"🔄 [{code} - {name}] Đang gọi Claude Sonnet 4.6 (Phần 1: Tham quan & Hoạt động)...", flush=True)
    p1 = generate_plan_part1(p_info)

    time.sleep(2)  # Tránh 429

    print(f"🔄 [{code} - {name}] Đang gọi Claude Sonnet 4.6 (Phần 2: Ẩm thực, Chợ & Lưu trú)...", flush=True)
    p2 = generate_plan_part2(p_info)

    combined_places = p1.get("places", []) + p2.get("places", [])
    
    # Chuẩn hóa metadata và gắn fallback rules
    cat_counts = {c: 0 for c in CATEGORIES}
    for p in combined_places:
        c = p.get("category")
        if c in cat_counts:
            cat_counts[c] += 1
        rule = FALLBACK_RULES.get(c, {"typical_time_spent": "60 phút", "price_range": "30.000đ - 100.000đ"})
        p["typical_time_spent"] = rule["typical_time_spent"]
        p["price_range"] = rule["price_range"]

    rhythm_strategy = {
        "morning": p1.get("morning_strategy", "Tham quan danh thắng cảnh quan và di tích lịch sử."),
        "noon": p2.get("noon_strategy", "Thưởng thức ẩm thực đặc sản truyền thống địa phương."),
        "afternoon": p1.get("afternoon_strategy", "Check-in khách sạn, nghỉ ngơi nhẹ và tham gia hoạt động trải nghiệm."),
        "evening": p2.get("evening_strategy", "Ăn tối đặc sản và dạo chợ đêm / phố đi bộ mua quà.")
    }

    full_plan = {
        "province_code": code,
        "province_name": name,
        "codename": p_info["codename"],
        "region": p_info["region"],
        "sub_provinces": p_info["sub_provinces"],
        "total_quota": len(combined_places),
        "category_quotas": cat_counts,
        "biological_rhythm_strategy": rhythm_strategy,
        "places": combined_places
    }

    valid = validate_province_plan(full_plan, code)
    if not valid:
        print(f"⚠️ Cảnh báo: Tỉnh {code} chưa đạt hoàn hảo 5 category, kiểm tra lại...")
    print(f"✅ [{code} - {name}] Hoàn thành: {len(combined_places)} địa điểm, các danh mục: {cat_counts}", flush=True)
    return full_plan

def validate_province_plan(data: Dict[str, Any], expected_code: int) -> bool:
    """Kiểm tra tính hợp lệ của dữ liệu kế hoạch do Claude Sonnet 4.6 sinh ra."""
    if not isinstance(data, dict):
        return False
    try:
        p_code = int(data.get("province_code", -1))
        if p_code != expected_code:
            return False
    except (ValueError, TypeError):
        return False

    places = data.get("places", [])
    if not isinstance(places, list) or len(places) < 15 or len(places) > 25:
        return False

    cats_found = set()
    for p in places:
        if not isinstance(p, dict):
            return False
        cat = str(p.get("category", "")).strip().upper()
        p["category"] = cat
        cats_found.add(cat)
        if not p.get("name") or not p.get("query"):
            return False

    # Phải đủ cả 5 danh mục
    for req_cat in CATEGORIES:
        if req_cat not in cats_found:
            return False

    rhythm = data.get("biological_rhythm_strategy", {})
    if not isinstance(rhythm, dict):
        return False
    rhythm_lower_keys = {k.lower() for k in rhythm.keys()}
    if not all(k in rhythm_lower_keys for k in ["morning", "noon", "afternoon", "evening"]):
        return False

    return True

def generate_all_provinces_plan() -> Dict[str, Any]:
    """Điều phối sinh kế hoạch tuần tự chuẩn hóa cho toàn bộ 25 tỉnh còn lại."""
    provinces_info = get_province_metadata()
    os.makedirs(DATA_DIR, exist_ok=True)

    # Đọc cache nếu có để hỗ trợ resume
    existing_plan: Dict[str, Any] = {}
    if os.path.exists(OUTPUT_PLAN_FILE):
        try:
            with open(OUTPUT_PLAN_FILE, "r", encoding="utf-8") as f:
                existing_plan = json.load(f)
        except Exception:
            existing_plan = {}

    completed_provinces = existing_plan.get("provinces", {})

    print(f"🚀 Bắt đầu lập kế hoạch Lead BA cho 25 tỉnh còn lại.")
    print(f"📌 Đã có sẵn {len(completed_provinces)}/25 tỉnh trong cache.")

    remaining_codes = [c for c in TARGET_PROVINCE_CODES if str(c) not in completed_provinces]

    for idx, code in enumerate(remaining_codes, 1):
        p_info = provinces_info[code]
        print(f"\n[{idx}/{len(remaining_codes)}] 📍 Bắt đầu tỉnh: {code} - {p_info['name']} (Tổng: {len(completed_provinces)}/25)", flush=True)
        try:
            result = generate_plan_for_province(p_info)
            completed_provinces[str(code)] = result
            # Lưu checkpoint ngay sau mỗi tỉnh hoàn thành
            full_output = {
                "plan_version": "1.0",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "generated_by": "Claude Sonnet 4.6 (Lead BA Agent)",
                "model": "claude-sonnet-4-6",
                "total_provinces": len(completed_provinces),
                "total_places_planned": sum(len(p.get("places", [])) for p in completed_provinces.values()),
                "target_province_codes": TARGET_PROVINCE_CODES,
                "biological_rhythm_rules": {
                    "morning": "Tham quan di tích, danh lam thắng cảnh, điểm ngắm cảnh (ATTRACTION)",
                    "noon": "Thưởng thức ẩm thực đặc sản địa phương, nhà hàng uy tín (RESTAURANT)",
                    "afternoon": "Check-in khách sạn/resort (HOTEL), nghỉ ngơi nhẹ, tham gia hoạt động trải nghiệm/vui chơi sinh thái (ACTIVITY / ATTRACTION)",
                    "evening": "Ăn tối đặc sản / hải sản (RESTAURANT), dạo chợ đêm, phố đi bộ, mua sắm đặc sản (MARKET)"
                },
                "provinces": completed_provinces
            }
            with open(OUTPUT_PLAN_FILE, "w", encoding="utf-8") as f:
                json.dump(full_output, f, ensure_ascii=False, indent=2)
            print(f"💾 Checkpoint: {len(completed_provinces)}/25 tỉnh đã được lưu an toàn.", flush=True)
            time.sleep(2)  # Delay nhẹ giữa các tỉnh
        except Exception as e:
            print(f"❌ Lỗi xử lý tỉnh code {code}: {e}", flush=True)

    with open(OUTPUT_PLAN_FILE, "r", encoding="utf-8") as f:
        final_plan = json.load(f)

    return final_plan

def validate_ba_plan_file(filepath: str = OUTPUT_PLAN_FILE) -> Dict[str, Any]:
    """Kiểm tra độc lập và báo cáo tính toàn vẹn của file ba_remaining_provinces_plan.json."""
    if not os.path.exists(filepath):
        return {"valid": False, "error": f"File không tồn tại: {filepath}"}

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return {"valid": False, "error": f"Không thể parse JSON: {e}"}

    provinces = data.get("provinces", {})
    if len(provinces) != 25:
        return {"valid": False, "error": f"Số lượng tỉnh không đủ 25 (hiện có {len(provinces)})"}

    errors = []
    total_places = 0
    category_totals = {c: 0 for c in CATEGORIES}

    for code_str, p_data in provinces.items():
        code = int(code_str)
        if code not in TARGET_PROVINCE_CODES:
            errors.append(f"Mã tỉnh không hợp lệ: {code}")
            continue

        places = p_data.get("places", [])
        p_len = len(places)
        total_places += p_len

        if p_len < 15 or p_len > 25:
            errors.append(f"Tỉnh {code} ({p_data.get('province_name')}) có số lượng places={p_len} ngoài dải [15, 25]")

        cats_in_p = set()
        for pl in places:
            cat = pl.get("category")
            if cat not in CATEGORIES:
                errors.append(f"Tỉnh {code}: Category lạ '{cat}' tại place '{pl.get('name')}'")
            else:
                cats_in_p.add(cat)
                category_totals[cat] += 1

            if not pl.get("name") or not pl.get("query"):
                errors.append(f"Tỉnh {code}: Place thiếu name hoặc query: {pl}")

        missing_cats = set(CATEGORIES) - cats_in_p
        if missing_cats:
            errors.append(f"Tỉnh {code} ({p_data.get('province_name')}) thiếu category: {missing_cats}")

        rhythm = p_data.get("biological_rhythm_strategy", {})
        if not all(k in rhythm for k in ["morning", "noon", "afternoon", "evening"]):
            errors.append(f"Tỉnh {code}: Thiếu chiến lược nhịp sinh học đầy đủ")

    if total_places < 350:
        errors.append(f"Tổng số địa điểm {total_places} nhỏ hơn ngưỡng tối thiểu 350+")

    is_valid = len(errors) == 0
    return {
        "valid": is_valid,
        "total_provinces": len(provinces),
        "total_places": total_places,
        "category_breakdown": category_totals,
        "errors_count": len(errors),
        "errors": errors[:10]
    }

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Lead BA Planning Generator")
    parser.add_argument("--validate", action="store_true", help="Chỉ kiểm tra tính hợp lệ của file plan hiện có")
    args = parser.parse_args()

    if args.validate:
        res = validate_ba_plan_file()
        print("🔍 Kết quả kiểm tra file plan:")
        print(json.dumps(res, ensure_ascii=False, indent=2))
        sys.exit(0 if res["valid"] else 1)

    plan = generate_all_provinces_plan()
    val_res = validate_ba_plan_file()
    print("\n" + "="*60)
    print("🏆 BÁO CÁO TỔNG KẾT LEAD BA PLANNING (M1):")
    print(f"- Trạng thái hợp lệ: {'✅ ĐẠT' if val_res['valid'] else '❌ KHÔNG ĐẠT'}")
    print(f"- Số tỉnh bao phủ: {val_res['total_provinces']} / 25")
    print(f"- Tổng số địa điểm được lên kế hoạch: {val_res['total_places']} (Yêu cầu: >= 350)")
    print(f"- Phân bổ danh mục:")
    for cat, cnt in val_res["category_breakdown"].items():
        print(f"  + {cat}: {cnt} địa điểm")
    print("="*60)
    sys.exit(0 if val_res["valid"] else 1)
