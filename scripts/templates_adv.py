"""
scripts/templates_adv.py
Bộ khuôn mẫu câu (Templates) dành riêng cho tập ADVERSARIAL & MINIMAL PAIRS.
Bao phủ 6 kiểu thử thách khó trên cả 4 intent:
1. Phủ định địa danh (excluded_mentions: trừ, né, không đi, bỏ qua, tránh, khỏi ghé, ngoại trừ)
2. Phủ định hoạt động (excluded_activities: không leo núi, né ăn hải sản, tránh đi đêm)
3. Phủ định thuộc tính (preferences: không gần biển, không quá ồn ào, không gian yên tĩnh)
4. Đảo ngữ cú pháp (đặt điểm đón origin lên đầu câu)
5. Tiếng Việt không dấu / teencode
6. Nhiều con số trong câu (ngân sách, số người, số ngày)
Cùng cơ chế Minimal Pair: ghép cặp đối lập (pinned_mentions vs excluded_mentions).
"""

from typing import List, Dict, Any

# 1. Các khuôn Minimal Pair (Cặp tối thiểu)
MINIMAL_PAIR_TEMPLATES = [
    {
        "pair_type": "pin_vs_excl",
        "pattern_pin": "Lập kế hoạch du hí {dest_mention} trong {duration_days} ngày từ {origin_mention}, nhất quyết ghé {target_poi}",
        "pattern_excl": "Lập kế hoạch du hí {dest_mention} trong {duration_days} ngày từ {origin_mention}, nhất quyết trừ {target_poi} ra",
        "kind": "province",
    },
    {
        "pair_type": "pin_vs_excl",
        "pattern_pin": "Lên tour trải nghiệm {dest_mention} {duration_days} hôm đón tại {origin_mention} cho {group_size} người, ghé thăm {target_poi}",
        "pattern_excl": "Lên tour trải nghiệm {dest_mention} {duration_days} hôm đón tại {origin_mention} cho {group_size} người, né {target_poi} giúp mình",
        "kind": "province",
    },
    {
        "pair_type": "pin_vs_excl",
        "pattern_pin": "Chuyến đi {dest_mention} {duration_days} ngày từ {origin_mention}, nhớ ghé {target_poi} nhé",
        "pattern_excl": "Chuyến đi {dest_mention} {duration_days} ngày từ {origin_mention}, bỏ qua {target_poi} nhé",
        "kind": "province",
    },
    {
        "pair_type": "pin_vs_excl",
        "pattern_pin": "Lộ trình tham quan {dest_mention} {duration_days} ngày xuất phát từ {origin_mention}, chọn ghé {target_poi}",
        "pattern_excl": "Lộ trình tham quan {dest_mention} {duration_days} ngày xuất phát từ {origin_mention}, khỏi ghé {target_poi}",
        "kind": "province",
    },
]

# 2. Các khuôn Đảo ngữ (Inverted Syntax)
ADV_INVERTED_TEMPLATES = [
    {
        "id": "adv_inv_01",
        "intent": "plan_itinerary",
        "pattern": "Khởi hành từ {origin_mention}, đích đến là {dest_mention} trong {duration_days} ngày cho {group_size} người",
        "slots": ["origin_mention", "dest_mention", "duration_days", "group_size"],
        "kind": "province",
    },
    {
        "id": "adv_inv_02",
        "intent": "plan_itinerary",
        "pattern": "Điểm đón tại {origin_mention}, mục tiêu khám phá {dest_mention} {duration_days} hôm {vehicle_phrase}",
        "slots": ["origin_mention", "dest_mention", "duration_days", "vehicle_type"],
        "kind": "province",
    },
    {
        "id": "adv_inv_03",
        "intent": "plan_itinerary",
        "pattern": "Từ {origin_mention} lên đường ghé chơi {dest_mention} {duration_days} ngày, né {excl_mention}",
        "slots": ["origin_mention", "dest_mention", "duration_days", "excluded_mentions"],
        "kind": "province",
    },
    {
        "id": "adv_inv_04",
        "intent": "plan_itinerary",
        "pattern": "Xuất phát điểm ở {origin_mention}, tour {dest_mention} kéo dài {duration_days} ngày với {budget_phrase}",
        "slots": ["origin_mention", "dest_mention", "duration_days", "budget_total_vnd"],
        "kind": "province",
    },
]

