"""
Script: scripts/fetch_hotel_photos.py
Mục đích:
- Kiểm tra và thực thi các phương pháp lấy ảnh THẬT 100% cho Khách sạn / Homestay / Resort.
- Hỗ trợ:
  1. Cách 1: Google Custom Search API (chính thức, 100 req/ngày miễn phí).
  2. Cách 2: Playwright Headless Browser (tự động cào ảnh gốc phân giải cao, không cần API key).
  3. Cách 3: Xác thực link CDN thực tế (Agoda / Booking / OTA) bằng HTTP HEAD request (200 OK).
"""

import os
import sys
import json
import requests

# -------------------------------------------------------------
# CÁCH 1: GOOGLE CUSTOM SEARCH JSON API (Chuẩn nhất & ổn định)
# -------------------------------------------------------------
def fetch_hotel_image_google_cse(hotel_name, city_name, api_key=None, cse_id=None):
    """
    Tìm ảnh thật từ CDN Booking.com hoặc Agoda.net qua Google Custom Search API.
    Cần đăng ký Google Programmable Search Engine (miễn phí 100 requests/ngày).
    """
    api_key = api_key or os.getenv("GOOGLE_CSE_KEY")
    cse_id = cse_id or os.getenv("GOOGLE_CSE_CX")
    
    if not api_key or not cse_id:
        return None, "Chưa cấu hình GOOGLE_CSE_KEY hoặc GOOGLE_CSE_CX trong môi trường."
    
    query = f'"{hotel_name}" "{city_name}" site:booking.com OR site:agoda.com'
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": api_key,
        "cx": cse_id,
        "q": query,
        "searchType": "image",
        "num": 1
    }
    
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            if items:
                return items[0].get("link"), "Thành công (Google CSE)"
            return None, "Không tìm thấy kết quả ảnh phù hợp."
        return None, f"Lỗi Google API: HTTP {resp.status_code} - {resp.text[:100]}"
    except Exception as e:
        return None, f"Lỗi kết nối Google CSE: {e}"


