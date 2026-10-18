# VNTravel AI — Nền Tảng Lập Lịch Trình & Trợ Lý Du Lịch Việt Nam Thông Minh

Hệ thống lập lịch trình du lịch thông minh cho 34 tỉnh/thành phố Việt Nam, tích hợp **Trợ lý Trò chuyện AI Đa lượt (Conversational AI Assistant)**, kết hợp thuật toán tối ưu hóa vận trù học (2-Opt Local Search + Hard Time-Window TSPTW), phân bổ 3 nhịp sinh học tự nhiên, tính toán chi phí minh bạch, vẽ bản đồ đường uốn lượn thực tế Goong Maps và hệ thống xác thực, lưu trữ phiên chat đa người dùng bảo mật cao.

---

## 1. Điểm Nhấn Kiến Trúc & Công Nghệ (Core Tech Stack)

* **Backend Framework**: Python 3.10+, FastAPI, SQLAlchemy 2.0, Pydantic v2.
* **Kiến trúc Cơ sở dữ liệu Kép (Dual-SQLite Zero-Lock Architecture)**:
  * **`travel_db.db` (Dữ liệu Tĩnh & Nghiệp vụ Địa lý)**: Chứa **34 Tỉnh thành**, **3.321 Xã/Phường**, **1.369 Địa danh** (100% có Google Place ID, Google Maps URL và ảnh thực tế) cùng **22 Sân bay dân dụng**. Read-heavy, không bị nghẽn.
  * **`chat_state.db` (Dữ liệu Động & Quản lý Phiên)**: Quản lý người dùng, token xác thực, phiên hội thoại (`chat_sessions`) và tin nhắn (`chat_messages`). Thiết kế độc lập hoàn toàn để không khóa `travel_db.db` khi ghi đồng thời.
* **Hệ thống Hội thoại & NLU (Conversational AI)**:
  * **NLU Pipeline**: Phân tách ý định và trích xuất thực thể (Điểm đến, điểm xuất phát, số ngày, phương tiện, ngân sách, địa điểm yêu thích/loại trừ).
  * **Dialogue Engine (Rule-based)**: Đọc luật từ `config/dialogue.json`, tự động phát hiện slot cốt lõi còn thiếu và sinh tối đa 2 câu hỏi làm rõ kèm danh sách nút gợi ý (chips).
  * **Cơ chế Nút gợi ý (Chips)**: Bấm chip sẽ ghi thẳng vào slot tương ứng và **bỏ qua NLU 100% (bypasses NLU)** để tăng tốc độ phản hồi và chống hallucination.
* **Xác thực & Bảo mật Đa người dùng (Auth & Multi-Tenancy)**:
  * Thuật toán băm mật khẩu: PBKDF2-HMAC-SHA256 với salt ngẫu nhiên 16 bytes và dummy hash chống Timing Attack.
  * Opaque Random Token được lưu dưới dạng SHA-256 hash trong DB.
  * Hỗ trợ đồng thời **Bearer Authorization Header** và **httpOnly Cookie** (`SameSite=Lax`).
  * Cô lập đa người dùng tuyệt đối: Mỗi user chỉ có tối đa 1 phiên đang dở (`collecting` hoặc `ready`); truy cập chéo phiên bị chặn 403 Forbidden.
  * Phục hồi trạng thái hoàn hảo khi tải lại trang (F5 reload / Drawer reopen).
* **Deterministic Core Engine (Toán học xác định 100%)**:
  * Tối ưu hóa lộ trình bằng **2-Opt Local Search** khử hoàn toàn giao cắt đường đi, kết hợp **Hard Time-Window TSPTW** đối chiếu giờ mở/đóng cửa và giờ nghỉ trưa thực tế.
  * Phân bổ 3 nhịp sinh học đặc thù: Biển (nghỉ trưa tránh nắng gắt), Di tích/Đô thị, Đồi núi/Cao nguyên (săn mây, dạo chiều).
  * Nhân hệ số địa hình $K_{\text{topo}} \in \{1.25, 1.35, 1.75\}$ (Đồng bằng, Bán sơn địa, Đèo núi).
  * Thuật toán neo khách sạn: Cảnh báo đổi khách sạn khi cự ly $\ge 35\text{ km}$ và tiết kiệm $\ge 20\text{ km}$.
