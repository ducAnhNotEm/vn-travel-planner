# TÀI LIỆU XÁC ĐỊNH TÁC NHÂN VÀ YÊU CẦU HỆ THỐNG
**Đề tài**: Hệ thống Lập kế hoạch Du lịch Thông minh Đa phương thức tại Việt Nam (VNTravel AI)

---

## I. CÁC TÁC NHÂN CỦA HỆ THỐNG (ACTORS)

Hệ thống **VNTravel AI** bao gồm các tác nhân người dùng và hệ thống ngoại vi sau:

### 1. Tác nhân con người (Human Actors)
1. **Khách du lịch tự do (End User / Traveler)**: 
   - Người dùng trực tiếp sử dụng hệ thống để tìm kiếm điểm đến, nhập sở thích, tải và tùy biến lộ trình (thêm/bớt/đổi điểm, ghim khách sạn, chia tiền nhóm).
2. **Trưởng nhóm du lịch (Trip Leader / Group Organizer)**:
   - Đại diện nhóm bạn hoặc gia đình lập kế hoạch, cấu hình số lượng thành viên, chia sẻ liên kết lịch trình, phân bổ phòng nghỉ và chia đều chi phí phương tiện/ăn uống cho cả đoàn.
3. **Quản trị viên hệ thống (System Administrator / Data Curator)**:
   - Quản lý cơ sở dữ liệu địa điểm du lịch (`travel_db.db`), kiểm duyệt tọa độ, địa chỉ thực tế, hình ảnh chuẩn Wikipedia/Wikimedia, theo dõi hạn mức sử dụng API ngoại vi (Goong Maps, Claude/Gemini AI) và kiểm soát nhật ký hệ thống.

### 2. Tác nhân hệ thống ngoại vi (External System Actors)
4. **Dịch vụ Bản đồ & Chỉ đường (Map & Routing Provider - Goong Maps API)**:
   - Cung cấp dữ liệu Geocoding, ma trận khoảng cách thời gian thực và tọa độ polyline giải mã đường đi thực tế theo mạng lưới giao thông đường bộ Việt Nam.
5. **Dịch vụ Trí tuệ nhân tạo (LLM Engine - Claude 4.6 / Gemini Flash)**:
   - Đảm nhận vai trò NLU Parser (bóc tách ý định, điểm đi/đến, sở thích) và NLG Explainer (tổng hợp lời giải thích lộ trình, tư vấn đổi khách sạn thông minh).
6. **Hệ thống Thông tin Địa lý & Dữ liệu mở (Wikimedia Commons / Google Places CDN)**:
   - Cung cấp nguồn hình ảnh chân thực, ảnh thực địa 100% cho các danh lam thắng cảnh, di tích lịch sử và cơ sở lưu trú.

---

## II. 10 YÊU CẦU CHỨC NĂNG (FUNCTIONAL REQUIREMENTS - FR)

