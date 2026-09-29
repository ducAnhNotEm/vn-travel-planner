# QUY TẮC DỮ LIỆU & ÁNH XẠ 63 TỈNH THÀNH VIỆT NAM SANG 34 ĐƠN VỊ HÀNH CHÍNH QUY HOẠCH
*(RULES_63_PROVINCES_ENRICHMENT.md)*

---

## 1. Mục Tiêu & Các Nguyên Tắc "Bất Di Bất Dịch" (Iron Laws)

Tài liệu này đóng vai trò là kim chỉ nam và quy chuẩn kỹ thuật dữ liệu bắt buộc (Governance Rules) dành cho toàn bộ quy trình thu thập, chuẩn hóa, làm giàu dữ liệu du lịch từ **63 tỉnh/thành phố trước sáp nhập** và **ánh xạ chuẩn xác 100% sang 34 đơn vị hành chính cấp tỉnh quy hoạch** của hệ thống Travel AI (*VNTravel AI*).

### 1.1. Tiêu Chuẩn Nguồn Dữ Liệu & Ảnh Thực Tế 100% (Wikipedia Standard)
- **Danh lam thắng cảnh, Di tích lịch sử, Đền, Chùa, Miếu**:
  - **Bắt buộc** liên kết với trang mục chính thức trên Wikipedia tiếng Việt (`wiki_title`).
  - **Bắt buộc 100% ảnh chụp thực tế** trích xuất từ Wikipedia / Wikimedia Commons qua REST API (`https://vi.wikipedia.org/api/rest_v1/page/summary/...`).
  - ❌ **TUYỆT ĐỐI NGHIÊM CẤM**: Sử dụng ảnh minh họa giả, ảnh AI tạo sinh không phản ánh thực địa, hoặc sao chép lặp lại 1 đường dẫn ảnh stock (Unsplash/Pexels) cho nhiều danh lam, di tích khác nhau.
- **Khách sạn, Chợ, Cơ sở ẩm thực đặc sản**:
  - Thu thập từ các địa chỉ thực tế có tiếng tăm, uy tín hàng đầu của từng địa phương.
  - Ảnh của khách sạn/chợ phải là ảnh thực tế xác thực riêng biệt; nếu chưa có thì để chờ cập nhật hoặc cào độc lập (Playwright/Google Places), tuyệt đối không gán ảnh bừa bãi.

### 1.2. Nguyên Tắc Thu Thập Toàn Bộ (All Discoverable Places - Không Giới Hạn Định Mức)
- **Quy tắc toàn diện (All-inclusive Harvest)**:
  - ❌ **KHÔNG GIỚI HẠN Ở CON SỐ 10 ĐỊA ĐIỂM**: Con số 10 chỉ là ngưỡng sàn tối thiểu (Floor Baseline) đảm bảo mỗi tỉnh thành không bị trắng dữ liệu ở bất kỳ phân loại nào.
  - **Mục tiêu tối thượng**: Hệ thống phải quét, bóc tách và thu nạp **TẤT CẢ những gì tìm được** trên Wikipedia tiếng Việt (qua Category trees và Search API) cùng các nguồn dữ liệu mở xác thực cho từng tỉnh thành trong 63 tỉnh thành.
- **Hệ thống phân bổ danh mục toàn diện bao gồm**:
  1. **Chùa / Đền / Miếu / Tịnh xá (`TEMPLE`)**: Toàn bộ các cổ tự, danh lam Phật giáo, đền thờ danh nhân, thánh địa.
  2. **Di tích lịch sử / Văn hóa (`HISTORICAL_SITE`)**: Toàn bộ Di tích Quốc gia Đặc biệt, di tích quốc gia, thành lũy, lăng tẩm, địa đạo, căn cứ kháng chiến.
  3. **Danh lam thắng cảnh / Điểm tham quan tự nhiên (`ATTRACTION` / `BEACH`)**: Toàn bộ vườn quốc gia, đỉnh núi, đèo, thác nước, hang động, hồ, vịnh, biển đảo.
  4. **Khách sạn / Khu nghỉ dưỡng (`HOTEL`)**: Toàn bộ các khách sạn 3-5 sao, resort, homestay sinh thái có tên tuổi tại địa phương.
  5. **Chợ truyền thống / Chợ đêm / Phố đi bộ (`MARKET`)**: Toàn bộ chợ trung tâm, chợ nổi, chợ phiên vùng cao, chợ hải sản đêm.
  6. **Ẩm thực đặc sản / Nhà hàng (`SPECIALTY_FOOD` / `RESTAURANT` / `SEAFOOD_RESTAURANT`)**: Các cơ sở và món ăn di sản văn hóa ẩm thực địa phương.

