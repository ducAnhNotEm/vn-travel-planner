# 🛡️ MODEL ASSURANCE & SEMANTIC CONTRACT MANIFESTO
## Định Nghĩa Ranh Giới: Semantic Parser vs Decision Maker (Top 0.01% Standard)

> **TÔN CHỈ TỐI CAO:**  
> **"Qwen 7B được thiết kế và kiểm thử với vai trò duy nhất là một SEMANTIC PARSER, tuyệt đối KHÔNG PHẢI là một Decision Maker."**  
> NLU chỉ chuyển đổi phát ngôn tự nhiên của người dùng thành biểu diễn dữ liệu có khế ước rõ ràng (Structured Representation), không tự ý thay đổi sự thật, không thực thi business logic và không đoán mò những dữ liệu mà hệ thống có nguồn sự thật tốt hơn.

---

## 1. 3 TẦNG KIỂM CHỨNG HỆ THỐNG (THE 3 TIERS OF VERIFICATION)

Trong một hệ thống Machine Learning Production nghiêm túc:
1. **Tầng A — Cú pháp (Syntactic Correctness):** JSON hợp lệ, đúng schema Pydantic. *(Điều kiện cần, mức độ sơ đẳng).*
2. **Tầng B — Ngữ nghĩa (Semantic Correctness):** Đo bằng **Contract Violation Rate** và **Field-Level Semantic Accuracy** trên các cặp đối nghịch tối thiểu (Minimal Pairs / Counterfactuals). *(Bảo đảm hành vi NLU).*
3. **Tầng C — Toàn hệ thống (System Correctness):** Sự phối hợp giữa Context Resolver, Requirement Validator, Constraint Engine và Routing Planner. *(Bảo đảm trải nghiệm người dùng cuối).*

---

## 2. 7 ĐỊNH LUẬT BẤT BIẾN (THE 7 INVARIANTS)

```
                            PIPELINE KIẾN TRÚC THỰC THI
                                         │
                                         ▼
                           ┌───────────────────────────┐
                           │       USER REQUEST        │
                           └─────────────┬─────────────┘
                                         │
                                         ▼
                           ┌───────────────────────────┐
                           │   QWEN 7B SEMANTIC PARSER │
                           │  (Extract facts & tokens) │
                           └─────────────┬─────────────┘
                                         │
                ┌────────────────────────┼────────────────────────┐
                ▼                        ▼                        ▼
          [USER FACTS]           [REFERENCE TOKEN]         [USER INTENT]
      group_size: 16             origin: "CURRENT_LOCATION" intent: "plan_itinerary"
      vehicle_type: "car"        prefer_flight: null       (Tách biệt hoàn toàn
      (Không sửa thành van)     (Không ép true/false)      với slot completeness)
                │                        │                        │
                └────────────────────────┼────────────────────────┘
                                         ▼
                           ┌───────────────────────────┐
                           │     CONTEXT RESOLVER      │
                           │ Phân giải CURRENT_LOCATION│
                           │ sang GPS thực của Client  │
                           └─────────────┬─────────────┘
                                         │
                                         ▼
                           ┌───────────────────────────┐
                           │   REQUIREMENT VALIDATOR   │
                           │  Kiểm tra Critical Slots: │
                           │  Nếu thiếu -> Hỏi lại     │
                           └─────────────┬─────────────┘
                                         │
                                         ▼
                           ┌───────────────────────────┐
                           │     CONSTRAINT ENGINE     │
                           │  16 người + car -> Lỗi tải│
                           │  Tự động nâng hạng xe van │
                           └─────────────┬─────────────┘
                                         │
                                         ▼
                           ┌───────────────────────────┐
                           │    DETERMINISTIC ROUTE    │
                           │      & TRIP PLANNER       │
                           └───────────────────────────┘
```

1. **Rule 1 (Zero Semantic Mutation):**  
   NLU ghi nhận nguyên văn sự thật. User nói *"16 người đi ô tô"* $\to$ NLU trả về `group_size: 16`, `vehicle_type: "car"`. Việc xe 4 chỗ không chở được 16 người thuộc thẩm quyền của **Constraint Engine** sau đó.
2. **Rule 2 (`null` là Không có dữ liệu, KHÔNG PHẢI "Hệ thống tự quyết"):**  
   `prefer_flight: null` chỉ có nghĩa là *User không đưa ra quyết định bay*. Backend không được tự động coi đó là "cho phép tự chọn".
3. **Rule 3 (Intent $\neq$ Completeness):**  
   Câu *"Lên tour Đà Nẵng 3 ngày"* có intent rõ ràng là `plan_itinerary`. Việc nó thiếu `origin` hay `group_size` thuộc trách nhiệm của **Requirement Validator**, NLU không được phép hạ cấp intent thành `clarify_needed`.