| Mã FR | Tên chức năng | Mô tả chi tiết |
|:---:|:---|:---|
| **FR-01** | **Xử lý ngôn ngữ tự nhiên & Bóc tách ý định (NLU Parsing)** | Hệ thống cho phép người dùng nhập yêu cầu bằng câu tự nhiên (tiếng Việt), tự động phân tích và bóc tách chính xác các thực thể: Điểm xuất phát (`origin`), Điểm đến (`destination`), Số ngày đi, Số lượng người, Phương tiện di chuyển và Thẻ sở thích mà không bị nhầm lẫn giữa điểm đón và điểm du lịch. |
| **FR-02** | **Tự động gom cụm & Phân bổ lịch trình đa ngày (Spatial Clustering)** | Hệ thống tự động phân bổ các điểm tham quan, di tích, giải trí vào từng ngày dựa trên mật độ khoảng cách địa lý (sử dụng thuật toán toán học xác định K-Means/DBSCAN hoặc phân vùng bán kính), đảm bảo các điểm trong cùng một ngày nằm gần nhau để giảm thiểu thời gian di chuyển. |
| **FR-03** | **Tối ưu hóa thứ tự tham quan trong ngày (TSP Routing)** | Với danh sách điểm trong một ngày, hệ thống tự động giải bài toán người du lịch (TSP) để sắp xếp lộ trình tham quan ngắn nhất, bắt đầu từ điểm lưu trú (hoặc điểm xuất phát) qua các chặng tham quan và quay về nơi nghỉ ngơi. |
| **FR-04** | **Phân bổ khung giờ theo Nhịp sinh học du lịch Việt Nam (Human Rhythm Scheduling)** | Hệ thống tự động xếp lịch trình theo 1 trong 3 nhịp sinh học đặc thù (Vùng biển, Vùng di sản/đô thị, Vùng đồi núi), bắt buộc chèn thời gian nghỉ trưa tránh nắng (13:00 - 15:00) tại khách sạn/quán cafe máy lạnh và cố định giờ ăn sáng, trưa, tối hợp lý. |
| **FR-05** | **Tư vấn & Tối ưu hóa điểm lưu trú (Smart Hotel Anchoring & Advisory)** | Hệ thống đánh giá khoảng cách từ khách sạn tới cụm tham quan trong ngày. Nếu khoảng cách một chiều $\ge 35\text{ km}$, hệ thống kích hoạt thẻ tư vấn với 2 phương án: Phương án A (gợi ý đổi khách sạn lân cận để tiết kiệm thời gian) và Phương án B (giữ nguyên khách sạn của khách và cảnh báo thời gian di chuyển). |
| **FR-06** | **Tính toán chi phí & Phân bổ ngân sách chi tiết (Budget & Room Calculation)** | Hệ thống tự động ước tính chi phí chuyến đi dựa trên đơn giá thực tế từ cơ sở dữ liệu: tính số phòng nghỉ theo công thức $\lceil \text{Số người}/2 \rceil$, chia đều tiền nhiên liệu/thuê xe/vé đỗ cho cả nhóm và tính chi phí ăn uống, vé vào cổng từng người. |
| **FR-07** | **Định tuyến Road Trip đường dài & Ràng buộc an toàn sinh học (Fatigue Constraint)** | Khi khách di chuyển đường bộ cự ly dài ($> 300\text{ km}$), hệ thống tự động chèn trạm dừng nghỉ ngắn 30 phút sau mỗi 3.5 giờ lái xe liên tục, giới hạn tối đa 8 giờ lái xe/ngày và tự động đề xuất điểm dừng chân nghỉ đêm liên tỉnh (Overnight Staging City). |
| **FR-08** | **Định tuyến trung chuyển đa phương thức & Sân bay cửa ngõ (Multi-Modal & Gateway Airport)** | Đối với các chặng di chuyển liên tỉnh $\ge 300\text{ km}$ hoặc điểm đến không có sân bay thương mại (Sa Pa, Hội An, Ninh Bình...), hệ thống tự động quét các sân bay cửa ngõ trong bán kính $150\text{ km}$ và lập lộ trình kết hợp: Đón chặng đầu (First-mile) $\rightarrow$ Bay trung chuyển $\rightarrow$ Đường bộ chặng cuối (Last-mile). |
| **FR-09** | **Tương tác bản đồ số & Hiển thị đường đi thực tế (Interactive Map & Polyline)** | Hệ thống hiển thị bản đồ trực quan bằng Leaflet/Mapbox, vẽ đường polyline thực tế bám sát mạng lưới đường bộ (thông qua Goong API cache) thay vì đường chim bay, hiển thị các marker kèm liên kết Google Place ID/URL dẫn đường đã được xác thực 100%. |
| **FR-10** | **Tùy biến & Chỉnh sửa lịch trình tương tác (Interactive Re-planning)** | Người dùng có thể kéo thả thay đổi thứ tự địa điểm, thêm/xóa điểm đến, ghim cố định một địa điểm vào ngày cụ thể (Hard Pinned Day), hoặc yêu cầu AI tái tính toán và giải thích lại toàn bộ lịch trình. |

---

## III. 10 YÊU CẦU PHI CHỨC NĂNG (NON-FUNCTIONAL REQUIREMENTS - NFR)

