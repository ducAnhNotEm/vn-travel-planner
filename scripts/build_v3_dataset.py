#!/usr/bin/env python3
"""
build_v3_dataset.py
-------------------
1. Migrate train_nlu_master.jsonl (schema v2, 11 fields) -> schema v3 (15 fields).
2. Sinh 29 mẫu đối kháng (vùng miền / địa hình trừu tượng + loại trừ địa danh).
3. Validate toàn bộ bằng các invariant của Manifesto (+ Rule 8-10 mới).
4. Ghi:  train_nlu_adversarial_v3.jsonl   (chỉ 29 mẫu mới)
         train_nlu_master_v3.jsonl        (937 mẫu đã migrate + 29 mẫu mới)

Cách dùng:
    python build_v3_dataset.py --master data/train_nlu_master.jsonl --out data/
    python build_v3_dataset.py --master data/train_nlu_master.jsonl --out data/ --remap-34   # (tuỳ chọn)
"""
import argparse
import collections
import json
import re
import sys
import unicodedata
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. SCHEMA v3
# ---------------------------------------------------------------------------
KEY_ORDER = [
    "intent", "destination",
    "destination_regions", "terrain_types", "excluded_destinations", "excluded_places",   # <- MỚI
    "origin", "duration_days", "group_size", "vehicle_type", "budget_total_vnd",
    "preferences", "excluded_activities", "hard_pinned_locations", "prefer_flight",
]
NEW_FIELDS = ["destination_regions", "terrain_types", "excluded_destinations", "excluded_places"]

INTENTS = {"plan_itinerary", "search_place", "ask_advisory", "clarify_needed"}
REGIONS = {"NORTH", "NORTHWEST", "NORTHEAST", "RED_RIVER_DELTA", "NORTH_CENTRAL", "CENTRAL",
           "SOUTH_CENTRAL", "CENTRAL_HIGHLANDS", "SOUTH", "SOUTHEAST", "MEKONG_DELTA"}
TERRAINS = {"BEACH", "ISLAND", "MOUNTAIN", "HIGHLAND", "FOREST", "CAVE", "RIVER"}

# 34 tỉnh/thành sau sắp xếp (PROJECT.md §1)
P34 = set("""Hà Nội|Huế|Lai Châu|Điện Biên|Sơn La|Lạng Sơn|Quảng Ninh|Thanh Hóa|Nghệ An|Hà Tĩnh|Cao Bằng|
Tuyên Quang|Lào Cai|Thái Nguyên|Phú Thọ|Bắc Ninh|Hưng Yên|Hải Phòng|Ninh Bình|Quảng Trị|Đà Nẵng|
Quảng Ngãi|Gia Lai|Khánh Hòa|Lâm Đồng|Đắk Lắk|Hồ Chí Minh|Đồng Nai|Tây Ninh|Cần Thơ|Vĩnh Long|
Đồng Tháp|Cà Mau|An Giang""".replace("\n", "").split("|"))

REMAP_34 = {"Quảng Nam": "Đà Nẵng", "Bà Rịa - Vũng Tàu": "Hồ Chí Minh",
            "Hà Giang": "Tuyên Quang", "Kiên Giang": "An Giang"}

