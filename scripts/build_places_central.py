"""
scripts/build_places_central.py

Script thu thập, làm sạch, làm giàu và chuẩn hóa dữ liệu địa danh cho 19 tỉnh Miền Trung & Tây Nguyên:
1. 19 tỉnh thành:
   Thanh Hóa, Nghệ An, Hà Tĩnh, Quảng Bình, Quảng Trị, Thừa Thiên Huế,
   Đà Nẵng, Quảng Nam, Quảng Ngãi, Bình Định, Phú Yên, Khánh Hòa,
   Ninh Thuận, Bình Thuận, Kon Tum, Gia Lai, Đắk Lắk, Đắk Nông, Lâm Đồng.
2. Bổ sung các tỉnh còn thiếu (Bình Thuận, Ninh Thuận, Phú Yên, Quảng Nam) lên >= 15-20 địa danh.
3. Đảm bảo Đắk Nông có di tích lịch sử xác thực (Nhà ngục Đăk Mil).
4. Loại bỏ địa danh nước ngoài và rác tại Bình Định, Quảng Bình, Quảng Trị; làm giàu địa danh thực tế Bình Định.
5. Mỗi tỉnh phủ đủ 6 danh mục chính (HISTORICAL_SITE, TEMPLE, ATTRACTION, HOTEL, MARKET, SPECIALTY_FOOD) và có 17-20 địa danh.
6. Sử dụng harvest_pipeline.py: lọc GPS Việt Nam, blacklist SVG/bản đồ, deduplicate ảnh toàn cục, bốc ảnh Wikipedia.
7. Xuất ra file data/places_central.json.
"""

import os
import sys
import json
import time
import urllib.parse
from collections import defaultdict, Counter

# Đảm bảo đường dẫn import tới thư mục gốc
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scripts.mapping_config import MAPPING_63_TO_34, FALLBACK_RULES, PROVINCE_COORDINATES
from scripts.harvest_pipeline import (
    VIETNAM_LAT_MIN, VIETNAM_LAT_MAX, VIETNAM_LNG_MIN, VIETNAM_LNG_MAX,
    PHOTO_BLACKLIST_KEYWORDS, SCHEMA_20_FIELDS,
    is_within_vietnam_bounds, is_foreign_landmark, is_blacklisted_photo,
    WikipediaFetcher, normalize_place_record, HarvestPipeline
)

CENTRAL_PROVINCES = [
    'Thanh Hóa', 'Nghệ An', 'Hà Tĩnh', 'Quảng Bình', 'Quảng Trị',
    'Thừa Thiên Huế', 'Đà Nẵng', 'Quảng Nam', 'Quảng Ngãi', 'Bình Định',
    'Phú Yên', 'Khánh Hòa', 'Ninh Thuận', 'Bình Thuận', 'Kon Tum',
    'Gia Lai', 'Đắk Lắk', 'Đắk Nông', 'Lâm Đồng'
]

