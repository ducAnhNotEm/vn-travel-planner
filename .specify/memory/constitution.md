# PROJECT CONSTITUTION — VIETNAM TRAVEL PLANNER
<!-- Spec Kit Governance & Architectural Invariants -->

## 0. Triết lý Phát triển — Lazy Senior Dev (Ponytail)
> **"The best code is the code never written."**
Mọi tính năng và dòng code mới phải leo qua thang kiểm tra tối giản:
1. Có thực sự cần tồn tại không? (YAGNI)
2. Đã có trong codebase chưa? (Tái sử dụng `app/services/`, `travel_db.db`)
3. Thư viện chuẩn Python hoặc dependency sẵn có làm được không?
4. Viết tối thiểu dòng code đạt hiệu quả cao nhất.

---

## 1. Các Luật Sắt Bất Biến (Iron Laws)

### 🔒 Luật 1: Ground Truth 100% từ Database (`travel_db.db`)
- ❌ **CẤM BỊA ĐẶT ĐỊA DANH / ĐỊA CHỈ**: 100% địa điểm trong lịch trình phải tồn tại trong `travel_db.db` với tọa độ thực tế và địa chỉ bưu chính xác thực. Tuyệt đối không sinh địa chỉ placeholder kiểu `"{name}, {province}, Việt Nam"`.
- ❌ **CẤM TỰ Ý TẠO URL GOOGLE MAPS GIẢ**: Chỉ sử dụng `google_maps_url` từ scraper kiểm định hoặc Google Place ID chuẩn (`ChIJ...`). Nếu chưa có, để `NULL`.

### 🔒 Luật 2: Kiến trúc AI Sandwich & Tính toán Xác định (Deterministic Math)
- ❌ **CẤM ĐỂ AI TÍNH NHẨM**: AI/LLM chỉ đóng vai trò phân tích ý đồ người dùng (NLU) và viết lời thuyết minh (NLG).
- ✅ Toàn bộ việc tính toán khoảng cách (Haversine), gom cụm địa lý, tính toán đường đi, số phòng khách sạn và phân bổ chi phí **BẮT BUỘC PHẢI DO PYTHON CORE ENGINE XỬ LÝ 100%**.

### 🔒 Luật 3: Bảo mật API Key Goong Map & Google Maps
- ❌ **TUYỆT ĐỐI KHÔNG ĐƯA API KEY LÊN FRONTEND**: Tất cả API Key trả phí (Goong, Google) phải được lưu trữ trong `.env` và chỉ backend được phép truy cập.
- ✅ Mọi yêu cầu vẽ bản đồ tĩnh hoặc tìm đường phải đi qua **Backend Proxy** (`/api/map/...`) kèm cơ chế bộ nhớ đệm (Caching) để bảo vệ quota.

### 🔒 Luật 4: Phân bổ Chi phí & Phòng Khách sạn Minh Bạch
- **Phòng nghỉ**: $\text{Số phòng} = \lceil \text{Số người} / 2 \rceil$.
- **Phương tiện chia sẻ**: Chi phí xăng dầu, cầu đường, thuê xe là chi phí dùng chung cho cả đoàn, sau đó chia đều theo đầu người (`cost_per_person`).
- **Sức chứa xe máy**: Tối đa 2 người/xe $\rightarrow \text{Số xe máy} = \lceil \text{Số người} / 2 \rceil$.

---

## 2. Nhịp sinh học du lịch Việt Nam (Human Biological Rhythm)
Mọi lịch trình đa ngày bắt buộc phải phân loại và tuân theo chính xác 1 trong 3 nhịp sống thực tế:

### 🌊 A. Nhịp Sinh Học Du Lịch Biển (Coastal / Beach Rhythm)
- 🌅 **05:30 - 07:00**: Đón bình minh bãi biển & Tắm biển sớm.
- 🍜 **07:30 - 08:30**: Ăn sáng đặc sản địa phương (bún cá, bánh canh...).
- 🚶 **09:00 - 11:30**: Đi dạo / Tham quan danh thắng / Check-in mát mẻ.
- 🍲 **11:45 - 13:00**: Ăn trưa hải sản / nhà hàng đặc sản.
- 🏨 **13:00 - 15:30**: **BẮT BUỘC NGHỈ TRƯA TRÁNH NẮNG GẮT TẠI KHÁCH SẠN** (Tuyệt đối không xếp hoạt động ngoài trời lúc nắng đỉnh điểm).
- 🌇 **16:00 - 18:00**: Ngắm hoàng hôn trên biển / Bãi tắm chiều & Thể thao biển.
- 🚿 **18:00 - 18:45**: Về phòng tắm tráng nước ngọt & Lên đồ đi chơi tối.
- 🦀 **19:00 - 20:30**: Ăn tối tiệc hải sản tươi sống.
- 🌊 **20:45 - 22:30**: Đi dạo biển đêm tiếp / Chợ đêm ven biển / Cafe nghe sóng.

### 🏛️ B. Nhịp Sinh Học Di Tích, Văn Hóa & Đồng Bằng / Đô Thị (Heritage & Urban Rhythm)
- 🍜 **07:30 - 08:30**: Ăn sáng đặc sản (phở, bún bò, bánh cuốn...).
- 🏛️ **08:30 - 11:30**: Tham quan danh thắng chính / Di tích lịch sử / Đền chùa (Tranh thủ lúc trời mát).
- 🍲 **11:45 - 13:00**: Ăn trưa đặc sản vùng miền.
- 🏨 **13:00 - 14:30**: Nghỉ trưa tránh nắng (Khách sạn hoặc quán cafe điều hòa yên tĩnh).
- 🛶 **14:45 - 17:00**: Trải nghiệm Làng nghề truyền thống / Đi thuyền sinh thái mát mẻ (Tràng An, Tam Cốc...).
- ☕ **17:15 - 18:30**: Cafe view ngắm hoàng hôn / Dạo bờ hồ (Hồ Gươm, Hồ Tây, Sông Hương...).
- 🍲 **19:00 - 20:30**: Ăn tối nhà hàng đặc sản.
- 🏮 **20:45 - 22:30**: Phố đi bộ, Chợ đêm, xem biểu diễn nghệ thuật truyền thống.
- ❌ **Cấm kỵ**: Tuyệt đối không xếp 3 - 4 di tích/chùa liên tiếp; cấm xếp leo núi/bậc thang ngoài trời nắng từ 12:30 - 14:30.

