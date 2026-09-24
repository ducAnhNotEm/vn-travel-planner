import json
import os
from typing import List, Dict, Any

PROVINCES_JSON_PATH = os.path.join("data", "provinces_v2.json")

def load_provinces_from_json() -> List[Dict[str, Any]]:
    """
    Đọc trực tiếp dữ liệu 34 Tỉnh thành từ file JSON trong folder data/provinces_v2.json
    """
    if not os.path.exists(PROVINCES_JSON_PATH):
        raise FileNotFoundError(f"Không tìm thấy file JSON tại {PROVINCES_JSON_PATH}")
        
    with open(PROVINCES_JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data

def get_province_by_code_from_json(code: int) -> Dict[str, Any]:
    """
    Tìm thông tin tỉnh thành theo mã code trực tiếp từ file JSON
    """
    provinces = load_provinces_from_json()
    for p in provinces:
        if p.get("code") == code:
            return p
    return None

if __name__ == "__main__":
    provinces = load_provinces_from_json()
    print(f" Đã đọc thành công {len(provinces)} tỉnh thành từ file data/provinces_v2.json!")
