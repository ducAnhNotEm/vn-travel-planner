# VNTravel AI — Tài Liệu Kiến Trúc & Hiện Trạng Dự Án (Project Master Specification)

> **Tiêu chuẩn Kỹ thuật**: Top 0.1% Elite Systems Engineering & `AGENTS.md`  
> **Nguyên tắc Cốt lõi**: Zero Hallucination, Toán học xác định trên hết (Deterministic Math Core), LLM là lớp giao tiếp & thuyết minh (AI Sandwich Pattern), 100% dữ liệu thực địa từ `travel_db.db`.  
> *Cập nhật lần cuối: Tháng 10/2026*

---

## 1. Cơ Sở Dữ Liệu & Các Con Số Sự Thật (Ground Truth Matrix)

Mọi tài liệu, code và cấu hình trong dự án đều bắt buộc phải đồng bộ tuyệt đối với bảng số liệu thực địa sau:

| Chỉ số / Thực thể | Con số Chuẩn xác 100% | Nguồn Sự Thật (Source of Truth) | Ghi chú & Kiểm chứng |
|---|:---:|---|---|
| **Số Tỉnh / Thành phố** | **34** | `provinces` trong `travel_db.db` | Ánh xạ từ 63 tỉnh lịch sử sang 34 tỉnh quy hoạch mới |
| **Số Đơn vị Xã / Phường** | **3.321** | `wards` trong `travel_db.db` | Cấu trúc phân cấp hành chính chuẩn quốc gia |
| **Tổng số Địa danh Du lịch** | **1.369** | `places` trong `travel_db.db` | 100% có `google_place_id` (`ChIJ...`), 100% có `google_maps_url`, 100% có ảnh thực tế |
| **Số Sân bay Dân dụng** | **22** | `airports` trong `travel_db.db` | 11 sân bay quốc tế, 11 sân bay nội địa toàn quốc |
| **Bán kính Sân bay Cửa ngõ** | **$\le 150\text{ km}$** | `app/services/travel_params.py` | Quét cửa ngõ cho tỉnh không có sân bay (Hội An, Ninh Bình, Sa Pa...) |
| **Thời lượng Chuyến đi** | **1 đến 14 ngày** | `MAX_TRIP_DAYS = 14` | Mở rộng linh hoạt, không ép cứng 5N4Đ |
| **Ngưỡng Kích hoạt Hàng không** | **$\ge 300\text{ km}$** | `ROAD_TRIP_THRESHOLD_KM` | Khoảng cách trắc địa liên tỉnh một chiều |
| **Ngưỡng Cảnh báo Xa Khách sạn** | **$\ge 35\text{ km}$** | `HOTEL_FAR_ONE_WAY_KM` | Cự ly 1 chiều kích hoạt Thẻ Tư vấn Vị trí Khách sạn A/B |
| **Ngưỡng Tiết kiệm Đổi Khách sạn** | **$\ge 20\text{ km}$** | `HOTEL_MIN_SAVING_KM` | Mức cự ly tiết kiệm tối thiểu để khuyến nghị chuyển phòng |
| **Trần Thể lực Lái xe / Ngày** | **$\le 400\text{ km}$ / $8\text{h}$** | `SAFE_DAILY_KM["car"]` | Ô tô: 400km; Xe máy: 280km; Trạm nghỉ (Pit-stop) mỗi 3.5h |
| **Bộ Kiểm thử Tự động** | **127 / 127 PASS** | `pytest tests -q` | 5 Test Suites, 100% Pass, Độ trễ warm cache < 100ms |

---

## 2. Kiến Trúc 3 Tầng: The AI Sandwich Pattern

