"""
scripts/compose.py
═══════════════════════════════════════════════════════════════════════════════
Module sinh tổ hợp cú pháp (Combinatorial Syntax Composition Engine)
cho bộ khuôn mẫu câu NLU Travel AI Việt Nam theo Annotation Spec v5.2.

Chức năng:
1. Định nghĩa các thành phần cú pháp độc lập (Openers, Slot Clauses, Connectors).
2. Tách biệt từ vựng giữa Train, Val và Adv để triệt tiêu rò rỉ (Trigram Jaccard < 0.35).
3. Đa dạng hóa hoán vị thứ tự slot (Origin-first, Group-first, Duration-first) cho Val/Adv
   nhằm đảm bảo tỷ lệ trùng lặp chu kỳ slot (Slot Order Duplicate Rate) < 40% (mục tiêu 15-25%).
4. Đảm bảo mật độ dòng/khuôn của Train <= 30 (với >= 100 khuôn/intent, >= 400 khuôn tổng cộng).
═══════════════════════════════════════════════════════════════════════════════
"""

from typing import List, Dict, Any, Tuple
import re

# ---------------------------------------------------------------------------
# 1. THÀNH PHẦN MỞ ĐẦU CÂU (SENTENCE OPENERS) - TÁCH BIỆT TỪ VỰNG THEO SPLIT
# ---------------------------------------------------------------------------

# Train Openers: Trang trọng, phổ biến, yêu cầu lịch sự
TRAIN_PLAN_OPENERS = [
    "Lên kế hoạch",
    "Nhờ bạn xếp lịch trình",
    "Lập tour",
    "Sắp xếp chuyến đi",
    "Bố trí hành trình",
    "Thiết kế chuyến du lịch",
    "Chuẩn bị kế hoạch",
    "Gợi ý lịch trình",
    "Tổ chức chuyến du lịch",
    "Tư vấn tour",
    "Tạo lịch trình",
    "Xây dựng kế hoạch",
    "Lập kế hoạch du lịch",
    "Nhờ bạn lên kế hoạch",
    "Giúp mình sắp xếp chuyến đi",
    "Tư vấn giúp mình lịch trình",
    "Lên lịch trình",
    "Tổ chức tour",
    "Cần kế hoạch",
    "Mình muốn sắp xếp chuyến đi",
]

# Val Openers: Văn phong trải nghiệm, thưởng ngoạn, phong phú (Khác Train)
VAL_PLAN_OPENERS = [
    "Phác thảo tour trải nghiệm",
    "Định hướng cung đường",
    "Thiết kế chuyến thưởng ngoạn",
    "Xin gợi ý hành trình vi vu",
    "Xây dựng lộ trình trải nghiệm",
    "Hỗ trợ phác thảo chuyến tham quan",
    "Tư vấn cung đường dạo chơi",
    "Thiết lập tour kỳ nghỉ",
    "Lên sơ đồ chuyến du ngoạn",
    "Khảo sát cung đường thưởng lãm",
    "Vạch kế hoạch chuyến ngao du",
    "Gợi ý lịch trình dạo quanh",
]

# Adv Openers: Đảo ngữ, khẩu ngữ, nhấn mạnh đích đến
ADV_PLAN_OPENERS = [
    "Mục tiêu là ghé",
    "Đích đến là",
    "Chuyến du hí",
    "Kế hoạch phượt bụi",
    "Hành trình khám phá ngược dòng",
    "Thẳng tiến tới",
    "Hành trình đặt chân đến",
]

# ---------------------------------------------------------------------------
# 2. MỆNH ĐỀ THAM SỐ (SLOT CLAUSES)
# ---------------------------------------------------------------------------

# Điểm đến (Destination)
DEST_CLAUSES = [
    ("đi {dest_mention}", ["dest_mention"]),
    ("tới {dest_mention}", ["dest_mention"]),
    ("đến {dest_mention}", ["dest_mention"]),
    ("khám phá {dest_mention}", ["dest_mention"]),
    ("du lịch {dest_mention}", ["dest_mention"]),
    ("thăm quan {dest_mention}", ["dest_mention"]),
    ("ghé thăm {dest_mention}", ["dest_mention"]),
    ("vi vu {dest_mention}", ["dest_mention"]),
    ("nghỉ dưỡng ở {dest_mention}", ["dest_mention"]),
    ("dạo chơi {dest_mention}", ["dest_mention"]),
]

# Thời lượng (Duration)
DURATION_CLAUSES = [
    ("trong {duration_days} ngày", ["duration_days"], {}),
    ("{duration_days} ngày", ["duration_days"], {}),
    ("kéo dài {duration_days} ngày", ["duration_days"], {}),
    ("{duration_days} hôm", ["duration_days"], {}),
    ("thời lượng {duration_days} ngày", ["duration_days"], {}),
    ("khoảng {duration_days} hôm", ["duration_days"], {}),
    ("{duration_days} ngày {nights} đêm", ["duration_days"], {"min_days": 2}),
    ("{duration_days} hôm {nights} đêm", ["duration_days"], {"min_days": 2}),
]

# Điểm xuất phát (Origin)
ORIGIN_CLAUSES = [
    ("từ {origin_mention}", ["origin_mention"]),
    ("khởi hành từ {origin_mention}", ["origin_mention"]),
    ("xuất phát từ {origin_mention}", ["origin_mention"]),
    ("điểm đón tại {origin_mention}", ["origin_mention"]),
    ("bắt đầu ở {origin_mention}", ["origin_mention"]),
    ("đi từ {origin_mention}", ["origin_mention"]),
]

# Số lượng thành viên (Group size)
GROUP_CLAUSES = [
    ("cho {group_size} người", ["group_size"]),
    ("cho đoàn {group_size} người", ["group_size"]),
    ("nhóm {group_size} bạn", ["group_size"]),
    ("đoàn {group_size} khách", ["group_size"]),
    ("cho {group_size} thành viên", ["group_size"]),
    ("nhóm bạn {group_size} người", ["group_size"]),
]

# Phương tiện (Vehicle)
VEHICLE_CLAUSES = [
    ("{vehicle_phrase}", ["vehicle_type"]),
    ("bằng {vehicle_phrase}", ["vehicle_type"]),
    ("đi lại {vehicle_phrase}", ["vehicle_type"]),
    ("di chuyển {vehicle_phrase}", ["vehicle_type"]),
]

# Ngân sách (Budget)
BUDGET_CLAUSES = [
    ("với {budget_phrase}", ["budget_total_vnd"]),
    ("ngân sách {budget_phrase}", ["budget_total_vnd"]),
    ("dự trù {budget_phrase}", ["budget_total_vnd"]),
    ("chi phí {budget_phrase}", ["budget_total_vnd"]),
    ("khoản tiền {budget_phrase}", ["budget_total_vnd"]),
]

# Sở thích / Thuộc tính (Preferences)
PREF_CLAUSES = [
    ("{pref_phrase}", ["preferences"]),
    ("tiêu chí {pref_phrase}", ["preferences"]),
    ("yêu cầu {pref_phrase}", ["preferences"]),
    ("ưu tiên {pref_phrase}", ["preferences"]),
]

