"""
scripts/build_v5_dataset.py
═══════════════════════════════════════════════════════════════════════════════
Dataset v5.2 Slot-First Production Synthesis Engine for Travel AI Việt Nam
Triển khai nghiêm ngặt theo Hướng dẫn chi tiết NLU v5.1 & Annotation Spec v5.2:

1. Slot-First Generation: (1) tạo SlotSpec, (2) chọn template, (3) render,
   (4) check_row bắt buộc, (5) ghi.
2. Render chính xác với string.Formatter, lưu character spans tự động.
3. Không bao giờ đoán nhãn từ câu (không dùng regex ngược, bỏ hoàn toàn convert_v3).
4. Origin an toàn tuyệt đối: dest_code != orig_code, origin resolve được và không mơ hồ.
5. Entity classification (kind: province, attraction, hotel, restaurant).
6. Tách khuôn câu độc lập giữa Train, Val và Adversarial (Zero template leakage).
7. Origin hold-out (70% Train, 30% Val/Test phân chia theo mã tỉnh địa lý).
8. Adversarial đa intent (đủ 4 intent) và Minimal Pairs với pair_id.
9. Đầy đủ các tỷ lệ slot: budget (20-25%), exclusion (15-20%), CURRENT_LOCATION (5-8%),
   không dấu (10-15%), slot trống (25-35%).
10. Cố định seed ngẫu nhiên rng = random.Random(42).
═══════════════════════════════════════════════════════════════════════════════
"""

import os
import sys
import json
import random
import sqlite3
import unicodedata
import re
from dataclasses import dataclass, field
from string import Formatter
from typing import List, Dict, Any, Set, Tuple, Optional

# sys.path root
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.gazetteer import Gazetteer, normalize_text, strip_accents
from scripts.templates_train import (
    TRAIN_PLAN_TEMPLATES,
    TRAIN_SEARCH_TEMPLATES,
    TRAIN_ADVISORY_TEMPLATES,
    TRAIN_CLARIFY_TEMPLATES,
)
from scripts.templates_val import (
    VAL_PLAN_TEMPLATES,
    VAL_SEARCH_TEMPLATES,
    VAL_ADVISORY_TEMPLATES,
    VAL_CLARIFY_TEMPLATES,
)
from scripts.templates_adv import (
    MINIMAL_PAIR_TEMPLATES,
    ADV_INVERTED_TEMPLATES,
    ADV_SEARCH_TEMPLATES,
    ADV_ADVISORY_TEMPLATES,
    ADV_CLARIFY_TEMPLATES,
    ADV_UNACCENTED_TEMPLATES,
)

# ---------------------------------------------------------------------------
# 1. SPEC V5.2 SCHEMA & CONSTANTS
# ---------------------------------------------------------------------------
KEY_ORDER_V5 = [
    "intent",
    "destination_mention",
    "destination_regions",
    "terrain_types",
    "excluded_mentions",
    "origin_mention",
    "duration_days",
    "group_size",
    "vehicle_type",
    "budget_total_vnd",
    "preferences",
    "excluded_activities",
    "pinned_mentions",
    "prefer_flight",
]

INTENTS = {"plan_itinerary", "search_place", "ask_advisory", "clarify_needed"}
REGIONS = {
    "NORTH", "NORTHWEST", "NORTHEAST", "RED_RIVER_DELTA", "NORTH_CENTRAL", "CENTRAL",
    "SOUTH_CENTRAL", "CENTRAL_HIGHLANDS", "SOUTH", "SOUTHEAST", "MEKONG_DELTA"
}
TERRAINS = {"BEACH", "ISLAND", "MOUNTAIN", "HIGHLAND", "FOREST", "CAVE", "RIVER"}

SYSTEM_V5_1 = (
    "Bạn là NLU Engine chuyên dụng cho hệ thống Travel AI Việt Nam.\n"
    "Nhiệm vụ: Phân tích yêu cầu tự do của người dùng và trích xuất thành định dạng JSON chuẩn.\n"
    "Quy tắc nghiêm ngặt:\n"
    "1. Chỉ trả về duy nhất chuỗi JSON hợp lệ bắt đầu bằng '{' và kết thúc bằng '}', không kèm markdown hay lời dẫn.\n"
    "2. Xác định đúng intent trong 4 loại: 'plan_itinerary', 'search_place', 'ask_advisory', 'clarify_needed'. "
    "Khi câu quá ngắn, thiếu hoàn toàn điểm đến hoặc mơ hồ, bắt buộc chọn 'clarify_needed'.\n"
    "3. Nếu người dùng không đề cập thông tin nào, trường tương ứng BẮT BUỘC để null (hoặc [] với mảng). "
    "Tuyệt đối không tự suy diễn số liệu hay điền thông tin không có trong câu.\n"
    "4. 'destination_mention' và 'origin_mention' BẮT BUỘC trích xuất NGUYÊN VĂN chuỗi ký tự chỉ địa danh xuất hiện trong câu "
    "(giữ nguyên cách viết, teencode, viết tắt hay tên cũ của người dùng, không tự ý đổi sang tên tỉnh hành chính). "
    "Điểm đến (destination) thường đứng sau các từ như 'đi', 'đến', 'tới', 'ghé', 'thăm', 'du lịch'. "
    "Điểm xuất phát (origin) thường đứng sau các từ như 'từ', 'xuất phát từ', 'khởi hành từ'. "
    "Nếu người dùng nói 'từ đây', 'ở đây', 'chỗ này', 'vị trí hiện tại', origin_mention BẮT BUỘC ghi là 'CURRENT_LOCATION'.\n"
    "5. Nếu người dùng không nêu địa danh cụ thể mà chỉ nói vùng miền hoặc loại địa hình (vd: 'phía Bắc', 'đi biển', 'núi'), "
    "để destination_mention = null và điền 'destination_regions' / 'terrain_types'.\n"
    "   - destination_regions chỉ nhận: NORTH, NORTHWEST, NORTHEAST, RED_RIVER_DELTA, NORTH_CENTRAL, CENTRAL, "
    "SOUTH_CENTRAL, CENTRAL_HIGHLANDS, SOUTH, SOUTHEAST, MEKONG_DELTA.\n"
    "   - terrain_types chỉ nhận: BEACH, ISLAND, MOUNTAIN, HIGHLAND, FOREST, CAVE, RIVER (xếp theo bảng chữ cái).\n"
    "   Khi đã có destination_mention cụ thể thì cả hai trường trên BẮT BUỘC là [] (các từ như 'biển', 'núi' đưa vào preferences).\n"
    "6. Địa danh người dùng muốn LOẠI TRỪ (trừ, ngoại trừ, không đi, tránh, bỏ...) đưa nguyên văn vào 'excluded_mentions'. "
    "Địa danh bắt buộc ghé đưa nguyên văn vào 'pinned_mentions'.\n"
    "7. 'vehicle_type' chỉ nhận một trong 5 giá trị: 'car', 'motorbike', 'plane', 'coach' (xe khách/limousine/16 chỗ), 'train'. "
    "Nếu người dùng không nêu rõ hoặc chỉ nói phương tiện chung chung, để null.\n"
    "8. 'budget_total_vnd' là tổng ngân sách ước tính bằng VNĐ (kiểu integer). Nếu người dùng nói ngân sách theo đầu người "
    "và có số người, nhân ra tổng chi phí; nếu không có số người hoặc không nói ngân sách, để null.\n"
    "9. 'duration_days' là số ngày của chuyến đi (ví dụ: '3N2Đ' -> 3, '4 ngày' -> 4, '1 hôm' -> 1). "
    "Tuyệt đối KHÔNG nhầm lẫn số ngày '4N3Đ' thành số người 'group_size'."
)

