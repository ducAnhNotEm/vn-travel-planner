# Travel UI & UX Engineering Standard (Top 0.1% Field-Grade Specification)

> **Mục tiêu**: Chuẩn hóa toàn bộ trải nghiệm hiển thị (Information Architecture, Pacing Hierarchy, Decision Explainability, Mobile Field Ergonomics) cho hệ thống **VN Travel Planner**.
> Chắt lọc tinh hoa từ các hệ thống UX thực chiến cao cấp (Maps/Transit/Field Apps), loại bỏ toàn bộ trang trí sáo rỗng (Visual Fluff), phục vụ trực tiếp các ràng buộc cốt lõi tại `AGENTS.md`.

---

## 1. Information Architecture & Spatial System (Cấu trúc Không gian & Thứ bậc)

### 1.1. Native Dual-Plane Layout (Mô hình 2 Mặt phẳng Tương tác)
Tuyệt đối không dùng bố cục dạng cột (multi-column) kiểu desktop cổ điển. Ứng dụng du lịch thực tế bắt buộc chạy theo mô hình **Map Canvas + Bottom Sheet/Drawer**:
- **Plane 0 (Underlay - Background Canvas)**: MapLibre / Leaflet vector map toàn màn hình (Full viewport $100\text{vw} \times 100\text{vh}$).
- **Plane 1 (Overlay - Interactive Drawer)**: Cửa sổ vuốt (Interactive Sheet) với 3 nấc neo (Snap Points):
  - `Collapsed` ($12\text{vh}$ / $96\text{px}$): Thanh tóm tắt chặng hiện tại + nút điều hướng nhanh (Quick Actions).
  - `Half-expanded` ($45\text{vh}$): Timeline trong ngày hiện tại, cho phép vừa quan sát bản đồ vừa kiểm tra các chặng dừng.
  - `Fully-expanded` ($88\text{vh}$): Chi tiết toàn bộ lịch trình đa ngày, bảng kê chi phí nhóm và thiết lập tùy chỉnh.

### 1.2. The 3-Piece Transit Visualization Hierarchy (Hiển thị Lộ trình 3 Mảnh)
Khi kích hoạt chế độ trung chuyển đa phương thức (Multi-Modal Transit $\ge 300\text{km}$):
1. **First-mile**: Nét liền màu xanh dương (`#2563EB`, stroke $4\text{px}$), thể hiện đường bộ kết nối tới Sân bay Cửa ngõ (Gateway Airport).
2. **Air Corridor**: Nét đứt (dashed $6\text{px}$ gap $6\text{px}$) màu tím hàng không (`#7C3AED`, stroke $3\text{px}$), cung geodesic nối 2 mã IATA (VD: `HAN` $\to$ `DAD`), có icon máy bay định vị giữa chặng.
3. **Last-mile**: Nét liền màu xanh ngọc (`#0D9488`, stroke $4\text{px}$), đường bộ đón từ sân bay đến khách sạn/điểm đến.

---

## 2. Pacing Rhythm & Timeline Cards (Nhịp sinh học Du lịch Thực địa)

### 2.1. Biological Slot Indicators (Mã màu Nhịp sinh học)
Khung giờ không được để chữ xám đơn điệu mà phải có dải màu biên (Border Accent) phản ánh đúng tính chất nhịp sinh học theo quy tắc tại `AGENTS.md`:

| Nhịp sinh học | Khoảng giờ | Border Accent | Icon Token | Tính chất vận động |
| :--- | :--- | :--- | :--- | :--- |
| **Bình minh / Sáng sớm** | `05:30 - 08:30` | Amber (`#F59E0B`) | `🌅 / 🍜` | Săn mây, tắm biển sớm, nạp năng lượng đặc sản. |
| **Năng lượng cao (Sightseeing)** | `08:30 - 11:30` | Sky (`#0284C7`) | `🏛️ / 🌲` | Di tích, văn hóa, danh thắng ngoài trời. |
| **Bữa trưa địa phương** | `11:45 - 13:00` | Orange (`#EA580C`) | `🍲` | Nghỉ chân ăn trưa, tránh nắng đỉnh điểm. |
| **Nghỉ trưa bắt buộc (Siesta Guard)** | `13:00 - 15:00` | Indigo (`#6366F1`) | `🏨 / ☕` | **Cấm hoạt động nắng gắt**. Khách sạn hoặc cafe yên tĩnh. |
| **Chiều mát & Hoàng hôn** | `15:30 - 18:00` | Teal (`#0D9488`) | `🌊 / 🌸` | Biển chiều, làng nghề, ngắm hoàng hôn. |
| **Ẩm thực tối & Phố đêm** | `18:30 - 22:30` | Rose / Violet (`#E11D48`) | `🦀 / 🏮` | Hải sản, lẩu nướng, chợ đêm, phố đi bộ. |

### 2.2. Fatigue Break Marker (Trạm dừng Chống Kiệt sức Sinh học)
- Khi thời gian lái xe liên tục giữa 2 điểm $\ge 3\text{ giờ}$ hoặc cự ly $\ge 180\text{ km}$:
  - Tự động chèn thẻ **"Trạm dừng nghỉ khuyến nghị" (Biological Rest Stop)**:
  - Background: Muted Slate (`#F1F5F9`), viền đứt màu cảnh báo cam nhẹ (`#FDBA74`).
  - Nội dung: `[Nghỉ 30-45 phút: Uống nước, giãn cơ, đổ xăng]`. Tuyệt đối không để timeline liền mạch tạo cảm giác lái xe kiệt sức.

---

