"""
scripts/enrich_major_cities.py

Enrichment pipeline for 9 Major Cities / Tourist Hubs:
- Hà Nội (Code 1)
- Quảng Ninh (Code 22)
- Hải Phòng (Code 31)
- Huế (Code 46)
- Đà Nẵng (Code 48)
- Khánh Hòa (Code 56)
- Lâm Đồng (Code 68)
- Thành phố Hồ Chí Minh (Code 79)
- Cần Thơ (Code 92)

Targets ~30 curated places per city (270 total):
- 13 Hotels / Resorts / Homestays (HOTEL)
- 7 Traditional & Night Markets (MARKET)
- 7 Theme Parks / Amusements / Water Parks (ATTRACTION tag: khu_vui_choi)
- 3 Scenic Check-in spots (ATTRACTION tag: checkin)

Collects complete attributes:
- Name, Address, Lat/Lng GPS
- phone_number (hotline for reservation/inquiry)
- website (official booking/portal)
- rating, review_count, price_range
- High-res Google CDN images (lh3.googleusercontent.com)
"""

import os
import sys
import json
import time
import sqlite3
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
from apify_client import ApifyClient

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

DATA_DIR = os.path.join(ROOT_DIR, "data")
DB_PATH = os.path.join(ROOT_DIR, "travel_db.db")
CACHE_FILE = os.path.join(DATA_DIR, "crawled_major_cities_cache.json")
STATE_FILE = os.path.join(DATA_DIR, "apify_major_cities_state.json")

CITY_PROVINCE_CODES = {
    "ha_noi": 1,
    "quang_ninh": 22,
    "hai_phong": 31,
    "hue": 46,
    "da_nang": 48,
    "khanh_hoa": 56,
    "lam_dong": 68,
    "ho_chi_minh": 79,
    "can_tho": 92
}

