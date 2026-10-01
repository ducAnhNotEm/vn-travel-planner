import urllib.request
import json
import sys

prompt = "2 đứa mình tính đi Đà Lạt 3N2Đ từ Sài Gòn, đi xe máy, thích săn mây với ngắm hoàng hôn, không thích đi chùa"

system_prompt = (
    "Bạn là NLU Engine chuyên dụng cho hệ thống Travel AI Việt Nam.\n"
    "Nhiệm vụ: Phân tích yêu cầu của người dùng và trích xuất thành định dạng JSON chuẩn.\n"
    "Quy tắc:\n"
    "1. Chỉ trả về duy nhất chuỗi JSON hợp lệ bắt đầu bằng '{' và kết thúc bằng '}', không kèm markdown hay lời dẫn.\n"
    "2. Xác định đúng intent trong các loại: 'plan_itinerary', 'search_place', 'ask_advisory', 'clarify_needed'.\n"
    "3. Nếu người dùng không đề cập thông tin nào, trường tương ứng BẮT BUỘC để null (hoặc [] với mảng). Tuyệt đối không tự suy diễn số liệu."
)

data = {
    "model": "vn-travel-qwen:7b",
    "messages": [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}
    ],
    "stream": True,
    "options": {
        "temperature": 0.1
    }
}

req = urllib.request.Request(
    "http://localhost:11434/api/chat",
    data=json.dumps(data).encode("utf-8"),
    headers={"Content-Type": "application/json"}
)

print(f"=== ĐANG CHẠY TEST MODEL: vn-travel-qwen:7b ===")
print(f"PROMPT: {prompt}\n")
print("PHẢN HỒI:")

with urllib.request.urlopen(req) as resp:
    for line in resp:
        if not line:
            continue
        chunk = json.loads(line.decode("utf-8"))
        msg = chunk.get("message", {})
        content = msg.get("content", "")
        print(content, end="", flush=True)
        if chunk.get("done"):
            break

print("\n\n=== HOÀN TẤT ===")