| Mã NFR | Tiêu chí | Mô tả chi tiết |
|:---:|:---|:---|
| **NFR-01** | **Hiệu năng & Thời gian phản hồi (Performance & Latency)** | Thời gian tính toán và trả về toàn bộ kế hoạch lịch trình đa ngày (gồm gom cụm, giải thuật TSP, tính toán ngân sách và vẽ lộ trình) không vượt quá 2.5 giây đối với thuật toán lõi, và không quá 5 giây khi có bước tạo lời giải thích từ LLM. |
| **NFR-02** | **Tính toàn vẹn & Xác thực dữ liệu (Data Integrity & Ground Truth)** | 100% địa điểm, khách sạn và nhà hàng phải tồn tại thực tế trong cơ sở dữ liệu `travel_db.db`. Nghiêm cấm địa chỉ giả mạo (placeholder `"{name}, {province}"`); các liên kết Google Maps chỉ hiển thị khi có Place ID xác thực, nếu không có phải gán giá trị `null` để tránh người dùng lạc đường. |
| **NFR-03** | **Độ tin cậy & Khả năng chịu lỗi (Reliability & Fault Tolerance)** | Hệ thống áp dụng cơ chế phòng thủ đa tầng: nếu dịch vụ bên thứ ba (Goong API, Claude API) bị timeout hoặc cạn kiệt quota, hệ thống tự động chuyển sang giải thuật tính khoảng cách Haversine nội bộ và bộ đệm bộ nhớ (LRU Cache / MD5 Disk Cache), tuyệt đối không để xảy ra lỗi máy chủ nội bộ (500 Internal Server Error). |
| **NFR-04** | **Tính bảo mật (Security & API Protection)** | Các API Key trả phí (Google Maps API, Goong API, VyceAI LLM Key) bắt buộc phải lưu trữ an toàn ở biến môi trường backend, tuyệt đối không lộ ở mã nguồn frontend. Mọi yêu cầu gọi geocoding hoặc ma trận lộ trình đều phải đi qua Gateway API nội bộ. |
| **NFR-05** | **Khả năng mở rộng & Kiến trúc phân lớp (Scalability & Decoupled Architecture)** | Hệ thống tuân thủ mô hình AI Sandwich và Clean Architecture, phân tách độc lập giữa tầng NLU, tầng tính toán toán học cốt lõi (Deterministic Core Engine) và tầng giải thích NLG. Cho phép mở rộng dữ liệu từ 34 tỉnh hiện tại lên 63 tỉnh/thành phố mà không cần sửa cấu trúc mã nguồn. |
| **NFR-06** | **Tính chính xác trong tính toán (Mathematical Rigor & Determinism)** | Toàn bộ bài toán định tuyến cự ly, thời gian di chuyển, số lượng phòng khách sạn và chia tiền nhóm phải được tính bằng giải thuật toán học tất định (Deterministic Python Engine), tuyệt đối không để LLM tự suy diễn hoặc nhẩm số học. |
| **NFR-07** | **Khả năng tương thích & Đa nền tảng (Compatibility & Cross-Platform)** | Giao diện người dùng (Frontend) tương thích hoàn toàn trên các trình duyệt hiện đại (Chrome, Edge, Firefox, Safari) và hiển thị chuẩn Responsive trên cả thiết bị di động (Mobile) lẫn máy tính để bàn (Desktop). |
| **NFR-08** | **Tính khả dụng & Trải nghiệm người dùng (Usability & Accessibility)** | Giao diện trình bày trực quan, thông tin chi phí và lịch trình được trực quan hóa bằng dòng thời gian (Timeline) và bản đồ số đồng bộ; người dùng có thể tạo một lịch trình hoàn chỉnh chỉ với tối đa 3 thao tác cơ bản. |
| **NFR-09** | **Khả năng lưu trữ đệm & Tối ưu băng thông (Caching & Resource Optimization)** | Hệ thống triển khai bộ nhớ đệm kép (In-memory LRU Cache kết hợp đệm tệp MD5) cho các truy vấn lộ trình và Geocoding nhằm giảm ít nhất 70% số lượng request lặp lại ra dịch vụ ngoài, giúp tiết kiệm chi phí và tăng tốc độ phản hồi. |
| **NFR-10** | **Khả năng bảo trì & Giám sát (Maintainability & Observability)** | Mã nguồn được chuẩn hóa theo tiêu chuẩn PEP8, có tài liệu API tự động (OpenAPI/Swagger tại `/docs`), cấu trúc module hóa cao và ghi nhật ký hệ thống (structured logging) theo từng chặng tính toán để dễ dàng truy vết và gỡ lỗi. |