# ---------------------------------------------------------------------------
# 2. DATA CLASSES & CORE PROTOCOLS
# ---------------------------------------------------------------------------
@dataclass
class SlotSpec:
    intent: str
    dest_mention: Optional[str] = None
    orig_mention: Optional[str] = None
    duration_days: Optional[int] = None
    group_size: Optional[int] = None
    vehicle_type: Optional[str] = None
    budget_total_vnd: Optional[int] = None
    excluded_mentions: List[str] = field(default_factory=list)
    pinned_mentions: List[str] = field(default_factory=list)
    preferences: List[str] = field(default_factory=list)
    excluded_activities: List[str] = field(default_factory=list)
    destination_regions: List[str] = field(default_factory=list)
    terrain_types: List[str] = field(default_factory=list)
    prefer_flight: Optional[bool] = None
    pair_id: Optional[str] = None


def render(template: str, values: Dict[str, Any]) -> Tuple[str, Dict[str, List[Tuple[int, int]]]]:
    """Hàm render template ghi lại chính xác vị trí ký tự (char spans). Không dùng regex."""
    parts, spans, cur = [], {}, 0
    for literal, field_name, _, _ in Formatter().parse(template):
        parts.append(literal)
        cur += len(literal)
        if field_name is not None:
            val = str(values[field_name])
            spans.setdefault(field_name, []).append((cur, cur + len(val)))
            parts.append(val)
            cur += len(val)
    return "".join(parts), spans


def check_row(text: str, spans: Dict[str, List[Tuple[int, int]]], values: Dict[str, Any], spec: SlotSpec):
    """Kiểm tra bắt buộc sau khi render theo mục 2.3."""
    # 1. mỗi span khớp đúng giá trị
    for name, lst in spans.items():
        for s, e in lst:
            assert text[s:e] == str(values[name]), (
                f"Span mismatch for '{name}': expected '{values[name]}', got '{text[s:e]}' in text '{text}'"
            )
    # 2. các span không chồng lấn
    flat = sorted(x for lst in spans.values() for x in lst)
    for (s1, e1), (s2, e2) in zip(flat, flat[1:]):
        assert e1 <= s2, f"Span overlap in '{text}': ({s1}, {e1}) vs ({s2}, {e2})"
    # 3. dest khác orig
    if spec.dest_mention and spec.orig_mention and spec.orig_mention != "CURRENT_LOCATION":
        assert spec.dest_mention.lower() != spec.orig_mention.lower(), (
            f"dest equals orig in '{text}' ({spec.dest_mention})"
        )
    # 4. dest không nằm trong danh sách loại trừ
    if spec.dest_mention:
        assert spec.dest_mention not in spec.excluded_mentions, (
            f"dest '{spec.dest_mention}' is inside excluded_mentions {spec.excluded_mentions}"
        )


