"""
scripts/harvest_pipeline.py

Pipeline thu thập, làm sạch, chuẩn hóa và làm giàu dữ liệu địa danh 63 tỉnh thành Việt Nam:
1. Vietnam Territorial GPS Filter:
   - Giới hạn bounding box lãnh thổ Việt Nam: lat in [8.0, 23.5], lng in [102.0, 110.0].
   - Loại trừ 11 địa danh nước ngoài (Hồng Kông, Vũ Hán, Tứ Xuyên, Đài Loan, Thái Bình Dương,...).
   - Kiểm tra khoảng cách Haversine chống rò rỉ chéo tỉnh thành (> 200km).
2. Photo Sanitizer & Blacklist:
   - Loại bỏ triệt để file .svg, bản đồ hành chính (location_map, relief_location_map), quốc huy, cờ, biểu trưng.
   - Khử trùng lặp ảnh toàn cục (Global Duplicate Photo Deduction): Mỗi URL ảnh gán duy nhất cho 1 địa danh.
3. Wikipedia REST & Action API Fetcher:
   - Truy vấn REST Summary API và MediaWiki Action API (pithumbsize=800).
   - Thiết lập User-Agent chuẩn: VNTravelBot/1.0 (contact@vntravel.ai).
   - Tự động bỏ qua trang định hướng (disambiguation).
   - Dự phòng bốc ảnh chụp thực tế (JPG/PNG) từ prop=images và imageinfo khi thumbnail là ảnh sơ đồ.
4. Schema Normalizer:
   - Chuẩn hóa đầy đủ 20 trường dữ liệu theo quy chuẩn RULES_63_PROVINCES_ENRICHMENT.md.
   - Áp dụng quy tắc fallback thời gian tham quan (typical_time_spent) và khoảng giá (price_range).
5. Clean Interfaces & CLI:
   - Module APIs sạch và CLI trực quan cho các harvester miền và runner kiểm toán.
"""

import os
import sys
import json
import math
import re
import argparse
import urllib.parse
from typing import Dict, Any, List, Set, Tuple, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Đảm bảo đường dẫn import tới thư mục gốc
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scripts.mapping_config import MAPPING_63_TO_34, FALLBACK_RULES, PROVINCE_COORDINATES

__all__ = [
    "VIETNAM_LAT_MIN", "VIETNAM_LAT_MAX", "VIETNAM_LNG_MIN", "VIETNAM_LNG_MAX",
    "KNOWN_FOREIGN_KEYWORDS", "PHOTO_BLACKLIST_KEYWORDS", "DEFAULT_USER_AGENT",
    "SCHEMA_20_FIELDS", "is_within_vietnam_bounds", "haversine_distance_km",
    "is_foreign_landmark", "is_cross_province_leakage", "filter_gps_and_territory",
    "is_blacklisted_photo", "sanitize_photo_url", "sanitize_places_photos",
    "WikipediaFetcher", "normalize_category", "normalize_place_record",
    "normalize_dataset", "HarvestPipeline"
]


# ==============================================================================
# 1. HẰNG SỐ CẤU HÌNH & BỘ LỌC RANH GIỚI ĐỊA LÝ
# ==============================================================================

# Bounding box lãnh thổ đất liền và hải đảo Việt Nam
VIETNAM_LAT_MIN = 8.0
VIETNAM_LAT_MAX = 23.5
VIETNAM_LNG_MIN = 102.0
VIETNAM_LNG_MAX = 110.0

# Các từ khóa địa danh quốc tế bị rò rỉ trong dữ liệu cào thô
KNOWN_FOREIGN_KEYWORDS = [
    "hồng kông", "hong kong",
    "hoa nam", "wuhan", "vũ hán",
    "thái bình dương", "pacific",
    "cửu trại câu", "jiuzhaigou",
    "đài loan", "taiwan",
    "vũ lăng nguyên", "wulingyuan",
    "chùa thiếu lâm", "thiếu lâm", "shaolin",
    "hoàng long", "huanglong",
    "hoàng sơn", "huangshan",
    "tứ xuyên", "sichuan",
    "vân nam", "yunnan"
]

# Các từ khóa và định dạng ảnh bị cấm tuyệt đối (bản đồ SVG, quốc huy, cờ)
PHOTO_BLACKLIST_KEYWORDS = [
    ".svg", "location_map", "relief_location_map", "locator_map",
    "coat_of_arms", "coats_of_arms", "emblem", "flag_of", "party_flag",
    "blason", "arms_of", "national_emblem", "insignia", "logo",
    "map_of", "_map.", "_map_", "provinces_map", "district_map",
    "quankhuvn", "peace_dove", "commons-logo", "diagram", "vietnam_ct."
]

