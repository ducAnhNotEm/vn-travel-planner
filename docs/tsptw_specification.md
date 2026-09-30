# ĐẶC TẢ NGHIỆP VỤ & HỢP ĐỒNG DỮ LIỆU: BÀI TOÁN KHUNG THỜI GIAN CỨNG (HARD TSPTW) & 3 NHỊP SINH HỌC DU LỊCH VIỆT NAM
**Mã tài liệu: SPEC-TSPTW-VN-2026-P0**  
**Phiên bản: 1.0.0 (Chính thức)**  
**Trạng thái: Approved for Implementation (Milestone 1)**  
**Tác giả: Lead Business Analyst (Worker BA M1)**  
**Hệ thống mục tiêu: VNTravel AI Core Engine (`app/services/travel_calculator.py`)**  

---

## MỤC LỤC
1. [TỔNG QUAN HỆ THỐNG & TÔN CHỈ THIẾT KẾ](#1-tổng-quan-hệ-thống--tôn-chỉ-thiết-kế)
2. [MÔ HÌNH TOÁN HỌC KHUNG THỜI GIAN CỨNG (TSPTW FORMULATION)](#2-mô-hình-toán-học-khung-thời-gian-cứng-tsptw-formulation)
3. [CHUẨN HÓA THỜI GIAN LƯU TRÚ (DWELL TIME STANDARDS)](#3-chuẩn-hóa-thời-gian-lưu-trú-dwell-time-standards)
4. [3 NHỊP SINH HỌC DU LỊCH VIỆT NAM (BIOLOGICAL TRAVEL RHYTHMS)](#4-3-nhịp-sinh-học-du-lịch-việt-nam-biological-travel-rhythms)
5. [GIẢI THUẬT TỐI ƯU CỤC BỘ 2-OPT LOCAL SEARCH KẾT HỢP TSPTW](#5-giải-thuật-tối-ưu-cục-bộ-2-opt-local-search-kết-hợp-tsptw)
6. [MA TRẬN 5 CA KIỂM THỬ THỰC ĐỊA TỪ DATABASE (`travel_db.db`)](#6-ma-trận-5-ca-kiểm-thử-thực-địa-từ-database-travel_dbdb)
7. [HỢP ĐỒNG DỮ LIỆU ĐẦU RA (OUTPUT DATA CONTRACT & SCHEMA)](#7-hợp-đồng-dữ-liệu-đầu-ra-output-data-contract--schema)
8. [HƯỚNG DẪN BÀN GIAO & LỘ TRÌNH THỰC THI (HANDOFF GUIDELINES)](#8-hướng-dẫn-bàn-giao--lộ-trình-thực-thi-handoff-guidelines)

---

## 1. TỔNG QUAN HỆ THỐNG & TÔN CHỈ THIẾT KẾ

### 1.1. Bối Cảnh & Sự Cần Thiết Cấp Bách (P0)
Hệ thống lập lịch trình du lịch hiện tại của **VNTravel AI** trong `app/services/travel_calculator.py` gặp phải 2 hạn chế lớn mang tính chất cốt lõi:
1. **Bẫy Tham lam Cục bộ (Local Greedy Trap)**: Sử dụng thuật toán Nearest Neighbor đơn thuần, dẫn đến nguy cơ cao các cung đường bị cắt chéo chữ X (crossing edges) khi tập điểm phân bố rải rác.
2. **Điểm mù Thời gian Thực địa (Time-Window Blindness)**: Gán các mốc thời gian tĩnh cố định (`07:30`, `09:30`, `11:45`...) dựa trên thứ tự danh mục mà không hề kiểm tra:
   - Thời gian di chuyển thực tế tích lũy giữa các điểm ($T_{i, j}$).
   - Thời gian mở/đóng cửa thực tế của địa điểm (`working_hours`).
   - Giờ nghỉ trưa đóng cổng của các di tích lịch sử và cơ sở tín ngưỡng ($11:30 - 13:30$).
   - Giờ họp muộn của các chợ đêm ($17:30 - 23:45$).

Hậu quả thực tế là khách du lịch bị xếp đến Chợ Đêm Sơn Trà lúc 09:30 sáng khi chợ chưa mở cửa, hoặc bị xếp đến Chùa Quán Sứ lúc 12:00 trưa khi cổng chùa đang đóng then cài nghỉ trưa.

### 1.2. Tôn Chỉ Kỹ Thuật Đỉnh Cao Top 0.1% (Elite Standard)
Tuân thủ nghiêm ngặt **AGENTS.md**:
- **Toán học Xác định (Deterministic Mathematical Rigor)**: Không cho phép LLM suy đoán khoảng cách hay tự bịa giờ check-in. Toàn bộ chuỗi thời gian phải được tính toán tuần tự bằng giải thuật xác định trên dữ liệu thực tế từ `travel_db.db`.
- **Thiết kế Phòng thủ & Chống Sập Tuyệt đối (Zero-Failure Resiliency)**: Khi người dùng đưa ra các ràng buộc xung đột bất khả thi (ví dụ: ghim điểm mở 18:00 trước điểm đóng 17:00), hệ thống không được crash HTTP 500 mà phải đánh dấu cờ vi phạm `is_time_window_valid = False` và kích hoạt Thẻ Lời Khuyên Thông Minh (Smart Advisory Card).
- **Mô Hình Hóa Thực Tế Sâu Sắc**: Lồng ghép trọn vẹn 3 Nhịp sinh học du lịch Việt Nam (Biển, Di tích/Đô thị, Đồi núi) cùng Ma trận Vận tốc & Hệ số Địa hình Việt Nam ($K_{\text{topo}}$).
- **Tương Thích Ngược 100%**: Giữ nguyên schema cho frontend `frontend/index.html` và API endpoint `POST /api/plan/calculate`.

---

## 2. MÔ HÌNH TOÁN HỌC KHUNG THỜI GIAN CỨNG (TSPTW FORMULATION)

### 2.1. Định Nghĩa Bài Toán
Xét tập hợp các địa điểm tham quan trong ngày $\mathcal{V} = \{p_0, p_1, p_2, \dots, p_{n-1}\}$ với quy mô $N \le 10$ điểm/ngày.
Mỗi điểm $j \in \mathcal{V}$ được đặc trưng bởi bộ tham số:
- Tọa độ địa lý $(\text{lat}_j, \text{lng}_j)$.
- Danh mục loại hình $\text{category}_j \in \{\text{ATTRACTION}, \text{TEMPLE}, \text{HISTORICAL\_SITE}, \text{RESTAURANT}, \text{MARKET}, \text{HOTEL}, \dots\}$.
- Thời gian lưu trú tiêu chuẩn $\text{Dwell}_j$ (phút).
- Tập hợp các khoảng thời gian mở cửa hợp lệ trong ngày (tính theo phút từ nửa đêm $00:00$):
  $$\mathcal{W}_j = \bigcup_{k=1}^{M_j} [O_{j,k}, C_{j,k}], \quad 0 \le O_{j,k} < C_{j,k} \le 1440$$
  - Điểm mở cửa liên tục (ví dụ: $08:00 - 17:00$): $\mathcal{W}_j = \{[480, 1020]\}$.
  - Điểm có giờ nghỉ trưa (ví dụ: $07:30 - 11:30$ và $13:30 - 17:30$): $\mathcal{W}_j = \{[450, 690], [810, 1050]\}$.
  - Điểm mở cửa 24/7: $\mathcal{W}_j = \{[0, 1440]\}$.

### 2.2. Tính Toán Thời Gian Di Chuyển Thực Địa ($T_{i, j}$)
Khoảng cách trắc địa giữa hai điểm $i$ và $j$ được tính bằng công thức Haversine:
$$a = \sin^2\left(\frac{\Delta \text{lat}}{2}\right) + \cos(\text{lat}_i) \cdot \cos(\text{lat}_j) \cdot \sin^2\left(\frac{\Delta \text{lng}}{2}\right)$$
$$c = 2 \cdot \arctan2(\sqrt{a}, \sqrt{1 - a})$$
$$D_{\text{Haversine}}(i, j) = R \cdot c \quad (\text{với } R = 6371.0\text{ km})$$

Để phản ánh chân thực mạng lưới giao thông Việt Nam, cự ly thực tế được điều chỉnh qua **Hệ số Uốn lượn Địa hình ($K_{\text{topo}}$)** và **Vận tốc Bình quân Địa hình ($V_{\text{avg}}$)**:
$$T_{i, j} = \left(\frac{D_{\text{Haversine}}(i, j) \times K_{\text{topo}}}{V_{\text{avg}}}\right) \times 60 \quad (\text{phút})$$

#### Ma Trận Vận Tốc & Hệ Số Địa Hình Việt Nam (Topographic Terrain Matrix):
| Loại hình Địa hình | Tỉnh/Khu vực Tiêu biểu | Hệ số Uốn lượn ($K_{\text{topo}}$) | Vận tốc Bình quân Nội tỉnh ($V_{\text{avg}}$) | Ứng dụng Thực tế |
| :--- | :--- | :---: | :---: | :--- |
| **Đồng bằng / Đô thị lớn / Trục Cao tốc** | Hà Nội, TP.HCM, Đà Nẵng, Bắc Ninh, Cần Thơ | **$1.25$** | $40 - 50\text{ km/h}$ (Đô thị)<br>$80\text{ km/h}$ (Cao tốc liên huyện) | Tuyến nội thành, đường vành đai bằng phẳng |
| **Duyên hải / Bán sơn địa / Đồi thấp** | Thanh Hóa, Nghệ An, Bình Định, Khánh Hòa, Phú Quốc | **$1.35$** | $50 - 60\text{ km/h}$ | Đường ven biển, đèo thoải, giao thông hỗn hợp |
| **Đèo dốc Vùng cao / Tây Bắc / Tây Nguyên** | Hà Giang, Lào Cai, Sơn La, Điện Biên, Lâm Đồng, Cao Bằng | **$1.75$** | $30 - 35\text{ km/h}$ | Đèo dốc quanh co, cua tay áo, dốc $> 10\%$ |

*Quy tắc làm tròn*: $T_{i, j}$ được làm tròn lên số nguyên phút gần nhất ($\lceil T_{i, j} \rceil$). Cự ly nội bộ dưới $500\text{m}$ có $T_{i, j}$ tối thiểu là $3\text{ phút}$ (tính cả thời gian lên/xuống xe).

### 2.3. Hệ Phương Trình Mô Phỏng Thời Gian Xuôi Dòng (Forward Time-Window Simulation)
Giả sử đoàn xuất phát từ điểm khởi hành (hoặc khách sạn) $p_0$ vào thời điểm bắt đầu ngày $\text{Departure}_0 = T_{\text{start}}$ (phút từ nửa đêm, ví dụ $07:30 = 450$).
Với mỗi chặng dừng tiếp theo $j = 1, 2, \dots, n-1$ sau điểm $i$:

1. **Thời điểm Dự kiến Đến Cổng (Estimated Arrival Time)**:
   $$\text{EstimatedArrival}_j = \text{Departure}_i + T_{i, j}$$

2. **Thời gian Chờ Ngoài Cổng (Wait Time)**:
   Nếu du khách đến trước giờ mở cửa của khoảng khả thi gần nhất $O_{j,k}$:
   $$\text{WaitTime}_j = \max(0, O_{j,k} - \text{EstimatedArrival}_j)$$

3. **Thời điểm Bắt Đầu Tham Quan Chính Thức (Arrival Time)**:
   $$\text{Arrival}_j = \max(O_{j,k}, \text{EstimatedArrival}_j) = \text{EstimatedArrival}_j + \text{WaitTime}_j$$

4. **Thời điểm Rời Đi (Departure Time)**:
   $$\text{Departure}_j = \text{Arrival}_j + \text{Dwell}_j$$

5. **Ràng Buộc Đóng Cửa Cứng (Hard Closing Constraint)**:
   Để chuyến thăm được coi là hợp lệ, toàn bộ khoảng tham quan phải nằm trọn vẹn trong khoảng mở cửa $[O_{j,k}, C_{j,k}]$:
   $$\text{Departure}_j \le C_{j,k}$$

6. **Đánh Giá Tính Hợp Lệ & Trễ Giờ (Feasibility & Lateness)**:
   $$\text{Lateness}_j = \max(0, \text{Departure}_j - C_{j,k})$$
   $$\text{is\_time\_window\_valid}_j = (\text{Lateness}_j == 0)$$

---

## 3. CHUẨN HÓA THỜI GIAN LƯU TRÚ (DWELL TIME STANDARDS)

### 3.1. Cơ Chế Hai Tầng Ưu Tiên (Two-Tier Resolution)
Để xác định thời gian lưu trú $\text{Dwell}_j$ của một địa điểm:
- **Tầng 1 (Ưu tiên Cao nhất - Ground Truth Parsing)**: Bóc tách trực tiếp chuỗi văn bản `typical_time_spent` có sẵn trong bảng `places` của `travel_db.db` (hiện diện trên $99.6\%$ bản ghi).
- **Tầng 2 (Dự phòng Heuristic - Fallback Table)**: Áp dụng bảng chuẩn danh mục theo `PROJECT_CONTEXT.md` khi trường `typical_time_spent` là `NULL` hoặc chứa nội dung không thể định lượng.

### 3.2. Bảng Luật Phân Tích Cú Pháp (Regex Parser Rules)
Hàm parser chuẩn hóa chuỗi tiếng Việt sang số phút nguyên (`int`):

| Mẫu Chuỗi trong `travel_db.db` | Biểu thức Regex Khớp | Giá trị Quy đổi (Phút) | Giải thích Nghiệp vụ |
| :--- | :--- | :---: | :--- |
| `"90 phút"`, `"90 mins"` | `r"(\d+)\s*(?:phút\|min)"` | $90$ | Chuẩn cho chùa chiền, di tích lịch sử |
| `"60 phút"`, `"1 giờ"` | `r"(\d+)\s*(?:giờ\|h\|hour)"` | $60$ | Chuẩn cho chợ dân sinh, danh thắng nhỏ |
| `"75 phút"`, `"70 phút"` | `r"(\d+)\s*(?:phút\|min)"` | $75$ / $70$ | Chuẩn cho nhà hàng ẩm thực |
| `"1-2 giờ"`, `"1h - 2h"` | `r"(\d+)\s*(?:-|đến)\s*(\d+)\s*(?:giờ\|h)"` | $90$ | Lấy trung bình cộng: $(60 + 120) / 2 = 90$ phút |
| `"2h - 4h"`, `"2 - 4 giờ"` | `r"(\d+)\s*(?:-|đến)\s*(\d+)\s*(?:giờ\|h)"` | $180$ | Khu vui chơi, công viên chủ đề, bảo tàng lớn |
| `"30 phút - 1 giờ"` | `r"(\d+)\s*phút\s*-\s*(\d+)\s*giờ"` | $45$ | Điểm check-in, ngắm cảnh nhanh |
| `"Overnight / Lưu trú"` | `r"(?:overnight\|lưu trú\|nghỉ đêm)"` | $105$ | Áp dụng cho slot Nghỉ trưa tại Khách sạn |

### 3.3. Bảng Heuristic Fallback Theo Danh Mục (`PlaceCategory`)
Khi `typical_time_spent` là `NULL`, bắt buộc sử dụng bảng định mức sau:

| Danh mục (`category`) | Thời gian Mặc định | Giới hạn Dưới (Min) | Giới hạn Trên (Max) | Hoạt động Thực tế Đặc thù |
| :--- | :---: | :---: | :---: | :--- |
| `TEMPLE` | **$90\text{ phút}$** | $45\text{ phút}$ | $120\text{ phút}$ | Chiêm bái, vãn cảnh khuôn viên, chụp ảnh |
| `HISTORICAL_SITE` | **$90\text{ phút}$** | $60\text{ phút}$ | $180\text{ phút}$ | Mua vé, nghe hướng dẫn viên, xem hiện vật |
| `RESTAURANT` / `SPECIALTY_FOOD` | **$75\text{ phút}$** | $45\text{ phút}$ | $120\text{ phút}$ | Gọi món, chế biến tại bàn, ăn uống, thanh toán |
| `HOTEL` (Nghỉ trưa tránh nắng) | **$105\text{ phút}$** | $60\text{ phút}$ | $150\text{ phút}$ | Về phòng ngả lưng, sạc điện thoại, hồi phục thể lực |
| `MARKET` / `NIGHT_MARKET` | **$60\text{ phút}$** | $45\text{ phút}$ | $120\text{ phút}$ | Dạo chợ, ăn vặt đường phố, mua đồ lưu niệm |
| `ATTRACTION` | **$60\text{ phút}$** | $30\text{ phút}$ | $120\text{ phút}$ | Tham quan danh lam thắng cảnh tổng hợp |
| `ACTIVITY` | **$75\text{ phút}$** | $45\text{ phút}$ | $150\text{ phút}$ | Làng nghề thủ công, chèo thuyền, đi xe điện |
| `CAFE` | **$45\text{ phút}$** | $30\text{ phút}$ | $90\text{ phút}$ | Uống nước, nghỉ chân, ngắm view phố/biển/núi |

---

## 4. 3 NHỊP SINH HỌC DU LỊCH VIỆT NAM (BIOLOGICAL TRAVEL RHYTHMS)

Hệ thống tự động nhận diện tính chất địa phương dựa trên tên tỉnh, tên địa danh và địa chỉ để áp dụng 1 trong 3 nhịp sinh học chuẩn thực tế (theo **AGENTS.md** Mục 3):

```
                        ┌─────────────────────────────────┐
                        │   PHÂN LOẠI ĐỊA DANH / TỈNH     │
                        └────────────────┬────────────────┘
                                         │
         ┌───────────────────────────────┼───────────────────────────────┐
         ▼                               ▼                               ▼
 🌊 DU LỊCH BIỂN                 🏛️ DI TÍCH / ĐÔ THỊ             🌲 ĐỒI NÚI / CAO NGUYÊN
 (Đà Nẵng, Nha Trang,            (Hà Nội, Huế, Hội An,           (Sa Pa, Hà Giang, Đà Lạt,
  Phú Quốc, Quy Nhơn...)          Ninh Bình, TP.HCM...)           Mộc Châu, Tây Bắc...)
         │                               │                               │
         ├─ 05:30: Bình minh biển        ├─ 07:30: Ăn sáng đặc sản       ├─ 06:00: Săn mây thung lũng
         ├─ 11:45: Ăn trưa hải sản       ├─ 08:30: Thăm di tích sáng     ├─ 09:00: Trekking/Thác nước
         ├─ 13:00-15:30: NGHỈ TRƯA HOTEL ├─ 11:45: Ăn trưa ẩm thực      ├─ 11:45: Cơm lam gà đồi
         ├─ 16:00: Tắm chiều/Hoàng hôn   ├─ 13:00-14:30: Nghỉ trưa mát   ├─ 13:30-15:00: Nghỉ homestay
         ├─ 19:00: Tiệc tối hải sản      ├─ 14:45: Làng nghề/Đi thuyền   ├─ 15:00: Đồi thông/Vườn hoa
         └─ 20:45: Dạo chợ đêm ven biển  ├─ 17:15: Cà phê hoàng hôn      ├─ 18:30: Nướng than/Lẩu nóng
                                         ├─ 19:00: Ăn tối nhà hàng       └─ 20:45: Chợ đêm/Sữa nóng
                                         └─ 20:45: Phố đi bộ/Chợ đêm
```

---

### 4.1. 🌊 Nhịp Sinh Học Du Lịch Biển (Coastal / Beach Rhythm)
- **Địa bàn áp dụng**: Đà Nẵng, Nha Trang (Khánh Hòa), Phú Quốc (Kiên Giang), Quy Nhơn (Bình Định), Vũng Tàu, Phan Thiết (Bình Thuận), Sầm Sơn (Thanh Hóa), Cửa Lò (Nghệ An), Hạ Long (Quảng Ninh).
- **Đặc thù sinh học**: Nắng nóng gay gắt từ trưa đến đầu giờ chiều; chỉ số UV thường xuyên ở mức cực độ ($> 10$). Nước biển mát và êm nhất vào bình minh và hoàng hôn.
- **Khung lịch trình chuẩn hóa**:
  1. 🌅 **05:30 - 07:00**: Đón bình minh bãi biển & Tắm biển sớm (Dwell 90m).
  2. 🍜 **07:30 - 08:30**: Ăn sáng đặc sản biển (Bún chả cá, Bánh canh ghẹ) (Dwell 60m).
  3. 🚶 **09:00 - 11:30**: Đi dạo / Tham quan danh thắng ven biển / Check-in mát mẻ (Bán đảo Sơn Trà, Tháp Bà Ponagar) (Dwell 90m).
  4. 🍲 **11:45 - 13:00**: Ăn trưa hải sản tươi sống tại nhà hàng ven biển (Dwell 75m).
  5. 🏨 **13:00 - 15:30**: **BẮT BUỘC NGHỈ TRƯA TRÁNH NẮNG TẠI PHÒNG KHÁCH SẠN** (Dwell 150m).  
     *Điều cấm tuyệt đối*: Không xếp hoạt động bãi biển hoặc leo núi ngoài trời từ $12:30 - 15:30$.
  6. 🌇 **16:00 - 18:00**: Ngắm hoàng hôn trên biển / Bãi tắm chiều & Thể thao nước (Dwell 120m).
  7. 🚿 **18:00 - 18:45**: Về phòng khách sạn tắm tráng nước ngọt & thay trang phục dạo phố (Dwell 45m).
  8. 🦀 **19:00 - 20:30**: Bữa tối tiệc hải sản tươi sống (Dwell 90m).
  9. 🌊 **20:45 - 22:30**: Dạo biển đêm / Chợ Đêm Sơn Trà / Chợ Đêm Helio / Cafe nghe sóng biển & nhạc Acoustic (Dwell 90m).

---

### 4.2. 🏛️ Nhịp Sinh Học Vùng Di Tích, Văn Hóa & Đồng Bằng / Đô Thị (Heritage & Urban Rhythm)
- **Địa bàn áp dụng**: Hà Nội, Huế, Hội An (Quảng Nam), Ninh Bình, TP. Hồ Chí Minh, Cần Thơ, Bắc Ninh, Hải Dương.
- **Đặc thù sinh học**: Di tích lịch sử, chùa chiền, bảo tàng có quy định mở cửa và **nghỉ trưa đóng cửa nghiêm ngặt** ($11:30 - 13:30$). Di chuyển chủ yếu là đi bộ trên sân gạch, hành lang đá ngoài trời.
- **Khung lịch trình chuẩn hóa**:
  1. 🍜 **07:30 - 08:30**: Ăn sáng đặc sản truyền thống (Phở Hà Nội, Bún bò Huế, Bánh cuốn) (Dwell 60m).
  2. 🏛️ **08:30 - 11:30**: Tham quan các đại di tích lịch sử / Đền chùa chính (Hoàng thành Thăng Long, Văn Miếu, Đại Nội Huế, Tràng An) trong lúc không khí mát mẻ (Dwell 90 - 120m).
  3. 🍲 **11:45 - 13:00**: Ăn trưa ẩm thực cung đình / món ngon đặc sản dân dã (Dwell 75m).
  4. 🏨 **13:00 - 14:30**: Nghỉ trưa tránh nắng (Khách sạn hoặc quán cafe điều hòa yên tĩnh) (Dwell 90m).
  5. 🛶 **14:45 - 17:00**: Trải nghiệm văn hóa nhẹ nhàng / Làng nghề truyền thống / Đi thuyền sinh thái mát mẻ (Tam Cốc, Đi thuyền rồng Sông Hương) (Dwell 90 - 120m).
  6. ☕ **17:15 - 18:30**: Cafe view ngắm hoàng hôn / Dạo bộ quanh hồ (Hồ Hoàn Kiếm, Hồ Tây, Sông Hương) (Dwell 60m).
  7. 🍲 **19:00 - 20:30**: Ăn tối nhà hàng đặc sản truyền thống (Dwell 90m).
  8. 🏮 **20:45 - 22:30**: Phố đi bộ, Chợ đêm cuối tuần, xem biểu diễn nghệ thuật thực cảnh (Ký ức Hội An, Tinh hoa Bắc Bộ, Múa rối nước) (Dwell 90m).
- *Điều cấm kỵ*: Tuyệt đối không xếp 3 - 4 di tích/chùa liên tiếp trong một buổi; cấm xếp leo bậc thang đá dốc đứng (Hang Múa, Chùa Đồng Yên Tử) giữa trưa $12:00 - 14:00$.

---

### 4.3. 🌲 Nhịp Sinh Học Vùng Đồi Núi & Cao Nguyên (Mountain / Highland Rhythm)
- **Địa bàn áp dụng**: Sa Pa (Lào Cai), Hà Giang, Mộc Châu (Sơn La), Đà Lạt (Lâm Đồng), Buôn Ma Thuột (Đắk Lắk), Điện Biên, Cao Bằng, Lai Châu.
- **Đặc thù sinh học**: Sáng sớm và đêm có sương mù, nhiệt độ giảm sâu se lạnh; trưa nắng gắt; đường đèo hiểm trở cấm di chuyển sau 19:30 tối.
- **Khung lịch trình chuẩn hóa**:
  1. ☁️ **06:00 - 07:30**: Săn mây thung lũng / Đón bình minh trong sương sớm se lạnh (Dwell 90m).
  2. ☕ **07:45 - 08:45**: Ăn sáng ấm nóng (Bánh cuốn nóng, xôi ngũ sắc, thắng cố) + Cà phê phin ngắm núi rừng (Dwell 60m).
  3. 🚶 **09:00 - 11:30**: Khám phá bản làng văn hóa (Cát Cát, Pả Vi, Lô Lô Chải) / Check-in thác nước đại ngàn (Bản Giốc, Datanla) / Trekking nhẹ (Dwell 120m).
  4. 🍲 **11:45 - 13:15**: Ăn trưa cơm lam gà đồi nướng, lợn bản cắp nách, rau rừng (Dwell 90m).
  5. 🏨 **13:30 - 15:00**: Nghỉ ngơi tại homestay / resort bungalow view thung lũng (Dwell 90m).
  6. 🌸 **15:00 - 17:30**: Dạo đồi thông, đồi chè Ô Long, vườn hoa cẩm tú cầu, check-in hoàng hôn lưng đèo (Dwell 90m).
  7. 🔥 **18:30 - 20:30**: Bữa tối tiệc nướng ngói than hoa / Lẩu gà lá é / Lẩu cá tầm bốc khói nghi ngút quanh bếp lửa (Dwell 90 - 120m).
  8. 🧣 **20:45 - 22:30**: Dạo chợ đêm vùng cao, uống sữa đậu nành nóng hổi, nghe nhạc Acoustic trong không khí lành lạnh (Dwell 60 - 90m).

---

## 5. GIẢI THUẬT TỐI ƯU CỤC BỘ 2-OPT LOCAL SEARCH KẾT HỢP TSPTW

### 5.1. Cơ Chế Hoán Đổi Cạnh 2-Opt (2-Opt Edge Swap)
Giải thuật bắt đầu từ lộ trình sơ bộ $P = (p_0, p_1, \dots, p_{n-1})$ được sinh ra bởi bộ quy tắc nhịp sinh học.
Tại mỗi bước lặp, thuật toán chọn một cặp chỉ số $(a, b)$ sao cho $0 \le a < b < n$.
Phép biến đổi 2-Opt tạo ra lộ trình ứng viên mới $P'$ bằng cách đảo ngược thứ tự phân đoạn từ $a+1$ đến $b$:
$$P' = (p_0, \dots, p_a, \mathbf{p_b, p_{b-1}, \dots, p_{a+1}}, p_{b+1}, \dots, p_{n-1})$$

```
Trước 2-Opt:   p_a ───────> p_{a+1}
                     X        (Cung cắt chéo)
               p_b ───────> p_{b+1}

Sau 2-Opt:     p_a ───────> p_b
               p_{a+1} ───> p_{b+1}   (Hết cắt chéo)
```

### 5.2. Cơ Chế Chấp Thuận Hai Cổng (Double-Gated Acceptance Criteria)
Một phép hoán đổi 2-Opt **CHỈ ĐƯỢC CHẤP THUẬN** khi vượt qua đồng thời cả 2 cánh cổng kiểm định nghiêm ngặt:

#### 🚪 Cổng 1: Giảm Thiểu Khoảng Cách Địa Lý ($\Delta \text{Cost} < 0$)
Khoảng cách tiết kiệm được khi hoán đổi hai cạnh $(p_a, p_{a+1})$ và $(p_b, p_{b+1})$:
$$\Delta \text{Cost} = \left[ D(p_a, p_b) + D(p_{a+1}, p_{b+1}) \right] - \left[ D(p_a, p_{a+1}) + D(p_b, p_{b+1}) \right]$$
Điều kiện cần: $\Delta \text{Cost} < -\epsilon$ (với $\epsilon = 10^{-4}\text{ km}$). Nếu không giảm quãng đường, lập tức bỏ qua.

#### 🚪 Cổng 2: Mô Phỏng Xuôi Dòng Thỏa Mãn Giờ Mở Cửa (Time-Window Feasibility Check)
Chạy hàm mô phỏng thời gian xuôi dòng (Forward Time Simulation) trên toàn bộ lộ trình mới $P'$:
- Tính chuỗi thời gian mới: $\text{Arrival}_k(P'), \text{Departure}_k(P')$ cho mọi điểm $k \in \{0, 1, \dots, n-1\}$.
- **Bất biến Bắt buộc (Hard Invariant)**:
  $$\forall k \in \{0, 1, \dots, n-1\}: \text{Departure}_k(P') \le C_k$$
  Đồng thời, nếu điểm $k$ có giờ nghỉ trưa $[[O_1, C_1], [O_2, C_2]]$, khoảng tham quan $[\text{Arrival}_k, \text{Departure}_k]$ phải nằm trọn vẹn trong một ca duy nhất.
- **Quy tắc Quyết định**: Nếu có **bất kỳ điểm nào** trong $P'$ bị vi phạm giờ đóng cửa hoặc bị rơi vào giờ nghỉ trưa, phép hoán đổi **BẮT BUỘC BỊ TỪ CHỐI (REJECTED)**, ngay cả khi nó giúp tiết kiệm hàng chục km đường đi.

### 5.3. Ngân Sách Hiệu Năng & Độ Phức Tạp (Complexity & Performance Budget)
- Với quy mô một ngày du lịch thực tế: $N \le 10$ địa điểm.
- Số lượng cặp cạnh cần duyệt trong một lượt: $\frac{N(N-1)}{2} \le 45$ cặp.
- Mỗi lần mô phỏng xuôi dòng tốn $O(N)$ phép tính.
- Tổng độ phức tạp mỗi vòng lặp: $O(N^3) \approx 1.000$ thao tác số học cơ bản.
- **Ngân sách thời gian thực thi (Execution Time Budget)**:
  - Giới hạn cứng của hệ thống: $< 15\text{ms}$ trên CPU thông thường.
  - Kỳ vọng thực tế với Python thuần: **$1 - 3\text{ms}$**.

---

## 6. MA TRẬN 5 CA KIỂM THỬ THỰC ĐỊA TỪ DATABASE (`travel_db.db`)

Toàn bộ các thực thể dưới đây là các bản ghi có thật 100% trong `travel_db.db`, có Google Place ID xác thực và đã được đối soát giờ mở cửa thực địa qua cache Google Places Crawler:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                      MA TRẬN 5 CA KIỂM THỬ THỰC ĐỊA (GROUND-TRUTH)                     │
├──────┬──────────────────────┬─────────┬──────────────────────┬─────────────┬───────────┤
│ Case │ Kịch Bản Kiểm Thử    │ DB ID   │ Địa Danh Thực Tế     │ Tỉnh/Thành  │ Giờ Mở Cửa│
├──────┼──────────────────────┼─────────┼──────────────────────┼─────────────┼───────────┤
│ C1   │ Chợ đêm mở muộn      │ 1865    │ Chợ Đêm Sơn Trà      │ Đà Nẵng     │ 17:30-23:45│
│ C2   │ Di tích nghỉ trưa    │ 1012    │ Chùa Quán Sứ         │ Hà Nội      │ Nghỉ trưa │
│ C3   │ Thắng cảnh đóng sớm  │ 1001    │ Hoàng thành Thăng Long│ Hà Nội     │ Đóng 17:00│
│ C4   │ Nhà hàng ăn trưa     │ 2264/2155│ Bún Chả Đắc Kim     │ HN / Khánh Hòa│ 11:30-13:30│
│ C5   │ Xung đột bất khả thi │ 1446+1865│ Chăm Museum + Sơn Trà│ Đà Nẵng     │ Xung đột  │
└──────┴──────────────────────┴─────────┴──────────────────────┴─────────────┴───────────┘
```

---

### 6.1. Ca Kiểm Thử 1: Chợ Đêm Mở Muộn (Late-Opening Night Market)
- **Thực thể kiểm thử**:
  - `id`: **`1865`**
  - `name`: **`Chợ Đêm Sơn Trà`**
  - `category`: `MARKET`
  - `province`: Đà Nẵng
  - `lat`, `lng`: `16.0608125`, `108.2316875`
  - `address`: `366J+8M, An Hải, Đà Nẵng 550000, Việt Nam`
  - `google_place_id`: `ChIJAdChYQAZQjERdBTX1_66Q_8`
  - `working_hours` thực tế: `17:30 to 23:45` (tương đương $[1050, 1425]$ phút từ nửa đêm).
  - `typical_time_spent`: `1h - 2h` $\implies$ chuẩn hóa thành $\text{Dwell} = 60\text{ phút}$.
- **Lỗ hổng của thuật toán cũ (Nearest Neighbor)**:
  Do Chợ Đêm Sơn Trà nằm ngay sát chân Cầu Rồng và đối diện Bảo tàng Điêu khắc Chăm (chỉ cách $1.2\text{ km}$), thuật toán tham lam gom nó vào chùm buổi sáng và xếp du khách đến lúc **09:30 sáng** khi các quầy hàng đang đóng cửa im lìm.
- **Hành vi kỳ vọng của 2-Opt TSPTW**:
  - Chợ Đêm Sơn Trà **bắt buộc bị đẩy về cuối ngày**, có $\text{Arrival} \ge 17:30$ (khung giờ vàng: $20:00 - 21:00$ sau bữa tối).
  - Thuật toán 2-Opt đưa các điểm tham quan ban ngày (Bán đảo Sơn Trà, Bãi biển Mỹ Khê) lên trước.
  - $\text{is\_time\_window\_valid} = \text{True}$, $\text{wait\_time\_minutes} = 0$.

---

### 6.2. Ca Kiểm Thử 2: Di Tích Có Giờ Nghỉ Trưa (Heritage Site with Midday Lunch Closure)
- **Thực thể kiểm thử**:
  - `id`: **`1012`**
  - `name`: **`Chùa Quán Sứ`** (Trung ương Giáo hội Phật giáo Việt Nam)
  - `category`: `TEMPLE`
  - `province`: Hà Nội
  - `lat`, `lng`: `21.0535`, `105.8692`
  - `address`: `73 P. Quán Sứ, Cửa Nam, Hà Nội`
  - `google_place_id`: `ChIJfVZXRpGrNTERbkZTVxqHSD0`
  - `working_hours` thực tế: `07:30 to 11:30, 13:30 to 17:30` (Đóng cửa then cài lúc trưa: $11:30 - 13:30$).
  - `typical_time_spent`: `90 phút` $\implies \text{Dwell} = 90\text{ phút}$.
- **Lỗ hổng của thuật toán cũ**:
  Xếp giờ đến lúc **11:00** hoặc **12:00 trưa**. Nếu đến lúc 11:00 với thời lượng tham quan 90 phút, du khách mới đi được 30 phút thì bị mời ra ngoài lúc 11:30 để đóng cửa chùa; nếu đến lúc 12:00 trưa thì đứng bơ vơ ngoài đường nắng gắt.
- **Hành vi kỳ vọng của 2-Opt TSPTW**:
  - Lộ trình phải được tối ưu để thỏa mãn 1 trong 2 nhánh hợp lệ:
    - *Nhánh Sáng*: $\text{Arrival} \le 10:00$ để bảo đảm $\text{Departure} = \text{Arrival} + 90 \le 11:30$.
    - *Nhánh Chiều*: Sau khi ăn trưa ($11:45 - 13:00$) và nghỉ ngơi, đến chùa vào ca chiều với $\text{Arrival} \ge 13:30$ (ví dụ: $14:00 - 15:30$).
  - Tuyệt đối không có bất kỳ phút tham quan nào rơi vào khoảng cấm $[11:30, 13:30]$.
  - $\text{is\_time\_window\_valid} = \text{True}$.

---

### 6.3. Ca Kiểm Thử 3: Thắng Cảnh Đóng Cửa Sớm Hoàng Hôn (Scenic Spot Sunset Closing)
- **Thực thể kiểm thử**:
  - `id`: **`1001`**
  - `name`: **`Hoàng thành Thăng Long`** (Di sản Văn hóa Thế giới)
  - `category`: `HISTORICAL_SITE`
  - `province`: Hà Nội
  - `lat`, `lng`: `21.0347`, `105.8406`
  - `address`: `19c Hoàng Diệu, Ba Đình, Hà Nội`
  - `google_place_id`: `ChIJSXwdOKOrNTERNylYj9mnIbU`
  - `working_hours` thực tế: `08:00 to 17:00` (Quầy vé dừng bán lúc 16:30, cổng đóng chặt lúc 17:00).
  - `typical_time_spent`: `90 phút` $\implies \text{Dwell} = 90\text{ phút}$.
- **Lỗ hổng của thuật toán cũ**:
  Do đi dạo các quán cafe hoặc hồ Tây buổi chiều, hệ thống tham lam đẩy Hoàng thành Thăng Long xuống cuối chiều với mốc đến **16:30**. Chuyến tham quan 90 phút sẽ kéo dài đến $18:00$, vi phạm nghiêm trọng giờ đóng cửa (bị bảo vệ từ chối cho vào cổng).
- **Hành vi kỳ vọng của 2-Opt TSPTW**:
  - Thuật toán 2-Opt hoán đổi thứ tự để Hoàng thành Thăng Long có $\text{Arrival} \le 15:30$, bảo đảm:
    $$\text{Departure} = \text{Arrival} + 90 \le 17:00$$
  - Hoặc đưa Hoàng thành Thăng Long lên ca sáng ($08:30 - 10:00$) để tận hưởng trọn vẹn khuôn viên di tích rộng lớn.
  - $\text{is\_time\_window\_valid} = \text{True}$.

---

### 6.4. Ca Kiểm Thử 4: Nhà Hàng Khóa Khung Ăn Trưa Cố Định (Fixed Lunch Dining Window)
- **Thực thể kiểm thử**:
  - `id`: **`2264`**
  - `name`: **`Nhà hàng Bún Chả Đắc Kim`**
  - `category`: `RESTAURANT`
  - `province`: Hà Nội
  - `lat`, `lng`: `21.0315`, `105.8491`
  - `address`: `1 P. Hàng Mành, Phố cổ Hà Nội, Hoàn Kiếm, Hà Nội, Việt Nam`
  - `google_place_id`: `ChIJF5qJQL6rNTER5PCg1SoKopo`
  - `working_hours` thực tế: `09:00 to 21:00`.
  - `typical_time_spent`: `75 phút` $\implies \text{Dwell} = 75\text{ phút}$.
  *(Ghi chú: Đối với kịch bản ngoại tỉnh, có thể sử dụng bản ghi tương đương `id: 2155` - `Nhà Hàng Gà Đồi Điện Biên`, tọa độ `12.2880, 109.1923`, Dwell 70 phút).*
- **Lỗ hổng của thuật toán cũ**:
  Do quán ăn nằm sát các điểm di tích phố cổ, thuật toán Nearest Neighbor thuần túy xếp quán ăn vào lúc **08:30 sáng** (ngay sau khi vừa ăn sáng xong) hoặc bị đẩy xuống **15:30 chiều** (giờ trà chiều) chỉ vì khoảng cách địa lý ngắn nhất.
- **Hành vi kỳ vọng của 2-Opt TSPTW**:
  - Nhà hàng ăn trưa được neo chặt (hard-locked) vào cửa sổ nhịp sinh học trưa:
    $$\text{Arrival} \in [11:30, 12:30], \quad \text{Departure} \in [12:45, 13:45]$$
  - Các hoạt động tham quan sáng phải kết thúc trước $11:30$ để nhường chỗ cho bữa trưa.
  - Tuyệt đối không xếp bữa ăn chính vào các khung giờ phản khoa học (như 09:00 sáng hay 15:00 chiều).

---

### 6.5. Ca Kiểm Thử 5: Xử Lý Xung Đột Bất Khả Thi (Impossible Time-Window Conflict)
- **Thực thể kiểm thử**:
  - Điểm A: **`Chợ Đêm Sơn Trà`** (`id: 1865`, mở cửa `17:30 - 23:45`, Dwell 60m).
  - Điểm B: **`Bảo tàng Điêu khắc Chăm Đà Nẵng`** (`id: 1446`, `lat: 16.0603, lng: 108.2236`, mở cửa `07:00 - 17:00`, đóng cửa $17:00$, Dwell 90m).
  - Khoảng cách giữa 2 điểm: $\approx 1.5\text{ km}$ (qua Cầu Rồng).
- **Tình huống xung đột (Adversarial Infeasible Input)**:
  Người dùng thiết lập ràng buộc cứng (Hard-pin): Bắt buộc đi Chợ Đêm Sơn Trà trước lúc $18:00$, sau đó mới di chuyển sang Bảo tàng Điêu khắc Chăm:
  - Rời Chợ Đêm Sơn Trà: $18:00 + 60\text{m} = 19:00$.
  - Di chuyển sang Bảo tàng Chăm: $5\text{ phút} \implies \text{EstimatedArrival} = 19:05$.
  - Trong khi đó, Bảo tàng Chăm đóng cửa lúc $17:00$.
  - Thời gian trễ: $\text{Lateness} = (19:05 + 90\text{m}) - 17:00 = 20:35 - 17:00 = 215\text{ phút}$ (hoặc trễ giờ đến $125\text{ phút}$).
- **Quy trình xử lý phòng thủ (Graceful Degradation Protocol)**:
  1. **Không Crash**: Tuyệt đối không văng lỗi 500 hay ngắt quãng luồng xử lý.
  2. **Gán Metadata Vi phạm**:
     - `is_time_window_valid = False`
     - `arrival_time = "19:05"`
     - `departure_time = "20:35"`
  3. **Kích hoạt Thẻ Cảnh Báo (Smart Advisory Card)**:
     - Trường `time_window_advisory` được gán thông điệp rõ ràng:
       > *"⚠️ Xung đột thời gian: Bảo tàng Điêu khắc Chăm đóng cửa lúc 17:00, nhưng theo lộ trình bạn sẽ đến lúc 19:05 (quá giờ 125 phút). Khuyên bạn nên đổi Bảo tàng Chăm lên buổi sáng hoặc chuyển sang ngày khác."*
  4. **Hiển thị Frontend**: Timeline hiển thị badge màu đỏ cam kèm icon cảnh báo để người dùng chủ động điều chỉnh.

---

## 7. HỢP ĐỒNG DỮ LIỆU ĐẦU RA (OUTPUT DATA CONTRACT & SCHEMA)

### 7.1. Cấu Trúc Chi Tiết Của Từng Chặng Dừng Trong Timeline (`ItineraryStep`)
Để bảo đảm **tương thích ngược 100%** với API `POST /api/plan/calculate` và giao diện web hiện tại `frontend/index.html`, mỗi phần tử trong danh sách chặng dừng của từng ngày phải tuân thủ schema JSON sau:

```json
{
  "step": 1,
  "name": "Hoàng thành Thăng Long",
  "category": "HISTORICAL_SITE",
  "suggested_time": "08:30",
  "arrival_time": "08:30",
  "departure_time": "10:00",
  "dwell_time_minutes": 90,
  "wait_time_minutes": 0,
  "is_time_window_valid": true,
  "time_window_display": "08:00 - 17:00",
  "time_window_advisory": null,
  "period_name": "Danh thắng / Di tích sáng mát",
  "period_icon": "🏛️",
  "address": "19C Hoàng Diệu, Quán Thánh, Ba Đình, Hà Nội",
  "lat": 21.0347,
  "lng": 105.8406,
  "rating": 4.5,
  "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/...",
  "phone_number": "024 3734 5484",
  "website": "http://hoangthanhthanglong.vn/",
  "google_maps_url": "https://www.google.com/maps/place/?q=place_id:ChIJSXwdOKOrNTERNylYj9mnIbU",
  "price_display": "Miễn phí vé vào / Tự do tham quan",
  "price_info": {
    "has_price": false,
    "display": "Miễn phí vé vào / Tự do tham quan",
    "type_label": "Điểm tham quan / Chợ (Không mất vé)"
  }
}
```

### 7.2. Từ Điển Các Trường Dữ Liệu (Field Dictionary)

| Tên Trường (Field) | Kiểu Dữ Liệu | Nguồn Gốc | Mô Tả Ý Nghĩa & Ràng Buộc Kỹ Thuật |
| :--- | :---: | :---: | :--- |
| `step` | `int` | Cũ | Số thứ tự chặng dừng trong ngày ($1, 2, \dots, N$). |
| `name` | `str` | Cũ | Tên chính thức của địa điểm từ `travel_db.db`. |
| `category` | `str` | Cũ | Danh mục (`ATTRACTION`, `TEMPLE`, `RESTAURANT`, ...). |
| `suggested_time` | `str` (HH:MM) | **Cũ (Giữ nguyên)** | Thời điểm đề xuất hiển thị trên giao diện hiện tại. **Bắt buộc gán bằng `arrival_time`** để bảo đảm tương thích ngược hoàn hảo. |
| `arrival_time` | `str` (HH:MM) | **Mới (P0)** | Thời điểm thực tế du khách đặt chân tới điểm tham quan (đã tính thời gian di chuyển và thời gian chờ nếu đến sớm). |
| `departure_time` | `str` (HH:MM) | **Mới (P0)** | Thời điểm kết thúc tham quan: $\text{Arrival} + \text{Dwell}$. |
| `dwell_time_minutes` | `int` | **Mới (P0)** | Số phút du khách lưu trú trải nghiệm tại điểm. |
| `wait_time_minutes` | `int` | **Mới (P0)** | Số phút du khách phải đứng chờ ngoài cổng nếu đến trước giờ mở cửa. |
| `is_time_window_valid` | `bool` | **Mới (P0)** | `True` nếu chuyến thăm kết thúc trước giờ đóng cửa và không vi phạm giờ nghỉ trưa; `False` nếu bị vi phạm. |
| `time_window_display` | `str` | **Mới (P0)** | Chuỗi giờ mở cửa thực tế để hiển thị trên UI (ví dụ: `"08:00 - 17:00"` hoặc `"07:30 - 11:30, 13:30 - 17:30"`). |
| `time_window_advisory` | `Optional[str]`| **Mới (P0)** | Thông điệp cảnh báo người dùng nếu có xung đột thời gian hoặc `None` nếu hợp lệ. |
| `period_name` | `str` | Cũ | Tên nhịp sinh học (ví dụ: `"Đón bình minh & Tắm sớm"`). |
| `period_icon` | `str` | Cũ | Emoji đại diện nhịp sinh học (ví dụ: `"🌅"`, `"🏛️"`). |

### 7.3. Định Nghĩa Pydantic Schema Cho Tầng API (`app/models.py`)
```python
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class ItineraryStepSchema(BaseModel):
    step: int = Field(..., description="Thứ tự chặng dừng trong ngày (1-indexed)")
    name: str = Field(..., description="Tên địa danh")
    category: str = Field(..., description="Danh mục địa danh")
    
    # Backward Compatibility Aliases
    suggested_time: str = Field(..., description="Thời gian đề xuất (đồng bộ với arrival_time)")
    period_name: str = Field(..., description="Tên nhịp sinh học tương ứng")
    period_icon: str = Field(..., description="Biểu tượng nhịp sinh học")
    
    # Real-Time Operational Time-Window Metadata
    arrival_time: str = Field(..., description="Thời điểm đến thực tế (HH:MM)")
    departure_time: str = Field(..., description="Thời điểm rời đi (HH:MM)")
    dwell_time_minutes: int = Field(..., description="Thời gian lưu trú (phút)")
    wait_time_minutes: int = Field(0, description="Thời gian chờ mở cửa (phút)")
    is_time_window_valid: bool = Field(True, description="Cờ hợp lệ khung giờ mở cửa")
    time_window_display: str = Field(..., description="Giờ hoạt động thực tế (ví dụ: 08:00 - 17:00)")
    time_window_advisory: Optional[str] = Field(None, description="Cảnh báo xung đột thời gian nếu có")
    
    # Ground Truth Coordinates & Information
    address: str = Field(..., description="Địa chỉ thực địa 100%")
    lat: float = Field(..., description="Vĩ độ GPS")
    lng: float = Field(..., description="Kinh độ GPS")
    rating: float = Field(0.0, description="Điểm đánh giá Google")
    image_url: Optional[str] = Field(None, description="Đường dẫn ảnh thực tế")
    phone_number: Optional[str] = Field(None, description="Số điện thoại liên hệ")
    website: Optional[str] = Field(None, description="Trang web chính thức")
    google_maps_url: Optional[str] = Field(None, description="Đường dẫn Google Place ID xác thực")
    price_display: str = Field(..., description="Chuỗi hiển thị giá vé / chi phí")
    price_info: Dict[str, Any] = Field(default_factory=dict, description="Chi tiết cấu trúc giá")
```

---

## 8. HƯỚNG DẪN BÀN GIAO & LỘ TRÌNH THỰC THI (HANDOFF GUIDELINES)

### 8.1. Nhiệm Vụ Cho Kỹ Sư Giải Thuật (Milestone 2 - Algorithm Engineer)
File phụ trách duy nhất: `app/services/travel_calculator.py`.

1. **Triển khai Hàm Tiện ích Thời Gian**:
   - `parse_working_hours(hours_str: str) -> List[Tuple[int, int]]`: Chuyển đổi chuỗi `"07:30 to 11:30, 13:30 to 17:30"` thành danh sách cặp phút: `[(450, 690), (810, 1050)]`.
   - `parse_dwell_time(typical_time_spent: Optional[str], category: str) -> int`: Parse số phút theo Bảng luật Mục 3.2 và Fallback Mục 3.3.
   - `compute_travel_time(lat1: float, lng1: float, lat2: float, lng2: float, k_topo: float, v_avg: float) -> int`: Tính thời gian di chuyển làm tròn phút theo Mục 2.2.

2. **Bảng Fallback Giờ Mở Cửa khi DB Thiếu Cache `openingHours`**:
   Khi một địa điểm chưa có trường mở cửa thực tế:
   - `MARKET`: mặc định `[(360, 1140)]` ($06:00 - 19:00$). Nếu tên có từ "đêm" $\implies [(1050, 1425)]$ ($17:30 - 23:45$).
   - `TEMPLE` / `HISTORICAL_SITE`: mặc định `[(450, 1020)]` ($07:30 - 17:00$).
   - `RESTAURANT`: mặc định hai ca `[(660, 840), (1080, 1320)]` ($11:00 - 14:00$ và $18:00 - 22:00$).
   - `ATTRACTION`: mặc định `[(480, 1080)]` ($08:00 - 18:00$).
   - `HOTEL`: mặc định $24/24$ `[(0, 1440)]`.

3. **Thuật toán 2-Opt TSPTW**:
   - Nâng cấp hàm `sequence_by_human_rhythm` và `optimize_route`.
   - Vòng lặp 2-Opt duyệt các cặp cạnh, thực hiện hoán đổi và kiểm tra qua `Cổng 1` (giảm cự ly) và `Cổng 2` (mô phỏng xuôi dòng không vi phạm đóng cửa).
   - Bảo đảm thời gian thực thi $< 15\text{ms}$ cho cụm $N \le 10$.

### 8.2. Nhiệm Vụ Cho Kỹ Sư Kiểm Thử (Milestone 3 - Test Verification Engineer)
File phụ trách duy nhất: `tests/test_tsptw_routing.py`.

1. **Xây dựng 5 Hàm Test Tương Ứng Với Ma Trận Mục 6**:
   - `test_case_1_night_market_late_opening_son_tra()`: Khẳng định Chợ Đêm Sơn Trà (ID `1865`) luôn được xếp sau $17:30$.
   - `test_case_2_heritage_site_lunch_break_quan_su()`: Khẳng định Chùa Quán Sứ (ID `1012`) không có phút tham quan nào rơi vào $11:30 - 13:30$.
   - `test_case_3_scenic_spot_sunset_closing_hoang_thanh()`: Khẳng định Hoàng thành Thăng Long (ID `1001`) luôn rời đi trước hoặc bằng $17:00$.
   - `test_case_4_fixed_lunch_restaurant_dac_kim()`: Khẳng định Bún Chả Đắc Kim (ID `2264`) luôn rơi vào khung $11:30 - 13:30$.
   - `test_case_5_impossible_conflict_graceful_advisory()`: Khẳng định kịch bản xung đột trả về `is_time_window_valid = False` và có `time_window_advisory` chi tiết, không crash 500.

2. **Kiểm Thử Hiệu Năng & Khử Đường Cắt Chéo**:
   - `test_2opt_eliminates_crossing_edges()`: Tạo lộ trình có 2 cạnh cắt chéo chữ X, khẳng định 2-Opt gỡ bỏ hoàn toàn giao cắt.
   - `test_tsptw_execution_latency_under_15ms()`: Chạy 100 lần với $N = 10$, khẳng định thời gian xử lý bình quân $< 15\text{ms}$.

3. **Bảo Toàn Bộ Test Sẵn Có**:
   - Khẳng định toàn bộ 95 test case hiện tại trong `tests/` tiếp tục đạt **100% PASSED** mà không có bất kỳ regression nào.

---
**HẾT TÀI LIỆU ĐẶC TẢ NGHIỆP VỤ SPEC-TSPTW-VN-2026-P0**
