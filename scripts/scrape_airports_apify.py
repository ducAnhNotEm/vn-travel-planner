"""
scripts/scrape_airports_apify.py
Cào dữ liệu 22 Cảng hàng không / Sân bay dân dụng tại Việt Nam bằng Apify Google Maps Scraper.
Thu thập:
- Tên đầy đủ chuẩn xác thực địa
- Tọa độ lat, lng
- Mã IATA (HAN, SGN, DAD, CXR, PQC, ...)
- Địa chỉ bưu chính formatted_address
- Rating & Reviews count
- Google Place ID (ChIJ...)
- Google Maps URL xác thực
- Ảnh thực tế CDN
- Website & Hotline liên hệ
Lưu vào:
1. data/airports_vietnam.json
2. Bảng `airports` trong SQLite travel_db.db
"""

import os
import sys
import json
import sqlite3
import time
from typing import Dict, Any, List
from dotenv import load_dotenv
from apify_client import ApifyClient

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

DATA_DIR = os.path.join(ROOT_DIR, "data")
OUTPUT_JSON_PATH = os.path.join(DATA_DIR, "airports_vietnam.json")
DB_PATH = os.path.join(ROOT_DIR, "travel_db.db")

AIRPORTS_CATALOG = [
    {
        "iata_code": "HAN",
        "search_query": "Cảng hàng không quốc tế Nội Bài",
        "province_name": "Thành phố Hà Nội",
        "city_served": "Hà Nội",
        "is_international": True
    },
    {
        "iata_code": "SGN",
        "search_query": "Cảng hàng không quốc tế Tân Sơn Nhất",
        "province_name": "Thành phố Hồ Chí Minh",
        "city_served": "TP. Hồ Chí Minh",
        "is_international": True
    },
    {
        "iata_code": "DAD",
        "search_query": "Cảng hàng không quốc tế Đà Nẵng",
        "province_name": "Thành phố Đà Nẵng",
        "city_served": "Đà Nẵng",
        "is_international": True
    },
    {
        "iata_code": "CXR",
        "search_query": "Cảng hàng không quốc tế Cam Ranh",
        "province_name": "Tỉnh Khánh Hòa",
        "city_served": "Nha Trang / Cam Ranh",
        "is_international": True
    },
    {
        "iata_code": "PQC",
        "search_query": "Cảng hàng không quốc tế Phú Quốc",
        "province_name": "Tỉnh Kiên Giang",
        "city_served": "Phú Quốc",
        "is_international": True
    },
    {
        "iata_code": "HPH",
        "search_query": "Cảng hàng không quốc tế Cát Bi",
        "province_name": "Thành phố Hải Phòng",
        "city_served": "Hải Phòng",
        "is_international": True
    },
    {
        "iata_code": "VDO",
        "search_query": "Cảng hàng không quốc tế Vân Đồn",
        "province_name": "Tỉnh Quảng Ninh",
        "city_served": "Quảng Ninh / Hạ Long",
        "is_international": True
    },
    {
        "iata_code": "VCA",
        "search_query": "Cảng hàng không quốc tế Cần Thơ",
        "province_name": "Thành phố Cần Thơ",
        "city_served": "Cần Thơ",
        "is_international": True
    },
    {
        "iata_code": "HUI",
        "search_query": "Cảng hàng không quốc tế Phú Bài",
        "province_name": "Thành phố Huế",
        "city_served": "Huế",
        "is_international": True
    },
    {
        "iata_code": "DLI",
        "search_query": "Cảng hàng không quốc tế Liên Khương",
        "province_name": "Tỉnh Lâm Đồng",
        "city_served": "Đà Lạt",
        "is_international": True
    },
    {
        "iata_code": "BMV",
        "search_query": "Cảng hàng không Buôn Ma Thuột",
        "province_name": "Tỉnh Đắk Lắk",
        "city_served": "Buôn Ma Thuột",
        "is_international": False
    },
    {
        "iata_code": "UIH",
        "search_query": "Cảng hàng không Phù Cát",
        "province_name": "Tỉnh Bình Định",
        "city_served": "Quy Nhơn",
        "is_international": False
    },
    {
        "iata_code": "PXU",
        "search_query": "Cảng hàng không Pleiku",
        "province_name": "Tỉnh Gia Lai",
        "city_served": "Pleiku",
        "is_international": False
    },
    {
        "iata_code": "TBB",
        "search_query": "Cảng hàng không Tuy Hòa",
        "province_name": "Tỉnh Phú Yên",
        "city_served": "Tuy Hòa",
        "is_international": False
    },
    {
        "iata_code": "VCL",
        "search_query": "Cảng hàng không Chu Lai",
        "province_name": "Tỉnh Quảng Nam",
        "city_served": "Quảng Nam / Quảng Ngãi",
        "is_international": False
    },
    {
        "iata_code": "VDH",
        "search_query": "Cảng hàng không Đồng Hới",
        "province_name": "Tỉnh Quảng Bình",
        "city_served": "Đồng Hới",
        "is_international": False
    },
    {
        "iata_code": "VII",
        "search_query": "Cảng hàng không quốc tế Vinh",
        "province_name": "Tỉnh Nghệ An",
        "city_served": "Vinh",
        "is_international": True
    },
    {
        "iata_code": "THD",
        "search_query": "Cảng hàng không Thọ Xuân",
        "province_name": "Tỉnh Thanh Hóa",
        "city_served": "Thanh Hóa",
        "is_international": False
    },
    {
        "iata_code": "DIN",
        "search_query": "Cảng hàng không Điện Biên Phủ",
        "province_name": "Tỉnh Điện Biên",
        "city_served": "Điện Biên Phủ",
        "is_international": False
    },
    {
        "iata_code": "VCS",
        "search_query": "Cảng hàng không Côn Đảo",
        "province_name": "Tỉnh Bà Rịa - Vũng Tàu",
        "city_served": "Côn Đảo",
        "is_international": False
    },
    {
        "iata_code": "VKG",
        "search_query": "Cảng hàng không Rạch Giá",
        "province_name": "Tỉnh Kiên Giang",
        "city_served": "Rạch Giá",
        "is_international": False
    },
    {
        "iata_code": "CAH",
        "search_query": "Cảng hàng không Cà Mau",
        "province_name": "Tỉnh Cà Mau",
        "city_served": "Cà Mau",
        "is_international": False
    }
]

