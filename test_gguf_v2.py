"""
test_gguf_v2.py
═══════════════════════════════════════════════════════════════════════════════
BÀI TEST THẨM ĐỊNH MÔ HÌNH GGUF MỚI (Qwen2.5-7B-Instruct-v2.Q4_K_M.gguf)
Chuẩn Kỹ thuật Top 0.01%: Model Assurance, Contract Invariants & Minimal Pairs.

Sử dụng:
  python test_gguf_v2.py                    # Chạy kiểm thử tự động với Ollama
  python test_gguf_v2.py --model <tên_model> # Chỉ định model cụ thể (mặc định: vn-travel-qwen-v2)
  python test_gguf_v2.py --claude           # Chạy đối sánh với Claude 4.6 (Primary Cloud)
  python test_gguf_v2.py --dry-run          # Xem trước ma trận 10 ca kiểm thử đối nghịch
═══════════════════════════════════════════════════════════════════════════════
"""

import os
import sys
import json
import time
import argparse
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional, Tuple

# Import ma trận ca kiểm thử chuẩn từ test suite
from tests.test_semantic_nlu_benchmarks import ASSURANCE_TEST_CASES, ContractAssuranceScorer

GGUF_V2_FILE = "Qwen2.5-7B-Instruct-v2.Q4_K_M.gguf"
MODELFILE_V2 = "Modelfile_v2"
DEFAULT_MODEL_NAME = "vn-travel-qwen-v2"
OLLAMA_BASE_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

SYSTEM_PROMPT = (
    "Bạn là NLU Engine chuyên dụng cho hệ thống Travel AI Việt Nam.\n"
    "Nhiệm vụ: Phân tích yêu cầu của người dùng và trích xuất thành định dạng JSON chuẩn.\n"
    "Quy tắc:\n"
    "1. Chỉ trả về duy nhất chuỗi JSON hợp lệ bắt đầu bằng '{' và kết thúc bằng '}', không kèm markdown hay lời dẫn.\n"
    "2. Xác định đúng intent trong các loại: 'plan_itinerary', 'search_place', 'ask_advisory', 'clarify_needed'.\n"
    "3. Nếu người dùng không đề cập thông tin nào, trường tương ứng BẮT BUỘC để null (hoặc [] với mảng). Tuyệt đối không tự suy diễn số liệu."
)


def check_local_gguf_file():
    """Kiểm tra sự tồn tại của file GGUF v2 mới trong repository."""
    if os.path.exists(GGUF_V2_FILE):
        size_gb = os.path.getsize(GGUF_V2_FILE) / (1024 ** 3)
        print(f"  [x] File trọng số GGUF v2: {GGUF_V2_FILE} ({size_gb:.2f} GB) - TỒN TẠI")
        return True
    else:
        print(f"  [!] KHÔNG tìm thấy file {GGUF_V2_FILE} tại thư mục gốc.")
        return False


def check_ollama_server() -> Optional[List[str]]:
    """Kiểm tra Ollama server và lấy danh sách models đang có."""
    url = f"{OLLAMA_BASE_URL}/api/tags"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "VNTravel-Test"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name", "") for m in data.get("models", [])]
            return models
    except Exception:
        return None


Tuple_Result = Tuple[str, float, Optional[str]]


def call_ollama_chat(model: str, prompt: str, timeout: int = 30) -> Tuple_Result:
    """Gọi Ollama chat completion API và đo latency."""
    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "stream": False,
        "options": {
            "temperature": 0.0,
            "top_p": 0.9
        }
    }
    t0 = time.perf_counter()
    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data_bytes, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            dur_ms = (time.perf_counter() - t0) * 1000.0
            raw_body = json.loads(resp.read().decode("utf-8"))
            content = raw_body.get("message", {}).get("content", "").strip()
            return content, dur_ms, None
    except Exception as e:
        dur_ms = (time.perf_counter() - t0) * 1000.0
        return "", dur_ms, str(e)


