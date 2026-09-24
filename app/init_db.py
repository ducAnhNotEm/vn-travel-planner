import json
import os
from app.database import engine, SessionLocal
from app.models import Base, Province, Ward, ProvinceType

# 1. Danh sách 21 tỉnh/thành giáp biển theo quy hoạch sáp nhập 34 tỉnh thành 2026:
COASTAL_CODENAMES = {
    "quang_ninh", "hai_phong", "hung_yen", "ninh_binh", "thanh_hoa",
    "nghe_an", "ha_tinh", "quang_tri", "hue", "da_nang",
    "quang_ngai", "gia_lai", "khanh_hoa", "dak_lak", "lam_dong",
    "ho_chi_minh", "dong_thap", "vinh_long", "can_tho", "an_giang", "ca_mau"
}

# 2. Các đô thị lớn / trung tâm du lịch sầm uất (MAJOR):
MAJOR_CODENAMES = {
    "ha_noi", "ho_chi_minh", "da_nang", "quang_ninh", "khanh_hoa",
    "lam_dong", "hue", "hai_phong", "can_tho"
}

# 3. BẢNG ÁNH XẠ ĐẦY ĐỦ 100% TOÀN BỘ 34 TỈNH/THÀNH PHỐ THUỘC DỰ ÁN:
CITY_NAME_MAP = {
    "ha_noi": "Hanoi",
    "cao_bang": "Cao Bang",
    "tuyen_quang": "Tuyen Quang",
    "dien_bien": "Dien Bien",
    "lai_chau": "Lai Chau",
    "son_la": "Son La",
    "lao_cai": "Lao Cai",
    "thai_nguyen": "Thai Nguyen",
    "lang_son": "Lang Son",
    "quang_ninh": "Quang Ninh",
    "bac_ninh": "Bac Ninh",
    "phu_tho": "Phu Tho",
    "hai_phong": "Hai Phong",
    "hung_yen": "Hung Yen",
    "ninh_binh": "Ninh Binh",
    "thanh_hoa": "Thanh Hoa",
    "nghe_an": "Nghe An",
    "ha_tinh": "Ha Tinh",
    "quang_tri": "Quang Tri",
    "hue": "Hue",
    "da_nang": "Da Nang",
    "quang_ngai": "Quang Ngai",
    "gia_lai": "Gia Lai",
    "khanh_hoa": "Nha Trang",
    "dak_lak": "Dak Lak",
    "lam_dong": "Da Lat",
    "dong_nai": "Dong Nai",
    "ho_chi_minh": "Ho Chi Minh",
    "tay_ninh": "Tay Ninh",
    "dong_thap": "Dong Thap",
    "vinh_long": "Vinh Long",
    "an_giang": "An Giang",
    "can_tho": "Can Tho",
    "ca_mau": "Ca Mau"
}

def init_database():
    print("1. Creating Database Tables...")
    Base.metadata.create_all(bind=engine)

    json_path = os.path.join("data", "provinces_v2.json")
    if not os.path.exists(json_path):
        print(f"File {json_path} not found.")
        return

    print("2. Ingesting 34 Provinces and Wards with FULL 34 CITY_NAME_MAP...")
    db = SessionLocal()
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            provinces_data = json.load(f)

        for item in provinces_data:
            prov_code = item["code"]
            codename = item.get("codename", "")
            has_sea = codename in COASTAL_CODENAMES
            
            # Phân loại province_type: MAJOR, COASTAL, hoặc REGULAR
            if codename in MAJOR_CODENAMES:
                p_type = ProvinceType.MAJOR
                scrape_limit = 100
            elif has_sea:
                p_type = ProvinceType.COASTAL
                scrape_limit = 50
            else:
                p_type = ProvinceType.REGULAR
                scrape_limit = 20

            city_name = CITY_NAME_MAP.get(codename, item["name"].replace("Thành phố ", "").replace("Tỉnh ", ""))

            prov = db.query(Province).filter_by(code=prov_code).first()
            if not prov:
                prov = Province(
                    code=prov_code,
                    name=item["name"],
                    codename=codename,
                    city_name=city_name,
                    division_type=item.get("division_type"),
                    is_in_project=True,
                    province_type=p_type,
                    has_sea=has_sea,
                    scrape_limit=scrape_limit
                )
                db.add(prov)
            else:
                prov.city_name = city_name
                prov.has_sea = has_sea
                prov.province_type = p_type
                prov.scrape_limit = scrape_limit

            # Nạp danh sách Xã/Phường
            for w in item.get("wards", []):
                w_code = w["code"]
                ward = db.query(Ward).filter_by(code=w_code).first()
                if not ward:
                    ward = Ward(
                        code=w_code,
                        province_code=prov_code,
                        name=w["name"],
                        codename=w.get("codename"),
                        division_type=w.get("division_type")
                    )
                    db.add(ward)

        db.commit()
        print(" Successfully updated ALL 34 Provinces in CITY_NAME_MAP!")

    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    init_database()
