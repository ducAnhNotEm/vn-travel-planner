# Travel UI & UX Engineering Standard (Top 0.1% Field-Grade Specification)

> **Mục tiêu**: Chuẩn hóa toàn bộ trải nghiệm hiển thị (Information Architecture, Pacing Hierarchy, Decision Explainability, Mobile Field Ergonomics) cho hệ thống **VN Travel Planner**.
> Chắt lọc tinh hoa từ các hệ thống UX thực chiến cao cấp (Maps/Transit/Field Apps), loại bỏ toàn bộ trang trí sáo rỗng (Visual Fluff), phục vụ trực tiếp các ràng buộc cốt lõi tại `AGENTS.md`.

---

## 0. Triết lý Thiết kế: "Foolproof & Frictionless UX" (Đơn giản đến mức ai cũng hiểu ngay)

> **Tôn chỉ tối thượng**: *"Giao diện phải đơn giản, mạch lạc và trực quan đến mức con bò cũng hiểu được và thao tác ngay mà không cần đọc hướng dẫn."*
> Triệt tiêu hoàn toàn gánh nặng nhận thức (Zero Cognitive Load), không giấu tính năng vào các menu con phức tạp, không bắt người dùng đoán xem hệ thống đang làm gì.

### 3 Nguyên tắc Bất biến của Giao diện Siêu Trực Quan:
1. **Luồng tuyến tính một chiều (Linear 1-Way Funnel)**:
   - Tuyệt đối không nhảy cóc hay hiển thị quá nhiều quyết định cùng lúc.
   - Luồng thao tác đi thẳng một đường duy nhất: **Nhập ý định / Chọn tỉnh $\to$ Bấm [Gợi ý] $\to$ Duyệt 4 nhóm & Tick chọn $\to$ Bấm [Lập lịch trình ngay] $\to$ Mở Google Maps đi chơi**.
2. **Minh bạch phân nhóm (Strict 4-Category Separation)**:
   - Nghiêm cấm đổ dồn một đống danh lam thắng cảnh, quán ăn, khách sạn vào chung một danh sách hỗn độn.
   - Bắt buộc chia tách thành **4 phân mục trực quan riêng biệt**: Khách sạn, Nhà hàng, Điểm Must-Visit, Khu vui chơi/Chợ.
3. **1-Chạm ra thực địa (1-Click Field Hand-off)**:
   - Mục đích tối thượng của ứng dụng là phục vụ người dùng lúc đang đi ngoài đường. Mọi chặng dừng trên lịch trình bắt buộc phải có nút ghim Google Maps để chạm 1 cái là bật định vị dẫn đường ngay lập tức.

---

## 1. Luồng Lập Lịch Trình 2 Bước Chuẩn Hóa (The 2-Button Planning Workflow)

Toàn bộ quy trình lập kế hoạch chuyến đi được đóng gói trong **chính xác 2 nút bấm quyết định**:

