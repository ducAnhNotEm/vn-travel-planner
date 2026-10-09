# VNTravel AI — Nền Tảng Lập Lịch Trình Du Lịch Việt Nam Thông Minh

Hệ thống lập lịch trình du lịch thông minh cho 34 tỉnh/thành phố Việt Nam, kết hợp thuật toán tối ưu hóa vận trù học (2-Opt Local Search + Hard Time-Window TSPTW), phân bổ nhịp sinh học tự nhiên theo 3 vùng miền, tính toán chi phí di chuyển minh bạch, vẽ bản đồ đường uốn lượn thực tế Goong Maps và tư vấn du lịch thông minh kết hợp Claude 4.6 AI.

---

## 1. Công Nghệ & Kiến Trúc (Tech Stack)

* **Backend**: Python 3.10+, FastAPI, SQLAlchemy 2.0, Pydantic.
* **Cơ sở dữ liệu**: **Thuần SQLite 100% (`travel_db.db`)**
  * Triển khai Zero-Configuration: Clone code về là chạy ngay, không cần Docker, không cần cài đặt database ngoại vi.
  * Tốc độ phản hồi cực nhanh (in-process, 0ms network overhead).
  * Chứa dữ liệu xác thực thực tế 100%: **34 Tỉnh thành**, **3.321 Xã/Phường**, **1.369 Địa danh** (100% có Google Place ID, Google Maps URL và ảnh thực tế) cùng **22 Sân bay dân dụng**.
* **Frontend**: HTML5, Tailwind CSS, FontAwesome, Leaflet.js vẽ polyline đường bộ uốn lượn thực tế theo mạng lưới giao thông Goong Maps Directions.
* **Định vị & Bản đồ**: Hybrid Geolocation (HTML5 GPS + Silent Network IP Fallback qua BigDataCloud & IPWhois).

---

## 2. Mô Hình Lập Lịch Trình (The AI Sandwich Pattern)

1. **Lớp Trên (NLU / User Intent)**: Tiếp nhận yêu cầu người dùng (điểm xuất phát, điểm đến, số ngày từ 1 đến 14, số lượng người, phương tiện, khách sạn neo).
2. **Lớp Giữa (Deterministic Core Engine — Toán học xác định 100%)**:
   * Truy vấn địa danh thực tế từ `travel_db.db`.
   * Tối ưu hóa lộ trình bằng **2-Opt Local Search** khử hoàn toàn giao cắt đường đi, kết hợp **Hard Time-Window TSPTW** đối chiếu giờ mở/đóng cửa và giờ nghỉ trưa thực tế.
   * Phân bổ 3 nhịp sinh học đặc thù: Biển (nghỉ trưa tránh nắng gắt), Di tích/Đô thị, Đồi núi/Cao nguyên (săn mây, dạo chiều).
   * Nhân hệ số địa hình $K_{\text{topo}} \in \{1.25, 1.35, 1.75\}$ (Đồng bằng, Bán sơn địa, Đèo núi).
   * Thuật toán neo khách sạn: Cảnh báo đổi khách sạn khi cự ly $\ge 35\text{ km}$ và tiết kiệm $\ge 20\text{ km}$.
   * Tính toán ngân sách theo 4 loại phương tiện (`car`, `van`, `taxi`, `motorbike`) và quy tắc phòng nghỉ ($\lceil \text{người} / 2 \rceil$).
   * Tự động sinh tuyến đường bộ thực tế qua Goong Directions API với bộ đệm kép RAM + MD5 Disk Cache.
3. **Lớp Dưới (AI Explainer — LLM Layer)**:
   * **ĐÃ TRIỂN KHAI**: Tích hợp **Claude 4.6** (`claude-sonnet-4-6` qua VyceAI API) tại [`app/services/llm_service.py`](file:///d:/vn-travel-planner/app/services/llm_service.py) để sinh lời khuyên đánh đổi khách sạn (Phương án A vs B) và cảnh báo thể lực road trip đường dài, kèm fallback Ollama `vn-travel-qwen:7b` và mẫu câu xác định Zero-Crash.
   * **KẾ HOẠCH (Roadmap)**: End-to-End NLU Request Router phân tách văn bản tự do tại API Gateway; Conversational Re-planner tương tác đa lượt.

---

## 3. Cài Đặt & Chạy Ứng Dụng

### Yêu cầu:
* Python 3.10 trở lên.

### Các bước khởi động:
```powershell
# 1. Tạo môi trường ảo (nếu chưa có)
python -m venv venv
.\venv\Scripts\activate

# 2. Cài đặt các gói phụ thuộc
pip install -r requirements.txt

# 3. Khởi động Web Server FastAPI
uvicorn app.main:app --reload --port 8000
```
Truy cập giao diện tại: `http://localhost:8000`

---

## 4. Chạy Toàn Bộ Bộ Kiểm Thử (127/127 Tests Passed)

Dự án sở hữu bộ kiểm thử tự động toàn diện bao phủ 100% các phân hệ:
```powershell
.\venv\Scripts\python -m pytest tests -q
```
*(Kết quả: `127 passed in ~64s`, thời gian phản hồi warm cache API $< 100\text{ms}$)*

---

## 5. Cấu Trúc Thư Mục Chuẩn

```
vn-travel-planner/
├── app/
│   ├── routers/            # Router FastAPI (/api/plan/calculate, /api/map/directions)
│   ├── services/           # Services lõi: travel_params, travel_calculator, llm_service, map_service
│   ├── config.py           # Cấu hình hệ thống
│   ├── database.py         # Khởi tạo SQLite Engine & Session
│   ├── models.py           # Schema SQLAlchemy (Province, Ward, Place, Airport)
│   └── main.py             # Entry point FastAPI & phục vụ Frontend
├── data/
│   ├── provinces_v2.json   # Dữ liệu 34 tỉnh và 3.321 xã phường
│   └── airports_vietnam.json # Dữ liệu 22 sân bay dân dụng
├── docs/
│   ├── tsptw_specification.md # Đặc tả kỹ thuật 2-Opt & TSPTW
│   └── MODEL_ASSURANCE_MANIFESTO.md
├── frontend/
│   └── index.html          # Giao diện người dùng Leaflet vẽ đường Goong uốn lượn
├── tests/                  # 127 Test cases đạt 100% Pass
├── travel_db.db            # Cơ sở dữ liệu SQLite duy nhất (1.369 địa danh, 22 sân bay)
├── requirements.txt        # Thư viện Python gọn nhẹ
├── AGENTS.md               # Quy chuẩn phát triển & luật thép cho AI Agent
├── PROJECT.md              # Báo cáo kiến trúc & hiện trạng triển khai
├── PROJECT_CONTEXT.md      # Bối cảnh & tài liệu kiến trúc kỹ thuật
└── IMPLEMENTATION_STATUS.md# Nhật ký tiến độ chi tiết
```