DEFAULT_USER_AGENT = "VNTravelBot/1.0 (contact@vntravel.ai)"
WIKI_REST_BASE = "https://vi.wikipedia.org/api/rest_v1/page/summary"
WIKI_ACTION_BASE = "https://vi.wikipedia.org/w/api.php"

# Danh sách 20 trường bắt buộc trong Schema
SCHEMA_20_FIELDS = [
    "id", "name", "category", "is_must_visit", "badge_label",
    "original_province", "region", "target_province_code", "target_province_name",
    "target_ward_code", "target_ward_name", "lat", "lng",
    "typical_time_spent", "price_range", "photo_url", "photo_source",
    "wiki_title", "wiki_url", "description"
]

# ==============================================================================
# 2. BỘ LỌC TỌA ĐỘ GPS & ĐỊA DANH NƯỚC NGOÀI
# ==============================================================================

def is_within_vietnam_bounds(lat: Optional[float], lng: Optional[float]) -> bool:
    """Kiểm tra tọa độ có nằm trọn vẹn trong bounding box lãnh thổ Việt Nam."""
    if lat is None or lng is None:
        return False
    try:
        lat_f = float(lat)
        lng_f = float(lng)
        return (VIETNAM_LAT_MIN <= lat_f <= VIETNAM_LAT_MAX) and (VIETNAM_LNG_MIN <= lng_f <= VIETNAM_LNG_MAX)
    except (ValueError, TypeError):
        return False

def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Tính khoảng cách đường tròn lớn giữa hai điểm tọa độ (công thức Haversine, đơn vị km)."""
    r = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2))
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c

def is_foreign_landmark(place: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Xác định địa danh có phải thực thể ngoài lãnh thổ Việt Nam hay không:
    - Tiêu chí 1 (Tuyệt đối): Tọa độ GPS ngoài ranh giới lãnh thổ Việt Nam [8.0, 23.5] lat, [102.0, 110.0] lng.
      Bắt chính xác 11 địa danh ngoại quốc (Hồng Kông, Vũ Hán, Thái Bình Dương, Cửu Trại Câu, Đài Loan, Vũ Lăng Nguyên, Chùa Thiếu Lâm, Hoàng Long, Hoàng Sơn).
    - Tiêu chí 2: Danh lam thắng cảnh quốc tế nổi tiếng khớp tên/wiki_title (loại trừ các cơ sở lưu trú/nhà hàng nội địa).
    """
    lat = place.get("lat")
    lng = place.get("lng")

    # 1. Kiểm tra tọa độ GPS ngoài bounding box lãnh thổ Việt Nam
    if lat is not None and lng is not None:
        if not is_within_vietnam_bounds(lat, lng):
            return True, f"Tọa độ ({lat}, {lng}) nằm ngoài lãnh thổ Việt Nam [{VIETNAM_LAT_MIN}-{VIETNAM_LAT_MAX}, {VIETNAM_LNG_MIN}-{VIETNAM_LNG_MAX}]"

    # 2. Kiểm tra tên/wiki_title danh lam quốc tế đặc trưng
    name = (place.get("name") or "").strip().lower()
    wiki_title = (place.get("wiki_title") or "").strip().lower()

    # Bỏ qua nếu là cơ sở dịch vụ nội địa (khách sạn, nhà hàng, resort, quán cà phê)
    if any(prefix in name for prefix in ["khách sạn", "nhà hàng", "quán", "resort", "homestay", "công ty", "bến xe"]):
        return False, ""

    exact_foreign = [
        "đường hải phòng, hồng kông", "chợ buôn bán hải sản hoa nam",
        "thái bình dương", "khu thắng cảnh cửu trại câu", "cửu trại câu",
        "đài loan", "khu thắng cảnh vũ lăng nguyên", "vũ lăng nguyên",
        "chùa thiếu lâm", "hoàng sơn", "hoàng long (tứ xuyên)"
    ]
    for ef in exact_foreign:
        if ef == name or ef == wiki_title or f"({ef})" in name or f"({ef})" in wiki_title:
            return True, f"Khớp địa danh quốc tế: '{ef}'"

    return False, ""


