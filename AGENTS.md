# TRAVEL AI - PROJECT RULES & AGENT GOVERNANCE

## 1. Mandatory Workflow for Coding Agents

Before modifying or creating any code, the AI Agent MUST strictly execute this pipeline:

```
TASK ASSIGNED
      │
      ▼
1. READ AGENTS.md & PROJECT_CONTEXT.md
      │
      ▼
2. INSPECT CURRENT IMPLEMENTATION
   (Check app/models.py, app/services/, app/routers/, travel_db.db)
      │
      ▼
3. CHECK EXISTING CAPABILITIES & PREVENT DUPLICATION
   (Never create duplicate files like hotelOptimizer.py if travel_calculator.py exists)
      │
      ▼
4. IMPACT ANALYSIS & STEP-BY-STEP PLAN
      │
      ▼
5. IMPLEMENT CODE (Preserve existing working functions)
      │
      ▼
6. EXECUTE TESTS ON REAL DATABASE (travel_db.db)
      │
      ▼
7. UPDATE IMPLEMENTATION_STATUS.md & REPORT
```

---

## 2. Architectural Boundaries & "Iron Laws"

### The Golden Rule: AI Sandwich Pattern
- **Top Layer (LLM Parser - NLU)**: Understand user intent, extract constraints (province, days, group size, vehicle, preferences).
- **Middle Layer (Deterministic Python Core Engine)**: Handles ALL calculations, routing, clustering, hotel distance evaluation, and financial sums.
- **Bottom Layer (LLM Explainer - NLG)**: Translates algorithmic decisions into friendly, contextual explanations (e.g., explaining why a hotel switch was recommended).

### Strict Negative Constraints:
- ❌ **LLM MUST NOT** directly calculate route distances or travel times in its head. (Must execute Haversine or matrix API).
- ❌ **LLM MUST NOT** decide hotel switching on pure intuition. (Must strictly follow distance threshold & cost evaluation).
- ❌ **LLM MUST NOT** calculate bill totals or split expenses mentally. (Must use deterministic math).
- ❌ **LLM MUST NOT** guess or invent coordinates, opening hours, or room prices. Ground truth must come from `travel_db.db`.
- ❌ **NEVER EXPOSE PAID API KEYS (Google Maps / Goong Maps)** in public frontend code. All third-party geocoding / autocomplete API calls with paid keys MUST route through a backend endpoint (`/api/...`) with in-memory caching to prevent quota exhaustion and credential leakage.
- ❌ **NEVER BREAK ZERO-ERROR GEOLOCATION**: Free client fallbacks (HTML5 Geolocation + IP reverse-geocoding via BigDataCloud/IPWhois) must always remain operational even if external Google API keys are missing or quota is exceeded.

---

## 3. Data Integrity & Pacing Rules

- **No Hallucinated Places**: Every location in an itinerary MUST exist in `travel_db.db`.
- **Missing Data Fallback**: When `typical_time_spent` or `price_range` is null in the database, use the explicit heuristic fallbacks defined in `PROJECT_CONTEXT.md`. NEVER invent random arbitrary numbers.
- **Human Travel Rhythm (Bắt buộc theo nhịp sinh học)**:
  $$\text{Tham quan sáng} \rightarrow \text{Ăn trưa} \rightarrow \text{Nghỉ trưa / Check-in} \rightarrow \text{Tham quan chiều} \rightarrow \text{Cà phê} \rightarrow \text{Ăn tối} \rightarrow \text{Chợ đêm / Nghỉ ngơi}$$
  Never schedule 4 temples or museums consecutively.

---

## 4. Hotel Switching Rules (Quy tắc đổi khách sạn)

- Do not recommend hotel changes for minor distance differences ($< 20\text{ km}$).
- Only trigger hotel switching alerts when distance between days is substantial ($\ge 30 - 40\text{ km}$) and travel time saved outweighs check-in/out inconvenience.
- In multi-day trips (3-5 days), cap hotel changes at 1-2 times maximum to avoid hotel-hopping fatigue.

---

## 5. Room & Expense Allocation Rules

- Group accommodation calculations must account for room capacity:
  $$\text{Số phòng} = \lceil \text{Số người} / 2 \rceil$$
  *(Ví dụ: 4 người = 2 phòng đôi, không được nhân đơn giá phòng x 4).*
- Transportation fuel/parking is shared across the entire group, not multiplied per person.