def call_claude_reference(prompt: str) -> Tuple_Result:
    """Gọi Claude 4.6 (Primary Cloud) làm hệ quy chiếu."""
    from app.services.llm_service import call_llm
    t0 = time.perf_counter()
    res = call_llm(prompt=prompt, system_prompt=SYSTEM_PROMPT, temperature=0.0)
    dur_ms = (time.perf_counter() - t0) * 1000.0
    return res, dur_ms, None


def extract_json_from_response(raw_text: str) -> Optional[Dict[str, Any]]:
    """Trích xuất và làm sạch chuỗi JSON từ đầu ra của LLM."""
    text = raw_text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    start_idx = text.find("{")
    end_idx = text.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        json_str = text[start_idx:end_idx + 1]
        try:
            return json.loads(json_str)
        except Exception:
            return None
    return None


def print_dry_run_matrix():
    """In chi tiết 10 ca kiểm thử đối nghịch chuẩn mực."""
    print("\n" + "=" * 80)
    print("📋 MA TRẬN 10 CA KIỂM THỬ ĐỐI NGHỊCH (ASSURANCE BENCHMARK MATRIX)")
    print("=" * 80)
    for idx, tc in enumerate(ASSURANCE_TEST_CASES, 1):
        print(f"\n[TC {idx:02d}] {tc['id']}")
        print(f"  • Bẫy lỗi (Failure Mode)    : {tc['failure_mode']}")
        print(f"  • Câu lệnh kiểm thử (Input) : \"{tc['input']}\"")
        print(f"  • Kỳ vọng chuẩn (Expected)  : {json.dumps(tc['expected'], ensure_ascii=False)}")
        print(f"  • CẤM BỊA (Forbidden)       : {json.dumps(tc['forbidden_inferences'], ensure_ascii=False)}")
    print("\n" + "=" * 80)