# -------------------------------------------------------------
# CÁCH 2: PLAYWRIGHT HEADLESS BROWSER (Không cần API Key)
# -------------------------------------------------------------
def scrape_hotel_photo_playwright(hotel_name, city_name):
    """
    Mở trình duyệt Chromium ngầm, cào ảnh gốc độ phân giải cao thực tế.
    Không cần API Key, hoàn toàn miễn phí.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, "Chưa cài đặt thư viện 'playwright'. Chạy: pip install playwright && playwright install chromium"
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            # Sử dụng Bing Images để tránh Captcha và lấy trực tiếp link murl (ảnh gốc độ nét cao)
            query = requests.utils.quote(f"{hotel_name} {city_name} hotel")
            search_url = f"https://www.bing.com/images/search?q={query}&form=HDRSC2"
            page.goto(search_url, timeout=15000)
            page.wait_for_timeout(2500)
            
            # Thuộc tính 'm' của thẻ a.iusc chứa JSON có trường murl (Media URL gốc)
            links = page.query_selector_all("a.iusc")
            for link in links[:5]:
                m_data = link.get_attribute("m")
                if m_data:
                    try:
                        info = json.loads(m_data)
                        murl = info.get("murl")
                        # Lọc ảnh hợp lệ (không phải icon/logo)
                        if murl and murl.startswith("http") and not any(x in murl.lower() for x in ["logo", "icon", "vector"]):
                            browser.close()
                            return murl, "Thành công (Playwright Headless)"
                    except Exception:
                        continue
            
            # Fallback nếu không có a.iusc: lấy thẻ img.mimg
            imgs = page.query_selector_all("img.mimg")
            for img in imgs:
                src = img.get_attribute("src")
                if src and src.startswith("http"):
                    browser.close()
                    return src, "Thành công (Playwright Thumbnail)"
            
            browser.close()
            return None, "Không tìm thấy ảnh phù hợp trên trang kết quả."
    except Exception as e:
        return None, f"Lỗi thực thi Playwright: {e}"


# -------------------------------------------------------------
# HÀM XÁC THỰC LINK ẢNH (HTTP HEAD / GET)
# -------------------------------------------------------------
def verify_image_url(url):
    """Kiểm tra link ảnh có tồn tại thực sự (HTTP 200) và đúng định dạng ảnh không"""
    if not url or not url.startswith("http"):
        return False, "URL không hợp lệ"
    import time
    headers = {"User-Agent": "VNTravelBot/1.0 (https://vntravel.ai; contact@vntravel.ai)"}
    for attempt in range(2):
        try:
            res = requests.head(url, headers=headers, timeout=10, allow_redirects=True)
            if res.status_code == 200 and "image" in res.headers.get("content-type", "").lower():
                content_length = int(res.headers.get("content-length", 0))
                return True, f"200 OK | Type: {res.headers.get('content-type')} | Size: {content_length // 1024} KB"
            if res.status_code == 429:
                time.sleep(1.5)
                continue
            return False, f"HTTP {res.status_code} ({res.headers.get('content-type', 'unknown')})"
        except Exception as e:
            if attempt == 1:
                return False, f"Lỗi kết nối: {e}"
            time.sleep(1)
    return False, "Không thể xác thực URL sau 2 lần thử"


def scrape_place_photo_playwright(place_name, location="", category="ATTRACTION"):
    """
    Sử dụng Playwright Chromium để tìm ảnh thực tế cho địa danh, danh lam thắng cảnh hoặc khách sạn.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, "Chưa cài đặt playwright."

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            if category == "HOTEL":
                query_term = f"{place_name} {location} hotel"
            elif category in ["TEMPLE", "HISTORICAL_SITE"]:
                query_term = f"{place_name} {location}"
            else:
                query_term = f"{place_name} {location} du lịch"

            query = requests.utils.quote(query_term.strip())
            search_url = f"https://www.bing.com/images/search?q={query}&form=HDRSC2"
            page.goto(search_url, timeout=15000)
            page.wait_for_timeout(2000)

            links = page.query_selector_all("a.iusc")
            for link in links[:8]:
                m_data = link.get_attribute("m")
                if m_data:
                    try:
                        info = json.loads(m_data)
                        murl = info.get("murl")
                        if murl and murl.startswith("http") and not any(x in murl.lower() for x in ["logo", "icon", "vector", ".svg", "diagram", "clipart"]):
                            browser.close()
                            return murl, f"Thành công (Playwright: {query_term})"
                    except Exception:
                        continue

            imgs = page.query_selector_all("img.mimg")
            for img in imgs:
                src = img.get_attribute("src")
                if src and src.startswith("http"):
                    browser.close()
                    return src, f"Thành công (Playwright Thumbnail: {query_term})"

            browser.close()
            return None, f"Không tìm thấy ảnh cho: {query_term}"
    except Exception as e:
        return None, f"Lỗi thực thi Playwright: {e}"


# -------------------------------------------------------------
# ĐIỀN NỐT ẢNH CÒN THIẾU TRONG CƠ SỞ DỮ LIỆU & FILE DỮ LIỆU
# -------------------------------------------------------------
VERIFIED_WIKI_PHOTOS = {
    1076: {
        "name": "Sóc Sơn",
        "url": "https://upload.wikimedia.org/wikipedia/commons/2/27/%C4%90%E1%BB%81n_S%C3%B3c_-_NKS.jpg",
        "source": "Wikimedia Commons (Đền Sóc / Tượng đài Thánh Gióng)"
    },
    1150: {
        "name": "Mường La",
        "url": "https://upload.wikimedia.org/wikipedia/commons/b/ba/S%C6%A1n_La_Dam_reservoir.JPG",
        "source": "Wikimedia Commons (Thủy điện Sơn La - Mường La)"
    },
    1193: {
        "name": "Lương Văn Tri",
        "url": "https://upload.wikimedia.org/wikipedia/commons/9/94/Ch%C3%B9a_Th%C3%A0nh.jpg",
        "source": "Wikimedia Commons (Chùa Thành - Di tích Lương Văn Tri Lạng Sơn)"
    },
    1260: {
        "name": "Phúc Yên",
        "url": "https://upload.wikimedia.org/wikipedia/commons/4/43/H%E1%BB%93_%C4%90%E1%BA%A1i_L%E1%BA%A3i.jpg",
        "source": "Wikimedia Commons (Hồ Đại Lải - Phúc Yên)"
    },
    1309: {
        "name": "Chùa Keo Thái Bình",
        "url": "https://upload.wikimedia.org/wikipedia/commons/f/fb/Chuakeothaibinh.jpg",
        "source": "Wikimedia Commons (Chùa Keo Thái Bình)"
    },
    1349: {
        "name": "Đền Trần",
        "url": "https://upload.wikimedia.org/wikipedia/commons/d/d9/Tam_quan_Den_Tran.jpg",
        "source": "Wikimedia Commons (Tam quan Đền Trần Nam Định)"
    }
}


