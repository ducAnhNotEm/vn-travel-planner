"""
scripts/templates_val.py
Bộ khuôn mẫu câu (Templates) dành riêng cho tập VALIDATION (Hold-out).
Được thiết kế hoàn toàn khác biệt về cấu trúc ngữ pháp và từ vựng so với Train.
Zero-leakage: Đảm bảo độ trùng lặp cú pháp (delexicalized overlap) < 1%.
"""

from typing import List, Dict, Any

VAL_PLAN_TEMPLATES = [
    {
        "id": "val_plan_01",
        "pattern": "Cần gợi ý lịch trình vi vu {dest_mention} khoảng {duration_days} ngày từ {origin_mention} cho nhóm bạn {group_size} người",
        "slots": ["dest_mention", "duration_days", "origin_mention", "group_size"],
        "kind": "province",
    },
    {
        "id": "val_plan_02",
        "pattern": "Phác thảo tour trải nghiệm {dest_mention} trong {duration_days} hôm khởi hành từ {origin_mention} cho {group_size} khách",
        "slots": ["dest_mention", "duration_days", "origin_mention", "group_size"],
        "kind": "province",
    },
    {
        "id": "val_plan_03",
        "pattern": "Hỗ trợ lên kế hoạch khám phá vùng đất {dest_mention} {duration_days} ngày khởi hành từ {origin_mention} {vehicle_phrase}",
        "slots": ["dest_mention", "duration_days", "origin_mention", "vehicle_type"],
        "kind": "province",
    },
    {
        "id": "val_plan_04",
        "pattern": "Thiết kế tour khám phá {dest_mention} {duration_days} ngày với điểm đón từ {origin_mention}, dự trù {budget_phrase}",
        "slots": ["dest_mention", "duration_days", "origin_mention", "budget_total_vnd"],
        "kind": "province",
    },
    {
        "id": "val_plan_05",
        "pattern": "Cho mình xin gợi ý chuyến thưởng ngoạn {dest_mention} {duration_days} hôm xuất phát từ {origin_mention}, {pref_phrase}",
        "slots": ["dest_mention", "duration_days", "origin_mention", "preferences"],
        "kind": "attraction",
    },
    {
        "id": "val_plan_06",
        "pattern": "Xây dựng lộ trình trải nghiệm văn hóa {dest_mention} {duration_days} ngày từ {origin_mention}, lưu ý né {excl_mention}",
        "slots": ["dest_mention", "duration_days", "origin_mention", "excluded_mentions"],
        "kind": "province",
    },
    {
        "id": "val_plan_07",
        "pattern": "Hành trình vi vu {dest_mention} {duration_days} hôm đi từ {origin_mention} cho {group_size} người, tránh {excl_mention} và không {excl_activity}",
        "slots": ["dest_mention", "duration_days", "origin_mention", "group_size", "excluded_mentions", "excluded_activities"],
        "kind": "province",
    },
    {
        "id": "val_plan_08",
        "pattern": "Lên lộ trình ghé thăm danh thắng {dest_mention} {duration_days} ngày từ {origin_mention}, ưu tiên ghé {pin_mention}",
        "slots": ["dest_mention", "duration_days", "origin_mention", "pinned_mentions"],
        "kind": "attraction",
    },
    {
        "id": "val_plan_09",
        "pattern": "Xin lịch trình khám phá thiên nhiên {dest_mention} {duration_days} hôm từ đây cho đoàn {group_size} người",
        "slots": ["dest_mention", "duration_days", "origin_mention", "group_size"],
        "kind": "province",
        "origin_current": True,
    },
    {
        "id": "val_plan_10",
        "pattern": "Khởi hành ngay tại vị trí hiện tại đi {dest_mention} trong {duration_days} ngày với {budget_phrase}",
        "slots": ["dest_mention", "duration_days", "origin_mention", "budget_total_vnd"],
        "kind": "province",
        "origin_current": True,
    },
    {
        "id": "val_plan_11",
        "pattern": "Tư vấn chuyến đi thư giãn ở {dest_mention} thời lượng {duration_days} ngày dành cho {group_size} bạn",
        "slots": ["dest_mention", "duration_days", "group_size"],
        "kind": "province",
    },
    {
        "id": "val_plan_12",
        "pattern": "Cho mình kế hoạch du ngoạn {dest_mention} {duration_days} hôm với khoản tiền {budget_phrase}",
        "slots": ["dest_mention", "duration_days", "budget_total_vnd"],
        "kind": "province",
    },
    {
        "id": "val_plan_13",
        "pattern": "Định hướng cung đường du lịch {region_phrase} {duration_days} ngày xuất phát từ {origin_mention} cho {group_size} người",
        "slots": ["destination_regions", "duration_days", "origin_mention", "group_size"],
        "kind": "region",
    },
    {
        "id": "val_plan_14",
        "pattern": "Tìm kiếm hành trình vượt cảnh quan {terrain_phrase} {duration_days} hôm từ {origin_mention} với {budget_phrase}",
        "slots": ["terrain_types", "duration_days", "origin_mention", "budget_total_vnd"],
        "kind": "terrain",
    },
    {
        "id": "val_plan_15",
        "pattern": "Thiết lập tour nghỉ dưỡng {dest_mention} {duration_days} ngày từ {origin_mention}, khách dặn không đi máy bay",
        "slots": ["dest_mention", "duration_days", "origin_mention", "prefer_flight"],
        "kind": "province",
        "flight_flag": False,
    },
    {
        "id": "val_plan_16",
        "pattern": "Chuyến đi {dest_mention} khoảng {duration_days} hôm từ {origin_mention} cho {group_size} người, né hoàn toàn máy bay",
        "slots": ["dest_mention", "duration_days", "origin_mention", "group_size", "prefer_flight"],
        "kind": "province",
        "flight_flag": False,
    },
]