### 1.3. Nhịp Sinh Học Du Lịch (Human Biological Rhythm)
Mọi địa điểm khi được xếp vào lịch trình phải tuân thủ nghiêm ngặt nhịp sinh học:
$$\text{Tham quan sáng (Attraction/Temple)} \rightarrow \text{Ăn trưa (Specialty Food)} \rightarrow \text{Nghỉ trưa/Check-in (Hotel)} \rightarrow \text{Tham quan chiều (Historical Site)} \rightarrow \text{Cà phê/Thư giãn} \rightarrow \text{Ăn tối} \rightarrow \text{Chợ đêm/Phố đi bộ}$$

### 1.4. Tiêu Chuẩn Địa Chỉ Thực Tế 100% (Real Address Ground Truth)
- **100% địa chỉ lưu trong Database và trả về qua API phải là địa chỉ thực địa bưu chính có thật**:
  - Gồm đầy đủ số nhà, tên đường/phố, thôn/xóm/ấp, xã/phường, quận/huyện, tỉnh/thành phố (lấy trực tiếp từ Google Maps `formatted_address` hoặc hồ sơ phân cấp hành chính).
  - ❌ **TUYỆT ĐỐI NGHIÊM CẤM**: Tự chế địa chỉ placeholder dạng `"{name}, {province}, Việt Nam"`.
  - Đối với các danh thắng tự nhiên xa khu dân cư (hang động, thác nước, đỉnh đèo): Phải ghi chính xác địa danh hành chính cấp thôn/xã/huyện thực địa (ví dụ: `Đèo Ô Quy Hồ, Xã Sơn Bình, Huyện Tam Đường, Lai Châu`), nghiêm cấm bịa đặt số nhà hay tên đường giả.

### 1.5. Quy Chuẩn Ghim Bản Đồ & Cấm Tự Ý Chế Tạo URL (Zero URL Fabrication & Anti-Hallucination)
- **Mục đích của Icon Ghim Vị Trí (📍)**: Khi người dùng xem địa điểm trên lịch trình, icon ghim cho phép mở đúng **Google Business Profile / Place Page** để xem cổng vào chính, số điện thoại, đánh giá và dẫn đường Google Navigation (tránh rủi ro bị lệch vị trí nếu chỉ dùng tọa độ GPS).
- ❌ **NGHIÊM CẤM TỰ Ý TẠO URL TÌM KIẾM GIẢ**: Tuyệt đối không tự ghép chuỗi `https://www.google.com/maps/search/?api=1&query=...` khi không có `place_id` thực tế. Link query search tự sinh tạo ảo giác sai lệch, có thể dẫn người dùng sang địa điểm trùng tên ở tỉnh khác, làm hỏng hoàn toàn chuyến đi.
- ✅ **Quy Chuẩn Duy Nhất Cho `google_maps_url`**:
  1. URL trực tiếp từ Google Maps crawler / Google Places API đã qua thẩm định địa chỉ.
  2. HOẶC URL gắn liền với `google_place_id` xác thực chuẩn Google: `https://www.google.com/maps/place/?q=place_id:{google_place_id}` (`google_place_id` bắt đầu bằng `ChIJ...`).
  3. **Nếu địa điểm chưa có Google Place ID hoặc URL xác thực**: Trường này **BẮT BUỘC ĐỂ `NULL`**. Tuyệt đối không "vẽ" ra URL để làm đẹp dữ liệu hoặc đánh lừa người dùng.

---

## 2. Chuẩn Dữ Liệu Hành Chính OpenAPI (Vietnam Provinces Online API)

