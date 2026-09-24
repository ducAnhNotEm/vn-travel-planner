# Cost Calculation & Expense Splitting Skill

## Purpose
Deterministically calculate the complete itemized cost of a travel plan and compute fair expense-sharing per traveler.

## Calculation Formula

$$\text{Total Cost} = C_{hotel} + C_{dining} + C_{transit} + C_{tickets} + C_{contingency}$$

### 1. Accommodation ($C_{hotel}$)
- Number of rooms required:
  $$N_{rooms} = \lceil \text{group size} / 2 \rceil$$
  *(Ví dụ: 3 người = 2 phòng, 4 người = 2 phòng, 5 người = 3 phòng).*
- Rate per room: Extracted from `places.prices` or `places.price_range` in DB.

### 2. Dining ($C_{dining}$)
- Number of meals = $\text{Days} \times 2$ (Lunch + Dinner).
- Rate per meal: From DB restaurant average, or regional standard estimate ($150.000\text{đ} / \text{người} / \text{bữa}$).
- $$C_{dining} = \text{Meals} \times \text{Group size} \times \text{Rate per meal}$$

### 3. Transportation ($C_{transit}$)
Calculated strictly based on selected vehicle and total itinerary distance:
- **Private Car (`car`)**: $(\text{Total km} \times 1.800\text{đ}) + (\text{Days} \times 30.000\text{đ parking})$.
- **Thuê xe du lịch riêng (`chartered_van`)**: $1.000.000\text{đ base} + (\text{Total km} \times 2.500\text{đ})$ trọn gói cả xe (chia đều cho cả nhóm).
- **Taxi (`taxi`)**: $12.000\text{đ} + (\text{Total km} \times 14.000\text{đ})$.
- **Motorbike (`motorbike`)**: $(\text{Total km} \times 600\text{đ}) + (\text{Days} \times 10.000\text{đ parking})$.


### 4. Tickets ($C_{tickets}$)
- Temples, pagodas, public markets: **0 VND / Free Entry**.
- Special paid attractions: Read from DB if available.

### 5. Group Expense Splitting
- Cost per person:
  $$\text{Per person} = \frac{\text{Total Cost}}{\text{Group size}}$$
- Ledger algorithm: Compare $(\text{Paid by Person } X) - \text{Per person share}$ to compute debt reconciliation.
