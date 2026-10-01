"""
VN Travel Planner — Adversarial Benchmark Generator (Top 0.01% Standard)
========================================================================
Xuất file adversarial_nlu_benchmark.jsonl phục vụ việc chấm điểm
Semantic Field-Level Accuracy & Minimal Pairs trên checkpoint Qwen 7B.
"""

import json
from pathlib import Path
from tests.test_semantic_nlu_benchmarks import MINIMAL_PAIRS_TEST_CASES

SYSTEM_PROMPT = """Bạn là NLU Engine chuyên dụng cho hệ thống Travel AI Việt Nam.
Nhiệm vụ: Phân tích yêu cầu của người dùng và trích xuất thành định dạng JSON chuẩn.
Quy tắc:
1. Chỉ trả về duy nhất chuỗi JSON hợp lệ bắt đầu bằng '{' và kết thúc bằng '}', không kèm markdown hay lời dẫn.
2. Xác định đúng intent trong các loại: 'plan_itinerary', 'search_place', 'ask_advisory', 'clarify_needed'.
3. Nếu người dùng không đề cập thông tin nào, trường tương ứng BẮT BUỘC để null (hoặc [] với mảng). Tuyệt đối không tự suy diễn số liệu.
4. Ghi nhận trung thực 100% mong muốn của người dùng. Nếu người dùng nhắc đến vị trí hiện tại ('từ đây', 'từ chỗ tôi'), origin là 'CURRENT_LOCATION'."""

def export_adversarial_set():
    benchmark_data = []
    for tc in MINIMAL_PAIRS_TEST_CASES:
        benchmark_data.append({
            "test_id": tc["id"],
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": tc["input"]},
                {"role": "assistant", "content": json.dumps(tc["expected"], ensure_ascii=False)}
            ]
        })

    out_path = Path(r"d:\vn-travel-planner\data\adversarial_nlu_benchmark.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        for item in benchmark_data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"✅ Đã xuất {len(benchmark_data)} ca kiểm thử Minimal Pairs vào: {out_path}")

if __name__ == "__main__":
    export_adversarial_set()