# Loại trừ địa danh (Excluded Mentions)
EXCL_CLAUSES = [
    ("trừ {excl_mention} ra", ["excluded_mentions"]),
    ("né {excl_mention} nhé", ["excluded_mentions"]),
    ("bỏ qua {excl_mention}", ["excluded_mentions"]),
    ("không đi {excl_mention}", ["excluded_mentions"]),
    ("tránh {excl_mention} giúp mình", ["excluded_mentions"]),
]

# Ghim địa danh (Pinned Mentions)
PIN_CLAUSES = [
    ("nhất định ghé {pin_mention}", ["pinned_mentions"]),
    ("nhớ ghé {pin_mention} nhé", ["pinned_mentions"]),
    ("ghé thăm {pin_mention}", ["pinned_mentions"]),
    ("ưu tiên ghé {pin_mention}", ["pinned_mentions"]),
]

# Loại trừ hoạt động (Excluded Activities)
EXCL_ACT_CLAUSES = [
    ("không {excl_activity}", ["excluded_activities"]),
    ("lưu ý không {excl_activity}", ["excluded_activities"]),
    ("né {excl_activity} ra", ["excluded_activities"]),
    ("tránh {excl_activity}", ["excluded_activities"]),
]


# ---------------------------------------------------------------------------
# 3. HÀM TỔ HỢP CHO TẬP TRAIN (TRAIN COMPOSITION)
# ---------------------------------------------------------------------------

def compose_train_plan_templates(count_target: int = 100) -> List[Dict[str, Any]]:
    """
    Sinh các template cho train_plan_itinerary tuân thủ:
    - Cú pháp chuẩn P1: Dest -> Days [-> Nights] -> Origin [-> Extra]
    - Slots nhất quán, không có số cứng, không placeholder thiếu.
    """
    templates: List[Dict[str, Any]] = []
    idx = 100

    # Phân nhóm biến thể extra
    extra_sets = [
        # (suffix_label, clause_list)
        ("grp", GROUP_CLAUSES),
        ("veh", VEHICLE_CLAUSES),
        ("bud", BUDGET_CLAUSES),
        ("pref", PREF_CLAUSES),
        ("excl", EXCL_CLAUSES),
        ("pin", PIN_CLAUSES),
        ("exca", EXCL_ACT_CLAUSES),
        ("none", [(None, [])]),
    ]

    for opener in TRAIN_PLAN_OPENERS:
        for d_text, d_slots in DEST_CLAUSES[:6]:
            for dur_text, dur_slots, dur_extra in DURATION_CLAUSES[:6]:
                for o_text, o_slots in ORIGIN_CLAUSES[:4]:
                    for extra_name, extra_list in extra_sets:
                        ex_text, ex_slots = extra_list[idx % len(extra_list)]
                        
                        # Ghép câu
                        parts = [opener, d_text, dur_text, o_text]
                        slots = ["dest_mention"] + dur_slots + ["origin_mention"]
                        if ex_text:
                            parts.append(ex_text)
                            slots += ex_slots
                        
                        pattern = " ".join(parts)
                        t_item: Dict[str, Any] = {
                            "id": f"train_plan_c{idx:03d}",
                            "intent": "plan_itinerary",
                            "pattern": pattern,
                            "slots": list(dict.fromkeys(slots)),
                            "kind": "province",
                        }
                        if dur_extra.get("min_days"):
                            t_item["min_days"] = dur_extra["min_days"]
                        
                        templates.append(t_item)
                        idx += 1
                        if len(templates) >= count_target:
                            return templates
    return templates


def compose_train_search_templates(count_target: int = 100) -> List[Dict[str, Any]]:
    """
    Sinh các template tìm kiếm địa điểm phong phú tự nhiên cho tập TRAIN.
    Bao gồm khách sạn, nhà hàng, homestay, cafe, điểm check-in, ẩm thực đặc sản.
    """
    verbs = [
        "Tìm", "Gợi ý", "Cho mình danh sách", "Tìm kiếm", "Có",
        "Chỉ giúp mình", "Xin địa chỉ", "Gợi ý vài", "Hỏi thăm", "Cần tìm",
    ]
    targets = [
        ("khách sạn tiện nghi ở {dest_mention}", ["dest_mention"]),
        ("khách sạn giá rẻ tại {dest_mention}", ["dest_mention"]),
        ("homestay view núi tại {dest_mention}", ["dest_mention"]),
        ("homestay view biển đẹp ở {dest_mention}", ["dest_mention"]),
        ("resort cao cấp quanh {dest_mention}", ["dest_mention"]),
        ("nhà nghỉ bình dân ở {dest_mention}", ["dest_mention"]),
        ("quán ăn ngon ở {dest_mention}", ["dest_mention"]),
        ("quán ăn đặc sản tại {dest_mention}", ["dest_mention"]),
        ("nhà hàng hải sản tươi ngon ở {dest_mention}", ["dest_mention"]),
        ("quán lẩu nướng đông khách tại {dest_mention}", ["dest_mention"]),
        ("quán cafe view ngắm hoàng hôn tại {dest_mention}", ["dest_mention"]),
        ("quán cafe phong cách chill ở {dest_mention}", ["dest_mention"]),
        ("quán cafe acoustic tại {dest_mention}", ["dest_mention"]),
        ("điểm check-in chụp ảnh hot ở {dest_mention}", ["dest_mention"]),
        ("điểm tham quan ngắm cảnh tại {dest_mention}", ["dest_mention"]),
        ("khu vui chơi giải trí ở {dest_mention}", ["dest_mention"]),
        ("chợ đêm sầm uất tại {dest_mention}", ["dest_mention"]),
        ("di tích lịch sử văn hóa ở {dest_mention}", ["dest_mention"]),
        ("địa điểm cắm trại dã ngoại quanh {dest_mention}", ["dest_mention"]),
        ("quán ăn vặt nổi tiếng ở {dest_mention}", ["dest_mention"]),
    ]
    closers = [
        "",
        "giá cả phải chăng",
        "được nhiều người khen",
        "phù hợp gia đình",
        "gần trung tâm",
        "thuận tiện đi lại",
        "chất lượng phục vụ tốt",
        "không gian thoáng mát",
    ]

    templates: List[Dict[str, Any]] = []
    idx = 100
    for v in verbs:
        for t_text, t_slots in targets:
            for c in closers:
                pattern = f"{v} {t_text}"
                if c:
                    pattern += f" {c}"
                templates.append({
                    "id": f"train_search_c{idx:03d}",
                    "intent": "search_place",
                    "pattern": pattern,
                    "slots": t_slots,
                    "kind": "province",
                })
                idx += 1
                if len(templates) >= count_target:
                    return templates
    return templates


