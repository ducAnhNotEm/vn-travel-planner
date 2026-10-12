"""
tests/test_minimal_pairs.py
═══════════════════════════════════════════════════════════════════════════════
Unit tests for Requirement R4: Adversarial Minimal Pairs & Multi-dimensional Negation.
Verifies:
1. MINIMAL_PAIR_TEMPLATES contains all 4 categories:
   - pin_vs_excl (POI pinning vs exclusion)
   - activity_inc_vs_excl (Activity inclusion/preference vs activity exclusion)
   - pref_pos_vs_neg (Positive preference vs negative constraint attribute)
   - reverse_polarity ('không' does NOT mean exclusion: POI pin, activity pref, unlimited budget)
2. All templates have 0 hardcoded digits.
3. Synchronized pair_id in generated adversarial dataset.
4. Correct slot labeling per Annotation Spec v5.2.
═══════════════════════════════════════════════════════════════════════════════
"""

import os
import re
import json
from collections import defaultdict, Counter
import pytest

from scripts.templates_adv import MINIMAL_PAIR_TEMPLATES


def test_minimal_pair_templates_structure_and_categories():
    """Kiểm tra cấu trúc và các danh mục của MINIMAL_PAIR_TEMPLATES."""
    assert len(MINIMAL_PAIR_TEMPLATES) >= 20, f"Expected at least 20 pairs, got {len(MINIMAL_PAIR_TEMPLATES)}"

    pair_types = Counter(t["pair_type"] for t in MINIMAL_PAIR_TEMPLATES)
    assert pair_types["pin_vs_excl"] >= 8
    assert pair_types["activity_inc_vs_excl"] >= 4
    assert pair_types["pref_pos_vs_neg"] >= 4
    assert pair_types["reverse_polarity"] >= 4

    # Kiểm tra reverse polarity có đủ các sub_type: poi, activity, budget
    rev_subtypes = {t.get("sub_type") for t in MINIMAL_PAIR_TEMPLATES if t["pair_type"] == "reverse_polarity"}
    assert {"poi", "activity", "budget"}.issubset(rev_subtypes)


def test_no_hardcoded_digits_in_templates():
    """Không được có chữ số cứng trong bất kỳ pattern nào của minimal pair."""
    for tpl in MINIMAL_PAIR_TEMPLATES:
        patterns = [
            tpl.get("pattern_pin"),
            tpl.get("pattern_excl"),
            tpl.get("pattern_pos"),
            tpl.get("pattern_neg"),
        ]
        for p in patterns:
            if p:
                assert not re.search(r"\d", p), f"Pattern contains hardcoded digit: {p}"


def test_reverse_polarity_contains_negation_words():
    """Cặp reverse_polarity bắt buộc phải chứa từ phủ định (không, chẳng, kiêng...) nhưng không mang nghĩa loại trừ."""
    for tpl in MINIMAL_PAIR_TEMPLATES:
        if tpl["pair_type"] == "reverse_polarity":
            pat_pos = tpl["pattern_pos"]
            assert re.search(r"\b(không|khong)\b", pat_pos.lower()), (
                f"Reverse polarity positive pattern must contain negation word 'không': {pat_pos}"
            )


def test_adversarial_dataset_synchronized_pair_ids():
    """Kiểm tra dataset train_nlu_adversarial_v5.jsonl có pair_id đồng bộ 100%."""
    adv_path = os.path.join("data", "train_nlu_adversarial_v5.jsonl")
    if not os.path.exists(adv_path):
        pytest.skip("Dataset file data/train_nlu_adversarial_v5.jsonl does not exist yet")

    with open(adv_path, "r", encoding="utf-8") as f:
        records = [json.loads(line) for line in f]

    pairs = defaultdict(list)
    for idx, r in enumerate(records):
        meta = r.get("meta", {})
        pid = meta.get("pair_id")
        if pid:
            pairs[pid].append((idx, r))

    assert len(pairs) >= 150, f"Expected at least 150 minimal pairs, got {len(pairs)}"

    # Mỗi pair_id phải có đúng 2 câu (câu A và câu B)
    for pid, items in pairs.items():
        assert len(items) == 2, f"Pair {pid} has {len(items)} items instead of 2"
        idx_a, item_a = items[0]
        idx_b, item_b = items[1]
        assert idx_b == idx_a + 1, f"Pair {pid} items are not adjacent (idx {idx_a} and {idx_b})"
        assert item_a["meta"]["pair_id"] == pid
        assert item_b["meta"]["pair_id"] == pid


