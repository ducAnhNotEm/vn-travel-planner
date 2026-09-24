# Itinerary Planning Skill (Human Rhythm & Time Slots)

## Purpose
Assemble selected and gap-filled destinations into a structured, chronologically sound daily schedule following human biological pacing.

## Biological Pacing Rules (Nhịp sống thật)
Each day must be divided into strictly ordered operational slots:

| Time Slot | Primary Function | Accepted Categories | Default Duration |
| :--- | :--- | :--- | :--- |
| **08:00 - 11:30** | Sáng: Tham quan / Năng lượng cao | `TEMPLE`, `HISTORICAL_SITE`, `ATTRACTION` | 1h30m - 2h00m |
| **11:30 - 13:00** | Trưa: Ẩm thực / Nạp năng lượng | `RESTAURANT`, `SEAFOOD_RESTAURANT`, `SPECIALTY_FOOD` | 1h15m |
| **13:00 - 14:45** | Nghỉ trưa / Check-in khách sạn | `HOTEL`, `CAFE` (nếu không về KS) | 1h45m |
| **15:00 - 17:30** | Chiều: Tham quan văn hóa / Check-in nhẹ | `ATTRACTION`, `TEMPLE`, `MARKET` | 1h30m - 2h00m |
| **17:30 - 18:30** | Chiều tối: Cà phê ngắm hoàng hôn | `CAFE`, `ATTRACTION` | 45m - 1h00m |
| **18:30 - 20:00** | Tối: Ăn tối đặc sản | `RESTAURANT`, `SPECIALTY_FOOD` | 1h30m |
| **20:00 - 22:00** | Đêm: Chợ đêm / Dạo phố / Nghỉ | `MARKET`, `HOTEL` | 1h30m |

## Negative Constraints
- ❌ NEVER schedule 3 consecutive sightseeing stops without lunch/rest in between.
- ❌ NEVER schedule lunch before 11:00 or after 14:00.
- ❌ NEVER schedule dinner before 17:30 or after 21:30.
- ❌ Do not send travelers to closed destinations (cross-check `working_hours` if available).

## Gap-Filling Logic
If user selects only $K$ spots for an $M$-day trip, and $K < M \times 2$:
1. Identify vacant time slots for each day.
2. If Lunch/Dinner slot is empty $\rightarrow$ Query nearest `RESTAURANT` within 10 km.
3. If Midday slot is empty $\rightarrow$ Slot current `HOTEL` or nearest `CAFE`.
4. If Afternoon slot is empty $\rightarrow$ Query nearest unvisited `TEMPLE` / `ATTRACTION` with rating $\ge 4.0$.