```
[ BƯỚC 1: ĐẦU VÀO ]
  Người dùng nhập Natural Language Prompt (VD: "Đà Nẵng 3 ngày ăn hải sản")
  HOẶC Chọn thủ công Tỉnh/Thành phố từ Menu Dropdown
        │
        ▼
  [ NÚT 1: ✨ GỢI Ý ĐỊA ĐIỂM ]
        │
        ▼
[ HIỂN THỊ 4 PHÂN MỤC ĐỘC LẬP ĐỂ NGƯỜI DÙNG TICK CHỌN ]
  ┌──────────────────────────────────────────────────────────────┐
  │ 🏨 1. Khách Sạn & Nơi Lưu Trú (Hotels & Resorts)              │
  │    (Gợi ý khách sạn có giá phòng, số sao từ Database)         │
  ├──────────────────────────────────────────────────────────────┤
  │ 🍲 2. Nhà Hàng & Ẩm Thực Địa Phương (Dining & Specialties)    │
  │    (Quán ăn ngon, hải sản tươi, đặc sản vùng miền)           │
  ├──────────────────────────────────────────────────────────────┤
  │ ⭐ 3. Điểm Must-Visit Tiêu Biểu (Landmarks & Heritage)        │
  │    (Danh lam thắng cảnh, di tích lịch sử bắt buộc phải ghé)  │
  ├──────────────────────────────────────────────────────────────┤
  │ 🎡 4. Khu Vui Chơi, Hoạt Động & Chợ (Activities & Markets)   │
  │    (Chợ đêm, chợ truyền thống, điểm check-in, công viên)     │
  └──────────────────────────────────────────────────────────────┘
  * Cơ chế: Hệ thống tự tick sẵn (Pre-selected) 2-3 điểm tiêu biểu nhất mỗi nhóm.
            Người dùng tự do tick thêm hoặc bỏ chọn theo nhu cầu.
            Hiển thị Badge số lượng: "Đã chọn: X điểm".
        │
        ▼
[ BƯỚC 2: CHỐT LỊCH TRÌNH ]
  [ NÚT 2: 🚀 LẬP LỊCH TRÌNH NGAY (X điểm đã chọn) ] (Nút Quyết Định)
        │
        ▼
[ HIỂN THỊ LỊCH TRÌNH CHI TIẾT (ITINERARY VIEW) ]
  - Bản đồ tuyến đường (Leaflet / Goong Static)
  - Timeline từng ngày (Ngày 1, Ngày 2, ...) theo nhịp sinh học
  - 📍 TẤT CẢ các địa điểm đều có NÚT GHIM GOOGLE MAPS trực tiếp
```

### Chi tiết Đặc tả 2 Nút Bấm:

#### Nút 1: `[ ✨ Gợi ý địa điểm ]` (Discovery Action)
- **Vị trí**: Nằm ngay cạnh ô nhập Prompt và ô chọn Tỉnh/Thành phố.
- **Hành vi khi bấm**:
  - Truy vấn `travel_db.db` lọc ra các địa điểm phù hợp nhất với tỉnh hoặc từ khóa prompt.
  - Phân loại tức thì vào 4 phân vùng giao diện riêng biệt:
    1. 🏨 **Khách sạn**: Hiện rõ hạng sao, tầm giá/đêm (`places.price_range`).
    2. 🍲 **Nhà hàng**: Hiện tên đặc sản, thời gian phục vụ trưa/tối.
    3. ⭐ **Must-Visit**: Điểm có gắn nhãn `is_must_visit = 1` hoặc rating cao nhất.
    4. 🎡 **Vui chơi / Chợ**: Chợ dân sinh, chợ đêm, danh thắng mở tự do.
  - Mỗi thẻ địa điểm hiển thị: Ảnh thật xác thực, Tên, Địa chỉ thực tế, Giá tham khảo và **Checkbox chọn/bỏ chọn**.

#### Nút 2: `[ 🚀 Lập lịch trình ngay ]` (Commit & Route Optimization Action)
- **Vị trí**: Ghim cố định ở chân màn hình chọn điểm (Sticky Floating Bar), luôn hiển thị trong tầm mắt kể cả khi cuộn trang.
- **Trạng thái**: Hiển thị rõ số lượng điểm người dùng đã chọn (Ví dụ: `Lập lịch trình ngay (8 điểm đã chọn) ➔`).
- **Hành vi khi bấm**:
  - Đóng gói toàn bộ các điểm đã chọn gửi lên endpoint `/api/plan/calculate`.
  - Core Engine chạy thuật toán 2-Opt TSPTW, gom cụm ngày, tối ưu lộ trình và ghép khung giờ sinh học.
  - Chuyển màn hình mượt mà sang **Màn hình Lịch trình Chi tiết (Screen Itinerary)**.

---

## 2. Information Architecture & Spatial System (Cấu trúc Không gian & Thứ bậc)