### 🌲 C. Nhịp Sinh Học Đồi Núi & Cao Nguyên (Mountain / Highland Rhythm)
- ☁️ **06:00 - 07:30**: Săn mây / Đón bình minh thung lũng trong không khí se lạnh.
- ☕ **07:45 - 08:45**: Ăn sáng nóng hổi + Nhâm nhi cafe ngắm núi rừng.
- 🚶 **09:00 - 11:30**: Check-in thác nước / Bản làng văn hóa / Trekking nhẹ.
- 🍲 **11:45 - 13:15**: Ăn trưa cơm lam gà đồi, lợn bản nướng, rau rừng.
- 🏨 **13:30 - 15:00**: Nghỉ ngơi tại homestay / resort.
- 🌸 **15:00 - 17:30**: Dạo đồi thông, đồi chè, vườn hoa, ngắm hoàng hôn.
- 🔥 **18:30 - 20:30**: Tiệc nướng than hoa / Lẩu nóng quây quần bên bếp lửa.
- 🧣 **20:45 - 22:30**: Dạo chợ đêm vùng cao, uống sữa đậu nành nóng / Nghe nhạc Acoustic.

---

## 3. Quy tắc Đường Lui 4 Tầng khi Thiếu Dữ liệu (Graceful 4-Tier Fallback)
Khi người dùng tìm kiếm địa điểm chung chung hoặc dịch vụ vi mô (quán net, bi-a, tiệm thuốc...) không có trong Database và Apify không cào được:
1. **Tầng 1 (Tra cứu DB & Apify)**: Ưu tiên tìm kiếm thực địa chính thức.
2. **Tầng 2 (Thay thế tương đương ngữ nghĩa - Semantic Substitution)**: Tự động gợi ý điểm giải trí/thư giãn cùng bản chất từ `travel_db.db` (rạp phim, trung tâm mua sắm, cafe boardgame) kèm lời giải thích thành thật.
3. **Tầng 3 (Chặng dừng Phố trung tâm - Commercial Hub)**: Đưa người dùng đến khu phố thương mại/chợ sầm uất nhất khu vực nơi các dịch vụ này tập trung để khách tự chọn.
4. **Tầng 4 (Thẻ Hoạt động Tự do + Nút Radar Google Maps)**: Giữ nguyên khung giờ trong Timeline dưới dạng `[Hoạt động tự do]`, tích hợp nút 1-chạm mở app Google Maps quét tìm dịch vụ xung quanh vị trí thực tế của khách. **TUYỆT ĐỐI KHÔNG BỊA ĐẶT ĐỊA DANH ẢO.**

---

## 4. Quy tắc Cảnh báo Điểm Quá Xa (Distance Outlier & Smart Advisory)
- **Ngưỡng khoảng cách bất thường**: Khi một điểm phụ (quán cafe, quán ăn vặt, giải trí) cách cụm tham quan chính trong ngày $\ge 15 - 20\text{ km}$ ($> 35 - 45\text{ phút}$ di chuyển):
  - ❌ **CẤM** âm thầm nhét vào làm con thoi lịch trình, đội chi phí và làm kiệt sức du khách.
  - ✅ **BẮT BUỘC** kích hoạt Thẻ Lời khuyên Thông minh (Smart Advisory Card):
    1. **Minh bạch số liệu**: Nêu rõ số km chênh lệch, thời gian lái xe tốn thêm và chi phí phát sinh ước tính.
    2. **Phương án A (Khuyên dùng)**: Gợi ý điểm tương đương gần hơn trong bán kính $< 3\text{ km}$ của cụm ngày đó.
    3. **Phương án B (Tôn trọng khách)**: Nếu khách bắt buộc phải đi, tự động dời điểm đó về cuối ngày trên đường về khách sạn hoặc ghép sang ngày khác có tuyến đường tiện nhất.

---

## 5. Quy tắc Ghim Ngày Cố định & Hạt Nhân Thích Ứng (Hard Pinned Day & Anchor Clustering)
- Khi người dùng có yêu cầu bắt buộc ghé thăm một địa điểm vào một ngày/buổi cụ thể (Hard Constraint):
  - **Mệnh lệnh tối cao**: Thuật toán gom cụm **TUYỆT ĐỐI KHÔNG ĐƯỢC CHUYỂN** địa điểm ghim sang ngày khác.
  - **Hạt nhân thích ứng (Anchor-Based Adaptive Clustering)**: Lấy điểm ghim làm "Tâm hạt nhân" của Ngày $X$. Tự động hút các điểm tham quan/quán ăn lân cận điểm ghim về Ngày $X$ và đẩy các điểm xa sang ngày khác để tối ưu lộ trình.
  - **Cảnh báo xung đột**: Nếu người dùng ghim 2 điểm cách nhau $> 100\text{ km}$ vào cùng một ngày, hệ thống vẫn xếp theo lệnh nhưng bắt buộc hiện cảnh báo thời gian di chuyển trên cao tốc.