def is_cross_province_leakage(place: Dict[str, Any], max_distance_km: float = 200.0) -> Tuple[bool, float, str]:
    """
    Phát hiện rò rỉ chéo địa danh (ví dụ Chợ Bến Thành gán vào Thái Bình/Vĩnh Phúc):
    Tính khoảng cách từ tọa độ địa danh tới tâm tỉnh thành khai báo.
    """
    prov = place.get("original_province")
    lat = place.get("lat")
    lng = place.get("lng")

    if not prov or lat is None or lng is None:
        return False, 0.0, ""

    center = PROVINCE_COORDINATES.get(prov)
    if not center:
        return False, 0.0, ""

    try:
        dist = haversine_distance_km(float(lat), float(lng), center[0], center[1])
        if dist > max_distance_km:
            return True, dist, f"Khoảng cách tới tâm {prov} là {dist:.1f} km (vượt ngưỡng {max_distance_km} km)"
    except Exception as e:
        return False, 0.0, str(e)

    return False, dist, ""

def filter_gps_and_territory(
    places: List[Dict[str, Any]],
    prune_foreign: bool = True,
    prune_leakage: bool = False,
    max_leakage_km: float = 200.0
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Lọc danh sách địa danh, phân tách thành danh sách hợp lệ và danh sách bị loại bỏ.
    """
    valid_places = []
    rejected_places = []

    for p in places:
        is_foreign, foreign_reason = is_foreign_landmark(p)
        if prune_foreign and is_foreign:
            rejected_item = dict(p)
            rejected_item["rejection_reason"] = foreign_reason
            rejected_places.append(rejected_item)
            continue

        if prune_leakage:
            is_leak, dist, leak_reason = is_cross_province_leakage(p, max_distance_km=max_leakage_km)
            if is_leak:
                rejected_item = dict(p)
                rejected_item["rejection_reason"] = leak_reason
                rejected_places.append(rejected_item)
                continue

        valid_places.append(p)

    return valid_places, rejected_places

# ==============================================================================
# 3. PHOTO SANITIZER, SVG BLACKLIST & KHỬ TRÙNG LẶP ẢNH
# ==============================================================================

def is_blacklisted_photo(photo_url: Optional[str]) -> bool:
    """
    Kiểm tra một URL ảnh có thuộc danh sách đen hay không:
    - Là ảnh SVG (.svg, .svg.png, .svg/...)
    - Chứa các từ khóa sơ đồ, bản đồ hành chính, quốc huy, quốc kỳ, biểu trưng.
    """
    if not photo_url or not isinstance(photo_url, str):
        return False

    url_lower = photo_url.lower()

    # Kiểm tra các từ khóa cấm
    for kw in PHOTO_BLACKLIST_KEYWORDS:
        if kw in url_lower:
            return True

    return False

def sanitize_photo_url(photo_url: Optional[str], seen_urls: Optional[Set[str]] = None) -> Optional[str]:
    """
    Làm sạch một URL ảnh:
    - Trả về None nếu URL rỗng, không hợp lệ hoặc nằm trong blacklist (SVG/Map).
    - Trả về None nếu URL đã tồn tại trong `seen_urls` (khử trùng lặp ảnh).
    - Thêm URL vào `seen_urls` nếu hợp lệ.
    """
    if not photo_url or not isinstance(photo_url, str):
        return None

    cleaned_url = photo_url.strip()
    if not cleaned_url.startswith(("http://", "https://")):
        return None

    if is_blacklisted_photo(cleaned_url):
        return None

    if seen_urls is not None:
        if cleaned_url in seen_urls:
            # Bị trùng lặp với địa danh đã có trước đó -> nullify
            return None
        seen_urls.add(cleaned_url)

    return cleaned_url

def sanitize_places_photos(
    places: List[Dict[str, Any]],
    seen_urls: Optional[Set[str]] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    Làm sạch URL ảnh cho toàn bộ danh sách địa điểm:
    - Loại bỏ ảnh SVG/bản đồ.
    - Khử trùng lặp ảnh toàn cục (chỉ giữ URL cho địa danh đầu tiên gặp).
    - Cập nhật trường photo_source thành 'Chờ cập nhật xác thực' khi photo_url là None.
    """
    if seen_urls is None:
        seen_urls = set()

    sanitized_places = []
    stats = {
        "total_records": len(places),
        "photos_initial": 0,
        "photos_retained": 0,
        "blacklisted_svg_removed": 0,
        "duplicates_removed": 0,
        "null_photos_count": 0
    }

    for p in places:
        item = dict(p)
        raw_url = item.get("photo_url")
        if raw_url:
            stats["photos_initial"] += 1

            if is_blacklisted_photo(raw_url):
                stats["blacklisted_svg_removed"] += 1
                item["photo_url"] = None
                item["photo_source"] = "Chờ cập nhật xác thực"
            elif raw_url in seen_urls:
                stats["duplicates_removed"] += 1
                item["photo_url"] = None
                item["photo_source"] = "Chờ cập nhật xác thực"
            else:
                seen_urls.add(raw_url)
                item["photo_url"] = raw_url
                if not item.get("photo_source") or item.get("photo_source") == "Chờ cập nhật xác thực":
                    item["photo_source"] = "Wikipedia / Wikimedia Commons"
                stats["photos_retained"] += 1
        else:
            item["photo_url"] = None
            item["photo_source"] = "Chờ cập nhật xác thực"
            stats["null_photos_count"] += 1

        sanitized_places.append(item)

    return sanitized_places, stats

# ==============================================================================
# 4. WIKIPEDIA REST & ACTION API FETCHER
# ==============================================================================

class WikipediaFetcher:
    """
    Công cụ truy vấn dữ liệu và ảnh thực tế từ Wikipedia tiếng Việt:
    - REST Summary API: Lấy tóm tắt, ảnh thumbnail chuẩn và tọa độ GPS.
    - MediaWiki Action API: Truy vấn hàng loạt (pithumbsize=800, extracts, coordinates).
    - Deep Image Recovery: Khi thumbnail là bản đồ SVG, bốc ảnh chụp JPG/PNG thực tế từ prop=images.
    """

    def __init__(self, user_agent: str = DEFAULT_USER_AGENT, timeout: float = 8.0, max_retries: int = 3):
        self.user_agent = user_agent
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})

        retries = Retry(
            total=max_retries,
            backoff_factor=0.3,
            status_forcelist=[429, 500, 502, 503, 504],
            raise_on_status=False
        )
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def fetch_summary_rest(self, wiki_title: str) -> Optional[Dict[str, Any]]:
        """
        Truy vấn trang qua Wikipedia REST API:
        https://vi.wikipedia.org/api/rest_v1/page/summary/{wiki_title}
        """
        if not wiki_title or not wiki_title.strip():
            return None

        clean_title = wiki_title.strip().replace(" ", "_")
        encoded_title = urllib.parse.quote(clean_title)
        url = f"{WIKI_REST_BASE}/{encoded_title}"

        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code != 200:
                return None

            data = resp.json()

            # Bỏ qua trang định hướng
            page_type = data.get("type", "")
            if page_type == "disambiguation":
                return None

            thumb = data.get("thumbnail", {}).get("source")
            if thumb and is_blacklisted_photo(thumb):
                thumb = None

            orig = data.get("originalimage", {}).get("source")
            if orig and is_blacklisted_photo(orig):
                orig = None

            coords = data.get("coordinates") or {}
            lat = coords.get("lat")
            lng = coords.get("lon")

            desktop_url = data.get("content_urls", {}).get("desktop", {}).get("page")
            if not desktop_url:
                desktop_url = f"https://vi.wikipedia.org/wiki/{encoded_title}"

            return {
                "wiki_title": data.get("title", wiki_title),
                "type": page_type,
                "description": data.get("description", ""),
                "extract": data.get("extract", ""),
                "thumbnail_url": thumb,
                "original_image_url": orig,
                "lat": lat,
                "lng": lng,
                "wiki_url": desktop_url
            }
        except Exception:
            return None

    def batch_fetch_action(self, titles: List[str], chunk_size: int = 50) -> Dict[str, Dict[str, Any]]:
        """
        Truy vấn hàng loạt tiêu đề qua MediaWiki Action API (lên tới 50 tiêu đề/request).
        """
        if not titles:
            return {}

        results = {}
        for i in range(0, len(titles), chunk_size):
            chunk = titles[i:i + chunk_size]
            clean_chunk = [t.strip() for t in chunk if t and t.strip()]
            if not clean_chunk:
                continue

            params = {
                "action": "query",
                "titles": "|".join(clean_chunk),
                "prop": "coordinates|pageimages|extracts|info|pageprops",
                "inprop": "url",
                "exintro": 1,
                "explaintext": 1,
                "piprop": "thumbnail",
                "pithumbsize": 800,
                "format": "json"
            }

            try:
                resp = self.session.get(WIKI_ACTION_BASE, params=params, timeout=self.timeout)
                if resp.status_code != 200:
                    continue

                payload = resp.json()
                pages = payload.get("query", {}).get("pages", {})

                for pid, p in pages.items():
                    if pid == "-1":
                        continue

                    # Bỏ qua nếu là trang định hướng
                    if "disambiguation" in p.get("pageprops", {}):
                        continue

                    title = p.get("title")
                    coords_list = p.get("coordinates", [])
                    lat = coords_list[0].get("lat") if coords_list else None
                    lng = coords_list[0].get("lon") if coords_list else None

                    thumb_source = p.get("thumbnail", {}).get("source")
                    if thumb_source and is_blacklisted_photo(thumb_source):
                        thumb_source = None

                    extract = p.get("extract", "")

                    results[title] = {
                        "wiki_title": title,
                        "lat": lat,
                        "lng": lng,
                        "photo_url": thumb_source,
                        "extract": extract,
                        "wiki_url": p.get("fullurl", f"https://vi.wikipedia.org/wiki/{urllib.parse.quote(title)}")
                    }
            except Exception:
                continue

        return results

    def fetch_authentic_images_for_page(self, wiki_title: str, max_candidates: int = 10) -> List[str]:
        """
        Dự phòng khi thumbnail chính của bài viết là bản đồ SVG hoặc rỗng:
        Quét prop=images để bốc danh sách file ảnh thực tế (JPG, PNG) và lấy URL chất lượng cao.
        """
        if not wiki_title:
            return []

        clean_title = wiki_title.strip()
        params = {
            "action": "query",
            "titles": clean_title,
            "prop": "images",
            "imlimit": max_candidates,
            "format": "json"
        }

        image_titles = []
        try:
            r = self.session.get(WIKI_ACTION_BASE, params=params, timeout=self.timeout).json()
            pages = r.get("query", {}).get("pages", {})
            for pid, p in pages.items():
                if pid == "-1":
                    continue
                for img in p.get("images", []):
                    img_title = img.get("title", "")
                    # Bỏ qua các file SVG và file bản đồ
                    if not is_blacklisted_photo(img_title) and any(img_title.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                        image_titles.append(img_title)
        except Exception:
            return []

        if not image_titles:
            return []

        # Truy vấn URL cho các ảnh hợp lệ qua imageinfo
        valid_urls = []
        info_params = {
            "action": "query",
            "titles": "|".join(image_titles[:5]),
            "prop": "imageinfo",
            "iiprop": "url",
            "iiurlwidth": 800,
            "format": "json"
        }
        try:
            r2 = self.session.get(WIKI_ACTION_BASE, params=info_params, timeout=self.timeout).json()
            info_pages = r2.get("query", {}).get("pages", {})
            for pid, p in info_pages.items():
                infos = p.get("imageinfo", [])
                if infos:
                    url = infos[0].get("thumburl") or infos[0].get("url")
                    if url and not is_blacklisted_photo(url):
                        valid_urls.append(url)
        except Exception:
            pass

        return valid_urls

    def search_wiki(self, query: str, limit: int = 3) -> List[str]:
        """Tìm kiếm tiêu đề bài viết Wikipedia qua Search API."""
        if not query or not query.strip():
            return []

        params = {
            "action": "query",
            "list": "search",
            "srsearch": query.strip(),
            "srlimit": limit,
            "format": "json"
        }
        try:
            r = self.session.get(WIKI_ACTION_BASE, params=params, timeout=self.timeout).json()
            items = r.get("query", {}).get("search", [])
            return [it["title"] for it in items if "title" in it]
        except Exception:
            return []

# ==============================================================================
# 5. SCHEMA NORMALIZER & FALLBACK RULES
# ==============================================================================

def normalize_category(cat: Optional[str]) -> str:
    """Chuẩn hóa danh mục địa danh theo enum PlaceCategory."""
    if not cat:
        return "ATTRACTION"
    cat_upper = cat.strip().upper()
    valid_categories = {
        "HISTORICAL_SITE", "TEMPLE", "ATTRACTION", "HOTEL",
        "MARKET", "SPECIALTY_FOOD", "RESTAURANT", "SEAFOOD_RESTAURANT", "BEACH"
    }
    return cat_upper if cat_upper in valid_categories else "ATTRACTION"

def normalize_place_record(
    place: Dict[str, Any],
    fallback_rules: Optional[Dict[str, Dict[str, str]]] = None,
    mapping_config: Optional[Dict[str, Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Chuẩn hóa 1 bản ghi địa danh:
    - Đảm bảo đầy đủ 20 trường bắt buộc trong Schema.
    - Ánh xạ tự động mã và tên tỉnh thành mới từ original_province (nếu thiếu hoặc sai lệch).
    - Áp dụng thời gian tham quan (typical_time_spent) và khoảng giá (price_range) dự phòng.
    - Chuẩn hóa lat, lng thành số thực làm tròn 6 chữ số thập phân.
    - Bảo toàn các trường mở rộng nếu có (rating, review_count, address, prices,...).
    """
    if fallback_rules is None:
        fallback_rules = FALLBACK_RULES
    if mapping_config is None:
        mapping_config = MAPPING_63_TO_34

    norm = dict(place)

    # 1. Tên và danh mục
    name = (norm.get("name") or norm.get("wiki_title") or "Địa điểm tham quan").strip()
    norm["name"] = name
    category = normalize_category(norm.get("category"))
    norm["category"] = category

    # 2. Tỉnh thành gốc & Ánh xạ tỉnh thành đích
    orig_prov = norm.get("original_province") or "Hà Nội"
    norm["original_province"] = orig_prov

    mapping = mapping_config.get(orig_prov)
    if mapping:
        norm["target_province_code"] = norm.get("target_province_code") or mapping["target_code"]
        norm["target_province_name"] = norm.get("target_province_name") or mapping["target_name"]
        norm["region"] = norm.get("region") or mapping.get("region", "Đồng bằng sông Hồng")
    else:
        norm["target_province_code"] = norm.get("target_province_code", 1)
        norm["target_province_name"] = norm.get("target_province_name", "Thành phố Hà Nội")
        norm["region"] = norm.get("region", "Đồng bằng sông Hồng")

    # 3. Phường / Xã
    norm["target_ward_code"] = norm.get("target_ward_code")
    norm["target_ward_name"] = norm.get("target_ward_name") or ""

    # 4. Tọa độ GPS
    lat = norm.get("lat")
    lng = norm.get("lng")
    if lat is not None:
        try:
            norm["lat"] = round(float(lat), 6)
        except (ValueError, TypeError):
            norm["lat"] = 21.0285
    else:
        center = PROVINCE_COORDINATES.get(orig_prov, (21.0285, 105.8542))
        norm["lat"] = round(center[0], 6)

    if lng is not None:
        try:
            norm["lng"] = round(float(lng), 6)
        except (ValueError, TypeError):
            norm["lng"] = 105.8542
    else:
        center = PROVINCE_COORDINATES.get(orig_prov, (21.0285, 105.8542))
        norm["lng"] = round(center[1], 6)

    # 5. Quy tắc fallback pacing & pricing
    fb = fallback_rules.get(category, {"typical_time_spent": "60 phút", "price_range": "Miễn phí / Tự do"})
    if not norm.get("typical_time_spent"):
        norm["typical_time_spent"] = fb.get("typical_time_spent", "60 phút")
    if not norm.get("price_range"):
        norm["price_range"] = fb.get("price_range", "Miễn phí / Tự do")

    # 6. Ảnh và nguồn ảnh
    photo_url = norm.get("photo_url")
    if photo_url:
        norm["photo_url"] = photo_url
        if not norm.get("photo_source") or norm.get("photo_source") == "Chờ cập nhật xác thực":
            norm["photo_source"] = "Wikipedia / Wikimedia Commons"
    else:
        norm["photo_url"] = None
        norm["photo_source"] = "Chờ cập nhật xác thực"

    # 7. Wiki fields & Flags
    norm["is_must_visit"] = bool(norm.get("is_must_visit", False))
    norm["badge_label"] = norm.get("badge_label") or ""
    norm["wiki_title"] = norm.get("wiki_title") or name
    norm["wiki_url"] = norm.get("wiki_url") or f"https://vi.wikipedia.org/wiki/{urllib.parse.quote(norm['wiki_title'])}"
    norm["description"] = norm.get("description") or ""

    # Đảm bảo trường ID
    if "id" not in norm or norm["id"] is None:
        norm["id"] = 1000

    # Đảm bảo thứ tự khóa theo chuẩn 20 trường của Schema
    ordered_record = {}
    for key in SCHEMA_20_FIELDS:
        ordered_record[key] = norm.get(key)

    # Giữ lại các trường mở rộng nếu có
    for k, v in norm.items():
        if k not in ordered_record:
            ordered_record[k] = v

    return ordered_record

def normalize_dataset(places: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Chuẩn hóa toàn bộ danh sách địa danh trong tập dữ liệu."""
    return [normalize_place_record(p) for p in places]

# ==============================================================================
# 6. PIPELINE ORCHESTRATOR
# ==============================================================================

class HarvestPipeline:
    """
    Lớp điều phối toàn diện quy trình làm sạch, lọc địa danh, khử trùng lặp và làm giàu Wikipedia.
    """

    def __init__(self, user_agent: str = DEFAULT_USER_AGENT, seen_photos: Optional[Set[str]] = None):
        self.fetcher = WikipediaFetcher(user_agent=user_agent)
        self.seen_photos = seen_photos if seen_photos is not None else set()

    def clean_dataset(
        self,
        places: List[Dict[str, Any]],
        prune_foreign: bool = True,
        prune_leakage: bool = False,
        max_leakage_km: float = 200.0,
        sanitize_photos: bool = True,
        normalize_schema: bool = True
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Quy trình làm sạch dữ liệu:
        1. Lọc bỏ các địa danh ngoài ranh giới Việt Nam (hoặc từ khóa nước ngoài).
        2. Làm sạch URL ảnh, loại bỏ SVG và khử trùng lặp ảnh toàn cục.
        3. Chuẩn hóa Schema và điền fallback pacing/pricing.
        """
        initial_count = len(places)

        # BƯỚC 1: Lọc GPS & Nước ngoài
        valid_places, rejected_places = filter_gps_and_territory(
            places,
            prune_foreign=prune_foreign,
            prune_leakage=prune_leakage,
            max_leakage_km=max_leakage_km
        )

        # BƯỚC 2: Khử ảnh SVG và trùng lặp
        if sanitize_photos:
            cleaned_places, photo_stats = sanitize_places_photos(valid_places, seen_urls=self.seen_photos)
        else:
            cleaned_places = valid_places
            photo_stats = {}

        # BƯỚC 3: Chuẩn hóa Schema
        if normalize_schema:
            final_places = normalize_dataset(cleaned_places)
        else:
            final_places = cleaned_places

        stats = {
            "initial_count": initial_count,
            "final_count": len(final_places),
            "foreign_pruned": len(rejected_places),
            "rejections": [{"id": r.get("id"), "name": r.get("name"), "reason": r.get("rejection_reason")} for r in rejected_places],
            "photo_stats": photo_stats
        }

        return final_places, stats

    def enrich_missing_photos(
        self,
        places: List[Dict[str, Any]],
        max_enrich: int = 50,
        verbose: bool = False
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Truy vấn Wikipedia REST & Action API để bổ sung ảnh thực tế cho các địa danh đang thiếu ảnh.
        """
        enriched_count = 0
        enriched_places = []

        for p in places:
            item = dict(p)
            if not item.get("photo_url") and enriched_count < max_enrich:
                wiki_title = item.get("wiki_title") or item.get("name")
                if wiki_title:
                    if verbose:
                        print(f"[*] Đang tìm ảnh cho: {wiki_title}...", flush=True)

                    # 1. Thử qua REST Summary
                    summary = self.fetcher.fetch_summary_rest(wiki_title)
                    new_thumb = None
                    if summary:
                        new_thumb = summary.get("thumbnail_url")
                        if not item.get("description") and summary.get("extract"):
                            item["description"] = summary["extract"][:400]

                    # 2. Nếu REST không có ảnh hoặc là SVG, quét prop=images
                    if not new_thumb:
                        alt_images = self.fetcher.fetch_authentic_images_for_page(wiki_title, max_candidates=8)
                        for alt in alt_images:
                            if alt not in self.seen_photos:
                                new_thumb = alt
                                break

                    # 3. Gán ảnh nếu hợp lệ và chưa từng xuất hiện
                    if new_thumb and new_thumb not in self.seen_photos:
                        self.seen_photos.add(new_thumb)
                        item["photo_url"] = new_thumb
                        item["photo_source"] = "Wikipedia / Wikimedia Commons"
                        enriched_count += 1
                        if verbose:
                            print(f"    -> Đã bổ sung ảnh thành công: {new_thumb[:60]}...", flush=True)

            enriched_places.append(item)

        return enriched_places, enriched_count

# ==============================================================================
# 7. CLI EXECUTION & STATS REPORTING
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(description="VNTravel AI Landmark Harvest Pipeline")
    parser.add_argument("--input", type=str, default="data/places_63_to_34.json", help="Đường dẫn file JSON đầu vào")
    parser.add_argument("--output", type=str, default=None, help="Đường dẫn lưu file JSON đầu ra sau khi làm sạch")
    parser.add_argument("--clean", action="store_true", help="Thực thi làm sạch GPS, khử ảnh SVG và khử trùng lặp")
    parser.add_argument("--enrich", action="store_true", help="Thực thi làm giàu ảnh từ Wikipedia API cho bản ghi thiếu ảnh")
    parser.add_argument("--enrich-limit", type=int, default=30, help="Số lượng địa danh tối đa cần làm giàu ảnh")
    parser.add_argument("--prune-leakage", action="store_true", help="Loại bỏ các địa danh rò rỉ chéo tỉnh (>200km)")
    parser.add_argument("--check", action="store_true", help="Chỉ kiểm tra và xuất báo cáo hiện trạng")
    args = parser.parse_args()

    input_path = os.path.join(ROOT_DIR, args.input) if not os.path.isabs(args.input) else args.input
    if not os.path.exists(input_path):
        print(f"[!] Không tìm thấy file: {input_path}")
        sys.exit(1)

    print("=" * 80)
    print(" VNTRAVEL AI - LANDMARK HARVEST & DATA CLEANING PIPELINE")
    print(f" Nguồn dữ liệu: {input_path}")
    print("=" * 80)

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    pipeline = HarvestPipeline()

    if args.check or (not args.clean and not args.enrich):
        # Báo cáo hiện trạng
        total = len(data)
        foreign = [p for p in data if is_foreign_landmark(p)[0]]
        svgs = [p for p in data if p.get("photo_url") and is_blacklisted_photo(p["photo_url"])]
        all_photos = [p["photo_url"] for p in data if p.get("photo_url")]
        unique_photos = set(all_photos)

        print(f"Tổng số bản ghi: {total}")
        print(f"Địa danh nước ngoài / ngoài ranh giới: {len(foreign)}")
        for f_item in foreign:
            print(f"  - [{f_item.get('id')}] {f_item.get('name')} ({f_item.get('lat')}, {f_item.get('lng')}): {is_foreign_landmark(f_item)[1]}")
        print(f"Ảnh SVG / Bản đồ bị cấm: {len(svgs)}")
        print(f"Tổng số ảnh: {len(all_photos)}, Số ảnh duy nhất: {len(unique_photos)}, Trùng lặp: {len(all_photos) - len(unique_photos)}")
        print("=" * 80)
        return

    # Thực thi làm sạch
    if args.clean:
        print("[*] Đang thực thi lọc GPS, khử SVG và khử trùng lặp ảnh...", flush=True)
        cleaned_data, stats = pipeline.clean_dataset(
            data,
            prune_foreign=True,
            prune_leakage=args.prune_leakage,
            sanitize_photos=True,
            normalize_schema=True
        )
        print(f" -> Ban đầu: {stats['initial_count']} | Sau làm sạch: {stats['final_count']}")
        print(f" -> Loại bỏ địa danh nước ngoài: {stats['foreign_pruned']}")
        p_stats = stats["photo_stats"]
        print(f" -> Ảnh SVG loại bỏ: {p_stats.get('blacklisted_svg_removed', 0)}")
        print(f" -> Ảnh trùng lặp nullify: {p_stats.get('duplicates_removed', 0)}")
        print(f" -> Ảnh duy nhất giữ lại: {p_stats.get('photos_retained', 0)}")
        data = cleaned_data

    # Thực thi làm giàu
    if args.enrich:
        print(f"[*] Đang làm giàu ảnh từ Wikipedia API (tối đa {args.enrich_limit} địa danh)...", flush=True)
        enriched_data, enriched_count = pipeline.enrich_missing_photos(data, max_enrich=args.enrich_limit, verbose=True)
        print(f" -> Bổ sung thành công: {enriched_count} ảnh thực tế!")
        data = enriched_data

    # Ghi file kết quả nếu có --output
    if args.output:
        out_path = os.path.join(ROOT_DIR, args.output) if not os.path.isabs(args.output) else args.output
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n[+] Đã lưu kết quả thành công vào: {out_path}")
    print("=" * 80)

if __name__ == "__main__":
    main()
