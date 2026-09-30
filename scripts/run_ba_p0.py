import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.ba_agent import ask_ba

P0_BA_PROMPT = r"""### NHIỆM VỤ CỦA LEAD BA: ĐẶC TẢ CHI TIẾT HẠNG MỤC P0 (2-OPT TSP & HARD TIME-WINDOW SCHEDULING)

Dự án VNTravel AI hiện đang gặp 2 lỗ hổng nghiêm trọng ở tầng giải thuật định tuyến trong `app/services/travel_calculator.py`:
1. Vẫn dùng thuật toán tham lam thô sơ (Greedy Nearest Neighbor), dẫn đến đường đi bị cắt chéo hình chữ X (crossing edges) gây lãng phí $15-30\%$ quãng đường.
2. Phân bổ thời gian theo slot cố định (Sáng di tích, Trưa ăn đặc sản, Chiều dạo mát) mà CHƯA đối chiếu giờ mở/đóng cửa thực tế (`working_hours`) từ `travel_db.db`. Ví dụ: Chợ đêm/Phố đi bộ chỉ mở từ 18:00 lại bị xếp vào buổi sáng chỉ vì gần khách sạn; Bảo tàng đóng cửa trưa (11:30 - 13:30) nhưng du khách lại bị xếp đến vào 12:00.

BẠN HÃY XÂY DỰNG MỘT TÀI LIỆU ĐẶC TẢ NGHIỆP VỤ & KIẾN TRÚC GIẢI THUẬT (PRD & TECHNICAL SPEC) ĐẦY ĐỦ VỚI 5 PHẦN SAU:

#### 1. ĐẶC TẢ MÔ HÌNH TOÁN HỌC KHUNG GIỜ CỨNG (HARD TIME-WINDOW TSPTW)
- Định nghĩa hàm mục tiêu: Giảm thiểu quãng đường $D$ và thời gian chờ ($Wait$), triệt tiêu vi phạm giờ đóng cửa (Late Arrival Penalty).
- Khung giờ địa điểm $i$: $\text{working\_hours}_i = [[O_{i,1}, C_{i,1}], [O_{i,2}, C_{i,2}]]$.
- Thời gian lưu trú (Dwell time $Dwell_i$) lấy từ `typical_time_spent` (với fallback chuẩn theo category trong `PROJECT_CONTEXT.md`).
- Thời gian di chuyển $T_{i, j}$ tính từ Haversine + Ma trận Vận tốc Địa hình ($K_{\text{topo}}, V_{\text{avg}}$).
- Ràng buộc bất biến:
  $$\text{Arrival}_j = \max(O_j, \text{Departure}_i + T_{i,j})$$
  $$\text{Departure}_j = \text{Arrival}_j + Dwell_j \le C_j$$
- Giải thuật xử lý khi vi phạm (Infeasibility Handling): Khi người dùng chọn các điểm xung đột giờ mở cửa, BA đề xuất chiến lược sắp xếp và thông báo cảnh báo thế nào?

#### 2. GIẢI THUẬT 2-OPT LOCAL SEARCH
- Mô tả chi tiết từng bước thuật toán 2-Opt hoán đổi cạnh $(i, i+1)$ và $(j, j+1)$ để gỡ các nút giao cắt.
- Điều kiện dừng: Khi không còn hoán đổi nào cải thiện tổng chi phí $> \epsilon$ hoặc đạt số vòng lặp tối đa ($Iter_{\max} = 100$).
- Tích hợp 2-Opt với Time Windows: Làm thế nào để phép lật ngược chuỗi (reverse path) không làm phá vỡ thứ tự thời gian mở cửa?

#### 3. BẢNG MA TRẬN 5 TEST SCENARIOS THỰC TẾ VIỆT NAM (ACCEPTANCE CRITERIA)
Xây dựng 5 kịch bản kiểm thử góc (Edge Cases) bắt buộc thuật toán phải vượt qua:
- Case 1: Điểm mở muộn (Chợ đêm Helio / Phố đi bộ Hội An chỉ mở từ 17:30/18:00).
- Case 2: Di tích/Bảo tàng đóng cửa giờ trưa (11:30 - 13:30) tại Hà Nội hoặc Huế.
- Case 3: Danh lam thắng cảnh đóng cửa sớm lúc hoàng hôn (17:00) như Tràng An, Tam Cốc.
- Case 4: Ghim giờ ăn trưa (11:45 - 13:00) tại Nhà hàng đặc sản cố định.
- Case 5: Xung đột bất khả thi (2 điểm cách xa nhau 50km và đều chỉ mở từ 08:00 - 10:00).

#### 4. DATA CONTRACT & SCHEMA BỔ SUNG
- Đặc tả schema JSON trả về của từng điểm trong timeline: Bổ sung các trường `arrival_time`, `departure_time`, `is_time_window_valid`, `wait_time_minutes`.
- Đảm bảo tương thích ngược 100% với giao diện `frontend/index.html`.

#### 5. CODE MẪU THUẦN PYTHON CHUẨN KỸ SƯ TRƯỞNG
- Cung cấp hàm Python mẫu: `solve_day_tsptw_2opt(places, start_coords, start_time="08:00") -> List[dict]`.
- Viết bằng Python thuần, chú thích rõ ràng, tốc độ thực thi $< 10\text{ms}$ cho $N \le 10$ điểm.

Hãy xuất bản toàn bộ phản hồi dưới dạng tài liệu Markdown chuẩn công nghiệp."""

def main():
    print("🚀 [BA Agent] Đang gửi yêu cầu đặc tả P0 tới Claude Sonnet qua VyceAI...")
    content = ask_ba(P0_BA_PROMPT, model="claude-sonnet-4-6", stream=True, temperature=0.2, max_tokens=4096, timeout=120)
    
    if content:
        output_file = "data/ba_p0_tsptw_specification.md"
        os.makedirs("data", exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"\n✅ Đã lưu toàn bộ bản đặc tả P0 vào: {output_file}")
    else:
        print("❌ Lỗi: Không nhận được phản hồi từ BA Agent.")

if __name__ == "__main__":
    main()
