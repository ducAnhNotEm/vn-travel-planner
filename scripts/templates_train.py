"""
scripts/templates_train.py
Bộ khuôn mẫu câu (Templates) dành riêng cho tập TRAIN.
Tuân thủ Annotation Spec v5.2 và nguyên tắc phân tách độc lập (Zero-leakage).
"""

from typing import List, Dict, Any

# Các template cho Intent: plan_itinerary
TRAIN_PLAN_TEMPLATES = [
    # Nhóm 1: Cơ bản và có điểm xuất phát rõ ràng
    {
        "id": "train_plan_01",
        "pattern": "Lên kế hoạch du lịch {dest_mention} trong {duration_days} ngày từ {origin_mention} cho đoàn {group_size} người",
        "slots": ["dest_mention", "duration_days", "origin_mention", "group_size"],
        "kind": "province",
    },
    {
        "id": "train_plan_02",
        "pattern": "Nhờ bạn xếp lịch trình đi {dest_mention} {duration_days} ngày 2 đêm khởi hành từ {origin_mention}",
        "slots": ["dest_mention", "duration_days", "origin_mention"],
        "kind": "province",
    },
    {
        "id": "train_plan_03",
        "pattern": "Lập tour tham quan {dest_mention} {duration_days} hôm từ {origin_mention} cho {group_size} người {vehicle_phrase}",
        "slots": ["dest_mention", "duration_days", "origin_mention", "group_size", "vehicle_type"],
        "kind": "attraction",
    },
    {
        "id": "train_plan_04",
        "pattern": "Sắp xếp chuyến đi {dest_mention} trong {duration_days} ngày xuất phát từ {origin_mention} với {budget_phrase}",
        "slots": ["dest_mention", "duration_days", "origin_mention", "budget_total_vnd"],
        "kind": "province",
    },
    {
        "id": "train_plan_05",
        "pattern": "Mình muốn đi chơi ở {dest_mention} {duration_days} ngày từ {origin_mention}, nhóm {group_size} bạn trẻ, {pref_phrase}",
        "slots": ["dest_mention", "duration_days", "origin_mention", "group_size", "preferences"],
        "kind": "province",
    },
    {
        "id": "train_plan_06",
        "pattern": "Lên lịch trình viếng thăm {dest_mention} {duration_days} hôm khởi hành từ {origin_mention}, đoàn {group_size} người",
        "slots": ["dest_mention", "duration_days", "origin_mention", "group_size"],
        "kind": "attraction",
    },
    # Nhóm 2: Có loại trừ POI hoặc hoạt động
    {
        "id": "train_plan_07",
        "pattern": "Gợi ý tour đi {dest_mention} {duration_days} ngày từ {origin_mention}, trừ {excl_mention} ra nhé",
        "slots": ["dest_mention", "duration_days", "origin_mention", "excluded_mentions"],
        "kind": "province",
    },
    {
        "id": "train_plan_08",
        "pattern": "Tổ chức chuyến du lịch {dest_mention} trong {duration_days} hôm từ {origin_mention} cho {group_size} người, né {excl_mention}",
        "slots": ["dest_mention", "duration_days", "origin_mention", "group_size", "excluded_mentions"],
        "kind": "province",
    },
    {
        "id": "train_plan_09",
        "pattern": "Đi {dest_mention} {duration_days} ngày xuất phát từ {origin_mention}, lưu ý không {excl_activity}",
        "slots": ["dest_mention", "duration_days", "origin_mention", "excluded_activities"],
        "kind": "province",
    },
    {
        "id": "train_plan_10",
        "pattern": "Lên tour khám phá {dest_mention} {duration_days} ngày từ {origin_mention} cho {group_size} người, bỏ qua {excl_mention} và không {excl_activity}",
        "slots": ["dest_mention", "duration_days", "origin_mention", "group_size", "excluded_mentions", "excluded_activities"],
        "kind": "province",
    },
    # Nhóm 3: Có ghim POI bắt buộc
    {
        "id": "train_plan_11",
        "pattern": "Lên lịch trình đi {dest_mention} {duration_days} ngày từ {origin_mention}, nhất định phải ghé {pin_mention}",
        "slots": ["dest_mention", "duration_days", "origin_mention", "pinned_mentions"],
        "kind": "province",
    },
    {
        "id": "train_plan_12",
        "pattern": "Bố trí chuyến đi {dest_mention} {duration_days} hôm từ {origin_mention} cho đoàn {group_size} người, ghé thăm {pin_mention}",
        "slots": ["dest_mention", "duration_days", "origin_mention", "group_size", "pinned_mentions"],
        "kind": "province",
    },
    # Nhóm 4: CURRENT_LOCATION
    {
        "id": "train_plan_13",
        "pattern": "Lên kế hoạch đi {dest_mention} {duration_days} ngày từ đây cho {group_size} người",
        "slots": ["dest_mention", "duration_days", "origin_mention", "group_size"],
        "kind": "province",
        "origin_current": True,
    },
    {
        "id": "train_plan_14",
        "pattern": "Xuất phát từ vị trí hiện tại đi {dest_mention} trong {duration_days} hôm với {budget_phrase}",
        "slots": ["dest_mention", "duration_days", "origin_mention", "budget_total_vnd"],
        "kind": "province",
        "origin_current": True,
    },
    # Nhóm 5: Không có điểm xuất phát (slot trống có chủ ý)
    {
        "id": "train_plan_15",
        "pattern": "Gợi ý lịch trình du lịch {dest_mention} trong {duration_days} ngày cho {group_size} người",
        "slots": ["dest_mention", "duration_days", "group_size"],
        "kind": "province",
    },
    {
        "id": "train_plan_16",
        "pattern": "Lập tour khám phá {dest_mention} trọn gói {duration_days} hôm với {budget_phrase}",
        "slots": ["dest_mention", "duration_days", "budget_total_vnd"],
        "kind": "province",
    },
    {
        "id": "train_plan_17",
        "pattern": "Mình cần lịch trình đi {dest_mention} {duration_days} ngày, {pref_phrase}",
        "slots": ["dest_mention", "duration_days", "preferences"],
        "kind": "province",
    },
    # Nhóm 6: Đi theo Vùng miền / Địa hình (Không có destination_mention cụ thể)
    {
        "id": "train_plan_18",
        "pattern": "Tư vấn lịch trình đi {region_phrase} {duration_days} ngày từ {origin_mention} cho {group_size} người",
        "slots": ["destination_regions", "duration_days", "origin_mention", "group_size"],
        "kind": "region",
    },
    {
        "id": "train_plan_19",
        "pattern": "Lên tour du lịch {terrain_phrase} {duration_days} hôm từ {origin_mention} với {budget_phrase}",
        "slots": ["terrain_types", "duration_days", "origin_mention", "budget_total_vnd"],
        "kind": "terrain",
    },
    {
        "id": "train_plan_20",
        "pattern": "Lập kế hoạch đi chơi {region_phrase} kết hợp {terrain_phrase} {duration_days} ngày từ {origin_mention}",
        "slots": ["destination_regions", "terrain_types", "duration_days", "origin_mention"],
        "kind": "region_terrain",
    },
    # Nhóm 7: Không đi máy bay (prefer_flight = False)
    {
        "id": "train_plan_21",
        "pattern": "Đi {dest_mention} {duration_days} ngày từ {origin_mention}, lưu ý không đi máy bay",
        "slots": ["dest_mention", "duration_days", "origin_mention", "prefer_flight"],
        "kind": "province",
        "flight_flag": False,
    },
    {
        "id": "train_plan_22",
        "pattern": "Lập tour đi {dest_mention} {duration_days} hôm xuất phát từ {origin_mention} cho {group_size} người, né máy bay giúp mình",
        "slots": ["dest_mention", "duration_days", "origin_mention", "group_size", "prefer_flight"],
        "kind": "province",
        "flight_flag": False,
    },
]

