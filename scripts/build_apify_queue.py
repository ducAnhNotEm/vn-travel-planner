"""
Build Apify Scraping Queue from VQA Knowledge Base.
Filters out places already in travel_db.db and noisy entries.
Ranks genuine new tourist spots by prominence (photo count & metadata completeness).
"""
import sqlite3
import json
import unicodedata
import re
import os

def normalize_name(text: str) -> str:
    if not text:
        return ""
    text = text.lower().strip()
    for prefix in [
        "khu du lịch", "khu di tích", "chùa", "đền", "bãi biển",
        "đỉnh", "núi", "vịnh", "cột cờ", "cột mốc", "thác", "hồ"
    ]:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    text = unicodedata.normalize("NFC", text)
    return re.sub(r"[^a-z0-9à-ỹ\s]", "", text).strip()

def build_queue():
    # 1. Lấy danh sách tên địa điểm đã có trong travel_db.db
    conn = sqlite3.connect("travel_db.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM places")
    db_places = cursor.fetchall()
    db_names = set(normalize_name(r[1]) for r in db_places)
    conn.close()

    # 2. Đọc kho VQA đã gom cụm
    with open("data/vqa_clustered_places.json", "r", encoding="utf-8") as f:
        vqa_places = json.load(f)

    STOPWORDS = {
        "địa danh chưa xác định", "bức ảnh này cho tôi", "nó", "ảnh này",
        "địa điểm", "vị trí", "khung cảnh", "hình ảnh", "chưa rõ", "bức ảnh"
    }

    queue = []
    for raw_name, data in vqa_places.items():
        n = normalize_name(raw_name)
        if len(n) < 3 or n in STOPWORDS or any(sw in raw_name.lower() for sw in STOPWORDS):
            continue

        # Bỏ qua nếu đã có trong DB
        if n in db_names:
            continue
        if any(n in db_n or db_n in n for db_n in db_names if len(db_n) > 4 and len(n) > 4):
            continue

        province = data.get("province", "Việt Nam")
        coords = data.get("coords")
        photos_count = data.get("total_photos", 1)
        hero_id = data.get("best_hero_image_id")
        
        # Tags tổng hợp
        tags = (
            data.get("aggregated_climates", []) +
            data.get("aggregated_terrain", []) +
            data.get("aggregated_activities", []) +
            data.get("aggregated_culture", [])
        )

        clean_tags = [t.strip().lower() for t in tags if len(t.strip()) > 2 and t.strip().lower() not in ("vực", "quân đội")]
        dedup_tags = list(dict.fromkeys(clean_tags))

        # Search query chuẩn Google Maps
        clean_name = raw_name.replace("(Cực Tây)", "").replace("(Quy Nhơn)", "").strip()
        search_query = f"{clean_name}, {province}" if province != "Việt Nam" and province not in clean_name else clean_name

        queue.append({
            "canonical_name": clean_name,
            "province": province,
            "search_query": search_query,
            "total_vqa_photos": photos_count,
            "suggested_coords": coords,
            "vqa_hero_image_id": hero_id,
            "vqa_tags": dedup_tags,
            "hero_visual_desc": data.get("hero_visual_desc", "")
        })

    # Sắp xếp theo mức độ nổi tiếng (số lượng ảnh được chụp nhiều nhất trong VQA)
    queue.sort(key=lambda x: (x["total_vqa_photos"], len(x["vqa_tags"])), reverse=True)

    out_path = "data/apify_candidates_queue.json"
    os.makedirs("data", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)

    print("=" * 75)
    print(f"ĐÃ TẠO HÀNG ĐỢI CÀO APIFY: {len(queue):,} ĐỊA DANH MỚI TIỀM NĂNG")
    print(f"File lưu trữ: {out_path}")
    print("=" * 75)

    print("\nTop 10 địa danh mới nổi bật nhất xếp đầu hàng đợi:")
    for idx, item in enumerate(queue[:10], 1):
        print(f"[{idx:02d}] 📍 {item['canonical_name']} ({item['province']})")
        print(f"     🔎 Query Google Maps: \"{item['search_query']}\"")
        print(f"     📸 {item['total_vqa_photos']} ảnh VQA | Hero ID dự phòng: {item['vqa_hero_image_id']}")
        print(f"     🏷️ Tags sẵn sàng: {item['vqa_tags'][:5]}")
        print("-" * 75)

if __name__ == "__main__":
    build_queue()
