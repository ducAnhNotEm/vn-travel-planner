"""
scripts/clean_and_filter_data.py
Làm sạch dữ liệu toàn diện:
1. Lọc bỏ toàn bộ HOTEL, MARKET, RESTAURANT, SPECIALTY_FOOD, SEAFOOD khỏi các file JSON và database.
2. Chỉ giữ lại HISTORICAL_SITE, TEMPLE, ATTRACTION, BEACH (Di tích, Thắng cảnh, Chùa chiền, Đền miếu, Biển).
3. Đánh số lại ID tuần tự chuẩn cho places_63_to_34.json.
4. Đồng bộ sạch vào travel_db.db (xóa sạch các dữ liệu quán xá, khách sạn, chợ).
5. Xuất file data/apify_search_queries.json sẵn sàng để đưa vào Apify cào địa chỉ bưu chính và ảnh thật.
"""

import os
import sys
import json
import sqlite3

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT_DIR, "data")
DB_PATH = os.path.join(ROOT_DIR, "travel_db.db")

KEEP_CATEGORIES = {"HISTORICAL_SITE", "TEMPLE", "ATTRACTION", "BEACH"}

def filter_json_file(filename: str):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        print(f"File {filename} không tồn tại, bỏ qua.")
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    before_len = len(data)
    filtered = [p for p in data if p.get("category") in KEEP_CATEGORIES]
    
    with open(path, "w", encoding="utf-8") as f:
        json.dump(filtered, f, ensure_ascii=False, indent=2)
    
    print(f"✓ Đã làm sạch {filename}: {before_len} -> {len(filtered)} địa điểm (giảm {before_len - len(filtered)})")
    return filtered

def reindex_and_clean_national():
    path = os.path.join(DATA_DIR, "places_63_to_34.json")
    with open(path, "r", encoding="utf-8") as f:
        places = json.load(f)
    
    # Lọc danh mục
    filtered = [p for p in places if p.get("category") in KEEP_CATEGORIES]
    
    # Đánh lại ID tuần tự từ 1001
    for idx, p in enumerate(filtered, start=1001):
        p["id"] = idx
    
    with open(path, "w", encoding="utf-8") as f:
        json.dump(filtered, f, ensure_ascii=False, indent=2)
    
    print(f"✓ Đã cập nhật data/places_63_to_34.json: {len(filtered)} di tích & danh thắng chuẩn.")
    return filtered

def sync_clean_database(places):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Xóa các địa điểm ID <= 20 mà không thuộc di tích/chùa (xóa quán ăn, khách sạn, chợ)
    cur.execute("""
        DELETE FROM places 
        WHERE category NOT IN ('HISTORICAL_SITE', 'TEMPLE', 'ATTRACTION', 'BEACH')
    """)
    removed_non_heritage = cur.rowcount
    
    # Xóa toàn bộ địa điểm từ 1001 trở đi để nạp lại bản sạch
    cur.execute("DELETE FROM places WHERE id >= 1001")
    
    insert_sql = """
        INSERT INTO places (
            id, google_place_id, province_code, ward_code, name, category,
            is_must_visit, badge_label, lat, lng, address, rating, review_count,
            image_url, typical_time_spent, popular_times, tags, price_range, prices
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    
    rows = []
    for p in places:
        pid = p["id"]
        google_id = f"wiki_vn_{pid}"
        prov_code = p["target_province_code"]
        ward_code = p.get("target_ward_code")
        name = p["name"]
        cat = p["category"]
        is_mv = 1 if p.get("is_must_visit") else 0
        badge = p.get("badge_label")
        lat = float(p["lat"])
        lng = float(p["lng"])
        addr = f"{p['name']}, {p['original_province']}"
        rating = 4.6 if p.get("is_must_visit") else 4.2
        review_count = 120 if p.get("is_must_visit") else 45
        image_url = p.get("photo_url")
        time_spent = p.get("typical_time_spent") or "90 phút"
        pop_times = None
        tags = json.dumps([p["category"].lower(), p["region"].lower()], ensure_ascii=False)
        price_range = p.get("price_range") or "0 VND / Miễn phí"
        prices = None
        
        rows.append((
            pid, google_id, prov_code, ward_code, name, cat,
            is_mv, badge, lat, lng, addr, rating, review_count,
            image_url, time_spent, pop_times, tags, price_range, prices
        ))
        
    cur.executemany(insert_sql, rows)
    conn.commit()
    
    # Thống kê
    cur.execute("SELECT count(*) FROM places")
    total_db = cur.fetchone()[0]
    cur.execute("PRAGMA foreign_key_check")
    fk_errors = cur.fetchall()
    conn.close()
    
    print(f"✓ Đồng bộ thành công travel_db.db:")
    print(f"  - Đã loại bỏ {removed_non_heritage} khách sạn, chợ, quán ăn.")
    print(f"  - Tổng số địa điểm danh thắng/di tích hiện tại trong DB: {total_db}")
    print(f"  - Lỗi khóa ngoại (FK violations): {len(fk_errors)}")

def export_apify_queries(places):
    """Xuất danh sách truy vấn chuẩn bị cho Apify Google Maps Scraper"""
    queries = []
    for p in places:
        name = p["name"]
        prov = p["original_province"]
        # Thêm từ khóa ngữ cảnh nếu tên quá ngắn
        q = f"{name} {prov}"
        queries.append({
            "id": p["id"],
            "name": name,
            "province": prov,
            "query": q,
            "category": p["category"]
        })
    
    out_path = os.path.join(DATA_DIR, "apify_search_queries.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(queries, f, ensure_ascii=False, indent=2)
    
    print(f"✓ Đã xuất {len(queries)} câu truy vấn vào data/apify_search_queries.json (sẵn sàng ném vào Apify)")

def main():
    print("=" * 60)
    print(" BẮT ĐẦU LÀM SẠCH DỮ LIỆU TOÀN DIỆN (CHỈ GIỮ DANH THẮNG/DI TÍCH)")
    print("=" * 60)
    filter_json_file("places_north.json")
    filter_json_file("places_central.json")
    filter_json_file("places_south.json")
    cleaned_places = reindex_and_clean_national()
    sync_clean_database(cleaned_places)
    export_apify_queries(cleaned_places)
    print("=" * 60)
    print(" HOÀN TẤT LÀM SẠCH DỮ LIỆU!")

if __name__ == "__main__":
    main()
