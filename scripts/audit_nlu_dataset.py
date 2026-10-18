#!/usr/bin/env python3
"""
audit_nlu_dataset.py - independent QA for the NLU jsonl datasets.

Usage:
  python audit_nlu_dataset.py --train data/train_nlu_master_v5.jsonl \
      --val data/val_nlu_v5.jsonl --adv data/train_nlu_adversarial_v5.jsonl \
      [--gazetteer-db travel_db.db] [--sample 100] [--out audit_out]

It does NOT import the generator, so it cannot share its bugs.
Exit code 1 if any HARD check fails.
Optional: if app.services.gazetteer is importable, province codes are used
for dest/origin comparison; otherwise only normalized strings are compared.
"""
import argparse, collections, json, os, random, re, sys, unicodedata

INTENTS = {"plan_itinerary", "search_place", "ask_advisory", "clarify_needed"}
SLOTS = ["destination_mention", "origin_mention", "duration_days", "group_size",
         "vehicle_type", "budget_total_vnd", "destination_regions", "terrain_types",
         "excluded_mentions", "pinned_mentions", "preferences", "excluded_activities",
         "prefer_flight"]
SENTINELS = {"CURRENT_LOCATION"}
# words that should never sit inside a place-name span
OVERCAPTURE = re.compile(r"(?<!\w)(bằng|săn|ngắm|cưỡi|uống|tắm biển|nghỉ dưỡng|cuối tuần|khoảng|trong|và|rồi|thích|đón)(?!\w)", re.I)
PLACE_OK = re.compile(r"cao bằng|chợ đêm|thích ca|đêm|người|ngày|hôm", re.I)  # legit place-name words
GROUP_WORDS = r"(?:người|nguoi|khách|khach|bạn|ban|thành viên|đứa|dua)\b"
PAIR_WORDS = r"(?:vợ chồng|vo chong|cặp đôi|cap doi|hai đứa|hai dua|2 vợ chồng|đôi mình)"
SOLO_WORDS = r"(?:một mình|1 mình|mot minh|solo|đi lẻ)"


def strip_accents(s):
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d")


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", strip_accents(s or ""))).strip()


def load(path):
    rows, errs = [], []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            try:
                rec = json.loads(line)
                user = rec["messages"][1]["content"]
                ann = json.loads(rec["messages"][2]["content"])
                rows.append({"line": i, "text": user, "ann": ann})
            except Exception as e:  # noqa
                errs.append((i, repr(e)))
    return rows, errs


class Prov:
    """province-code resolver, optional."""
    def __init__(self, db):
        self.fn = None
        try:
            sys.path.insert(0, os.getcwd())
            from app.services.gazetteer import Gazetteer
            g = Gazetteer(db)
            self.fn = lambda m: (g.resolve_mention(m) or {}).get("province_code")
        except Exception:
            pass

    def code(self, m):
        return self.fn(m) if (self.fn and m) else None


def template_key(row):
    t = norm(row["text"])
    a = row["ann"]
    for k, tag in (("destination_mention", "DEST"), ("origin_mention", "ORIG")):
        m = a.get(k)
        if m:
            t = t.replace(norm(m), f"<{tag}>")
    for k in ("excluded_mentions", "pinned_mentions"):
        for m in a.get(k) or []:
            t = t.replace(norm(m), "<POI>")
    return re.sub(r"\d+", "0", t)