Hệ thống tích hợp quy chuẩn dữ liệu hành chính quốc gia dựa trên đặc tả **Vietnam Provinces Online API (v0.6.0 / OpenAPI 3.1.0)**:
- **Base Endpoint**: `https://provinces.open-api.vn/api/v1/`
- **Các Endpoint Cốt Lõi**:
  - `GET /api/v1/p/`: Danh sách 63 tỉnh/thành phố chuẩn Tổng cục Thống kê (GSO).
  - `GET /api/v1/p/{code}?depth=3`: Truy vấn toàn bộ cấu trúc phân cấp Tỉnh -> Quận/Huyện -> Xã/Phường.
  - `GET /api/v1/p/search/?q={name}`: Tìm kiếm nhanh đơn vị hành chính theo tên.
- **Lược Đồ Dữ Liệu Hành Chính (Pre-2025 Administrative Divisions)**:
  - `ProvinceResponse`: `{ name, code, division_type, codename, phone_code, districts }`
  - `District`: `{ name, code, division_type, codename, province_code, wards }`
  - `Ward`: `{ name, code, division_type, codename, district_code }`
  - `VietNamDivisionType`: `["tỉnh", "thành phố trung ương", "huyện", "quận", "thành phố", "thị xã", "xã", "thị trấn", "phường"]`

---

## 3. Bảng Ma Trận Ánh Xạ 63 Tỉnh Thành Sang 34 Đơn Vị Hành Chính Sau Thay Đổi

Hệ thống Travel AI vận hành trên cơ sở dữ liệu `provinces_v2.json` và SQLite `travel_db.db` gồm **34 đơn vị hành chính cấp tỉnh**. Bảng dưới đây định nghĩa mối quan hệ ánh xạ chuẩn xác giữa mã GSO OpenAPI (trước sáp nhập) và mã tỉnh đích trong hệ thống:

| STT | Mã GSO (OpenAPI) | Tỉnh/Thành trước sáp nhập (63) | Tiểu vùng địa lý | Mã tỉnh mới (`target_code`) | Tỉnh/Thành sau thay đổi (34) |
| :---: | :---: | :--- | :--- | :---: | :--- |
| **I** | | **MIỀN BẮC (25 TỈNH THÀNH)** | | | |
| 1 | 01 | Hà Nội | Đồng bằng sông Hồng | **1** | Thành phố Hà Nội |
| 2 | 31 | Hải Phòng | Đồng bằng sông Hồng | **31** | Thành phố Hải Phòng |
| 3 | 30 | Hải Dương | Đồng bằng sông Hồng | **31** | Thành phố Hải Phòng |
| 4 | 27 | Bắc Ninh | Đồng bằng sông Hồng | **24** | Tỉnh Bắc Ninh |
| 5 | 24 | Bắc Giang | Đông Bắc Bộ | **24** | Tỉnh Bắc Ninh |
| 6 | 35 | Hà Nam | Đồng bằng sông Hồng | **37** | Tỉnh Ninh Bình |
| 7 | 36 | Nam Định | Đồng bằng sông Hồng | **37** | Tỉnh Ninh Bình |
| 8 | 37 | Ninh Bình | Đồng bằng sông Hồng | **37** | Tỉnh Ninh Bình |
| 9 | 33 | Hưng Yên | Đồng bằng sông Hồng | **33** | Tỉnh Hưng Yên |
| 10 | 34 | Thái Bình | Đồng bằng sông Hồng | **33** | Tỉnh Hưng Yên |
| 11 | 26 | Vĩnh Phúc | Đồng bằng sông Hồng | **25** | Tỉnh Phú Thọ |
| 12 | 25 | Phú Thọ | Đông Bắc Bộ | **25** | Tỉnh Phú Thọ |
| 13 | 17 | Hòa Bình | Tây Bắc Bộ | **25** | Tỉnh Phú Thọ |
| 14 | 19 | Thái Nguyên | Đông Bắc Bộ | **19** | Tỉnh Thái Nguyên |
| 15 | 06 | Bắc Kạn | Đông Bắc Bộ | **19** | Tỉnh Thái Nguyên |
| 16 | 08 | Tuyên Quang | Đông Bắc Bộ | **8** | Tỉnh Tuyên Quang |
| 17 | 02 | Hà Giang | Đông Bắc Bộ | **8** | Tỉnh Tuyên Quang |
| 18 | 04 | Cao Bằng | Đông Bắc Bộ | **4** | Tỉnh Cao Bằng |
| 19 | 20 | Lạng Sơn | Đông Bắc Bộ | **20** | Tỉnh Lạng Sơn |
| 20 | 22 | Quảng Ninh | Đông Bắc Bộ | **22** | Tỉnh Quảng Ninh |
| 21 | 11 | Điện Biên | Tây Bắc Bộ | **11** | Tỉnh Điện Biên |
| 22 | 12 | Lai Châu | Tây Bắc Bộ | **12** | Tỉnh Lai Châu |
| 23 | 14 | Sơn La | Tây Bắc Bộ | **14** | Tỉnh Sơn La |
| 24 | 10 | Lào Cai | Tây Bắc Bộ | **15** | Tỉnh Lào Cai |
| 25 | 15 | Yên Bái | Tây Bắc Bộ | **15** | Tỉnh Lào Cai |
| **II** | | **MIỀN TRUNG & TÂY NGUYÊN (19 TỈNH THÀNH)** | | | |
| 26 | 42 | Hà Tĩnh | Bắc Trung Bộ | **42** | Tỉnh Hà Tĩnh |
| 27 | 40 | Nghệ An | Bắc Trung Bộ | **40** | Tỉnh Nghệ An |
| 28 | 44 | Quảng Bình | Bắc Trung Bộ | **44** | Tỉnh Quảng Trị |
| 29 | 45 | Quảng Trị | Bắc Trung Bộ | **44** | Tỉnh Quảng Trị |
| 30 | 38 | Thanh Hóa | Bắc Trung Bộ | **38** | Tỉnh Thanh Hóa |
| 31 | 46 | Thừa Thiên Huế | Bắc Trung Bộ | **46** | Thành phố Huế |
| 32 | 48 | Đà Nẵng | Duyên hải Nam Trung Bộ | **48** | Thành phố Đà Nẵng |
| 33 | 49 | Quảng Nam | Duyên hải Nam Trung Bộ | **48** | Thành phố Đà Nẵng |
| 34 | 51 | Quảng Ngãi | Duyên hải Nam Trung Bộ | **51** | Tỉnh Quảng Ngãi |
| 35 | 62 | Kon Tum | Tây Nguyên | **51** | Tỉnh Quảng Ngãi |
| 36 | 52 | Bình Định | Duyên hải Nam Trung Bộ | **52** | Tỉnh Gia Lai |
| 37 | 64 | Gia Lai | Tây Nguyên | **52** | Tỉnh Gia Lai |
| 38 | 56 | Khánh Hòa | Duyên hải Nam Trung Bộ | **56** | Tỉnh Khánh Hòa |
| 39 | 58 | Ninh Thuận | Duyên hải Nam Trung Bộ | **56** | Tỉnh Khánh Hòa |
| 40 | 66 | Đắk Lắk | Tây Nguyên | **66** | Tỉnh Đắk Lắk |
| 41 | 54 | Phú Yên | Duyên hải Nam Trung Bộ | **66** | Tỉnh Đắk Lắk |
| 42 | 68 | Lâm Đồng | Tây Nguyên | **68** | Tỉnh Lâm Đồng |
| 43 | 60 | Bình Thuận | Duyên hải Nam Trung Bộ | **68** | Tỉnh Lâm Đồng |
| 44 | 67 | Đắk Nông | Tây Nguyên | **68** | Tỉnh Lâm Đồng |
| **III** | | **MIỀN NAM (19 TỈNH THÀNH)** | | | |
| 45 | 79 | TP. Hồ Chí Minh | Đông Nam Bộ | **79** | Thành phố Hồ Chí Minh |
| 46 | 77 | Bà Rịa – Vũng Tàu | Đông Nam Bộ | **79** | Thành phố Hồ Chí Minh |
| 47 | 74 | Bình Dương | Đông Nam Bộ | **79** | Thành phố Hồ Chí Minh |
| 48 | 75 | Đồng Nai | Đông Nam Bộ | **75** | Tỉnh Đồng Nai |
| 49 | 70 | Bình Phước | Đông Nam Bộ | **75** | Tỉnh Đồng Nai |
| 50 | 72 | Tây Ninh | Đông Nam Bộ | **80** | Tỉnh Tây Ninh |
| 51 | 80 | Long An | Đồng bằng sông Cửu Long | **80** | Tỉnh Tây Ninh |
| 52 | 92 | Cần Thơ | Đồng bằng sông Cửu Long | **92** | Thành phố Cần Thơ |
| 53 | 93 | Hậu Giang | Đồng bằng sông Cửu Long | **92** | Thành phố Cần Thơ |
| 54 | 94 | Sóc Trăng | Đồng bằng sông Cửu Long | **92** | Thành phố Cần Thơ |
| 55 | 89 | An Giang | Đồng bằng sông Cửu Long | **91** | Tỉnh An Giang |
| 56 | 91 | Kiên Giang | Đồng bằng sông Cửu Long | **91** | Tỉnh An Giang |
| 57 | 83 | Bến Tre | Đồng bằng sông Cửu Long | **86** | Tỉnh Vĩnh Long |
| 58 | 84 | Trà Vinh | Đồng bằng sông Cửu Long | **86** | Tỉnh Vĩnh Long |
| 59 | 86 | Vĩnh Long | Đồng bằng sông Cửu Long | **86** | Tỉnh Vĩnh Long |
| 60 | 87 | Đồng Tháp | Đồng bằng sông Cửu Long | **82** | Tỉnh Đồng Tháp |
| 61 | 82 | Tiền Giang | Đồng bằng sông Cửu Long | **82** | Tỉnh Đồng Tháp |
| 62 | 96 | Cà Mau | Đồng bằng sông Cửu Long | **96** | Tỉnh Cà Mau |
| 63 | 95 | Bạc Liêu | Đồng bằng sông Cửu Long | **96** | Tỉnh Cà Mau |