* **Frontend & Bản đồ**:
  * HTML5, Tailwind CSS, FontAwesome, Leaflet.js vẽ polyline đường bộ uốn lượn thực tế theo Goong Maps Directions API với bộ đệm kép RAM + MD5 Disk Cache.
  * Hybrid Geolocation (HTML5 GPS + Silent Network IP Fallback qua BigDataCloud & IPWhois).

---

## 2. Hợp Đồng API Chính (API Endpoints)

### A. Xác thực (`/api/auth`)
| Phương thức | Đường dẫn | Mô tả |
|---|---|---|
| `POST` | `/api/auth/register` | Đăng ký tài khoản mới (tối thiểu 8 ký tự mật khẩu) & tự động đăng nhập (201) |
| `POST` | `/api/auth/login` | Đăng nhập tài khoản bằng email & mật khẩu (200) |
| `GET` | `/api/auth/me` | Lấy thông tin người dùng hiện tại (yêu cầu Bearer hoặc Cookie) |
| `POST` | `/api/auth/logout` | Đăng xuất, thu hồi token trong DB và xóa cookie httpOnly |

### B. Phiên Trò Chuyện AI (`/api/chat`)
| Phương thức | Đường dẫn | Mô tả |
|---|---|---|
| `POST` | `/api/chat/sessions` | Lấy phiên đang dở hiện có của người dùng, hoặc khởi tạo phiên mới |
| `GET` | `/api/chat/sessions/{id}` | Lấy chi tiết phiên, bản yêu cầu (`trip_request`) và toàn bộ lịch sử tin nhắn để phục hồi giao diện |
| `POST` | `/api/chat/sessions/{id}/messages` | Gửi tin nhắn văn bản (qua NLU) hoặc sự kiện bấm chip (bỏ qua NLU). Khi đủ slot, trả về `planning` + `plan_task_id` |

### C. Lập Lịch Trình & Bản Đồ
| Phương thức | Đường dẫn | Mô tả |
|---|---|---|
| `POST` | `/api/plan/calculate` | Tính toán lịch trình tối ưu theo 2-Opt & TSPTW |
| `POST` | `/api/plan/parse-prompt` | Phân tích prompt NLU thô độc lập |
| `GET` | `/api/map/directions` | Lấy tọa độ đường uốn lượn thực tế từ Goong Directions |

---

## 3. Cài Đặt & Chạy Ứng Dụng

### Yêu cầu:
* Python 3.10 trở lên (khuyên dùng Python 3.12).
* Không cần cài đặt cơ sở dữ liệu bên ngoài (Zero-Configuration với SQLite).

### Các bước khởi động:
```powershell
# 1. Tạo môi trường ảo (nếu chưa có)
python -m venv venv
.\venv\Scripts\activate

# 2. Cài đặt các gói phụ thuộc
pip install -r requirements.txt
pip install httpx

# 3. Khởi động Web Server FastAPI
uvicorn app.main:app --reload --port 8000
```

Truy cập ứng dụng tại:
- Giao diện người dùng: `http://localhost:8000`
- Tài liệu API tương tác (Swagger UI): `http://localhost:8000/docs`

---

## 4. Bộ Kiểm Thử Tự Động (806/806 Tests Passed)

Dự án sở hữu bộ kiểm thử tự động toàn diện bao phủ 100% các phân hệ (NLU, Dialogue Engine, Gazetteer, SQLite DAO, Auth, Concurrency Locks, API Routers, Acceptance Tests và TSPTW Optimization):

```powershell
python -m pytest -q
```

**Kết quả kiểm chứng thực tế**:
```
806 passed, 1 warning in ~70s (100% Pass, Zero Regression)
```