SYSTEM_V3 = (
    "Bạn là NLU Engine chuyên dụng cho hệ thống Travel AI Việt Nam.\n"
    "Nhiệm vụ: Phân tích yêu cầu của người dùng và trích xuất thành định dạng JSON chuẩn.\n"
    "Quy tắc:\n"
    "1. Chỉ trả về duy nhất chuỗi JSON hợp lệ bắt đầu bằng '{' và kết thúc bằng '}', không kèm markdown hay lời dẫn.\n"
    "2. Xác định đúng intent trong các loại: 'plan_itinerary', 'search_place', 'ask_advisory', 'clarify_needed'.\n"
    "3. Nếu người dùng không đề cập thông tin nào, trường tương ứng BẮT BUỘC để null (hoặc [] với mảng). "
    "Tuyệt đối không tự suy diễn số liệu.\n"
    "4. 'destination' CHỈ điền khi người dùng nêu rõ một tỉnh/thành/địa danh cụ thể (chuẩn hóa về tên tỉnh/thành). "
    "Nếu người dùng chỉ nói vùng miền hoặc loại địa hình (vd: 'phía Bắc', 'đi biển', 'núi'), để destination = null và điền "
    "'destination_regions' / 'terrain_types'. TUYỆT ĐỐI không tự liệt kê tỉnh thay cho vùng miền.\n"
    "5. 'destination_regions' chỉ nhận: NORTH, NORTHWEST, NORTHEAST, RED_RIVER_DELTA, NORTH_CENTRAL, CENTRAL, "
    "SOUTH_CENTRAL, CENTRAL_HIGHLANDS, SOUTH, SOUTHEAST, MEKONG_DELTA. 'terrain_types' chỉ nhận: BEACH, ISLAND, "
    "MOUNTAIN, HIGHLAND, FOREST, CAVE, RIVER (xếp theo bảng chữ cái). Khi đã có destination cụ thể thì cả hai để [] "
    "và các từ như 'biển', 'núi' chỉ ghi vào preferences.\n"
    "6. Địa danh người dùng muốn LOẠI TRỪ (trừ, ngoại trừ, không đi, tránh, bỏ, chán, đi rồi, khỏi...) đưa vào "
    "'excluded_destinations' (cấp tỉnh/thành) hoặc 'excluded_places' (địa danh nhỏ hơn tỉnh). Địa danh bị loại trừ "
    "KHÔNG BAO GIỜ được đưa vào destination, hard_pinned_locations hay preferences. Điểm xuất phát (origin) độc lập "
    "với danh sách loại trừ."
)


def row(user, **kw):
    """Tạo 1 mẫu: mọi trường mặc định null/[]; chỉ ghi đè trường được nêu."""
    out = {
        "intent": "plan_itinerary", "destination": None,
        "destination_regions": [], "terrain_types": [], "excluded_destinations": [], "excluded_places": [],
        "origin": None, "duration_days": None, "group_size": None, "vehicle_type": None,
        "budget_total_vnd": None, "preferences": [], "excluded_activities": [],
        "hard_pinned_locations": [], "prefer_flight": None,
    }
    out.update(kw)
    return user, out