4. **Rule 4 (`CURRENT_LOCATION` là Reference Token):**  
   Khi user nói *"từ chỗ tôi"*, *"từ đây"*, NLU trả về token `"CURRENT_LOCATION"`. Context Resolver sẽ chịu trách nhiệm phân giải token này ra toạ độ GPS.
5. **Rule 5 (Business Defaults nằm ngoài NLU):**  
   Qwen không biết và không quan tâm `default_group_size = 2` hay `default_days = 2`. Qwen chỉ trả về `null`.
6. **Rule 6 (Conditional Request $\neq$ Preference):**  
   Câu *"Nếu có hoa tam giác mạch thì đi Hà Giang"* là một điều kiện (Condition). Qwen không được "giả vờ hỗ trợ" bằng cách nhét bừa vào `preferences: ["hoa tam giác mạch"]`.
7. **Rule 7 (Adversarial Minimal Pairs Benchmark):**  
   Tính toàn vẹn của mô hình được kiểm chứng bằng ma trận cấm kỵ (`forbidden_inferences`) và các cặp đối nghịch tối thiểu (**Minimal Pairs** & **Counterfactual Pairs**).

---

## 3. HỆ THỐNG ĐÁNH GIÁ TỰ ĐỘNG (ASSURANCE BENCHMARK)

- 🧪 **Pytest Harness:** [`tests/test_semantic_nlu_benchmarks.py`](file:///d:/vn-travel-planner/tests/test_semantic_nlu_benchmarks.py)
- 🚀 **Ollama Evaluation Runner:** [`test_gguf_v2.py`](file:///d:/vn-travel-planner/test_gguf_v2.py)
- 📂 **Unified Master Benchmark Dataset:** [`data/train_nlu_master.jsonl`](file:///d:/vn-travel-planner/data/train_nlu_master.jsonl)

---

## 4. CHIẾN LƯỢC KIỂM ĐỊNH & KẾT HỢP SONG HÀNH 2 MÔ HÌNH GGUF (DUAL-GGUF ENSEMBLE SPECIFICATION)

Nhằm tối ưu hóa năng lực toàn diện, hệ thống travel AI kết hợp hai mô hình trọng số GGUF với ranh giới trách nhiệm rõ ràng:

| Đặc tính / Vai trò | Mô hình V1 (`vn-travel-qwen:7b`) | Mô hình V2 (`vn-travel-qwen-v2`) |
|---|---|---|
| **Trọng số GGUF** | `Qwen2.5-7B-Instruct.Q4_K_M.gguf` | `Qwen2.5-7B-Instruct-v2.Q4_K_M.gguf` |
| **Nhiệt độ (Temperature)** | `0.1` | `0.0` (Thuần xác định) |
| **Vai trò Trọng tâm** | **Domain Reasoner & Advisory Explainer** | **Strict Semantic Invariant Parser** |
| **Khả năng chịu tải đối kháng** | Khái quát ngữ cảnh rộng, đối thoại du lịch | Vượt qua 10/10 ca đối kháng khế ước (TC01-TC10) |
| **Xử lý Đảo ngữ & Phủ định** | Khả năng trung bình | **Khả năng tuyệt đối (100% chuẩn xác)** |
| **Xử lý Token Tham chiếu** | Có thể bị suy diễn vị trí mặc định | Trả chính xác `"CURRENT_LOCATION"` |

### 4.1. Cơ Chế Điều Phối Song Hành (Ensemble & Consensus Protocol):
1. **Pha 1 — Bóc tách khế ước (Strict Parsing Phase)**:
   - Request người dùng luôn được định tuyến trước tiên tới **Model V2** (`temperature=0.0`).
   - Kiểm tra tính toàn vẹn của JSON đầu ra và kiểm định vi phạm khế ước (`ContractViolationCheck`).
2. **Pha 2 — Thẩm định phân kỳ & Bỏ phiếu (Consensus Verification)**:
   - Với các câu phức hợp nhiều mệnh đề hoặc có từ khóa mơ hồ, **Model V1** được gọi song song để đối soát.
   - Nếu cả V1 và V2 cùng cho ra `origin` và `destination` đồng thuận $\to$ Đánh dấu độ tin cậy tuyệt đối (`confidence = 1.0`).
   - Nếu có sự phân kỳ giữa V1 và V2 $\to$ Quyền phán quyết thực thể (Slot Extraction) thuộc về V2; quyền giải thích và gợi ý mở rộng thuộc về V1.
3. **Pha 3 — Thuyết minh & Sinh giải pháp (Advisory Explanation Phase)**:
   - Sau khi Deterministic Engine (TSPTW & Goong Polyline) giải xong bài toán lộ trình, **Model V1** được ưu tiên huy động để sinh văn phong tư vấn tự nhiên, thân thiện và giàu cảm xúc cho người dùng cuối.
