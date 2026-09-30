# Feature Specification: 001-multi-day-planner-goong
<!-- Spec Kit Feature Specification -->

## 1. Problem Statement
- **Vấn đề**: Hiện tại hệ thống chỉ mới hỗ trợ lập lịch trình đơn ngày (1 ngày) qua hàm `optimize_route` (TSP đơn). Khi người dùng đi nhiều ngày (2 - 5 ngày) với đoàn đông người:
  1. Chưa có thuật toán phân cụm địa lý theo từng ngày (dẫn đến việc chạy lòng vòng giữa các ngày).
  2. Chưa có sắp xếp theo nhịp sinh học du lịch Việt Nam (Sáng di tích, Trưa ăn ngon, Chiều trải nghiệm/cafe, Tối dạo phố).
  3. Chưa có bản đồ tĩnh (Goong Static Map) để người dùng xem nhanh lộ trình đường thật của từng ngày.
  4. Chi phí di chuyển chưa được tính toán chính xác cho cả chuyến đi và chia bình quân theo từng người.
- **Mục tiêu**: Xây dựng bộ máy lập lịch trình đa ngày hoàn chỉnh, tích hợp Goong Static Map bảo mật qua Backend Proxy, và xuất bảng tài chính minh bạch cho cả đoàn và từng người.

## 2. User Stories & Scenarios
- **Story 1 (Đoàn đông người)**: "Chúng tôi là nhóm 4 người đi Đà Nẵng 3 ngày 2 đêm bằng ô tô. Chúng tôi muốn biết mỗi ngày đi những cụm nào, xem bản đồ đường đi của ngày đó, và biết rõ tổng tiền xe, tiền khách sạn là bao nhiêu và mỗi người phải chia nhau bao nhiêu tiền."
- **Story 2 (Điền khuyết tự động)**: "Tôi chỉ chọn 2 điểm yêu thích ở Ninh Bình, nhưng đi 2 ngày. Hệ thống phải tự tìm thêm nhà hàng đặc sản và quán cafe lân cận để lấp đầy lịch trình mà tôi không cần phải tự nghĩ."

## 3. Functional Requirements
- **FR-1 [Multi-day Clustering]**: Tự động gom cụm các địa điểm theo $K$ ngày ($K \in [1, 5]$) dựa trên ma trận khoảng cách Haversine.
- **FR-2 [Biological Rhythm Sequencing]**: Phân bổ thứ tự các điểm trong ngày theo nhịp:
  - Buổi sáng: `ATTRACTION` / Di tích / Thắng cảnh.
  - Buổi trưa: `RESTAURANT` / Ẩm thực địa phương.
  - Buổi chiều: `ACTIVITY` / Check-in / Cafe.
  - Buổi tối: `RESTAURANT` $\rightarrow$ `MARKET` / Chợ đêm / Dạo phố.
- **FR-3 [Smart Gap-filling]**: Khi số điểm người dùng chọn không đủ các buổi trong $K$ ngày, tự động query `travel_db.db` lấy thêm các điểm cùng tỉnh trong bán kính lân cận cụm ngày đó.
- **FR-4 [Goong Static Map Proxy]**:
  - Backend cung cấp endpoint `/api/map/static-route` tạo ảnh bản đồ lộ trình thực tế bằng Goong Static Map.
  - Caching ảnh theo hash lộ trình trong `data/map_cache/` để bảo vệ quota.
- **FR-5 [Deterministic Expense Calculation]**:
  - Tính tổng quãng đường cả chuyến đi.
  - Tính tiền xe cả đoàn theo loại phương tiện.
  - Tính số phòng: $\text{rooms} = \lceil \text{group\_size} / 2 \rceil$.
  - Tính tiền bình quân đầu người: $\text{cost\_per\_person} = \text{total\_cost} / \text{group\_size}$.

## 4. Non-Functional Requirements & Safety Guards
- Tuân thủ [constitution.md](../../memory/constitution.md):
  - 100% địa điểm từ `travel_db.db`, không bịa đặt địa chỉ.
  - `GOONG_API_KEY` nằm trong backend `.env`, không bao giờ lộ ra frontend.
  - Nếu Goong API gặp lỗi mạng hoặc hết quota, hệ thống tự động fallback êm thấm mà không làm sập ứng dụng.

## 5. Acceptance Criteria
- [ ] Lập lịch trình 3 ngày tại Đà Nẵng chia đúng 3 cụm ngày riêng biệt.
- [ ] Mỗi ngày có ảnh bản đồ tĩnh đường đi từ Goong Map hiển thị mượt mà.
- [ ] Bảng chi phí hiển thị rõ ràng: Tổng tiền xe cả đoàn, tổng tiền phòng cả đoàn, và số tiền bình quân mỗi người.
- [ ] Vẫn giữ nguyên 100% nút ghim Google Maps URL cho từng địa điểm.
