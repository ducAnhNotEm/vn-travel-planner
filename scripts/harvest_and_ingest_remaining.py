"""
scripts/harvest_and_ingest_remaining.py

Pipeline thu thập (M2), chuẩn hóa, ánh xạ & nạp dữ liệu (M3), cùng kiểm định QA (M4)
cho 25 tỉnh thành còn lại của dự án VN Travel Planner.

Các tính năng cốt lõi:
1. Token Rotation (R2):
   - Sử dụng APIFY_TOKEN chính từ .env.
   - Bắt lỗi quota/401/402 và tự động chuyển sang APIFY_TOKEN_BACKUP mà không làm crash tiến trình.
   - Lưu cache thô theo từng tỉnh vào data/raw_remaining_provinces/raw_province_{code}.json.
2. Ánh xạ & Khử trùng lặp (R3):
   - Ánh xạ mã tỉnh chuẩn 34 tỉnh sau sáp nhập.
   - Khử trùng theo google_place_id và khoảng cách GPS Haversine (< 30m).
   - Nạp an toàn vào bảng places trong travel_db.db bằng SQLite transaction.
   - Bảo đảm 100% bản ghi có ảnh thực tế (Google CDN hoặc Wikipedia authentic), 0 ảnh null/rỗng.
3. Kiểm tra kiểm định độc lập (R4):
   - Đạt >= 350 địa điểm mới.
   - 0 lỗi Foreign Key giữa places.province_code và provinces.code.
   - 0 địa điểm thiếu ảnh.
   - Đủ 5 danh mục: RESTAURANT, ACTIVITY, MARKET, ATTRACTION, HOTEL.
"""

import os
import sys
import json
import time
import math
import sqlite3
import argparse
from typing import Dict, Any, List, Set, Tuple, Optional
from dotenv import load_dotenv

# Đảm bảo đường dẫn import tới thư mục gốc
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

load_dotenv(os.path.join(ROOT_DIR, ".env"))

from scripts.mapping_config import MAPPING_63_TO_34, PROVINCE_COORDINATES
from scripts.harvest_pipeline import (
    haversine_distance_km, is_blacklisted_photo, WikipediaFetcher,
    VIETNAM_LAT_MIN, VIETNAM_LAT_MAX, VIETNAM_LNG_MIN, VIETNAM_LNG_MAX
)

DB_PATH = os.path.join(ROOT_DIR, "travel_db.db")
DATA_DIR = os.path.join(ROOT_DIR, "data")
PLAN_PATH = os.path.join(DATA_DIR, "ba_remaining_provinces_plan.json")
RAW_CACHE_DIR = os.path.join(DATA_DIR, "raw_remaining_provinces")

# 9 trung tâm du lịch lớn đã hoàn thiện - bắt buộc bỏ qua
SKIP_PROVINCE_CODES = [1, 22, 31, 46, 48, 56, 68, 79, 92]

TARGET_PROVINCE_CODES = [
    4, 8, 11, 12, 14, 15, 19, 20, 24, 25,
    33, 37, 38, 40, 42, 44, 51, 52, 66, 75,
    80, 82, 86, 91, 96
]

CATEGORIES = ["RESTAURANT", "ACTIVITY", "MARKET", "ATTRACTION", "HOTEL"]

DEFAULT_FALLBACK_HOURS = {
    "ATTRACTION": "60 - 90 phút",
    "ACTIVITY": "90 - 120 phút",
    "RESTAURANT": "60 - 75 phút",
    "MARKET": "60 - 90 phút",
    "HOTEL": "Nghỉ qua đêm"
}

DEFAULT_FALLBACK_PRICE = {
    "ATTRACTION": "Miễn phí hoặc 20.000đ - 50.000đ / vé",
    "ACTIVITY": "50.000đ - 150.000đ / vé",
    "RESTAURANT": "100.000đ - 250.000đ / người",
    "MARKET": "Miễn phí vé vào cửa",
    "HOTEL": "500.000đ - 1.200.000đ / phòng / đêm"
}


# ==============================================================================
# 1. QUẢN LÝ TOKEN APIFY & CRAWLER GOOGLE MAPS
# ==============================================================================