def test_semantic_annotations_in_minimal_pairs():
    """Kiểm tra ngữ nghĩa gán nhãn của các cặp đối lập trong dataset."""
    adv_path = os.path.join("data", "train_nlu_adversarial_v5.jsonl")
    if not os.path.exists(adv_path):
        pytest.skip("Dataset file does not exist")

    with open(adv_path, "r", encoding="utf-8") as f:
        records = [json.loads(line) for line in f]

    pairs = defaultdict(list)
    for r in records:
        pid = r.get("meta", {}).get("pair_id")
        if pid:
            pairs[pid].append(r)

    checked_categories = set()

    for pid, (rec_a, rec_b) in pairs.items():
        tid_a = rec_a["meta"]["template_id"]
        ann_a = json.loads(rec_a["messages"][2]["content"])
        ann_b = json.loads(rec_b["messages"][2]["content"])

        # 1. POI pin vs excl (adv_pair_01 - 08)
        if "pin" in tid_a or tid_a.startswith("adv_pair_0"):
            if ann_a.get("pinned_mentions") and ann_b.get("excluded_mentions"):
                assert ann_a["pinned_mentions"] == ann_b["excluded_mentions"]
                assert ann_a.get("excluded_mentions") == []
                assert ann_b.get("pinned_mentions") == []
                checked_categories.add("pin_vs_excl")

        # 2. Activity inclusion vs exclusion (adv_pair_09 - 12)
        if any(f"adv_pair_{i:02d}" in tid_a for i in range(9, 13)):
            assert len(ann_a.get("preferences", [])) > 0
            assert len(ann_b.get("excluded_activities", [])) > 0
            assert ann_a["preferences"] == ann_b["excluded_activities"]
            checked_categories.add("activity_inc_vs_excl")

        # 3. Preference attributes (adv_pair_13 - 16)
        if any(f"adv_pair_{i:02d}" in tid_a for i in range(13, 17)):
            assert len(ann_a.get("preferences", [])) > 0
            assert len(ann_b.get("preferences", [])) > 0
            pref_a = ann_a["preferences"][0]
            pref_b = ann_b["preferences"][0]
            assert pref_a != pref_b
            assert re.search(r"\bkhông\b", pref_b)
            checked_categories.add("pref_pos_vs_neg")

        # 4. Reverse polarity (adv_pair_17 - 20)
        if "adv_pair_17" in tid_a or "adv_pair_18" in tid_a:
            # POI: 'không thể bỏ qua {poi}' -> PINNED
            assert len(ann_a.get("pinned_mentions", [])) > 0
            assert len(ann_b.get("excluded_mentions", [])) > 0
            assert ann_a.get("excluded_mentions") == []
            checked_categories.add("reverse_polarity_poi")

        if "adv_pair_19" in tid_a:
            # Activity: 'không ngại {activity}' -> preference, NOT excluded_activities
            assert len(ann_a.get("preferences", [])) > 0
            assert ann_a.get("excluded_activities") == []
            assert len(ann_b.get("excluded_activities", [])) > 0
            checked_categories.add("reverse_polarity_act")

        if "adv_pair_20" in tid_a:
            # Budget: 'không giới hạn ngân sách' -> budget=None, preference=['không giới hạn ngân sách']
            assert ann_a.get("budget_total_vnd") is None
            assert "không giới hạn ngân sách" in ann_a.get("preferences", [])
            assert ann_b.get("budget_total_vnd") is not None
            checked_categories.add("reverse_polarity_bud")

    assert "pin_vs_excl" in checked_categories
    assert "activity_inc_vs_excl" in checked_categories
    assert "pref_pos_vs_neg" in checked_categories
    assert "reverse_polarity_poi" in checked_categories
    assert "reverse_polarity_act" in checked_categories
    assert "reverse_polarity_bud" in checked_categories