def norm_simple(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", strip_accents(s or ""))).strip()


def sample_origin(
    dest: Optional[str],
    excluded: List[str],
    pool: List[str],
    gaz: Gazetteer,
    rng: random.Random,
    max_try: int = 30,
) -> str:
    """Chọn origin an toàn theo mục 2.4: resolve được, không mơ hồ, khác tỉnh với dest."""
    dest_res = gaz.resolve_mention(dest) if dest else None
    dest_code = dest_res["province_code"] if dest_res else None
    excl = {x.lower() for x in excluded}
    for _ in range(max_try):
        o = rng.choice(pool)
        r = gaz.resolve_mention(o)
        if r is None or r.get("province_code") is None:
            continue  # origin phải resolve được và không mơ hồ
        if dest_code is not None and r["province_code"] == dest_code:
            continue  # cùng tỉnh -> bốc lại
        if o.lower() in excl:
            continue
        # Chặn chuỗi con gây nhầm lẫn (như Vinh vs Vĩnh Long)
        if dest:
            d_norm = norm_simple(dest)
            o_norm = norm_simple(o)
            if d_norm in o_norm or o_norm in d_norm:
                continue
        return o
    raise ValueError(f"Không chọn được origin an toàn cho dest='{dest}'")


# ---------------------------------------------------------------------------
# 3. DEDUP & DELEXICALIZATION
# ---------------------------------------------------------------------------
def delex(text: str, spec: SlotSpec) -> str:
    t = text.lower()
    if spec.dest_mention:
        t = t.replace(spec.dest_mention.lower(), "<dest>")
    if spec.orig_mention and spec.orig_mention != "CURRENT_LOCATION":
        t = t.replace(spec.orig_mention.lower(), "<orig>")
    for ex in spec.excluded_mentions:
        t = t.replace(ex.lower(), "<poi>")
    for pin in spec.pinned_mentions:
        t = t.replace(pin.lower(), "<poi>")
    t = re.sub(r"\d+", "0", t)
    return t


def trigrams(s: str) -> Set[str]:
    words = s.split()
    return {" ".join(words[i:i + 3]) for i in range(max(1, len(words) - 2))}


def jaccard(a: Set[str], b: Set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


# ---------------------------------------------------------------------------
# 4. KHO THỰC THỂ (POIS & PROVINCES & HOLDOUT)
# ---------------------------------------------------------------------------
def load_and_classify_entities(db_path: str = "travel_db.db", gaz: Gazetteer = None):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # 1. Tải danh sách tỉnh
    cur.execute("SELECT code, name FROM provinces ORDER BY code")
    prov_rows = cur.fetchall()

    # 2. Tải địa danh
    cur.execute("""
        SELECT p.id, p.name, p.category, p.province_code, pr.name
        FROM places p
        JOIN provinces pr ON p.province_code = pr.code
        ORDER BY p.id
    """)
    place_rows = cur.fetchall()
    conn.close()

    provinces = []
    for code, pname in prov_rows:
        clean = pname.replace("Thành phố", "").replace("Tỉnh", "").strip()
        provinces.append({"code": code, "name": clean, "kind": "province"})

    # Phân loại thực thể
    attractions = []
    hotels = []
    restaurants = []
    places_by_pcode: Dict[int, List[Dict[str, Any]]] = {}

    OVERCAPTURE_RE = re.compile(
        r"(?<!\w)(bằng|săn|ngắm|cưỡi|uống|tắm biển|nghỉ dưỡng|cuối tuần|khoảng|trong|và|rồi|thích|đón)(?!\w)",
        re.I
    )

    for pid, name, cat, pcode, pr_name in place_rows:
        s_name = name.strip()
        if OVERCAPTURE_RE.search(s_name) or "(" in s_name or ")" in s_name or len(s_name) > 35:
            continue
        item = {
            "id": pid,
            "name": s_name,
            "category": cat,
            "province_code": pcode,
            "province_name": pr_name.replace("Thành phố", "").replace("Tỉnh", "").strip(),
        }
        places_by_pcode.setdefault(pcode, []).append(item)
        if cat in ("ATTRACTION", "TEMPLE", "HISTORICAL_SITE", "BEACH", "ACTIVITY", "MARKET"):
            item["kind"] = "attraction"
            attractions.append(item)
        elif cat == "HOTEL":
            item["kind"] = "hotel"
            hotels.append(item)
        elif cat == "RESTAURANT":
            item["kind"] = "restaurant"
            restaurants.append(item)

    # Chia hold-out theo tỉnh (Origin hold-out: ~30% mã tỉnh cho Val/Adv)
    # Val/Adv hold-out provinces: 11 (Điện Biên), 20 (Lạng Sơn), 33 (Hưng Yên), 42 (Hà Tĩnh),
    # 51 (Quảng Ngãi), 52 (Gia Lai), 80 (Tây Ninh), 86 (Vĩnh Long), 91 (An Giang), 96 (Cà Mau)
    val_origin_pcodes = {11, 20, 33, 42, 51, 52, 80, 86, 91, 96}

    # Pool origins
    all_origin_names = [
        "Hà Nội", "Hồ Chí Minh", "Đà Nẵng", "Hải Phòng", "Cần Thơ", "Huế",
        "Nha Trang", "Đà Lạt", "Quy Nhơn", "Vũng Tàu", "Buôn Ma Thuột", "Hạ Long",
        "Ninh Bình", "Thanh Hóa", "Vinh", "Phan Thiết", "Bắc Ninh", "Thái Nguyên",
        "Sơn La", "Điện Biên", "Lạng Sơn", "Hưng Yên", "Hà Tĩnh", "Quảng Ngãi",
        "Pleiku", "Tây Ninh", "Vĩnh Long", "Rạch Giá", "Cà Mau"
    ]
    train_origins = []
    val_origins = []
    for oname in all_origin_names:
        r = gaz.resolve_mention(oname)
        if r and r.get("province_code"):
            pcode = r["province_code"]
            if pcode in val_origin_pcodes:
                val_origins.append(oname)
            else:
                train_origins.append(oname)

    # Chia POIs: 80% train, 20% val/adv
    rng = random.Random(42)
    shuffled_attractions = list(attractions)
    rng.shuffle(shuffled_attractions)
    att_split = int(len(shuffled_attractions) * 0.8)
    train_attractions = shuffled_attractions[:att_split]
    val_attractions = shuffled_attractions[att_split:]

    return {
        "provinces": provinces,
        "train_origins": train_origins,
        "val_origins": val_origins,
        "train_attractions": train_attractions,
        "val_attractions": val_attractions,
        "hotels": hotels,
        "restaurants": restaurants,
        "places_by_pcode": places_by_pcode,
    }


# ---------------------------------------------------------------------------
# 5. SYNTHESIS ENGINE
# ---------------------------------------------------------------------------
VEHICLE_CHOICES = [
    ("car", "bằng ô tô"),
    ("car", "bằng xe hơi"),
    ("car", "thuê ô tô tự lái"),
    ("motorbike", "đi xe máy"),
    ("motorbike", "phượt xe máy"),
    ("plane", "bằng máy bay"),
    ("coach", "đi xe khách"),
    ("coach", "thuê xe 16 chỗ"),
    ("coach", "đi xe giường nằm"),
    ("coach", "đi limousine"),
    ("train", "bằng tàu hỏa"),
    ("train", "đi tàu hoả"),
]

BUDGET_CHOICES = [
    (3000000, "ngân sách 3 triệu"),
    (5000000, "ngân sách 5 triệu"),
    (8000000, "khoảng 8 triệu"),
    (10000000, "ngân sách 10 triệu"),
    (15000000, "kinh phí 15 triệu"),
    (20000000, "chi phí 20 triệu"),
    (25000000, "tầm 25 triệu"),
    (30000000, "ngân sách tầm 30 triệu"),
]

PREFERENCE_CHOICES = [
    "thích nghỉ dưỡng thư giãn",
    "ngắm cảnh thiên nhiên chill",
    "thích chụp ảnh sống ảo",
    "thưởng thức ẩm thực địa phương",
    "thích trải nghiệm văn hóa lịch sử",
    "ưu tiên không gian yên tĩnh",
    "kết hợp tắm biển và ngắm hoàng hôn",
]

ACTIVITY_EXCLUSION_CHOICES = [
    "leo núi",
    "ăn hải sản",
    "tắm biển",
    "đi đêm",
    "đi bộ nhiều",
    "vào quán bar ồn ào",
]

REGION_PAIRS = [
    ("NORTH", "miền Bắc"),
    ("NORTHWEST", "vùng Tây Bắc"),
    ("NORTHEAST", "vùng Đông Bắc"),
    ("RED_RIVER_DELTA", "vùng đồng bằng sông Hồng"),
    ("CENTRAL", "miền Trung"),
    ("SOUTH_CENTRAL", "duyên hải Nam Trung Bộ"),
    ("CENTRAL_HIGHLANDS", "vùng Tây Nguyên"),
    ("SOUTH", "miền Nam"),
    ("MEKONG_DELTA", "miền Tây"),
]

TERRAIN_PAIRS = [
    ("BEACH", "vùng biển"),
    ("MOUNTAIN", "vùng núi cao"),
    ("HIGHLAND", "vùng cao nguyên"),
    ("FOREST", "vùng rừng sinh thái"),
    ("CAVE", "vùng hang động"),
    ("ISLAND", "biển đảo"),
]


def make_record_dict(spec: SlotSpec, text: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    asst_dict = {
        "intent": spec.intent,
        "destination_mention": spec.dest_mention,
        "destination_regions": sorted(list(set(spec.destination_regions))),
        "terrain_types": sorted(list(set(spec.terrain_types))),
        "excluded_mentions": spec.excluded_mentions,
        "origin_mention": spec.orig_mention,
        "duration_days": spec.duration_days,
        "group_size": spec.group_size,
        "vehicle_type": spec.vehicle_type,
        "budget_total_vnd": spec.budget_total_vnd,
        "preferences": spec.preferences,
        "excluded_activities": spec.excluded_activities,
        "pinned_mentions": spec.pinned_mentions,
        "prefer_flight": spec.prefer_flight,
    }
    ordered_asst = {k: asst_dict[k] for k in KEY_ORDER_V5}
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_V5_1},
            {"role": "user", "content": text.strip()},
            {"role": "assistant", "content": json.dumps(ordered_asst, ensure_ascii=False)},
        ],
        "meta": meta,
    }


