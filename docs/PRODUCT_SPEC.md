# PRODUCT SPEC: CHAT AI DU LỊCH (ĐĂNG NHẬP, HỎI LẠI, NÚT GỢI Ý, TỰ LÊN LỊCH)

*Tài liệu này dùng để giao việc cho agent code. Đặt tại `docs/PRODUCT_SPEC.md` làm Hợp đồng & Tiêu chuẩn phát triển.*

---

## 1. Cách giao việc cho agent (đọc trước)

Agent làm tốt khi có ba thứ: **bối cảnh** (sản phẩm là gì, đã có gì), **hợp đồng** (dữ liệu và API chính xác) và **tiêu chí nghiệm thu kiểm tra được** (test). Thiếu một trong ba, nó sẽ tự đoán.

Nguyên tắc khi giao:
1. **Bắt nó đọc repo trước khi viết code**, rồi tóm tắt lại những gì đã hiểu để bạn xác nhận. Đừng để nó giả định công nghệ (framework, DB, cách xác thực).
2. **Giao từng lát nhỏ chạy được** (ví dụ: chỉ lớp trạng thái hội thoại + test), không giao "làm cả tính năng chat".
3. **Yêu cầu kế hoạch trước, code sau**, mỗi lát một commit nhỏ.
4. **Không tin lời tự báo cáo.** Yêu cầu nó chạy test và dán kết quả thật. Bạn tự chạy lại lệnh kiểm tra.
5. **Cấm làm những việc ngoài phạm vi** (xem mục 11).

---

## 2. Sản phẩm là gì

Trợ lý du lịch Việt Nam. Người dùng gõ yêu cầu bằng tiếng Việt tự nhiên (*"du lịch miền núi phía bắc"*). Hệ thống:
1. Hiểu yêu cầu (NLU) và điền vào một **bản yêu cầu chuyến đi dạng JSON**.
2. Nếu thiếu **thông tin quan trọng**, hỏi lại và hiện **nút gợi ý (chips)**. Bấm nút thì ô tương ứng tự điền.
3. Khi đủ thông tin quan trọng, **tự lên lịch trình** và hiển thị.

Giao diện tham chiếu: khung chat dạng **aside** (bảng trượt bên cạnh): tin nhắn người dùng bên phải, tin nhắn bot bên trái, hàng nút "Gợi ý" bên dưới, ô nhập ở cuối.

---

## 3. Luồng người dùng (state machine)

```
[Trang web]
   │ bấm nút "Chat AI"
   ▼
 Đã đăng nhập? ── Không ──► Màn hình đăng nhập ──(thành công)──┐
   │ Có                                                          │
   ▼                                                             │
 Mở aside chat  ◄─────────────────────────────────────────────────┘
   │ (nếu có phiên đang dở của user này thì khôi phục)
   ▼
 Người dùng gõ câu hoặc bấm nút gợi ý
   ▼
 NLU trích slot  →  gộp vào bản yêu cầu
   ▼
 Thiếu slot QUAN TRỌNG? ── Có ──► Hỏi (tối đa 2 câu/lượt) + nút gợi ý ──┐
   │ Không                                                              │
   ▼                                                                    │
 Tự lên lịch trình → hiển thị ◄── (người dùng trả lời, quay lại trên) ──┘
```

### 3.1 Quy tắc đăng nhập
- Bấm Chat AI khi chưa đăng nhập: **chặn và chuyển tới đăng nhập**. Sau khi đăng nhập thành công, **quay lại đúng trang cũ và tự mở aside chat** (lưu ý "ý định mở chat" qua redirect).
- **Chặn ở cả backend**: mọi API chat bắt buộc xác thực. Chỉ ẩn nút ở frontend là chưa đủ an toàn. Chưa đăng nhập thì backend trả 401.
- Phiên chat gắn với user. Người dùng khác không đọc được phiên của nhau.
- Hết phiên đăng nhập giữa chừng: giữ lại tin nhắn đang gõ, yêu cầu đăng nhập lại, rồi gửi tiếp.

### 3.2 Đăng ký và đăng nhập (Bản tối giản, đã chốt)
Chỉ cần đăng ký bằng email rồi đăng nhập bình thường. Không xác minh email, không quên mật khẩu, không đăng nhập bằng Google, không phân quyền.
- **Bảng users**: `id`, `email` (duy nhất, lưu chữ thường), `password_hash`, `created_at`.
- **Đăng ký**: nhập email và mật khẩu, tạo tài khoản và đăng nhập luôn. Không gửi email, không bước kích hoạt.
- **Đăng nhập**: email và mật khẩu đúng thì cấp phiên đăng nhập.
- **Băm mật khẩu**: dùng thuật toán chuẩn (`bcrypt` hoặc `argon2`), tuyệt đối không lưu nguyên văn.
- **Kiểm tra tối thiểu**: email đúng định dạng, mật khẩu từ 8 ký tự, email chưa tồn tại. Sai đăng nhập báo chung: *"email hoặc mật khẩu không đúng"*.
- **Phiên đăng nhập**: cookie `httpOnly` hoặc token `Bearer` hợp với frontend hiện có. Thời hạn dài để người dùng ít phải đăng nhập lại.
- **Phụ thuộc dùng chung**: một hàm lấy user hiện tại (`get_current_user`), trả 401 nếu chưa đăng nhập. Mọi route chat đều dùng nó.
- **Endpoint**: `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/logout`.