### 2.1. Native Dual-Plane Layout (Mô hình 2 Mặt phẳng Tương tác)
Tuyệt đối không dùng bố cục dạng cột (multi-column) kiểu desktop cổ điển. Ứng dụng du lịch thực tế bắt buộc chạy theo mô hình **Map Canvas + Bottom Sheet/Drawer**:
- **Plane 0 (Underlay - Background Canvas)**: MapLibre / Leaflet vector map toàn màn hình (Full viewport $100\text{vw} \times 100\text{vh}$).
- **Plane 1 (Overlay - Interactive Drawer)**: Cửa sổ vuốt (Interactive Sheet) với 3 nấc neo (Snap Points):
  - `Collapsed` ($12\text{vh}$ / $96\text{px}$): Thanh tóm tắt chặng hiện tại + nút điều hướng nhanh (Quick Actions).
  - `Half-expanded` ($45\text{vh}$): Timeline trong ngày hiện tại, cho phép vừa quan sát bản đồ vừa kiểm tra các chặng dừng.
  - `Fully-expanded` ($88\text{vh}$): Chi tiết toàn bộ lịch trình đa ngày, bảng kê chi phí nhóm và thiết lập tùy chỉnh.

### 2.2. The 3-Piece Transit Visualization Hierarchy (Hiển thị Lộ trình 3 Mảnh)
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

### 5.3. Quy Chuẩn Ghim URL Google Maps Từng Điểm (Per-Stop Google Maps Pin Hand-off)
Ở màn hình lịch trình chi tiết (Itinerary View) của từng ngày:
- **Nguyên tắc cốt lõi**: Phục vụ người dùng lúc đang di chuyển thực địa trên đường phố. Tuyệt đối không để người dùng phải tự gõ lại tên quán hay copy paste địa chỉ.
- **Quy chuẩn hiển thị nút ghim (📍)**:
  - Trên **TẤT CẢ** các thẻ địa điểm trong Timeline của từng ngày (Ngày 1, 2, 3...), bắt buộc phải có nút bấm mở Google Maps trực tiếp:
    ```html
    <a href="{place.google_maps_url}" target="_blank" 
       class="inline-flex items-center gap-1.5 px-3 py-1 bg-orange-50 hover:bg-brand-orange hover:text-white text-brand-orange border border-orange-200 rounded-lg text-xs font-bold transition shadow-xs">
      <i class="fa-solid fa-location-dot text-xs"></i>
      <span>Xem trên GG Maps</span>
    </a>
    ```
  - Nút bấm phải nổi bật, rõ ràng, đặt ngay cạnh tên địa điểm hoặc ở thanh hành động của thẻ.
- **Hành vi kích hoạt**:
  - Khi người dùng chạm/ấn vào nút: Mở thẳng ứng dụng Google Maps (trên điện thoại) hoặc mở tab mới Google Maps (trên máy tính) với tọa độ hoặc Google Place ID chuẩn xác (`place_id:ChIJ...`), lập tức sẵn sàng cho chế độ dẫn đường Turn-by-turn Navigation.

---

## 6. Implementation Checklist cho Frontend Engine
- [ ] Luồng 2 Bước / 2 Nút Chuẩn Tuyến Tính:
  - [ ] Nút 1: `[ ✨ Gợi ý địa điểm ]` phân loại dữ liệu tức thì vào 4 phân vùng độc lập (Khách sạn, Nhà hàng, Must-visit, Chợ/Vui chơi) (§1).
  - [ ] Hệ thống tự tick sẵn (Pre-selected) 2-3 điểm tiêu biểu mỗi nhóm và có thanh đếm tổng số điểm đã chọn (§1).
  - [ ] Nút 2: `[ 🚀 Lập lịch trình ngay ]` dạng Sticky Bar ở chân màn hình để chốt danh sách và chuyển sang xem lịch trình (§1).
- [ ] Tích hợp CSS Variable Tokens đồng bộ theo bảng màu nhịp sinh học (§2.1).
- [ ] Component `SmartAdvisoryCard` có khả năng render hai nhánh lựa chọn A/B (§3.1).
- [ ] Component `TwoSpeedBadge` tự động chuyển trạng thái qua polling SSE (§4).
- [ ] 100% các thẻ địa điểm trên timeline từng ngày đều có Nút Ghim Google Maps URL chuẩn xác (§5.3).
- [ ] Engine sinh Google Maps Multi-stop URL và iCal export tương thích chuẩn RFC 5545 (§5.2).