def run_apify_scrape(token: str) -> List[Dict[str, Any]]:
    client = ApifyClient(token)
    search_queries = [a["search_query"] for a in AIRPORTS_CATALOG]
    
    print(f"[*] Bắt đầu gửi yêu cầu cào dữ liệu cho 22 sân bay tới Apify Google Maps Scraper...")
    run_input = {
        "searchStringsArray": search_queries,
        "maxCrawledPlacesPerSearch": 1,
        "language": "vi",
        "countryCode": "vn",
        "maxImages": 1,
        "scrapeReviews": False,
        "scrapePlaceDetailPage": False,
        "scrapeContacts": False,
        "maxReviews": 0,
        "maxQuestions": 0,
        "scrapeImageAuthors": False
    }
    
    run = client.actor("compass/crawler-google-places").start(
        run_input=run_input,
        memory_mbytes=1024
    )
    
    run_id = getattr(run, "id", None) or run.get("id")
    dataset_id = getattr(run, "default_dataset_id", None) or run.get("defaultDatasetId")
    print(f"[+] Đã khởi tạo Apify Run ID: {run_id}")
    
    # Chờ run hoàn thành
    while True:
        status_info = client.run(run_id).get()
        status = getattr(status_info, "status", None) or status_info.get("status")
        print(f"    Trạng thái: {status}...")
        if status in ["SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"]:
            break
        time.sleep(5)
        
    if status != "SUCCEEDED":
        print(f"[!] Lỗi: Run kết thúc với trạng thái {status}")
        return []
        
    actual_dataset_id = getattr(status_info, "default_dataset_id", None) or status_info.get("defaultDatasetId") or dataset_id
    print(f"[✓] Run thành công! Đang tải dữ liệu từ Dataset: {actual_dataset_id}")
    
    items = []
    for item in client.dataset(actual_dataset_id).iterate_items():
        items.append(item)
        
    print(f"[✓] Đã tải về {len(items)} kết quả từ Apify.")
    return items