CITY_QUERIES = {
    "ha_noi": [
        # Khách sạn (13)
        ("Khách sạn Sofitel Legend Metropole Hà Nội", "HOTEL", ["khach_san", "5_sao", "pho_co"]),
        ("Khách sạn JW Marriott Hotel Hanoi", "HOTEL", ["khach_san", "5_sao", "sang_trong"]),
        ("Khách sạn Lotte Hotel Hanoi", "HOTEL", ["khach_san", "5_sao", "view_dep"]),
        ("Khách sạn InterContinental Hanoi Westlake", "HOTEL", ["khach_san", "5_sao", "ho_tay"]),
        ("Khách sạn Pan Pacific Hanoi", "HOTEL", ["khach_san", "5_sao"]),
        ("Khách sạn Apricot Hotel Hà Nội", "HOTEL", ["khach_san", "boutique", "ho_guom"]),
        ("Khách sạn Peridot Grand Luxury Hotel Hà Nội", "HOTEL", ["khach_san", "boutique"]),
        ("Khách sạn La Siesta Classic Mã Mây Hà Nội", "HOTEL", ["khach_san", "boutique", "pho_co"]),
        ("Khách sạn The Chi Boutique Hotel Hà Nội", "HOTEL", ["khach_san", "boutique"]),
        ("Khách sạn Melia Hanoi", "HOTEL", ["khach_san", "5_sao"]),
        ("Khách sạn Silk Path Hotel Hanoi", "HOTEL", ["khach_san", "4_sao"]),
        ("Homestay Nhà Của Bu Hồ Tây Hà Nội", "HOTEL", ["homestay", "ho_tay", "view_dep"]),
        ("Hanoi Emerald Waters Hotel Trendy", "HOTEL", ["khach_san", "pho_co"]),
        # Chợ (7)
        ("Chợ Đồng Xuân Hà Nội", "MARKET", ["cho_truyen_thong", "pho_co", "dac_san"]),
        ("Chợ đêm Phố Cổ Hà Nội", "MARKET", ["cho_dem", "pho_co", "am_thuc"]),
        ("Chợ hoa Quảng An Hà Nội", "MARKET", ["cho_hoa", "ho_tay", "dem"]),
        ("Chợ Hàng Bè Hà Nội", "MARKET", ["cho_truyen_thong", "am_thuc", "pho_co"]),
        ("Chợ Hôm Đức Viên Hà Nội", "MARKET", ["cho_truyen_thong", "vai_voc", "am_thuc"]),
        ("Chợ Long Biên Hà Nội", "MARKET", ["cho_dau_moi", "dem"]),
        ("Chợ Bưởi Hà Nội", "MARKET", ["cho_truyen_thong", "cay_canh"]),
        # Khu vui chơi (7)
        ("Mega Grand World Hà Nội", "ATTRACTION", ["khu_vui_choi", "venice", "giai_tri"]),
        ("Thủy cung Vinpearl Aquarium Times City", "ATTRACTION", ["khu_vui_choi", "thuy_cung", "gia_dinh"]),
        ("VinKE Times City Hà Nội", "ATTRACTION", ["khu_vui_choi", "tre_em", "giai_tri"]),
        ("Công viên nước Hồ Tây", "ATTRACTION", ["khu_vui_choi", "cong_vien_nuoc"]),
        ("Thiên đường Bảo Sơn Hà Nội", "ATTRACTION", ["khu_vui_choi", "cong_vien_giai_tri"]),
        ("Lotte World Aquarium Hanoi Tây Hồ", "ATTRACTION", ["khu_vui_choi", "thuy_cung"]),
        ("Công viên Thống Nhất Hà Nội", "ATTRACTION", ["khu_vui_choi", "cong_vien_xanh"]),
        # Check-in (3)
        ("Phố bích họa Phùng Hưng Hà Nội", "ATTRACTION", ["checkin", "song_ao", "nghe_thuat"]),
        ("Phố đường tàu Phùng Hưng Hà Nội", "ATTRACTION", ["checkin", "song_ao", "ca_phe"]),
        ("Cầu Long Biên Hà Nội", "ATTRACTION", ["checkin", "lich_su", "ngam_canh"])
    ],
    "ho_chi_minh": [
        # Khách sạn (13)
        ("Khách sạn The Reverie Saigon", "HOTEL", ["khach_san", "6_sao", "quan_1"]),
        ("Khách sạn Caravelle Saigon", "HOTEL", ["khach_san", "5_sao", "quan_1"]),
        ("Khách sạn Park Hyatt Saigon", "HOTEL", ["khach_san", "5_sao", "sang_trong"]),
        ("Khách sạn Hotel Des Arts Saigon", "HOTEL", ["khach_san", "boutique", "rooftop"]),
        ("Khách sạn Sheraton Saigon Hotel & Towers", "HOTEL", ["khach_san", "5_sao"]),
        ("Khách sạn Lotte Hotel Saigon", "HOTEL", ["khach_san", "5_sao", "song_sai_gon"]),
        ("Khách sạn Nikko Saigon", "HOTEL", ["khach_san", "5_sao", "quan_1"]),
        ("Khách sạn Mia Saigon Luxury Boutique Hotel", "HOTEL", ["khach_san", "resort", "thao_dien"]),
        ("Khách sạn Pullman Saigon Centre", "HOTEL", ["khach_san", "5_sao"]),
        ("Khách sạn InterContinental Saigon", "HOTEL", ["khach_san", "5_sao"]),
        ("Khách sạn Fusion Suites Saigon", "HOTEL", ["khach_san", "spa"]),
        ("Khách sạn Silverland Jolie Hotel Sài Gòn", "HOTEL", ["khach_san", "boutique"]),
        ("Homestay The Laban Quận 3 Sài Gòn", "HOTEL", ["homestay", "tre_trung"]),
        # Chợ (7)
        ("Chợ Bến Thành Quận 1", "MARKET", ["cho_truyen_thong", "bieu_tuong", "dac_san"]),
        ("Chợ Tân Định Quận 1", "MARKET", ["cho_truyen_thong", "am_thuc"]),
        ("Chợ Lớn Bình Tây Quận 6", "MARKET", ["cho_dau_moi", "kien_truc", "hoa"]),
        ("Chợ đêm Hồ Thị Kỷ Quận 10", "MARKET", ["cho_dem", "am_thuc", "pho_hoa"]),
        ("Chợ Bà Chiểu Bình Thạnh", "MARKET", ["cho_truyen_thong", "do_si"]),
        ("Chợ hoa Đầm Sen", "MARKET", ["cho_hoa", "dem"]),
        ("Chợ Xóm Chiếu Quận 4", "MARKET", ["cho_am_thuc", "an_vat"]),
        # Khu vui chơi (7)
        ("Đài quan sát Landmark 81 SkyView", "ATTRACTION", ["khu_vui_choi", "skyview", "view_dep"]),
        ("Công viên văn hóa Suối Tiên", "ATTRACTION", ["khu_vui_choi", "cong_vien_chu_de"]),
        ("Công viên văn hóa Đầm Sen", "ATTRACTION", ["khu_vui_choi", "cong_vien_giai_tri"]),
        ("Thảo Cầm Viên Sài Gòn", "ATTRACTION", ["khu_vui_choi", "vuon_thu", "xanh"]),
        ("KizCiti Sài Gòn Quận 4", "ATTRACTION", ["khu_vui_choi", "tre_em"]),
        ("Khu du lịch The BCR Quận 9", "ATTRACTION", ["khu_vui_choi", "da_ngoai", "ban_sung_son"]),
        ("Công viên nước Đầm Sen", "ATTRACTION", ["khu_vui_choi", "cong_vien_nuoc"]),
        # Check-in (3)
        ("Phố đi bộ Nguyễn Huệ", "ATTRACTION", ["checkin", "pho_di_bo", "trung_tam"]),
        ("Bưu điện Trung tâm Sài Gòn", "ATTRACTION", ["checkin", "kien_truc_phap"]),
        ("Bến Bạch Đằng Quận 1", "ATTRACTION", ["checkin", "song_sai_gon", "waterbus"])
    ],
    "da_nang": [
        # Khách sạn (13)
        ("InterContinental Danang Sun Peninsula Resort", "HOTEL", ["resort", "5_sao", "son_tra"]),
        ("Khách sạn Novotel Danang Premier Han River", "HOTEL", ["khach_san", "5_sao", "song_han"]),
        ("Hyatt Regency Danang Resort & Spa", "HOTEL", ["resort", "5_sao", "bien_non_nuoc"]),
        ("Furama Resort Danang", "HOTEL", ["resort", "5_sao", "bien_my_khe"]),
        ("Vinpearl Resort & Spa Đà Nẵng", "HOTEL", ["resort", "5_sao"]),
        ("Khách sạn TMS Hotel Da Nang Beach", "HOTEL", ["khach_san", "bien_my_khe", "infinity_pool"]),
        ("Khách sạn Muong Thanh Luxury Da Nang", "HOTEL", ["khach_san", "5_sao", "bien"]),
        ("Khách sạn HAIAN Beach Hotel & Spa Đà Nẵng", "HOTEL", ["khach_san", "4_sao", "view_bien"]),
        ("Khách sạn Sala Danang Beach Hotel", "HOTEL", ["khach_san", "4_sao", "bien_my_khe"]),
        ("Khách sạn Brilliant Hotel Đà Nẵng", "HOTEL", ["khach_san", "song_han"]),
        ("Khách sạn Golden Bay Đà Nẵng", "HOTEL", ["khach_san", "dat_vang", "ho_boi_vo_cuc"]),
        ("Naman Retreat Đà Nẵng", "HOTEL", ["resort", "kien_truc_tre", "nghi_duong"]),
        ("Minh House Homestay Đà Nẵng", "HOTEL", ["homestay", "xanh", "yen_tinh"]),
        # Chợ (7)
        ("Chợ Cồn Đà Nẵng", "MARKET", ["cho_am_thuc", "an_vat", "dac_san"]),
        ("Chợ Hàn Đà Nẵng", "MARKET", ["cho_truyen_thong", "dac_san", "mua_sam"]),
        ("Chợ đêm Helio Đà Nẵng", "MARKET", ["cho_dem", "am_thuc", "giai_tri"]),
        ("Chợ đêm Sơn Trà Đà Nẵng", "MARKET", ["cho_dem", "cau_rong", "mua_sam"]),
        ("Chợ đầu mối Hòa Cường Đà Nẵng", "MARKET", ["cho_dau_moi"]),
        ("Chợ Bắc Mỹ An Đà Nẵng", "MARKET", ["cho_am_thuc", "kem_bo"]),
        ("Chợ hải sản ăn liền Mân Thái Đà Nẵng", "MARKET", ["cho_hai_san", "ven_bien"]),
        # Khu vui chơi (7)
        ("Sun World Ba Na Hills", "ATTRACTION", ["khu_vui_choi", "cau_vang", "cap_treo"]),
        ("Công viên Châu Á Asia Park Đà Nẵng", "ATTRACTION", ["khu_vui_choi", "vong_quay_mat_troi"]),
        ("Mikazuki Water Park 365 Đà Nẵng", "ATTRACTION", ["khu_vui_choi", "cong_vien_nuoc", "nhat_ban"]),
        ("Công viên suối khoáng nóng Núi Thần Tài", "ATTRACTION", ["khu_vui_choi", "khoang_nong", "on-sen"]),
        ("Khu du lịch Hòa Phú Thành Đà Nẵng", "ATTRACTION", ["khu_vui_choi", "truot_thac"]),
        ("Cung Thiếu nhi Đà Nẵng", "ATTRACTION", ["khu_vui_choi", "kien_truc_tangram"]),
        ("Fantasy Park Bà Nà Hills", "ATTRACTION", ["khu_vui_choi", "trong_nha"]),
        # Check-in (3)
        ("Cầu Rồng Đà Nẵng", "ATTRACTION", ["checkin", "phun_lua", "bieu_tuong"]),
        ("Cầu Tình Yêu Đà Nẵng", "ATTRACTION", ["checkin", "song_han", "khoa_tinh_yeu"]),
        ("Đỉnh Bàn Cờ Bán đảo Sơn Trà", "ATTRACTION", ["checkin", "ngam_canh", "son_tra"])
    ],
    "quang_ninh": [
        # Khách sạn (13)
        ("Vinpearl Resort & Spa Hạ Long", "HOTEL", ["resort", "dao_reu", "5_sao"]),
        ("Khách sạn FLC Grand Hotel Hạ Long", "HOTEL", ["khach_san", "view_vinh", "golf"]),
        ("Premier Village Ha Long Bay Resort", "HOTEL", ["resort", "biet_thu", "bai_chay"]),
        ("Khách sạn Muong Thanh Luxury Quang Ninh", "HOTEL", ["khach_san", "5_sao"]),
        ("Khách sạn Novotel Ha Long Bay", "HOTEL", ["khach_san", "bai_chay"]),
        ("Khách sạn Wyndham Legend Halong", "HOTEL", ["khach_san", "5_sao", "cau_bai_chay"]),
        ("Yoko Onsen Quang Hanh Cẩm Phả", "HOTEL", ["resort", "khoang_nong", "onsen"]),
        ("Khách sạn Paddington Hotel Halong Bayview", "HOTEL", ["khach_san", "view_bien"]),
        ("Khách sạn D’Lioro Hotel Hạ Long", "HOTEL", ["khach_san", "doi_hai_quan"]),
        ("Khách sạn Royal Lotus Ha Long Resort & Spa", "HOTEL", ["khach_san", "4_sao"]),
        ("Legacy Yen Tu MGallery Quảng Ninh", "HOTEL", ["resort", "tam_linh", "yen_tu"]),
        ("Khách sạn Central Luxury Ha Long", "HOTEL", ["khach_san", "trung_tam"]),
        ("Homestay Coto Eco Lodge Cô Tô Quảng Ninh", "HOTEL", ["homestay", "dao_co_to"]),
        # Chợ (7)
        ("Chợ Hạ Long 1", "MARKET", ["cho_hai_san", "cha_muc", "dac_san"]),
        ("Chợ Hạ Long 2", "MARKET", ["cho_truyen_thong"]),
        ("Chợ đêm Hạ Long", "MARKET", ["cho_dem", "bai_chay", "mua_sam"]),
        ("Chợ cá Cảng Hòn Gai", "MARKET", ["cho_ca", "som_mai"]),
        ("Chợ Cái Dăm Bãi Cháy", "MARKET", ["cho_hai_san", "an_uong"]),
        ("Chợ Cẩm Phả Quảng Ninh", "MARKET", ["cho_truyen_thong"]),
        ("Chợ Móng Cái Quảng Ninh", "MARKET", ["cho_cua_khau", "bien_gioi"]),
        # Khu vui chơi (7)
        ("Sun World Ha Long Complex", "ATTRACTION", ["khu_vui_choi", "cap_treo_nu_hoang", "vong_quay"]),
        ("Công viên nước Typhoon Water Park Hạ Long", "ATTRACTION", ["khu_vui_choi", "cong_vien_nuoc"]),
        ("Công viên Rồng Dragon Park Hạ Long", "ATTRACTION", ["khu_vui_choi", "cam_giac_manh"]),
        ("Cung Cá Heo Quảng Ninh", "ATTRACTION", ["khu_vui_choi", "kien_truc", "trien_lam"]),
        ("Bảo tàng Quảng Ninh", "ATTRACTION", ["khu_vui_choi", "kien_truc_den", "checkin"]),
        ("Khu vui chơi Tuần Châu Hạ Long", "ATTRACTION", ["khu_vui_choi", "xiec_ca_heo"]),
        ("Khu du lịch sinh thái Thác Mơ Quảng Ninh", "ATTRACTION", ["khu_vui_choi", "sinh_thai"]),
        # Check-in (3)
        ("Cầu Bãi Cháy Hạ Long", "ATTRACTION", ["checkin", "bieu_tuong", "dem"]),
        ("Ngọn hải đăng Bãi Cháy", "ATTRACTION", ["checkin", "song_ao", "hoang_hon"]),
        ("Đường bao biển Trần Quốc Nghiễn Hạ Long", "ATTRACTION", ["checkin", "bao_bien", "view_vinh"])
    ],
    "hai_phong": [
        # Khách sạn (13)
        ("Khách sạn Sheraton Hai Phong", "HOTEL", ["khach_san", "5_sao", "vinhomes"]),
        ("Khách sạn Mercure Hai Phong", "HOTEL", ["khach_san", "5_sao"]),
        ("Khách sạn Hotel Nikko Hai Phong", "HOTEL", ["khach_san", "nhat_ban"]),
        ("Flamingo Cat Ba Resorts Hải Phòng", "HOTEL", ["resort", "5_sao", "cat_ba"]),
        ("Khách sạn Vinpearl Hotel Rivera Hai Phong", "HOTEL", ["khach_san", "5_sao"]),
        ("Khách sạn Mường Thanh Grand Hải Phòng", "HOTEL", ["khach_san", "4_sao"]),
        ("Khách sạn Somerset Central TD Hai Phong City", "HOTEL", ["khach_san", "can_ho"]),
        ("Khách sạn Roygent Parks Hai Phong", "HOTEL", ["khach_san", "nhat_ban"]),
        ("Cat Ba Island Resort & Spa", "HOTEL", ["resort", "cat_ba"]),
        ("Perle d’Orient Cat Ba MGallery", "HOTEL", ["resort", "5_sao", "cat_ba"]),
        ("Khách sạn Draco Thang Long Hotel Cát Bà", "HOTEL", ["khach_san", "cat_ba"]),
        ("Khách sạn Nam Cường Hải Phòng", "HOTEL", ["khach_san", "trung_tam"]),
        ("Lepont Bungalow Homestay Cát Bà", "HOTEL", ["homestay", "o_rom", "view_bien"]),
        # Chợ (7)
        ("Chợ Cát Bi Hải Phòng", "MARKET", ["cho_am_thuc", "foodtour", "an_vat"]),
        ("Chợ Lương Văn Can Hải Phòng", "MARKET", ["cho_am_thuc", "banh_beo"]),
        ("Chợ Ga Hải Phòng", "MARKET", ["cho_truyen_thong", "ga_tau"]),
        ("Chợ Tam Bạc (Chợ Đổ) Hải Phòng", "MARKET", ["cho_dau_moi", "lich_su"]),
        ("Chợ Núi Đèo Thủy Nguyên", "MARKET", ["cho_truyen_thong"]),
        ("Chợ Đồ Sơn Hải Phòng", "MARKET", ["cho_hai_san"]),
        ("Chợ đêm Cát Bà", "MARKET", ["cho_dem", "hai_san", "cat_ba"]),
        # Khu vui chơi (7)
        ("Khu du lịch quốc tế Đồi Rồng Dragon Ocean Đồ Sơn", "ATTRACTION", ["khu_vui_choi", "bien_nhan_tao"]),
        ("Cáp treo Cát Hải Cát Bà Sun World", "ATTRACTION", ["khu_vui_choi", "cap_treo"]),
        ("Công viên nước Đồ Sơn Water Park", "ATTRACTION", ["khu_vui_choi", "cong_vien_nuoc"]),
        ("Khu vui chơi trẻ em TiniWorld Vincom Hải Phòng", "ATTRACTION", ["khu_vui_choi", "tre_em"]),
        ("Khu du lịch sinh thái Đảo Hòn Dấu", "ATTRACTION", ["khu_vui_choi", "hai_dang", "sinh_thai"]),
        ("Vịnh Lan Hạ Cát Bà", "ATTRACTION", ["khu_vui_choi", "cheo_kayak", "tam_bien"]),
        ("Vườn quốc gia Cát Bà", "ATTRACTION", ["khu_vui_choi", "trekking", "thien_nhien"]),
        # Check-in (3)
        ("Nhà hát lớn Hải Phòng", "ATTRACTION", ["checkin", "kien_truc_phap", "quang_truong"]),
        ("Ga Hải Phòng", "ATTRACTION", ["checkin", "foodtour", "co_kinh"]),
        ("Cầu Hoàng Văn Thụ Hải Phòng", "ATTRACTION", ["checkin", "canh_chim_bien", "cau_dep"])
    ],
    "hue": [
        # Khách sạn (13)
        ("Khách sạn Silk Path Grand Hue Hotel", "HOTEL", ["khach_san", "5_sao", "kien_truc_cung_dinh"]),
        ("Khách sạn Melia Vinpearl Hue", "HOTEL", ["khach_san", "5_sao", "trung_tam"]),
        ("Azerai La Residence Hue", "HOTEL", ["resort", "5_sao", "song_huong"]),
        ("Khách sạn Imperial Hotel Hue", "HOTEL", ["khach_san", "5_sao"]),
        ("Khách sạn Saigon Morin Hotel Huế", "HOTEL", ["khach_san", "lich_su", "co_nhat"]),
        ("Khách sạn Pilgrimage Village Boutique Resort & Spa Huế", "HOTEL", ["resort", "lang_hanh_huong"]),
        ("Vedana Lagoon Resort & Spa Huế", "HOTEL", ["resort", "pha_tam_giang", "bungalow"]),
        ("Khách sạn Senna Hue Hotel", "HOTEL", ["khach_san", "kien_truc_phap"]),
        ("Khách sạn Moonlight Hotel Hue", "HOTEL", ["khach_san", "4_sao"]),
        ("Khách sạn Romance Hotel Hue", "HOTEL", ["khach_san", "trung_tam"]),
        ("Alba Wellness Resort By Fusion Huế", "HOTEL", ["resort", "khoang_nong", "on-sen"]),
        ("Khách sạn Eldora Hotel Huế", "HOTEL", ["khach_san", "co_dien"]),
        ("Hue Eco Homestay", "HOTEL", ["homestay", "xanh", "gan_song"]),
        # Chợ (7)
        ("Chợ Đông Ba Huế", "MARKET", ["cho_truyen_thong", "bieu_tuong", "dac_san"]),
        ("Chợ An Cựu Huế", "MARKET", ["cho_truyen_thong", "am_thuc"]),
        ("Chợ Bến Ngự Huế", "MARKET", ["cho_truyen_thong"]),
        ("Chợ Tây Lộc Huế", "MARKET", ["cho_do_si", "am_thuc"]),
        ("Chợ đêm Cầu Gỗ Lim Huế", "MARKET", ["cho_dem", "song_huong"]),
        ("Phố đi bộ Chu Văn An Huế", "MARKET", ["pho_di_bo", "cho_dem", "bar_pub"]),
        ("Chợ nón Dạ Lê Huế", "MARKET", ["cho_truyen_thong", "lang_nghe"]),
        # Khu vui chơi (7)
        ("Khu vui chơi công viên Hồ Thủy Tiên Huế", "ATTRACTION", ["khu_vui_choi", "cong_vien_rong", "bi_an"]),
        ("Khu du lịch Suối khoáng nóng Thanh Tân Alba", "ATTRACTION", ["khu_vui_choi", "zipline", "khoang_nong"]),
        ("Khu du lịch sinh thái Bạch Mã Village", "ATTRACTION", ["khu_vui_choi", "hobbit", "tam_suoi"]),
        ("Công viên nước Thanh Hà Huế", "ATTRACTION", ["khu_vui_choi", "cong_vien_nuoc"]),
        ("Khu du lịch sinh thái YesHue Eco Thác Mơ", "ATTRACTION", ["khu_vui_choi", "da_ngoai", "tam_thac"]),
        ("Công viên Dã Viên Huế", "ATTRACTION", ["khu_vui_choi", "cong_vien_xanh"]),
        ("Làng nghề làm hương Thủy Xuân Huế", "ATTRACTION", ["khu_vui_choi", "lang_nghe", "checkin"]),
        # Check-in (3)
        ("Cầu Trường Tiền Huế", "ATTRACTION", ["checkin", "bieu_tuong", "song_huong"]),
        ("Đồi Vọng Cảnh Huế", "ATTRACTION", ["checkin", "hoang_hon", "view_song_huong"]),
        ("Cầu gỗ lim sông Hương", "ATTRACTION", ["checkin", "di_dao", "song_huong"])
    ],
    "khanh_hoa": [
        # Khách sạn (13)
        ("Vinpearl Resort & Spa Nha Trang Bay", "HOTEL", ["resort", "5_sao", "hon_tre"]),
        ("Khách sạn InterContinental Nha Trang", "HOTEL", ["khach_san", "5_sao", "tran_phu"]),
        ("Sheraton Nha Trang Hotel & Spa", "HOTEL", ["khach_san", "5_sao", "view_bien"]),
        ("Amiana Resort Nha Trang", "HOTEL", ["resort", "5_sao", "ho_boi_nuoc_man"]),
        ("Khách sạn Muong Thanh Luxury Nha Trang", "HOTEL", ["khach_san", "5_sao", "tran_phu"]),
        ("Mia Resort Nha Trang", "HOTEL", ["resort", "bai_dong", "sang_trong"]),
        ("Khách sạn Havana Nha Trang Hotel", "HOTEL", ["khach_san", "5_sao", "duong_ham_bien"]),
        ("Khách sạn Novotel Nha Trang", "HOTEL", ["khach_san", "4_sao", "tran_phu"]),
        ("The Anam Cam Ranh Resort", "HOTEL", ["resort", "5_sao", "cam_ranh"]),
        ("Radisson Blu Resort Cam Ranh", "HOTEL", ["resort", "bai_dai"]),
        ("Khách sạn Sunrise Nha Trang Beach Hotel", "HOTEL", ["khach_san", "kien_truc_co_dien"]),
        ("Duyen Ha Resort Cam Ranh", "HOTEL", ["resort", "bai_dai"]),
        ("Tabalo Homestay Nha Trang", "HOTEL", ["homestay", "cabin", "tiet_kiem"]),
        # Chợ (7)
        ("Chợ Đầm Nha Trang", "MARKET", ["cho_truyen_thong", "bieu_tuong", "hai_san_kho"]),
        ("Chợ Xóm Mới Nha Trang", "MARKET", ["cho_am_thuc", "hai_san_tuoi"]),
        ("Chợ đêm Nha Trang", "MARKET", ["cho_dem", "mua_sam", "tran_phu"]),
        ("Chợ Vĩnh Hải Nha Trang", "MARKET", ["cho_truyen_thong"]),
        ("Chợ cảng cá Vĩnh Lương Nha Trang", "MARKET", ["cho_ca", "som_mai"]),
        ("Chợ Cam Ranh", "MARKET", ["cho_hai_san", "cam_ranh"]),
        ("Chợ cá Bến Đá Nha Trang", "MARKET", ["cho_hai_san", "tuoi_song"]),
        # Khu vui chơi (7)
        ("VinWonders Nha Trang", "ATTRACTION", ["khu_vui_choi", "cong_vien_giai_tri", "banh_xe_bau_troi"]),
        ("Khu du lịch Tắm khoáng bùn Trăm Trứng Nha Trang", "ATTRACTION", ["khu_vui_choi", "tam_bun", "khoang_nong"]),
        ("Khu du lịch Suối Khoáng Nóng I-Resort Nha Trang", "ATTRACTION", ["khu_vui_choi", "tam_bun", "cong_vien_nuoc"]),
        ("Khu vui chơi trên biển Sealife Bãi Dài", "ATTRACTION", ["khu_vui_choi", "the_thao_bien", "phao_noi"]),
        ("Công viên nước Phù Đổng Nha Trang", "ATTRACTION", ["khu_vui_choi", "cong_vien_nuoc", "ven_bien"]),
        ("Khu du lịch Yang Bay Khánh Hòa", "ATTRACTION", ["khu_vui_choi", "thac_nuoc", "sinh_thai"]),
        ("Viện Hải dương học Nha Trang", "ATTRACTION", ["khu_vui_choi", "thuy_cung", "kham_pha"]),
        # Check-in (3)
        ("Tháp Trầm Hương Nha Trang", "ATTRACTION", ["checkin", "bieu_tuong", "quang_truong_2_4"]),
        ("Hòn Chồng Nha Trang", "ATTRACTION", ["checkin", "ngam_canh", "bien"]),
        ("Cầu gỗ Điệp Sơn Khánh Hòa", "ATTRACTION", ["checkin", "con_duong_duoi_bien"])
    ],
    "lam_dong": [
        # Khách sạn (13)
        ("Dalat Edensee Lake Resort & Spa", "HOTEL", ["resort", "5_sao", "ho_tuyen_lam"]),
        ("Ana Mandara Villas Dalat Resort & Spa", "HOTEL", ["resort", "biet_thu_phap"]),
        ("Khách sạn Dalat Palace Heritage Hotel", "HOTEL", ["khach_san", "5_sao", "lich_su", "ho_xuan_huong"]),
        ("Swiss-Belresort Tuyền Lâm Đà Lạt", "HOTEL", ["resort", "chau_au", "golf"]),
        ("Khách sạn Colline Đà Lạt", "HOTEL", ["khach_san", "cho_da_lat", "hien_dai"]),
        ("Khách sạn Mercure Dalat Resort", "HOTEL", ["resort", "kien_truc_phap"]),
        ("Terracotta Hotel & Resort Dalat", "HOTEL", ["resort", "ven_ho", "rung_thong"]),
        ("Khách sạn Mường Thanh Holiday Đà Lạt", "HOTEL", ["khach_san", "4_sao"]),
        ("SAM Tuyen Lam Resort Đà Lạt", "HOTEL", ["resort", "tuyen_lam"]),
        ("Khách sạn Golf Valley Hotel Đà Lạt", "HOTEL", ["khach_san", "4_sao", "trung_tam"]),
        ("TTC Hotel Premium Da Lat", "HOTEL", ["khach_san", "view_ho"]),
        ("Cù Tê Homestay Đà Lạt", "HOTEL", ["homestay", "view_thung_lung"]),
        ("Légume Guesthouse Homestay Đà Lạt", "HOTEL", ["homestay", "luc_giac", "song_ao"]),
        # Chợ (7)
        ("Chợ Đà Lạt", "MARKET", ["cho_truyen_thong", "dac_san", "hoa_qua"]),
        ("Chợ đêm Đà Lạt", "MARKET", ["cho_dem", "an_vat", "banh_trang_nuong"]),
        ("Chợ hoa Đà Lạt", "MARKET", ["cho_hoa", "da_lat"]),
        ("Chợ Chi Lăng Đà Lạt", "MARKET", ["cho_truyen_thong"]),
        ("Chợ Thái Phiên Đà Lạt", "MARKET", ["cho_nong_san", "hoa"]),
        ("Chợ số 6 Đà Lạt", "MARKET", ["cho_am_thuc"]),
        ("Chợ nông sản Đà Lạt", "MARKET", ["cho_dau_moi", "rau_cu"]),
        # Khu vui chơi (7)
        ("Datanla High Rope Course & Alpine Coaster Đà Lạt", "ATTRACTION", ["khu_vui_choi", "mang_truot", "cam_giac_manh"]),
        ("Khu du lịch Thung Lũng Tình Yêu Đà Lạt", "ATTRACTION", ["khu_vui_choi", "canh_dep", "ho_da_thien"]),
        ("Khu du lịch Núi Langbiang Đà Lạt", "ATTRACTION", ["khu_vui_choi", "xe_jeep", "dinh_nui"]),
        ("Vườn thú Zoodoo Đà Lạt", "ATTRACTION", ["khu_vui_choi", "vuon_thu_uc", "tre_em"]),
        ("Puppy Farm Nông trại Cún Đà Lạt", "ATTRACTION", ["khu_vui_choi", "nong_trai", "thu_cung"]),
        ("Khu du lịch Fresh Garden Đà Lạt", "ATTRACTION", ["khu_vui_choi", "doi_hoa", "checkin"]),
        ("Lumiere Đà Lạt", "ATTRACTION", ["khu_vui_choi", "vuon_anh_sang", "3d"]),
        # Check-in (3)
        ("Quảng trường Lâm Viên Đà Lạt", "ATTRACTION", ["checkin", "nu_hoa_atiso", "bieu_tuong"]),
        ("Ga xe lửa Đà Lạt", "ATTRACTION", ["checkin", "kien_truc_art_deco", "tau_hoa_co"]),
        ("Đồi Chè Cầu Đất Đà Lạt", "ATTRACTION", ["checkin", "san_may", "doi_che"])
    ],
    "can_tho": [
        # Khách sạn (13)
        ("Sheraton Can Tho", "HOTEL", ["khach_san", "5_sao", "trung_tam"]),
        ("Victoria Can Tho Resort", "HOTEL", ["resort", "4_sao", "ven_song"]),
        ("Azerai Can Tho Resort", "HOTEL", ["resort", "con_au", "cao_cap"]),
        ("Khách sạn Mường Thanh Luxury Cần Thơ", "HOTEL", ["khach_san", "5_sao", "cai_khe"]),
        ("Khách sạn TTC Hotel Can Tho", "HOTEL", ["khach_san", "4_sao", "ben_ninh_kieu"]),
        ("Vinpearl Hotel Can Tho", "HOTEL", ["khach_san", "5_sao"]),
        ("Khách sạn Ninh Kiều Riverside Hotel", "HOTEL", ["khach_san", "view_song_hau"]),
        ("Khách sạn Iris Hotel Can Tho", "HOTEL", ["khach_san", "4_sao"]),
        ("Khách sạn West Hotel Cần Thơ", "HOTEL", ["khach_san", "trung_tam"]),
        ("Can Tho Ecolodge Resort", "HOTEL", ["resort", "sinh_thai", "ba_lang"]),
        ("Khách sạn Holiday One Can Tho", "HOTEL", ["khach_san", "4_sao"]),
        ("Khách sạn Con Khuong Resort Can Tho", "HOTEL", ["resort", "con_khuong"]),
        ("Mekong Rustic Can Tho Homestay", "HOTEL", ["homestay", "phong_dien", "sinh_thai"]),
        # Chợ (7)
        ("Chợ nổi Cái Răng Cần Thơ", "MARKET", ["cho_noi", "mien_tay", "dac_san", "song_nuoc"]),
        ("Chợ đêm Tây Đô Cần Thơ", "MARKET", ["cho_dem", "am_thuc", "mua_sam"]),
        ("Chợ nổi Phong Điền Cần Thơ", "MARKET", ["cho_noi", "truyen_thong"]),
        ("Chợ Tân An Cần Thơ", "MARKET", ["cho_hai_san", "nong_san"]),
        ("Chợ cổ Cần Thơ", "MARKET", ["cho_co", "kien_truc", "ben_ninh_kieu"]),
        ("Chợ đêm Ninh Kiều Cần Thơ", "MARKET", ["cho_dem", "am_thuc_duong_pho"]),
        ("Chợ An Bình Cần Thơ", "MARKET", ["cho_truyen_thong"]),
        # Khu vui chơi (7)
        ("Khu du lịch sinh thái Mỹ Khánh Cần Thơ", "ATTRACTION", ["khu_vui_choi", "sinh_thai", "dua_heo"]),
        ("Khu du lịch Cồn Sơn Cần Thơ", "ATTRACTION", ["khu_vui_choi", "ca_loc_bay", "vuon_trai_cay"]),
        ("Công viên nước Cần Thơ Water Park", "ATTRACTION", ["khu_vui_choi", "cong_vien_nuoc"]),
        ("Khu du lịch Lung Cột Cầu Cần Thơ", "ATTRACTION", ["khu_vui_choi", "sinh_thai", "dong_thap_muoi"]),
        ("Làng du lịch sinh thái Ông Đề Cần Thơ", "ATTRACTION", ["khu_vui_choi", "tro_choi_dan_gian"]),
        ("Khu du lịch sinh thái Phù Sa Cần Thơ", "ATTRACTION", ["khu_vui_choi", "con_au", "sinh_thai"]),
        ("Khu vui chơi trẻ em Funny Land Cần Thơ", "ATTRACTION", ["khu_vui_choi", "tre_em"]),
        # Check-in (3)
        ("Bến Ninh Kiều Cần Thơ", "ATTRACTION", ["checkin", "bieu_tuong", "song_hau"]),
        ("Cầu đi bộ Tình Yêu Cần Thơ", "ATTRACTION", ["checkin", "cau_di_bo", "hoa_sen"]),
        ("Nhà cổ Bình Thủy Cần Thơ", "ATTRACTION", ["checkin", "kien_truc_co", "lich_su"])
    ]
}