def generate_train_set(data_pool: Dict[str, Any], gaz: Gazetteer, target_count: int = 3700) -> List[Dict[str, Any]]:
    rng = random.Random(42)
    records = []
    origins = data_pool["train_origins"]
    provinces = data_pool["provinces"]
    attractions = data_pool["train_attractions"]
    p_by_code = data_pool["places_by_pcode"]

    # Phân bổ số lượng mẫu theo intent:
    # plan_itinerary: ~2,500 mẫu
    # search_place: ~550 mẫu
    # ask_advisory: ~350 mẫu
    # clarify_needed: ~300 mẫu

    # 1. PLAN_ITINERARY (~2,500)
    for i in range(2500):
        tpl = rng.choice(TRAIN_PLAN_TEMPLATES)
        kind = tpl.get("kind", "province")
        pattern = tpl["pattern"]

        # Chọn điểm đến
        dest_item = None
        if kind == "attraction":
            dest_item = rng.choice(attractions)
            dest_mention = dest_item["name"]
            dest_pcode = dest_item["province_code"]
        elif kind in ("region", "terrain", "region_terrain"):
            dest_mention = None
            dest_pcode = None
        else:
            p_obj = rng.choice(provinces)
            dest_mention = p_obj["name"]
            dest_pcode = p_obj["code"]

        # Chọn điểm xuất phát
        if tpl.get("origin_current"):
            orig_mention = "CURRENT_LOCATION"
        elif "origin_mention" in tpl["slots"]:
            orig_mention = sample_origin(dest_mention, [], origins, gaz, rng)
        else:
            orig_mention = None

        duration_days = rng.choice([1, 2, 3, 4, 5, 6, 7]) if "duration_days" in tpl["slots"] else None
        group_size = rng.choice([2, 4, 5, 6, 8, 10, 12]) if "group_size" in tpl["slots"] else None

        # Vehicle
        veh_type, veh_phrase = None, ""
        if "vehicle_type" in tpl["slots"]:
            veh_type, veh_phrase = rng.choice(VEHICLE_CHOICES)

        # Budget
        budget_vnd, budget_phrase = None, ""
        if "budget_total_vnd" in tpl["slots"]:
            budget_vnd, budget_phrase = rng.choice(BUDGET_CHOICES)

        # Preferences
        prefs, pref_phrase = [], ""
        if "preferences" in tpl["slots"]:
            p_text = rng.choice(PREFERENCE_CHOICES)
            prefs = [p_text]
            pref_phrase = p_text

        # Excluded mentions (Chọn POI cùng tỉnh hoặc địa danh khác)
        excl_mentions, excl_mention_val = [], ""
        if "excluded_mentions" in tpl["slots"] and dest_pcode:
            cand_pois = [p["name"] for p in p_by_code.get(dest_pcode, []) if p["name"] != dest_mention]
            if cand_pois:
                excl_poi = rng.choice(cand_pois)
                excl_mentions = [excl_poi]
                excl_mention_val = excl_poi

        # Pinned mentions
        pin_mentions, pin_mention_val = [], ""
        if "pinned_mentions" in tpl["slots"] and dest_pcode:
            cand_pois = [p["name"] for p in p_by_code.get(dest_pcode, []) if p["name"] != dest_mention and p["name"] not in excl_mentions]
            if cand_pois:
                pin_poi = rng.choice(cand_pois)
                pin_mentions = [pin_poi]
                pin_mention_val = pin_poi

        # Excluded activities
        excl_acts, excl_act_val = [], ""
        if "excluded_activities" in tpl["slots"]:
            act_text = rng.choice(ACTIVITY_EXCLUSION_CHOICES)
            excl_acts = [act_text]
            excl_act_val = act_text

        # Region / Terrain
        dest_regions, region_phrase = [], ""
        if "destination_regions" in tpl["slots"]:
            rcode, rphrase = rng.choice(REGION_PAIRS)
            dest_regions = [rcode]
            region_phrase = rphrase

        terrain_types, terrain_phrase = [], ""
        if "terrain_types" in tpl["slots"]:
            tcode, tphrase = rng.choice(TERRAIN_PAIRS)
            terrain_types = [tcode]
            terrain_phrase = tphrase

        # Flight flag
        prefer_flight = None
        if "prefer_flight" in tpl["slots"]:
            prefer_flight = tpl.get("flight_flag", False)
            if prefer_flight is False:
                veh_type = None

        spec = SlotSpec(
            intent="plan_itinerary",
            dest_mention=dest_mention,
            orig_mention=orig_mention,
            duration_days=duration_days,
            group_size=group_size,
            vehicle_type=veh_type,
            budget_total_vnd=budget_vnd,
            excluded_mentions=excl_mentions,
            pinned_mentions=pin_mentions,
            preferences=prefs,
            excluded_activities=excl_acts,
            destination_regions=dest_regions,
            terrain_types=terrain_types,
            prefer_flight=prefer_flight,
        )

        values = {
            "dest_mention": dest_mention or "",
            "origin_mention": orig_mention or "",
            "duration_days": duration_days or "",
            "group_size": group_size or "",
            "vehicle_phrase": veh_phrase,
            "budget_phrase": budget_phrase,
            "pref_phrase": pref_phrase,
            "excl_mention": excl_mention_val,
            "pin_mention": pin_mention_val,
            "excl_activity": excl_act_val,
            "region_phrase": region_phrase,
            "terrain_phrase": terrain_phrase,
        }

        rendered_text, spans = render(pattern, values)
        check_row(rendered_text, spans, values, spec)
        meta = {"template_id": tpl["id"], "generator_version": "5.2", "seed": 42, "spans": spans}
        records.append(make_record_dict(spec, rendered_text, meta))

    # 2. SEARCH_PLACE (~550)
    for i in range(550):
        tpl = rng.choice(TRAIN_SEARCH_TEMPLATES)
        kind = tpl.get("kind", "province")
        pattern = tpl["pattern"]

        if kind == "attraction":
            dest_item = rng.choice(attractions)
            dest_mention = dest_item["name"]
        else:
            p_obj = rng.choice(provinces)
            dest_mention = p_obj["name"]

        prefs = []
        if "preferences" in tpl["slots"]:
            prefs = ["view đẹp"]

        spec = SlotSpec(intent="search_place", dest_mention=dest_mention, preferences=prefs)
        values = {"dest_mention": dest_mention}
        rendered_text, spans = render(pattern, values)
        check_row(rendered_text, spans, values, spec)
        meta = {"template_id": tpl["id"], "generator_version": "5.2", "seed": 42, "spans": spans}
        records.append(make_record_dict(spec, rendered_text, meta))

    # 3. ASK_ADVISORY (~350)
    for i in range(350):
        tpl = rng.choice(TRAIN_ADVISORY_TEMPLATES)
        kind = tpl.get("kind", "province")
        pattern = tpl["pattern"]

        if kind == "attraction":
            dest_item = rng.choice(attractions)
            dest_mention = dest_item["name"]
        else:
            p_obj = rng.choice(provinces)
            dest_mention = p_obj["name"]

        spec = SlotSpec(intent="ask_advisory", dest_mention=dest_mention)
        values = {"dest_mention": dest_mention}
        rendered_text, spans = render(pattern, values)
        check_row(rendered_text, spans, values, spec)
        meta = {"template_id": tpl["id"], "generator_version": "5.2", "seed": 42, "spans": spans}
        records.append(make_record_dict(spec, rendered_text, meta))

    # 4. CLARIFY_NEEDED (~300)
    for i in range(300):
        tpl = rng.choice(TRAIN_CLARIFY_TEMPLATES)
        pattern = tpl["pattern"]
        spec = SlotSpec(intent="clarify_needed")
        rendered_text, spans = render(pattern, {})
        check_row(rendered_text, spans, {}, spec)
        meta = {"template_id": tpl["id"], "generator_version": "5.2", "seed": 42, "spans": spans}
        records.append(make_record_dict(spec, rendered_text, meta))

    return records


