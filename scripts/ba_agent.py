import os
import sys
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables from .env
load_dotenv()

VYCEAI_API_KEY = os.getenv("VYCEAI_API_KEY")
VYCEAI_BASE_URL = os.getenv("VYCEAI_BASE_URL", "https://vyceai.com/v1")

if not VYCEAI_API_KEY:
    print("❌ Lỗi: Chưa cấu hình VYCEAI_API_KEY trong file .env!")
    sys.exit(1)

client = OpenAI(
    api_key=VYCEAI_API_KEY,
    base_url=VYCEAI_BASE_URL
)

BA_SYSTEM_PROMPT = """Bạn là Business Analyst (BA) chính của dự án VN Travel Planner.
Nhiệm vụ của bạn là:
1. Phân tích yêu cầu nghiệp vụ du lịch, lập kế hoạch chi tiết cho hệ thống.
2. Kiểm tra tính hợp lý của dữ liệu địa điểm (Khách sạn, Chợ, Khu vui chơi, Nhà hàng, Check-in).
3. Đảm bảo tuân thủ nguyên tắc nhịp sinh học du lịch Việt Nam:
   Tham quan sáng -> Ăn trưa -> Nghỉ trưa -> Tham quan chiều -> Cà phê -> Ăn tối -> Chợ đêm/Nghỉ ngơi.
4. Hướng dẫn phân chia task cho các subagent phát triển phần mềm và làm sạch dữ liệu.

Hãy đưa ra phản hồi rõ ràng, cấu trúc mạch lạc (sử dụng Markdown) và giải pháp thực tế.
"""

def ask_ba(prompt: str, model: str = "claude-sonnet-4-6", stream: bool = True):
    """
    Gửi câu hỏi / yêu cầu tới BA Agent (Sử dụng Claude 3.5 Sonnet qua VyceAI API Proxy).
    """
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": BA_SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            stream=stream
        )

        if stream:
            full_content = ""
            for chunk in response:
                content = chunk.choices[0].delta.content or ""
                print(content, end="", flush=True)
                full_content += content
            print()
            return full_content
        else:
            content = response.choices[0].message.content
            print(content)
            return content

    except Exception as e:
        print(f"\n❌ Lỗi gọi VyceAI API: {e}")
        return None

if __name__ == "__main__":
    test_prompt = "Chào BA, hãy tóm tắt ngắn gọn 3 mục tiêu chiến lược tiếp theo để hoàn thiện hệ thống VN Travel Planner."
    print("🤖 [BA Agent Agent Connecting via VyceAI...]\n")
    ask_ba(test_prompt)
