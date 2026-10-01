import json
from collections import Counter
from pathlib import Path

train_path = Path(r"d:\vn-travel-planner\data\train_nlu.jsonl")
lines = [json.loads(l) for l in train_path.read_text(encoding="utf-8").strip().split("\n")]
print(f"Total train samples: {len(lines)}")

parsed_list = [json.loads(x["messages"][2]["content"]) for x in lines]

# 1. prefer_flight distribution
flight_dist = Counter([p.get("prefer_flight") for p in parsed_list])
print("\n[1. PREFER_FLIGHT DISTRIBUTION]")
for k, v in flight_dist.items():
    print(f"  • {str(k):<8}: {v} ({v/len(parsed_list)*100:.1f}%)")

# 2. origin distribution
origin_types = []
for p in parsed_list:
    orig = p.get("origin")
    if orig == "CURRENT_LOCATION": origin_types.append("CURRENT_LOCATION")
    elif orig is None: origin_types.append("None")
    else: origin_types.append("Explicit Location")
print("\n[2. ORIGIN DISTRIBUTION]")
for k, v in Counter(origin_types).items():
    print(f"  • {k:<18}: {v} ({v/len(parsed_list)*100:.1f}%)")

# 3. group_size distribution
group_types = []
for p in parsed_list:
    g = p.get("group_size")
    if g is None: group_types.append("None (Unresolved / Sparse)")
    elif g == 2: group_types.append("2 (Couple / Pair)")
    else: group_types.append(f"{g} (Explicit other)")
print("\n[3. GROUP_SIZE DISTRIBUTION]")
for k, v in Counter(group_types).items():
    print(f"  • {k:<28}: {v} ({v/len(parsed_list)*100:.1f}%)")

# 4. vehicle_type distribution
v_dist = Counter([str(p.get("vehicle_type")) for p in parsed_list])
print("\n[4. VEHICLE_TYPE DISTRIBUTION]")
for k, v in v_dist.items():
    print(f"  • {k:<10}: {v} ({v/len(parsed_list)*100:.1f}%)")

# 5. Check for TOXIC transport words in excluded_activities
toxic_words = ["máy bay", "ô tô", "xe máy", "xe khách", "bay"]
toxic_found = 0
for p in parsed_list:
    for act in p.get("excluded_activities", []):
        for tw in toxic_words:
            if tw in act.lower():
                print(f"🚨 TOXIC LEAKAGE DETECTED: \"{act}\"")
                toxic_found += 1
if toxic_found == 0:
    print("\n✅ ZERO TOXIC LEAKAGE: 100% excluded_activities là domain activity sạch, không dính phương tiện!")

# In 10 mẫu ngẫu nhiên để soi tận mắt
print("\n" + "=" * 75)
print("🔍 5 MẪU NGẪU NHIÊN KIỂM TRA TRỰC QUAN:")
print("=" * 75)
for i in [10, 50, 100, 200, 300]:
    sample = lines[i]
    print(f"USER: {sample['messages'][1]['content']}")
    print(f"JSON: {sample['messages'][2]['content']}\n")