# 3. Các khuôn Phủ định thuộc tính & Hoạt động cho search_place và ask_advisory
ADV_SEARCH_TEMPLATES = [
    {
        "id": "adv_search_01",
        "intent": "search_place",
        "pattern": "Tìm khách sạn ở {dest_mention} không gần biển",
        "slots": ["dest_mention"],
        "pref_val": "không gần biển",
        "kind": "province",
    },
    {
        "id": "adv_search_02",
        "intent": "search_place",
        "pattern": "Gợi ý quán ăn tại {dest_mention} không ăn hải sản",
        "slots": ["dest_mention"],
        "excl_act_val": "ăn hải sản",
        "kind": "province",
    },
    {
        "id": "adv_search_03",
        "intent": "search_place",
        "pattern": "Tìm điểm dừng chân ở {dest_mention} không quá ồn ào và đông đúc",
        "slots": ["dest_mention"],
        "pref_val": "không quá ồn ào",
        "kind": "province",
    },
    {
        "id": "adv_search_04",
        "intent": "search_place",
        "pattern": "Tìm quán cafe tại {dest_mention} không khói thuốc lá",
        "slots": ["dest_mention"],
        "pref_val": "không khói thuốc",
        "kind": "province",
    },
    {
        "id": "adv_search_05",
        "intent": "search_place",
        "pattern": "Quanh {dest_mention} có homestay nào giá rẻ không?",
        "slots": ["dest_mention"],
        "kind": "attraction",
    },
]

ADV_ADVISORY_TEMPLATES = [
    {
        "id": "adv_advisory_01",
        "intent": "ask_advisory",
        "pattern": "Tháng mấy nên đi {dest_mention} để tránh mùa mưa bão?",
        "slots": ["dest_mention"],
        "pref_val": "tránh mùa mưa bão",
        "kind": "province",
    },
    {
        "id": "adv_advisory_02",
        "intent": "ask_advisory",
        "pattern": "Thời điểm nào ghé {dest_mention} không bị quá lạnh và sương mù?",
        "slots": ["dest_mention"],
        "pref_val": "không quá lạnh",
        "kind": "province",
    },
    {
        "id": "adv_advisory_03",
        "intent": "ask_advisory",
        "pattern": "Đi {dest_mention} có cần đặt vé trước để không phải xếp hàng chờ đợi?",
        "slots": ["dest_mention"],
        "kind": "attraction",
    },
    {
        "id": "adv_advisory_04",
        "intent": "ask_advisory",
        "pattern": "Cung đường di chuyển đến {dest_mention} có đoạn nào đang sửa chữa cần né không?",
        "slots": ["dest_mention"],
        "kind": "province",
    },
]

# 4. Các khuôn CÓ từ phủ định nhưng KHÔNG loại trừ (Đặc biệt cho clarify_needed)
ADV_CLARIFY_TEMPLATES = [
    {
        "id": "adv_clarify_01",
        "intent": "clarify_needed",
        "pattern": "Không biết nên đi đâu chơi cho khuây khỏa dịp cuối tuần",
        "slots": [],
    },
    {
        "id": "adv_clarify_02",
        "intent": "clarify_needed",
        "pattern": "Mình chưa biết đi đâu cả, đầu óc đang bối rối quá",
        "slots": [],
    },
    {
        "id": "adv_clarify_03",
        "intent": "clarify_needed",
        "pattern": "Không có kế hoạch cụ thể nào, nhờ hệ thống gợi ý điểm du lịch hấp dẫn",
        "slots": [],
    },
    {
        "id": "adv_clarify_04",
        "intent": "clarify_needed",
        "pattern": "Cả hai vợ chồng đều không chọn được điểm đến ưng ý cho kỳ nghỉ này",
        "slots": [],
    },
    {
        "id": "adv_clarify_05",
        "intent": "clarify_needed",
        "pattern": "Không rõ tầm này thì nên đi du lịch hướng biển hay hướng núi thì hợp hơn?",
        "slots": [],
    },
    {
        "id": "adv_clarify_06",
        "intent": "clarify_needed",
        "pattern": "Chưa từng đi du lịch bao giờ nên không biết bắt đầu từ địa phương nào",
        "slots": [],
    },
]

# 5. Các khuôn Tiếng Việt không dấu / Teencode
ADV_UNACCENTED_TEMPLATES = [
    {
        "id": "adv_unacc_01",
        "intent": "plan_itinerary",
        "pattern": "Lich trinh di {dest_mention} {duration_days} ngay tu {origin_mention} cho {group_size} nguoi",
        "slots": ["dest_mention", "duration_days", "origin_mention", "group_size"],
        "kind": "province",
        "unaccented": True,
    },
    {
        "id": "adv_unacc_02",
        "intent": "plan_itinerary",
        "pattern": "Tu {origin_mention} di {dest_mention} {duration_days} hom {vehicle_phrase}, khong di {excl_mention}",
        "slots": ["origin_mention", "dest_mention", "duration_days", "vehicle_type", "excluded_mentions"],
        "kind": "province",
        "unaccented": True,
    },
    {
        "id": "adv_unacc_03",
        "intent": "search_place",
        "pattern": "Tim khach san tot o {dest_mention} gia re",
        "slots": ["dest_mention"],
        "kind": "province",
        "unaccented": True,
    },
    {
        "id": "adv_unacc_04",
        "intent": "ask_advisory",
        "pattern": "Di {dest_mention} mua nao dep nhat trong nam?",
        "slots": ["dest_mention"],
        "kind": "province",
        "unaccented": True,
    },
    {
        "id": "adv_unacc_05",
        "intent": "clarify_needed",
        "pattern": "Minh chua biet nen di dau choi cuoi tuan nay",
        "slots": [],
        "unaccented": True,
    },
]