# Các template cho Intent: search_place
TRAIN_SEARCH_TEMPLATES = [
    {
        "id": "train_search_01",
        "pattern": "Tìm khách sạn tốt ở {dest_mention} giá hợp lý",
        "slots": ["dest_mention"],
        "kind": "province",
    },
    {
        "id": "train_search_02",
        "pattern": "Gợi ý vài quán ăn ngon ở {dest_mention} chuyên món đặc sản",
        "slots": ["dest_mention"],
        "kind": "province",
    },
    {
        "id": "train_search_03",
        "pattern": "Tìm homestay tại {dest_mention} có view đẹp ngắm mây",
        "slots": ["dest_mention", "preferences"],
        "kind": "province",
    },
    {
        "id": "train_search_04",
        "pattern": "Quanh khu vực {dest_mention} có điểm check-in nào nổi tiếng không?",
        "slots": ["dest_mention"],
        "kind": "attraction",
    },
    {
        "id": "train_search_05",
        "pattern": "Tìm quán cà phê chill ở {dest_mention} thích hợp làm việc",
        "slots": ["dest_mention", "preferences"],
        "kind": "province",
    },
    {
        "id": "train_search_06",
        "pattern": "Cho mình danh sách các nhà hàng hải sản tươi sống ở {dest_mention}",
        "slots": ["dest_mention"],
        "kind": "province",
    },
    {
        "id": "train_search_07",
        "pattern": "Tìm điểm tham quan di tích lịch sử tại {dest_mention}",
        "slots": ["dest_mention"],
        "kind": "province",
    },
    {
        "id": "train_search_08",
        "pattern": "Có resort cao cấp nào ở {dest_mention} có hồ bơi vô cực không?",
        "slots": ["dest_mention", "preferences"],
        "kind": "province",
    },
    {
        "id": "train_search_09",
        "pattern": "Tìm chỗ nghỉ ngơi gần {dest_mention} thuận tiện đi lại",
        "slots": ["dest_mention"],
        "kind": "attraction",
    },
    {
        "id": "train_search_10",
        "pattern": "Gợi ý quán ăn đêm tại {dest_mention} phục vụ đến khuya",
        "slots": ["dest_mention", "preferences"],
        "kind": "province",
    },
]