```
                       ┌────────────────────────────────────────┐
                       │       LỚP TRÊN: NLU / GIAO DIỆN        │
                       │   Frontend Input & Intent Extraction   │
                       └───────────────────┬────────────────────┘
                                           │
                                           ▼
                       ┌────────────────────────────────────────┐
                       │     LỚP GIỮA: DETERMINISTIC ENGINE     │
                       │  - Tra cứu 100% thực địa travel_db.db  │
                       │  - 2-Opt Local Search & TSPTW          │
                       │  - K_topo & 3 Nhịp sinh học du lịch    │
                       │  - Goong Directions Real Polylines     │
                       │  - Hotel Commute & Road Trip Safety    │
                       └───────────────────┬────────────────────┘
                                           │
                                           ▼
                       ┌────────────────────────────────────────┐
                       │       LỚP DƯỚI: AI EXPLAINER (LLM)     │
                       │   Claude 4.6 (VyceAI) / Ollama Qwen    │
                       │   Tư vấn đánh đổi khách sạn & thể lực  │
                       └────────────────────────────────────────┘
```

---

## 3. Ma Trận Đã Triển Khai vs Kế Hoạch (Implementation Matrix)

### 3.1. Các Phân Hệ Cốt Lõi

| Phân hệ (Subsystem) | Hạng mục Kỹ thuật | Trạng thái | Chi tiết Triển khai |
|---|---|:---:|---|
| **Cơ sở Dữ liệu** | 1.369 Địa danh chuẩn mực | **ĐÃ TRIỂN KHAI** | Thuần SQLite `travel_db.db`, 0 vi phạm khóa ngoại, 100% Google Place ID & ảnh thực tế. |
| **Cơ sở Dữ liệu** | 22 Sân bay & 34 Tỉnh thành | **ĐÃ TRIỂN KHAI** | Bảng `airports`, `provinces`, `wards` chuẩn hóa toàn diện. |
| **Vận trù học Định tuyến** | 2-Opt Local Search | **ĐÃ TRIỂN KHAI** | Khử 100% crossing edges, tiết kiệm 21.9% - 38.2% quãng đường thừa. |
| **Vận trù học Định tuyến** | Hard Time-Window TSPTW | **ĐÃ TRIỂN KHAI** | Ràng buộc giờ mở cửa `working_hours`, giờ nghỉ trưa, 3 nhịp sinh học (Biển, Di tích, Đồi núi). |
| **Vận trù học Định tuyến** | Hệ số Địa hình $K_{\text{topo}}$ | **ĐÃ TRIỂN KHAI** | $1.25$ (Đồng bằng), $1.35$ (Bán sơn địa), $1.75$ (Đèo núi hiểm trở). |
| **Hàng không Đa phương thức** | Door-to-Door Flight Pipeline | **ĐÃ TRIỂN KHAI** | 3 chặng (First-mile $\to$ Air Corridor tím $\to$ Last-mile), Gateway Airport Radius 150km. |
| **Road Trip Đường dài** | Fatigue Caps & Pit-stops | **ĐÃ TRIỂN KHAI** | Nghỉ sau 3.5h, trần 8h/ngày, tách chặng nghỉ đêm (Staging City) khi $\ge 650\text{ km}$. |
| **Road Trip Đường dài** | Feasibility Trade-offs | **ĐÃ TRIỂN KHAI** | Trả về 3 phương án đánh đổi: `FLY`, `MORE_DAYS`, `CLOSER_DEST`. |
| **Bản đồ Thực tế** | Goong Real Directions | **ĐÃ TRIỂN KHAI** | Giải mã `overview_polyline` thành chuỗi tọa độ thực tế bám theo đường bộ trên Leaflet, bộ đệm kép RAM + MD5 Disk Cache. |
| **Khách sạn** | Neo Khách sạn (`selected_hotel_id`) | **ĐÃ TRIỂN KHAI** | Tôn trọng 100% lựa chọn khách, đo cự ly khứ hồi, kích hoạt Thẻ Tư vấn A/B khi cự ly $\ge 35\text{ km}$. |
| **Hạ tầng Kiểm thử** | 127 Test Cases | **ĐÃ TRIỂN KHAI** | 5 Suites đạt 100% Pass, Benchmark độ trễ Warm Cache $< 100\text{ms}$ (thực tế ~31ms). |
| **Xuất Lịch trình Thực địa** | Google Maps Multi-Stop Link | **KẾ HOẠCH (P2)** | Sinh link điều hướng nhiều điểm dừng trên Google Maps app cho từng ngày. |
| **Xuất Lịch trình Thực địa** | Xuất tệp iCal (`.ics`) | **KẾ HOẠCH (P2)** | Xuất lịch trình vào Apple Calendar / Google Calendar kèm chuông nhắc trước 15 phút. |

