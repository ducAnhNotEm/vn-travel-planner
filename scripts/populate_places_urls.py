"""
scripts/populate_places_urls.py

Nạp đường dẫn Google Maps (google_maps_url) xác thực vào travel_db.db.
Tuân thủ nghiêm ngặt Thiết luật (Iron Laws) trong AGENTS.md & PROJECT_CONTEXT.md:
1. Ground-Truth Only: Chỉ nạp URL khi có Google Place ID thật (ChIJ...) hoặc URL trích xuất từ scraper.
2. Zero Hallucination: Tuyệt đối KHÔNG tự ý ghép chuỗi tìm kiếm giả dạng 'https://www.google.com/maps/search/?api=1&query=...'.
3. Transparency: Địa điểm nào chưa có Place ID hoặc URL xác thực bắt buộc để NULL.
"""

import os
import sys
import json
import sqlite3
from typing import Dict, Tuple, Optional

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT_DIR, "travel_db.db")
DATA_DIR = os.path.join(ROOT_DIR, "data")


def load_offline_cache() -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Quét toàn bộ kho cache offline để lấy URL Google Maps và Website chính thức.
    Returns: (place_id_to_url, place_id_to_website)
    """
    id_to_url: Dict[str, str] = {}
    id_to_web: Dict[str, str] = {}

    def extract_from_obj(it: dict):
        pid = it.get("placeId") or it.get("google_place_id")
        if not pid or not isinstance(pid, str) or not pid.startswith("ChIJ"):
            return
        
        # URL Google Maps thật từ scraper
        url = it.get("url")
        if url and isinstance(url, str) and url.startswith("http"):
            id_to_url[pid] = url
        
        # Website thật
        web = it.get("website")
        if web and isinstance(web, str) and web.startswith("http"):
            id_to_web[pid] = web

    # 1. Quét crawled_google_places_cache.json
    cache_places = os.path.join(DATA_DIR, "crawled_google_places_cache.json")
    if os.path.exists(cache_places):
        try:
            with open(cache_places, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                for item in data: extract_from_obj(item)
            elif isinstance(data, dict):
                for item in data.values():
                    if isinstance(item, dict): extract_from_obj(item)
        except Exception as e:
            print(f"⚠️ Lỗi đọc {cache_places}: {e}")

    # 2. Quét crawled_major_cities_cache.json
    cache_major = os.path.join(DATA_DIR, "crawled_major_cities_cache.json")
    if os.path.exists(cache_major):
        try:
            with open(cache_major, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                for item in data: extract_from_obj(item)
            elif isinstance(data, dict):
                for item in data.values():
                    if isinstance(item, dict): extract_from_obj(item)
        except Exception as e:
            print(f"⚠️ Lỗi đọc {cache_major}: {e}")

    # 3. Quét toàn bộ 25 file raw cache của 25 tỉnh
    raw_dir = os.path.join(DATA_DIR, "raw_remaining_provinces")
    if os.path.exists(raw_dir):
        for fname in os.listdir(raw_dir):
            if fname.endswith(".json"):
                fpath = os.path.join(raw_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        items = json.load(f)
                    if isinstance(items, list):
                        for item in items: extract_from_obj(item)
                except Exception as e:
                    print(f"⚠️ Lỗi đọc {fpath}: {e}")

    print(f"📦 Đã quét offline cache: Tìm thấy {len(id_to_url)} URL Google Maps và {len(id_to_web)} Website xác thực.")
    return id_to_url, id_to_web


def migrate_and_populate():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 1. Thêm cột google_maps_url nếu chưa có (idempotent)
    existing_cols = [r[1] for r in c.execute("PRAGMA table_info(places)").fetchall()]
    if "google_maps_url" not in existing_cols:
        c.execute("ALTER TABLE places ADD COLUMN google_maps_url VARCHAR(500)")
        print("✅ Đã thêm cột google_maps_url vào bảng places.")
    else:
        print("⏭ Cột google_maps_url đã tồn tại trong bảng places.")

    # 2. Đọc offline cache
    id_to_url, id_to_web = load_offline_cache()

    # 3. Lấy toàn bộ địa danh
    c.execute("SELECT id, name, google_place_id, website FROM places")
    rows = c.fetchall()
    total_places = len(rows)

    updated_urls = 0
    updated_webs = 0
    null_urls = 0

    for place_id, name, g_place_id, current_web in rows:
        target_url = None
        target_web = None

        # Quy tắc bất biến: Chỉ gán URL khi có Google Place ID thật (ChIJ...)
        if g_place_id and isinstance(g_place_id, str) and g_place_id.startswith("ChIJ"):
            if g_place_id in id_to_url:
                target_url = id_to_url[g_place_id]
            else:
                # Chuẩn URL chính thức của Google cho Place ID
                target_url = f"https://www.google.com/maps/place/?q=place_id:{g_place_id}"

            # Backfill website nếu DB đang thiếu
            if (not current_web or current_web.strip() == "") and g_place_id in id_to_web:
                target_web = id_to_web[g_place_id]

        if target_url:
            if target_web:
                c.execute("UPDATE places SET google_maps_url = ?, website = ? WHERE id = ?", (target_url, target_web, place_id))
                updated_webs += 1
            else:
                c.execute("UPDATE places SET google_maps_url = ? WHERE id = ?", (target_url, place_id))
            updated_urls += 1
        else:
            # Tuyệt đối để NULL nếu không có Place ID xác thực - CẤM TẠO ẢO GIÁC
            c.execute("UPDATE places SET google_maps_url = NULL WHERE id = ?", (place_id,))
            null_urls += 1

    conn.commit()

    # 4. Kiểm tra thống kê
    c.execute("SELECT COUNT(*) FROM places WHERE google_maps_url IS NOT NULL")
    total_with_url = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM places WHERE google_maps_url IS NULL")
    total_null_url = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM places WHERE website IS NOT NULL AND length(trim(website)) > 0")
    total_with_web = c.fetchone()[0]

    conn.close()

    print("\n" + "=" * 65)
    print("📊 BÁO CÁO KẾT QUẢ POPULATE GOOGLE MAPS URL (GROUND-TRUTH ONLY)")
    print("=" * 65)
    print(f"Tổng số địa danh trong database:          {total_places}")
    print(f"Số địa danh có URL Google Maps xác thực:   {total_with_url} ({total_with_url/total_places*100:.2f}%)")
    print(f"Số địa danh để NULL (chưa có Place ID):   {total_null_url} ({total_null_url/total_places*100:.2f}%)")
    print(f"Số địa danh có Website chính thức:        {total_with_web}")
    print(f"Số website mới được backfill:             {updated_webs}")
    print("=" * 65)
    print("✅ Đã hoàn thành nạp URL theo đúng Thiết luật Zero-Hallucination!")


if __name__ == "__main__":
    migrate_and_populate()