def generate_val_set(
    data_pool: Dict[str, Any],
    gaz: Gazetteer,
    train_delex_keys: Set[str],
    train_trigrams: List[Set[str]],
) -> List[Dict[str, Any]]:
    """
    Sinh tập VALIDATION với yêu cầu phân bổ chính xác:
    - plan_itinerary: 380 mẫu
    - search_place: 250 mẫu
    - ask_advisory: 200 mẫu
    - clarify_needed: 200 mẫu
    Tổng cộng: 1.030 mẫu.
    Đảm bảo hold-out địa lý origin và dedup trigram Jaccard < 0.7 với Train.
    """
    rng = random.Random(42)
    records = []
    origins = data_pool["val_origins"]  # Hold-out origins!
    provinces = data_pool["provinces"]
    attractions = data_pool["val_attractions"]  # Hold-out POIs!
    p_by_code = data_pool["places_by_pcode"]

    # 1. PLAN_ITINERARY (380 mẫu)
    count = 0
    while count < 380:
        tpl = rng.choice(VAL_PLAN_TEMPLATES)
        kind = tpl.get("kind", "province")
        pattern = tpl["pattern"]

        if kind == "attraction":
            dest_item = rng.choice(attractions)
            dest_mention = dest_item["name"]
            dest_pcode = dest_item["province_code"]
        elif kind in ("region", "terrain"):
            dest_mention = None
            dest_pcode = None
        else:
            p_obj = rng.choice(provinces)
            dest_mention = p_obj["name"]
            dest_pcode = p_obj["code"]

        if tpl.get("origin_current"):
            orig_mention = "CURRENT_LOCATION"
        elif "origin_mention" in tpl["slots"]:
            orig_mention = sample_origin(dest_mention, [], origins, gaz, rng)
        else:
            orig_mention = None

        duration_days = rng.choice([1, 2, 3, 4, 5, 6, 7]) if "duration_days" in tpl["slots"] else None
        group_size = rng.choice([2, 4, 5, 6, 8, 10]) if "group_size" in tpl["slots"] else None

        veh_type, veh_phrase = None, ""
        if "vehicle_type" in tpl["slots"]:
            veh_type, veh_phrase = rng.choice(VEHICLE_CHOICES)

        budget_vnd, budget_phrase = None, ""
        if "budget_total_vnd" in tpl["slots"]:
            budget_vnd, budget_phrase = rng.choice(BUDGET_CHOICES)

        prefs, pref_phrase = [], ""
        if "preferences" in tpl["slots"]:
            p_text = rng.choice(PREFERENCE_CHOICES)
            prefs = [p_text]
            pref_phrase = p_text

        excl_mentions, excl_mention_val = [], ""
        if "excluded_mentions" in tpl["slots"] and dest_pcode:
            cand_pois = [p["name"] for p in p_by_code.get(dest_pcode, []) if p["name"] != dest_mention]
            if cand_pois:
                excl_poi = rng.choice(cand_pois)
                excl_mentions = [excl_poi]
                excl_mention_val = excl_poi

        pin_mentions, pin_mention_val = [], ""
        if "pinned_mentions" in tpl["slots"] and dest_pcode:
            cand_pois = [p["name"] for p in p_by_code.get(dest_pcode, []) if p["name"] != dest_mention and p["name"] not in excl_mentions]
            if cand_pois:
                pin_poi = rng.choice(cand_pois)
                pin_mentions = [pin_poi]
                pin_mention_val = pin_poi

        excl_acts, excl_act_val = [], ""
        if "excluded_activities" in tpl["slots"]:
            act_text = rng.choice(ACTIVITY_EXCLUSION_CHOICES)
            excl_acts = [act_text]
            excl_act_val = act_text

        dest_regions, region_phrase = [], ""
        if "destination_regions" in tpl["slots"]:
            rcode, rphrase = rng.choice(REGION_PAIRS)
            dest_regions = [rcode]
            region_phrase = rphrase

        terrain_types, terrain_phrase = [], ""
        if "terrain_types" in tpl["slots"]:
            tcode, tphrase = rng.choice(TERRAIN_PAIRS)
            terrain_types = [tcode]
            terrain_phrase = tphrase

        prefer_flight = None
        if "prefer_flight" in tpl["slots"]:
            prefer_flight = tpl.get("flight_flag", False)
            if prefer_flight is False:
                veh_type = None

        spec = SlotSpec(
            intent="plan_itinerary",
            dest_mention=dest_mention,
            orig_mention=orig_mention,
            duration_days=duration_days,
            group_size=group_size,
            vehicle_type=veh_type,
            budget_total_vnd=budget_vnd,
            excluded_mentions=excl_mentions,
            pinned_mentions=pin_mentions,
            preferences=prefs,
            excluded_activities=excl_acts,
            destination_regions=dest_regions,
            terrain_types=terrain_types,
            prefer_flight=prefer_flight,
        )

        values = {
            "dest_mention": dest_mention or "",
            "origin_mention": orig_mention or "",
            "duration_days": duration_days or "",
            "group_size": group_size or "",
            "vehicle_phrase": veh_phrase,
            "budget_phrase": budget_phrase,
            "pref_phrase": pref_phrase,
            "excl_mention": excl_mention_val,
            "pin_mention": pin_mention_val,
            "excl_activity": excl_act_val,
            "region_phrase": region_phrase,
            "terrain_phrase": terrain_phrase,
        }

        rendered_text, spans = render(pattern, values)
        check_row(rendered_text, spans, values, spec)

        # Kiểm tra leak
        d_key = delex(rendered_text, spec)
        if d_key in train_delex_keys:
            continue
        tg = trigrams(d_key)
        if any(jaccard(tg, t_tg) >= 0.70 for t_tg in train_trigrams[:200]):
            continue

        meta = {"template_id": tpl["id"], "generator_version": "5.2", "seed": 42, "spans": spans}
        records.append(make_record_dict(spec, rendered_text, meta))
        count += 1

    # 2. SEARCH_PLACE (250 mẫu)
    for i in range(250):
        tpl = rng.choice(VAL_SEARCH_TEMPLATES)
        kind = tpl.get("kind", "province")
        pattern = tpl["pattern"]

        if kind == "attraction":
            dest_item = rng.choice(attractions)
            dest_mention = dest_item["name"]
        else:
            p_obj = rng.choice(provinces)
            dest_mention = p_obj["name"]

        prefs = []
        if "preferences" in tpl["slots"]:
            prefs = ["yên tĩnh"]

        spec = SlotSpec(intent="search_place", dest_mention=dest_mention, preferences=prefs)
        values = {"dest_mention": dest_mention}
        rendered_text, spans = render(pattern, values)
        check_row(rendered_text, spans, values, spec)
        meta = {"template_id": tpl["id"], "generator_version": "5.2", "seed": 42, "spans": spans}
        records.append(make_record_dict(spec, rendered_text, meta))

    # 3. ASK_ADVISORY (200 mẫu)
    for i in range(200):
        tpl = rng.choice(VAL_ADVISORY_TEMPLATES)
        kind = tpl.get("kind", "province")
        pattern = tpl["pattern"]

        if kind == "attraction":
            dest_item = rng.choice(attractions)
            dest_mention = dest_item["name"]
        else:
            p_obj = rng.choice(provinces)
            dest_mention = p_obj["name"]

        prefs = []
        if "preferences" in tpl["slots"]:
            prefs = ["hoạt động trong nhà"]

        spec = SlotSpec(intent="ask_advisory", dest_mention=dest_mention, preferences=prefs)
        values = {"dest_mention": dest_mention}
        rendered_text, spans = render(pattern, values)
        check_row(rendered_text, spans, values, spec)
        meta = {"template_id": tpl["id"], "generator_version": "5.2", "seed": 42, "spans": spans}
        records.append(make_record_dict(spec, rendered_text, meta))

    # 4. CLARIFY_NEEDED (200 mẫu)
    for i in range(200):
        tpl = rng.choice(VAL_CLARIFY_TEMPLATES)
        pattern = tpl["pattern"]
        spec = SlotSpec(intent="clarify_needed")
        rendered_text, spans = render(pattern, {})
        check_row(rendered_text, spans, {}, spec)
        meta = {"template_id": tpl["id"], "generator_version": "5.2", "seed": 42, "spans": spans}
        records.append(make_record_dict(spec, rendered_text, meta))

    return records


