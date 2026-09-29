# Project: VNTravel AI 63 Provinces Landmark Harvest & Enrichment

## Architecture
VNTravel AI landmark harvest system transforms raw tourism data across 63 historic provinces of Vietnam into a clean, authentic, and standardized dataset mapped to 34 planned administrative units, fully ingested into SQLite `travel_db.db` and `data/places_63_to_34.json`.

```
                    [ORIGINAL_REQUEST.md]
                              │
            ┌─────────────────┴─────────────────┐
            ▼                                   ▼
 [Implementation Track]                [E2E Testing Track]
  - M1: Sanitizer & Pipeline Engine     - Test Harness & Runner
  - M2: Miền Bắc (25 provinces)         - Tier 1: Province Coverage (63/63)
  - M3: Miền Trung (19 provinces)       - Tier 2: Category & GPS Bounds
  - M4: Miền Nam (19 provinces)         - Tier 3: Photo Authenticity & Deduplication
  - M5: Sync JSON & SQLite travel_db    - Tier 4: Real-world Trip Planning Queries
  - M6: Final Verification & Audit      └── Publishes TEST_READY.md
            │                                   │
            └─────────────────┬─────────────────┘
                              ▼
            [100% E2E Pass + Forensic Audit Clean]
```

## Feature Inventory
Every requirement from ORIGINAL_REQUEST.md and the Survey phase is mapped below:

| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1 | 63-to-34 Mapping Matrix | Complete alignment of 63 former provinces to 34 planned provinces matching `provinces_v2.json` | M1, M5 | RULES_63_PROVINCES_ENRICHMENT.md |
| F2 | Sanitize Out-of-Bounds & Foreign Entities | Eliminate 11 foreign entries (Hong Kong, Wuhan, Sichuan, Taiwan, Pacific) and distance anomalies | M1 | Survey Findings |
| F3 | SVG Map & Duplicate Photo Purge | Purge SVG maps, national locator maps, and duplicated stock photos from existing records | M1 | AGENTS.md, Survey |
| F4 | Miền Bắc Harvest & Enrichment | 25 northern provinces: ensure each has 15-30 typical places across 6 categories | M2 | ORIGINAL_REQUEST §R1 |
| F5 | Miền Trung & Tây Nguyên Harvest | 19 central/highland provinces: enrich deficient provinces (Bình Thuận, Ninh Thuận, Phú Yên, Quảng Nam) to >=15 | M3 | ORIGINAL_REQUEST §R1 |
| F6 | Miền Nam Harvest | 19 southern provinces: enrich deficient provinces (Đồng Nai, Bạc Liêu, Cà Mau, Hậu Giang, Vĩnh Long) to >=15 | M4 | ORIGINAL_REQUEST §R1 |
| F7 | 6 Core Categories Coverage | Ensure every province covers `HISTORICAL_SITE`, `TEMPLE`, `ATTRACTION`, `HOTEL`, `MARKET`, `SPECIALTY_FOOD` | M2, M3, M4 | ORIGINAL_REQUEST §R1 |
| F8 | Authentic Wikipedia Photo Harvest | Extract verified photos from Wikipedia REST/Action API with verified HTTP 200 URLs | M2, M3, M4 | ORIGINAL_REQUEST §R2 |
| F9 | Photo Coverage Threshold (>=60%-70%) | Overall dataset achieves >=60%-70% verified authentic photos, 100% unique per place | M5 | ORIGINAL_REQUEST §R2 |
| F10 | GPS Coordinate Validation | All coordinates within Vietnam bounding box [8.0, 23.5] lat, [102.0, 110.0] lng and province radius | M1, M5 | ORIGINAL_REQUEST §R2 |
| F11 | Missing Data Fallbacks | Implement biological pacing and price range fallbacks per `PROJECT_CONTEXT.md` | M1, M5 | PROJECT_CONTEXT.md |
| F12 | Standard JSON Dataset Sync | Clean output formatted to 20-field JSON schema in `data/places_63_to_34.json` | M5 | ORIGINAL_REQUEST §R3 |
| F13 | SQLite Database Sync | Ingest 100% of places into `travel_db.db` `places` table with `image_url` and `address` | M5 | ORIGINAL_REQUEST §R3 |
| F14 | verify_mapping.py Compatibility | Maintain 100% match with 34 provinces in DB and exit code 0 | M5, M6 | ORIGINAL_REQUEST §R3, verify_mapping.py |
| F15 | E2E Testing Suite & Audit | Pass 100% tests in E2E suite and pass forensic integrity audit | M6 | Orchestrator Protocol |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M0 | E2E Testing Suite | Comprehensive 4-tier test runner validating all 15 features, produces TEST_READY.md | none | IN_PROGRESS |
| M1 | Sanitizer & Harvesting Pipeline | Create sanitization filters, SVG blacklist, and Wikipedia enrichment pipeline | none | PLANNED |
| M2 | Miền Bắc Harvest (25 provinces) | Verify and enrich 25 Northern provinces (>=15 places, 6 categories, real photos) | M1 | PLANNED |
| M3 | Miền Trung & Tây Nguyên (19 prov) | Verify and enrich 19 Central/Highland provinces (enrich 4 deficient provinces) | M1 | PLANNED |
| M4 | Miền Nam Harvest (19 provinces) | Verify and enrich 19 Southern provinces (enrich 5 deficient provinces) | M1 | PLANNED |
| M5 | Deduplication & SQLite Ingestion | Consolidate `places_63_to_34.json`, deduplicate, sync into SQLite `travel_db.db` | M2, M3, M4 | PLANNED |
| M6 | Final E2E Pass & Forensic Audit | Run full test suite via Reviewer/Challenger and execute Forensic Integrity Audit | M0, M5 | PLANNED |

## Interface Contracts
### Raw Harvester Output ↔ Consolidation Engine
- Format: JSON array of place objects.
- Mandatory keys (20 fields):
  `id`, `name`, `category`, `original_province`, `original_province_code`, `target_province`, `target_province_code`, `target_ward_code`, `lat`, `lng`, `wiki_title`, `wiki_url`, `photo_url`, `is_must_visit`, `rating`, `review_count`, `price_range`, `prices`, `typical_time_spent`, `popular_times`.
- Constraints:
  - `lat`: float in [8.0, 23.5]
  - `lng`: float in [102.0, 110.0]
  - `photo_url`: string starting with `https://` (Wikimedia) or `null`. No duplicate URLs across places.
  - `target_province_code`: valid integer matching `provinces.code` in `travel_db.db`.

### JSON Dataset ↔ SQLite `travel_db.db`
- Table: `places`
- Field mappings:
  - `photo_url` -> `image_url`
  - `address`: synthesized from place `name`, `target_province` (e.g. `f"{name}, {target_province}, Việt Nam"`)
  - `province_code`: `target_province_code`
  - `ward_code`: `target_ward_code` (nullable)
  - `category`: `PlaceCategory` enum string

## Code Layout
- `scripts/verify_mapping.py`: Existing mapping verification script.
- `scripts/mapping_config.py`: Provincial mapping definitions and category fallbacks.
- `scripts/harvest_pipeline.py`: Modular enrichment, cleaning, and Wikipedia fetching tool.
- `scripts/sync_to_db.py`: Ingestion script from `places_63_to_34.json` into SQLite `travel_db.db`.
- `tests/test_e2e_places.py`: Comprehensive test runner covering Tiers 1-4.
- `data/places_63_to_34.json`: Standardized JSON dataset.
- `data/provinces_v2.json`: Master administrative reference (34 provinces, 3,321 wards).
- `travel_db.db`: Target SQLite database.