def compose_train_advisory_templates(count_target: int = 100) -> List[Dict[str, Any]]:
    """
    Sinh các câu hỏi tư vấn (ask_advisory) cho tập TRAIN về mùa, thời tiết,
    trang phục, phong tục, đặc sản, phương tiện di chuyển.
    """
    patterns_raw = [
        "Du lịch {dest_mention} vào tháng nào trong năm là thích hợp nhất?",
        "Thời tiết ở {dest_mention} mùa này có mưa nhiều không bạn?",
        "Đi tham quan {dest_mention} cần chuẩn bị trang phục gì phù hợp?",
        "Kinh nghiệm đi chơi {dest_mention} tự túc cần lưu ý những điều gì?",
        "Đến {dest_mention} thì nên mua đặc sản gì về làm quà biếu?",
        "Thời điểm nào ngắm bình minh tại {dest_mention} là lý tưởng nhất?",
        "Đường đi lên {dest_mention} bằng xe máy có dốc và nguy hiểm không?",
        "Nên đi {dest_mention} vào mùa khô hay mùa mưa thì trải nghiệm tốt hơn?",
        "Món ăn đặc sắc nhất định phải thưởng thức ở {dest_mention} là món nào?",
        "Đi du lịch {dest_mention} tự túc cần chuẩn bị những giấy tờ gì?",
        "Thời tiết ở {dest_mention} đợt này ban đêm có lạnh lắm không?",
        "Nên mang theo những vật dụng cá nhân gì khi đi dã ngoại {dest_mention}?",
        "Chi phí ăn ở tự túc tại {dest_mention} khoảng bao nhiêu tiền một người?",
        "Tháng mấy tại {dest_mention} bước vào mùa lễ hội đông vui nhất?",
        "Đến viếng các đền miếu tại {dest_mention} cần kiêng kỵ những điều gì?",
        "Cung đường chạy xe từ vùng lân cận đến {dest_mention} có dễ đi không?",
        "Nên chọn phương tiện nào để di chuyển tới {dest_mention} an toàn?",
        "Ghé thăm {dest_mention} có cần đặt phòng trước cả tháng không?",
        "Thời điểm nào ở {dest_mention} ít sương mù và trời trong xanh nhất?",
        "Các món quà bánh truyền thống nổi tiếng ở {dest_mention} gồm những gì?",
    ]
    suffixes = [
        "",
        "nhờ bạn chia sẻ kinh nghiệm",
        "tư vấn giúp mình nhé",
        "cho mình xin lời khuyên",
        "mình muốn biết trước để chuẩn bị",
        "ai từng đi rồi cho mình review với",
    ]

    templates: List[Dict[str, Any]] = []
    idx = 100
    for p in patterns_raw:
        for s in suffixes:
            full_p = p if not s else (p.rstrip("?") + f", {s}?")
            templates.append({
                "id": f"train_adv_c{idx:03d}",
                "intent": "ask_advisory",
                "pattern": full_p,
                "slots": ["dest_mention"],
                "kind": "province",
            })
            idx += 1
            if len(templates) >= count_target:
                return templates
    return templates


def compose_train_clarify_templates(count_target: int = 100) -> List[Dict[str, Any]]:
    """
    Sinh các câu hỏi chưa rõ ý (clarify_needed) cho tập TRAIN.
    TUYỆT ĐỐI không có destination_mention và không có duration_days.
    """
    openers = [
        "Mình muốn đi chơi",
        "Cả nhóm đang bàn nhau đi du lịch",
        "Gia đình muốn tổ chức một chuyến đi nghỉ dưỡng",
        "Cuối tuần này muốn xả stress",
        "Hai đứa muốn đổi gió đi chơi xa",
        "Bọn mình đang muốn tìm chỗ giải ngố",
        "Đang tính làm một chuyến dã ngoại",
        "Muốn kiếm chỗ nào thư giãn",
        "Đang phân vân tìm chuyến du lịch",
        "Cần tìm một tour ngắn ngày",
    ]
    reasons = [
        "mà chưa biết nên chọn địa điểm nào",
        "nhưng chưa chốt được đích đến cụ thể",
        "mà chưa có ý tưởng đi đâu cho vui",
        "nhưng chưa biết tỉnh nào phong cảnh đẹp",
        "mà chưa quyết định được nơi nào phù hợp",
        "nhưng chưa thống nhất được điểm đến",
        "mà chưa chọn được bãi biển hay vùng núi",
        "nhưng đang băn khoăn không biết đi đâu",
        "mà chưa biết nơi nào thời tiết đang mát mẻ",
        "nhưng chưa rõ địa phương nào thích hợp nhất",
    ]
    closers = [
        "",
        "bạn tư vấn giúp mình nhé",
        "nhờ bạn gợi ý giúp",
        "có ý tưởng nào hay không",
        "xin vài gợi ý từ bạn",
    ]

    templates: List[Dict[str, Any]] = []
    idx = 100
    for op in openers:
        for r in reasons:
            for cl in closers:
                text = f"{op} {r}"
                if cl:
                    text += f", {cl}"
                templates.append({
                    "id": f"train_clarify_c{idx:03d}",
                    "intent": "clarify_needed",
                    "pattern": text,
                    "slots": [],
                })
                idx += 1
                if len(templates) >= count_target:
                    return templates
    return templates


# ---------------------------------------------------------------------------
# 4. HÀM TỔ HỢP CHO TẬP VAL (VAL COMPOSITION) - ĐA DẠNG HÓA HOÁN VỊ
# ---------------------------------------------------------------------------