## 3. Decision Explainability & Smart Advisory UX (Minh bạch Quyết định Thuật toán)

### 3.1. Smart Advisory Card (Thẻ Cảnh báo Điểm Outlier)
Khi thuật toán phát hiện điểm người dùng muốn ghé cách cụm chính $\ge 15 - 20\text{ km}$ ($> 35\text{ phút}$ di chuyển):
- **Cấu trúc Thẻ Advisory**:
  ```markdown
  ┌──────────────────────────────────────────────────────────────────┐
  │ ⚠️ ĐIỂM CÁCH XA CỤM THAM QUAN CHÍNH (~22 km • Tốn thêm 45 phút)   │
  ├──────────────────────────────────────────────────────────────────┤
  │ Quán Cà Phê Suối Mơ nằm lệch hẳn so với cụm Tràng An - Bái Đính.  │
  │ Lựa chọn xử lý tối ưu:                                           │
  │                                                                  │
  │ [✓] Phương án A (Khuyên dùng): Gợi ý quán cafe view đầm sen      │
  │     ngay cạnh Tràng An (< 1.5 km, tiết kiệm 120.000đ tiền taxi). │
  │                                                                  │
  │ [ ] Phương án B: Giữ nguyên điểm này (Tự động chuyển xuống cuối  │
  │     ngày trên đường về khách sạn).                               │
  └──────────────────────────────────────────────────────────────────┘
  ```
- **Tương tác**: Không phán xét người dùng, có nút chuyển đổi 1-chạm giữa Phương án A và B.

### 3.2. Hotel Switch Reasoner (Giải thích Đổi Khách sạn)
Khi thẻ đề xuất chuyển khách sạn xuất hiện:
- Phải hiển thị bảng **Trade-off Matrix Mini**:
  - `Quãng đường di chuyển tiết kiệm`: $\Delta D \ge 25\text{ km}$ ($> 45\text{ phút}$).
  - `Chi phí khách sạn chênh lệch`: So sánh giá phòng giữa khách sạn cũ và mới.
  - Badge cảnh báo: *"Chỉ đề xuất đổi vì tiết kiệm đáng kể thời gian di chuyển ngày hôm sau"*.

---

## 4. Verification Badge & Two-Speed Indicator (Minh bạch Độ tin cậy Dữ liệu)

Tuân thủ nguyên tắc Two-Speed Place Resolution tại `AGENTS.md`:

| Trạng thái | Visual Badge | Chi tiết hiển thị | Tương tác |
| :--- | :--- | :--- | :--- |
| **Lane A (Geocoding sơ bộ)** | `⚠️ Chưa xác minh đầy đủ` (Badge Vàng hổ phách `#F59E0B`) | Tọa độ & địa chỉ tạm thời. Ẩn giờ mở cửa nếu chưa có dữ liệu. | Có nút "Đang tải dữ liệu thực địa..." (Spinner vi mô). |
| **Lane B (Đã xác minh Apify/DB)** | `✅ Đã xác minh` (Badge Xanh ngọc `#10B981`) | Giờ mở cửa chuẩn, Google Place ID, ảnh thật Wikimedia/Google CDN. | Hiện nút ghim bản đồ Google Maps chính thức. |
| **Địa chỉ không có thật** | ❌ **ẨN NÚT BẢN ĐỒ** | Thà để `NULL` hoặc hiện cảnh báo tọa độ tương đối, **tuyệt đối cấm tạo URL tìm kiếm giả mạo**. | - |

---

## 5. Mobile Field Ergonomics & 1-Click Action Hand-off (Công thái học Thực địa)

### 5.1. Thumb Zone Accessibility (Vùng tương tác Ngón tay cái)
- Mọi nút bấm thao tác cốt lõi trong lúc đang di chuyển (`Mở Google Maps`, `Gọi Hotline`, `Đổi chặng`) phải nằm trong vùng **$40\%$ đáy màn hình**.
- Kích thước chạm tối thiểu (Touch Target): **$48\text{px} \times 48\text{px}$** (vượt chuẩn WCAG $44\text{px}$).
- Tỷ lệ tương phản chữ/nền: Tối thiểu **$4.5:1$** (Normal text) và **$7:1$** cho các thông số giờ giấc/cảnh báo ngoài trời.

### 5.2. Actionable Hand-off Bar (Thanh Xuất bản Lộ trình 1-Chạm)
Cung cấp thanh điều hướng ghim cố định ở đáy (Sticky Bottom Bar) khi người dùng hoàn thiện lịch trình:
- **Button 1 (Primary - Emerald `#059669`)**: `🗺️ Dẫn đường toàn ngày trên Google Maps` (Mở URL Google Multi-stop `https://www.google.com/maps/dir/...`).
- **Button 2 (Secondary - Slate `#334155`)**: `📅 Đồng bộ Lịch (iCal / Google Calendar)` (Tải file `.ics` có nhắc nhở trước 15 phút).
- **Button 3 (Tertiary Outline)**: `📤 Chia sẻ nhóm (Copy Link / QR Code)`.

---

## 6. Implementation Checklist cho Frontend Engine
- [ ] Tích hợp CSS Variable Tokens đồng bộ theo bảng màu nhịp sinh học (§2.1).
- [ ] Component `SmartAdvisoryCard` có khả năng render hai nhánh lựa chọn A/B (§3.1).
- [ ] Component `TwoSpeedBadge` tự động chuyển trạng thái qua polling SSE (§4).
- [ ] Engine sinh Google Maps Multi-stop URL và iCal export tương thích chuẩn RFC 5545 (§5.2).