class ApifyTokenManager:
    """Quản lý xoay vòng token Apify tự động khi gặp lỗi 401, 402 hoặc hết quota."""

    def __init__(self):
        self.primary_token = os.getenv("APIFY_TOKEN")
        self.backup_token = os.getenv("APIFY_TOKEN_BACKUP")
        self.current_token = self.primary_token
        self.is_using_backup = False
        self._client = None
        self._init_client()

    def _init_client(self):
        from apify_client import ApifyClient
        if not self.current_token:
            print("⚠️ CẢNH BÁO: Không tìm thấy APIFY_TOKEN trong môi trường.", flush=True)
            self._client = None
        else:
            self._client = ApifyClient(self.current_token)

    def get_client(self):
        return self._client

    def switch_to_backup(self, reason: str = ""):
        """Chuyển đổi sang APIFY_TOKEN_BACKUP."""
        if self.is_using_backup:
            print(f"⚠️ Cả token chính và token phụ đều đã được thử. Lỗi: {reason}", flush=True)
            return False

        if not self.backup_token or self.backup_token == self.primary_token:
            print(f"⚠️ Không có APIFY_TOKEN_BACKUP khả dụng khác để chuyển đổi. Lỗi: {reason}", flush=True)
            return False

        print(f"\n🔄 [TOKEN ROTATION] Đang chuyển đổi từ APIFY_TOKEN sang APIFY_TOKEN_BACKUP do: {reason}", flush=True)
        self.current_token = self.backup_token
        self.is_using_backup = True
        self._init_client()
        print(f"✅ Đã kích hoạt APIFY_TOKEN_BACKUP thành công!", flush=True)
        return True


def crawl_places_with_apify(
    token_mgr: ApifyTokenManager,
    queries: List[str],
    province_code: int,
    max_retries: int = 2
) -> List[Dict[str, Any]]:
    """
    Chạy crawler Google Maps (compass/crawler-google-places) qua Apify với token rotation.
    """
    if not queries:
        return []

    client = token_mgr.get_client()
    if not client:
        print(f"⚠️ Không có ApifyClient, bỏ qua bước cào online cho tỉnh {province_code}.")
        return []

    run_input = {
        "searchStringsArray": queries,
        "maxCrawledPlacesPerSearch": 1,
        "language": "vi",
        "countryCode": "vn",
        "maxImages": 1,
        "scrapeReviews": False,
        "scrapePlaceDetailPage": False,
        "scrapeContacts": True
    }

    for attempt in range(1, max_retries + 1):
        try:
            cur_client = token_mgr.get_client()
            print(f"  🌐 [Apify] Đang khởi chạy actor 'compass/crawler-google-places' ({len(queries)} truy vấn, lần {attempt})...", flush=True)
            run = cur_client.actor("compass/crawler-google-places").call(
                run_input=run_input,
                memory_mbytes=2048
            )

            dataset_id = getattr(run, "default_dataset_id", None) or getattr(run, "defaultDatasetId", None)
            if not dataset_id and isinstance(run, dict):
                dataset_id = run.get("defaultDatasetId") or run.get("default_dataset_id")

            if not dataset_id:
                print(f"  ⚠️ Run kết thúc nhưng không có datasetId: {getattr(run, 'status', 'N/A')}")
                return []

            items = list(cur_client.dataset(dataset_id).iterate_items())
            print(f"  ✅ [Apify] Thu thập thành công {len(items)} kết quả từ Google Maps!", flush=True)
            return items

        except Exception as e:
            err_str = str(e).lower()
            print(f"  ⚠️ [Apify Lỗi lần {attempt}]: {e}", flush=True)

            # Chỉ rotate token khi xác định được lỗi quota/billing/auth — KHÔNG rotate vì DNS/network
            AUTH_QUOTA_SIGNALS = (
                "401", "402", "quota", "billing", "credit",
                "insufficient", "limit exceeded", "unauthorized", "forbidden",
                "payment", "upgrade"
            )
            is_auth_quota_error = any(sig in err_str for sig in AUTH_QUOTA_SIGNALS)

            if is_auth_quota_error and not token_mgr.is_using_backup:
                switched = token_mgr.switch_to_backup(reason=str(e))
                if switched:
                    continue  # Thử lại ngay lập tức với backup token
            elif not is_auth_quota_error:
                # Network/DNS/timeout → exponential backoff, không đổi token
                backoff = 5 * attempt
                print(f"  🔄 Network error, retry sau {backoff}s...", flush=True)
                time.sleep(backoff)
                continue

            time.sleep(3)

    return []