# Các template cho Intent: ask_advisory
TRAIN_ADVISORY_TEMPLATES = [
    {
        "id": "train_advisory_01",
        "pattern": "Đi du lịch {dest_mention} mùa nào trong năm là đẹp nhất?",
        "slots": ["dest_mention"],
        "kind": "province",
    },
    {
        "id": "train_advisory_02",
        "pattern": "Thời tiết ở {dest_mention} đợt này có thích hợp đi biển không?",
        "slots": ["dest_mention"],
        "kind": "province",
    },
    {
        "id": "train_advisory_03",
        "pattern": "Đến tham quan {dest_mention} cần lưu ý trang phục gì khi vào viếng?",
        "slots": ["dest_mention"],
        "kind": "attraction",
    },
    {
        "id": "train_advisory_04",
        "pattern": "Kinh nghiệm du lịch {dest_mention} tự túc tiết kiệm chi phí",
        "slots": ["dest_mention"],
        "kind": "province",
    },
    {
        "id": "train_advisory_05",
        "pattern": "Nên mang những đồ dùng gì khi đi phượt {dest_mention} vào mùa lạnh?",
        "slots": ["dest_mention"],
        "kind": "province",
    },
    {
        "id": "train_advisory_06",
        "pattern": "Đặc sản ẩm thực làm quà nổi tiếng ở {dest_mention} gồm những món nào?",
        "slots": ["dest_mention"],
        "kind": "province",
    },
    {
        "id": "train_advisory_07",
        "pattern": "Thời điểm lý tưởng để săn hoa tam giác mạch tại {dest_mention} là tháng mấy?",
        "slots": ["dest_mention"],
        "kind": "province",
    },
    {
        "id": "train_advisory_08",
        "pattern": "Đường đi lên {dest_mention} bằng xe máy có nguy hiểm hay khó đi không?",
        "slots": ["dest_mention"],
        "kind": "attraction",
    },
]

# Các template cho Intent: clarify_needed (Không có destination_mention và duration_days)
TRAIN_CLARIFY_TEMPLATES = [
    {
        "id": "train_clarify_01",
        "pattern": "Mình muốn đi chơi cuối tuần này nhưng chưa biết nên chọn địa điểm nào",
        "slots": [],
    },
    {
        "id": "train_clarify_02",
        "pattern": "Cả nhóm đang phân vân không biết nên đi đâu vừa vui vừa mát mẻ",
        "slots": [],
    },
    {
        "id": "train_clarify_03",
        "pattern": "Tư vấn giúp mình chuyến du lịch nghỉ dưỡng gia đình mà chưa chọn được điểm đến",
        "slots": [],
    },
    {
        "id": "train_clarify_04",
        "pattern": "Đang muốn đổi gió xả stress mà chưa có ý tưởng nên đi tỉnh nào",
        "slots": [],
    },
    {
        "id": "train_clarify_05",
        "pattern": "Có chỗ nào đi phượt cuối tuần gần thiên nhiên hoang sơ không bạn?",
        "slots": [],
    },
    {
        "id": "train_clarify_06",
        "pattern": "Mình và người yêu định đi du lịch kỷ niệm mà chưa quyết định được đi đâu",
        "slots": [],
    },
    {
        "id": "train_clarify_07",
        "pattern": "Cần tư vấn một chuyến đi giải ngố cùng bạn bè mà chưa chốt được đích đến",
        "slots": [],
    },
    {
        "id": "train_clarify_08",
        "pattern": "Hè này muốn dẫn con nhỏ đi trải nghiệm nhưng chưa biết địa phương nào phù hợp",
        "slots": [],
    },
]
