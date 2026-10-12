# Quy Chuẩn Gán Nhãn Dataset NLU (Annotation Spec v5.2)

Tài liệu quy chuẩn gán nhãn chính thức cho NLU Dataset của VNTravel AI. Mọi generator dữ liệu phải tuân thủ nghiêm ngặt quy cách này.

## 1. Bảng Quy Định Gán Nhãn Theo Hiện Tượng Ngôn Ngữ

| Hiện tượng | Ví dụ | Trường | Giá trị |
| :--- | :--- | :--- | :--- |
| **Loại trừ địa danh** | Đi Đà Nẵng, trừ Bà Nà ra | `excluded_mentions` | `['Bà Nà']` |
| **Loại trừ tỉnh** | Đi miền Trung, né Huế ra | `excluded_mentions` | `['Huế']` |
| **Loại trừ hoạt động** | Lên Sa Pa nhưng không leo núi | `excluded_activities` | `['leo núi']` |
| **Loại trừ ăn uống** | Đi Cát Bà, không ăn hải sản | `excluded_activities` | `['ăn hải sản']` |
| **Không đi máy bay** | Hà Nội đi Đà Lạt, không đi máy bay | `prefer_flight` | `false` (`vehicle_type`: `null`) |
| **Trần ngân sách** | không quá 10 triệu | `budget_total_vnd` | `10000000` |
| **Không biết nên đi đâu** | Không biết nên đi Huế hay Đà Nẵng | `intent` | `clarify_needed` |
| **Thuộc tính vị trí** | Tìm khách sạn Nha Trang không gần biển | `preferences` | `['không gần biển']` |

---

## 2. Quy Tắc Bắt Buộc (Iron Rules)

1. **Chuẩn hóa giá trị loại trừ hoạt động (`excluded_activities`)**:
   - Bỏ toàn bộ từ phủ định ở đầu (ghi `'leo núi'`, KHÔNG ghi `'không leo núi'`), vì tên trường `excluded_activities` đã mang ngữ nghĩa loại trừ.

2. **Cờ máy bay (`prefer_flight`)**:
   - `true`: Người dùng chủ động yêu cầu đi máy bay (ví dụ: *"đi bằng máy bay"*, *"đặt vé bay"*).
   - `false`: Người dùng nói rõ KHÔNG đi máy bay (ví dụ: *"không đi máy bay"*, *"né máy bay"*). Lúc này `vehicle_type` để `null`.
   - `null`: Không nhắc tới máy bay.

3. **Chỉ chứa tên thực thể thuần túy (`destination_mention` & `origin_mention`)**:
   - Chỉ chứa **TÊN** địa danh. Tuyệt đối không chứa động từ, số ngày, phương tiện hay cụm từ thừa.
   - *Sai:* `'Phú Quốc bằng máy bay'`
   - *Đúng:* `'Phú Quốc'`

4. **Định danh vị trí hiện tại**:
   - Nếu người dùng nói *"từ đây"*, *"tại đây"*, *"vị trí hiện tại"*, *"chỗ mình đang đứng"*: `origin_mention = 'CURRENT_LOCATION'`.

5. **Giá trị khuyết thiếu (Missing slots)**:
   - Với mọi câu không đề cập đến một thông tin nào đó, trường tương ứng phải là `null` (đối với trường đơn) hoặc `[]` (đối với danh sách). Tuyệt đối không bịa đặt hoặc gán chuỗi rỗng `""`.

6. **Tính hợp lệ về địa lý**:
   - `destination_mention` và `origin_mention` không được cùng một đơn vị tỉnh/thành phố hành chính.
   - `destination_mention` không được nằm trong `excluded_mentions`.
