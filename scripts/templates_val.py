"""
scripts/templates_val.py
═══════════════════════════════════════════════════════════════════════════════
Bộ khuôn mẫu câu (Templates) dành riêng cho tập VALIDATION (Hold-out).
Được thiết kế hoàn toàn khác biệt về cấu trúc ngữ pháp và hoán vị slot so với Train.
Zero-leakage: Đảm bảo độ tương đồng Trigram Jaccard < 0.35 và tỷ lệ trùng thứ tự slot < 25%.
═══════════════════════════════════════════════════════════════════════════════
"""

import sys, os
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from typing import List, Dict, Any
from scripts.compose import compose_val_templates

_val_data = compose_val_templates()

VAL_PLAN_TEMPLATES: List[Dict[str, Any]] = _val_data["plan"]
VAL_SEARCH_TEMPLATES: List[Dict[str, Any]] = _val_data["search"]
VAL_ADVISORY_TEMPLATES: List[Dict[str, Any]] = _val_data["advisory"]
VAL_CLARIFY_TEMPLATES: List[Dict[str, Any]] = _val_data["clarify"]