def compose_val_templates() -> Dict[str, List[Dict[str, Any]]]:
    """
    Sinh tập khuôn hold-out cho VAL với các hoán vị thứ tự slot hoàn toàn mới:
    - P2 (Origin-first): ORIG -> DEST -> DAYS [-> Extra]
    - P3 (Group-first): GRP -> ORIG -> DEST -> DAYS
    - P4 (Duration-first): DAYS -> DEST -> ORIG
    - P5 (Dest-Orig-Days): DEST -> ORIG -> DAYS
    - Multi-slot search: ('PREF', 'DEST'), ('GRP', 'DEST')
    Đảm bảo:
    - Duplicate slot signature rate với Train < 40% (mục tiêu 15-25%).
    - Delexicalized Trigram Jaccard < 0.35.
    """
    plan_templates: List[Dict[str, Any]] = [
        # P2: Origin-first (ORIG -> DEST -> DAYS ...)
        {
            "id": "val_plan_p2_01",
            "pattern": "Khởi hành từ {origin_mention}, mình muốn khám phá {dest_mention} trong {duration_days} ngày cho {group_size} người",
            "slots": ["origin_mention", "dest_mention", "duration_days", "group_size"],
            "kind": "province",
        },
        {
            "id": "val_plan_p2_02",
            "pattern": "Xuất phát tại {origin_mention}, lên tour du ngoạn {dest_mention} kéo dài {duration_days} hôm với khoản chi {budget_phrase}",
            "slots": ["origin_mention", "dest_mention", "duration_days", "budget_total_vnd"],
            "kind": "province",
        },
        {
            "id": "val_plan_p2_03",
            "pattern": "Bắt đầu từ {origin_mention}, thiết kế chuyến thăm {dest_mention} thời lượng {duration_days} ngày {vehicle_phrase}",
            "slots": ["origin_mention", "dest_mention", "duration_days", "vehicle_type"],
            "kind": "province",
        },
        {
            "id": "val_plan_p2_04",
            "pattern": "Từ {origin_mention} lên lộ trình thưởng ngoạn {dest_mention} {duration_days} hôm, {pref_phrase}",
            "slots": ["origin_mention", "dest_mention", "duration_days", "preferences"],
            "kind": "province",
        },
        {
            "id": "val_plan_p2_05",
            "pattern": "Điểm xuất phát từ {origin_mention}, vạch kế hoạch ghé {dest_mention} {duration_days} ngày, né {excl_mention}",
            "slots": ["origin_mention", "dest_mention", "duration_days", "excluded_mentions"],
            "kind": "province",
        },
        {
            "id": "val_plan_p2_06",
            "pattern": "Khởi hành ở {origin_mention}, phác thảo cung đường {dest_mention} {duration_days} hôm, ghé thăm {pin_mention}",
            "slots": ["origin_mention", "dest_mention", "duration_days", "pinned_mentions"],
            "kind": "province",
        },
        {
            "id": "val_plan_p2_07",
            "pattern": "Đi từ {origin_mention} tới danh thắng {dest_mention} trong {duration_days} ngày, không {excl_activity}",
            "slots": ["origin_mention", "dest_mention", "duration_days", "excluded_activities"],
            "kind": "province",
        },
        {
            "id": "val_plan_p2_08",
            "pattern": "Bắt đầu ở {origin_mention}, vạch tour vi vu {dest_mention} {duration_days} ngày cho {group_size} khách, né {excl_mention}",
            "slots": ["origin_mention", "dest_mention", "duration_days", "group_size", "excluded_mentions"],
            "kind": "province",
        },

        # P3: Group-first (GRP -> ORIG -> DEST -> DAYS ...)
        {
            "id": "val_plan_p3_01",
            "pattern": "Nhóm bạn {group_size} người từ {origin_mention} cần tour dạo chơi {dest_mention} trong {duration_days} ngày",
            "slots": ["group_size", "origin_mention", "dest_mention", "duration_days"],
            "kind": "province",
        },
        {
            "id": "val_plan_p3_02",
            "pattern": "Đoàn {group_size} khách khởi hành tại {origin_mention} du ngoạn vùng đất {dest_mention} {duration_days} hôm với {budget_phrase}",
            "slots": ["group_size", "origin_mention", "dest_mention", "duration_days", "budget_total_vnd"],
            "kind": "province",
        },
        {
            "id": "val_plan_p3_03",
            "pattern": "Đoàn {group_size} thành viên xuất phát từ {origin_mention} khám phá {dest_mention} {duration_days} ngày {vehicle_phrase}",
            "slots": ["group_size", "origin_mention", "dest_mention", "duration_days", "vehicle_type"],
            "kind": "province",
        },
        {
            "id": "val_plan_p3_04",
            "pattern": "Gia đình {group_size} người từ {origin_mention} lên kế hoạch nghỉ dưỡng {dest_mention} {duration_days} hôm, nhớ ghé {pin_mention}",
            "slots": ["group_size", "origin_mention", "dest_mention", "duration_days", "pinned_mentions"],
            "kind": "province",
        },
        {
            "id": "val_plan_p3_05",
            "pattern": "Nhóm bạn {group_size} người đi từ {origin_mention} khám phá {dest_mention} {duration_days} ngày, né {excl_mention}",
            "slots": ["group_size", "origin_mention", "dest_mention", "duration_days", "excluded_mentions"],
            "kind": "province",
        },

        # P4: Duration-first (DAYS -> DEST -> ORIG ...)
        {
            "id": "val_plan_p4_01",
            "pattern": "Khoảng {duration_days} ngày tại {dest_mention} xuất phát từ {origin_mention}, nhờ bạn gợi ý hành trình",
            "slots": ["duration_days", "dest_mention", "origin_mention"],
            "kind": "province",
        },
        {
            "id": "val_plan_p4_02",
            "pattern": "Thời lượng {duration_days} hôm khám phá {dest_mention} đi từ {origin_mention} cho đoàn {group_size} người",
            "slots": ["duration_days", "dest_mention", "origin_mention", "group_size"],
            "kind": "province",
        },
        {
            "id": "val_plan_p4_03",
            "pattern": "Dành trọn {duration_days} ngày thưởng ngoạn {dest_mention} khởi hành ở {origin_mention} với chi phí {budget_phrase}",
            "slots": ["duration_days", "dest_mention", "origin_mention", "budget_total_vnd"],
            "kind": "province",
        },
        {
            "id": "val_plan_p4_04",
            "pattern": "Tận dụng {duration_days} hôm dạo chơi {dest_mention} đón tại {origin_mention} {vehicle_phrase}",
            "slots": ["duration_days", "dest_mention", "origin_mention", "vehicle_type"],
            "kind": "province",
        },
        {
            "id": "val_plan_p4_05",
            "pattern": "Kỳ nghỉ {duration_days} ngày ở {dest_mention} bắt đầu tại {origin_mention}, ghé thăm {pin_mention}",
            "slots": ["duration_days", "dest_mention", "origin_mention", "pinned_mentions"],
            "kind": "province",
        },

        # P5: Dest-Origin-Days (DEST -> ORIG -> DAYS ...)
        {
            "id": "val_plan_p5_01",
            "pattern": "Khảo sát vùng đất {dest_mention} đón khách từ {origin_mention} trong {duration_days} ngày cho {group_size} thành viên",
            "slots": ["dest_mention", "origin_mention", "duration_days", "group_size"],
            "kind": "province",
        },
        {
            "id": "val_plan_p5_02",
            "pattern": "Tham quan cảnh đẹp {dest_mention} đón tại {origin_mention} khoảng {duration_days} hôm với số tiền {budget_phrase}",
            "slots": ["dest_mention", "origin_mention", "duration_days", "budget_total_vnd"],
            "kind": "province",
        },
        {
            "id": "val_plan_p5_03",
            "pattern": "Thưởng ngoạn danh thắng {dest_mention} xuất phát ở {origin_mention} kéo dài {duration_days} ngày",
            "slots": ["dest_mention", "origin_mention", "duration_days"],
            "kind": "province",
        },
        {
            "id": "val_plan_p5_04",
            "pattern": "Dạo chơi khắp {dest_mention} khởi hành từ {origin_mention} thời lượng {duration_days} ngày, trừ {excl_mention}",
            "slots": ["dest_mention", "origin_mention", "duration_days", "excluded_mentions"],
            "kind": "province",
        },
        {
            "id": "val_plan_p5_05",
            "pattern": "Du ngoạn vùng {region_phrase} bắt đầu từ {origin_mention} trong {duration_days} ngày cho {group_size} khách",
            "slots": ["destination_regions", "origin_mention", "duration_days", "group_size"],
            "kind": "region",
        },
        {
            "id": "val_plan_p5_06",
            "pattern": "Trải nghiệm vùng {terrain_phrase} xuất phát tại {origin_mention} khoảng {duration_days} hôm với {budget_phrase}",
            "slots": ["terrain_types", "origin_mention", "duration_days", "budget_total_vnd"],
            "kind": "terrain",
        },
    ]

    search_templates: List[Dict[str, Any]] = [
        # 4 mẫu đơn slot {dest_mention}
        {
            "id": "val_search_01",
            "pattern": "Khảo sát địa điểm lưu trú chất lượng cao tại {dest_mention}",
            "slots": ["dest_mention"],
            "kind": "province",
        },
        {
            "id": "val_search_02",
            "pattern": "Khảo sát nơi thưởng thức ẩm thực nổi danh ở {dest_mention}",
            "slots": ["dest_mention"],
            "kind": "province",
        },
        {
            "id": "val_search_03",
            "pattern": "Điểm lưu trú phong cách mộc mạc quanh {dest_mention}",
            "slots": ["dest_mention"],
            "kind": "province",
        },
        {
            "id": "val_search_04",
            "pattern": "Không gian ẩm thực đậm chất truyền thống ở {dest_mention}",
            "slots": ["dest_mention"],
            "kind": "province",
        },
        # 4 mẫu multi-slot search: PREF -> DEST hoặc GRP -> DEST
        {
            "id": "val_search_05",
            "pattern": "Khách sạn {pref_phrase} tại vùng {dest_mention}",
            "slots": ["preferences", "dest_mention"],
            "kind": "province",
        },
        {
            "id": "val_search_06",
            "pattern": "Chỗ lưu trú {pref_phrase} quanh khu vực {dest_mention}",
            "slots": ["preferences", "dest_mention"],
            "kind": "province",
        },
        {
            "id": "val_search_07",
            "pattern": "Quán ăn phục vụ đoàn {group_size} khách tại {dest_mention}",
            "slots": ["group_size", "dest_mention"],
            "kind": "province",
        },
        {
            "id": "val_search_08",
            "pattern": "Nhà hàng ấm cúng cho {group_size} người ở {dest_mention}",
            "slots": ["group_size", "dest_mention"],
            "kind": "province",
        },
    ]

    advisory_templates: List[Dict[str, Any]] = [
        {
            "id": "val_adv_01",
            "pattern": "Thời khắc tham quan {dest_mention} đẹp và thuận tiện nhất?",
            "slots": ["dest_mention"],
            "kind": "province",
        },
        {
            "id": "val_adv_02",
            "pattern": "Kinh nghiệm mang hành lý khi trải nghiệm {dest_mention}?",
            "slots": ["dest_mention"],
            "kind": "province",
        },
        {
            "id": "val_adv_03",
            "pattern": "Phương tiện thích hợp nhất để tới {dest_mention}?",
            "slots": ["dest_mention"],
            "kind": "province",
        },
        {
            "id": "val_adv_04",
            "pattern": "Nét văn hóa độc đáo cần biết khi đến {dest_mention}?",
            "slots": ["dest_mention"],
            "kind": "province",
        },
        {
            "id": "val_adv_05",
            "pattern": "Món quà kỷ niệm mang đậm dấu ấn tại {dest_mention} là gì?",
            "slots": ["dest_mention"],
            "kind": "province",
        },
        {
            "id": "val_adv_06",
            "pattern": "Đi tham quan {dest_mention} {pref_phrase} cần lưu ý những gì?",
            "slots": ["dest_mention", "preferences"],
            "kind": "province",
        },
    ]

    clarify_templates: List[Dict[str, Any]] = [
        {
            "id": "val_clarify_01",
            "pattern": "Dự định thực hiện kỳ nghỉ thư thái mà chưa lựa được miền đất nào",
            "slots": [],
        },
        {
            "id": "val_clarify_02",
            "pattern": "Đang cân nhắc tìm điểm thư giãn cuối tuần nhưng chưa định hình tọa độ",
            "slots": [],
        },
        {
            "id": "val_clarify_03",
            "pattern": "Muốn tổ chức chuyến thưởng ngoạn non nước nhưng còn lưỡng lự chưa chốt nơi",
            "slots": [],
        },
        {
            "id": "val_clarify_04",
            "pattern": "Cần tham khảo một cung đường dã ngoại thanh bình mà chưa xác định nơi đi",
            "slots": [],
        },
        {
            "id": "val_clarify_05",
            "pattern": "Muốn tìm một chốn dừng chân thanh tịnh để giải tỏa căng thẳng",
            "slots": [],
        },
        {
            "id": "val_clarify_06",
            "pattern": "Đoàn mình lên kế hoạch vi vu đổi không khí mà chưa thống nhất được phương hướng",
            "slots": [],
        },
        {
            "id": "val_clarify_07",
            "pattern": "Băn khoăn lựa chọn một điểm du lịch phù hợp cho gia đình có người lớn tuổi",
            "slots": [],
        },
        {
            "id": "val_clarify_08",
            "pattern": "Muốn tìm cung đường trekking nhẹ nhàng gần gũi cỏ cây mà chưa biết ở đâu",
            "slots": [],
        },
    ]

    return {
        "plan": plan_templates,
        "search": search_templates,
        "advisory": advisory_templates,
        "clarify": clarify_templates,
    }