# Danh mục định nghĩa chi tiết cho 19 tỉnh thành (18-20 địa điểm/tỉnh)
CURATED_CENTRAL_PLACES = {
    "Thanh Hóa": [
        {"name": "Thành nhà Hồ", "category": "HISTORICAL_SITE", "wiki_title": "Thành nhà Hồ", "lat": 20.0767, "lng": 105.6067, "is_must_visit": True, "badge_label": "⭐ Di sản Văn hóa Thế giới UNESCO"},
        {"name": "Khu di tích Lam Kinh", "category": "HISTORICAL_SITE", "wiki_title": "Lam Kinh", "lat": 19.9167, "lng": 105.3833, "is_must_visit": True, "badge_label": "⭐ Nơi phát tích khởi nghĩa Lam Sơn"},
        {"name": "Khu di tích Bà Triệu", "category": "HISTORICAL_SITE", "wiki_title": "Đền Bà Triệu", "lat": 19.9667, "lng": 105.8167, "is_must_visit": True, "badge_label": "Di tích Quốc gia Đặc biệt núi Tùng"},
        {"name": "Cầu Hàm Rồng", "category": "HISTORICAL_SITE", "wiki_title": "Cầu Hàm Rồng", "lat": 19.8333, "lng": 105.7833, "is_must_visit": True, "badge_label": "Biểu tượng ý chí kiên cường sông Mã"},
        {"name": "Đền Độc Cước", "category": "TEMPLE", "wiki_title": "Đền Độc Cước", "lat": 19.7333, "lng": 105.9056, "is_must_visit": True, "badge_label": "Đền thiêng ngự trên hòn Cổ Giải"},
        {"name": "Chùa Sùng Nghiêm Diên Thánh", "category": "TEMPLE", "wiki_title": "Chùa Sùng Nghiêm Diên Thánh", "lat": 19.9500, "lng": 105.8667, "is_must_visit": True, "badge_label": "Cổ tự thời Lý Di tích Quốc gia"},
        {"name": "Bãi biển Sầm Sơn", "category": "ATTRACTION", "wiki_title": "Sầm Sơn", "lat": 19.7417, "lng": 105.9083, "is_must_visit": True, "badge_label": "Đô thị du lịch biển nổi tiếng"},
        {"name": "Khu bảo tồn thiên nhiên Pù Luông", "category": "ATTRACTION", "wiki_title": "Pù Luông", "lat": 20.4667, "lng": 105.1833, "is_must_visit": True, "badge_label": "Thiên đường ruộng bậc thang và mây ngàn"},
        {"name": "Bãi biển Hải Tiến", "category": "ATTRACTION", "wiki_title": "Hoằng Hóa", "lat": 19.8500, "lng": 105.9333, "is_must_visit": False, "badge_label": "Bãi biển thanh bình trong xanh"},
        {"name": "Suối cá thần Cẩm Lương", "category": "ATTRACTION", "wiki_title": "Suối cá Cẩm Lương", "lat": 20.2167, "lng": 105.3333, "is_must_visit": True, "badge_label": "Hiện tượng thiên nhiên kỳ thú đàn cá nghìn con"},
        {"name": "Hòn Trống Mái Sầm Sơn", "category": "ATTRACTION", "wiki_title": "Sầm Sơn", "lat": 19.7333, "lng": 105.9056, "is_must_visit": False, "badge_label": "Thắng cảnh gắn liền tình sử huyền thoại"},
        {"name": "Vườn quốc gia Bến En", "category": "ATTRACTION", "wiki_title": "Vườn quốc gia Bến En", "lat": 19.6167, "lng": 105.5167, "is_must_visit": True, "badge_label": "Vịnh Hạ Long trên cạn xứ Thanh"},
        {"name": "Chợ Vườn Hoa TP Thanh Hóa", "category": "MARKET", "wiki_title": "Thanh Hóa (thành phố)", "lat": 19.8056, "lng": 105.7778, "is_must_visit": False, "badge_label": "Chợ trung tâm đầu mối lớn nhất tỉnh"},
        {"name": "Chợ hải sản Cột Đỏ Sầm Sơn", "category": "MARKET", "wiki_title": "Sầm Sơn", "lat": 19.7444, "lng": 105.8986, "is_must_visit": False, "badge_label": "Chợ hải sản tươi sống sáng sớm"},
        {"name": "FLC Luxury Resort Sam Son", "category": "HOTEL", "wiki_title": "Tập đoàn FLC", "lat": 19.7583, "lng": 105.9222, "is_must_visit": False, "badge_label": "Quần thể resort 5 sao mặt biển"},
        {"name": "Pu Luong Retreat", "category": "HOTEL", "wiki_title": "Pù Luông", "lat": 20.4500, "lng": 105.2000, "is_must_visit": False, "badge_label": "Khu nghỉ dưỡng sinh thái view ruộng bậc thang"},
        {"name": "Vinpearl Hotel Thanh Hóa", "category": "HOTEL", "wiki_title": "Vinpearl", "lat": 19.8067, "lng": 105.7750, "is_must_visit": False, "badge_label": "Khách sạn 5 sao trung tâm TP Thanh Hóa"},
        {"name": "Nem chua Thanh Hóa (Cơ sở Thắng Tuyến)", "category": "SPECIALTY_FOOD", "wiki_title": "Nem chua", "lat": 19.8083, "lng": 105.7722, "is_must_visit": True, "badge_label": "Đặc sản nức tiếng truyền thống xứ Thanh"},
        {"name": "Chả tôm Thanh Hóa", "category": "SPECIALTY_FOOD", "wiki_title": "Thanh Hóa (thành phố)", "lat": 19.8070, "lng": 105.7760, "is_must_visit": True, "badge_label": "Món ăn vặt thơm nức trên than hồng"}
    ],

    "Nghệ An": [
        {"name": "Khu di tích Quốc gia Đặc biệt Kim Liên (Quê Bác)", "category": "HISTORICAL_SITE", "wiki_title": "Khu di tích Kim Liên", "lat": 18.6833, "lng": 105.5667, "is_must_visit": True, "badge_label": "⭐ Nơi sinh Chủ tịch Hồ Chí Minh"},
        {"name": "Khu di tích Truông Bồn", "category": "HISTORICAL_SITE", "wiki_title": "Truông Bồn", "lat": 18.8167, "lng": 105.4500, "is_must_visit": True, "badge_label": "Huyền thoại cung đường lửa hào hùng"},
        {"name": "Thành cổ Vinh", "category": "HISTORICAL_SITE", "wiki_title": "Thành cổ Vinh", "lat": 18.6667, "lng": 105.6667, "is_must_visit": True, "badge_label": "Thành lũy hình lục giác thời nhà Nguyễn"},
        {"name": "Đền Cuông (Thờ Thục Phán An Dương Vương)", "category": "TEMPLE", "wiki_title": "Đền Cuông", "lat": 19.0333, "lng": 105.6500, "is_must_visit": True, "badge_label": "Đền thiêng trên núi Mộ Dạ"},
        {"name": "Đền Ông Hoàng Mười (Mỏ Hạc Linh Từ)", "category": "TEMPLE", "wiki_title": "Đền Ông Hoàng Mười", "lat": 18.6167, "lng": 105.6833, "is_must_visit": True, "badge_label": "⭐ Ngôi đền linh thiêng bậc nhất xứ Nghệ"},
        {"name": "Đền Cờn", "category": "TEMPLE", "wiki_title": "Đền Cờn", "lat": 19.2333, "lng": 105.7500, "is_must_visit": True, "badge_label": "Đệ nhất đền thiêng Tứ linh miếu Nghệ An"},
        {"name": "Chùa Đại Tuệ", "category": "TEMPLE", "wiki_title": "Nam Đàn", "lat": 18.7333, "lng": 105.5333, "is_must_visit": False, "badge_label": "Ngôi chùa trên đỉnh núi Đại Huệ"},
        {"name": "Bãi biển Cửa Lò", "category": "ATTRACTION", "wiki_title": "Cửa Lò", "lat": 18.8000, "lng": 105.7167, "is_must_visit": True, "badge_label": "⭐ Đô thị du lịch biển sầm uất"},
        {"name": "Vườn quốc gia Pù Mát", "category": "ATTRACTION", "wiki_title": "Vườn quốc gia Pù Mát", "lat": 18.9667, "lng": 104.7500, "is_must_visit": True, "badge_label": "Khu dự trữ sinh quyển thế giới"},
        {"name": "Đồi chè Thanh Chương", "category": "ATTRACTION", "wiki_title": "Thanh Chương", "lat": 18.7500, "lng": 105.2833, "is_must_visit": True, "badge_label": "Ốc đảo chè xanh thơ mộng giữa lòng hồ"},
        {"name": "Cánh đồng hoa hướng dương Nghĩa Đàn", "category": "ATTRACTION", "wiki_title": "Nghĩa Đàn", "lat": 19.3333, "lng": 105.4500, "is_must_visit": False, "badge_label": "Đồng hoa rực rỡ bạt ngàn miền Tây xứ Nghệ"},
        {"name": "Chợ Vinh", "category": "MARKET", "wiki_title": "Vinh", "lat": 18.6667, "lng": 105.6722, "is_must_visit": False, "badge_label": "Chợ đầu mối bán buôn lớn nhất Bắc Trung Bộ"},
        {"name": "Chợ hải sản Cửa Lò", "category": "MARKET", "wiki_title": "Cửa Lò", "lat": 18.8083, "lng": 105.7111, "is_must_visit": False, "badge_label": "Chợ hải sản tươi sống và mực một nắng"},
        {"name": "Chợ Ga Vinh", "category": "MARKET", "wiki_title": "Vinh", "lat": 18.6750, "lng": 105.6700, "is_must_visit": False, "badge_label": "Chợ truyền thống đầu mối trung tâm ga"},
        {"name": "Vinpearl Discovery Cua Hoi", "category": "HOTEL", "wiki_title": "Cửa Lò", "lat": 18.7750, "lng": 105.7417, "is_must_visit": False, "badge_label": "Resort 5 sao cao cấp Cửa Hội"},
        {"name": "Muong Thanh Song Lam Hotel Vinh", "category": "HOTEL", "wiki_title": "Tập đoàn Mường Thanh", "lat": 18.6742, "lng": 105.6847, "is_must_visit": False, "badge_label": "Khách sạn 5 sao trung tâm TP Vinh"},
        {"name": "Sài Gòn Kim Liên Resort Cửa Lò", "category": "HOTEL", "wiki_title": "Cửa Lò", "lat": 18.8050, "lng": 105.7150, "is_must_visit": False, "badge_label": "Khu nghỉ dưỡng 4 sao mặt biển Cửa Lò"},
        {"name": "Súp lươn xứ Nghệ (Quán lươn Bà Liễu)", "category": "SPECIALTY_FOOD", "wiki_title": "Lươn", "lat": 18.6706, "lng": 105.6792, "is_must_visit": True, "badge_label": "Đặc sản lừng danh xứ Nghệ"},
        {"name": "Nhút Thanh Chương & Tương Nam Đàn", "category": "SPECIALTY_FOOD", "wiki_title": "Nhút Thanh Chương", "lat": 18.7000, "lng": 105.5000, "is_must_visit": True, "badge_label": "Món ăn dân dã đậm đà tình quê xứ Nghệ"}
    ],

    "Hà Tĩnh": [
        {"name": "Khu di tích Đại thi hào Nguyễn Du", "category": "HISTORICAL_SITE", "wiki_title": "Nguyễn Du", "lat": 18.6333, "lng": 105.7667, "is_must_visit": True, "badge_label": "⭐ Danh nhân Văn hóa Thế giới UNESCO"},
        {"name": "Khu di tích Ngã ba Đồng Lộc", "category": "HISTORICAL_SITE", "wiki_title": "Ngã ba Đồng Lộc", "lat": 18.3667, "lng": 105.7000, "is_must_visit": True, "badge_label": "⭐ Huyền thoại 10 cô gái thanh niên xung phong"},
        {"name": "Khu di tích Tổng bí thư Trần Phú", "category": "HISTORICAL_SITE", "wiki_title": "Trần Phú", "lat": 18.5333, "lng": 105.5833, "is_must_visit": True, "badge_label": "Khu lưu niệm Tổng bí thư đầu tiên của Đảng"},
        {"name": "Chùa Hương Tích (Hà Tĩnh)", "category": "TEMPLE", "wiki_title": "Chùa Hương Tích (Hà Tĩnh)", "lat": 18.4333, "lng": 105.7833, "is_must_visit": True, "badge_label": "⭐ Hoan Châu đệ nhất danh lam trên núi Hồng"},
        {"name": "Đền Chợ Củi (Đền Quan Hoàng Mười)", "category": "TEMPLE", "wiki_title": "Nghi Xuân", "lat": 18.6167, "lng": 105.7000, "is_must_visit": True, "badge_label": "Ngôi đền linh thiêng bờ sông Lam"},
        {"name": "Đền thờ Chiêu Trưng Đại vương Lê Khôi", "category": "TEMPLE", "wiki_title": "Lê Khôi", "lat": 18.4667, "lng": 105.9500, "is_must_visit": True, "badge_label": "Di tích Quốc gia cửa biển Nam Giới"},
        {"name": "Bãi biển Thiên Cầm", "category": "ATTRACTION", "wiki_title": "Thiên Cầm", "lat": 18.2833, "lng": 106.0167, "is_must_visit": True, "badge_label": "Cung đàn trời biển trong xanh"},
        {"name": "Hồ Kẻ Gỗ", "category": "ATTRACTION", "wiki_title": "Hồ Kẻ Gỗ", "lat": 18.1833, "lng": 105.9500, "is_must_visit": True, "badge_label": "Hồ nước nhân tạo thơ mộng đại ngàn"},
        {"name": "Dãy núi Hồng Lĩnh", "category": "ATTRACTION", "wiki_title": "Hồng Lĩnh (dãy núi)", "lat": 18.5333, "lng": 105.8167, "is_must_visit": True, "badge_label": "Non Hồng 99 ngọn biểu tượng non nước"},
        {"name": "Bãi biển Xuân Thành", "category": "ATTRACTION", "wiki_title": "Nghi Xuân", "lat": 18.6000, "lng": 105.8500, "is_must_visit": False, "badge_label": "Bãi cát trắng mịn thoai thoải"},
        {"name": "Suối khoáng nóng Sơn Kim", "category": "ATTRACTION", "wiki_title": "Hương Sơn, Hà Tĩnh", "lat": 18.4333, "lng": 105.2167, "is_must_visit": False, "badge_label": "Điểm du lịch sinh thái nghỉ dưỡng biên giới"},
        {"name": "Chợ TP Hà Tĩnh", "category": "MARKET", "wiki_title": "Hà Tĩnh (thành phố)", "lat": 18.3417, "lng": 105.9056, "is_must_visit": False, "badge_label": "Chợ trung tâm lớn nhất tỉnh Hà Tĩnh"},
        {"name": "Chợ cá Cửa Nhượng (Thiên Cầm)", "category": "MARKET", "wiki_title": "Cẩm Xuyên", "lat": 18.2667, "lng": 106.0333, "is_must_visit": False, "badge_label": "Chợ cá sáng sớm hải sản tươi rói"},
        {"name": "Vinpearl Discovery Ha Tinh Resort", "category": "HOTEL", "wiki_title": "Vinpearl", "lat": 18.4667, "lng": 105.9000, "is_must_visit": False, "badge_label": "Resort 5 sao bãi biển Cửa Sót"},
        {"name": "Muong Thanh Grand Ha Tinh Hotel", "category": "HOTEL", "wiki_title": "Tập đoàn Mường Thanh", "lat": 18.0667, "lng": 106.3167, "is_must_visit": False, "badge_label": "Khách sạn 4 sao Kỳ Anh"},
        {"name": "Khách sạn BMC Hà Tĩnh", "category": "HOTEL", "wiki_title": "Hà Tĩnh (thành phố)", "lat": 18.3450, "lng": 105.9050, "is_must_visit": False, "badge_label": "Khách sạn 4 sao trung tâm thành phố"},
        {"name": "Kẹo Cu Đơ Hà Tĩnh (Cu Đơ Thư Viện)", "category": "SPECIALTY_FOOD", "wiki_title": "Kẹo cu đơ", "lat": 18.3444, "lng": 105.9083, "is_must_visit": True, "badge_label": "Đặc sản nức tiếng truyền đời Hà Tĩnh"},
        {"name": "Mực nhảy Vũng Áng", "category": "SPECIALTY_FOOD", "wiki_title": "Vũng Áng", "lat": 18.0167, "lng": 106.3833, "is_must_visit": True, "badge_label": "Món mực tươi sống giòn ngọt trứ danh"}
    ],

    "Quảng Bình": [
        {"name": "Vườn quốc gia Phong Nha – Kẻ Bàng", "category": "ATTRACTION", "wiki_title": "Vườn quốc gia Phong Nha - Kẻ Bàng", "lat": 17.5833, "lng": 106.2833, "is_must_visit": True, "badge_label": "⭐ Di sản Thiên nhiên Thế giới 2 lần UNESCO"},
        {"name": "Động Phong Nha", "category": "ATTRACTION", "wiki_title": "Động Phong Nha", "lat": 17.5861, "lng": 106.2833, "is_must_visit": True, "badge_label": "Kỳ quan đệ nhất động nước"},
        {"name": "Động Thiên Đường", "category": "ATTRACTION", "wiki_title": "Động Thiên Đường", "lat": 17.5208, "lng": 106.2236, "is_must_visit": True, "badge_label": "Hoàng cung lộng lẫy trong lòng đất"},
        {"name": "Hang Sơn Đoòng", "category": "ATTRACTION", "wiki_title": "Hang Sơn Đoòng", "lat": 17.4583, "lng": 106.2833, "is_must_visit": True, "badge_label": "⭐ Hang động tự nhiên lớn nhất hành tinh"},
        {"name": "Động Tiên Sơn (Quảng Bình)", "category": "ATTRACTION", "wiki_title": "Động Tiên Sơn (Quảng Bình)", "lat": 17.5880, "lng": 106.2850, "is_must_visit": False, "badge_label": "Lâu đài thạch nhũ huyền ảo trên cao"},
        {"name": "Suối Nước Moọc", "category": "ATTRACTION", "wiki_title": "Bố Trạch", "lat": 17.5667, "lng": 106.2500, "is_must_visit": True, "badge_label": "Dòng suối xanh ngọc bích giữa rừng già"},
        {"name": "Bãi biển Nhật Lệ", "category": "ATTRACTION", "wiki_title": "Nhật Lệ (bãi biển)", "lat": 17.4833, "lng": 106.6333, "is_must_visit": True, "badge_label": "Bãi tắm cát trắng thơ mộng cửa sông"},
        {"name": "Bãi Đá Nhảy Quảng Bình", "category": "ATTRACTION", "wiki_title": "Bố Trạch", "lat": 17.6500, "lng": 106.5500, "is_must_visit": True, "badge_label": "Kiệt tác điêu khắc của sóng biển"},
        {"name": "Khu lăng mộ Đại tướng Võ Nguyên Giáp", "category": "HISTORICAL_SITE", "wiki_title": "Võ Nguyên Giáp", "lat": 17.9167, "lng": 106.4833, "is_must_visit": True, "badge_label": "⭐ Nơi an nghỉ Người anh cả QĐNDVN"},
        {"name": "Quảng Bình quan", "category": "HISTORICAL_SITE", "wiki_title": "Quảng Bình quan", "lat": 17.4667, "lng": 106.6167, "is_must_visit": True, "badge_label": "Cửa ngõ lũy Thầy kiên cố thời Trịnh Nguyễn"},
        {"name": "Thành Đồng Hới", "category": "HISTORICAL_SITE", "wiki_title": "Thành Đồng Hới", "lat": 17.4700, "lng": 106.6200, "is_must_visit": True, "badge_label": "Di tích thành lũy phòng thủ cổ"},
        {"name": "Chùa Hoằng Phúc", "category": "TEMPLE", "wiki_title": "Chùa Hoằng Phúc", "lat": 17.1833, "lng": 106.7500, "is_must_visit": True, "badge_label": "⭐ Ngôi chùa cổ hơn 700 năm đất Quảng Bình"},
        {"name": "Chùa Đại Giác Quảng Bình", "category": "TEMPLE", "wiki_title": "Đồng Hới", "lat": 17.4650, "lng": 106.6100, "is_must_visit": False, "badge_label": "Chùa lớn trung tâm TP Đồng Hới"},
        {"name": "Chợ Đồng Hới", "category": "MARKET", "wiki_title": "Đồng Hới", "lat": 17.4694, "lng": 106.6264, "is_must_visit": False, "badge_label": "Chợ hải sản sầm uất bên bờ sông Nhật Lệ"},
        {"name": "Chợ đêm Đồng Hới", "category": "MARKET", "wiki_title": "Đồng Hới", "lat": 17.4722, "lng": 106.6236, "is_must_visit": False, "badge_label": "Chợ đêm ẩm thực du lịch phố biển"},
        {"name": "Sun Spa Resort & Villa Quảng Bình", "category": "HOTEL", "wiki_title": "Đồng Hới", "lat": 17.4778, "lng": 106.6361, "is_must_visit": False, "badge_label": "Resort 5 sao bán đảo Bảo Ninh"},
        {"name": "Celina Peninsula Resort Quảng Bình", "category": "HOTEL", "wiki_title": "Đồng Hới", "lat": 17.4900, "lng": 106.6400, "is_must_visit": False, "badge_label": "Resort nghỉ dưỡng biển cao cấp"},
        {"name": "Cháo canh Quảng Bình & Bánh xèo gạo lứt", "category": "SPECIALTY_FOOD", "wiki_title": "Quảng Bình", "lat": 17.4681, "lng": 106.6222, "is_must_visit": True, "badge_label": "Món ăn sáng đậm vị quê hương Quảng Bình"},
        {"name": "Khoai gieo Quảng Bình", "category": "SPECIALTY_FOOD", "wiki_title": "Khoai gieo", "lat": 17.4700, "lng": 106.6250, "is_must_visit": True, "badge_label": "Đặc sản dân dã dẻo thơm vùng cát trắng"}
    ],

    "Quảng Trị": [
        {"name": "Thành cổ Quảng Trị", "category": "HISTORICAL_SITE", "wiki_title": "Thành cổ Quảng Trị", "lat": 16.7456, "lng": 107.1897, "is_must_visit": True, "badge_label": "⭐ 81 ngày đêm rực lửa mùa hè 1972"},
        {"name": "Địa đạo Vịnh Mốc", "category": "HISTORICAL_SITE", "wiki_title": "Địa đạo Vịnh Mốc", "lat": 17.0608, "lng": 107.1128, "is_must_visit": True, "badge_label": "⭐ Làng hầm huyền thoại sống trong lòng đất"},
        {"name": "Cầu Hiền Lương - Sông Bến Hải (Vĩ tuyến 17)", "category": "HISTORICAL_SITE", "wiki_title": "Cầu Hiền Lương", "lat": 17.0097, "lng": 107.0514, "is_must_visit": True, "badge_label": "Chứng tích lịch sử chia cắt đất nước"},
        {"name": "Nghĩa trang Liệt sĩ Quốc gia Trường Sơn", "category": "HISTORICAL_SITE", "wiki_title": "Nghĩa trang liệt sĩ Trường Sơn", "lat": 16.9500, "lng": 106.9667, "is_must_visit": True, "badge_label": "Nơi an nghỉ hơn 10.000 liệt sĩ Trường Sơn"},
        {"name": "Nghĩa trang Liệt sĩ Quốc gia Đường 9", "category": "HISTORICAL_SITE", "wiki_title": "Đông Hà", "lat": 16.8000, "lng": 107.0833, "is_must_visit": True, "badge_label": "Khu tưởng niệm anh hùng chiến dịch Đường 9"},
        {"name": "Sân bay Tà Cơn & Căn cứ Khe Sanh", "category": "HISTORICAL_SITE", "wiki_title": "Sân bay Tà Cơn", "lat": 16.6500, "lng": 106.7167, "is_must_visit": True, "badge_label": "Cứ điểm quân sự chấn động thung lũng Khe Sanh"},
        {"name": "Thánh địa La Vang", "category": "TEMPLE", "wiki_title": "La Vang", "lat": 16.7167, "lng": 107.1833, "is_must_visit": True, "badge_label": "⭐ Trung tâm hành hương Công giáo lớn nhất VN"},
        {"name": "Chùa Sắc Tứ Tịnh Quang", "category": "TEMPLE", "wiki_title": "Triệu Phong", "lat": 16.7667, "lng": 107.1833, "is_must_visit": True, "badge_label": "Tổ đình Phật giáo cổ kính nhất Quảng Trị"},
        {"name": "Đảo Cồn Cỏ", "category": "ATTRACTION", "wiki_title": "Cồn Cỏ", "lat": 17.1667, "lng": 107.3333, "is_must_visit": True, "badge_label": "Tiền đồn biển đảo xanh tươi giữa đại dương"},
        {"name": "Bãi biển Cửa Tùng", "category": "ATTRACTION", "wiki_title": "Cửa Tùng", "lat": 17.0167, "lng": 107.1000, "is_must_visit": True, "badge_label": "Nữ hoàng của các bãi tắm xứ Trung"},
        {"name": "Bãi biển Cửa Việt", "category": "ATTRACTION", "wiki_title": "Cửa Việt", "lat": 16.9000, "lng": 107.1833, "is_must_visit": False, "badge_label": "Bãi tắm sóng êm cát phẳng trải dài"},
        {"name": "Suối nước nóng Klu", "category": "ATTRACTION", "wiki_title": "Đakrông", "lat": 16.6333, "lng": 106.9500, "is_must_visit": False, "badge_label": "Dòng khoáng nóng tự nhiên vùng cao"},
        {"name": "Chợ Đông Hà", "category": "MARKET", "wiki_title": "Đông Hà", "lat": 16.8167, "lng": 107.1000, "is_must_visit": False, "badge_label": "Chợ hàng biên mậu Thái - Lào lớn nhất tỉnh"},
        {"name": "Chợ thị xã Quảng Trị", "category": "MARKET", "wiki_title": "Quảng Trị (thị xã)", "lat": 16.7472, "lng": 107.1917, "is_must_visit": False, "badge_label": "Chợ truyền thống lâu đời bên sông Thạch Hãn"},
        {"name": "Muong Thanh Grand Quang Tri", "category": "HOTEL", "wiki_title": "Tập đoàn Mường Thanh", "lat": 16.8117, "lng": 107.0983, "is_must_visit": False, "badge_label": "Khách sạn 4 sao trung tâm TP Đông Hà"},
        {"name": "Khách sạn Sài Gòn Đông Hà", "category": "HOTEL", "wiki_title": "Đông Hà", "lat": 16.8200, "lng": 107.1050, "is_must_visit": False, "badge_label": "Khách sạn tiện nghi 4 sao quốc tế"},
        {"name": "Bánh ướt Phương Lang & Cháo bột cá lóc", "category": "SPECIALTY_FOOD", "wiki_title": "Bánh ướt", "lat": 16.7333, "lng": 107.2167, "is_must_visit": True, "badge_label": "Đặc sản bánh ướt thịt heo nức tiếng Hải Lăng"},
        {"name": "Thịt trâu lá trơng Quảng Trị", "category": "SPECIALTY_FOOD", "wiki_title": "Quảng Trị", "lat": 16.8150, "lng": 107.1020, "is_must_visit": True, "badge_label": "Món ngon đậm vị cay nồng lá trơng vùng đất lửa"}
    ],

    "Thừa Thiên Huế": [
        {"name": "Quần thể di tích Cố đô Huế", "category": "HISTORICAL_SITE", "wiki_title": "Quần thể di tích Cố đô Huế", "lat": 16.4700, "lng": 107.5786, "is_must_visit": True, "badge_label": "⭐ Di sản Văn hóa Thế giới đầu tiên của VN"},
        {"name": "Đại Nội Huế (Hoàng thành & Tử Cấm Thành)", "category": "HISTORICAL_SITE", "wiki_title": "Hoàng thành Huế", "lat": 16.4686, "lng": 107.5783, "is_must_visit": True, "badge_label": "⭐ Cung điện nguy nga triều Nguyễn"},
        {"name": "Lăng Khải Định (Ứng Lăng)", "category": "HISTORICAL_SITE", "wiki_title": "Lăng Khải Định", "lat": 16.3989, "lng": 107.5906, "is_must_visit": True, "badge_label": "Đỉnh cao nghệ thuật khảm sành sứ Á - Âu"},
        {"name": "Lăng Tự Đức (Khiêm Lăng)", "category": "HISTORICAL_SITE", "wiki_title": "Lăng Tự Đức", "lat": 16.4328, "lng": 107.5658, "is_must_visit": True, "badge_label": "Bức tranh sơn thủy hữu tình thơ mộng"},
        {"name": "Lăng Minh Mạng (Hiếu Lăng)", "category": "HISTORICAL_SITE", "wiki_title": "Lăng Minh Mạng", "lat": 16.3833, "lng": 107.5667, "is_must_visit": True, "badge_label": "Kiến trúc uy nghiêm đăng đối triều Nguyễn"},
        {"name": "Chùa Thiên Mụ", "category": "TEMPLE", "wiki_title": "Chùa Thiên Mụ", "lat": 16.4528, "lng": 107.5447, "is_must_visit": True, "badge_label": "⭐ Biểu tượng tâm linh xứ Huế bên sông Hương"},
        {"name": "Chùa Từ Đàm", "category": "TEMPLE", "wiki_title": "Chùa Từ Đàm", "lat": 16.4500, "lng": 107.5833, "is_must_visit": False, "badge_label": "Trung tâm Phật giáo chấn hưng miền Trung"},
        {"name": "Chùa Huyền Không Sơn Thượng", "category": "TEMPLE", "wiki_title": "Hương Trà", "lat": 16.4667, "lng": 107.5000, "is_must_visit": True, "badge_label": "Chốn thiền môn thanh tịnh giữa rừng thông"},
        {"name": "Sông Hương & Cầu Tràng Tiền", "category": "ATTRACTION", "wiki_title": "Sông Hương", "lat": 16.4683, "lng": 107.5900, "is_must_visit": True, "badge_label": "Trái tim lãng mạn của vùng đất Cố đô"},
        {"name": "Đồi Vọng Cảnh", "category": "ATTRACTION", "wiki_title": "Huế", "lat": 16.4333, "lng": 107.5500, "is_must_visit": True, "badge_label": "Nơi ngắm toàn cảnh khúc cua sông Hương đẹp nhất"},
        {"name": "Vườn quốc gia Bạch Mã", "category": "ATTRACTION", "wiki_title": "Vườn quốc gia Bạch Mã", "lat": 16.1983, "lng": 107.8500, "is_must_visit": True, "badge_label": "Vọng Hải Đài ngút ngàn mây trắng"},
        {"name": "Vịnh Lăng Cô", "category": "ATTRACTION", "wiki_title": "Vịnh Lăng Cô", "lat": 16.2333, "lng": 108.0167, "is_must_visit": True, "badge_label": "Một trong những vịnh biển đẹp nhất thế giới"},
        {"name": "Phá Tam Giang", "category": "ATTRACTION", "wiki_title": "Phá Tam Giang", "lat": 16.5833, "lng": 107.5500, "is_must_visit": True, "badge_label": "Đầm phá nước lợ lớn nhất Đông Nam Á"},
        {"name": "Chợ Đông Ba", "category": "MARKET", "wiki_title": "Chợ Đông Ba", "lat": 16.4719, "lng": 107.5878, "is_must_visit": True, "badge_label": "Chợ truyền thống linh hồn ẩm thực Cố đô"},
        {"name": "Chợ đêm Cầu Gỗ Lim phố đi bộ Nguyễn Đình Chiểu", "category": "MARKET", "wiki_title": "Huế", "lat": 16.4678, "lng": 107.5889, "is_must_visit": False, "badge_label": "Phố đi bộ lung linh bờ Nam sông Hương"},
        {"name": "Azerai La Residence Hue", "category": "HOTEL", "wiki_title": "Huế", "lat": 16.4611, "lng": 107.5750, "is_must_visit": False, "badge_label": "Khách sạn boutique 5 sao kiến trúc Art Deco"},
        {"name": "Silk Path Grand Hue Hotel", "category": "HOTEL", "wiki_title": "Huế", "lat": 16.4617, "lng": 107.5833, "is_must_visit": False, "badge_label": "Khách sạn 5 sao phong cách quý tộc"},
        {"name": "Bún bò Huế Mụ Rơi & Cơm hến Hoa Đông", "category": "SPECIALTY_FOOD", "wiki_title": "Bún bò Huế", "lat": 16.4639, "lng": 107.5917, "is_must_visit": True, "badge_label": "Tinh hoa ẩm thực cung đình & dân gian"},
        {"name": "Bánh bèo, nậm, lọc xứ Huế", "category": "SPECIALTY_FOOD", "wiki_title": "Bánh bèo", "lat": 16.4650, "lng": 107.5880, "is_must_visit": True, "badge_label": "Các món bánh Huế thanh tao nước mắm ruốc"}
    ],

    "Đà Nẵng": [
        {"name": "Danh thắng Ngũ Hành Sơn", "category": "HISTORICAL_SITE", "wiki_title": "Ngũ Hành Sơn (núi)", "lat": 16.0044, "lng": 108.2636, "is_must_visit": True, "badge_label": "⭐ Di tích Quốc gia Đặc biệt non nước Ngũ Hành"},
        {"name": "Bảo tàng Điêu khắc Chăm Đà Nẵng", "category": "HISTORICAL_SITE", "wiki_title": "Bảo tàng Nghệ thuật Điêu khắc Chăm Đà Nẵng", "lat": 16.0603, "lng": 108.2236, "is_must_visit": True, "badge_label": "Bảo tàng lưu giữ hiện vật Chăm Pa quy mô nhất"},
        {"name": "Thành Điện Hải", "category": "HISTORICAL_SITE", "wiki_title": "Thành Điện Hải", "lat": 16.0750, "lng": 108.2222, "is_must_visit": True, "badge_label": "Di tích Quốc gia Đặc biệt pháo đài kháng Pháp"},
        {"name": "Chùa Linh Ứng Bãi Bụt (Sơn Trà)", "category": "TEMPLE", "wiki_title": "Bán đảo Sơn Trà", "lat": 16.1000, "lng": 108.2778, "is_must_visit": True, "badge_label": "⭐ Tượng Quan Thế Âm Bồ Tát cao 67m ngự biển"},
        {"name": "Chùa Tam Thai (Ngũ Hành Sơn)", "category": "TEMPLE", "wiki_title": "Chùa Tam Thai (Đà Nẵng)", "lat": 16.0039, "lng": 108.2639, "is_must_visit": True, "badge_label": "Quốc tự cổ thời vua Minh Mạng ngự phong"},
        {"name": "Chùa Pháp Lâm Đà Nẵng", "category": "TEMPLE", "wiki_title": "Đà Nẵng", "lat": 16.0639, "lng": 108.2167, "is_must_visit": False, "badge_label": "Trụ sở Phật giáo Đà Nẵng thanh tịnh"},
        {"name": "Bà Nà Hills & Cầu Vàng", "category": "ATTRACTION", "wiki_title": "Bà Nà Hills", "lat": 15.9961, "lng": 107.9875, "is_must_visit": True, "badge_label": "⭐ Cầu Vàng - Biểu tượng du lịch quốc tế"},
        {"name": "Bãi biển Mỹ Khê", "category": "ATTRACTION", "wiki_title": "Mỹ Khê", "lat": 16.0592, "lng": 108.2464, "is_must_visit": True, "badge_label": "⭐ Top bãi biển đẹp nhất hành tinh (Forbes)"},
        {"name": "Cầu Rồng Đà Nẵng", "category": "ATTRACTION", "wiki_title": "Cầu Rồng", "lat": 16.0611, "lng": 108.2272, "is_must_visit": True, "badge_label": "Cây cầu biểu tượng phun lửa và nước cuối tuần"},
        {"name": "Bán đảo Sơn Trà & Đỉnh Bàn Cờ", "category": "ATTRACTION", "wiki_title": "Bán đảo Sơn Trà", "lat": 16.1200, "lng": 108.2800, "is_must_visit": True, "badge_label": "Lá phổi xanh và nơi ngắm toàn cảnh vịnh Đà Nẵng"},
        {"name": "Cầu Sông Hàn", "category": "ATTRACTION", "wiki_title": "Cầu Sông Hàn", "lat": 16.0722, "lng": 108.2278, "is_must_visit": True, "badge_label": "Cầu quay đầu tiên và duy nhất do người Việt thiết kế"},
        {"name": "Đèo Hải Vân", "category": "ATTRACTION", "wiki_title": "Đèo Hải Vân", "lat": 16.1956, "lng": 108.1317, "is_must_visit": True, "badge_label": "Thiên hạ đệ nhất hùng quan nối Huế - Đà Nẵng"},
        {"name": "Suối khoáng nóng Núi Thần Tài", "category": "ATTRACTION", "wiki_title": "Hòa Vang", "lat": 15.9833, "lng": 107.9833, "is_must_visit": False, "badge_label": "Khu công viên suối khoáng nóng thư giãn"},
        {"name": "Chợ Hàn", "category": "MARKET", "wiki_title": "Chợ Hàn", "lat": 16.0683, "lng": 108.2244, "is_must_visit": True, "badge_label": "Thiên đường mua sắm đặc sản du lịch Đà Nẵng"},
        {"name": "Chợ Cồn", "category": "MARKET", "wiki_title": "Chợ Cồn", "lat": 16.0686, "lng": 108.2139, "is_must_visit": True, "badge_label": "Chợ ẩm thực ăn vặt sầm uất bậc nhất thành phố"},
        {"name": "Chợ đêm Sơn Trà", "category": "MARKET", "wiki_title": "Đà Nẵng", "lat": 16.0617, "lng": 108.2325, "is_must_visit": False, "badge_label": "Chợ đêm nhộn nhịp chân cầu Rồng"},
        {"name": "InterContinental Danang Sun Peninsula Resort", "category": "HOTEL", "wiki_title": "Bán đảo Sơn Trà", "lat": 16.1206, "lng": 108.3117, "is_must_visit": False, "badge_label": "Khu nghỉ dưỡng 5 sao sang trọng đẳng cấp quốc tế"},
        {"name": "Vinpearl Luxury Da Nang", "category": "HOTEL", "wiki_title": "Vinpearl", "lat": 16.0236, "lng": 108.2611, "is_must_visit": False, "badge_label": "Resort 5 sao cao cấp bờ biển Non Nước"},
        {"name": "Mì Quảng Bà Mua & Bánh tráng cuốn thịt heo Đại Lộc", "category": "SPECIALTY_FOOD", "wiki_title": "Mì Quảng", "lat": 16.0650, "lng": 108.2200, "is_must_visit": True, "badge_label": "Đặc sản ẩm thực tinh túy xứ Quảng"},
        {"name": "Bún chả cá Đà Nẵng & Gỏi cá Nam Ô", "category": "SPECIALTY_FOOD", "wiki_title": "Bún chả cá", "lat": 16.0670, "lng": 108.2180, "is_must_visit": True, "badge_label": "Món ngon đậm vị biển miền Trung"}
    ],

    "Quảng Nam": [
        {"name": "Phố cổ Hội An", "category": "HISTORICAL_SITE", "wiki_title": "Hội An", "lat": 15.8800, "lng": 108.3380, "is_must_visit": True, "badge_label": "⭐ Di sản Văn hóa Thế giới UNESCO thương cảng cổ"},
        {"name": "Thánh địa Mỹ Sơn", "category": "HISTORICAL_SITE", "wiki_title": "Thánh địa Mỹ Sơn", "lat": 15.7656, "lng": 108.1242, "is_must_visit": True, "badge_label": "⭐ Di sản Thế giới đền tháp thung lũng Chăm Pa"},
        {"name": "Chùa Cầu Hội An (Lai Viễn Kiều)", "category": "HISTORICAL_SITE", "wiki_title": "Chùa Cầu", "lat": 15.8772, "lng": 108.3258, "is_must_visit": True, "badge_label": "⭐ Biểu tượng di sản in trên tờ tiền 20.000 VNĐ"},
        {"name": "Tượng đài Mẹ Thứ", "category": "HISTORICAL_SITE", "wiki_title": "Tam Kỳ", "lat": 15.5833, "lng": 108.4833, "is_must_visit": True, "badge_label": "Tượng đài Mẹ Việt Nam anh hùng lớn nhất Đông Nam Á"},
        {"name": "Cù Lao Chàm", "category": "ATTRACTION", "wiki_title": "Cù Lao Chàm", "lat": 15.9583, "lng": 108.5167, "is_must_visit": True, "badge_label": "Khu dự trữ sinh quyển thế giới san hô biển"},
        {"name": "Hồ Phú Ninh", "category": "ATTRACTION", "wiki_title": "Hồ Phú Ninh", "lat": 15.4833, "lng": 108.4333, "is_must_visit": True, "badge_label": "Hồ nước ngọc bích viên ngọc xanh xứ Quảng"},
        {"name": "Làng gốm Thanh Hà", "category": "ATTRACTION", "wiki_title": "Hội An", "lat": 15.8750, "lng": 108.3083, "is_must_visit": True, "badge_label": "Làng nghề gốm đất nung truyền thống hơn 500 năm"},
        {"name": "Làng rau Trà Quế", "category": "ATTRACTION", "wiki_title": "Hội An", "lat": 15.9000, "lng": 108.3333, "is_must_visit": False, "badge_label": "Làng rau sinh thái xanh tươi bón bằng rong sông"},
        {"name": "Rừng dừa Bảy Mẫu Cẩm Thanh", "category": "ATTRACTION", "wiki_title": "Hội An", "lat": 15.8700, "lng": 108.3667, "is_must_visit": True, "badge_label": "Trải nghiệm thuyền thúng múa nước sông nước miền Tây"},
        {"name": "Bãi biển An Bàng", "category": "ATTRACTION", "wiki_title": "Hội An", "lat": 15.9167, "lng": 108.3333, "is_must_visit": True, "badge_label": "Top những bãi biển bình yên nhất thế giới"},
        {"name": "Đỉnh Quế Tây Giang", "category": "ATTRACTION", "wiki_title": "Tây Giang", "lat": 15.9000, "lng": 107.5000, "is_must_visit": False, "badge_label": "Săn mây đại ngàn Trường Sơn hùng vĩ"},
        {"name": "Chùa Chúc Thánh Hội An", "category": "TEMPLE", "wiki_title": "Hội An", "lat": 15.8917, "lng": 108.3333, "is_must_visit": True, "badge_label": "Tổ đình Thiền phái Chúc Thánh hơn 300 năm"},
        {"name": "Chùa Vạn Đức Hội An", "category": "TEMPLE", "wiki_title": "Hội An", "lat": 15.8950, "lng": 108.3280, "is_must_visit": False, "badge_label": "Cổ tự thanh tịnh ngoại ô phố Hội"},
        {"name": "Chợ Hội An", "category": "MARKET", "wiki_title": "Hội An", "lat": 15.8789, "lng": 108.3317, "is_must_visit": True, "badge_label": "Chợ ẩm thực đường phố hấp dẫn hàng đầu châu Á"},
        {"name": "Chợ đêm Nguyễn Hoàng Hội An", "category": "MARKET", "wiki_title": "Hội An", "lat": 15.8767, "lng": 108.3244, "is_must_visit": False, "badge_label": "Chợ đèn lồng rực rỡ bên bờ sông Hoài"},
        {"name": "Four Seasons Resort The Nam Hai", "category": "HOTEL", "wiki_title": "Điện Bàn", "lat": 15.9167, "lng": 108.3167, "is_must_visit": False, "badge_label": "Khu nghỉ dưỡng biệt thự biển siêu sang 5 sao"},
        {"name": "Anantara Hoi An Resort", "category": "HOTEL", "wiki_title": "Hội An", "lat": 15.8783, "lng": 108.3389, "is_must_visit": False, "badge_label": "Resort 5 sao phong cách Pháp - Việt ven sông Thu Bồn"},
        {"name": "Cao lầu Hội An (Quán Bà Bé) & Cơm gà Bà Buội", "category": "SPECIALTY_FOOD", "wiki_title": "Cao lầu", "lat": 15.8792, "lng": 108.3306, "is_must_visit": True, "badge_label": "Hương vị ẩm thực phố cổ vang danh năm châu"},
        {"name": "Bê thui Cầu Mống Điện Bàn", "category": "SPECIALTY_FOOD", "wiki_title": "Điện Bàn", "lat": 15.9000, "lng": 108.2500, "is_must_visit": True, "badge_label": "Món bê thui chấm mắm nêm gia truyền trứ danh"}
    ],

    "Quảng Ngãi": [
        {"name": "Khu chứng tích Sơn Mỹ (Thảm sát Mỹ Lai)", "category": "HISTORICAL_SITE", "wiki_title": "Thảm sát Mỹ Lai", "lat": 15.1764, "lng": 108.8833, "is_must_visit": True, "badge_label": "Khu chứng tích lịch sử hòa bình thế giới"},
        {"name": "Bệnh xá Đặng Thùy Trâm", "category": "HISTORICAL_SITE", "wiki_title": "Đặng Thùy Trâm", "lat": 14.8500, "lng": 108.9833, "is_must_visit": True, "badge_label": "Nơi ghi dấu nhật ký người nữ liệt sĩ anh hùng"},
        {"name": "Khu di tích Khởi nghĩa Ba Tơ", "category": "HISTORICAL_SITE", "wiki_title": "Ba Tơ", "lat": 14.7667, "lng": 108.7333, "is_must_visit": True, "badge_label": "Chiếc nôi của Đội du kích Ba Tơ anh hùng"},
        {"name": "Chùa Thiên Ấn & Mộ cụ Huỳnh Thúc Kháng", "category": "TEMPLE", "wiki_title": "Núi Thiên Ấn", "lat": 15.1389, "lng": 108.8250, "is_must_visit": True, "badge_label": "Thiên Ấn Niêm Hà đệ nhất thắng cảnh xứ Quảng"},
        {"name": "Chùa Hang Lý Sơn (Thiên Khổng Thạch Tự)", "category": "TEMPLE", "wiki_title": "Lý Sơn", "lat": 15.3889, "lng": 109.1306, "is_must_visit": True, "badge_label": "Ngôi chùa trong vách đá núi lửa triệu năm"},
        {"name": "Đảo Lý Sơn (Vương quốc Tỏi)", "category": "ATTRACTION", "wiki_title": "Lý Sơn", "lat": 15.3833, "lng": 109.1167, "is_must_visit": True, "badge_label": "⭐ Trầm tích núi lửa triệu năm giữa biển khơi"},
        {"name": "Đỉnh Thới Lới & Cổng Tò Vò Lý Sơn", "category": "ATTRACTION", "wiki_title": "Lý Sơn", "lat": 15.3750, "lng": 109.1333, "is_must_visit": True, "badge_label": "Cổng đá bazan tự nhiên độc nhất vô nhị"},
        {"name": "Đảo Bé An Bình (Lý Sơn)", "category": "ATTRACTION", "wiki_title": "Lý Sơn", "lat": 15.4167, "lng": 109.0833, "is_must_visit": True, "badge_label": "Maldives thu nhỏ làn nước xanh thấu đáy"},
        {"name": "Bãi biển Mỹ Khê Quảng Ngãi", "category": "ATTRACTION", "wiki_title": "Quảng Ngãi (thành phố)", "lat": 15.1667, "lng": 108.8833, "is_must_visit": False, "badge_label": "Bãi biển rừng phi lao xanh ngát"},
        {"name": "Đèo Vi Ô Lắc", "category": "ATTRACTION", "wiki_title": "Ba Tơ", "lat": 14.7167, "lng": 108.5500, "is_must_visit": False, "badge_label": "Con đèo mây phủ nối đồng bằng lên Kon Tum"},
        {"name": "Thác Trắng Minh Long", "category": "ATTRACTION", "wiki_title": "Minh Long", "lat": 14.9500, "lng": 108.7000, "is_must_visit": False, "badge_label": "Thác nước tự nhiên đổ từ vách đá cao"},
        {"name": "Chợ Quảng Ngãi", "category": "MARKET", "wiki_title": "Quảng Ngãi (thành phố)", "lat": 15.1222, "lng": 108.8000, "is_must_visit": False, "badge_label": "Chợ trung tâm đầu mối nông lâm thủy sản"},
        {"name": "Chợ đêm bờ kè sông Trà Khúc", "category": "MARKET", "wiki_title": "Quảng Ngãi (thành phố)", "lat": 15.1278, "lng": 108.7944, "is_must_visit": False, "badge_label": "Chợ đêm gió mát ven sông Trà"},
        {"name": "Chợ cá Cảng Sa Kỳ", "category": "MARKET", "wiki_title": "Bình Sơn, Quảng Ngãi", "lat": 15.2167, "lng": 108.9167, "is_must_visit": False, "badge_label": "Chợ cá tàu thuyền tấp nập buổi sớm"},
        {"name": "Muong Thanh Holiday Ly Son", "category": "HOTEL", "wiki_title": "Lý Sơn", "lat": 15.3722, "lng": 109.1222, "is_must_visit": False, "badge_label": "Khách sạn 4 sao trung tâm đảo Lớn"},
        {"name": "Cocoland River Beach Resort & Spa", "category": "HOTEL", "wiki_title": "Tư Nghĩa", "lat": 15.0833, "lng": 108.8500, "is_must_visit": False, "badge_label": "Resort 4 sao sinh thái sông Vực Hồng"},
        {"name": "Cá bống sông Trà & Don Quảng Ngãi", "category": "SPECIALTY_FOOD", "wiki_title": "Sông Trà Khúc", "lat": 15.1250, "lng": 108.7986, "is_must_visit": True, "badge_label": "Món ngon sông Trà đi vào ca dao cổ tích"},
        {"name": "Tỏi Lý Sơn & Gỏi rong biển", "category": "SPECIALTY_FOOD", "wiki_title": "Lý Sơn", "lat": 15.3800, "lng": 109.1200, "is_must_visit": True, "badge_label": "Tỏi cô đơn và hương vị hải sản biển đảo"}
    ],

    "Bình Định": [
        {"name": "Tháp Đôi", "category": "HISTORICAL_SITE", "wiki_title": "Tháp Đôi", "lat": 13.7917, "lng": 109.2139, "is_must_visit": True, "badge_label": "⭐ Kiệt tác tháp đôi Chăm Pa thế kỷ XII"},
        {"name": "Tháp Bánh Ít", "category": "HISTORICAL_SITE", "wiki_title": "Tháp Bánh Ít", "lat": 13.9189, "lng": 109.1111, "is_must_visit": True, "badge_label": "⭐ Quần thể 4 ngọn tháp Chăm lọt top 1.001 công trình kiến trúc thế giới"},
        {"name": "Tháp Dương Long", "category": "HISTORICAL_SITE", "wiki_title": "Tháp Dương Long", "lat": 13.9472, "lng": 108.9861, "is_must_visit": True, "badge_label": "Tháp gạch cao nhất Đông Nam Á hơn 39m"},
        {"name": "Thành Hoàng Đế", "category": "HISTORICAL_SITE", "wiki_title": "An Nhơn", "lat": 13.9278, "lng": 109.0889, "is_must_visit": True, "badge_label": "Kinh đô thời Tây Sơn Di tích Quốc gia Đặc biệt"},
        {"name": "Bảo tàng Quang Trung & Đền thờ Tây Sơn Tam Kiệt", "category": "HISTORICAL_SITE", "wiki_title": "Bảo tàng Quang Trung", "lat": 13.9167, "lng": 108.9167, "is_must_visit": True, "badge_label": "⭐ Đất phát tích vị anh hùng áo vải cờ đào"},
        {"name": "Tiểu chủng viện Làng Sông", "category": "HISTORICAL_SITE", "wiki_title": "Tiểu chủng viện Làng Sông", "lat": 13.8333, "lng": 109.1833, "is_must_visit": True, "badge_label": "Một trong ba cơ sở in chữ Quốc ngữ đầu tiên tại VN"},
        {"name": "Chùa Thiên Hưng (Bình Định)", "category": "TEMPLE", "wiki_title": "An Nhơn", "lat": 13.8833, "lng": 109.1167, "is_must_visit": True, "badge_label": "Phượng Hoàng Cổ Trấn thu nhỏ của Bình Định"},
        {"name": "Chùa Long Khánh Quy Nhơn", "category": "TEMPLE", "wiki_title": "Quy Nhơn", "lat": 13.7750, "lng": 109.2300, "is_must_visit": False, "badge_label": "Tổ đình Phật giáo hơn 300 năm giữa lòng Quy Nhơn"},
        {"name": "Kỳ Co – Eo Gió (Quy Nhơn)", "category": "ATTRACTION", "wiki_title": "Quy Nhơn", "lat": 13.8833, "lng": 109.2833, "is_must_visit": True, "badge_label": "⭐ Nơi ngắm bình minh và hoàng hôn đẹp nhất Việt Nam"},
        {"name": "Ghềnh Ráng Tiên Sa & Mộ thi sĩ Hàn Mặc Tử", "category": "ATTRACTION", "wiki_title": "Ghềnh Ráng", "lat": 13.7444, "lng": 109.2194, "is_must_visit": True, "badge_label": "Bãi đá Trứng chim và di tích Hàn thi sĩ"},
        {"name": "Hòn Khô (Nhơn Hải)", "category": "ATTRACTION", "wiki_title": "Quy Nhơn", "lat": 13.7667, "lng": 109.3000, "is_must_visit": True, "badge_label": "Con đường cát nổi xuyên biển xanh ngọc"},
        {"name": "Cù Lao Xanh", "category": "ATTRACTION", "wiki_title": "Cù Lao Xanh", "lat": 13.6167, "lng": 109.3500, "is_must_visit": False, "badge_label": "Hòn ngọc xanh biếc giữa vịnh Xuân Đài"},
        {"name": "Đầm Thị Nại & Cầu Thị Nại", "category": "ATTRACTION", "wiki_title": "Đầm Thị Nại", "lat": 13.8000, "lng": 109.2500, "is_must_visit": True, "badge_label": "Cây cầu vượt biển dài nhất Việt Nam một thời"},
        {"name": "Chợ Đầm Quy Nhơn", "category": "MARKET", "wiki_title": "Quy Nhơn", "lat": 13.7806, "lng": 109.2319, "is_must_visit": False, "badge_label": "Chợ hải sản khô và tươi lớn nhất tỉnh"},
        {"name": "Chợ đêm Quy Nhơn", "category": "MARKET", "wiki_title": "Quy Nhơn", "lat": 13.7722, "lng": 109.2250, "is_must_visit": False, "badge_label": "Chợ đêm ẩm thực mua sắm cạnh phố biển"},
        {"name": "FLC Luxury Resort Quy Nhon", "category": "HOTEL", "wiki_title": "Tập đoàn FLC", "lat": 13.8806, "lng": 109.2611, "is_must_visit": False, "badge_label": "Quần thể resort 5 sao sân golf Eo Gió"},
        {"name": "Anantara Quy Nhon Villas", "category": "HOTEL", "wiki_title": "Quy Nhơn", "lat": 13.7167, "lng": 109.2167, "is_must_visit": False, "badge_label": "Khu nghỉ dưỡng biệt thự biển 5 sao đẳng cấp"},
        {"name": "Bánh xèo tôm nhảy rau mầm & Chả ram tôm đất", "category": "SPECIALTY_FOOD", "wiki_title": "Bánh xèo", "lat": 13.7750, "lng": 109.2283, "is_must_visit": True, "badge_label": "Món ngon xứ Nẫu giòn rụm tôm đất"},
        {"name": "Bún chả cá Quy Nhơn & Tré Bình Định", "category": "SPECIALTY_FOOD", "wiki_title": "Quy Nhơn", "lat": 13.7780, "lng": 109.2270, "is_must_visit": True, "badge_label": "Chả cá quết mịn nước lèo thanh ngọt và nem tré"}
    ],

    "Phú Yên": [
        {"name": "Gành Đá Đĩa", "category": "ATTRACTION", "wiki_title": "Gành Đá Đĩa", "lat": 13.3500, "lng": 109.2833, "is_must_visit": True, "badge_label": "⭐ Di tích Quốc gia Đặc biệt kỳ quan đá núi lửa"},
        {"name": "Mũi Điện (Mũi Đại Lãnh - Bãi Môn)", "category": "ATTRACTION", "wiki_title": "Mũi Đại Lãnh", "lat": 12.8833, "lng": 109.4667, "is_must_visit": True, "badge_label": "⭐ Nơi đón ánh bình minh đầu tiên trên đất liền"},
        {"name": "Bãi Xép - Gành Ông (Hoa vàng trên cỏ xanh)", "category": "ATTRACTION", "wiki_title": "Tuy An", "lat": 13.2000, "lng": 109.3000, "is_must_visit": True, "badge_label": "Bối cảnh phim ảnh nên thơ xứ Nẫu"},
        {"name": "Đầm Ô Loan", "category": "ATTRACTION", "wiki_title": "Đầm Ô Loan", "lat": 13.2500, "lng": 109.2833, "is_must_visit": True, "badge_label": "Đầm nước lợ danh thắng quốc gia nổi danh sò huyết"},
        {"name": "Vịnh Vũng Rô & Di tích Tàu Không Số", "category": "HISTORICAL_SITE", "wiki_title": "Vũng Rô", "lat": 12.8667, "lng": 109.4167, "is_must_visit": True, "badge_label": "Huyền thoại đường Hồ Chí Minh trên biển"},
        {"name": "Tháp Nhạn Tuy Hòa", "category": "HISTORICAL_SITE", "wiki_title": "Tháp Nhạn", "lat": 13.0889, "lng": 109.3083, "is_must_visit": True, "badge_label": "⭐ Di tích Quốc gia Đặc biệt tháp Chăm ngự sông Đà Rằng"},
        {"name": "Nhà thờ Mằng Lăng", "category": "HISTORICAL_SITE", "wiki_title": "Nhà thờ Mằng Lăng", "lat": 13.3167, "lng": 109.2167, "is_must_visit": True, "badge_label": "Nơi lưu giữ cuốn sách in chữ Quốc ngữ đầu tiên"},
        {"name": "Cầu gỗ Ông Cọp", "category": "ATTRACTION", "wiki_title": "Tuy An", "lat": 13.3333, "lng": 109.2500, "is_must_visit": True, "badge_label": "Cây cầu gỗ dài nhất Việt Nam mộc mạc bắc qua sông"},
        {"name": "Đảo Nhất Tự Sơn", "category": "ATTRACTION", "wiki_title": "Sông Cầu", "lat": 13.5167, "lng": 109.2667, "is_must_visit": False, "badge_label": "Hòn đảo có con đường cát chìm dưới nước độc đáo"},
        {"name": "Tháp Nghinh Phong Tuy Hòa", "category": "ATTRACTION", "wiki_title": "Tuy Hòa", "lat": 13.1020, "lng": 109.3200, "is_must_visit": True, "badge_label": "Công trình biểu tượng kiến trúc đương đại Phú Yên"},
        {"name": "Chùa Đá Trắng (Bạch Thạch Tự)", "category": "TEMPLE", "wiki_title": "Tuy An", "lat": 13.2833, "lng": 109.2000, "is_must_visit": True, "badge_label": "Cổ tự nổi danh giống xoài tiến vua ngự trị"},
        {"name": "Chùa Bảo Lâm Tuy Hòa", "category": "TEMPLE", "wiki_title": "Tuy Hòa", "lat": 13.1167, "lng": 109.2833, "is_must_visit": False, "badge_label": "Ngôi chùa thanh tịnh dưới chân núi Chóp Chài"},
        {"name": "Chợ Tuy Hòa", "category": "MARKET", "wiki_title": "Tuy Hòa", "lat": 13.0833, "lng": 109.3167, "is_must_visit": False, "badge_label": "Chợ đầu mối hải sản sầm uất lớn nhất tỉnh"},
        {"name": "Chợ đêm Tuy Hòa", "category": "MARKET", "wiki_title": "Tuy Hòa", "lat": 13.0917, "lng": 109.3111, "is_must_visit": False, "badge_label": "Chợ đêm đi bộ ẩm thực phong phú"},
        {"name": "Rosa Alba Resort & Spa Tuy Hoa", "category": "HOTEL", "wiki_title": "Tuy Hòa", "lat": 13.1000, "lng": 109.3167, "is_must_visit": False, "badge_label": "Resort 5 sao đẳng cấp mặt biển Tuy Hòa"},
        {"name": "Stelia Beach Resort Phú Yên", "category": "HOTEL", "wiki_title": "Tuy Hòa", "lat": 13.0958, "lng": 109.3208, "is_must_visit": False, "badge_label": "Resort phong cách Địa Trung Hải Santorini"},
        {"name": "Mắt cá ngừ đại dương hầm thuốc bắc", "category": "SPECIALTY_FOOD", "wiki_title": "Tuy Hòa", "lat": 13.0861, "lng": 109.3139, "is_must_visit": True, "badge_label": "Đặc sản độc nhất vô nhị chỉ có ở Phú Yên"},
        {"name": "Bánh hỏi lòng heo Đầm Ô Loan", "category": "SPECIALTY_FOOD", "wiki_title": "Bánh hỏi", "lat": 13.2550, "lng": 109.2800, "is_must_visit": True, "badge_label": "Bánh hỏi gạo thơm lòng heo nóng hổi và sò huyết"}
    ],

    "Khánh Hòa": [
        {"name": "Tháp Bà Ponagar", "category": "HISTORICAL_SITE", "wiki_title": "Tháp Bà Po Nagar", "lat": 12.2656, "lng": 109.1958, "is_must_visit": True, "badge_label": "⭐ Thánh địa tôn giáo Chăm Pa cổ kính trên đồi Cù Lao"},
        {"name": "Thành cổ Diên Khánh", "category": "HISTORICAL_SITE", "wiki_title": "Thành Diên Khánh", "lat": 12.2500, "lng": 109.1000, "is_must_visit": True, "badge_label": "Thành lũy quân sự kiểu Vauban thời Nguyễn"},
        {"name": "Viện Hải dương học Nha Trang", "category": "HISTORICAL_SITE", "wiki_title": "Viện Hải dương học Nha Trang", "lat": 12.2083, "lng": 109.2167, "is_must_visit": True, "badge_label": "Cơ sở lưu trữ và nghiên cứu sinh vật biển thế kỷ XX"},
        {"name": "Chùa Long Sơn (Chùa Phật Trắng)", "category": "TEMPLE", "wiki_title": "Chùa Long Sơn (Nha Trang)", "lat": 12.2514, "lng": 109.1806, "is_must_visit": True, "badge_label": "⭐ Tượng Kim Thân Phật Tổ uy nghiêm ngự đồi Trại Thủy"},
        {"name": "Chùa Từ Vân (Chùa Ốc Cam Ranh)", "category": "TEMPLE", "wiki_title": "Cam Ranh", "lat": 11.9167, "lng": 109.1500, "is_must_visit": True, "badge_label": "Ngôi chùa dựng từ vỏ ốc biển và san hô độc nhất vô nhị"},
        {"name": "Nhà thờ Núi Nha Trang (Chánh tòa)", "category": "TEMPLE", "wiki_title": "Nhà thờ chính tòa Nha Trang", "lat": 12.2467, "lng": 109.1883, "is_must_visit": True, "badge_label": "Kiến trúc Gothic Pháp cổ kính trên núi Bông"},
        {"name": "Vịnh Nha Trang", "category": "ATTRACTION", "wiki_title": "Vịnh Nha Trang", "lat": 12.2167, "lng": 109.2500, "is_must_visit": True, "badge_label": "⭐ Một trong những vịnh biển đẹp nhất thế giới"},
        {"name": "VinWonders Nha Trang (Hòn Tre)", "category": "ATTRACTION", "wiki_title": "Vinpearl Land (Nha Trang)", "lat": 12.2194, "lng": 109.2417, "is_must_visit": True, "badge_label": "Khu công viên giải trí biển đảo quy mô hàng đầu VN"},
        {"name": "Đảo Điệp Sơn", "category": "ATTRACTION", "wiki_title": "Vạn Ninh, Khánh Hòa", "lat": 12.6333, "lng": 109.2000, "is_must_visit": True, "badge_label": "Con đường cát trắng đi bộ xuyên biển độc đáo"},
        {"name": "Đảo Bình Hưng", "category": "ATTRACTION", "wiki_title": "Cam Ranh", "lat": 11.7833, "lng": 109.2000, "is_must_visit": True, "badge_label": "Hòn ngọc thô biển xanh ngắt nước tôm hùm"},
        {"name": "Vịnh Vân Phong", "category": "ATTRACTION", "wiki_title": "Vịnh Vân Phong", "lat": 12.6167, "lng": 109.3333, "is_must_visit": True, "badge_label": "Vịnh nước sâu nguyên sơ thiên nhiên tráng lệ"},
        {"name": "Bãi Dài Cam Ranh", "category": "ATTRACTION", "wiki_title": "Cam Lâm", "lat": 12.0667, "lng": 109.1833, "is_must_visit": False, "badge_label": "Bãi cát trắng mịn thoai thoải trải dài bất tận"},
        {"name": "Chợ Đầm Nha Trang", "category": "MARKET", "wiki_title": "Chợ Đầm", "lat": 12.2556, "lng": 109.1917, "is_must_visit": True, "badge_label": "Biểu tượng kiến trúc chợ tròn hoa sen phố biển"},
        {"name": "Chợ đêm Nha Trang (Phố đi bộ Yến Sào)", "category": "MARKET", "wiki_title": "Nha Trang", "lat": 12.2389, "lng": 109.1967, "is_must_visit": False, "badge_label": "Chợ đêm ẩm thực phố biển sầm uất"},
        {"name": "Chợ Xóm Mới Nha Trang", "category": "MARKET", "wiki_title": "Nha Trang", "lat": 12.2440, "lng": 109.1900, "is_must_visit": False, "badge_label": "Chợ hải sản địa phương giá tốt nổi tiếng"},
        {"name": "Vinpearl Resort & Spa Nha Trang Bay", "category": "HOTEL", "wiki_title": "Vinpearl", "lat": 12.2167, "lng": 109.2333, "is_must_visit": False, "badge_label": "Resort 5 sao đảo Hòn Tre sang trọng"},
        {"name": "Six Senses Ninh Van Bay", "category": "HOTEL", "wiki_title": "Ninh Hòa", "lat": 12.3583, "lng": 109.2833, "is_must_visit": False, "badge_label": "Resort 6 sao ẩn mình trong vịnh biệt lập xa hoa"},
        {"name": "Bún chả cá dầm Nha Trang & Yến sào Khánh Hòa", "category": "SPECIALTY_FOOD", "wiki_title": "Yến sào", "lat": 12.2472, "lng": 109.1944, "is_must_visit": True, "badge_label": "Đặc sản yến sào tiến vua và tô bún chả cá thanh ngọt"},
        {"name": "Nem nướng Ninh Hòa (Đặng Văn Quyên)", "category": "SPECIALTY_FOOD", "wiki_title": "Nem nướng Ninh Hòa", "lat": 12.2480, "lng": 109.1930, "is_must_visit": True, "badge_label": "Nem nướng lụi cuốn bánh tráng ram giòn sốt chấm đặc biệt"}
    ],

    "Ninh Thuận": [
        {"name": "Tháp Po Klong Garai", "category": "HISTORICAL_SITE", "wiki_title": "Po Klong Garai", "lat": 11.6042, "lng": 108.9486, "is_must_visit": True, "badge_label": "⭐ Di tích Quốc gia Đặc biệt quần thể Tháp Chăm đỉnh cao"},
        {"name": "Tháp Po Rome", "category": "HISTORICAL_SITE", "wiki_title": "Tháp Po Rome", "lat": 11.5333, "lng": 108.9333, "is_must_visit": True, "badge_label": "Ngôi tháp Chăm gạch nung cuối cùng tại Việt Nam"},
        {"name": "Vịnh Vĩnh Hy", "category": "ATTRACTION", "wiki_title": "Vịnh Vĩnh Hy", "lat": 11.7167, "lng": 109.2000, "is_must_visit": True, "badge_label": "⭐ Một trong 4 vịnh biển nguyên sơ đẹp nhất Việt Nam"},
        {"name": "Hang Rái (Núi Chúa)", "category": "ATTRACTION", "wiki_title": "Vườn quốc gia Núi Chúa", "lat": 11.7050, "lng": 109.1850, "is_must_visit": True, "badge_label": "Thềm san hô cổ hóa thạch tựa sao Hỏa bên bờ sóng"},
        {"name": "Đồng cừu An Hòa", "category": "ATTRACTION", "wiki_title": "Ninh Hải, Ninh Thuận", "lat": 11.6333, "lng": 108.9833, "is_must_visit": True, "badge_label": "Cánh đồng cừu du mục thảo nguyên bình yên"},
        {"name": "Đồi cát Nam Cương", "category": "ATTRACTION", "wiki_title": "Ninh Phước", "lat": 11.5333, "lng": 109.0000, "is_must_visit": True, "badge_label": "Dải sa mạc cát vàng thay hình đổi dạng theo gió"},
        {"name": "Vườn quốc gia Núi Chúa", "category": "ATTRACTION", "wiki_title": "Vườn quốc gia Núi Chúa", "lat": 11.7167, "lng": 109.1500, "is_must_visit": True, "badge_label": "Khu dự trữ sinh quyển thế giới rừng khô hạn độc đáo"},
        {"name": "Bãi biển Ninh Chữ", "category": "ATTRACTION", "wiki_title": "Ninh Chữ", "lat": 11.5833, "lng": 109.0333, "is_must_visit": True, "badge_label": "Bãi tắm vòng cung cát trắng hàng dương đón gió"},
        {"name": "Vườn nho Ba Mọi", "category": "ATTRACTION", "wiki_title": "Phan Rang – Tháp Chàm", "lat": 11.5800, "lng": 108.9500, "is_must_visit": True, "badge_label": "Vườn nho trĩu quả biểu tượng nông nghiệp xứ nắng"},
        {"name": "Mũi Dinh & Hải đăng Mũi Dinh", "category": "ATTRACTION", "wiki_title": "Thuận Nam", "lat": 11.3667, "lng": 109.0167, "is_must_visit": False, "badge_label": "Ngọn hải đăng cheo leo trên mỏm núi đá hoang sơ"},
        {"name": "Thiền viện Trúc Lâm Viên Ngộ", "category": "TEMPLE", "wiki_title": "Ninh Hải, Ninh Thuận", "lat": 11.6167, "lng": 109.0500, "is_must_visit": True, "badge_label": "Chùa hướng biển trên sườn núi Đá Chồng linh thiêng"},
        {"name": "Chùa Trùng Khánh", "category": "TEMPLE", "wiki_title": "Phan Rang – Tháp Chàm", "lat": 11.5833, "lng": 109.0200, "is_must_visit": False, "badge_label": "Ngôi chùa cổ xây từ đá xanh tự nhiên trên đồi"},
        {"name": "Chợ Phan Rang", "category": "MARKET", "wiki_title": "Phan Rang – Tháp Chàm", "lat": 11.5667, "lng": 108.9833, "is_must_visit": False, "badge_label": "Chợ trung tâm đầu mối tỏi, nho, táo và hải sản khô"},
        {"name": "Chợ Nại (Ninh Hải)", "category": "MARKET", "wiki_title": "Ninh Hải, Ninh Thuận", "lat": 11.5833, "lng": 109.0333, "is_must_visit": False, "badge_label": "Chợ cảng cá đầm Nại tôm cá tươi rói sớm mai"},
        {"name": "Amanoi Resort (Vịnh Vĩnh Hy)", "category": "HOTEL", "wiki_title": "Vịnh Vĩnh Hy", "lat": 11.7167, "lng": 109.1833, "is_must_visit": False, "badge_label": "Resort 6 sao siêu xa xỉ hàng đầu thế giới"},
        {"name": "TTC Resort Ninh Thuan", "category": "HOTEL", "wiki_title": "Phan Rang – Tháp Chàm", "lat": 11.5833, "lng": 109.0167, "is_must_visit": False, "badge_label": "Resort 4 sao bãi biển Ninh Chữ kiến trúc Chăm"},
        {"name": "Cơm gà Phan Rang & Nho Ninh Thuận", "category": "SPECIALTY_FOOD", "wiki_title": "Phan Rang – Tháp Chàm", "lat": 11.5681, "lng": 108.9861, "is_must_visit": True, "badge_label": "Gà thả vườn chấm muối ớt chanh và nho ngọt mát"},
        {"name": "Bánh căn & Bánh xèo Ninh Thuận", "category": "SPECIALTY_FOOD", "wiki_title": "Bánh căn", "lat": 11.5690, "lng": 108.9880, "is_must_visit": True, "badge_label": "Bánh đổ khuôn đất nung chấm 4 loại nước chấm đặc biệt"}
    ],

    "Bình Thuận": [
        {"name": "Hải đăng Kê Gà", "category": "ATTRACTION", "wiki_title": "Hải đăng Kê Gà", "lat": 10.6978, "lng": 107.9944, "is_must_visit": True, "badge_label": "Ngọn hải đăng cổ nhất và cao nhất Việt Nam"},
        {"name": "Bàu Trắng (Đồi Cát Trắng & Hồ Sen)", "category": "ATTRACTION", "wiki_title": "Bàu Trắng", "lat": 11.0667, "lng": 108.4167, "is_must_visit": True, "badge_label": "⭐ Tuyệt cảnh hồ sen ngọt ngào giữa mênh mông cát trắng"},
        {"name": "Tháp Po Sah Inư", "category": "HISTORICAL_SITE", "wiki_title": "Tháp Po Sah Inư", "lat": 10.9389, "lng": 108.1361, "is_must_visit": True, "badge_label": "Cụm tháp Chăm cổ thế kỷ VIII ngự đồi Bà Nài"},
        {"name": "Trường Dục Thanh", "category": "HISTORICAL_SITE", "wiki_title": "Trường Dục Thanh", "lat": 10.9278, "lng": 108.0986, "is_must_visit": True, "badge_label": "Nơi người thanh niên Nguyễn Tất Thành từng dạy học"},
        {"name": "Vạn Thủy Tú", "category": "HISTORICAL_SITE", "wiki_title": "Vạn Thủy Tú", "lat": 10.9250, "lng": 108.1000, "is_must_visit": True, "badge_label": "Nơi lưu giữ bộ xương cá Ông lớn nhất Đông Nam Á"},
        {"name": "Chùa Cổ Thạch (Chùa Hang)", "category": "TEMPLE", "wiki_title": "Chùa Cổ Thạch", "lat": 11.1967, "lng": 108.7000, "is_must_visit": True, "badge_label": "Chùa cổ trong hang đá bên bờ sóng nghìn năm"},
        {"name": "Dinh Thầy Thím", "category": "TEMPLE", "wiki_title": "Dinh Thầy Thím", "lat": 10.7167, "lng": 107.7833, "is_must_visit": True, "badge_label": "Di tích kiến trúc nghệ thuật tâm linh xứ La Gi"},
        {"name": "Đồi cát bay Mũi Né", "category": "ATTRACTION", "wiki_title": "Mũi Né", "lat": 10.9333, "lng": 108.2833, "is_must_visit": True, "badge_label": "⭐ Tiểu sa mạc Sahara biến đổi muôn hình theo gió"},
        {"name": "Suối Tiên Mũi Né", "category": "ATTRACTION", "wiki_title": "Mũi Né", "lat": 10.9500, "lng": 108.2500, "is_must_visit": True, "badge_label": "Dòng suối cạn đỏ cam bên tháp nhũ cát tuyệt mỹ"},
        {"name": "Đảo Phú Quý", "category": "ATTRACTION", "wiki_title": "Phú Quý", "lat": 10.5167, "lng": 108.9500, "is_must_visit": True, "badge_label": "Thiên đường biển đảo hoang sơ giữa đại dương"},
        {"name": "Bãi đá Cà Dược (Bãi đá 7 màu)", "category": "ATTRACTION", "wiki_title": "Tuy Phong", "lat": 11.1980, "lng": 108.7050, "is_must_visit": False, "badge_label": "Bãi đá sỏi đa sắc màu lấp lánh bên sóng biển"},
        {"name": "Làng chài Mũi Né", "category": "MARKET", "wiki_title": "Mũi Né", "lat": 10.9383, "lng": 108.2917, "is_must_visit": False, "badge_label": "Bến thuyền thúng mua bán hải sản tươi rói sớm mai"},
        {"name": "Chợ Phan Thiết", "category": "MARKET", "wiki_title": "Phan Thiết", "lat": 10.9278, "lng": 108.0986, "is_must_visit": False, "badge_label": "Chợ đầu mối hải sản và nước mắm truyền thống lâu đời"},
        {"name": "The Anam Mui Ne Resort", "category": "HOTEL", "wiki_title": "Mũi Né", "lat": 10.9500, "lng": 108.2167, "is_must_visit": False, "badge_label": "Resort 5 sao phong cách Đông Dương ven biển"},
        {"name": "Centara Mirage Resort Mui Ne", "category": "HOTEL", "wiki_title": "Mũi Né", "lat": 10.9417, "lng": 108.2667, "is_must_visit": False, "badge_label": "Resort công viên nước giải trí kiểu Địa Trung Hải"},
        {"name": "Pandanus Resort Mũi Né", "category": "HOTEL", "wiki_title": "Mũi Né", "lat": 10.9350, "lng": 108.2950, "is_must_visit": False, "badge_label": "Resort bãi biển rợp bóng dừa xanh mát"},
        {"name": "Lẩu thả Mũi Né & Bánh canh chả cá Phan Thiết", "category": "SPECIALTY_FOOD", "wiki_title": "Phan Thiết", "lat": 10.9306, "lng": 108.1014, "is_must_visit": True, "badge_label": "Đặc sản lẩu cá suốt trình bày hoa bắp chuối"},
        {"name": "Răng mực nướng & Bánh tráng nướng mắm ruốc", "category": "SPECIALTY_FOOD", "wiki_title": "Phan Thiết", "lat": 10.9280, "lng": 108.1020, "is_must_visit": True, "badge_label": "Món ăn vặt đường phố Phan Thiết đậm đà gió biển"}
    ],

    "Kon Tum": [
        {"name": "Nhà thờ Gỗ Kon Tum (Nhà thờ chính tòa)", "category": "HISTORICAL_SITE", "wiki_title": "Nhà thờ chính tòa Kon Tum", "lat": 14.3486, "lng": 108.0139, "is_must_visit": True, "badge_label": "⭐ Tuyệt tác kiến trúc gỗ Cà Chít hơn 100 năm"},
        {"name": "Di tích lịch sử Ngục Kon Tum", "category": "HISTORICAL_SITE", "wiki_title": "Kon Tum (thành phố)", "lat": 14.3400, "lng": 108.0050, "is_must_visit": True, "badge_label": "Di tích lịch sử kháng chiến oanh liệt của các chiến sĩ"},
        {"name": "Chiến trường Đắk Tô – Tân Cảnh", "category": "HISTORICAL_SITE", "wiki_title": "Đắk Tô", "lat": 14.6500, "lng": 107.8167, "is_must_visit": True, "badge_label": "Căn cứ chiến thắng hào hùng Bắc Tây Nguyên 1972"},
        {"name": "Chùa Bác Ái Kon Tum", "category": "TEMPLE", "wiki_title": "Kon Tum (thành phố)", "lat": 14.3583, "lng": 108.0083, "is_must_visit": True, "badge_label": "Ngôi sắc tứ cổ tự đầu tiên trên vùng đất Kon Tum"},
        {"name": "Tượng Đức Mẹ Măng Đen", "category": "TEMPLE", "wiki_title": "Măng Đen", "lat": 14.6000, "lng": 108.2900, "is_must_visit": True, "badge_label": "Điểm hành hương tâm linh nổi tiếng giữa đại ngàn"},
        {"name": "Cầu treo Kon Klor & Nhà rông Kon Klor", "category": "ATTRACTION", "wiki_title": "Kon Tum (thành phố)", "lat": 14.3458, "lng": 108.0333, "is_must_visit": True, "badge_label": "Nhà rông lớn nhất Tây Nguyên bên dòng Đăk Bla"},
        {"name": "Khu du lịch sinh thái Măng Đen", "category": "ATTRACTION", "wiki_title": "Măng Đen", "lat": 14.6000, "lng": 108.2833, "is_must_visit": True, "badge_label": "⭐ Đà Lạt thứ hai giữa đại ngàn thông reo"},
        {"name": "Thác Pa Sỹ Măng Đen", "category": "ATTRACTION", "wiki_title": "Măng Đen", "lat": 14.6167, "lng": 108.2667, "is_must_visit": True, "badge_label": "Thác nước trắng xóa tuôn trào giữa rừng nguyên sinh"},
        {"name": "Hồ Đăk Ke Măng Đen", "category": "ATTRACTION", "wiki_title": "Măng Đen", "lat": 14.6050, "lng": 108.2800, "is_must_visit": False, "badge_label": "Hồ nước thơ mộng trong truyền thuyết 7 hồ 3 thác"},
        {"name": "Ngã ba Đông Dương (Cửa khẩu Bờ Y)", "category": "ATTRACTION", "wiki_title": "Ngọc Hồi, Kon Tum", "lat": 14.6833, "lng": 107.5667, "is_must_visit": True, "badge_label": "Một tiếng gà gáy ba nước cùng nghe"},
        {"name": "Vườn quốc gia Chư Mom Ray", "category": "ATTRACTION", "wiki_title": "Vườn quốc gia Chư Mom Ray", "lat": 14.5000, "lng": 107.7167, "is_must_visit": True, "badge_label": "Khu bảo tồn động thực vật quý hiếm Đông Dương"},
        {"name": "Chợ trung tâm TP Kon Tum", "category": "MARKET", "wiki_title": "Kon Tum (thành phố)", "lat": 14.3500, "lng": 108.0056, "is_must_visit": False, "badge_label": "Chợ sầm uất bên bờ sông Đăk Bla chảy ngược"},
        {"name": "Chợ phiên Măng Đen", "category": "MARKET", "wiki_title": "Kon Plông", "lat": 14.6028, "lng": 108.2889, "is_must_visit": False, "badge_label": "Chợ rau củ quả xứ lạnh và sâm dây dược liệu"},
        {"name": "Indochine Hotel Kon Tum", "category": "HOTEL", "wiki_title": "Kon Tum (thành phố)", "lat": 14.3425, "lng": 108.0208, "is_must_visit": False, "badge_label": "Khách sạn 4 sao với quán cà phê kiến trúc tre kỷ lục"},
        {"name": "Golden Boutique Hotel Mang Den", "category": "HOTEL", "wiki_title": "Măng Đen", "lat": 14.6056, "lng": 108.2917, "is_must_visit": False, "badge_label": "Khách sạn 4 sao cao cấp tại thị trấn Măng Đen"},
        {"name": "Khách sạn Hưng Yên Măng Đen", "category": "HOTEL", "wiki_title": "Măng Đen", "lat": 14.6030, "lng": 108.2900, "is_must_visit": False, "badge_label": "Khách sạn tiện nghi giữa rừng thông"},
        {"name": "Gà nướng cơm lam Măng Đen & Gỏi lá Kon Tum", "category": "SPECIALTY_FOOD", "wiki_title": "Gỏi lá Kon Tum", "lat": 14.3517, "lng": 108.0069, "is_must_visit": True, "badge_label": "Món ăn kết hợp hơn 40 loại lá rừng đại ngàn"},
        {"name": "Heo Broong heo mọi nướng Măng Đen", "category": "SPECIALTY_FOOD", "wiki_title": "Măng Đen", "lat": 14.6040, "lng": 108.2850, "is_must_visit": True, "badge_label": "Đặc sản thịt heo mọi nướng than củi chấm muối tiêu rừng"}
    ],

    "Gia Lai": [
        {"name": "Quảng trường Đại Đoàn Kết Pleiku", "category": "HISTORICAL_SITE", "wiki_title": "Pleiku", "lat": 13.9833, "lng": 108.0056, "is_must_visit": True, "badge_label": "Tượng đài Bác Hồ với các dân tộc Tây Nguyên"},
        {"name": "Di tích lịch sử Nhà lao Pleiku", "category": "HISTORICAL_SITE", "wiki_title": "Pleiku", "lat": 13.9750, "lng": 108.0100, "is_must_visit": True, "badge_label": "Nơi giam giữ các chiến sĩ cách mạng kiên trung"},
        {"name": "Di tích Tây Sơn Thượng Đạo (An Khê)", "category": "HISTORICAL_SITE", "wiki_title": "An Khê", "lat": 13.9500, "lng": 108.6500, "is_must_visit": True, "badge_label": "Căn cứ địa phát tích khởi nghĩa Tây Sơn"},
        {"name": "Chùa Minh Thành Gia Lai", "category": "TEMPLE", "wiki_title": "Chùa Minh Thành", "lat": 13.9722, "lng": 107.9944, "is_must_visit": True, "badge_label": "⭐ Tuyệt tác kiến trúc Phật giáo mang phong cách Á Đông"},
        {"name": "Chùa Bửu Minh (Đồi chè Biển Hồ)", "category": "TEMPLE", "wiki_title": "Chư Păh", "lat": 14.0667, "lng": 108.0167, "is_must_visit": True, "badge_label": "Ngôi chùa cổ kính soi bóng bên đồi chè trăm năm"},
        {"name": "Biển Hồ T'Nưng (Đôi mắt Pleiku)", "category": "ATTRACTION", "wiki_title": "Hồ T'Nưng", "lat": 14.0500, "lng": 108.0000, "is_must_visit": True, "badge_label": "⭐ Miệng núi lửa triệu năm nước xanh ngắt sâu thẳm"},
        {"name": "Núi lửa Chư Đăng Ya", "category": "ATTRACTION", "wiki_title": "Chư Đăng Ya", "lat": 14.1333, "lng": 108.0333, "is_must_visit": True, "badge_label": "Thiên đường hoa dã quỳ nhuộm vàng lòng núi lửa"},
        {"name": "Thác Phú Cường", "category": "ATTRACTION", "wiki_title": "Chư Sê", "lat": 13.6833, "lng": 108.1167, "is_must_visit": True, "badge_label": "Dòng thác hùng vĩ đổ trên nền nham thạch cổ"},
        {"name": "Đồi chè Biển Hồ Gia Lai", "category": "ATTRACTION", "wiki_title": "Chư Păh", "lat": 14.0600, "lng": 108.0100, "is_must_visit": True, "badge_label": "Hàng thông trăm tuổi và đồn điền chè đầu tiên thời Pháp"},
        {"name": "Thác K50 (Khu bảo tồn Kon Chư Răng)", "category": "ATTRACTION", "wiki_title": "Khu bảo tồn thiên nhiên Kon Chư Răng", "lat": 14.5167, "lng": 108.5667, "is_must_visit": True, "badge_label": "Dải lụa bạc giữa rừng nguyên sinh đại ngàn"},
        {"name": "Vườn quốc gia Kon Ka Kinh", "category": "ATTRACTION", "wiki_title": "Vườn quốc gia Kon Ka Kinh", "lat": 14.2167, "lng": 108.3167, "is_must_visit": False, "badge_label": "Vườn di sản ASEAN mái nhà của nóc nhà Gia Lai"},
        {"name": "Chợ trung tâm Pleiku", "category": "MARKET", "wiki_title": "Pleiku", "lat": 13.9778, "lng": 108.0000, "is_must_visit": False, "badge_label": "Chợ đầu mối nông sản cà phê hồ tiêu lớn nhất tỉnh"},
        {"name": "Chợ đêm Pleiku", "category": "MARKET", "wiki_title": "Pleiku", "lat": 13.9792, "lng": 108.0017, "is_must_visit": False, "badge_label": "Chợ đêm ẩm thực phố núi se lạnh tấp nập"},
        {"name": "Khách sạn Hoàng Anh Gia Lai", "category": "HOTEL", "wiki_title": "Pleiku", "lat": 13.9767, "lng": 108.0083, "is_must_visit": False, "badge_label": "Khách sạn 4 sao cao cấp trung tâm thành phố"},
        {"name": "Boston Hotel Pleiku", "category": "HOTEL", "wiki_title": "Pleiku", "lat": 13.9856, "lng": 108.0028, "is_must_visit": False, "badge_label": "Khách sạn tiện nghi phong cách hiện đại"},
        {"name": "Khách sạn Tre Xanh Pleiku", "category": "HOTEL", "wiki_title": "Pleiku", "lat": 13.9800, "lng": 108.0050, "is_must_visit": False, "badge_label": "Khách sạn dịch vụ đầy đủ trung tâm Pleiku"},
        {"name": "Phở khô Gia Lai (Phở Hai Tô Hồng)", "category": "SPECIALTY_FOOD", "wiki_title": "Pleiku", "lat": 13.9789, "lng": 108.0033, "is_must_visit": True, "badge_label": "Kỷ lục ẩm thực châu Á một tô phở một tô súp bò"},
        {"name": "Bò một nắng Krông Pa & Muối kiến vàng", "category": "SPECIALTY_FOOD", "wiki_title": "Krông Pa", "lat": 13.2000, "lng": 108.7000, "is_must_visit": True, "badge_label": "Đặc sản thịt bò tơ phơi một nắng chấm muối kiến chua"}
    ],

    "Đắk Lắk": [
        {"name": "Bảo tàng Thế giới Cà phê Buôn Ma Thuột", "category": "HISTORICAL_SITE", "wiki_title": "Buôn Ma Thuột", "lat": 12.6972, "lng": 108.0583, "is_must_visit": True, "badge_label": "⭐ Biểu tượng kiến trúc nhà dài thủ phủ cà phê"},
        {"name": "Nhà đày Buôn Ma Thuột", "category": "HISTORICAL_SITE", "wiki_title": "Buôn Ma Thuột", "lat": 12.6780, "lng": 108.0460, "is_must_visit": True, "badge_label": "Di tích Quốc gia Đặc biệt nơi giam cầm các chí sĩ"},
        {"name": "Biệt điện Bảo Đại Đắk Lắk", "category": "HISTORICAL_SITE", "wiki_title": "Buôn Ma Thuột", "lat": 12.6840, "lng": 108.0490, "is_must_visit": True, "badge_label": "Dinh thự nghỉ ngơi của vua Bảo Đại giữa vườn cây cổ thụ"},
        {"name": "Chùa Sắc Tứ Khải Đoan", "category": "TEMPLE", "wiki_title": "Chùa Khải Đoan", "lat": 12.6861, "lng": 108.0444, "is_must_visit": True, "badge_label": "Ngôi chùa cuối cùng được phong Sắc Tứ triều Nguyễn"},
        {"name": "Chùa Hoa Nghiêm Buôn Ma Thuột", "category": "TEMPLE", "wiki_title": "Buôn Ma Thuột", "lat": 12.6750, "lng": 108.0400, "is_must_visit": False, "badge_label": "Ngôi chùa thanh tịnh giữa phố núi Đắk Lắk"},
        {"name": "Thác Dray Nur", "category": "ATTRACTION", "wiki_title": "Thác Dray Nur", "lat": 12.5333, "lng": 107.8833, "is_must_visit": True, "badge_label": "⭐ Thác Vợ hùng vĩ trắng xóa trên dòng sông Sêrêpôk"},
        {"name": "Thác Dray Sap", "category": "ATTRACTION", "wiki_title": "Thác Dray Nur", "lat": 12.5350, "lng": 107.8800, "is_must_visit": True, "badge_label": "Thác Chồng màn khói nước bảng lảng núi rừng"},
        {"name": "Hồ Lắk & Buôn Jun", "category": "ATTRACTION", "wiki_title": "Hồ Lắk", "lat": 12.4167, "lng": 108.1833, "is_must_visit": True, "badge_label": "Hồ nước ngọt tự nhiên lớn thứ hai Việt Nam"},
        {"name": "Buôn Đôn (Bản Đôn quê hương Voi)", "category": "ATTRACTION", "wiki_title": "Buôn Đôn", "lat": 12.8917, "lng": 107.7833, "is_must_visit": True, "badge_label": "Cái nôi văn hóa thuần dưỡng voi rừng Tây Nguyên"},
        {"name": "Vườn quốc gia Yok Đôn", "category": "ATTRACTION", "wiki_title": "Vườn quốc gia Yok Đôn", "lat": 12.8667, "lng": 107.7500, "is_must_visit": True, "badge_label": "Khu rừng khộp rụng lá mùa khô lớn nhất Việt Nam"},
        {"name": "Đá Voi Mẹ Yang Tao", "category": "ATTRACTION", "wiki_title": "Lắk", "lat": 12.4667, "lng": 108.2333, "is_must_visit": False, "badge_label": "Tảng đá nguyên khối lớn nhất Việt Nam hình voi phục"},
        {"name": "Chợ trung tâm Buôn Ma Thuột", "category": "MARKET", "wiki_title": "Buôn Ma Thuột", "lat": 12.6806, "lng": 108.0389, "is_must_visit": False, "badge_label": "Chợ đầu mối nông sản cà phê hồ tiêu lớn nhất tỉnh"},
        {"name": "Chợ đêm Buôn Ma Thuột", "category": "MARKET", "wiki_title": "Buôn Ma Thuột", "lat": 12.6847, "lng": 108.0417, "is_must_visit": False, "badge_label": "Chợ đêm ẩm thực phố núi rộn ràng ngã sáu"},
        {"name": "Khách sạn Mường Thanh Luxury Buôn Ma Thuột", "category": "HOTEL", "wiki_title": "Tập đoàn Mường Thanh", "lat": 12.6944, "lng": 108.0639, "is_must_visit": False, "badge_label": "Khách sạn 5 sao cao cấp trung tâm thành phố"},
        {"name": "Lắk Tented Camp Resort", "category": "HOTEL", "wiki_title": "Hồ Lắk", "lat": 12.4111, "lng": 108.1750, "is_must_visit": False, "badge_label": "Khu nghỉ dưỡng lều sinh thái ven hồ Lắk thơ mộng"},
        {"name": "Khách sạn Sài Gòn Ban Mê", "category": "HOTEL", "wiki_title": "Buôn Ma Thuột", "lat": 12.6820, "lng": 108.0430, "is_must_visit": False, "badge_label": "Khách sạn 4 sao nhìn ra tượng đài ngã sáu"},
        {"name": "Cà phê chồn Buôn Ma Thuột & Bún đỏ Cao Nguyên", "category": "SPECIALTY_FOOD", "wiki_title": "Buôn Ma Thuột", "lat": 12.6833, "lng": 108.0425, "is_must_visit": True, "badge_label": "Tách cà phê thơm nồng và tô bún đỏ cua đồng đặc trưng"},
        {"name": "Gà nướng Bản Đôn & Cơm lam", "category": "SPECIALTY_FOOD", "wiki_title": "Buôn Đôn", "lat": 12.8900, "lng": 107.7850, "is_must_visit": True, "badge_label": "Gà thả rẫy nướng than củi chấm muối é ớt rừng"}
    ],

    "Đắk Nông": [
        {"name": "Nhà ngục Đăk Mil", "category": "HISTORICAL_SITE", "wiki_title": "Nhà ngục Đăk Mil", "lat": 12.4514, "lng": 107.6083, "is_must_visit": True, "badge_label": "⭐ Di tích lịch sử Quốc gia ngục đày cách mạng"},
        {"name": "Tượng đài N'Trang Lơng Gia Nghĩa", "category": "HISTORICAL_SITE", "wiki_title": "N'Trang Lơng", "lat": 12.0080, "lng": 107.6870, "is_must_visit": True, "badge_label": "Tượng đài người tù trưởng M'Nông khởi nghĩa anh dũng"},
        {"name": "Chùa Pháp Hoa Đắk Nông", "category": "TEMPLE", "wiki_title": "Gia Nghĩa", "lat": 12.0000, "lng": 107.6833, "is_must_visit": True, "badge_label": "Ngôi chùa trên đồi cao nhìn toàn cảnh thành phố"},
        {"name": "Chùa Hoa Nghiêm Đắk Mil", "category": "TEMPLE", "wiki_title": "Đắk Mil", "lat": 12.4450, "lng": 107.6250, "is_must_visit": False, "badge_label": "Chùa cổ thanh tịnh huyện Đắk Mil"},
        {"name": "Công viên địa chất toàn cầu UNESCO Đắk Nông", "category": "ATTRACTION", "wiki_title": "Công viên địa chất Đắk Nông", "lat": 12.2500, "lng": 107.6833, "is_must_visit": True, "badge_label": "⭐ Hệ thống hang động núi lửa dài nhất Đông Nam Á"},
        {"name": "Hồ Tà Đùng (Vịnh Hạ Long của Tây Nguyên)", "category": "ATTRACTION", "wiki_title": "Hồ Tà Đùng", "lat": 11.8667, "lng": 107.9833, "is_must_visit": True, "badge_label": "⭐ Tuyệt tác gần 40 hòn đảo lớn nhỏ trên mặt hồ biếc"},
        {"name": "Thác Liêng Nung", "category": "ATTRACTION", "wiki_title": "Gia Nghĩa", "lat": 12.0333, "lng": 107.7500, "is_must_visit": True, "badge_label": "Vòm đá bazan tổ ong kỳ vĩ như tranh"},
        {"name": "Thác Đray Sáp (Khu vực Đắk Nông)", "category": "ATTRACTION", "wiki_title": "Thác Đray Sáp", "lat": 12.5361, "lng": 107.8806, "is_must_visit": True, "badge_label": "Thác khói sương bảng lảng đại ngàn hùng vĩ"},
        {"name": "Thác Gia Long", "category": "ATTRACTION", "wiki_title": "Thác Đray Sáp", "lat": 12.5400, "lng": 107.8750, "is_must_visit": False, "badge_label": "Dòng thác hoang sơ gắn liền dấu chân vua Gia Long"},
        {"name": "Thác Trinh Nữ", "category": "ATTRACTION", "wiki_title": "Cư Jút", "lat": 12.5833, "lng": 107.8667, "is_must_visit": False, "badge_label": "Dòng thác êm đềm len lỏi qua hang đá bazan"},
        {"name": "Hồ Tây Đắk Mil", "category": "ATTRACTION", "wiki_title": "Đắk Mil", "lat": 12.4500, "lng": 107.6333, "is_must_visit": True, "badge_label": "Hồ nước bán nhân tạo thanh bình như đôi mắt biếc"},
        {"name": "Thác Đắk G'lun", "category": "ATTRACTION", "wiki_title": "Tuy Đức", "lat": 12.0833, "lng": 107.5333, "is_must_visit": False, "badge_label": "Thác nước đôi cao hơn 50m giữa thung lũng xanh"},
        {"name": "Chợ Gia Nghĩa", "category": "MARKET", "wiki_title": "Gia Nghĩa", "lat": 12.0056, "lng": 107.6889, "is_must_visit": False, "badge_label": "Chợ trung tâm đầu mối lớn nhất tỉnh Đắk Nông"},
        {"name": "Chợ phiên Đắk Mil", "category": "MARKET", "wiki_title": "Đắk Mil", "lat": 12.4500, "lng": 107.6167, "is_must_visit": False, "badge_label": "Chợ nông sản sầu riêng bơ sáp trứ danh Đắk Mil"},
        {"name": "Tà Đùng Topview Homestay & Resort", "category": "HOTEL", "wiki_title": "Hồ Tà Đùng", "lat": 11.8722, "lng": 107.9778, "is_must_visit": False, "badge_label": "Resort hồ bơi vô cực ngắm trọn vịnh Tà Đùng"},
        {"name": "Khách sạn Robin Hotel Gia Nghĩa", "category": "HOTEL", "wiki_title": "Gia Nghĩa", "lat": 12.0083, "lng": 107.6861, "is_must_visit": False, "badge_label": "Khách sạn tiện nghi trung tâm thành phố"},
        {"name": "Cơm lam gà sa lửa Đắk Nông & Cá lăng sông Sêrêpôk", "category": "SPECIALTY_FOOD", "wiki_title": "Sông Srepok", "lat": 12.0067, "lng": 107.6850, "is_must_visit": True, "badge_label": "Ẩm thực nướng than củi thơm lừng đại ngàn"},
        {"name": "Cà phê Đắk Nông & Bơ sáp Đắk Mil", "category": "SPECIALTY_FOOD", "wiki_title": "Đắk Mil", "lat": 12.4480, "lng": 107.6200, "is_must_visit": True, "badge_label": "Đặc sản trái bơ sáp béo ngậy và hương vị cà phê bazan"}
    ],

    "Lâm Đồng": [
        {"name": "Dinh III Bảo Đại", "category": "HISTORICAL_SITE", "wiki_title": "Dinh Bảo Đại (Đà Lạt)", "lat": 11.9297, "lng": 108.4294, "is_must_visit": True, "badge_label": "⭐ Dinh thự nghỉ ngơi của vị Hoàng đế cuối cùng triều Nguyễn"},
        {"name": "Dinh I Bảo Đại (King Palace)", "category": "HISTORICAL_SITE", "wiki_title": "Dinh Bảo Đại (Đà Lạt)", "lat": 11.9333, "lng": 108.4667, "is_must_visit": True, "badge_label": "Dinh thự bề thế trên đồi thông thơ mộng"},
        {"name": "Ga Đà Lạt", "category": "HISTORICAL_SITE", "wiki_title": "Ga Đà Lạt", "lat": 11.9417, "lng": 108.4550, "is_must_visit": True, "badge_label": "Nhà ga cổ kính nhất Đông Dương kiến trúc răng cưa"},
        {"name": "Thiền viện Trúc Lâm Đà Lạt", "category": "TEMPLE", "wiki_title": "Thiền viện Trúc Lâm (Đà Lạt)", "lat": 11.9056, "lng": 108.4358, "is_must_visit": True, "badge_label": "⭐ Tổ đình thiền viện trên núi Phụng Hoàng soi bóng hồ Tuyền Lâm"},
        {"name": "Chùa Linh Phước (Chùa Ve Chai)", "category": "TEMPLE", "wiki_title": "Chùa Linh Phước", "lat": 11.9444, "lng": 108.4986, "is_must_visit": True, "badge_label": "⭐ Công trình khảm sành sứ rồng dài 49m kỷ lục"},
        {"name": "Chùa Linh Quy Pháp Ấn (Bảo Lộc)", "category": "TEMPLE", "wiki_title": "Bảo Lâm, Lâm Đồng", "lat": 11.5167, "lng": 107.7500, "is_must_visit": True, "badge_label": "Cổng trời săn mây đón bình minh tuyệt cảnh"},
        {"name": "Chùa Tàu (Thiên Vương Cổ Sát)", "category": "TEMPLE", "wiki_title": "Thiên Vương Cổ Sát", "lat": 11.9350, "lng": 108.4600, "is_must_visit": False, "badge_label": "Ngôi chùa ba pho tượng Phật trầm hương và chiếc bàn xoay kỳ lạ"},
        {"name": "Hồ Xuân Hương & Quảng trường Lâm Viên", "category": "ATTRACTION", "wiki_title": "Hồ Xuân Hương (Đà Lạt)", "lat": 11.9406, "lng": 108.4456, "is_must_visit": True, "badge_label": "⭐ Trái tim mộng mơ của xứ sở sương mù ngàn hoa"},
        {"name": "Thác Datanla", "category": "ATTRACTION", "wiki_title": "Thác Datanla", "lat": 11.9036, "lng": 108.4489, "is_must_visit": True, "badge_label": "Máng trượt dài nhất Đông Nam Á băng qua rừng thông"},
        {"name": "Thác Pongour", "category": "ATTRACTION", "wiki_title": "Thác Pongour", "lat": 11.6917, "lng": 108.2667, "is_must_visit": True, "badge_label": "Nam thiên đệ nhất thác 7 tầng kỳ vĩ"},
        {"name": "Thác Dambri (Bảo Lộc)", "category": "ATTRACTION", "wiki_title": "Thác Dambri", "lat": 11.6333, "lng": 107.7500, "is_must_visit": True, "badge_label": "Ngọn thác cao nhất tỉnh đổ nước gầm vang hùng tráng"},
        {"name": "Hồ Tuyền Lâm", "category": "ATTRACTION", "wiki_title": "Hồ Tuyền Lâm", "lat": 11.8950, "lng": 108.4300, "is_must_visit": True, "badge_label": "Khu du lịch quốc gia mặt hồ phẳng lặng thông xanh ngắt"},
        {"name": "Langbiang (Đỉnh núi Bà Langbiang)", "category": "ATTRACTION", "wiki_title": "Núi Bà (Lâm Đồng)", "lat": 12.0433, "lng": 108.4333, "is_must_visit": True, "badge_label": "Nóc nhà Đà Lạt nơi ghi dấu thiên tình sử K'Lang và H'Biang"},
        {"name": "Chợ Đà Lạt & Chợ đêm Âm Phủ", "category": "MARKET", "wiki_title": "Chợ Đà Lạt", "lat": 11.9422, "lng": 108.4367, "is_must_visit": True, "badge_label": "Thiên đường áo len hoa quả tươi và bánh tráng nướng"},
        {"name": "Chợ Bảo Lộc", "category": "MARKET", "wiki_title": "Bảo Lộc", "lat": 11.5450, "lng": 107.8050, "is_must_visit": False, "badge_label": "Chợ đầu mối nông sản chè và tơ tằm Nam Tây Nguyên"},
        {"name": "Dalat Palace Heritage Hotel", "category": "HOTEL", "wiki_title": "Dalat Palace", "lat": 11.9389, "lng": 108.4417, "is_must_visit": False, "badge_label": "Khách sạn 5 sao di sản sang trọng từ năm 1922"},
        {"name": "Ana Mandara Villas Dalat Resort & Spa", "category": "HOTEL", "wiki_title": "Đà Lạt", "lat": 11.9444, "lng": 108.4236, "is_must_visit": False, "badge_label": "Quần thể biệt thự Pháp cổ 5 sao lưng đồi thông"},
        {"name": "Lẩu gà lá é Tao Ngộ & Bánh ướt lòng gà Long", "category": "SPECIALTY_FOOD", "wiki_title": "Đà Lạt", "lat": 11.9367, "lng": 108.4439, "is_must_visit": True, "badge_label": "Món ăn ấm lòng giữa tiết trời se lạnh phố núi sương mù"},
        {"name": "Bánh tráng nướng Đà Lạt & Sữa đậu nành Tăng Bạt Hổ", "category": "SPECIALTY_FOOD", "wiki_title": "Đà Lạt", "lat": 11.9410, "lng": 108.4380, "is_must_visit": True, "badge_label": "Pizza Việt Nam giòn rụm bên ly sữa đậu nành nóng hổi"}
    ]
}

