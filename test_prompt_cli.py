"""
test_prompt_cli.py
═══════════════════════════════════════════════════════════════════════════════
Công cụ Terminal chuyên dụng để test NLU prompt và trả ra JSON chuẩn y hệt lúc train.
Sử dụng:
  python test_prompt_cli.py "câu prompt của bạn"
  python test_prompt_cli.py --model vn-travel-qwen:7b "câu prompt"
  python test_prompt_cli.py  (Chế độ tương tác gõ liên tục)
═══════════════════════════════════════════════════════════════════════════════
"""

import sys
import json
import argparse
import urllib.request
import urllib.error

OLLAMA_URL = "http://localhost:11434/api/chat"

SYSTEM_PROMPT = (
    "Bạn là NLU Engine chuyên dụng cho hệ thống Travel AI Việt Nam.\n"
    "Nhiệm vụ: Phân tích yêu cầu của người dùng và trích xuất thành định dạng JSON chuẩn.\n"
    "Quy tắc:\n"
    "1. Chỉ trả về duy nhất chuỗi JSON hợp lệ bắt đầu bằng '{' và kết thúc bằng '}', không kèm markdown hay lời dẫn.\n"
    "2. Xác định đúng intent trong các loại: 'plan_itinerary', 'search_place', 'ask_advisory', 'clarify_needed'.\n"
    "3. Nếu người dùng không đề cập thông tin nào, trường tương ứng BẮT BUỘC để null (hoặc [] với mảng). Tuyệt đối không tự suy diễn số liệu.\n"
    "4. 'destination' CHỈ điền khi người dùng nêu rõ một tỉnh/thành/địa danh cụ thể (chuẩn hóa về tên tỉnh/thành). Nếu người dùng chỉ nói vùng miền hoặc loại địa hình (vd: 'phía Bắc', 'đi biển', 'núi'), để destination = null và điền 'destination_regions' / 'terrain_types'. TUYỆT ĐỐI không tự liệt kê tỉnh thay cho vùng miền.\n"
    "5. 'destination_regions' chỉ nhận: NORTH, NORTHWEST, NORTHEAST, RED_RIVER_DELTA, NORTH_CENTRAL, CENTRAL, SOUTH_CENTRAL, CENTRAL_HIGHLANDS, SOUTH, SOUTHEAST, MEKONG_DELTA. 'terrain_types' chỉ nhận: BEACH, ISLAND, MOUNTAIN, HIGHLAND, FOREST, CAVE, RIVER (xếp theo bảng chữ cái). Khi đã có destination cụ thể thì cả hai để [] và các từ như 'biển', 'núi' chỉ ghi vào preferences.\n"
    "6. Địa danh người dùng muốn LOẠI TRỪ (trừ, ngoại trừ, không đi, tránh, bỏ, chán, đi rồi, khỏi...) đưa vào 'excluded_destinations' (cấp tỉnh/thành) hoặc 'excluded_places' (địa danh nhỏ hơn tỉnh). Địa danh bị loại trừ KHÔNG BAO GIỜ được đưa vào destination, hard_pinned_locations hay preferences. Điểm xuất phát (origin) độc lập với danh sách loại trừ."
)


def call_ollama(prompt: str, model: str = "vn-travel-qwen-v2") -> str:
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
    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(OLLAMA_URL, data=data_bytes, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("message", {}).get("content", "").strip()
    except urllib.error.URLError as e:
        return f"[LỖI KẾT NỐI OLLAMA] Không kết nối được {OLLAMA_URL}. Hãy chạy 'ollama serve'. Chi tiết: {e}"
    except Exception as e:
        return f"[LỖI] {e}"


def print_formatted_result(prompt: str, raw_output: str, model: str):
    print("\n" + "=" * 70)
    print(f"📝 PROMPT INPUT: \"{prompt}\"")
    print(f"🤖 MODEL       : {model}")
    print("=" * 70)
    print("📦 JSON ĐẦU RA Y HỆT LÚC TRAIN (RAW ASSISTANT CONTENT):")
    
    # Làm đẹp JSON nếu hợp lệ
    try:
        clean_text = raw_output
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        if clean_text.startswith("```"):
            clean_text = clean_text[3:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
        clean_text = clean_text.strip()
        
        parsed = json.loads(clean_text)
        print(json.dumps(parsed, indent=2, ensure_ascii=False))
        print("-" * 70)
        print("🔍 BÓC TÁCH CỐT LÕI:")
        print(f"  • Điểm xuất phát (origin)     : {parsed.get('origin')}")
        print(f"  • Điểm đến (destination)      : {parsed.get('destination')}")
        print(f"  • Thời gian (duration_days)   : {parsed.get('duration_days') or parsed.get('days')}")
        print(f"  • Số người (group_size)       : {parsed.get('group_size')}")
        print(f"  • Phương tiện (vehicle_type)  : {parsed.get('vehicle_type')}")
        print(f"  • Ưu tiên bay (prefer_flight) : {parsed.get('prefer_flight')}")
        print(f"  • Sở thích (preferences)      : {parsed.get('preferences')}")
        print(f"  • Loại trừ (excluded)         : {parsed.get('excluded_activities')}")
    except Exception:
        print(raw_output)
    print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Test prompt NLU trực tiếp với format training.")
    parser.add_argument("prompt", nargs="?", type=str, help="Câu prompt cần test")
    parser.add_argument("--model", type=str, default="vn-travel-qwen-v2", help="Tên model trong Ollama (vn-travel-qwen-v2 hoặc vn-travel-qwen:7b)")
    args = parser.parse_args()

    if args.prompt:
        output = call_ollama(args.prompt, model=args.model)
        print_formatted_result(args.prompt, output, args.model)
    else:
        print("\n" + "=" * 70)
        print(f"🚀 CHẾ ĐỘ TEST PROMPT TƯƠNG TÁC (Model: {args.model})")
        print("Gõ câu prompt của bạn và nhấn Enter. Gõ 'exit' hoặc 'q' để thoát.")
        print("=" * 70)
        while True:
            try:
                user_input = input("\n👉 Nhập prompt: ").strip()
                if not user_input:
                    continue
                if user_input.lower() in ["exit", "q", "quit"]:
                    print("Tạm biệt!")
                    break
                output = call_ollama(user_input, model=args.model)
                print_formatted_result(user_input, output, args.model)
            except (KeyboardInterrupt, EOFError):
                print("\nĐã thoát.")
                break


if __name__ == "__main__":
    main()