def process_and_save(scraped_items: List[Dict[str, Any]]):
    # Map searchString hoặc title về catalog
    catalog_by_query = {a["search_query"].lower(): a for a in AIRPORTS_CATALOG}
    
    results = []
    for cat in AIRPORTS_CATALOG:
        query_lower = cat["search_query"].lower()
        matched = None
        
        # Tìm theo searchString
        for item in scraped_items:
            s_str = (item.get("searchString") or "").lower()
            if query_lower in s_str or s_str in query_lower:
                matched = item
                break
                
        # Nếu chưa thấy, tìm theo title
        if not matched:
            for item in scraped_items:
                title = (item.get("title") or "").lower()
                iata = cat["iata_code"].lower()
                if (cat["city_served"].lower() in title) or (iata in title):
                    matched = item
                    break

        if matched:
            loc = matched.get("location") or {}
            processed = {
                "iata_code": cat["iata_code"],
                "name": matched.get("title") or cat["search_query"],
                "province_name": cat["province_name"],
                "city_served": cat["city_served"],
                "is_international": cat["is_international"],
                "lat": loc.get("lat"),
                "lng": loc.get("lng"),
                "address": matched.get("address"),
                "rating": matched.get("totalScore"),
                "review_count": matched.get("reviewsCount"),
                "google_place_id": matched.get("placeId"),
                "google_maps_url": matched.get("url"),
                "image_url": matched.get("imageUrl"),
                "phone_number": matched.get("phone"),
                "website": matched.get("website")
            }
            results.append(processed)
        else:
            print(f"[!] Cảnh báo: Không khớp kết quả cho: {cat['search_query']}")

    # Lưu ra JSON
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"[✓] Đã lưu {len(results)} sân bay vào file JSON: {OUTPUT_JSON_PATH}")

    # Cập nhật / tạo bảng airports trong travel_db.db
    if os.path.exists(DB_PATH):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS airports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                iata_code VARCHAR(10) UNIQUE NOT NULL,
                name VARCHAR(255) NOT NULL,
                province_name VARCHAR(100),
                city_served VARCHAR(100),
                is_international BOOLEAN DEFAULT 0,
                lat FLOAT NOT NULL,
                lng FLOAT NOT NULL,
                address VARCHAR(500),
                rating FLOAT,
                review_count INTEGER,
                google_place_id VARCHAR(100) UNIQUE,
                google_maps_url VARCHAR(500),
                image_url TEXT,
                phone_number VARCHAR(50),
                website VARCHAR(500)
            )
        """)
        
        for r in results:
            cur.execute("""
                INSERT INTO airports (
                    iata_code, name, province_name, city_served, is_international,
                    lat, lng, address, rating, review_count, google_place_id,
                    google_maps_url, image_url, phone_number, website
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(iata_code) DO UPDATE SET
                    name=excluded.name,
                    province_name=excluded.province_name,
                    city_served=excluded.city_served,
                    is_international=excluded.is_international,
                    lat=excluded.lat,
                    lng=excluded.lng,
                    address=excluded.address,
                    rating=excluded.rating,
                    review_count=excluded.review_count,
                    google_place_id=excluded.google_place_id,
                    google_maps_url=excluded.google_maps_url,
                    image_url=excluded.image_url,
                    phone_number=excluded.phone_number,
                    website=excluded.website
            """, (
                r["iata_code"], r["name"], r["province_name"], r["city_served"],
                1 if r["is_international"] else 0,
                r["lat"], r["lng"], r["address"], r["rating"], r["review_count"],
                r["google_place_id"], r["google_maps_url"], r["image_url"],
                r["phone_number"], r["website"]
            ))
            
        conn.commit()
        conn.close()
        print(f"[✓] Đã đồng bộ nguyên tử {len(results)} sân bay vào bảng 'airports' trong {DB_PATH}")

if __name__ == "__main__":
    token = os.getenv("APIFY_TOKEN_BACKUP") or os.getenv("APIFY_TOKEN")
    if not token:
        print("[LỖI] Thiếu APIFY_TOKEN trong .env!")
        sys.exit(1)
        
    items = run_apify_scrape(token)
    if items:
        process_and_save(items)
    else:
        print("[!] Không có dữ liệu để xử lý.")
