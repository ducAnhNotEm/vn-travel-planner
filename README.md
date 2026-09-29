# VNTravel AI - Nền Tảng Lập Lịch Trình Du Lịch Việt Nam Thông Minh

Hệ thống lập lịch trình du lịch thông minh cho 34 tỉnh/thành phố Việt Nam, kết hợp thuật toán tối ưu hóa đường đi ngắn nhất (Nearest Neighbor TSP), phân bổ nhịp sinh học tự nhiên cho con người, tính toán chi phí di chuyển thực tế và đề xuất đổi khách sạn thông minh.

---

## 1. Công Nghệ & Kiến Trúc (Tech Stack)

* **Backend**: Python 3.10+, FastAPI, SQLAlchemy 2.0, Pydantic.
* **Cơ sở dữ liệu**: **Thuần SQLite 100% (`travel_db.db`)**
  * Triển khai Zero-Configuration: Clone code về là chạy ngay, không cần Docker, không cần cài đặt database server ngoại vi.
  * Tốc độ phản hồi cực nhanh (in-process, 0ms latency kết nối mạng).
  * Chứa dữ liệu xác thực thực tế: 34 Tỉnh thành, 3.321 Xã/Phường, cùng các địa điểm du lịch, khách sạn, nhà hàng, chùa chiền.
* **Frontend**: HTML5, Tailwind CSS, FontAwesome, giao diện desktop-first lấy cảm hứng từ Traveloka (`#0F294D` Deep Blue & `#FF5E1F` Warm Orange).
* **Định vị & Bản đồ**: Hybrid Geolocation (HTML5 GPS + Silent Network IP Fallback qua BigDataCloud & IPWhois).

---

## 2. Mô Hình Lập Lịch Trình (The AI Sandwich)

1. **Lớp Trên (NLU - Intent Parser)**: Trích xuất ý định người dùng (tỉnh đích, số ngày, số lượng người, phương tiện, sở thích).
2. **Lớp Giữa (Deterministic Python Engine)**:
   * Truy vấn địa điểm thực tế từ `travel_db.db`.
   * Tối ưu hóa lộ trình ngắn nhất (Haversine Distance + Nearest Neighbor TSP).
   * Phân bổ nhịp sinh học: *Tham quan sáng $\rightarrow$ Ăn trưa $\rightarrow$ Nghỉ trưa/Check-in $\rightarrow$ Tham quan chiều $\rightarrow$ Cà phê $\rightarrow$ Ăn tối $\rightarrow$ Chợ đêm/Nghỉ ngơi*.
   * Thuật toán tối ưu khách sạn: Cảnh báo đổi khách sạn khi khoảng cách di chuyển giữa các ngày $\ge 30 - 40\text{ km}$.
   * Tính toán ngân sách chính xác theo 4 loại phương tiện (`car`, `chartered_van`, `taxi`, `motorbike`) và quy tắc phòng nghỉ ($\lceil \text{người} / 2 \rceil$).
3. **Lớp Dưới (NLG - Explainer)**: Thuyết minh hợp lý hóa lịch trình và hỗ trợ điều chỉnh linh hoạt.

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

Mở trình duyệt tại: **`http://localhost:8000/`** để sử dụng ứng dụng web.
Tài liệu API Swagger UI: **`http://localhost:8000/docs`**.

---

## 4. Cấu Trúc Thư Mục

```
vn-travel-planner/
├── app/
│   ├── routers/            # Các router FastAPI (/api/plan)
│   ├── services/           # Thuật toán tính toán, tối ưu lộ trình & chi phí
│   ├── config.py           # Cấu hình hệ thống (Database URL)
│   ├── database.py         # Khởi tạo SQLite Engine & Session
│   ├── models.py           # Schema SQLAlchemy (Province, Ward, Place)
│   ├── init_db.py          # Script nạp danh mục tỉnh thành & xã phường
│   └── main.py             # Entry point FastAPI & phục vụ Frontend
├── data/
│   ├── provinces_v2.json   # Dữ liệu 34 tỉnh và 3.321 xã phường
│   └── places_63_to_34.json# Cơ sở dữ liệu 2.209 địa điểm 63 tỉnh thành ánh xạ 34 tỉnh
├── frontend/
│   └── index.html          # Giao diện người dùng hoàn chỉnh 5 màn hình
├── travel_db.db            # Cơ sở dữ liệu SQLite duy nhất của dự án
├── requirements.txt        # Danh sách thư viện Python gọn nhẹ
├── AGENTS.md               # Quy chuẩn phát triển & luật thép cho AI Agent
├── PROJECT_CONTEXT.md      # Bối cảnh & tài liệu kiến trúc kỹ thuật
├── RULES_63_PROVINCES_ENRICHMENT.md # Quy tắc ánh xạ 63 tỉnh sang 34 tỉnh quy hoạch
└── IMPLEMENTATION_STATUS.md# Tiến độ triển khai các hạng mục
```