HN = "Hà Nội"
SAMPLES = [
    # ---- NHÓM A: vùng miền / địa hình trừu tượng (Dạng 1) -------------------------------------------
    row("Tạo lịch trình du lịch núi phía Bắc cho 2 người xuất phát từ HN",
        destination_regions=["NORTH"], terrain_types=["MOUNTAIN"], origin=HN, group_size=2),
    row("Lên kế hoạch đi biển miền Trung 4 ngày 3 đêm cho 4 người, từ Hà Nội",
        destination_regions=["CENTRAL"], terrain_types=["BEACH"], origin=HN, duration_days=4, group_size=4),
    row("Muốn lên Tây Bắc săn mây 3 ngày, đi xe máy từ HN",   # 'săn mây' là sở thích, KHÔNG suy ra MOUNTAIN
        destination_regions=["NORTHWEST"], origin=HN, duration_days=3, vehicle_type="motorbike",
        preferences=["săn mây"]),
    row("Gợi ý lịch trình cao nguyên Tây Nguyên 5 ngày cho nhóm 6 người, đi ô tô từ TP.HCM",
        destination_regions=["CENTRAL_HIGHLANDS"], terrain_types=["HIGHLAND"], origin="TP.HCM",
        duration_days=5, group_size=6, vehicle_type="car"),
    row("Cả nhà 5 người từ Cần Thơ muốn đi biển đảo phía Nam 3 ngày 2 đêm",
        destination_regions=["SOUTH"], terrain_types=["BEACH", "ISLAND"], origin="Cần Thơ",
        duration_days=3, group_size=5),
    row("Cho mình lịch trình đi biển 4 ngày, 7 người, xuất phát từ đây",   # chỉ địa hình, không vùng miền
        terrain_types=["BEACH"], origin="CURRENT_LOCATION", duration_days=4, group_size=7),
    row("Cuối tuần này 2 vợ chồng muốn đi rừng núi Đông Bắc bằng xe máy, xuất phát từ Hà Nội",
        destination_regions=["NORTHEAST"], terrain_types=["FOREST", "MOUNTAIN"], origin=HN,
        group_size=2, vehicle_type="motorbike"),                           # 'cuối tuần' != số ngày -> null
    row("Mình muốn đi du lịch miền Tây sông nước 3 ngày, 4 người, từ TP.HCM",
        destination_regions=["MEKONG_DELTA"], terrain_types=["RIVER"], origin="TP.HCM",
        duration_days=3, group_size=4),
    row("Thiết kế chuyến khám phá hang động phía Bắc 3 ngày, đi 3 người từ Hải Phòng",
        destination_regions=["NORTH"], terrain_types=["CAVE"], origin="Hải Phòng", duration_days=3, group_size=3),
    row("Gia đình 4 người từ Hà Nội, muốn bay đi nghỉ dưỡng ở miền Trung",   # prefer_flight=true, vehicle=null
        destination_regions=["CENTRAL"], origin=HN, group_size=4, preferences=["nghỉ dưỡng"], prefer_flight=True),
    # ---- NHÓM B: cặp tối thiểu (không có loại trừ) ----------------------------------------------------
    row("Đi biển các tỉnh phía Bắc 2 ngày 1 đêm, 2 người, xuất phát từ Hà Nội",
        destination_regions=["NORTH"], terrain_types=["BEACH"], origin=HN, duration_days=2, group_size=2),
    row("Đi biển Hải Phòng 3 ngày, 3 người, xuất phát từ Hà Nội",           # có destination -> terrain=[]
        destination="Hải Phòng", origin=HN, duration_days=3, group_size=3, preferences=["đi biển"]),
    row("Đi biển các tỉnh phía Bắc 2 ngày, 3 người, xuất phát từ Hải Phòng",   # origin KHÔNG tự thành loại trừ
        destination_regions=["NORTH"], terrain_types=["BEACH"], origin="Hải Phòng", duration_days=2, group_size=3),
    # ---- NHÓM C: loại trừ địa danh (Dạng 2) -----------------------------------------------------------
    row("Tôi muốn đi biển các tỉnh phía Bắc đi 3 người xuất phát từ Hà Nội trừ Hải Phòng",
        destination_regions=["NORTH"], terrain_types=["BEACH"], excluded_destinations=["Hải Phòng"],
        origin=HN, group_size=3),
    row("Trừ Hải Phòng ra, tôi muốn đi biển phía Bắc, đi 3 người từ Hà Nội",   # đảo ngữ
        destination_regions=["NORTH"], terrain_types=["BEACH"], excluded_destinations=["Hải Phòng"],
        origin=HN, group_size=3),
    row("Đi biển phía Bắc 3 ngày từ Hà Nội, 4 người, ngoại trừ Quảng Ninh",
        destination_regions=["NORTH"], terrain_types=["BEACH"], excluded_destinations=["Quảng Ninh"],
        origin=HN, duration_days=3, group_size=4),
    row("Từ Hà Nội, 2 người muốn đi biển miền Trung 4 ngày, trừ Đà Nẵng và Huế",
        destination_regions=["CENTRAL"], terrain_types=["BEACH"], excluded_destinations=["Đà Nẵng", "Huế"],
        origin=HN, duration_days=4, group_size=2),
    row("Xuất phát từ Hải Phòng, 3 người muốn đi biển phía Bắc, trừ Hải Phòng",   # origin == excluded
        destination_regions=["NORTH"], terrain_types=["BEACH"], excluded_destinations=["Hải Phòng"],
        origin="Hải Phòng", group_size=3),
    row("2 người từ Hà Nội đi núi Tây Bắc 3 ngày, không đi Sa Pa",            # địa danh dưới cấp tỉnh
        destination_regions=["NORTHWEST"], terrain_types=["MOUNTAIN"], excluded_places=["Sa Pa"],
        origin=HN, duration_days=3, group_size=2),
    row("Đi biển phía Bắc, bỏ Hạ Long ra nhé, 3 người từ Hà Nội",
        destination_regions=["NORTH"], terrain_types=["BEACH"], excluded_places=["Hạ Long"],
        origin=HN, group_size=3),
    row("Cả nhà 5 người từ Đà Nẵng đi biển miền Nam, đừng chọn Vũng Tàu",
        destination_regions=["SOUTH"], terrain_types=["BEACH"], excluded_places=["Vũng Tàu"],
        origin="Đà Nẵng", group_size=5),
    row("Chán Đà Lạt rồi, lên lịch trình cao nguyên Tây Nguyên chỗ khác 4 ngày cho 2 người, từ TP.HCM",  # phủ định ngầm
        destination_regions=["CENTRAL_HIGHLANDS"], terrain_types=["HIGHLAND"], excluded_places=["Đà Lạt"],
        origin="TP.HCM", duration_days=4, group_size=2),
    row("Đi núi phía Bắc 3 ngày cho 2 người từ Hà Nội, Lào Cai thì đi rồi nên thôi",   # phủ định ngầm 'đi rồi'
        destination_regions=["NORTH"], terrain_types=["MOUNTAIN"], excluded_destinations=["Lào Cai"],
        origin=HN, duration_days=3, group_size=2),
    row("3 người từ Hà Nội đi biển phía Bắc bằng ô tô, tránh Hải Phòng với Quảng Ninh nhé",
        destination_regions=["NORTH"], terrain_types=["BEACH"],
        excluded_destinations=["Hải Phòng", "Quảng Ninh"], origin=HN, group_size=3, vehicle_type="car"),
    # ---- NHÓM D: có destination + loại trừ (chống rò rỉ vào hard_pinned / destination) ----------------
    row("Đi Quảng Ninh 3 ngày 2 đêm, 4 người từ Hà Nội, không đi Hạ Long",
        destination="Quảng Ninh", excluded_places=["Hạ Long"], origin=HN, duration_days=3, group_size=4),
    row("Đi Đà Nẵng 3 ngày từ Hà Nội cho 2 người, không ghé Bà Nà Hills",
        destination="Đà Nẵng", excluded_places=["Bà Nà Hills"], origin=HN, duration_days=3, group_size=2),
    row("3 người từ Hà Nội đi biển phía Bắc, không ăn hải sản, trừ Cát Bà",   # loại trừ hoạt động != loại trừ địa danh
        destination_regions=["NORTH"], terrain_types=["BEACH"], excluded_places=["Cát Bà"],
        excluded_activities=["không ăn hải sản"], origin=HN, group_size=3),
    # ---- NHÓM E: robustness văn phong (không dấu / khẩu ngữ) -------------------------------------------
    row("di bien cac tinh phia bac 3 nguoi xuat phat tu HN tru Hai Phong",
        destination_regions=["NORTH"], terrain_types=["BEACH"], excluded_destinations=["Hải Phòng"],
        origin=HN, group_size=3),
    row("Alo cho mình lên lịch đi chơi biển mấy tỉnh phía Bắc với, nhà mình 3 người đi từ Hà Nội, Hải Phòng thì khỏi nhé",
        destination_regions=["NORTH"], terrain_types=["BEACH"], excluded_destinations=["Hải Phòng"],
        origin=HN, group_size=3),
]