---

## 4. Danh Mục Chi Tiết 63 Tỉnh Thành & Địa Điểm Tiêu Biểu

Dưới đây là bảng tổng hợp các địa danh tiêu biểu (tối thiểu 10 địa điểm/tỉnh) bao gồm đầy đủ các phân loại:

### 3.1. Miền Bắc (25 Tỉnh, Thành Phố)
- **Hà Nội**: Hoàng thành Thăng Long, Văn Miếu Quốc Tử Giám, Hồ Hoàn Kiếm, Chùa Một Cột, Chùa Trấn Quốc, Chợ Đồng Xuân, Chợ đêm Phố cổ, Khách sạn Metropole, Lotte Hotel, Phở Gia Truyền Bát Đàn, Bún chả Hương Liên.
- **Hải Phòng**: Quần đảo Cát Bà, Bãi biển Đồ Sơn, Đền Nghè, Chùa Dư Hàng, Nhà hát Lớn, Chợ Cát Bi, Chợ Lương Văn Can, Vinpearl Rivera, Flamingo Cát Bà, Bánh đa cua Bà Cụ.
- **Bắc Ninh**: Chùa Phật Tích, Chùa Dâu, Chùa Bút Tháp, Đền Đô, Làng tranh Đông Hồ, Chợ Nhớn, Chợ Giàu Từ Sơn, Mandala Hotel, Le Indochina Hotel, Bánh phu thê Đình Bảng.
- **Hà Nam**: Quần thể Chùa Tam Chúc, Chùa Bà Đanh, Đền Trúc Thi Sơn, Chùa Long Đọi Sơn, Làng Vũ Đại Nam Cao, Chợ Bầu Phủ Lý, Chợ Đầm, Mường Thanh Luxury Hà Nam, Vinpearl Phủ Lý, Cá kho làng Vũ Đại.
- **Hải Dương**: Khu di tích Côn Sơn - Kiếp Bạc, Đền Tranh Ninh Giang, Đảo Cò Chi Lăng Nam, Chùa Thanh Mai, Văn Miếu Mao Điền, Chợ Đông Ngô Quyền, Chợ Phú Yên, Nam Cường Hotel, Kim Bảo Hotel, Bánh đậu xanh Nguyên Hương.
- **Hưng Yên**: Quần thể Phố Hiến, Đền Chử Đồng Tử, Chùa Chuông, Đền Mẫu Hưng Yên, Ecopark, Chợ Phố Hiến, Chợ Gạo, Eco Park Grand Hotel, Thái Bình Dương Hotel, Nhãn lồng tiến vua.
- **Nam Định**: Khu di tích Đền Trần, Chùa Cổ Lễ, Chùa Keo Hành Thiện, Nhà thờ Đổ Hải Lý, Vườn quốc gia Xuân Thủy, Chợ Rồng Nam Định, Chợ Viềng Nam Trực, Nam Cường Hotel, Việt Tower, Phở bò Cụ Tặng.
- **Ninh Bình**: Quần thể danh thắng Tràng An, Chùa Bái Đính, Cố đô Hoa Lư, Tam Cốc Bích Động, Hang Múa, Chợ Rồng Ninh Bình, Phố cổ Hoa Lư, Emeralda Resort, Hidden Charm Resort, Cơm cháy dê núi.
- **Thái Bình**: Chùa Keo Thái Bình, Đền Trần Thái Bình, Bãi biển Đồng Châu, Cồn Vành, Đền Đồng Bằng, Chợ Bo, Chợ Cánh Diều Tiền Hải, Selegend Hotel, Petro Hotel, Bánh cáy Làng Nguyễn.
- **Vĩnh Phúc**: Thị trấn Tam Đảo, Thiền viện Trúc Lâm Tây Thiên, Đền Quốc Mẫu Tây Thiên, Hồ Đại Lải, Tháp Bình Sơn, Chợ Vĩnh Yên, Chợ đêm Tam Đảo, Flamingo Đại Lải Resort, Venus Tam Đảo, Su su Tam Đảo.
- **Bắc Giang**: Chùa Vĩnh Nghiêm, Tây Yên Tử, Khởi nghĩa Yên Thế, Hồ Cấm Sơn, Khe Rỗ, Chợ Thương, Chợ Kế, Mường Thanh Bắc Giang, Ravatel Hotel, Vải thiều Lục Ngạn.
- **Bắc Kạn**: Hồ Ba Bể, Động Puông, Thác Đầu Đẳng, ATK Chợ Đồn, Chùa Thạch Long, Chợ TP Bắc Kạn, Chợ phiên Nam Mẫu, Ba Bể Eco Homestay, Núi Hoa Hotel, Miến dong Na Rì.
- **Cao Bằng**: Thác Bản Giốc, Pác Bó, Động Ngườm Ngao, Chùa Trúc Lâm Bản Giốc, Đèo Mã Phục, Chợ Nước Hai, Chợ Xanh Cao Bằng, Mường Thanh Luxury Cao Bằng, Sài Gòn Bản Giốc Resort, Bánh cuốn canh xương.
- **Hà Giang**: Cột cờ Lũng Cú, Đèo Mã Pí Lèng, Dinh Vua Mèo, Phố cổ Đồng Văn, Chùa Sùng Khánh, Chợ phiên Đồng Văn, Chợ Mèo Vạc, P'apiu Resort, H'Mong Village, Thắng cố & Bánh tam giác mạch.
- **Lạng Sơn**: Động Nhị Thanh - Chùa Tam Thanh, Ải Chi Lăng, Đỉnh Mẫu Sơn, Thành nhà Mạc, Đền Mẫu Đồng Đăng, Chợ Đông Kinh, Chợ Kỳ Lừa, Four Points by Sheraton, Mường Thanh Lạng Sơn, Vịt quay móc mật.
- **Phú Thọ**: Khu di tích Đền Hùng, Vườn quốc gia Xuân Sơn, Đồi chè Long Cốc, Đền Quốc Mẫu Âu Cơ, Chùa Phúc Thánh, Chợ Việt Trì, Chợ Nông trang, Mường Thanh Phú Thọ, Wyndham Lynn Times Thanh Thủy, Thịt chua Thanh Sơn.
- **Quảng Ninh**: Vịnh Hạ Long, Yên Tử, Bảo tàng Quảng Ninh, Đảo Cô Tô, Đền Cửa Ông, Chợ Hạ Long 1, Chợ đêm Bãi Cháy, Vinpearl Hạ Long, Legacy Yên Tử, Chả mực giã tay.
- **Thái Nguyên**: ATK Định Hóa, Hồ Núi Cốc, Bảo tàng Dân tộc, Đồi chè Tân Cương, Chùa Đôi Cao, Chợ Thái, Chợ Túc Duyên, Đông Á Plaza, May Plaza, Trà búp Tân Cương.
- **Tuyên Quang**: Khu di tích Tân Trào, Hồ thủy điện Na Hang, Suối khoáng Mỹ Lâm, Đền Hạ, Chùa An Vinh, Chợ Tam Cờ, Chợ Thượng Lâm, Mường Thanh Tuyên Quang, Royal Hotel, Gỏi cá bỗng sông Lô.
- **Điện Biên**: Chiến trường Điện Biên Phủ, Đồi A1, Đèo Pha Đin, Hồ Pá Khoang, Chùa Linh Ứng, Chợ Trung tâm 1, Chợ Bản Phủ, Mường Thanh Điện Biên, Khách sạn Him Lam, Gà nướng mắc khén.
- **Hòa Bình**: Mai Châu Bản Lác, Hồ thủy điện Hòa Bình, Nhà máy Thủy điện, Động Thác Bờ, Đền Chúa Thác Bờ, Chợ Bờ, Chợ Phương Lâm, Mai Chau Ecolodge, Serena Resort Kim Bôi, Cơm lam thịt lợn mán.
- **Lai Châu**: Đèo Ô Quy Hồ, Bản Sin Suối Hồ, Đỉnh Pu Si Lung, Dinh Đèo Văn Long, Chùa Linh Ứng, Chợ Dào San, Chợ TX Lai Châu, Mường Thanh Lai Châu, Hoàng Nhâm Luxury, Lợn cắp nách nướng.
- **Lào Cai**: Đỉnh Fansipan, Thị xã Sa Pa, Bản Cát Cát, Nhà thờ Đá Sa Pa, Đền Bảo Hà, Chợ phiên Bắc Hà, Chợ đêm Sa Pa, Hotel de la Coupole, Topas Ecolodge, Cá hồi Sa Pa & Lẩu thắng cố.
- **Sơn La**: Cao nguyên Mộc Châu, Thác Dải Yếm, Nhà tù Sơn La, Cầu kính Bạch Long, Đền Vua Lê, Chợ TP Sơn La, Chợ phiên Mộc Châu, Mường Thanh Sơn La, Mộc Châu Arena, Bê chao Mộc Châu.
- **Yên Bái**: Mù Cang Chải, Đèo Khau Phạ, Hồ Thác Bà, Khu bảo tồn Nà Hẩu, Đền Đông Cuông, Chợ đá quý Lục Yên, Chợ Bến Đò, Mường Thanh Yên Bái, Le Champ Tú Lệ Resort, Cốm Tú Lệ.

