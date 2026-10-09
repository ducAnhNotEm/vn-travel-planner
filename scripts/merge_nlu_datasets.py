"""
merge_nlu_datasets.py
═══════════════════════════════════════════════════════════════════════════════
Script hợp nhất các tập dữ liệu huấn luyện NLU:
- data/train_nlu.jsonl (Tập v1: 811 mẫu phong phú)
- data/train_nlu_v2_pure.jsonl (Tập v2: 128 mẫu đối kháng đảo ngữ/phủ định)

Đầu ra:
- data/train_nlu_master.jsonl (Tập Master hợp nhất, khử trùng lặp, kiểm định schema 100%)
═══════════════════════════════════════════════════════════════════════════════
"""

import os
import json
from typing import Set, List, Dict, Any

INPUT_FILES = [
    "data/train_nlu.jsonl",
    "data/train_nlu_v2_pure.jsonl"
]
OUTPUT_FILE = "data/train_nlu_master.jsonl"


def normalize_prompt_key(text: str) -> str:
    return " ".join(text.strip().lower().split())


def merge_datasets():
    seen_prompts: Set[str] = set()
    master_records: List[Dict[str, Any]] = []
    skipped_duplicates = 0
    invalid_records = 0

    print("=" * 70)
    print("🚀 BẮT ĐẦU HỢP NHẤT CÁC TẬP DỮ LIỆU NLU")
    print("=" * 70)

    for filepath in INPUT_FILES:
        if not os.path.exists(filepath):
            print(f"⚠️  Không tìm thấy tệp: {filepath}")
            continue

        file_count = 0
        with open(filepath, "r", encoding="utf-8") as f:
            for line_idx, line in enumerate(f, 1):
                line_str = line.strip()
                if not line_str:
                    continue

                try:
                    record = json.loads(line_str)
                    messages = record.get("messages", [])
                    if len(messages) < 3:
                        invalid_records += 1
                        continue

                    user_msg = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
                    asst_msg = next((m.get("content", "") for m in messages if m.get("role") == "assistant"), "")

                    if not user_msg or not asst_msg:
                        invalid_records += 1
                        continue

                    # Kiểm tra tính hợp lệ của JSON assistant
                    json.loads(asst_msg)

                    prompt_key = normalize_prompt_key(user_msg)
                    if prompt_key in seen_prompts:
                        skipped_duplicates += 1
                        continue

                    seen_prompts.add(prompt_key)
                    master_records.append(record)
                    file_count += 1

                except Exception as e:
                    print(f"  ❌ Lỗi tại dòng {line_idx} trong {filepath}: {e}")
                    invalid_records += 1

        print(f"  [x] Đã nạp thành công từ {filepath}: {file_count} mẫu câu hợp lệ.")

    # Ghi vào file master
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as out_f:
        for rec in master_records:
            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print("-" * 70)
    print(f"🎉 HỢP NHẤT HOÀN TẤT THÀNH CÔNG RỰC RỠ!")
    print(f"📁 Tệp xuất xưởng : {OUTPUT_FILE}")
    print(f"📊 Tổng số mẫu    : {len(master_records)} mẫu câu")
    print(f"🧹 Trùng lặp bỏ qua: {skipped_duplicates}")
    print(f"⚠️  Mẫu lỗi bỏ qua : {invalid_records}")
    print("=" * 70)


if __name__ == "__main__":
    merge_datasets()