---

## 4. Bản yêu cầu chuyến đi (JSON trung tâm)

Đây là "nguồn sự thật" của cuộc hội thoại. Chia hai nhóm: **quan trọng (critical)** và **bổ sung (extra)**.

```json
{
  "session_id": "uuid",
  "status": "collecting",
  "intent": "plan_itinerary",
  "critical": {
    "destination_mention": null,
    "origin_mention": null,
    "duration_days": null
  },
  "extra": {
    "group_size": null,
    "budget_total_vnd": null,
    "vehicle_type": null,
    "prefer_flight": null,
    "preferences": [],
    "pinned_mentions": [],
    "excluded_mentions": [],
    "excluded_activities": []
  },
  "hints": {
    "destination_regions": [],
    "terrain_types": []
  },
  "asked": [],
  "turn": 0
}
```

### 4.1 Ý nghĩa từng nhóm
| Nhóm | Vai trò | Khi null |
| --- | --- | --- |
| `critical` | Bắt buộc có đủ mới lên lịch được | Hỏi lại + nút gợi ý |
| `extra` | Làm lịch trình tốt hơn, nhưng không bắt buộc | Không chặn; dùng mặc định hoặc hỏi sau cùng |
| `hints` | Manh mối chưa đủ cụ thể (vùng, địa hình) | Dùng để sinh nút gợi ý điểm đến |

### 4.2 Danh sách slot quan trọng đề xuất
- `destination_mention`: điểm đến cụ thể. Chỉ có vùng hoặc địa hình ("miền núi phía bắc") chưa tính là đủ.
- `origin_mention`: nơi xuất phát. Cho phép giá trị đặc biệt `CURRENT_LOCATION` (từ vị trí hiện tại).
- `duration_days`: số ngày, số nguyên ≥ 1.

### 4.3 Quy ước cho ba trạng thái giá trị
- `null` hoặc `[]`: chưa nói.
- Có giá trị: người dùng đã nói (hoặc đã bấm nút).
- Với cờ như `prefer_flight`: `null` chưa nói, `true` muốn, `false` không muốn.

### 4.4 Trạng thái status
| status | Ý nghĩa |
| --- | --- |
| `collecting` | Đang thu thập, còn thiếu slot quan trọng |
| `ready` | Đủ slot quan trọng, sắp lên lịch |
| `planning` | Planner đang chạy ở nền, kèm mã tác vụ `plan_task_id` |
| `planned` | Đã có lịch trình |
| `error` | Lỗi, cần thử lại |

---

## 5. Cách NLU và JSON liên kết với nhau

NLU trả về JSON phẳng theo schema: `intent`, `destination_mention`, `destination_regions`, `terrain_types`, `excluded_mentions`, `origin_mention`, `duration_days`, `group_size`, `vehicle_type`, `budget_total_vnd`, `preferences`, `excluded_activities`, `pinned_mentions`, `prefer_flight`.

Lớp "gộp trạng thái" ánh xạ trường phẳng đó vào bản yêu cầu:
- `destination_mention`, `origin_mention`, `duration_days` $\rightarrow$ `critical`
- `group_size`, `budget_total_vnd`, `vehicle_type`, `prefer_flight`, `preferences`, `pinned_mentions`, `excluded_mentions`, `excluded_activities` $\rightarrow$ `extra`
- `destination_regions`, `terrain_types` $\rightarrow$ `hints`

**Quy tắc gộp:**
1. Slot mới có giá trị thì ghi vào. Slot mới là `null` hoặc `[]` thì **không** ghi đè giá trị cũ.
2. Người dùng đổi ý ("thôi đi Sa Pa") thì giá trị mới ghi đè giá trị cũ.
3. Danh sách (`excluded_mentions`, `pinned_mentions`, `preferences`) gộp và loại trùng.
4. Nếu `destination_mention` đã có thì xóa `hints.destination_regions` và `hints.terrain_types`.
5. Mô hình NLU không sinh câu hỏi. Câu hỏi do code đọc từ file cấu hình (mục 6).

---

## 6. File cấu hình luật hỏi lại