def trigrams(s):
    w = s.split()
    return {" ".join(w[i:i + 3]) for i in range(max(1, len(w) - 2))}


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def check_rows(name, rows, prov, hard):
    issues = collections.defaultdict(list)
    for r in rows:
        a, u, un = r["ann"], r["text"], norm(r["text"])
        ul = u.lower()
        if a.get("intent") not in INTENTS:
            issues["bad_intent"].append(r)
        d, o = a.get("destination_mention"), a.get("origin_mention")
        for k, m in (("destination_mention", d), ("origin_mention", o)):
            if m in SENTINELS:
                continue
            if m and OVERCAPTURE.search(PLACE_OK.sub(" ", m)):
                issues[f"overcaptured_{k}"].append(r)
            if m and m.lower() not in ul and norm(m) not in un:
                issues[f"ungrounded_{k}"].append(r)
        for k in ("excluded_mentions", "pinned_mentions"):
            for m in a.get(k) or []:
                if m.lower() not in ul and norm(m) not in un:
                    issues[f"ungrounded_{k}"].append(r)
                    break
        if d and o:
            if norm(d) == norm(o):
                issues["dest_eq_orig_string"].append(r)
            else:
                cd, co = prov.code(d), prov.code(o)
                if cd is not None and cd == co:
                    issues["dest_eq_orig_province"].append(r)
        if d and o and (norm(d) in norm(o) or norm(o) in norm(d)):
            if norm(d) != norm(o):
                issues["dest_orig_substring"].append(r)
        if d and o and d.lower() in ul and o.lower() in ul:
            pd, po = ul.find(d.lower()), ul.find(o.lower())
            before = ul[max(0, po - 14):po]
            if not re.search(r"(từ|tu|xuất phát|khởi hành|ở|o|bay từ|đi từ)\s*$", before.strip() + " ") \
               and not re.search(r"(từ|tu|xuat phat|khoi hanh)\s*$", strip_accents(before)):
                issues["origin_without_origin_cue"].append(r)
        # duration
        dd = a.get("duration_days")
        if dd is not None:
            m = re.search(r"(\d+)\s*(?:ngày|ngay|hôm|hom|n\s*\d+\s*[đd])", ul)
            m2 = re.search(r"\b(\d+)\s*n\s*(\d+)\s*[đd]\b", ul)
            if m2 and int(m2.group(1)) != dd:
                issues["duration_mismatch"].append(r)
            elif m and not m2 and int(m.group(1)) != dd:
                issues["duration_mismatch"].append(r)
        # group size
        g = a.get("group_size")
        if g is not None:
            ok = (re.search(rf"\b{g}\s*{GROUP_WORDS}", ul) or re.search(PAIR_WORDS, ul)
                  or re.search(SOLO_WORDS, ul) or re.search(r"\b(hai|ba|bốn|năm|sáu)\b", ul)
                  or re.search(rf"nhóm\s*{g}\b", ul) or re.search(rf"\b{g}\b", ul))
            if not ok:
                issues["group_size_ungrounded"].append(r)
            elif re.search(rf"\b{g}\s*(?:ngày|ngay|hôm|đêm)\b", ul) and not (
                    re.search(rf"\b{g}\s*{GROUP_WORDS}", ul) or re.search(PAIR_WORDS, ul)
                    or re.search(SOLO_WORDS, ul)):
                issues["group_size_maybe_from_duration"].append(r)
        b = a.get("budget_total_vnd")
        if b is not None and (not isinstance(b, int) or b <= 0):
            issues["budget_not_positive_int"].append(r)
        if a.get("intent") == "clarify_needed" and (d or a.get("duration_days")):
            issues["clarify_with_dest_or_duration"].append(r)
    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", required=True)
    ap.add_argument("--val", required=True)
    ap.add_argument("--adv")
    ap.add_argument("--gazetteer-db", default="travel_db.db")
    ap.add_argument("--sample", type=int, default=100)
    ap.add_argument("--near-dup", type=float, default=0.8)
    ap.add_argument("--out", default="audit_out")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    random.seed(7)
    prov = Prov(args.gazetteer_db)
    print(f"[info] province-code resolver: {'ON' if prov.fn else 'OFF (string compare only)'}")

    sets = {"train": args.train, "val": args.val}
    if args.adv:
        sets["adv"] = args.adv
    data, hard_fail = {}, False
    for name, p in sets.items():
        rows, errs = load(p)
        data[name] = rows
        print(f"\n=== {name}: {len(rows)} rows ({p}) ===")
        if errs:
            hard_fail = True
            print(f"  HARD parse errors: {len(errs)} e.g. {errs[:3]}")

    HARD = {"bad_intent", "ungrounded_destination_mention", "ungrounded_origin_mention",
            "ungrounded_excluded_mentions", "ungrounded_pinned_mentions",
            "dest_eq_orig_string", "dest_eq_orig_province", "duration_mismatch",
            "budget_not_positive_int", "overcaptured_destination_mention",
            "overcaptured_origin_mention"}
    report = {}
    for name, rows in data.items():
        iss = check_rows(name, rows, prov, HARD)
        print(f"\n--- row checks: {name} ---")
        if not iss:
            print("  no issues")
        for k, v in sorted(iss.items(), key=lambda x: -len(x[1])):
            tag = "HARD" if k in HARD else "soft"
            print(f"  [{tag}] {k}: {len(v)}")
            for r in v[:3]:
                print(f"      L{r['line']}: {r['text'][:110]}")
            if k in HARD:
                hard_fail = True
        report[name] = {k: [r["line"] for r in v] for k, v in iss.items()}

        c = collections.Counter(r["ann"].get("intent") for r in rows)
        print("  intents:", dict(c))
        fill = {s: sum(1 for r in rows if r["ann"].get(s) not in (None, [], "")) for s in SLOTS}
        print("  slot fill %:", {k: round(100 * v / len(rows), 1) for k, v in fill.items()})
        cross = collections.Counter(
            (r["ann"].get("intent"), bool(r["ann"].get("excluded_mentions"))) for r in rows)
        print("  intent x has_exclusion:", dict(cross))

    # ---- leakage: template + near-dup + entities ----
    print("\n--- leakage (train vs val / adv) ---")
    tk = {n: [template_key(r) for r in rows] for n, rows in data.items()}
    train_keys = set(tk["train"])
    tri_train = [trigrams(k) for k in tk["train"]]
    inv = collections.defaultdict(list)
    for i, tg in enumerate(tri_train):
        for g in tg:
            inv[g].append(i)
    for n in [x for x in data if x != "train"]:
        same_tpl = sum(1 for k in tk[n] if k in train_keys)
        near = []
        for i, k in enumerate(tk[n]):
            tg = trigrams(k)
            cand = collections.Counter(j for g in tg for j in inv.get(g, ()))
            best = max(((jaccard(tg, tri_train[j]), j) for j, _ in cand.most_common(30)), default=(0, -1))
            if best[0] >= args.near_dup:
                near.append((i, best[1], round(best[0], 2)))
        print(f"  {n}: identical delexicalized template in train: {same_tpl}/{len(tk[n])} "
              f"({100*same_tpl/len(tk[n]):.1f}%)")
        print(f"  {n}: near-dup (trigram Jaccard >= {args.near_dup}): {len(near)}/{len(tk[n])} "
              f"({100*len(near)/len(tk[n]):.1f}%)")
        for i, j, s in near[:3]:
            print(f"      {s}: [{n}] {data[n][i]['text'][:70]}  ~  [train] {data['train'][j]['text'][:70]}")
        report[f"leak_{n}"] = {"same_template": same_tpl, "near_dup": len(near)}
        for slot in ("destination_mention", "origin_mention"):
            ts = {norm(r["ann"].get(slot)) for r in data["train"] if r["ann"].get(slot)}
            vs = [norm(r["ann"].get(slot)) for r in data[n] if r["ann"].get(slot)]
            if vs:
                seen = sum(1 for x in vs if x in ts)
                print(f"  {n}: {slot} seen in train: {100*seen/len(vs):.1f}% of {len(vs)}")

    # ---- minimal-pair / spurious cue check for adversarial ----
    if "adv" in data:
        print("\n--- adversarial spurious-cue check ---")
        neg = re.compile(r"\b(trừ|tru|không đi|khong di|bỏ|bo qua|ngoại trừ|đừng|tránh)\b")
        for n in ("train", "val", "adv"):
            rows = data[n]
            tot = [r for r in rows if neg.search(strip_accents(r["text"]).replace("đ", "d")) or neg.search(r["text"].lower())]
            cnt = collections.Counter(r["ann"].get("intent") for r in tot)
            print(f"  {n}: rows with negation cue = {len(tot)}; by intent = {dict(cnt)}")

    # ---- manual-review sample ----
    pool = [(n, r) for n, rows in data.items() for r in rows]
    smp = random.sample(pool, min(args.sample, len(pool)))
    with open(os.path.join(args.out, "manual_review_sample.tsv"), "w", encoding="utf-8") as f:
        f.write("set\tline\ttext\tintent\tdest\torig\tdays\tgroup\tbudget\texcluded\tOK?\tnote\n")
        for n, r in smp:
            a = r["ann"]
            f.write("\t".join(str(x) for x in [
                n, r["line"], r["text"].replace("\t", " "), a.get("intent"),
                a.get("destination_mention"), a.get("origin_mention"), a.get("duration_days"),
                a.get("group_size"), a.get("budget_total_vnd"), a.get("excluded_mentions"), "", ""]) + "\n")
    with open(os.path.join(args.out, "audit_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f"\n[out] {args.out}/manual_review_sample.tsv ({len(smp)} rows) and audit_report.json")
    print("RESULT:", "FAIL (hard issues)" if hard_fail else "PASS (no hard issues)")
    sys.exit(1 if hard_fail else 0)


if __name__ == "__main__":
    main()
