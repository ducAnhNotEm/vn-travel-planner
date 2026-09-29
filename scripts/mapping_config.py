"""
Cấu hình chuẩn hóa:
1. Bảng ánh xạ 63 tỉnh thành trước sáp nhập sang 34 tỉnh thành sau quy hoạch.
2. Quy tắc fallback thời gian và khoảng giá (Human biological rhythm).
"""

MAPPING_63_TO_34 = {
    # Miền Bắc - Đồng bằng sông Hồng (10)
    "Hà Nội": {"target_code": 1, "target_name": "Thành phố Hà Nội", "region": "Đồng bằng sông Hồng"},
    "Hải Phòng": {"target_code": 31, "target_name": "Thành phố Hải Phòng", "region": "Đồng bằng sông Hồng"},
    "Hải Dương": {"target_code": 31, "target_name": "Thành phố Hải Phòng", "region": "Đồng bằng sông Hồng"},
    "Bắc Ninh": {"target_code": 24, "target_name": "Tỉnh Bắc Ninh", "region": "Đồng bằng sông Hồng"},
    "Hà Nam": {"target_code": 37, "target_name": "Tỉnh Ninh Bình", "region": "Đồng bằng sông Hồng"},
    "Nam Định": {"target_code": 37, "target_name": "Tỉnh Ninh Bình", "region": "Đồng bằng sông Hồng"},
    "Ninh Bình": {"target_code": 37, "target_name": "Tỉnh Ninh Bình", "region": "Đồng bằng sông Hồng"},
    "Hưng Yên": {"target_code": 33, "target_name": "Tỉnh Hưng Yên", "region": "Đồng bằng sông Hồng"},
    "Thái Bình": {"target_code": 33, "target_name": "Tỉnh Hưng Yên", "region": "Đồng bằng sông Hồng"},
    "Vĩnh Phúc": {"target_code": 25, "target_name": "Tỉnh Phú Thọ", "region": "Đồng bằng sông Hồng"},
    
    # Miền Bắc - Đông Bắc Bộ (9)
    "Bắc Giang": {"target_code": 24, "target_name": "Tỉnh Bắc Ninh", "region": "Đông Bắc Bộ"},
    "Bắc Kạn": {"target_code": 19, "target_name": "Tỉnh Thái Nguyên", "region": "Đông Bắc Bộ"},
    "Cao Bằng": {"target_code": 4, "target_name": "Tỉnh Cao Bằng", "region": "Đông Bắc Bộ"},
    "Hà Giang": {"target_code": 8, "target_name": "Tỉnh Tuyên Quang", "region": "Đông Bắc Bộ"},
    "Lạng Sơn": {"target_code": 20, "target_name": "Tỉnh Lạng Sơn", "region": "Đông Bắc Bộ"},
    "Phú Thọ": {"target_code": 25, "target_name": "Tỉnh Phú Thọ", "region": "Đông Bắc Bộ"},
    "Quảng Ninh": {"target_code": 22, "target_name": "Tỉnh Quảng Ninh", "region": "Đông Bắc Bộ"},
    "Thái Nguyên": {"target_code": 19, "target_name": "Tỉnh Thái Nguyên", "region": "Đông Bắc Bộ"},
    "Tuyên Quang": {"target_code": 8, "target_name": "Tỉnh Tuyên Quang", "region": "Đông Bắc Bộ"},
    
    # Miền Bắc - Tây Bắc Bộ (6)
    "Điện Biên": {"target_code": 11, "target_name": "Tỉnh Điện Biên", "region": "Tây Bắc Bộ"},
    "Hòa Bình": {"target_code": 25, "target_name": "Tỉnh Phú Thọ", "region": "Tây Bắc Bộ"},
    "Lai Châu": {"target_code": 12, "target_name": "Tỉnh Lai Châu", "region": "Tây Bắc Bộ"},
    "Lào Cai": {"target_code": 15, "target_name": "Tỉnh Lào Cai", "region": "Tây Bắc Bộ"},
    "Sơn La": {"target_code": 14, "target_name": "Tỉnh Sơn La", "region": "Tây Bắc Bộ"},
    "Yên Bái": {"target_code": 15, "target_name": "Tỉnh Lào Cai", "region": "Tây Bắc Bộ"},
    
    # Miền Trung - Bắc Trung Bộ (6)
    "Hà Tĩnh": {"target_code": 42, "target_name": "Tỉnh Hà Tĩnh", "region": "Bắc Trung Bộ"},
    "Nghệ An": {"target_code": 40, "target_name": "Tỉnh Nghệ An", "region": "Bắc Trung Bộ"},
    "Quảng Bình": {"target_code": 44, "target_name": "Tỉnh Quảng Trị", "region": "Bắc Trung Bộ"},
    "Quảng Trị": {"target_code": 44, "target_name": "Tỉnh Quảng Trị", "region": "Bắc Trung Bộ"},
    "Thanh Hóa": {"target_code": 38, "target_name": "Tỉnh Thanh Hóa", "region": "Bắc Trung Bộ"},
    "Thừa Thiên Huế": {"target_code": 46, "target_name": "Thành phố Huế", "region": "Bắc Trung Bộ"},
    
    # Miền Trung - Duyên hải Nam Trung Bộ (8)
    "Đà Nẵng": {"target_code": 48, "target_name": "Thành phố Đà Nẵng", "region": "Duyên hải Nam Trung Bộ"},
    "Bình Định": {"target_code": 52, "target_name": "Tỉnh Gia Lai", "region": "Duyên hải Nam Trung Bộ"},
    "Bình Thuận": {"target_code": 68, "target_name": "Tỉnh Lâm Đồng", "region": "Duyên hải Nam Trung Bộ"},
    "Khánh Hòa": {"target_code": 56, "target_name": "Tỉnh Khánh Hòa", "region": "Duyên hải Nam Trung Bộ"},
    "Ninh Thuận": {"target_code": 56, "target_name": "Tỉnh Khánh Hòa", "region": "Duyên hải Nam Trung Bộ"},
    "Phú Yên": {"target_code": 66, "target_name": "Tỉnh Đắk Lắk", "region": "Duyên hải Nam Trung Bộ"},
    "Quảng Nam": {"target_code": 48, "target_name": "Thành phố Đà Nẵng", "region": "Duyên hải Nam Trung Bộ"},
    "Quảng Ngãi": {"target_code": 51, "target_name": "Tỉnh Quảng Ngãi", "region": "Duyên hải Nam Trung Bộ"},
    
    # Miền Trung - Tây Nguyên (5)
    "Đắk Lắk": {"target_code": 66, "target_name": "Tỉnh Đắk Lắk", "region": "Tây Nguyên"},
    "Đắk Nông": {"target_code": 68, "target_name": "Tỉnh Lâm Đồng", "region": "Tây Nguyên"},
    "Gia Lai": {"target_code": 52, "target_name": "Tỉnh Gia Lai", "region": "Tây Nguyên"},
    "Kon Tum": {"target_code": 51, "target_name": "Tỉnh Quảng Ngãi", "region": "Tây Nguyên"},
    "Lâm Đồng": {"target_code": 68, "target_name": "Tỉnh Lâm Đồng", "region": "Tây Nguyên"},
    
    # Miền Nam - Đông Nam Bộ (6)
    "TP. Hồ Chí Minh": {"target_code": 79, "target_name": "Thành phố Hồ Chí Minh", "region": "Đông Nam Bộ"},
    "Bà Rịa – Vũng Tàu": {"target_code": 79, "target_name": "Thành phố Hồ Chí Minh", "region": "Đông Nam Bộ"},
    "Bình Dương": {"target_code": 79, "target_name": "Thành phố Hồ Chí Minh", "region": "Đông Nam Bộ"},
    "Bình Phước": {"target_code": 75, "target_name": "Tỉnh Đồng Nai", "region": "Đông Nam Bộ"},
    "Đồng Nai": {"target_code": 75, "target_name": "Tỉnh Đồng Nai", "region": "Đông Nam Bộ"},
    "Tây Ninh": {"target_code": 80, "target_name": "Tỉnh Tây Ninh", "region": "Đông Nam Bộ"},
    
    # Miền Nam - Đồng bằng sông Cửu Long (13)
    "Cần Thơ": {"target_code": 92, "target_name": "Thành phố Cần Thơ", "region": "Đồng bằng sông Cửu Long"},
    "An Giang": {"target_code": 91, "target_name": "Tỉnh An Giang", "region": "Đồng bằng sông Cửu Long"},
    "Bạc Liêu": {"target_code": 96, "target_name": "Tỉnh Cà Mau", "region": "Đồng bằng sông Cửu Long"},
    "Bến Tre": {"target_code": 86, "target_name": "Tỉnh Vĩnh Long", "region": "Đồng bằng sông Cửu Long"},
    "Cà Mau": {"target_code": 96, "target_name": "Tỉnh Cà Mau", "region": "Đồng bằng sông Cửu Long"},
    "Đồng Tháp": {"target_code": 82, "target_name": "Tỉnh Đồng Tháp", "region": "Đồng bằng sông Cửu Long"},
    "Hậu Giang": {"target_code": 92, "target_name": "Thành phố Cần Thơ", "region": "Đồng bằng sông Cửu Long"},
    "Kiên Giang": {"target_code": 91, "target_name": "Tỉnh An Giang", "region": "Đồng bằng sông Cửu Long"},
    "Long An": {"target_code": 80, "target_name": "Tỉnh Tây Ninh", "region": "Đồng bằng sông Cửu Long"},
    "Sóc Trăng": {"target_code": 92, "target_name": "Thành phố Cần Thơ", "region": "Đồng bằng sông Cửu Long"},
    "Tiền Giang": {"target_code": 82, "target_name": "Tỉnh Đồng Tháp", "region": "Đồng bằng sông Cửu Long"},
    "Trà Vinh": {"target_code": 86, "target_name": "Tỉnh Vĩnh Long", "region": "Đồng bằng sông Cửu Long"},
    "Vĩnh Long": {"target_code": 86, "target_name": "Tỉnh Vĩnh Long", "region": "Đồng bằng sông Cửu Long"}
}

