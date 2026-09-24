# IMPLEMENTATION STATUS

*Last Updated: 2026-09-25*

## 1. Database & Ground Truth Data
- [x] Schema initialized (`provinces`, `wards`, `places` tables).
- [x] Ingested 34 Provinces and Wards (`data/provinces_v2.json`).
- [x] Extended `places` schema with `price_range` (String) and `prices` (JSON).
- [x] Ingested 20 initial places for Bắc Ninh (5 Restaurants, 5 Hotels, 5 Temples, 5 Markets).
- [x] Populated real Google Places multi-provider pricing for Hotels in `places`.
- [ ] Ingest remaining 33 provinces (batch crawl Google Places / Mock datasets).
- [ ] Parse & structure `working_hours` into `[open_time, close_time]` intervals.

---

## 2. Planning Engine & Algorithms
- [x] Haversine GPS distance formula (`app/services/travel_calculator.py`).
- [x] Single-day Nearest Neighbor route sequencing (TSP).
- [x] Transportation cost calculator for 4 modes (`car`, `bus`, `taxi`, `motorbike`).
- [x] Dynamic database price formatting (Hotels with real rates, Free temples/markets).
- [ ] Multi-day Geographic Clustering (K-Means / DBSCAN / Distance-based density).
- [ ] Human biological pacing time-slot allocation (Morning, Lunch, Midday rest, Afternoon, Dinner, Night).
- [ ] Gap-filling engine (Auto-recommend nearby dining/cafes when days > user picks).
- [ ] Inter-day Hotel Switching Evaluator ($\ge 30-40\text{ km}$ threshold alert).
- [ ] Group accommodation math ($\lceil \text{group size} / 2 \rceil$ rooms) & Bill splitter.

---

## 3. AI Layer (LLM NLU & Explainer)
- [x] Core AI prompt matcher prototype in `travel_calculator.py`.
- [ ] LLM Function Calling pipeline (Gemini / OpenAI API adapter).
- [ ] Natural Language Intent Parser (extracting constraints from user text).
- [ ] Natural Language Explainer (explaining hotel switches, route trade-offs, and pacing).
- [ ] Conversational Re-planner (adjusting schedule on the fly based on user chat).

---

## 4. API & Integration
- [x] FastAPI base application (`app/main.py`).
- [x] API Endpoint `POST /api/plan/calculate` (`app/routers/planner_router.py`).
- [ ] API Endpoint `POST /api/plan/ai-generate` (LLM prompt-to-itinerary).
- [ ] API Endpoint `POST /api/plan/switch-hotel` (Hotel evaluation & replacement).
- [ ] Backend Google Places / Geocoding Proxy (`app/routers/places_router.py`) with API key masking & LRU cache.
- [ ] Database Enrichment crawler via Google Places Details API (operating hours, review counts, photos).

---

## 5. Frontend & UI
- [x] Google Stitch production-grade Master Prompt drafted with 6-step User Flow.
- [x] Created complete interactive desktop-first frontend application (`frontend/index.html`).
- [x] Implemented 5 functional screens (Home, Trip Planner, Itinerary with Human Rhythm, Place Details, Explore).
- [x] Integrated Deep Blue (`#0F294D`) & Warm Orange (`#FF5E1F`) Traveloka-style visual identity.
- [x] Configured FastAPI (`app/main.py`) to serve the frontend directly at `http://localhost:8000/`.
- [x] Multi-tiered Hybrid Geolocation (Hardware GPS with 3.5s timeout + silent BigDataCloud & IPWhois fallback for Desktop/Ethernet without GPS).
- [x] Interactive reactive selection effects for Vehicle Cards & Must-visit Places grid with real-time dynamic counters.
- [ ] Google Places Autocomplete search dropdown on `#start-location-input` with session token optimization.