VAL_SEARCH_TEMPLATES = [
    {
        "id": "val_search_01",
        "pattern": "Điểm danh khách sạn view xịn ở {dest_mention} được đánh giá cao",
        "slots": ["dest_mention"],
        "kind": "province",
    },
    {
        "id": "val_search_02",
        "pattern": "Xin địa chỉ các quán ngon đặc sắc tại {dest_mention} chuyên món ẩm thực địa phương",
        "slots": ["dest_mention"],
        "kind": "province",
    },
    {
        "id": "val_search_03",
        "pattern": "Cần tìm điểm dừng chân nghỉ dưỡng tại {dest_mention} không gian yên tĩnh",
        "slots": ["dest_mention", "preferences"],
        "kind": "province",
    },
    {
        "id": "val_search_04",
        "pattern": "Gợi ý tọa độ sống ảo không thể bỏ lỡ ở {dest_mention} cho giới trẻ",
        "slots": ["dest_mention"],
        "kind": "attraction",
    },
    {
        "id": "val_search_05",
        "pattern": "Tra cứu dịch vụ ăn uống chuẩn vị bản địa tại {dest_mention} cho gia đình",
        "slots": ["dest_mention"],
        "kind": "province",
    },
    {
        "id": "val_search_06",
        "pattern": "Có homestay xinh xắn nào tại {dest_mention} gần gũi thiên nhiên không?",
        "slots": ["dest_mention", "preferences"],
        "kind": "province",
    },
    {
        "id": "val_search_07",
        "pattern": "Tìm điểm tham quan di sản nổi bật nhất của {dest_mention}",
        "slots": ["dest_mention"],
        "kind": "province",
    },
]

VAL_ADVISORY_TEMPLATES = [
    {
        "id": "val_advisory_01",
        "pattern": "Cho mình hỏi đi {dest_mention} vào khoảng tháng nào thì cảnh sắc thơ mộng nhất?",
        "slots": ["dest_mention"],
        "kind": "province",
    },
    {
        "id": "val_advisory_02",
        "pattern": "Mẹo di chuyển và lưu ý an toàn khi tham quan {dest_mention} cho người mới?",
        "slots": ["dest_mention"],
        "kind": "province",
    },
    {
        "id": "val_advisory_03",
        "pattern": "Nên dành bao nhiêu thời gian để khám phá trọn vẹn vẻ đẹp của {dest_mention}?",
        "slots": ["dest_mention"],
        "kind": "attraction",
    },
    {
        "id": "val_advisory_04",
        "pattern": "Phương tiện nào di chuyển tiện nhất khi ghé thăm {dest_mention} tự túc?",
        "slots": ["dest_mention"],
        "kind": "province",
    },
    {
        "id": "val_advisory_05",
        "pattern": "Đến {dest_mention} vào mùa mưa thì có những hoạt động trong nhà nào hấp dẫn?",
        "slots": ["dest_mention", "preferences"],
        "kind": "province",
    },
]

VAL_CLARIFY_TEMPLATES = [
    {
        "id": "val_clarify_01",
        "pattern": "Tụi mình đang phân vân không biết nên chọn địa điểm du lịch nào sắp tới",
        "slots": [],
    },
    {
        "id": "val_clarify_02",
        "pattern": "Muốn làm một chuyến xả hơi cùng hội bạn mà chưa biết nên đi hướng nào",
        "slots": [],
    },
    {
        "id": "val_clarify_03",
        "pattern": "Chưa có dự định cụ thể nào, nhờ hệ thống gợi ý điểm du lịch hấp dẫn",
        "slots": [],
    },
    {
        "id": "val_clarify_04",
        "pattern": "Đang tìm kiếm cảm hứng cho kỳ nghỉ sắp tới mà đầu óc trống rỗng",
        "slots": [],
    },
    {
        "id": "val_clarify_05",
        "pattern": "Phân vân giữa các địa điểm du lịch, chưa biết chọn nơi nào cho phù hợp",
        "slots": [],
    },
]