def main():
    print("=" * 70)
    print("VNTRAVEL AI - MIỀN TRUNG & TÂY NGUYÊN HARVEST & ENRICHMENT PIPELINE")
    print("=" * 70)

    # 1. Khởi tạo WikipediaFetcher
    fetcher = WikipediaFetcher()
    pipeline = HarvestPipeline()
    seen_photos = set()

    # Tải dataset hiện tại để tham chiếu và tái sử dụng ảnh/mô tả đã có
    with open(os.path.join(ROOT_DIR, "data", "places_63_to_34.json"), "r", encoding="utf-8") as f:
        existing_all = json.load(f)

    # Tạo map tra cứu theo (original_province, name) hoặc wiki_title
    existing_map = {}
    for p in existing_all:
        prov = p.get("original_province")
        name = p.get("name")
        wiki_title = p.get("wiki_title")
        if prov and name:
            existing_map[(prov, name.lower())] = p
        if wiki_title:
            existing_map[wiki_title.lower()] = p

    total_provinces = len(CENTRAL_PROVINCES)
    print(f"[*] Xử lý {total_provinces} tỉnh thành Miền Trung & Tây Nguyên...")

    all_harvested_records = []
    base_id = 3000

    for prov_idx, prov in enumerate(CENTRAL_PROVINCES, 1):
        items = CURATED_CENTRAL_PLACES.get(prov, [])
        mapping = MAPPING_63_TO_34.get(prov, {})
        target_code = mapping.get("target_code")
        target_name = mapping.get("target_name")
        region = mapping.get("region")

        print(f"\n[{prov_idx}/{total_provinces}] Đang xử lý tỉnh {prov} ({len(items)} địa danh)...")

        for item_idx, raw_place in enumerate(items):
            base_id += 1
            name = raw_place["name"]
            category = raw_place["category"]
            wiki_title = raw_place.get("wiki_title") or name
            lat = raw_place.get("lat")
            lng = raw_place.get("lng")
            is_must_visit = raw_place.get("is_must_visit", False)
            badge_label = raw_place.get("badge_label", "")

            # Kiểm tra xem địa danh đã có trong existing dataset chưa
            existing = existing_map.get((prov, name.lower())) or existing_map.get(wiki_title.lower())
            
            photo_url = None
            description = ""
            wiki_url = f"https://vi.wikipedia.org/wiki/{wiki_title.replace(' ', '_')}"

            # 1. Thử lấy từ existing nếu hợp lệ
            if existing:
                ex_photo = existing.get("photo_url")
                if ex_photo and not is_blacklisted_photo(ex_photo) and ex_photo not in seen_photos:
                    photo_url = ex_photo
                    seen_photos.add(photo_url)
                if existing.get("description"):
                    description = existing.get("description")
                if existing.get("wiki_url"):
                    wiki_url = existing.get("wiki_url")

            # 2. Nếu chưa có ảnh và không phải khách sạn, fetch từ Wikipedia (REST -> images -> search)
            if not photo_url and category != "HOTEL":
                # Thử qua REST Summary với wiki_title
                summary = fetcher.fetch_summary_rest(wiki_title)
                if summary:
                    thumb = summary.get("thumbnail_url")
                    if thumb and not is_blacklisted_photo(thumb) and thumb not in seen_photos:
                        photo_url = thumb
                        seen_photos.add(photo_url)
                    
                    if not description and summary.get("extract"):
                        description = summary.get("extract")[:400]
                    if summary.get("wiki_url"):
                        wiki_url = summary.get("wiki_url")

                # Nếu thumbnail chính không có hoặc bị blacklist, quét prop=images của wiki_title
                if not photo_url:
                    candidate_imgs = fetcher.fetch_authentic_images_for_page(wiki_title)
                    for c_img in candidate_imgs:
                        if c_img not in seen_photos and not is_blacklisted_photo(c_img):
                            photo_url = c_img
                            seen_photos.add(photo_url)
                            break

                # Nếu vẫn chưa có ảnh, tìm kiếm qua Wikipedia Search API bằng tên địa danh
                if not photo_url:
                    search_titles = fetcher.search_wiki(name, limit=3)
                    for st in search_titles:
                        s2 = fetcher.fetch_summary_rest(st)
                        if s2:
                            t2 = s2.get("thumbnail_url")
                            if t2 and not is_blacklisted_photo(t2) and t2 not in seen_photos:
                                photo_url = t2
                                seen_photos.add(photo_url)
                                wiki_title = st
                                wiki_url = s2.get("wiki_url") or f"https://vi.wikipedia.org/wiki/{urllib.parse.quote(st.replace(' ', '_'))}"
                                if not description and s2.get("extract"):
                                    description = s2.get("extract")[:400]
                                break
                            
                            # Thử bốc ảnh từ prop=images của search title
                            c_imgs = fetcher.fetch_authentic_images_for_page(st)
                            for ci in c_imgs:
                                if ci not in seen_photos and not is_blacklisted_photo(ci):
                                    photo_url = ci
                                    seen_photos.add(photo_url)
                                    wiki_title = st
                                    wiki_url = f"https://vi.wikipedia.org/wiki/{urllib.parse.quote(st.replace(' ', '_'))}"
                                    break
                            if photo_url:
                                break

            # Áp dụng quy tắc pacing & pricing fallback
            fb = FALLBACK_RULES.get(category, {"typical_time_spent": "60 phút", "price_range": "Miễn phí / Tự do"})
            typical_time_spent = fb.get("typical_time_spent", "60 phút")
            price_range = fb.get("price_range", "Miễn phí / Tự do")

            photo_source = "Wikipedia / Wikimedia Commons" if photo_url else "Chờ cập nhật xác thực"

            record = {
                "id": base_id,
                "name": name,
                "category": category,
                "is_must_visit": is_must_visit,
                "badge_label": badge_label,
                "original_province": prov,
                "region": region,
                "target_province_code": target_code,
                "target_province_name": target_name,
                "target_ward_code": None,
                "target_ward_name": "",
                "lat": round(float(lat), 6),
                "lng": round(float(lng), 6),
                "typical_time_spent": typical_time_spent,
                "price_range": price_range,
                "photo_url": photo_url,
                "photo_source": photo_source,
                "wiki_title": wiki_title,
                "wiki_url": wiki_url,
                "description": description
            }

            norm_record = normalize_place_record(record)
            all_harvested_records.append(norm_record)

    # Lọc lại toàn bộ qua HarvestPipeline để đảm bảo GPS ranh giới và deduplicate
    print(f"\n[*] Tổng số địa danh đã tổng hợp: {len(all_harvested_records)}")
    print("[*] Đang chạy kiểm toán GPS ranh giới và khử trùng lặp qua HarvestPipeline...")

    cleaned_places, stats = pipeline.clean_dataset(
        all_harvested_records,
        prune_foreign=True,
        prune_leakage=False,
        sanitize_photos=True,
        normalize_schema=True
    )

    print(f"  + Số lượng sau làm sạch: {len(cleaned_places)}")
    print(f"  + Địa danh ngoại quốc bị loại bỏ: {stats['foreign_pruned']}")
    print(f"  + Thống kê ảnh: {stats['photo_stats']}")

    # Kiểm tra tỷ lệ ảnh thực tế
    total_count = len(cleaned_places)
    photos_count = sum(1 for p in cleaned_places if p.get("photo_url"))
    photo_ratio = photos_count / total_count if total_count else 0
    print(f"  + Tổng số ảnh thực tế: {photos_count}/{total_count} ({photo_ratio * 100:.2f}%)")

    # Kiểm tra độ phủ 19 tỉnh thành và 6 categories
    prov_counter = Counter(p["original_province"] for p in cleaned_places)
    cat_by_prov = defaultdict(set)
    for p in cleaned_places:
        cat_by_prov[p["original_province"]].add(p["category"])

    required_cats = {"HISTORICAL_SITE", "TEMPLE", "ATTRACTION", "HOTEL", "MARKET", "SPECIALTY_FOOD"}
    all_passed = True

    print("\n" + "=" * 70)
    print("KIỂM TOÁN ĐỘ PHỦ 19 TỈNH THÀNH:")
    print("=" * 70)
    for prov in CENTRAL_PROVINCES:
        count = prov_counter.get(prov, 0)
        cats = cat_by_prov.get(prov, set())
        missing_c = required_cats - cats
        prov_photos = sum(1 for p in cleaned_places if p["original_province"] == prov and p.get("photo_url"))
        status = "PASSED" if count >= 15 and not missing_c else "FAILED"
        if status == "FAILED":
            all_passed = False
        print(f"  {prov:18}: {count:2} places | {prov_photos:2} photos | missing: {list(missing_c)} -> [{status}]")

    print(f"\nTrạng thái thẩm định độ phủ: {'HOÀN HẢO (100% PASS)' if all_passed else 'CẦN ĐIỀU CHỈNH'}")

    # Ghi file output data/places_central.json
    output_path = os.path.join(ROOT_DIR, "data", "places_central.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(cleaned_places, f, ensure_ascii=False, indent=2)

    print(f"\n[SUCCESS] Đã lưu thành công bộ dữ liệu vào: {output_path}")
    print(f"File size: {os.path.getsize(output_path)} bytes")

if __name__ == "__main__":
    main()