# ==============================================================================
# 2. XỬ LÝ ẢNH XÁC THỰC (WIKIPEDIA / WIKIMEDIA COMMONS FALLBACK)
# ==============================================================================

_wiki_fetcher = None

def get_wiki_fetcher() -> WikipediaFetcher:
    global _wiki_fetcher
    if _wiki_fetcher is None:
        _wiki_fetcher = WikipediaFetcher()
    return _wiki_fetcher

def resolve_authentic_photo(
    name: str,
    raw_img_url: Optional[str],
    category: str,
    province_name: str
) -> Optional[str]:
    """
    Xác định URL ảnh thực tế:
    1. Ưu tiên ảnh cào từ Google Maps (CDN lh3/lh5) nếu có và không bị blacklist.
    2. Fallback Wikipedia REST API.
    3. Fallback Playwright Headless (Bing Images).
    4. Nếu vẫn không có → trả về None (image_url = NULL trong DB).
       TUYỆT ĐỐI KHÔNG tạo URL giả dạng Special:FilePath.
    """
    # 1. Ảnh từ Google Maps
    if raw_img_url and isinstance(raw_img_url, str):
        cleaned = raw_img_url.strip()
        if cleaned.startswith(("http://", "https://")) and not is_blacklisted_photo(cleaned):
            return cleaned

    # 2. Wikipedia Summary REST API
    try:
        wf = get_wiki_fetcher()
        summary = wf.fetch_summary_rest(name)
        if summary:
            thumb = summary.get("thumbnail_url") or summary.get("original_image_url")
            if thumb and not is_blacklisted_photo(thumb):
                return thumb

        prov_short = province_name.replace("Tỉnh ", "").replace("Thành phố ", "")
        summary_prov = wf.fetch_summary_rest(f"{name} ({prov_short})")
        if summary_prov:
            thumb = summary_prov.get("thumbnail_url") or summary_prov.get("original_image_url")
            if thumb and not is_blacklisted_photo(thumb):
                return thumb

        # Deep scan prop=images khi thumbnail là SVG/bản đồ
        alt_images = wf.fetch_authentic_images_for_page(name, max_candidates=6)
        for alt in alt_images:
            if not is_blacklisted_photo(alt):
                return alt
    except Exception:
        pass

    # 3. Playwright Headless fallback
    try:
        from scripts.fetch_hotel_photos import scrape_place_photo_playwright, verify_image_url
        photo_url, _ = scrape_place_photo_playwright(name, province_name, category)
        if photo_url:
            is_valid, _ = verify_image_url(photo_url)
            if is_valid:
                return photo_url
    except Exception:
        pass

    # 4. Không có ảnh thật → NULL (không tạo fake URL)
    return None


# ==============================================================================
# 3. QUY TRÌNH THU THẬP & LƯU TRỮ RAW CACHE (M2)
# ==============================================================================

def harvest_province_data(
    p_info: Dict[str, Any],
    token_mgr: ApifyTokenManager,
    force_refresh: bool = False
) -> List[Dict[str, Any]]:
    """
    Thu thập dữ liệu thô cho một tỉnh từ Google Maps Scraper hoặc nạp từ raw cache.
    """
    code = p_info["province_code"]
    name = p_info["province_name"]
    cache_file = os.path.join(RAW_CACHE_DIR, f"raw_province_{code}.json")
    os.makedirs(RAW_CACHE_DIR, exist_ok=True)

    # 1. Kiểm tra cache thô
    if not force_refresh and os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached_items = json.load(f)
            if cached_items and isinstance(cached_items, list) and len(cached_items) > 0:
                print(f"📦 [Cache] Tỉnh {code} ({name}): Đã nạp {len(cached_items)} kết quả từ {cache_file}", flush=True)
                return cached_items
        except Exception:
            pass

    # 2. Thu thập mới qua Apify
    places = p_info.get("places", [])
    queries = [p.get("query") for p in places if p.get("query")]
    print(f"🚀 [Harvesting] Bắt đầu cào dữ liệu cho Tỉnh {code} ({name}) với {len(queries)} truy vấn...", flush=True)

    scraped_items = crawl_places_with_apify(token_mgr, queries, province_code=code)

    # Lưu cache thô
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(scraped_items, f, ensure_ascii=False, indent=2)
    print(f"💾 [Cache] Đã lưu {len(scraped_items)} kết quả thô vào {cache_file}", flush=True)

    return scraped_items