FALLBACK_RULES = {
    "HISTORICAL_SITE": {"typical_time_spent": "90 phút", "price_range": "0 - 50.000đ / vé"},
    "TEMPLE": {"typical_time_spent": "90 phút", "price_range": "0 VND / Miễn phí"},
    "ATTRACTION": {"typical_time_spent": "60 phút", "price_range": "30.000đ - 150.000đ"},
    "MARKET": {"typical_time_spent": "60 phút", "price_range": "Tự do mua sắm"},
    "HOTEL": {"typical_time_spent": "105 phút", "price_range": "600.000đ - 2.500.000đ / đêm"},
    "RESTAURANT": {"typical_time_spent": "75 phút", "price_range": "100.000đ - 300.000đ / người"},
    "SPECIALTY_FOOD": {"typical_time_spent": "60 phút", "price_range": "40.000đ - 120.000đ / phần"},
    "SEAFOOD_RESTAURANT": {"typical_time_spent": "75 phút", "price_range": "200.000đ - 500.000đ / người"},
    "BEACH": {"typical_time_spent": "90 phút", "price_range": "0 VND / Miễn phí"}
}

# Tọa độ mặc định trung tâm 63 tỉnh thành Việt Nam (phục vụ kiểm tra ranh giới và GPS fallback)
PROVINCE_COORDINATES = {
    # Miền Bắc
    "Hà Nội": (21.0285, 105.8542), "Hải Phòng": (20.8449, 106.6881), "Hải Dương": (20.9386, 106.3197),
    "Bắc Ninh": (21.1861, 106.0763), "Hà Nam": (20.5417, 105.9167), "Nam Định": (20.4286, 106.1758),
    "Ninh Bình": (20.2506, 105.9745), "Hưng Yên": (20.6528, 106.0564), "Thái Bình": (20.4467, 106.3389),
    "Vĩnh Phúc": (21.3117, 105.5967), "Bắc Giang": (21.2728, 106.1944), "Bắc Kạn": (22.1467, 105.8347),
    "Cao Bằng": (22.6667, 106.2583), "Hà Giang": (22.8233, 104.9839), "Lạng Sơn": (21.8417, 106.7625),
    "Phú Thọ": (21.3092, 105.4183), "Quảng Ninh": (20.9506, 107.0906), "Thái Nguyên": (21.5908, 105.8456),
    "Tuyên Quang": (21.8256, 105.2189), "Điện Biên": (21.3853, 103.0189), "Hòa Bình": (20.8194, 105.3361),
    "Lai Châu": (22.3986, 103.4611), "Lào Cai": (22.4833, 103.9667), "Sơn La": (21.3267, 103.9133),
    "Yên Bái": (21.7167, 104.8667),
    # Miền Trung & Tây Nguyên
    "Hà Tĩnh": (18.3417, 105.9056), "Nghệ An": (18.6667, 105.6722), "Quảng Bình": (17.4694, 106.6264),
    "Quảng Trị": (16.8167, 107.1000), "Thanh Hóa": (19.8056, 105.7778), "Thừa Thiên Huế": (16.4637, 107.5909),
    "Đà Nẵng": (16.0544, 108.2022), "Quảng Nam": (15.5667, 108.4833), "Quảng Ngãi": (15.1222, 108.8000),
    "Bình Định": (13.7806, 109.2319), "Phú Yên": (13.0889, 109.3083), "Khánh Hòa": (12.2388, 109.1967),
    "Ninh Thuận": (11.5667, 108.9833), "Bình Thuận": (10.9278, 108.0986), "Kon Tum": (14.3500, 108.0056),
    "Gia Lai": (13.9778, 108.0000), "Đắk Lắk": (12.6806, 108.0389), "Đắk Nông": (12.0056, 107.6889),
    "Lâm Đồng": (11.9404, 108.4583),
    # Miền Nam
    "TP. Hồ Chí Minh": (10.7769, 106.7009), "Bà Rịa – Vũng Tàu": (10.3460, 107.0843), "Bình Dương": (10.9806, 106.6528),
    "Bình Phước": (11.5333, 106.8833), "Đồng Nai": (10.9472, 106.8194), "Tây Ninh": (11.3111, 106.0972),
    "Cần Thơ": (10.0333, 105.7867), "An Giang": (10.3759, 105.4358), "Bạc Liêu": (9.2889, 105.7250),
    "Bến Tre": (10.2372, 106.3761), "Cà Mau": (9.1764, 105.1528), "Đồng Tháp": (10.4611, 105.6361),
    "Hậu Giang": (9.7833, 105.4667), "Kiên Giang": (10.0111, 105.0806), "Long An": (10.5361, 106.4083),
    "Sóc Trăng": (9.6028, 105.9722), "Tiền Giang": (10.3556, 106.3639), "Trà Vinh": (9.9389, 106.3444),
    "Vĩnh Long": (10.2528, 105.9722)
}