def run_benchmark(model_name: str, use_claude: bool = False):
    """Thực thi toàn bộ bài kiểm thử trên mô hình."""
    target_display = "Claude 4.6 (Cloud Reference)" if use_claude else f"Ollama Local ({model_name})"
    print("\n" + "=" * 80)
    print(f"🚀 BẮT ĐẦU CHẠY BÀI TEST THẨM ĐỊNH MÔ HÌNH: {target_display}")
    print("=" * 80)

    scorer = ContractAssuranceScorer()
    latencies: List[float] = []

    for idx, tc in enumerate(ASSURANCE_TEST_CASES, 1):
        tc_id = tc["id"]
        user_input = tc["input"]
        print(f"\n--------------------------------------------------------------------------------")
        print(f"▶ [{idx:02d}/10] {tc_id}")
        print(f"  Input: \"{user_input}\"")

        if use_claude:
            raw_resp, dur_ms, err = call_claude_reference(user_input)
        else:
            raw_resp, dur_ms, err = call_ollama_chat(model_name, user_input)

        if err:
            print(f"  ❌ LỖI GỌI API ({dur_ms:.0f}ms): {err}")
            scorer.total += 1
            scorer.contract_violations.append({
                "test_id": tc_id,
                "failure_mode": tc["failure_mode"],
                "violation": f"API Call Failed: {err}",
                "input": user_input
            })
            continue

        latencies.append(dur_ms)
        parsed = extract_json_from_response(raw_resp)

        if parsed is None:
            print(f"  ❌ LỖI CÚ PHÁP ({dur_ms:.0f}ms): Không trích xuất được JSON hợp lệ!")
            print(f"     Raw: {raw_resp[:120]}...")
            scorer.total += 1
            scorer.contract_violations.append({
                "test_id": tc_id,
                "failure_mode": "syntax_error",
                "violation": "Output is not valid JSON",
                "input": user_input
            })
            continue

        # Đánh giá mẫu theo khế ước
        scorer.evaluate_sample(tc, parsed)

        # Kiểm tra xem ca này có bị vi phạm không
        recent_violation = next((v for v in scorer.contract_violations if v["test_id"] == tc_id), None)
        if recent_violation:
            print(f"  ⚠️  VI PHẠM KHẾ ƯỚC ({dur_ms:.0f}ms): {recent_violation['violation']}")
            print(f"     Output: {json.dumps(parsed, ensure_ascii=False)}")
        else:
            # So khớp toàn bộ field expected
            all_match = all(parsed.get(k) == v for k, v in tc["expected"].items())
            if all_match:
                print(f"  ✅ CHÍNH XÁC TUYỆT ĐỐI (EXACT MATCH) ({dur_ms:.0f}ms)")
                print(f"     Output: {json.dumps(parsed, ensure_ascii=False)}")
            else:
                print(f"  🟡 KHỚP MỘT PHẦN ({dur_ms:.0f}ms)")
                print(f"     Expected: {json.dumps(tc['expected'], ensure_ascii=False)}")
                print(f"     Actual  : {json.dumps(parsed, ensure_ascii=False)}")

    # In báo cáo tổng kết
    scorer.print_summary()

    if latencies:
        avg_lat = sum(latencies) / len(latencies)
        print(f"⏱️ ĐỘ TRỄ SUY LUẬN TRUNG BÌNH: {avg_lat:.1f}ms/câu (N={len(latencies)})")
    print("=" * 80 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Chạy bài test thẩm định mô hình GGUF v2 mới.")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL_NAME, help="Tên model trong Ollama")
    parser.add_argument("--claude", action="store_true", help="Chạy đối sánh với Claude 4.6 (Cloud Reference)")
    parser.add_argument("--dry-run", action="store_true", help="In danh sách 10 ca kiểm thử đối nghịch")
    args = parser.parse_args()

    print("\n" + "=" * 80)
    print("🛡️  HỆ THỐNG KIỂM ĐỊNH MÔ HÌNH VNTRAVEL AI — GGUF V2 ASSURANCE SUITE")
    print("=" * 80)

    # 1. Kiểm tra file GGUF vật lý
    check_local_gguf_file()

    # 2. Xử lý cờ --dry-run
    if args.dry_run:
        print_dry_run_matrix()
        return

    # 3. Xử lý cờ --claude (Cloud reference)
    if args.claude:
        run_benchmark(model_name="claude", use_claude=True)
        return

    # 4. Kiểm tra kết nối Ollama
    print(f"\n[1/3] Đang kiểm tra Ollama daemon tại {OLLAMA_BASE_URL}...")
    models = check_ollama_server()

    if models is None:
        print(f"\n❌ OLLAMA CHƯA ĐƯỢC BẬT HOẶC KHÔNG PHẢN HỒI TẠI {OLLAMA_BASE_URL}!")
        print("\n👉 CÁC BƯỚC ĐỂ BẬT VÀ NẠP MODEL GGUF V2 MỚI:")
        print("  ────────────────────────────────────────────────────────────────────────")
        print("  Bước 1: Khởi động Ollama Server:")
        print("          ollama serve")
        print(f"  Bước 2: Nạp mô hình GGUF v2 mới qua {MODELFILE_V2}:")
        print(f"          ollama create {args.model} -f {MODELFILE_V2}")
        print("  Bước 3: Chạy lại bài test này:")
        print(f"          python test_gguf_v2.py --model {args.model}")
        print("  ────────────────────────────────────────────────────────────────────────")
        print("\n💡 GỢI Ý: Bạn cũng có thể xem trước nội dung 10 ca kiểm thử ngay bây giờ:")
        print("          python test_gguf_v2.py --dry-run")
        print("       Hoặc chạy đối sánh ngay lập tức với Claude 4.6 (không cần Ollama):")
        print("          python test_gguf_v2.py --claude\n")
        return

    print(f"  [x] Kết nối Ollama thành công! Models hiện có: {models}")

    # 5. Kiểm tra model đích có trong Ollama không
    matching_model = next((m for m in models if args.model in m), None)
    if not matching_model:
        print(f"\n⚠️  CHƯA TÌM THẤY MODEL '{args.model}' TRONG OLLAMA!")
        print(f"👉 Vui lòng chạy lệnh nạp mô hình:")
        print(f"   ollama create {args.model} -f {MODELFILE_V2}\n")
        return

    # 6. Chạy benchmark
    run_benchmark(model_name=matching_model, use_claude=False)


if __name__ == "__main__":
    main()
