#!/usr/bin/env python3
"""
audit_templates.py - kiem tra chat luong bo khuon cau (templates), TRUOC khi sinh du lieu.

Chay:
  python audit_templates.py --train scripts/templates_train.py \
      --val scripts/templates_val.py --adv scripts/templates_adv.py \
      [--rows-train 3500 --rows-val 400 --rows-adv 900]

Kiem tra:
  1. placeholder khong khai bao trong slots / slot khai bao nhung khong co cach render
  2. so cung trong khuon (vd '2 dem' canh {duration_days})
  3. pref_val / excl_act_val phai nam NGUYEN VAN trong cau
  4. trung 'chu ky thu tu slot' giua val/adv va train
  5. do giong trigram (da bo placeholder) giua val/adv va train
  6. so dong trung binh moi khuon (neu truyen --rows-*)
Thoat ma 1 neu co loi CUNG.
"""
import argparse, collections, importlib.util, re, sys

PH = re.compile(r"\{(\w+)\}")
PH2SLOT = {
    "dest_mention": "dest_mention", "origin_mention": "origin_mention",
    "duration_days": "duration_days", "nights": "duration_days", "group_size": "group_size",
    "budget_phrase": "budget_total_vnd", "vehicle_phrase": "vehicle_type",
    "pref_phrase": "preferences", "excl_mention": "excluded_mentions",
    "excl_activity": "excluded_activities", "pin_mention": "pinned_mentions",
    "target_poi": "pinned_or_excluded_mentions", "region_phrase": "destination_regions",
    "terrain_phrase": "terrain_types", "target_activity": "preferences_or_excluded_activities",
}
SHORT = {"dest_mention": "DEST", "origin_mention": "ORIG", "duration_days": "DAYS",
         "nights": "NIGHTS", "group_size": "GRP", "budget_phrase": "BUD", "vehicle_phrase": "VEH",
         "pref_phrase": "PREF", "excl_mention": "EXCL", "excl_activity": "EXCA",
         "pin_mention": "POI", "target_poi": "POI", "region_phrase": "REG",
         "terrain_phrase": "TER", "target_activity": "ACT"}
# slot co the khong co placeholder vi da nam co dinh trong cau
FIXED_TEXT_OK = {"origin_mention", "prefer_flight", "preferences", "excluded_activities"}


def load(path):
    spec = importlib.util.spec_from_file_location("m_" + str(abs(hash(path))), path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def collect(mod):
    out = []
    for var, val in vars(mod).items():
        if not (isinstance(val, list) and val and isinstance(val[0], dict)):
            continue
        for i, t in enumerate(val):
            intent = t.get("intent")
            if not intent:
                v = var.upper()
                intent = ("plan_itinerary" if "PLAN" in v or "PAIR" in v or "INVERT" in v else
                          "search_place" if "SEARCH" in v else
                          "ask_advisory" if "ADVISORY" in v else
                          "clarify_needed" if "CLARIFY" in v else var)
            for key in ("pattern", "pattern_pin", "pattern_excl", "pattern_pos", "pattern_neg"):
                if key in t:
                    tid = t.get("id") or f"{var}[{i}]"
                    if key != "pattern":
                        tid += ":" + key.split("_")[1]
                    out.append({"id": tid, "intent": intent, "pattern": t[key], "t": t})
    return out


def signature(p):
    return tuple(SHORT.get(x, x) for x in PH.findall(p))


def delex(p):
    return re.sub(r"\s+", " ", PH.sub("X", p.lower())).strip()


def tri(s):
    w = s.split()
    return {" ".join(w[i:i + 3]) for i in range(max(1, len(w) - 2))}


def jac(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", required=True)
    ap.add_argument("--val", required=True)
    ap.add_argument("--adv", required=True)
    ap.add_argument("--rows-train", type=int)
    ap.add_argument("--rows-val", type=int)
    ap.add_argument("--rows-adv", type=int)
    ap.add_argument("--jaccard", type=float, default=0.5)
    a = ap.parse_args()
    sets = {"train": collect(load(a.train)), "val": collect(load(a.val)), "adv": collect(load(a.adv))}
    rows = {"train": a.rows_train, "val": a.rows_val, "adv": a.rows_adv}
    hard = 0

    print("== So khuon theo tap x intent ==")
    for n, lst in sets.items():
        c = collections.Counter(x["intent"] for x in lst)
        print(f"  {n}: {len(lst)} khuon  {dict(c)}")
        if rows[n]:
            print(f"      ~{rows[n] / max(1, len(lst)):.0f} dong / khuon (nen <= 30)")

    print("\n== Loi trong tung khuon ==")
    for n, lst in sets.items():
        for x in lst:
            t, p = x["t"], x["pattern"]
            phs = set(PH.findall(p))
            if "slots" not in t:  # khuon cap minimal pair khong khai bao slots
                declared = None
            else:
                declared = set(t["slots"])
            for ph in (phs if declared is not None else ()):
                s = PH2SLOT.get(ph, ph)
                ok = (s in declared or (s == "pinned_or_excluded_mentions") or ph in declared)
                if not ok:
                    print(f"  [HARD] {n}/{x['id']}: placeholder {{{ph}}} khong nam trong slots")
                    hard += 1
            for s in (declared or ()):
                if s in FIXED_TEXT_OK:
                    continue
                if not any(PH2SLOT.get(ph) == s or ph == s for ph in phs):
                    print(f"  [HARD] {n}/{x['id']}: slot '{s}' khai bao nhung cau khong co cho render")
                    hard += 1
            if re.search(r"\d", p):
                print(f"  [HARD] {n}/{x['id']}: co so cung trong khuon -> {p[:70]}")
                hard += 1
            body = re.sub(r"\s+", " ", PH.sub(" ", p.lower()))
            for k in ("pref_val", "excl_act_val"):
                if k in t and t[k].lower() not in body:
                    print(f"  [HARD] {n}/{x['id']}: {k}='{t[k]}' khong nam nguyen van trong cau")
                    hard += 1

    print("\n== Chu ky thu tu slot (val/adv so voi train, cung intent) ==")
    train_sig = collections.defaultdict(set)
    for x in sets["train"]:
        train_sig[x["intent"]].add(signature(x["pattern"]))
    for n in ("val", "adv"):
        lst = sets[n]
        same = [x for x in lst if signature(x["pattern"]) in train_sig[x["intent"]] and signature(x["pattern"])]
        new = len({signature(x["pattern"]) for x in lst if signature(x["pattern"])
                   and signature(x["pattern"]) not in train_sig[x["intent"]]})
        print(f"  {n}: {len(same)}/{len(lst)} khuon co chu ky GIONG train; {new} chu ky moi")
        if len(same) > 0.6 * len(lst):
            print(f"      [CANH BAO] {n} chu yeu la dien dat lai khuon train (cung thu tu slot)")

    print(f"\n== Giong trigram >= {a.jaccard} (sau khi bo placeholder) ==")
    tr = [(x["id"], tri(delex(x["pattern"]))) for x in sets["train"]]
    for n in ("val", "adv"):
        bad = 0
        for x in sets[n]:
            s = tri(delex(x["pattern"]))
            best = max(((jac(s, t), i) for i, t in tr), default=(0, ""))
            if best[0] >= a.jaccard:
                print(f"  [HARD] {n}/{x['id']} ~ train/{best[1]}: {best[0]:.2f}")
                bad += 1
        hard += bad
        print(f"  {n}: {bad} khuon vuot nguong")

    print("\nKET QUA:", "FAIL" if hard else "PASS", f"({hard} loi cung)")
    sys.exit(1 if hard else 0)


if __name__ == "__main__":
    main()