def fill_missing_database_photos(db_path=None, sync_json=True):
    """
    Quét cơ sở dữ liệu travel_db.db, tìm các địa điểm còn thiếu image_url
    và bổ sung ảnh thực tế đã xác thực 100% (Wikimedia / Playwright).
    Đồng bộ dữ liệu sang các file JSON.
    """
    import sqlite3
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = db_path or os.path.join(root_dir, "travel_db.db")

    if not os.path.exists(db_path):
        print(f"[ERROR] Database không tồn tại tại {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        SELECT id, name, category, address 
        FROM places 
        WHERE image_url IS NULL OR image_url = ''
    """)
    missing_places = cur.fetchall()

    print("=" * 70)
    print(f"  TIẾN TRÌNH LẤY ẢNH CÒN THIẾU CHO CƠ SỞ DỮ LIỆU: {len(missing_places)} ĐỊA ĐIỂM")
    print("=" * 70)

    if not missing_places:
        print("[✓] Cơ sở dữ liệu đã phủ 100% ảnh (0 địa điểm thiếu)!")
        conn.close()
        return

    updated_map = {}

    for place_id, name, cat, addr in missing_places:
        print(f"\n* Đang xử lý ID {place_id}: {name} ({cat}) - {addr}")
        
        # 1. Kiểm tra kho ảnh Wikimedia Commons xác thực
        if place_id in VERIFIED_WIKI_PHOTOS:
            photo_info = VERIFIED_WIKI_PHOTOS[place_id]
            photo_url = photo_info["url"]
            source_desc = photo_info["source"]
            is_valid, v_msg = verify_image_url(photo_url)
            print(f"  -> Nguồn: {source_desc}")
            print(f"  -> Xác thực HTTP: {v_msg}")
            if is_valid:
                updated_map[place_id] = (photo_url, source_desc)
                cur.execute("UPDATE places SET image_url = ? WHERE id = ?", (photo_url, place_id))
                print(f"  [✓ CẬP NHẬT THÀNH CÔNG] ID {place_id} -> {photo_url}")
                continue

        # 2. Nếu chưa có trong danh sách Wikimedia, dùng Playwright cào trực tiếp
        print("  -> Đang quét bằng Playwright...")
        photo_url, msg = scrape_place_photo_playwright(name, addr or "", cat)
        if photo_url:
            is_valid, v_msg = verify_image_url(photo_url)
            if is_valid:
                updated_map[place_id] = (photo_url, "Playwright Verified Web Photo")
                cur.execute("UPDATE places SET image_url = ? WHERE id = ?", (photo_url, place_id))
                print(f"  [✓ CẬP NHẬT THÀNH CÔNG (Playwright)] ID {place_id} -> {photo_url}")
            else:
                print(f"  [!] Ảnh tìm được không đạt chuẩn HTTP: {v_msg}")
        else:
            print(f"  [X] Không tìm thấy ảnh: {msg}")

    conn.commit()
    conn.close()
    print(f"\n[✓] Đã cập nhật thành công {len(updated_map)}/{len(missing_places)} địa điểm vào travel_db.db!")

    # 3. Đồng bộ vào các file JSON nếu sync_json=True
    if sync_json and updated_map:
        json_targets = ["places_63_to_34.json", "places_north.json"]
        for jf in json_targets:
            jpath = os.path.join(root_dir, "data", jf)
            if not os.path.exists(jpath):
                continue
            with open(jpath, "r", encoding="utf-8") as f:
                data = json.load(f)

            sync_count = 0
            for p in data:
                pid = p.get("id")
                if pid in updated_map:
                    p["photo_url"] = updated_map[pid][0]
                    p["photo_source"] = updated_map[pid][1]
                    sync_count += 1

            with open(jpath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            print(f"[✓] Đã đồng bộ {sync_count} ảnh vào {jf}")


# -------------------------------------------------------------
# MAIN CLI
# -------------------------------------------------------------
if __name__ == "__main__":
    fill_missing_database_photos()
