import os
import hashlib
import urllib.request
import urllib.error
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

CACHE_DIR = Path("data/map_cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

GOONG_API_KEY = os.getenv("GOONG_API_KEY")

def get_static_route_image(
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
    vehicle: str = "car",
    width: int = 600,
    height: int = 350
) -> Optional[bytes]:
    """
    Tạo ảnh bản đồ tĩnh thể hiện lộ trình thực tế qua Goong Maps API với bộ nhớ đệm (Cache).
    Bảo vệ API Key tuyệt đối trong Backend và tiết kiệm quota.
    """
    if not GOONG_API_KEY:
        return None

    # Ánh xạ phương tiện sang chuẩn Goong API ('car', 'bike', 'taxi')
    v_map = {
        "motorbike": "bike",
        "car": "car",
        "taxi": "taxi",
        "van": "car",
        "bus": "car"
    }
    goong_vehicle = v_map.get(vehicle.lower(), "car")

    # Tạo khóa hash cho cache
    cache_key = hashlib.md5(
        f"{origin_lat:.4f},{origin_lng:.4f}_{dest_lat:.4f},{dest_lng:.4f}_{goong_vehicle}_{width}_{height}".encode()
    ).hexdigest()
    
    cache_file = CACHE_DIR / f"{cache_key}.png"
    if cache_file.exists():
        try:
            return cache_file.read_bytes()
        except Exception:
            pass

    # Gọi Goong Static Map Route API
    api_url = (
        f"https://rsapi.goong.io/staticmap/route?"
        f"origin={origin_lat},{origin_lng}&"
        f"destination={dest_lat},{dest_lng}&"
        f"vehicle={goong_vehicle}&"
        f"width={width}&height={height}&"
        f"api_key={GOONG_API_KEY}"
    )

    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0 (Vietnam Travel Planner)"})
        with urllib.request.urlopen(req, timeout=8) as response:
            if response.status == 200:
                image_bytes = response.read()
                # Lưu vào cache đệm
                cache_file.write_bytes(image_bytes)
                return image_bytes
    except Exception as e:
        print(f"[Goong Map Service] Lỗi tải bản đồ tĩnh: {e}")
        return None

    return None