### Các bộ test quan trọng:
- `tests/test_chat_sessions_and_auth.py`: Kiểm thử nghiệm thu (Acceptance Tests) cho Mục 12A (Xác thực, 401 unauthenticated, 403 cross-tenant isolation) và Mục 12D (F5 reload / phục hồi phiên).
- `tests/test_chat_routers.py`: 98 test kiểm thử tích hợp toàn diện router chat, xử lý đồng thời (64-stripe locking), chip bypass NLU và lập lịch.
- `tests/test_auth_service.py`: 135 test kiểm tra mã hóa mật khẩu, quản lý token, timing attack defense và FastAPI dependency injection.
- `tests/test_chat_storage.py`: 99 test kiểm tra tính toàn vẹn dữ liệu SQLite, tie-break tin nhắn, thread-safety và ràng buộc unique index.
- `tests/test_dialogue_engine.py`: 137 test kiểm tra bộ quy tắc sinh câu hỏi làm rõ, tạo chip và cập nhật lượt tương tác.

---

## 5. Cấu Trúc Thư Mục Dự Án

```
vn-travel-planner/
├── app/
│   ├── config/
│   │   └── dialogue.json       # Quy tắc hỏi làm rõ & template câu hỏi/nút gợi ý
│   ├── routers/
│   │   ├── auth_router.py      # Endpoints xác thực: /register, /login, /me, /logout
│   │   ├── chat_router.py      # Endpoints chat: /sessions, /messages (khóa phân mảnh)
│   │   ├── planner_router.py   # Endpoint lập lịch trình du lịch
│   │   └── map_router.py       # Endpoint vẽ đường bản đồ Goong
│   ├── services/
│   │   ├── auth_service.py     # Hash PBKDF2, token SHA-256, dependency get_current_user
│   │   ├── chat_storage.py     # SQLite DAO cho chat_state.db (user, token, session, message)
│   │   ├── dialogue_engine.py  # Bộ quy tắc hỏi làm rõ & sinh nút chip thuần túy
│   │   ├── dialogue_state.py   # Dialogue State Reducer gộp slot NLU & quản lý bất biến
│   │   ├── nlu_adapter.py      # Adapter chuẩn hóa NLU output sang NLUFlatOutput
│   │   ├── gazetteer.py        # Tra cứu & phân giải thực thể địa danh (34 tỉnh thành)
│   │   ├── prompt_nlu_service.py # Dịch vụ phân tích câu hỏi tự nhiên bằng LLM
│   │   ├── travel_calculator.py# Thuật toán lõi 2-Opt & TSPTW
│   │   ├── travel_params.py    # Nguồn sự thật duy nhất (Single Source of Truth)
│   │   └── llm_service.py      # Tích hợp Claude 4.6 tư vấn thông minh
│   ├── chat_models.py          # Pydantic v2 schemas tầng API chat & auth
│   ├── dialogue_models.py      # Schema bản yêu cầu chuyến đi (TripRequest)
│   ├── database.py             # SQLite engine cho travel_db.db
│   ├── models.py               # SQLAlchemy models (Province, Ward, Place, Airport)
│   └── main.py                 # FastAPI App khởi chạy & kết nối routers
├── data/
│   ├── provinces_v2.json       # Dữ liệu 34 tỉnh và 3.321 xã phường
│   └── airports_vietnam.json   # Dữ liệu 22 sân bay dân dụng
├── docs/
│   ├── PRODUCT_SPEC.md         # Đặc tả sản phẩm & Hợp đồng phát triển Chat AI
│   └── tsptw_specification.md  # Đặc tả thuật toán vận trù học 2-Opt & TSPTW
├── frontend/
│   ├── index.html              # Giao diện chính người dùng & Bản đồ Leaflet
│   └── plan_stream.js          # Client-side streaming & rendering lịch trình
├── tests/                      # 806 Test cases tự động đạt 100% Pass
├── travel_db.db                # SQLite DB chứa dữ liệu địa danh & hành chính thực tế
├── AGENTS.md                   # Tiêu chuẩn kỹ thuật Top 0.1% & Quy tắc vận hành Agent
├── requirements.txt            # Thư viện phụ thuộc
└── README.md                   # Tài liệu hướng dẫn dự án
```