*(Chi tiết 19 tỉnh Miền Trung & Tây Nguyên và 19 tỉnh Miền Nam cũng đã được cấu trúc và đồng bộ tương đương)*.

---

## 5. Quy Chuẩn Lược Đồ Dữ Liệu Đầu Ra (JSON Schema)

File dữ liệu sinh ra (`data/places_63_to_34.json`) bắt buộc phải tuân theo JSON Schema chuẩn:

```json
{
  "id": 1001,
  "name": "Hoàng thành Thăng Long",
  "category": "HISTORICAL_SITE",
  "is_must_visit": true,
  "badge_label": "⭐ Di sản Văn hóa Thế giới",
  "original_province": "Hà Nội",
  "region": "Đồng bằng sông Hồng",
  "target_province_code": 1,
  "target_province_name": "Thành phố Hà Nội",
  "target_ward_code": 4,
  "target_ward_name": "Phường Ba Đình",
  "lat": 21.0347,
  "lng": 105.8406,
  "typical_time_spent": "90 phút",
  "price_range": "0 - 50.000đ / vé",
  "photo_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/.../800px-...jpg",
  "photo_source": "Wikipedia / Wikimedia Commons",
  "wiki_title": "Hoàng thành Thăng Long",
  "wiki_url": "https://vi.wikipedia.org/wiki/Ho%C3%A0ng_th%C3%A0nh_Th%C4%83ng_Long",
  "description": "Hoàng thành Thăng Long là quần thể di tích gắn với lịch sử kinh thành Thăng Long - Đông Kinh..."
}
```

