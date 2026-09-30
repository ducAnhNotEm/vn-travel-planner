import os
import sys
import json
import time
import requests
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

VYCEAI_API_KEY = os.getenv("VYCEAI_API_KEY")
VYCEAI_BASE_URL = os.getenv("VYCEAI_BASE_URL", "https://vyceai.com/v1")

if not VYCEAI_API_KEY:
    print("❌ Lỗi: Chưa cấu hình VYCEAI_API_KEY trong file .env!")
    sys.exit(1)

BA_SYSTEM_PROMPT = """Bạn là Business Analyst (BA) chính của dự án VN Travel Planner.
Nhiệm vụ của bạn là:
1. Phân tích yêu cầu nghiệp vụ du lịch, lập kế hoạch chi tiết cho hệ thống.
2. Kiểm tra tính hợp lý của dữ liệu địa điểm (Khách sạn, Chợ, Khu vui chơi, Nhà hàng, Check-in).
3. Đảm bảo tuân thủ nguyên tắc nhịp sinh học du lịch Việt Nam:
   Tham quan sáng -> Ăn trưa -> Nghỉ trưa -> Tham quan chiều -> Cà phê -> Ăn tối -> Chợ đêm/Nghỉ ngơi.
4. Hướng dẫn phân chia task cho các subagent phát triển phần mềm và làm sạch dữ liệu.

Hãy đưa ra phản hồi rõ ràng, cấu trúc mạch lạc (sử dụng Markdown hoặc JSON khi được yêu cầu) và giải pháp thực tế.
"""

def ask_ba(prompt: str, model: str = "claude-sonnet-4-6", stream: bool = False, temperature: float = 0.2, max_tokens: int = 4096, timeout: int = 120, include_system: bool = True):
    """
    Gửi câu hỏi / yêu cầu tới BA Agent (Sử dụng Claude Sonnet 4.6 qua VyceAI API Proxy).
    Hỗ trợ cả streaming output và return string trực tiếp, tự động xử lý HTTP 429 rate limit.
    """
    url = f"{VYCEAI_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {VYCEAI_API_KEY}",
        "Content-Type": "application/json"
    }
    messages = []
    if include_system:
        messages.append({"role": "system", "content": BA_SYSTEM_PROMPT})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    if stream:
        payload["stream"] = True

    for attempt in range(1, 4):
        try:
            if stream:
                response = requests.post(url, headers=headers, json=payload, stream=True, timeout=timeout)
            else:
                response = requests.post(url, headers=headers, json=payload, timeout=timeout)
            
            if response.status_code == 429:
                print(f"\n⚠️ Rate limit 429, chờ {3 * attempt}s...")
                time.sleep(3 * attempt)
                continue
            elif response.status_code in (502, 503, 504):
                print(f"\n⚠️ Server Gateway {response.status_code} (lần {attempt}/3), đang thử lại sau {2 * attempt}s...")
                time.sleep(2 * attempt)
                continue

            response.raise_for_status()

            if stream:
                full_content = []
                for line in response.iter_lines():
                    if not line:
                        continue
                    line_str = line.decode("utf-8")
                    if line_str.startswith("data: "):
                        data_part = line_str[6:].strip()
                        if data_part == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_part)
                            choices = chunk.get("choices", [])
                            if not choices:
                                continue
                            choice = choices[0]
                            delta = choice.get("delta", {}).get("content", "")
                            if delta:
                                print(delta, end="", flush=True)
                                full_content.append(delta)
                            if choice.get("finish_reason") in ("stop", "length"):
                                break
                        except json.JSONDecodeError:
                            continue
                print()
                return "".join(full_content)
            else:
                data = response.json()
                choices = data.get("choices", [])
                content = choices[0].get("message", {}).get("content", "") if choices else ""
                return content

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            print(f"\n⚠️ Lỗi kết nối timeout ({e}) lần {attempt}/3, đang thử lại...")
            time.sleep(2 * attempt)
        except Exception as e:
            print(f"\n❌ Lỗi gọi VyceAI API: {e}")
            return None
    return None

def ask_ba_json(prompt: str, model: str = "claude-sonnet-4-6", max_retries: int = 3, timeout: int = 90):
    """
    Gửi prompt yêu cầu JSON tới BA Agent và parse kết quả trả về dưới dạng Python dict/list.
    Tự động xử lý bóc tách markdown ```json ... ``` và thử lại nếu lỗi.
    """
    for attempt in range(1, max_retries + 1):
        content = ask_ba(prompt, model=model, stream=False, temperature=0.2, max_tokens=4096, timeout=timeout, include_system=False)
        if not content:
            time.sleep(2 * attempt)
            continue

        # Trích xuất JSON từ markdown block nếu có
        cleaned = content.strip()
        if "```json" in cleaned:
            cleaned = cleaned.split("```json", 1)[1]
            if "```" in cleaned:
                cleaned = cleaned.split("```", 1)[0]
        elif cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines)
        cleaned = cleaned.strip()

        try:
            parsed = json.loads(cleaned, strict=False)
            return parsed
        except json.JSONDecodeError as err:
            print(f"⚠️ Thử lần {attempt}: Phản hồi không phải JSON hợp lệ ({err}). Thử lại...")
            time.sleep(2 * attempt)
    return None

if __name__ == "__main__":
    test_prompt = "Chào BA, hãy tóm tắt ngắn gọn 3 mục tiêu chiến lược tiếp theo để hoàn thiện hệ thống VN Travel Planner."
    print("🤖 [BA Agent Connecting via VyceAI OpenAI Client...]\n")
    ask_ba(test_prompt, stream=True)
