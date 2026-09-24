# Hotel Optimization Skill

## Purpose
Evaluate whether the currently selected hotel for Day $N$ should be kept or switched for Day $N+1$, minimizing total inter-day travel distance without causing unnecessary hotel-hopping friction.

## Before Implementation
Inspect:
1. `app/models.py` for `Place` and `PlaceCategory.HOTEL`.
2. `app/services/travel_calculator.py` for `haversine_distance()`.
3. `travel_db.db` table `places` where `category = 'HOTEL'`.

## Algorithmic Rules
1. Calculate distance from Day $N$'s final destination ($E_N$) to current hotel ($H_{curr}$):
   $$d_1 = \text{haversine}(E_N, H_{curr})$$
2. Calculate distance from current hotel ($H_{curr}$) to Day $N+1$'s first destination ($S_{N+1}$):
   $$d_2 = \text{haversine}(H_{curr}, S_{N+1})$$
3. Compute total commute:
   $$D_{total} = d_1 + d_2$$
4. **Trigger Condition**:
   - If $d_2 \ge 30\text{ km}$ OR $D_{total} \ge 50\text{ km}$:
     - Query all candidate hotels $H_{cand}$ in the same province near $S_{N+1}$.
     - For each candidate, compute alternative commute:
       $$D_{cand} = \text{haversine}(E_N, H_{cand}) + \text{haversine}(H_{cand}, S_{N+1})$$
     - If $\Delta D = D_{total} - D_{cand} \ge 25\text{ km}$:
       - `should_switch = True`
       - Pick $H_{cand}$ with lowest distance and highest rating $\ge 4.0$.
5. **Friction Penalty Rule**:
   - Do NOT switch hotels if saved distance $< 20\text{ km}$. Check-in/check-out takes 1-2 hours and is not worth small distance gains.
   - Max 1 hotel switch for trips $\le 3$ days; max 2 switches for trips $\le 5$ days.

## Expected Output Schema
```json
{
  "day_index": 2,
  "current_hotel": { "id": 1, "name": "Grand Phoenix Hotel", "price": "$67 - $95" },
  "proposed_hotel": { "id": 8, "name": "Phoenix Resort Quế Võ", "price": "$20 - $54" },
  "should_switch": true,
  "distance_saved_km": 34.5,
  "estimated_time_saved_minutes": 65,
  "reason": "Khách sạn hiện tại cách điểm tham quan sáng Ngày 3 tới 38 km. Đổi sang Phoenix Resort giúp tiết kiệm 1h05 phút di chuyển."
}
```

## Testing Protocol
- Test with 2 spots within 5 km of hotel (must return `should_switch: false`).
- Test with Day 3 spot 40 km away (must return `should_switch: true` with valid candidate).
- Test when no alternative hotel exists in database (graceful fallback).