Đặt tại `config/dialogue.json`:
```json
{
  "max_questions_per_turn": 2,
  "critical_slots": [
    {
      "slot": "destination_mention",
      "ask": "Quý khách muốn đi điểm cụ thể nào{region_suffix}?",
      "suggest": {"source": "gazetteer_by_hints", "limit": 6}
    },
    {
      "slot": "origin_mention",
      "ask": "Quý khách dự định khởi hành từ tỉnh/thành nào?",
      "suggest": {"source": "popular_origins", "include_current_location": true, "limit": 5}
    },
    {
      "slot": "duration_days",
      "ask": "Quý khách dự định đi mấy ngày?",
      "suggest": {"source": "static", "values": [1, 2, 3, 4, 5]}
    }
  ],
  "extra_slots": [
    {"slot": "group_size", "default": 2},
    {"slot": "budget_total_vnd", "default": null}
  ],
  "after_ready": "auto_plan"
}
```

---

## 7. Nút gợi ý (chip) và cơ chế tự điền

### 7.1 Cấu trúc chip
```json
{
  "id": "chip_dest_sapa",
  "label": "Sa Pa",
  "slot": "destination_mention",
  "value": "Sa Pa"
}
```

### 7.2 Hành vi khi bấm
1. Frontend gửi sự kiện chip: `{"type": "chip", "slot": "destination_mention", "value": "Sa Pa"}`.
2. Backend ghi thẳng giá trị vào slot, **không gọi NLU**.
3. Chạy lại logic "còn thiếu gì" và trả về câu hỏi hoặc trạng thái tiếp theo.
4. Giao diện hiện lựa chọn của người dùng như một tin nhắn để tự nhiên.

### 7.3 Nguồn gợi ý
- Điểm đến: từ gazetteer theo `hints`. Sắp xếp ổn định (`ORDER BY`).
- Điểm xuất phát: các thành phố lớn + `CURRENT_LOCATION`.
- Số ngày: danh sách cố định [1, 2, 3, 4, 5].

---

## 8. Hợp đồng API & Lưu phiên

Mọi endpoint chat yêu cầu đăng nhập. Đăng ký/đăng nhập là công khai.

| Endpoint | Mục đích |
| --- | --- |
| `POST /api/chat/sessions` | Tạo phiên mới hoặc trả phiên đang dở của user |
| `GET /api/chat/sessions/{id}` | Lấy bản yêu cầu và lịch sử để khôi phục aside |
| `POST /api/chat/sessions/{id}/messages` | Gửi tin nhắn hoặc sự kiện chip |
| `POST /api/auth/register` | Đăng ký bằng email và mật khẩu |
| `POST /api/auth/login` | Đăng nhập |
| `GET /api/auth/me` | Lấy user hiện tại |
| `POST /api/auth/logout` | Đăng xuất |

Khi đủ slot quan trọng, backend trả ngay `status: "planning"` kèm `plan_task_id`, không chờ planner chạy xong đồng bộ.

### 8.1 Lưu phiên chat (SQLite riêng)
- Dùng file SQLite riêng (`chat_state.db`) để không khóa `travel_db.db` khi ghi.
- Bảng `chat_sessions`: `id`, `user_id`, `status`, `trip_request` (JSON), `updated_at`.
- Bảng `chat_messages`: `id`, `session_id`, `role`, `content`, `created_at`.
- Mỗi user có tối đa một phiên đang dở. Mở lại aside khôi phục phiên đó.

---

## 9. Lên lịch trình tự động (Planner Adapter)

- Không viết planner mới. Tận dụng `travel_calculator.py` và `planner_router.py` có sẵn.
- Adapter chuyển bản yêu cầu thành request cho planner hiện có.
- Chạy nền bất đồng bộ: trả `planning` + `plan_task_id`, dùng SSE/polling có sẵn.
- **Ràng buộc bắt buộc**: loại trừ `excluded_mentions`, `excluded_activities`; bao gồm `pinned_mentions`; đúng `duration_days`; điểm đến và điểm xuất phát phân giải qua gazetteer.

---

## 10. Trường hợp biên & Phân giải thực thể

- **Phân giải thực thể (Entity Resolution - Bắt buộc)**: Địa danh thô ("chùa Hương", "Tràng An", "Hội An") phải qua gazetteer để ra: mã chuẩn, cấp (tỉnh, huyện hay điểm tham quan), mã tỉnh chứa nó và tọa độ.
- Chùa Hương xuất phát từ Hà Nội: không coi là trùng vì chùa Hương là điểm tham quan cụ thể.
- Điểm đến và xuất phát trùng cùng một thực thể: báo và hỏi lại.
- Trả lời một mẩu ("từ Hà Nội", "3 ngày"): điền đúng slot đang được hỏi.
- Người dùng đổi ý: giá trị mới ghi đè cũ.
- Hỏi ≥ 3 lượt mà vẫn thiếu: đưa ra giá trị mặc định và gợi ý sơ bộ.

---

## 11. Ràng buộc & Tiêu chí nghiệm thu

Tuân thủ nghiêm ngặt theo các kịch bản Given / When / Then ở Mục 12 và thứ tự triển khai từng lát tại Mục 13 của Đặc tả dự án.