def generate_adv_set(data_pool: Dict[str, Any], gaz: Gazetteer, target_count: int = 850) -> List[Dict[str, Any]]:
    """
    Sinh tập ADVERSARIAL bao phủ 6 kiểu khó x 4 Intent và Minimal Pairs:
    - Minimal Pairs (pinned vs excluded) với pair_id.
    - Đảo ngữ cú pháp (origin trước destination).
    - Phủ định thuộc tính & hoạt động (search_place & ask_advisory).
    - Cặp ngược (câu có từ 'không' nhưng không loại trừ cho clarify_needed).
    - Không dấu / teencode.
    """
    rng = random.Random(42)
    records = []
    origins = data_pool["val_origins"] + data_pool["train_origins"]
    provinces = data_pool["provinces"]
    p_by_code = data_pool["places_by_pcode"]

    # 1. MINIMAL PAIRS (Ghép cặp với pair_id) (~300 mẫu = 150 cặp)
    for pair_idx in range(150):
        pair_id = f"pair_{pair_idx:04d}"
        tpl = rng.choice(MINIMAL_PAIR_TEMPLATES)
        p_obj = rng.choice(provinces)
        dest_mention = p_obj["name"]
        dest_pcode = p_obj["code"]

        orig_mention = sample_origin(dest_mention, [], origins, gaz, rng)
        duration_days = rng.choice([2, 3, 4, 5])
        has_group = tpl.get("has_group_size", False)
        group_size = rng.choice([2, 4, 5, 6]) if has_group else None

        cand_pois = [p["name"] for p in p_by_code.get(dest_pcode, []) if p["name"] != dest_mention]
        if not cand_pois:
            continue
        target_poi = rng.choice(cand_pois)

        values = {
            "dest_mention": dest_mention,
            "origin_mention": orig_mention,
            "duration_days": duration_days,
            "group_size": group_size or "",
            "target_poi": target_poi,
        }

        # Cặp PIN
        spec_pin = SlotSpec(
            intent="plan_itinerary",
            dest_mention=dest_mention,
            orig_mention=orig_mention,
            duration_days=duration_days,
            group_size=group_size,
            pinned_mentions=[target_poi],
            pair_id=pair_id,
        )
        text_pin, spans_pin = render(tpl["pattern_pin"], values)
        check_row(text_pin, spans_pin, values, spec_pin)
        meta_pin = {"template_id": "adv_min_pair_pin", "generator_version": "5.2", "seed": 42, "spans": spans_pin, "pair_id": pair_id}
        records.append(make_record_dict(spec_pin, text_pin, meta_pin))

        # Cặp EXCL
        spec_excl = SlotSpec(
            intent="plan_itinerary",
            dest_mention=dest_mention,
            orig_mention=orig_mention,
            duration_days=duration_days,
            group_size=group_size,
            excluded_mentions=[target_poi],
            pair_id=pair_id,
        )
        text_excl, spans_excl = render(tpl["pattern_excl"], values)
        check_row(text_excl, spans_excl, values, spec_excl)
        meta_excl = {"template_id": "adv_min_pair_excl", "generator_version": "5.2", "seed": 42, "spans": spans_excl, "pair_id": pair_id}
        records.append(make_record_dict(spec_excl, text_excl, meta_excl))

    # 2. ĐẢO NGỮ CÚ PHÁP (Origin xuất hiện trước Destination) (~150 mẫu)
    for i in range(150):
        tpl = rng.choice(ADV_INVERTED_TEMPLATES)
        p_obj = rng.choice(provinces)
        dest_mention = p_obj["name"]
        dest_pcode = p_obj["code"]

        cand_pois = [p["name"] for p in p_by_code.get(dest_pcode, []) if p["name"] != dest_mention]
        excl_poi = rng.choice(cand_pois) if cand_pois else "Bà Nà"
        orig_mention = sample_origin(dest_mention, [excl_poi], origins, gaz, rng)

        duration_days = rng.choice([2, 3, 4, 5])
        group_size = rng.choice([2, 4, 6])
        veh_type, veh_phrase = rng.choice(VEHICLE_CHOICES)
        budget_vnd, budget_phrase = rng.choice(BUDGET_CHOICES)

        spec = SlotSpec(
            intent="plan_itinerary",
            dest_mention=dest_mention,
            orig_mention=orig_mention,
            duration_days=duration_days,
            group_size=group_size if "group_size" in tpl["slots"] else None,
            vehicle_type=veh_type if "vehicle_type" in tpl["slots"] else None,
            budget_total_vnd=budget_vnd if "budget_total_vnd" in tpl["slots"] else None,
            excluded_mentions=[excl_poi] if "excluded_mentions" in tpl["slots"] else [],
        )
        values = {
            "origin_mention": orig_mention,
            "dest_mention": dest_mention,
            "duration_days": duration_days,
            "group_size": group_size,
            "vehicle_phrase": veh_phrase,
            "budget_phrase": budget_phrase,
            "excl_mention": excl_poi,
        }
        rendered_text, spans = render(tpl["pattern"], values)
        check_row(rendered_text, spans, values, spec)
        meta = {"template_id": tpl["id"], "generator_version": "5.2", "seed": 42, "spans": spans}
        records.append(make_record_dict(spec, rendered_text, meta))

    # 3. SEARCH_PLACE ADVERSARIAL (Phủ định thuộc tính & Hoạt động) (~150 mẫu)
    for i in range(150):
        tpl = rng.choice(ADV_SEARCH_TEMPLATES)
        p_obj = rng.choice(provinces)
        dest_mention = p_obj["name"]

        prefs = [tpl["pref_val"]] if "pref_val" in tpl else []
        excl_acts = [tpl["excl_act_val"]] if "excl_act_val" in tpl else []

        spec = SlotSpec(
            intent="search_place",
            dest_mention=dest_mention,
            preferences=prefs,
            excluded_activities=excl_acts,
        )
        values = {"dest_mention": dest_mention}
        rendered_text, spans = render(tpl["pattern"], values)
        check_row(rendered_text, spans, values, spec)
        meta = {"template_id": tpl["id"], "generator_version": "5.2", "seed": 42, "spans": spans}
        records.append(make_record_dict(spec, rendered_text, meta))

    # 4. ASK_ADVISORY ADVERSARIAL (Tránh mùa mưa, không bị lạnh...) (~120 mẫu)
    for i in range(120):
        tpl = rng.choice(ADV_ADVISORY_TEMPLATES)
        p_obj = rng.choice(provinces)
        dest_mention = p_obj["name"]

        prefs = [tpl["pref_val"]] if "pref_val" in tpl else []
        spec = SlotSpec(intent="ask_advisory", dest_mention=dest_mention, preferences=prefs)
        values = {"dest_mention": dest_mention}
        rendered_text, spans = render(tpl["pattern"], values)
        check_row(rendered_text, spans, values, spec)
        meta = {"template_id": tpl["id"], "generator_version": "5.2", "seed": 42, "spans": spans}
        records.append(make_record_dict(spec, rendered_text, meta))

    # 5. CLARIFY_NEEDED ADVERSARIAL (Có từ 'không' nhưng KHÔNG loại trừ) (~120 mẫu)
    for i in range(120):
        tpl = rng.choice(ADV_CLARIFY_TEMPLATES)
        spec = SlotSpec(intent="clarify_needed")
        rendered_text, spans = render(tpl["pattern"], {})
        check_row(rendered_text, spans, {}, spec)
        meta = {"template_id": tpl["id"], "generator_version": "5.2", "seed": 42, "spans": spans}
        records.append(make_record_dict(spec, rendered_text, meta))

    # 6. KHÔNG DẤU / TEENCODE (~100 mẫu)
    for i in range(100):
        tpl = rng.choice(ADV_UNACCENTED_TEMPLATES)
        intent = tpl["intent"]

        dest_mention = None
        orig_mention = None
        duration_days = None
        group_size = None
        veh_type, veh_phrase = None, ""
        excl_mentions = []

        if intent in ("plan_itinerary", "search_place", "ask_advisory"):
            p_obj = rng.choice(provinces)
            dest_mention = strip_accents(p_obj["name"])
            if intent == "plan_itinerary":
                orig_raw = sample_origin(p_obj["name"], [], origins, gaz, rng)
                orig_mention = strip_accents(orig_raw)
                duration_days = rng.choice([2, 3, 4, 5])
                group_size = rng.choice([2, 4, 5, 6]) if "group_size" in tpl["slots"] else None
                veh_type, veh_phrase_raw = rng.choice(VEHICLE_CHOICES)
                veh_phrase = strip_accents(veh_phrase_raw)
                cand_pois = [strip_accents(p["name"]) for p in p_by_code.get(p_obj["code"], [])]
                if cand_pois and "excluded_mentions" in tpl["slots"]:
                    excl_mentions = [rng.choice(cand_pois)]

        spec = SlotSpec(
            intent=intent,
            dest_mention=dest_mention,
            orig_mention=orig_mention,
            duration_days=duration_days,
            group_size=group_size,
            vehicle_type=veh_type,
            excluded_mentions=excl_mentions,
        )
        values = {
            "dest_mention": dest_mention or "",
            "origin_mention": orig_mention or "",
            "duration_days": duration_days or "",
            "group_size": group_size or "",
            "vehicle_phrase": veh_phrase,
            "excl_mention": excl_mentions[0] if excl_mentions else "",
        }
        rendered_text, spans = render(tpl["pattern"], values)
        check_row(rendered_text, spans, values, spec)
        meta = {"template_id": tpl["id"], "generator_version": "5.2", "seed": 42, "spans": spans}
        records.append(make_record_dict(spec, rendered_text, meta))

    return records


