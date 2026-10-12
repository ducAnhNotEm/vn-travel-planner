"""
scripts/templates_adv.py
═══════════════════════════════════════════════════════════════════════════════
Bộ khuôn mẫu câu (Templates) dành riêng cho tập ADVERSARIAL & MINIMAL PAIRS.
Bao phủ 6 kiểu thử thách khó trên cả 4 intent:
1. Phủ định địa danh (excluded_mentions: trừ, né, không đi, bỏ qua, tránh, khỏi ghé, ngoại trừ)
2. Phủ định hoạt động (excluded_activities: không leo núi, né ăn hải sản, tránh đi đêm)
3. Phủ định thuộc tính (preferences: không gần biển, không quá ồn ào, không gian yên tĩnh)
4. Đảo ngữ cú pháp (đặt điểm đón origin lên đầu câu)
5. Tiếng Việt không dấu / teencode
6. Nhiều con số trong câu (ngân sách, số người, số ngày)
Cùng cơ chế Minimal Pair: ghép cặp đối lập (pinned_mentions vs excluded_mentions).
Tỷ lệ trùng lặp chu kỳ slot với Train < 40% (mục tiêu 15-25%).
═══════════════════════════════════════════════════════════════════════════════
"""

import sys, os
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from typing import List, Dict, Any
from scripts.compose import compose_adv_templates

_adv_data = compose_adv_templates()

MINIMAL_PAIR_TEMPLATES: List[Dict[str, Any]] = _adv_data["minimal_pairs"]
ADV_INVERTED_TEMPLATES: List[Dict[str, Any]] = _adv_data["inverted"]
ADV_SEARCH_TEMPLATES: List[Dict[str, Any]] = _adv_data["search"]
ADV_ADVISORY_TEMPLATES: List[Dict[str, Any]] = _adv_data["advisory"]
ADV_CLARIFY_TEMPLATES: List[Dict[str, Any]] = _adv_data["clarify"]
ADV_UNACCENTED_TEMPLATES: List[Dict[str, Any]] = _adv_data["unaccented"]