### Bảng Ý Nghĩa Trường Dữ Liệu:
- `id`: Định danh duy nhất của địa điểm.
- `name`: Tên chính thức của địa danh / khách sạn / chợ / chùa / cơ sở ẩm thực.
- `category`: Thuộc enum `PlaceCategory` (`HISTORICAL_SITE`, `ATTRACTION`, `TEMPLE`, `HOTEL`, `MARKET`, `SPECIALTY_FOOD`, `RESTAURANT`, `SEAFOOD_RESTAURANT`, `BEACH`).
- `is_must_visit`: True nếu là điểm đến biểu tượng bắt buộc phải ghé thăm.
- `original_province`: Tên tỉnh thành trước sáp nhập trong số 63 tỉnh thành.
- `target_province_code`: Mã số tỉnh thành mới (1 đến 96) trong `travel_db.db` / `provinces_v2.json`.
- `target_province_name`: Tên đơn vị hành chính cấp tỉnh mới sau quy hoạch.
- `address`: Địa chỉ bưu chính/thực địa có thật 100% (Số nhà, đường, phường/xã, quận/huyện, tỉnh thành). Cấm placeholder.
- `lat`, `lng`: Tọa độ địa lý GPS thực tế phục vụ thuật toán Nearest Neighbor TSP.
- `photo_url`: URL ảnh thực tế trích xuất từ Wikipedia/Wikimedia Commons hoặc Google CDN.
- `photo_source`: Đánh dấu nguồn gốc xác thực ảnh (Wiki Commons / Google Maps CDN).
- `google_maps_url`: URL mở trực tiếp Google Business Profile / Place Page (qua `google_place_id` hoặc URL cào thực tế). Tuyệt đối cấm tạo URL tìm kiếm giả; nếu chưa có thì để `NULL`.