# ---------------------------------------------------------------------------
# 5. HÀM TỔ HỢP CHO TẬP ADV (ADVERSARIAL COMPOSITION)
# ---------------------------------------------------------------------------

def compose_adv_templates() -> Dict[str, Any]:
    """
    Sinh các template cho ADVERSARIAL & MINIMAL PAIRS:
    - Minimal Pairs mở rộng với các hoán vị Origin-first, POI-first, Duration-first
    - Inverted templates mở rộng
    - Bảo toàn verbatim cho pref_val và excl_act_val
    - Tỷ lệ trùng lặp chu kỳ slot với Train < 40% (mục tiêu 15-25%).
    """
    minimal_pairs = [
        # Cặp 1: Standard P1 (DEST -> DAYS -> ORIG -> POI) [Match Train]
        {
            "id": "adv_pair_01",
            "pair_type": "pin_vs_excl",
            "pattern_pin": "Lập kế hoạch du hí {dest_mention} trong {duration_days} ngày từ {origin_mention}, nhất quyết ghé {target_poi}",
            "pattern_excl": "Lập kế hoạch du hí {dest_mention} trong {duration_days} ngày từ {origin_mention}, nhất quyết trừ {target_poi} ra",
            "has_group_size": False,
            "kind": "province",
        },
        # Cặp 2: Standard P1 có group_size [Match Train]
        {
            "id": "adv_pair_02",
            "pair_type": "pin_vs_excl",
            "pattern_pin": "Lên tour trải nghiệm {dest_mention} {duration_days} hôm khởi hành từ {origin_mention} cho {group_size} người, ghé thăm {target_poi}",
            "pattern_excl": "Lên tour trải nghiệm {dest_mention} {duration_days} hôm khởi hành từ {origin_mention} cho {group_size} người, né {target_poi} giúp mình",
            "has_group_size": True,
            "kind": "province",
        },
        # Cặp 3: P2 Origin-first (ORIG -> DEST -> DAYS -> POI) [KHÔNG MATCH TRAIN]
        {
            "id": "adv_pair_03",
            "pair_type": "pin_vs_excl",
            "pattern_pin": "Khởi hành từ {origin_mention} đi {dest_mention} {duration_days} ngày, nhớ ghé {target_poi} nhé",
            "pattern_excl": "Khởi hành từ {origin_mention} đi {dest_mention} {duration_days} ngày, bỏ qua {target_poi} nhé",
            "has_group_size": False,
            "kind": "province",
        },
        # Cặp 4: P2 Origin-first có group_size (ORIG -> DEST -> DAYS -> GRP -> POI) [KHÔNG MATCH TRAIN]
        {
            "id": "adv_pair_04",
            "pair_type": "pin_vs_excl",
            "pattern_pin": "Bắt đầu ở {origin_mention} tới {dest_mention} {duration_days} hôm cho {group_size} người, nhất định ghé {target_poi}",
            "pattern_excl": "Bắt đầu ở {origin_mention} tới {dest_mention} {duration_days} hôm cho {group_size} người, trừ hẳn {target_poi}",
            "has_group_size": True,
            "kind": "province",
        },
        # Cặp 5: P3 POI-first (POI -> DEST -> DAYS -> ORIG) [KHÔNG MATCH TRAIN]
        {
            "id": "adv_pair_05",
            "pair_type": "pin_vs_excl",
            "pattern_pin": "Điểm đến {target_poi} phải ghé qua trong chuyến dạo chơi {dest_mention} {duration_days} ngày đi từ {origin_mention}",
            "pattern_excl": "Điểm đến {target_poi} phải gạch bỏ trong chuyến dạo chơi {dest_mention} {duration_days} ngày đi từ {origin_mention}",
            "has_group_size": False,
            "kind": "province",
        },
        # Cặp 6: P4 Duration-first (DAYS -> DEST -> ORIG -> POI) [KHÔNG MATCH TRAIN]
        {
            "id": "adv_pair_06",
            "pair_type": "pin_vs_excl",
            "pattern_pin": "Tận dụng {duration_days} ngày vi vu {dest_mention} từ {origin_mention}, ưu tiên ghé {target_poi}",
            "pattern_excl": "Tận dụng {duration_days} ngày vi vu {dest_mention} từ {origin_mention}, né xa {target_poi}",
            "has_group_size": False,
            "kind": "province",
        },
        # Cặp 7: P3 Group-first (GRP -> ORIG -> DEST -> DAYS -> POI) [KHÔNG MATCH TRAIN]
        {
            "id": "adv_pair_07",
            "pair_type": "pin_vs_excl",
            "pattern_pin": "Đoàn {group_size} người từ {origin_mention} lên đường đi {dest_mention} {duration_days} hôm, nhất định ghé {target_poi}",
            "pattern_excl": "Đoàn {group_size} người từ {origin_mention} lên đường đi {dest_mention} {duration_days} hôm, tránh xa {target_poi}",
            "has_group_size": True,
            "kind": "province",
        },
        # Cặp 8: P5 Dest-Orig-Days (DEST -> ORIG -> DAYS -> POI) [KHÔNG MATCH TRAIN]
        {
            "id": "adv_pair_08",
            "pair_type": "pin_vs_excl",
            "pattern_pin": "Lộ trình tham quan {dest_mention} xuất phát từ {origin_mention} kéo dài {duration_days} ngày, chọn ghé {target_poi}",
            "pattern_excl": "Lộ trình tham quan {dest_mention} xuất phát từ {origin_mention} kéo dài {duration_days} ngày, khỏi ghé {target_poi}",
            "has_group_size": False,
            "kind": "province",
        },
        # =====================================================================
        # CATEGORY A: ACTIVITY EXCLUSION VS INCLUSION (PREFERENCE)
        # =====================================================================
        # Cặp 9: P2 Origin-first (ORIG -> DEST -> DAYS -> ACT)
        {
            "id": "adv_pair_09",
            "pair_type": "activity_inc_vs_excl",
            "pattern_pos": "Khởi hành từ {origin_mention} đi {dest_mention} {duration_days} ngày, rất muốn trải nghiệm {target_activity}",
            "pattern_neg": "Khởi hành từ {origin_mention} đi {dest_mention} {duration_days} ngày, muốn tránh trải nghiệm {target_activity}",
            "has_group_size": False,
            "kind": "province",
        },
        # Cặp 10: P2 Origin-first có group_size (ORIG -> DEST -> DAYS -> GRP -> ACT)
        {
            "id": "adv_pair_10",
            "pair_type": "activity_inc_vs_excl",
            "pattern_pos": "Xuất phát tại {origin_mention} ghé {dest_mention} {duration_days} hôm cho {group_size} người, ưu tiên tham gia {target_activity}",
            "pattern_neg": "Xuất phát tại {origin_mention} ghé {dest_mention} {duration_days} hôm cho {group_size} người, lưu ý né {target_activity}",
            "has_group_size": True,
            "kind": "province",
        },
        # Cặp 11: P4 Duration-first (DAYS -> DEST -> ORIG -> ACT)
        {
            "id": "adv_pair_11",
            "pair_type": "activity_inc_vs_excl",
            "pattern_pos": "Dành trọn {duration_days} ngày khám phá {dest_mention} từ {origin_mention}, hào hứng với hoạt động {target_activity}",
            "pattern_neg": "Dành trọn {duration_days} ngày khám phá {dest_mention} từ {origin_mention}, không thích hoạt động {target_activity}",
            "has_group_size": False,
            "kind": "province",
        },
        # Cặp 12: P5 Dest-Orig-Days (DEST -> ORIG -> DAYS -> ACT)
        {
            "id": "adv_pair_12",
            "pair_type": "activity_inc_vs_excl",
            "pattern_pos": "Tour du ngoạn {dest_mention} đón tại {origin_mention} trong {duration_days} hôm, cả đoàn thích {target_activity}",
            "pattern_neg": "Tour du ngoạn {dest_mention} đón tại {origin_mention} trong {duration_days} hôm, cả đoàn kiêng {target_activity}",
            "has_group_size": False,
            "kind": "province",
        },
        # =====================================================================
        # CATEGORY B: PREFERENCE ATTRIBUTES (POSITIVE VS NEGATIVE CONSTRAINT)
        # =====================================================================
        # Cặp 13: P2 Origin-first (ORIG -> DEST -> DAYS)
        {
            "id": "adv_pair_13",
            "pair_type": "pref_pos_vs_neg",
            "pattern_pos": "Bắt đầu từ {origin_mention} đi nghỉ mát {dest_mention} {duration_days} ngày, ưu tiên chỗ ở gần biển",
            "pattern_neg": "Bắt đầu từ {origin_mention} đi nghỉ mát {dest_mention} {duration_days} ngày, ưu tiên chỗ ở không gần biển",
            "pref_pos_val": "gần biển",
            "pref_neg_val": "không gần biển",
            "has_group_size": False,
            "kind": "province",
        },
        # Cặp 14: P2 Origin-first có group_size (ORIG -> DEST -> DAYS -> GRP)
        {
            "id": "adv_pair_14",
            "pair_type": "pref_pos_vs_neg",
            "pattern_pos": "Từ {origin_mention} du lịch {dest_mention} {duration_days} hôm cho {group_size} khách, chọn không gian náo nhiệt",
            "pattern_neg": "Từ {origin_mention} du lịch {dest_mention} {duration_days} hôm cho {group_size} khách, chọn không gian không quá náo nhiệt",
            "pref_pos_val": "không gian náo nhiệt",
            "pref_neg_val": "không quá náo nhiệt",
            "has_group_size": True,
            "kind": "province",
        },
        # Cặp 15: P4 Duration-first (DAYS -> DEST -> ORIG)
        {
            "id": "adv_pair_15",
            "pair_type": "pref_pos_vs_neg",
            "pattern_pos": "Kỳ nghỉ {duration_days} ngày tại {dest_mention} đón ở {origin_mention}, yêu cầu phòng có hút thuốc",
            "pattern_neg": "Kỳ nghỉ {duration_days} ngày tại {dest_mention} đón ở {origin_mention}, yêu cầu phòng không khói thuốc",
            "pref_pos_val": "phòng có hút thuốc",
            "pref_neg_val": "không khói thuốc",
            "has_group_size": False,
            "kind": "province",
        },
        # Cặp 16: P5 Dest-Orig-Days (DEST -> ORIG -> DAYS)
        {
            "id": "adv_pair_16",
            "pair_type": "pref_pos_vs_neg",
            "pattern_pos": "Hành trình thăm thú {dest_mention} khởi hành ở {origin_mention} kéo dài {duration_days} hôm, mong muốn ở gần trung tâm",
            "pattern_neg": "Hành trình thăm thú {dest_mention} khởi hành ở {origin_mention} kéo dài {duration_days} hôm, mong muốn ở không gần trung tâm",
            "pref_pos_val": "gần trung tâm",
            "pref_neg_val": "không gần trung tâm",
            "has_group_size": False,
            "kind": "province",
        },
        # =====================================================================
        # CATEGORY C: REVERSE POLARITY MINIMAL PAIRS ('không' != exclusion)
        # =====================================================================
        # Cặp 17: POI Reverse Polarity Pin vs Exclusion (ORIG -> DEST -> DAYS -> POI)
        {
            "id": "adv_pair_17",
            "pair_type": "reverse_polarity",
            "sub_type": "poi",
            "pattern_pos": "Từ {origin_mention} lên tour đi {dest_mention} {duration_days} ngày, không thể bỏ qua {target_poi}",
            "pattern_neg": "Từ {origin_mention} lên tour đi {dest_mention} {duration_days} ngày, nhất quyết bỏ qua {target_poi}",
            "has_group_size": False,
            "kind": "province",
        },
        # Cặp 18: POI Reverse Polarity Pin vs Exclusion có group_size (ORIG -> DEST -> DAYS -> GRP -> POI)
        {
            "id": "adv_pair_18",
            "pair_type": "reverse_polarity",
            "sub_type": "poi",
            "pattern_pos": "Bắt đầu tại {origin_mention} ghé {dest_mention} {duration_days} hôm cho {group_size} người, không thể không tới {target_poi}",
            "pattern_neg": "Bắt đầu tại {origin_mention} ghé {dest_mention} {duration_days} hôm cho {group_size} người, dặn trước không tới {target_poi}",
            "has_group_size": True,
            "kind": "province",
        },
        # Cặp 19: Activity Reverse Polarity Preference vs Exclusion (DAYS -> DEST -> ORIG -> ACT)
        {
            "id": "adv_pair_19",
            "pair_type": "reverse_polarity",
            "sub_type": "activity",
            "pattern_pos": "Khoảng {duration_days} ngày dạo chơi {dest_mention} đi từ {origin_mention}, cả đoàn không ngại {target_activity}",
            "pattern_neg": "Khoảng {duration_days} ngày dạo chơi {dest_mention} đi từ {origin_mention}, cả đoàn rất ngại {target_activity}",
            "has_group_size": False,
            "kind": "province",
        },
        # Cặp 20: Budget Reverse Polarity (Unlimited) vs Budget Constraint (DEST -> ORIG -> DAYS [-> BUD])
        {
            "id": "adv_pair_20",
            "pair_type": "reverse_polarity",
            "sub_type": "budget",
            "pattern_pos": "Lộ trình khám phá {dest_mention} xuất phát từ {origin_mention} {duration_days} hôm, không giới hạn ngân sách chi tiêu",
            "pattern_neg": "Lộ trình khám phá {dest_mention} xuất phát từ {origin_mention} {duration_days} hôm, có giới hạn {budget_phrase} chi tiêu",
            "has_group_size": False,
            "kind": "province",
        },
    ]

    inverted_templates = [
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
            "pattern": "Khởi hành từ {origin_mention}, mục tiêu khám phá {dest_mention} {duration_days} hôm {vehicle_phrase}",
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
            "pattern": "Xuất phát từ {origin_mention}, tour {dest_mention} kéo dài {duration_days} ngày với {budget_phrase}",
            "slots": ["origin_mention", "dest_mention", "duration_days", "budget_total_vnd"],
            "kind": "province",
        },
        {
            "id": "adv_inv_05",
            "intent": "plan_itinerary",
            "pattern": "Bắt đầu ở {origin_mention}, lịch trình khám phá {dest_mention} {duration_days} hôm, nhất định ghé {pin_mention}",
            "slots": ["origin_mention", "dest_mention", "duration_days", "pinned_mentions"],
            "kind": "province",
        },
        {
            "id": "adv_inv_06",
            "intent": "plan_itinerary",
            "pattern": "Từ {origin_mention} tiến thẳng tới {dest_mention} {duration_days} ngày cho đoàn {group_size} khách {vehicle_phrase}",
            "slots": ["origin_mention", "dest_mention", "duration_days", "group_size", "vehicle_type"],
            "kind": "province",
        },
        {
            "id": "adv_inv_07",
            "intent": "plan_itinerary",
            "pattern": "Điểm đón ở {origin_mention}, hành trình {dest_mention} {duration_days} hôm với khoản tiền {budget_phrase}",
            "slots": ["origin_mention", "dest_mention", "duration_days", "budget_total_vnd"],
            "kind": "province",
        },
        {
            "id": "adv_inv_08",
            "intent": "plan_itinerary",
            "pattern": "Khởi hành tại {origin_mention}, cung đường {dest_mention} {duration_days} ngày, {pref_phrase}",
            "slots": ["origin_mention", "dest_mention", "duration_days", "preferences"],
            "kind": "province",
        },
        {
            "id": "adv_inv_09",
            "intent": "plan_itinerary",
            "pattern": "Từ {origin_mention} di chuyển tới {dest_mention} {duration_days} hôm, bỏ qua {excl_mention}",
            "slots": ["origin_mention", "dest_mention", "duration_days", "excluded_mentions"],
            "kind": "province",
        },
        {
            "id": "adv_inv_10",
            "intent": "plan_itinerary",
            "pattern": "Xuất phát ở {origin_mention}, kế hoạch vi vu {dest_mention} {duration_days} ngày, ưu tiên ghé {pin_mention}",
            "slots": ["origin_mention", "dest_mention", "duration_days", "pinned_mentions"],
            "kind": "province",
        },
    ]

    search_templates = [
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
            "pattern": "Gợi ý nơi nghỉ ngơi ở {dest_mention} không gian yên tĩnh",
            "slots": ["dest_mention"],
            "pref_val": "không gian yên tĩnh",
            "kind": "province",
        },
        {
            "id": "adv_search_06",
            "intent": "search_place",
            "pattern": "Tìm quán ăn quanh {dest_mention} không uống rượu bia",
            "slots": ["dest_mention"],
            "excl_act_val": "uống rượu bia",
            "kind": "province",
        },
    ]

    advisory_templates = [
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
            "pattern": "Thời điểm nào ghé {dest_mention} thì không quá lạnh và sương mù?",
            "slots": ["dest_mention"],
            "pref_val": "không quá lạnh",
            "kind": "province",
        },
        {
            "id": "adv_advisory_03",
            "intent": "ask_advisory",
            "pattern": "Đến {dest_mention} vào mùa này có bị không khí ẩm ướt không?",
            "slots": ["dest_mention"],
            "pref_val": "không khí ẩm ướt",
            "kind": "province",
        },
        {
            "id": "adv_advisory_04",
            "intent": "ask_advisory",
            "pattern": "Nên đi {dest_mention} vào tháng nào để không gặp bão lớn?",
            "slots": ["dest_mention"],
            "pref_val": "không gặp bão",
            "kind": "province",
        },
        {
            "id": "adv_advisory_05",
            "intent": "ask_advisory",
            "pattern": "Tháng nào tham quan {dest_mention} có thời tiết không quá nắng gắt?",
            "slots": ["dest_mention"],
            "pref_val": "không quá nắng gắt",
            "kind": "province",
        },
    ]

    clarify_templates = [
        {
            "id": "adv_clarify_01",
            "intent": "clarify_needed",
            "pattern": "Muốn đi du lịch mà không biết nên đi đâu cho khuây khỏa",
            "slots": [],
        },
        {
            "id": "adv_clarify_02",
            "intent": "clarify_needed",
            "pattern": "Cả nhóm không thống nhất được địa điểm đi chơi cuối tuần",
            "slots": [],
        },
        {
            "id": "adv_clarify_03",
            "intent": "clarify_needed",
            "pattern": "Mình không có ý tưởng gì cho chuyến đi nghỉ dưỡng sắp tới",
            "slots": [],
        },
        {
            "id": "adv_clarify_04",
            "intent": "clarify_needed",
            "pattern": "Đang muốn đổi gió nhưng không rõ chỗ nào đang có mùa hoa đẹp",
            "slots": [],
        },
        {
            "id": "adv_clarify_05",
            "intent": "clarify_needed",
            "pattern": "Chưa quyết định được nơi đến dù không thiếu thời gian rảnh",
            "slots": [],
        },
        {
            "id": "adv_clarify_06",
            "intent": "clarify_needed",
            "pattern": "Tư vấn giúp điểm du lịch nào không quá đông đúc mà chưa rõ đi đâu",
            "slots": [],
        },
        {
            "id": "adv_clarify_07",
            "intent": "clarify_needed",
            "pattern": "Cuối tuần không muốn ở nhà nhưng chưa biết xách balo đi đâu",
            "slots": [],
        },
        {
            "id": "adv_clarify_08",
            "intent": "clarify_needed",
            "pattern": "Hai đứa muốn đi chơi kỷ niệm nhưng không chọn được điểm hẹn",
            "slots": [],
        },
        {
            "id": "adv_clarify_09",
            "intent": "clarify_needed",
            "pattern": "Cần tìm nơi giải tỏa căng thẳng mà không có chút manh mối điểm đến",
            "slots": [],
        },
        {
            "id": "adv_clarify_10",
            "intent": "clarify_needed",
            "pattern": "Muốn lên đường ngay nhưng không quyết được hướng đi Bắc hay Nam",
            "slots": [],
        },
    ]

    unaccented_templates = [
        {
            "id": "adv_unacc_01",
            "intent": "plan_itinerary",
            "pattern": "di {dest_mention} {duration_days} ngay tu {origin_mention} cho {group_size} nguoi",
            "slots": ["dest_mention", "duration_days", "origin_mention", "group_size"],
            "kind": "province",
        },
        {
            "id": "adv_unacc_02",
            "intent": "plan_itinerary",
            "pattern": "khoi hanh tu {origin_mention} di {dest_mention} {duration_days} ngay",
            "slots": ["origin_mention", "dest_mention", "duration_days"],
            "kind": "province",
        },
        {
            "id": "adv_unacc_03",
            "intent": "search_place",
            "pattern": "tim khach san o {dest_mention} view dep",
            "slots": ["dest_mention"],
            "kind": "province",
        },
        {
            "id": "adv_unacc_04",
            "intent": "ask_advisory",
            "pattern": "di {dest_mention} mua nao dep nhat trong nam",
            "slots": ["dest_mention"],
            "kind": "province",
        },
        {
            "id": "adv_unacc_05",
            "intent": "clarify_needed",
            "pattern": "muon di choi ma chua biet di dau doi gio",
            "slots": [],
        },
        {
            "id": "adv_unacc_06",
            "intent": "plan_itinerary",
            "pattern": "tu {origin_mention} di {dest_mention} {duration_days} ngay, ne {excl_mention}",
            "slots": ["origin_mention", "dest_mention", "duration_days", "excluded_mentions"],
            "kind": "province",
        },
        {
            "id": "adv_unacc_07",
            "intent": "plan_itinerary",
            "pattern": "xuat phat tu {origin_mention} tham {dest_mention} {duration_days} hom {vehicle_phrase}",
            "slots": ["origin_mention", "dest_mention", "duration_days", "vehicle_type"],
            "kind": "province",
        },
        {
            "id": "adv_unacc_08",
            "intent": "plan_itinerary",
            "pattern": "doan {group_size} ban tu {origin_mention} di {dest_mention} {duration_days} ngay",
            "slots": ["group_size", "origin_mention", "dest_mention", "duration_days"],
            "kind": "province",
        },
    ]

    return {
        "minimal_pairs": minimal_pairs,
        "inverted": inverted_templates,
        "search": search_templates,
        "advisory": advisory_templates,
        "clarify": clarify_templates,
        "unaccented": unaccented_templates,
    }