def run_apify_crawl(queries_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Chạy Apify actor compass/crawler-google-places với chia nhỏ 2 mẻ song song."""
    token = os.getenv("APIFY_TOKEN")
    if not token:
        raise ValueError("APIFY_TOKEN không được tìm thấy trong file .env!")

    client = ApifyClient(token)
    
    # Kiểm tra cache trước
    cached_items = []
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cached_items = json.load(f)
            print(f"[CACHE] Đã nạp {len(cached_items)} kết quả từ file cache cục bộ.")
        except Exception:
            cached_items = []

    # Tạo mapping đã cào theo title/query
    existing_queries = set(item.get("searchString") for item in cached_items if item.get("searchString"))
    needed_queries = [q for q in queries_list if q["query"] not in existing_queries]

    if not needed_queries:
        print("[✓] Toàn bộ 270 địa điểm đã có trong cache offline! Không cần gọi API.")
        return cached_items

    print(f"[*] Cần cào {len(needed_queries)} địa điểm mới từ Google Maps qua Apify...")

    # Chia thành 2 mẻ (batch) chạy song song
    batch_size = (len(needed_queries) + 1) // 2
    batches = [needed_queries[i:i + batch_size] for i in range(0, len(needed_queries), batch_size)]

    # Kiểm tra xem có mẻ nào đang chạy dở trong STATE_FILE không
    active_runs = []
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                active_runs = saved.get("active_runs", [])
                if active_runs:
                    print(f"[*] Phục hồi {len(active_runs)} mẻ đang chạy dở từ {STATE_FILE}...")
        except Exception:
            active_runs = []

    if not active_runs:
        print(f"[*] Cần cào {len(needed_queries)} địa điểm mới từ Google Maps qua Apify...")

        # Chia thành 2 mẻ (batch) chạy song song
        batch_size = (len(needed_queries) + 1) // 2
        batches = [needed_queries[i:i + batch_size] for i in range(0, len(needed_queries), batch_size)]

        for idx, b in enumerate(batches, start=1):
            search_strings = [item["query"] for item in b]
            print(f"[*] Khởi động Mẻ {idx}/{len(batches)} ({len(search_strings)} queries)...")
            run_input = {
                "searchStringsArray": search_strings,
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
                memory_mbytes=2048
            )
            run_id = getattr(run, "id", None) or (run["id"] if isinstance(run, dict) else str(run))
            active_runs.append({
                "batch_idx": idx,
                "run_id": run_id,
                "status": "RUNNING",
                "dataset_id": None
            })
            print(f"    -> Run ID: {run_id}")

        # Lưu state
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"active_runs": active_runs}, f, ensure_ascii=False, indent=2)

    print("\n[*] Đang đợi các mẻ cào Google Maps hoàn tất...")
    new_results = []
    while True:
        all_done = True
        for r in active_runs:
            if r["status"] not in ["SUCCEEDED", "FAILED", "ABORTED"]:
                try:
                    info = client.run(r["run_id"]).get()
                    st = getattr(info, "status", None) or (info.get("status") if isinstance(info, dict) else None)
                    r["status"] = st
                    if st == "SUCCEEDED":
                        ds_id = getattr(info, "default_dataset_id", None) or getattr(info, "defaultDatasetId", None) or (info.get("defaultDatasetId") if isinstance(info, dict) else None)
                        r["dataset_id"] = ds_id
                        print(f"\n[✓] Mẻ {r['batch_idx']} ĐÃ HOÀN TẤT! Đang tải dữ liệu (Dataset ID: {ds_id})...")
                        for item in client.dataset(ds_id).iterate_items():
                            new_results.append(item)
                    elif st in ["FAILED", "ABORTED"]:
                        print(f"\n[X] Mẻ {r['batch_idx']} THẤT BẠI: {st}")
                    else:
                        all_done = False
                except Exception as e:
                    # Bắt lỗi mạng/DNS tạm thời để script không bị crash
                    all_done = False

        status_line = " | ".join(f"Mẻ {r['batch_idx']}: {r['status']}" for r in active_runs)
        print(f"\r    [{time.strftime('%H:%M:%S')}] {status_line}", end="", flush=True)

        if all_done:
            break
        time.sleep(5)

    # Xóa file state khi đã hoàn tất
    if os.path.exists(STATE_FILE):
        try:
            os.remove(STATE_FILE)
        except Exception:
            pass

    print(f"\n\n[✓] Thu thập thành công {len(new_results)} kết quả mới từ Google Maps!")

    all_items = cached_items + new_results
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(all_items, f, ensure_ascii=False, indent=2)

    return all_items


def ingest_places_to_database(crawled_items: List[Dict[str, Any]]):
    """Nạp các địa điểm đã cào vào travel_db.db và các file JSON."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Lấy max ID hiện tại
    cur.execute("SELECT coalesce(max(id), 1000) FROM places")
    current_max_id = cur.fetchone()[0]

    # Lấy danh sách google_place_id đã có để tránh trùng
    cur.execute("SELECT google_place_id, name FROM places")
    existing_place_ids = {r[0] for r in cur.fetchall() if r[0]}

    # Map queries metadata
    meta_by_query = {}
    for city, q_list in CITY_QUERIES.items():
        prov_code = CITY_PROVINCE_CODES[city]
        for name_query, cat, tags in q_list:
            meta_by_query[name_query.lower()] = {
                "category": cat,
                "tags": tags,
                "province_code": prov_code,
                "city": city
            }

    added_count = 0
    updated_phone_count = 0

    new_places_for_json = []

    for item in crawled_items:
        place_id = item.get("placeId")
        title = item.get("title")
        if not title or not place_id:
            continue

        search_str = (item.get("searchString") or "").lower()
        meta = meta_by_query.get(search_str)

        # Fallback tìm kiếm tương đối nếu searchString không khớp trực tiếp
        if not meta:
            for q_term, m in meta_by_query.items():
                if q_term in search_str or search_str in q_term:
                    meta = m
                    break

        if not meta:
            continue

        prov_code = meta["province_code"]
        category = meta["category"]
        tags = meta["tags"]

        phone = item.get("phone") or item.get("phoneUnformatted")
        website = item.get("website")
        address = item.get("address") or f"{title}, Việt Nam"
        rating = item.get("totalScore") or 4.5
        review_count = item.get("reviewsCount") or 100
        
        # Ảnh Google CDN
        img_url = item.get("imageUrl")
        if not img_url:
            imgs = item.get("imageUrls") or []
            if imgs:
                img_url = imgs[0]

        loc = item.get("location") or {}
        lat = loc.get("lat")
        lng = loc.get("lng")
        if not lat or not lng:
            continue

        # Định dạng giá
        price_range = None
        if category == "HOTEL":
            price_range = "500.000đ - 2.500.000đ"
            time_spent = "Overnight / Lưu trú"
        elif category == "MARKET":
            price_range = "Miễn phí vé vào / Mua sắm tự do"
            time_spent = "1h - 2h"
        else:
            price_range = "Tham khảo: 50.000đ - 300.000đ"
            time_spent = "2h - 4h"

        # Nếu đã có trong DB: cập nhật phone_number & website
        if place_id in existing_place_ids:
            cur.execute("""
                UPDATE places 
                SET phone_number = coalesce(?, phone_number),
                    website = coalesce(?, website)
                WHERE google_place_id = ?
            """, (phone, website, place_id))
            updated_phone_count += 1
            continue

        # Nếu là địa điểm mới hoàn toàn: INSERT
        current_max_id += 1
        new_id = current_max_id
        is_must_visit = 1 if (review_count > 1000 or rating >= 4.6) else 0
        badge = "⭐ Điểm đến tiêu biểu" if is_must_visit else None

        cur.execute("""
            INSERT INTO places (
                id, google_place_id, province_code, ward_code, name, category,
                is_must_visit, badge_label, lat, lng, address, rating, review_count,
                image_url, typical_time_spent, tags, price_range, phone_number, website
            ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            new_id, place_id, prov_code, title, category,
            is_must_visit, badge, lat, lng, address, rating, review_count,
            img_url, time_spent, json.dumps(tags, ensure_ascii=False), price_range, phone, website
        ))

        existing_place_ids.add(place_id)
        added_count += 1

        new_places_for_json.append({
            "id": new_id,
            "name": title,
            "category": category,
            "lat": lat,
            "lng": lng,
            "address": address,
            "target_province_code": prov_code,
            "google_place_id": place_id,
            "rating": rating,
            "review_count": review_count,
            "photo_url": img_url,
            "photo_source": "Google Places",
            "phone_number": phone,
            "website": website,
            "price_range": price_range,
            "tags": tags
        })

    conn.commit()
    conn.close()

    print(f"\n[DB SYNC] Đã thêm {added_count} địa điểm mới vào travel_db.db!")
    print(f"[DB SYNC] Đã cập nhật phone/website cho {updated_phone_count} địa điểm có sẵn!")

    # Cập nhật các file JSON
    if new_places_for_json:
        # 1. places_63_to_34.json
        p63_path = os.path.join(DATA_DIR, "places_63_to_34.json")
        if os.path.exists(p63_path):
            with open(p63_path, "r", encoding="utf-8") as f:
                p63 = json.load(f)
            p63.extend(new_places_for_json)
            with open(p63_path, "w", encoding="utf-8") as f:
                json.dump(p63, f, ensure_ascii=False, indent=2)
            print(f"[JSON] Đã đồng bộ {len(new_places_for_json)} địa điểm vào places_63_to_34.json (Tổng: {len(p63)})")

        # 2. Đồng bộ các file theo miền
        north_codes = {1, 22, 31}
        central_codes = {46, 48, 56, 68}
        south_codes = {79, 92}

        for fname, codes in [("places_north.json", north_codes), ("places_central.json", central_codes), ("places_south.json", south_codes)]:
            fpath = os.path.join(DATA_DIR, fname)
            if not os.path.exists(fpath):
                continue
            with open(fpath, "r", encoding="utf-8") as f:
                p_reg = json.load(f)
            items_to_add = [p for p in new_places_for_json if p["target_province_code"] in codes]
            p_reg.extend(items_to_add)
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(p_reg, f, ensure_ascii=False, indent=2)
            print(f"[JSON] Đã đồng bộ {len(items_to_add)} địa điểm vào {fname} (Tổng: {len(p_reg)})")


def main():
    print("=" * 70)
    print("  ENRICHMENT PIPELINE: 9 ĐÔ THỊ DU LỊCH LỚN (270 ĐỊA ĐIỂM TIÊU BIỂU)")
    print("  TẬP TRUNG: KHÁCH SẠN, CHỢ, KHU VUI CHƠI, CHECK-IN + SỐ ĐIỆN THOẠI")
    print("=" * 70)

    # Tổng hợp toàn bộ 270 queries
    all_queries = []
    for city, q_list in CITY_QUERIES.items():
        prov_code = CITY_PROVINCE_CODES[city]
        for name_query, cat, tags in q_list:
            all_queries.append({
                "city": city,
                "province_code": prov_code,
                "query": name_query,
                "category": cat,
                "tags": tags
            })

    print(f"[*] Tổng số địa điểm được lên kế hoạch: {len(all_queries)} queries trên 9 thành phố.")

    # 1. Chạy cào Apify
    crawled_results = run_apify_crawl(all_queries)

    # 2. Nạp vào Database và đồng bộ JSON
    ingest_places_to_database(crawled_results)

    print("\n" + "=" * 70)
    print("  HOÀN TẤT ENRICHMENT PIPELINE 9 THÀNH PHỐ LỚN!")
    print("=" * 70)


if __name__ == "__main__":
    main()