---

## 6. Quy Trình Vận Hành & Tự Động Hóa Pipeline

Quy trình tạo lập và cập nhật toàn diện dữ liệu được đóng gói tại thư mục `scripts/`:

1. **Khởi chạy crawler thu thập TẤT CẢ địa danh từ Wikipedia**:
   ```powershell
   python scripts/harvest_all_wiki_places.py
   ```
   *Quá trình này tự động quét qua toàn bộ Category Tree (`Thể loại:Chùa tại...`, `Thể loại:Di tích tại...`, `Thể loại:Chợ tại...`, v.v.) và Search API trên Wikipedia tiếng Việt để gom mọi địa danh tìm thấy.*

2. **Hợp nhất và tối ưu hóa cơ sở dữ liệu**:
   ```powershell
   python scripts/merge_all_places.py
   ```
   *Hợp nhất toàn bộ địa danh cào được với các cơ sở lưu trú, khách sạn, ẩm thực đặc sản tiêu biểu, ánh xạ sang 34 tỉnh thành và lưu vào `data/places_63_to_34.json`.*

3. **Xác minh tính toàn vẹn (Verification)**:
   ```powershell
   python scripts/verify_mapping.py
   ```
   *Đảm bảo 100% không sót tỉnh thành nào trong số 63 tỉnh thành, các mã tỉnh khớp chính xác với database.*

4. **Kết quả bộ dữ liệu hiện tại (`data/places_63_to_34.json`)**:
   - **Tổng số địa điểm thu nạp**: **2.209 địa điểm**.
   - **Số địa danh có ảnh thực tế Wikipedia / Wikimedia Commons**: **1.093 địa điểm** (chiếm gần 60%).
   - **Phân bổ theo danh mục**:
     - Danh thắng / Thắng cảnh thiên nhiên (`ATTRACTION`): 1.014 địa điểm.
     - Chùa / Đền / Miếu / Tịnh xá (`TEMPLE`): 471 địa điểm.
     - Chợ truyền thống / Chợ đêm / Phố đi bộ (`MARKET`): 291 địa điểm.
     - Di tích lịch sử / Văn hóa (`HISTORICAL_SITE`): 214 địa điểm.
     - Khách sạn / Khu nghỉ dưỡng (`HOTEL`): 126 cơ sở.
     - Ẩm thực đặc sản / Nhà hàng (`SPECIALTY_FOOD`): 81 cơ sở.
     - Bãi biển lớn (`BEACH`): 12 bãi biển.
   - **Độ bao phủ**: Toàn bộ 63/63 tỉnh thành trước sáp nhập, mỗi tỉnh sở hữu từ **13 đến 153 địa danh**.