# ---------------------------------------------------------------------------
# 2. MIGRATION
# ---------------------------------------------------------------------------
def ordered(d):
    return {k: d[k] for k in KEY_ORDER}


def migrate_assistant(old, user_text, remap):
    new = dict(old)
    for f in NEW_FIELDS:
        new.setdefault(f, [])
    if remap:
        if new["destination"] in REMAP_34:
            new["destination"] = REMAP_34[new["destination"]]
        if "Phú Quốc" in user_text and new["destination"] == "Cà Mau":   # nhãn sai trong v2
            new["destination"] = "An Giang"
    return ordered(new)


def make_msg(user, assistant):
    return {"messages": [
        {"role": "system", "content": SYSTEM_V3},
        {"role": "user", "content": user},
        {"role": "assistant", "content": json.dumps(assistant, ensure_ascii=False)},
    ]}


# ---------------------------------------------------------------------------
# 3. VALIDATION
# ---------------------------------------------------------------------------
def fold(s):
    s = unicodedata.normalize("NFD", s.lower().replace("đ", "d"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


FLIGHT_RE = re.compile(r"(\bbay\b|máy bay|vé|hàng không)", re.I)


def validate(user, a, strict_sources=True):
    """Trả về (errors, warnings)."""
    err, warn = [], []
    if list(a.keys()) != KEY_ORDER:
        err.append("KEY_ORDER/keys sai")
        return err, warn
    if a["intent"] not in INTENTS:
        err.append("intent ngoài enum")
    if not set(a["destination_regions"]) <= REGIONS:
        err.append("region ngoài enum")
    if not set(a["terrain_types"]) <= TERRAINS:
        err.append("terrain ngoài enum")
    if a["terrain_types"] != sorted(a["terrain_types"]):
        err.append("terrain_types chưa xếp alphabet")
    if a["destination"] is not None and (a["destination_regions"] or a["terrain_types"]):
        err.append("Rule 10: có destination thì regions/terrain phải []")
    if set(a["excluded_destinations"]) & set(a["excluded_places"]):
        err.append("trùng giữa excluded_destinations và excluded_places")
    excl = set(a["excluded_destinations"]) | set(a["excluded_places"])
    if a["destination"] in excl:
        err.append("Rule 9: destination nằm trong danh sách loại trừ")
    for p in a["hard_pinned_locations"] + a["preferences"]:
        if any(fold(e) in fold(p) for e in excl):
            err.append(f"Rule 9: địa danh loại trừ rò rỉ vào pinned/preferences: {p}")
    for e in a["excluded_destinations"]:
        if e not in P34:
            warn.append(f"excluded_destinations không thuộc 34 tỉnh: {e}")
    for e in excl:
        if fold(e) not in fold(user):
            err.append(f"Rule 1: '{e}' không xuất hiện trong câu người dùng")
    if a["prefer_flight"] is False and not FLIGHT_RE.search(user):
        warn.append("Rule 2: prefer_flight=false nhưng câu không nhắc bay")
    if a["prefer_flight"] is True and a["vehicle_type"] is not None and strict_sources:
        warn.append("prefer_flight=true đi kèm vehicle_type (cần rà soát nguồn)")
    if a["destination"] is not None and a["destination"] not in P34:
        warn.append(f"destination ngoài 34 tỉnh: {a['destination']}")
    return err, warn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--remap-34", action="store_true",
                    help="Đổi nhãn tỉnh cũ (Quảng Nam, Hà Giang, Kiên Giang, Bà Rịa - Vũng Tàu) sang tên 34 tỉnh")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # (a) mẫu mới
    new_rows, bad = [], 0
    for user, a in SAMPLES:
        a = ordered(a)
        e, w = validate(user, a)
        if e:
            bad += 1
            print("[LỖI MẪU MỚI]", user, e)
        new_rows.append(make_msg(user, a))
    if bad:
        sys.exit(f"{bad} mẫu mới vi phạm invariant")
    with open(out / "train_nlu_adversarial_v3.jsonl", "w", encoding="utf-8") as f:
        for r in new_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # (b) migrate master
    migrated, warn_counter = [], collections.Counter()
    with open(args.master, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            user = r["messages"][1]["content"]
            old = json.loads(r["messages"][2]["content"])
            a = migrate_assistant(old, user, args.remap_34)
            e, w = validate(user, a)
            if e:
                print("[LỖI MASTER]", user, e)
            for x in w:
                warn_counter[x.split(":")[0] if "ngoài 34" not in x else "destination ngoài 34 tỉnh"] += 1
            migrated.append(make_msg(user, a))
    with open(out / "train_nlu_master_v3.jsonl", "w", encoding="utf-8") as f:
        for r in migrated + new_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"OK: {len(new_rows)} mẫu mới | {len(migrated)} mẫu cũ đã migrate | tổng {len(migrated) + len(new_rows)}")
    print("Cảnh báo trên tập cũ (không chặn, cần rà soát nhãn):")
    for k, v in warn_counter.most_common():
        print(f"  {v:4d}  {k}")


if __name__ == "__main__":
    main()
