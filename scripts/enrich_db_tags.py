"""
Enrich travel_db.db places with rich semantic tags from VQA Knowledge Base.
Preserves existing tags, merges climate, terrain, activity, and cultural facets.
Safely backs up database before execution.
"""
import shutil
import sqlite3
import json
import unicodedata
import re

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

def run_enrichment():
    db_path = "travel_db.db"
    backup_path = "travel_db.db.bak"
    shutil.copyfile(db_path, backup_path)
    print(f"[*] Đã tạo bản sao lưu an toàn tại: {backup_path}")

    # Nạp kho tri thức VQA
    with open("data/vqa_clustered_places.json", "r", encoding="utf-8") as f:
        vqa_places = json.load(f)

    vqa_lookup = {}
    for raw_name, vqa_data in vqa_places.items():
        n = normalize_name(raw_name)
        if len(n) >= 3:
            vqa_lookup[n] = vqa_data

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, tags FROM places")
    db_places = cursor.fetchall()

    updated_count = 0
    # Danh sách từ loại bỏ vì quá thô hoặc mơ hồ
    NOISY_TAGS = {"vực", "quân đội"}

    for place_id, name, current_tags_json in db_places:
        norm_db = normalize_name(name)
        if len(norm_db) < 3:
            continue

        matched_vqa = None
        # Exact match
        if norm_db in vqa_lookup:
            matched_vqa = vqa_lookup[norm_db]
        else:
            # Substring match for longer names
            for norm_vqa, vqa_data in vqa_lookup.items():
                if (len(norm_vqa) > 4 and norm_vqa in norm_db) or (len(norm_db) > 4 and norm_db in norm_vqa):
                    matched_vqa = vqa_data
                    break

        if not matched_vqa:
            continue

        # Đọc tags hiện tại
        try:
            existing_tags = json.loads(current_tags_json) if current_tags_json else []
            if not isinstance(existing_tags, list):
                existing_tags = [str(existing_tags)]
        except Exception:
            existing_tags = []

        # Tổng hợp tags mới từ VQA
        candidate_tags = (
            matched_vqa.get("aggregated_climates", []) +
            matched_vqa.get("aggregated_terrain", []) +
            matched_vqa.get("aggregated_activities", []) +
            matched_vqa.get("aggregated_culture", [])
        )

        clean_candidate_tags = [t.strip().lower() for t in candidate_tags if t.strip().lower() not in NOISY_TAGS]

        # Hợp nhất và loại trừ trùng lặp
        merged_tags = list(dict.fromkeys(existing_tags + clean_candidate_tags))

        # Nếu có thêm tag mới thì update
        if len(merged_tags) > len(existing_tags):
            cursor.execute(
                "UPDATE places SET tags = ? WHERE id = ?",
                (json.dumps(merged_tags, ensure_ascii=False), place_id)
            )
            updated_count += 1

    conn.commit()
    conn.close()

    print(f"[+] Hoàn tất cập nhật tags cho {updated_count:,} / {len(db_places):,} địa điểm trong travel_db.db!")

if __name__ == "__main__":
    run_enrichment()