---

### 3.2. TRỌNG TÂM: Phân Định Rõ Ràng Tầng LLM (ĐÃ TRIỂN KHAI vs KẾ HOẠCH)

Đây là phân định rõ ràng nhất về sự khác biệt giữa những gì **đã chạy thực tế trong code** và những gì **mới là nghiên cứu/kế hoạch**:

#### A. ĐÃ TRIỂN KHAI (Implemented & Active in Production):
1. **Module Dịch Vụ AI Explainer ([`app/services/llm_service.py`](file:///d:/vn-travel-planner/app/services/llm_service.py))**:
   - **Lõi 1 (Primary Cloud)**: **Claude 4.6 Sonnet** (`claude-sonnet-4-6` qua VyceAI API tại `https://vyceai.com/v1/chat/completions` sử dụng `VYCEAI_API_KEY`).
   - **Lõi 2 (Local Fallback)**: **Ollama** (`vn-travel-qwen:7b` chạy tại `http://localhost:11434/api/chat`).
   - **Lõi 3 (Deterministic Heuristic Fallback)**: Cơ chế phòng thủ mẫu câu xác định khi mạng sập / timeout $\rightarrow$ Bảo đảm **Zero-Crash Resiliency (100% không vỡ app)**.
   - **Bộ đệm Tốc độ**: `_LLM_CACHE` in-memory LRU theo MD5 hash prompt.
2. **Nhiệm vụ AI Explainer Cụ thể Đã Nối Vào Hệ Thống**:
   - `explain_hotel_tradeoff()`: Chuyển hóa cự ly km và số phút di chuyển thành đoạn tư vấn tự nhiên, đề xuất rõ Phương án A (Đổi phòng gần hơn) vs Phương án B (Giữ phòng & dậy sớm).
   - `explain_roadtrip_tradeoff()`: Giải thích giới hạn mỏi mệt sinh học và tư vấn 3 phương án đánh đổi khi cự ly không khả thi.
3. **Cơ chế Gating Hiệu năng (Performance Guard)**:
   - Trong `POST /api/plan/calculate`: Tham số `include_ai_explanation: bool = False` (mặc định tắt gọi AI đồng bộ để giữ thời gian phản hồi API chuẩn $< 100\text{ms}$ khi warm cache). Khi client truyền `include_ai_explanation: true`, hệ thống mới kích hoạt làm giàu lời giải thích từ Claude 4.6.
4. **Công cụ Huấn luyện & Dữ liệu Ngoại vi (Offline AI Tooling)**:
   - Bộ dữ liệu hợp nhất chuẩn mực `data/train_nlu_master.jsonl` (937 mẫu câu toàn diện đã khử trùng lặp).
   - Google Colab Notebook huấn luyện Unsloth QLoRA 4-bit: `notebooks/train_qwen_v2_unsloth_colab.ipynb`.
   - File cấu hình Ollama: `Modelfile` và `Modelfile_v2`.

#### B. CHỈ LÀ KẾ HOẠCH (Planned Roadmap — Chưa Đưa Vào Production Runtime):
1. ❌ **[KẾ HOẠCH] End-to-End NLU Router tại API Gateway**:
   - *Hiện trạng code*: Request vào `/api/plan/calculate` nhận `prompt_keywords: List[str]` từ form giao diện và truy vấn trực tiếp bằng SQL xác định trên `travel_db.db`.
   - *Kế hoạch tương lai*: Xây dựng router NLU nhận thẳng một câu văn bản tự do của người dùng (ví dụ: *"2 đứa mình ở Bắc Ninh muốn đi Hội An bằng máy bay 3 ngày cuối tuần"*), tự động trích xuất thành Pydantic Schema (`origin="Bắc Ninh"`, `dest="Quảng Nam"`, `days=3`, `prefer_flight=True`) tại cổng API trước khi tính toán.
2. ❌ **[KẾ HOẠCH] Conversational Re-planner (Chatbot Đa Lượt Tương Tác)**:
   - *Hiện trạng code*: Hệ thống vận hành theo mô hình 1-shot (gửi yêu cầu $\to$ sinh toàn bộ lịch trình đa ngày).
   - *Kế hoạch tương lai*: Cho phép người dùng chat qua lại để tinh chỉnh lịch trình (ví dụ: *"Bỏ bớt đền chùa ở Ngày 2"*, *"Đổi bữa tối Ngày 1 sang quán hải sản"*).
3. ❌ **[KẾ HOẠCH] Function Calling Pipeline Tự Động (Gemini / OpenAI Agent)**:
   - *Kế hoạch tương lai*: Trao quyền cho LLM tự quyết định gọi các API công cụ con (weather, maps, geocoding) qua giao thức Function Calling chuẩn mực.

#### C. ĐẶC TẢ KẾT HỢP SONG HÀNH 2 MÔ HÌNH GGUF (DUAL-GGUF ENSEMBLE ARCHITECTURE):

Hệ thống sở hữu hai file trọng số GGUF đã được fine-tune chuyên biệt:
1. **Model V1 (`Qwen2.5-7B-Instruct.Q4_K_M.gguf` - 4.68 GB)**:
   - Cấu hình: `Modelfile` $\to$ Model name trong Ollama: `vn-travel-qwen:7b` (temperature = 0.1, top_p = 0.9).
   - Thế mạnh: Nắm bắt phổ rộng từ vựng du lịch, đàm thoại tự nhiên, giàu ngữ cảnh văn phong địa danh.
2. **Model V2 (`Qwen2.5-7B-Instruct-v2.Q4_K_M.gguf` - 4.68 GB)**:
   - Cấu hình: `Modelfile_v2` $\to$ Model name trong Ollama: `vn-travel-qwen-v2` (temperature = 0.0, top_p = 0.9).
   - Thế mạnh: Được huấn luyện trên tập đối kháng thuần `train_nlu_v2_pure.jsonl`, chuyên trị bài toán đảo ngữ (*"Tới Quảng Nam ... xuất phát từ Bắc Ninh"*), xử lý triệt để phủ định, trích xuất token tham chiếu (`CURRENT_LOCATION`), cam kết 0% biến dạng ngữ nghĩa (Zero Semantic Mutation) và trả JSON nghiêm ngặt theo khế ước (TC01 - TC10).

##### 2 Phương Án Kết Hợp (Combination Paradigms):
- **Phương án 1 (Kiến trúc Phần mềm: Dual-Model Cascade & Ensemble Consensus - Khuyên dùng chuẩn Top 0.1%)**:
  - **Tách bạch vai trò (Role Decoupling)**:
    - `vn-travel-qwen-v2`: Đóng vai trò **Semantic Invariant Parser** (Tầng bóc tách khế ước NLU đầu vào, trích xuất cấu trúc dữ liệu JSON để nạp vào Core Engine).
    - `vn-travel-qwen:7b`: Đóng vai trò **Domain Co-pilot & Advisory Explainer** (Tầng sinh lời giải thích tự nhiên cho các tình huống đánh đổi khách sạn, trạm dừng thể lực, hoặc thẩm định ý kiến thứ hai).
  - **Cơ chế Thác nước Phòng thủ (Cascade Failover)**:
    $$\text{Request} \xrightarrow{} \text{V2 (Strict Parser)} \xrightarrow[\text{nếu lỗi/lệch chuẩn}]{\text{fallback}} \text{V1 (Domain Parser)} \xrightarrow[\text{nếu lỗi/offline}]{\text{fallback}} \text{Claude 4.6} \xrightarrow[\text{mất mạng}]{\text{fallback}} \text{Deterministic Heuristic}$$
  - **Hội đồng Thẩm định Song hành (Ensemble Consensus)**:
    - Khi client yêu cầu độ tin cậy tuyệt đối: Cả V1 và V2 cùng trích xuất độc lập.
    - Nếu cả hai đồng thuận về `origin` và `destination` $\to$ Xác thực độ tin cậy 100% (High Confidence).
    - Nếu xảy ra phân kỳ (ví dụ ca đảo ngữ) $\to$ Quyền ưu tiên khế ước thuộc về V2 (dựa trên ma trận kiểm định đối kháng).
- **Phương án 2 (Trộn Trọng Số Ngoại Vi: Weight-Level Merging trước khi lượng tử hóa)**:
  - *Lưu ý kỹ thuật cốt lõi*: 2 file GGUF hiện tại đã ở định dạng lượng tử hóa khối 4-bit (`Q4_K_M`). Việc cộng trừ tensor trên các block int4 đã scale sẽ gây nhiễu lượng tử hóa và suy giảm chất lượng toán học.
  - *Quy trình chuẩn*: Sử dụng Google Colab notebook (`notebooks/train_qwen_v2_unsloth_colab.ipynb`), nạp lại trọng số unquantized base kèm 2 bộ LoRA adapter (`lora_v1` và `lora_v2`), áp dụng giải thuật nội suy trọng số (SLERP / TIES / DARE / Linear Interpolation: $W_{\text{merged}} = W_0 + \alpha \Delta W_{\text{v1}} + (1-\alpha) \Delta W_{\text{v2}}$), sau đó mới xuất xưởng thành 1 file GGUF thống nhất (`Qwen2.5-7B-Instruct-v3-merged.Q4_K_M.gguf`).

---

## 4. Bố Cục Thư Mục Tinh Gọn (Streamlined Repository Layout)

Sau khi dọn dẹp triệt để 71 file markdown tạm bợ và trùng lặp, cây thư mục tài liệu và mã nguồn chuẩn gồm:

```
d:\vn-travel-planner\
├── app/
│   ├── routers/
│   │   ├── planner_router.py       # API /api/plan/calculate, cache, tích hợp AI
│   │   └── map_router.py           # API /api/map/directions (Goong polyline proxy)
│   ├── services/
│   │   ├── travel_params.py        # NGUỒN SỰ THẬT DUY NHẤT (Single Source of Truth)
│   │   ├── travel_calculator.py    # 2-Opt TSPTW, nhịp sinh học, gom cụm đa ngày
│   │   ├── llm_service.py          # Claude 4.6 (Primary) + Ollama + Heuristic Fallback
│   │   ├── map_service.py          # Goong Directions, giải mã polyline, 2-tier cache
│   │   ├── road_trip_service.py    # Road Trip, giới hạn thể lực, 3 trade-offs
│   │   └── flight_transit_service.py # Gateway Airport Catchment & 3 chặng hàng không
│   ├── database.py                 # SQLite Engine
│   └── models.py                   # SQLAlchemy Models (Province, Ward, Place, Airport)
├── data/
│   ├── provinces_v2.json           # Dữ liệu 34 tỉnh và 3.321 xã phường
│   └── airports_vietnam.json       # Dữ liệu 22 sân bay dân dụng
├── docs/
│   ├── tsptw_specification.md      # Đặc tả kỹ thuật chuẩn 2-Opt & Hard Time-Window TSPTW
│   └── MODEL_ASSURANCE_MANIFESTO.md # Tuyên ngôn cam kết chất lượng kiểm thử
├── frontend/
│   └── index.html                  # Giao diện Leaflet vẽ đường uốn lượn Goong thực tế
├── tests/                          # 127 Test Cases đạt 100% Pass
│   ├── test_adversarial_resilience.py
│   ├── test_flight_transit.py
│   ├── test_road_trip_service.py
│   ├── test_tsptw_routing.py
│   └── test_single_source_and_advisories.py
├── travel_db.db                    # SQLite thực địa 1.369 địa danh & 22 sân bay
├── AGENTS.md                       # Bộ quy chuẩn quản trị tác tử kỹ sư Top 0.1%
├── PROJECT.md                      # Tài liệu tổng quan kiến trúc & hiện trạng (Tệp này)
├── PROJECT_CONTEXT.md              # Bối cảnh nghiệp vụ chi tiết & luật vận hành
├── README.md                       # Hướng dẫn khởi động & sử dụng ứng dụng
├── TEST_INFRA.md                   # Báo cáo hạ tầng & kết quả kiểm thử tự động
└── IMPLEMENTATION_STATUS.md        # Nhật ký tiến độ chi tiết từng giai đoạn
```