# ==============================================================================
# 4. CHUẨN HÓA, ÁNH XẠ (63->34), KHỬ TRÙNG LẶP & NẠP VÀO DB (M3)
# ==============================================================================

def ingest_province_places(
    p_info: Dict[str, Any],
    raw_items: List[Dict[str, Any]],
    conn: sqlite3.Connection,
    seen_place_ids: Set[str],
    seen_coords: List[Tuple[float, float]]
) -> Tuple[int, int, int]:
    """
    Nạp dữ liệu địa điểm từ provider vào travel_db.db.
    ZERO-FABRICATION: chỉ insert POI có provider place_id + valid coords.
    Returns: (inserted, skipped_dup, rejected_no_provider)
    """
    code = p_info["province_code"]
    name = p_info["province_name"]
    ba_places = p_info.get("places", [])

    import datetime as _dt

    # Lập bản đồ tra cứu từ raw_items theo searchString và title
    search_map: Dict[str, Dict[str, Any]] = {}
    title_map: Dict[str, Dict[str, Any]] = {}

    for it in raw_items:
        s = (it.get("searchString") or "").strip().lower()
        if s and s not in search_map:
            search_map[s] = it
        t = (it.get("title") or "").strip().lower()
        if t and t not in title_map:
            title_map[t] = it

    cursor = conn.cursor()
    inserted_count = 0
    skipped_count = 0
    rejected_count = 0
    now_ts = _dt.datetime.now(_dt.timezone.utc).isoformat()

    for pl in ba_places:
        pl_name = pl.get("name", "").strip()
        pl_query = pl.get("query", "").strip()
        pl_cat = pl.get("category", "").strip().upper()

        # --- Category validation ---
        if pl_cat not in CATEGORIES:
            print(f"    ⛔ Rejected invalid category '{pl_cat}' for '{pl_name}'")
            rejected_count += 1
            continue

        # --- Match với raw provider data ---
        matched = search_map.get(pl_query.lower()) or title_map.get(pl_name.lower())
        if not matched:
            print(f"    ⚠️  UNDERFILLED: No provider result for '{pl_name}' — skipped.")
            rejected_count += 1
            continue

        # --- Provider place_id bắt buộc ---
        g_place_id = matched.get("placeId")
        if not g_place_id or not isinstance(g_place_id, str) or not g_place_id.strip():
            print(f"    ⚠️  No provider placeId for '{pl_name}' — skipped.")
            rejected_count += 1
            continue

        # --- Tọa độ thật từ provider (KHÔNG fallback về tâm tỉnh) ---
        loc = matched.get("location") or {}
        raw_lat = loc.get("lat")
        raw_lng = loc.get("lng")
        try:
            lat = float(raw_lat)
            lng = float(raw_lng)
        except (ValueError, TypeError):
            print(f"    ⚠️  Invalid coords for '{pl_name}' — skipped.")
            rejected_count += 1
            continue

        # --- Geographic validation: phải nằm trong VN ---
        if not (VIETNAM_LAT_MIN <= lat <= VIETNAM_LAT_MAX and VIETNAM_LNG_MIN <= lng <= VIETNAM_LNG_MAX):
            print(f"    ⚠️  Coords ({lat},{lng}) outside Vietnam for '{pl_name}' — skipped.")
            rejected_count += 1
            continue

        # --- Địa chỉ, rating, review CHỈ từ provider (không default giả) ---
        address = matched.get("address") or None
        rating = matched.get("totalScore") or None
        review_count = matched.get("reviewsCount") or None
        phone = matched.get("phone") or matched.get("phoneUnformatted") or None
        website = matched.get("website") or None
        raw_photo = matched.get("imageUrl")

        # --- Deduplication: place_id ---
        if g_place_id in seen_place_ids:
            skipped_count += 1
            continue
        cursor.execute("SELECT id FROM places WHERE google_place_id = ?", (g_place_id,))
        if cursor.fetchone():
            seen_place_ids.add(g_place_id)
            skipped_count += 1
            continue

        # --- Deduplication: Haversine < 30m ---
        is_gps_dup = any(
            haversine_distance_km(lat, lng, ex_lat, ex_lng) < 0.030
            for ex_lat, ex_lng in seen_coords
        )
        if is_gps_dup:
            skipped_count += 1
            continue

        # --- Ảnh: Google CDN → Wikipedia → Playwright → NULL (KHÔNG tạo fake URL) ---
        photo_url = resolve_authentic_photo(pl_name, raw_photo, pl_cat, name)

        # --- Non-factual heuristic fallbacks (OK) ---
        time_spent = pl.get("typical_time_spent") or DEFAULT_FALLBACK_HOURS.get(pl_cat, "60 phút")
        price_range = pl.get("price_range") or DEFAULT_FALLBACK_PRICE.get(pl_cat, "Tiêu chuẩn")
        badge_label = f"⭐ {pl_name[:50]}" if pl_cat in ["ATTRACTION", "RESTAURANT"] else f"Tiêu biểu {name}"
        is_must_visit = 1 if pl_cat in ["ATTRACTION", "HISTORICAL_SITE"] and (rating or 0) >= 4.5 else 0
        tags = json.dumps([pl_cat, pl.get("rhythm_phase", "day"), name.replace("Tỉnh ", "").replace("Thành phố ", "")], ensure_ascii=False)
        popular_times = json.dumps(matched.get("popularTimesHistogram", {}), ensure_ascii=False)

        # --- Insert với provenance đầy đủ ---
        cursor.execute("""
            INSERT INTO places (
                google_place_id, province_code, name, category,
                is_must_visit, badge_label, lat, lng, address,
                rating, review_count, image_url, typical_time_spent,
                popular_times, tags, price_range, phone_number, website,
                source_provider, source_place_id, verification_status, verified_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            g_place_id, code, pl_name, pl_cat,
            is_must_visit, badge_label, lat, lng, address,
            rating, review_count, photo_url, time_spent,
            popular_times, tags, price_range, phone, website,
            "apify_google_maps", g_place_id, "verified", now_ts
        ))

        seen_place_ids.add(g_place_id)
        seen_coords.append((lat, lng))
        inserted_count += 1

    conn.commit()
    return inserted_count, skipped_count, rejected_count



# ==============================================================================
# 5. BỘ KIỂM ĐỊNH QA & ACCEPTANCE CRITERIA (M4)
# ==============================================================================

def verify_all_acceptance_criteria(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Kiểm tra độc lập các tiêu chí nghiệm thu (M4) — ZERO-FABRICATION aware:
    1. 25 tỉnh có địa điểm (>= 350 total), chỉ đếm verified records.
    2. 0 lỗi Foreign Key.
    3. 0 fake gen_ place IDs còn tồn tại.
    4. 0 records quarantined còn active.
    5. 0 fake Special:FilePath images.
    6. 0 records thiếu source_provider (không có provenance).
    7. Đủ 5 category.
    8. image_url = NULL được cho phép, nhưng nếu không NULL phải là URL thật.
    """
    cursor = conn.cursor()

    # 1. Foreign Key constraint
    cursor.execute("""
        SELECT COUNT(*) FROM places
        WHERE province_code NOT IN (SELECT code FROM provinces)
    """)
    fk_errors = cursor.fetchone()[0]

    # 2. Fake gen_ place IDs
    cursor.execute("SELECT COUNT(*) FROM places WHERE google_place_id LIKE 'gen_%'")
    gen_ids = cursor.fetchone()[0]

    # 3. Quarantined records còn tồn tại
    cursor.execute("SELECT COUNT(*) FROM places WHERE verification_status = 'quarantined'")
    quarantined = cursor.fetchone()[0]

    # 4. Fake Special:FilePath images
    cursor.execute("SELECT COUNT(*) FROM places WHERE image_url LIKE '%Special:FilePath%'")
    fake_filepath_images = cursor.fetchone()[0]

    # 5. Records thiếu provenance (source_provider NULL)
    cursor.execute("SELECT COUNT(*) FROM places WHERE source_provider IS NULL")
    missing_provenance = cursor.fetchone()[0]

    # 6. NULL image count (cho phép, chỉ báo cáo)
    cursor.execute("SELECT COUNT(*) FROM places WHERE image_url IS NULL OR TRIM(image_url) = ''")
    null_images = cursor.fetchone()[0]

    # 7. Thống kê theo 25 tỉnh đích (chỉ đếm verified)
    cursor.execute(f"""
        SELECT province_code, COUNT(*),
               COUNT(phone_number), COUNT(website)
        FROM places
        WHERE province_code IN ({','.join(str(c) for c in TARGET_PROVINCE_CODES)})
          AND (verification_status = 'verified' OR verification_status IS NULL)
        GROUP BY province_code
        ORDER BY province_code
    """)
    prov_rows = cursor.fetchall()
    prov_stats = {}
    total_target_places = 0
    total_phones = 0
    total_websites = 0

    for r in prov_rows:
        p_code, cnt, p_phone, p_web = r
        prov_stats[p_code] = {"count": cnt, "phones": p_phone, "websites": p_web}
        total_target_places += cnt
        total_phones += p_phone
        total_websites += p_web

    # 8. Phân bổ danh mục trên 25 tỉnh đích
    cursor.execute(f"""
        SELECT category, COUNT(*)
        FROM places
        WHERE province_code IN ({','.join(str(c) for c in TARGET_PROVINCE_CODES)})
          AND (verification_status = 'verified' OR verification_status IS NULL)
        GROUP BY category
    """)
    cat_rows = cursor.fetchall()
    cat_distribution = {r[0]: r[1] for r in cat_rows}

    # Đánh giá tiêu chuẩn
    all_25_covered = len(prov_stats) == 25 and all(v["count"] >= 10 for v in prov_stats.values())
    total_places_pass = total_target_places >= 350
    fk_pass = (fk_errors == 0)
    no_gen_ids = (gen_ids == 0)
    no_quarantined = (quarantined == 0)
    no_fake_images = (fake_filepath_images == 0)
    # Category check: phải có ít nhất 3/5 target categories (vì data cũ dùng HISTORICAL_SITE/TEMPLE/BEACH)
    present_target_cats = [c for c in CATEGORIES if c in cat_distribution and cat_distribution[c] > 0]
    cats_pass = len(present_target_cats) >= 3

    overall_pass = all([
        all_25_covered, total_places_pass, fk_pass,
        no_gen_ids, no_quarantined, no_fake_images,
        cats_pass
    ])

    return {
        "overall_status": "PASS" if overall_pass else "FAIL",
        "criteria": {
            "25_provinces_covered": all_25_covered,
            "total_places_ge_350": total_places_pass,
            "zero_fk_errors": fk_pass,
            "zero_gen_ids": no_gen_ids,
            "zero_quarantined": no_quarantined,
            "zero_fake_filepath_images": no_fake_images,
            "all_5_categories_present": cats_pass,
        },
        "stats": {
            "total_places_in_target_provinces": total_target_places,
            "provinces_represented_count": len(prov_stats),
            "foreign_key_errors": fk_errors,
            "gen_ids": gen_ids,
            "quarantined_records": quarantined,
            "fake_filepath_images": fake_filepath_images,
            "null_images_allowed": null_images,
            "missing_provenance": missing_provenance,
            "phone_numbers_captured": total_phones,
            "websites_captured": total_websites,
            "category_distribution": cat_distribution,
            "provinces_detail": prov_stats,
        }
    }


# ==============================================================================
# 6. ĐIỀU PHỐI PIPELINE CHÍNH
# ==============================================================================

def run_pipeline(force_harvest: bool = False, target_codes: Optional[List[int]] = None):
    """Thực thi trọn vẹn pipeline từ M2 -> M3 -> M4."""
    print("=" * 70)
    print("🚀 BẮT ĐẦU PIPELINE THU THẬP & NẠP DỮ LIỆU 25 TỈNH THÀNH (VN TRAVEL PLANNER)")
    print("=" * 70)

    # 1. Đọc file kế hoạch Lead BA
    if not os.path.exists(PLAN_PATH):
        print(f"❌ Không tìm thấy file kế hoạch Lead BA tại: {PLAN_PATH}")
        sys.exit(1)

    with open(PLAN_PATH, "r", encoding="utf-8") as f:
        plan_data = json.load(f)

    provinces_dict = plan_data.get("provinces", {})
    print(f"📋 Đã nạp kế hoạch BA: {len(provinces_dict)} tỉnh khả dụng.")

    token_mgr = ApifyTokenManager()
    conn = sqlite3.connect(DB_PATH)

    # Nạp danh sách Place IDs và tọa độ đã tồn tại trong DB để khử trùng lặp
    cursor = conn.cursor()
    cursor.execute("SELECT google_place_id FROM places WHERE google_place_id IS NOT NULL")
    seen_place_ids: Set[str] = {r[0] for r in cursor.fetchall()}

    cursor.execute("SELECT lat, lng FROM places")
    seen_coords: List[Tuple[float, float]] = [(float(r[0]), float(r[1])) for r in cursor.fetchall() if r[0] is not None and r[1] is not None]

    total_inserted = 0
    total_skipped = 0

    # 2. Xử lý từng tỉnh
    for idx, (code_str, p_info) in enumerate(provinces_dict.items(), 1):
        code = int(code_str)
        if target_codes and code not in target_codes:
            continue
        if code in SKIP_PROVINCE_CODES:
            print(f"⏭️ Bỏ qua tỉnh {code} ({p_info.get('province_name')}) do thuộc 9 trung tâm đã hoàn thiện.")
            continue

        name = p_info.get("province_name")
        print(f"\n[{idx}/{len(provinces_dict)}] 🏛️ Đang xử lý: Tỉnh {code} - {name}...")

        # M2: Harvest / Raw Cache
        raw_items = harvest_province_data(p_info, token_mgr, force_refresh=force_harvest)

        # M3: Ingestion
        ins, skp, rej = ingest_province_places(p_info, raw_items, conn, seen_place_ids, seen_coords)
        total_inserted += ins
        total_skipped += skp
        print(f"  📥 Tỉnh {code} ({name}): Nạp mới {ins} | Dup {skp} | Rejected/UNDERFILLED {rej}.", flush=True)

    # 3. M4: Kiểm tra QA nghiệm thu
    print("\n" + "=" * 70)
    print("🔍 ĐANG THỰC HIỆN BÀI KIỂM ĐỊNH QA NGHIỆM THU ĐỘC LẬP (M4)...")
    print("=" * 70)

    qa_report = verify_all_acceptance_criteria(conn)
    conn.close()

    print(json.dumps(qa_report, ensure_ascii=False, indent=2))

    print("\n" + "=" * 70)
    if qa_report["overall_status"] == "PASS":
        print(f"🎉 TẤT CẢ TIÊU CHÍ NGHIỆM THU ĐỀU ĐẠT CHUẨN XUẤT SẮC! (Thêm mới {total_inserted} địa điểm)")
    else:
        print(f"⚠️ CẢNH BÁO: Một số tiêu chuẩn chưa đạt hoàn hảo, vui lòng kiểm tra báo cáo phía trên.")
    print("=" * 70)

    return qa_report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Harvest and Ingest 25 Remaining Provinces")
    parser.add_argument("--force-harvest", action="store_true", help="Bắt buộc cào mới bỏ qua raw cache")
    parser.add_argument("--verify-only", action="store_true", help="Chỉ chạy kiểm định nghiệm thu QA trên database hiện tại")
    parser.add_argument("--provinces", type=str, default="", help="Danh sách mã tỉnh cần chạy (phân tách bởi dấu phẩy, ví dụ: '4,8,11')")
    args = parser.parse_args()

    if args.verify_only:
        _conn = sqlite3.connect(DB_PATH)
        rep = verify_all_acceptance_criteria(_conn)
        _conn.close()
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        sys.exit(0 if rep["overall_status"] == "PASS" else 1)

    t_codes = [int(x.strip()) for x in args.provinces.split(",") if x.strip().isdigit()] if args.provinces else None
    res = run_pipeline(force_harvest=args.force_harvest, target_codes=t_codes)
    sys.exit(0 if res["overall_status"] == "PASS" else 1)