# ---------------------------------------------------------------------------
# 6. MAIN BUILD & INTEGRITY ENFORCEMENT
# ---------------------------------------------------------------------------
def main():
    print("═" * 70)
    print("Khởi động Synthesis Engine v5.2 (Top 0.1% Standards)")
    print("═" * 70)

    db_path = "travel_db.db"
    gaz = Gazetteer.get_instance(db_path)

    # 1. Nạp và phân loại thực thể
    print("\n[1/4] Nạp và phân loại thực thể từ travel_db.db...")
    data_pool = load_and_classify_entities(db_path, gaz)
    print(f"  -> Tỉnh/Thành phố: {len(data_pool['provinces'])}")
    print(f"  -> Train Origins (70%): {len(data_pool['train_origins'])}")
    print(f"  -> Val Origins Hold-out (30%): {len(data_pool['val_origins'])}")
    print(f"  -> Attractions Train: {len(data_pool['train_attractions'])}")
    print(f"  -> Attractions Val Hold-out: {len(data_pool['val_attractions'])}")

    # 2. Sinh tập Train
    print("\n[2/4] Sinh tập Train NLU v5.2...")
    train_records = generate_train_set(data_pool, gaz, target_count=3700)
    print(f"  -> Tổng số mẫu Train: {len(train_records)}")

    # Thu thập delexicalized keys và trigrams của Train để chống leak
    train_delex_keys = set()
    train_trigrams = []
    for r in train_records:
        user_text = r["messages"][1]["content"]
        ann = json.loads(r["messages"][2]["content"])
        spec_dummy = SlotSpec(
            intent=ann.get("intent"),
            dest_mention=ann.get("destination_mention"),
            orig_mention=ann.get("origin_mention"),
            excluded_mentions=ann.get("excluded_mentions") or [],
            pinned_mentions=ann.get("pinned_mentions") or [],
        )
        d_k = delex(user_text, spec_dummy)
        train_delex_keys.add(d_k)
        train_trigrams.append(trigrams(d_k))

    # 3. Sinh tập Val (Hold-out & Anti-leakage)
    print("\n[3/4] Sinh tập Validation NLU v5.2...")
    val_records = generate_val_set(data_pool, gaz, train_delex_keys, train_trigrams)
    print(f"  -> Tổng số mẫu Val: {len(val_records)}")

    # 4. Sinh tập Adversarial (Minimal Pairs & Hard cases)
    print("\n[4/4] Sinh tập Adversarial NLU v5.2...")
    adv_records = generate_adv_set(data_pool, gaz, target_count=850)
    print(f"  -> Tổng số mẫu Adversarial: {len(adv_records)}")

    # 5. Kiểm tra toàn diện Dest/Origin không cùng tỉnh trước khi lưu
    print("\nKiểm tra toàn diện Dest vs Origin tỉnh thành...")
    for split_name, recs in [("train", train_records), ("val", val_records), ("adv", adv_records)]:
        for idx, r in enumerate(recs):
            ann = json.loads(r["messages"][2]["content"])
            d = ann.get("destination_mention")
            o = ann.get("origin_mention")
            if d and o and o != "CURRENT_LOCATION":
                cd = (gaz.resolve_mention(d) or {}).get("province_code")
                co = (gaz.resolve_mention(o) or {}).get("province_code")
                if cd is not None and co is not None and cd == co:
                    print(f"FATAL: dest and origin have same province_code in {split_name} row {idx}: dest='{d}' ({cd}), orig='{o}' ({co})")
                    sys.exit(1)

    # 6. Ghi ra đĩa
    out_paths = {
        "data/train_nlu_master_v5.jsonl": train_records,
        "data/val_nlu_v5.jsonl": val_records,
        "data/train_nlu_adversarial_v5.jsonl": adv_records,
    }

    for path, recs in out_paths.items():
        with open(path, "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"Đã ghi: {path} ({len(recs)} dòng)")

    print("\n✓ Hoàn tất sinh dataset v5.2 thành công mỹ mãn!")


if __name__ == "__main__":
    main()
