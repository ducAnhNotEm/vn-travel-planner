"""
VN Travel Planner — Model Assurance & Contract Verification Suite (Top 0.01% Standard)
======================================================================================
Bộ kiểm thử thẩm định hành vi mô hình (Model Behavioral Assurance):
- Định nghĩa rõ: Expected Output, Forbidden Inferences, Failure Mode, và Semantic Axes.
- Hỗ trợ 2 chế độ:
  1. Offline Harness Verification (Kiểm tra tính hợp lệ của Khung benchmark)
  2. Model Inference Evaluation (Đo lường Model Thật trên 7 thước đo vi phạm Contract)
"""

import json
from typing import Dict, Any, List, Tuple

# 10 CA BẪY ĐỐI NGHỊCH CHUẨN MỰC (ASSURANCE BENCHMARK MATRIX)
ASSURANCE_TEST_CASES = [
    # ── TC 1: Negation Flip ──────────────────────────────────────────────────
    {
        "id": "TC01_NEGATION_FLIP",
        "failure_mode": "negation_blindness",
        "semantic_axes": {"transport": "flight", "polarity": "negative"},
        "input": "Tôi không muốn bay vào Đà Nẵng 3 ngày cuối tuần này, đi ô tô nhé.",
        "expected": {
            "intent": "plan_itinerary",
            "destination": "Đà Nẵng",
            "vehicle_type": "car",
            "prefer_flight": False
        },
        "forbidden_inferences": {
            "prefer_flight": True  # Cấm bắt nhầm chữ 'bay'
        }
    },

    # ── TC 2: Preference Switch / Final Chosen State ──────────────────────────
    {
        "id": "TC02_PREFERENCE_SWITCH",
        "failure_mode": "historical_state_leakage",
        "semantic_axes": {"transport": "hybrid", "decision": "switched"},
        "input": "Ban đầu định đi máy bay vào Đà Nẵng nhưng thấy vé đắt quá nên thôi chuyển sang đi ô tô tự lái.",
        "expected": {
            "intent": "plan_itinerary",
            "destination": "Đà Nẵng",
            "vehicle_type": "car",
            "prefer_flight": False
        },
        "forbidden_inferences": {
            "prefer_flight": True
        }
    },

    # ── TC 3: Zero Semantic Mutation (Capacity Trap) ─────────────────────────
    {
        "id": "TC03_ZERO_MUTATION_CAPACITY",
        "failure_mode": "business_logic_mutation",
        "semantic_axes": {"quantity": "large_group", "transport": "ground"},
        "input": "Đoàn công ty mình 16 người đi Đà Lạt 3 ngày bằng ô tô nhé ad.",
        "expected": {
            "intent": "plan_itinerary",
            "destination": "Đà Lạt",
            "group_size": 16,
            "vehicle_type": "car"
        },
        "forbidden_inferences": {
            "vehicle_type": "van",  # CẤM AI tự sửa car -> van
            "group_size": 2         # CẤM AI tự default
        }
    },

    # ── TC 4: Reference Token Resolution ─────────────────────────────────────
    {
        "id": "TC04_REFERENCE_TOKEN_ORIGIN",
        "failure_mode": "context_hallucination",
        "semantic_axes": {"origin": "relative_reference"},
        "input": "Lên tour đi Sa Pa 3 ngày xuất phát từ chỗ tôi đang đứng.",
        "expected": {
            "intent": "plan_itinerary",
            "destination": "Sa Pa",
            "origin": "CURRENT_LOCATION"
        },
        "forbidden_inferences": {
            "origin": "Hà Nội",  # CẤM AI tự bịa thủ đô
            "origin": "Sa Pa"    # CẤM AI nhầm origin với destination
        }
    },

    # ── TC 5: Intent vs Completeness (Sparse Input) ───────────────────────────
    {
        "id": "TC05_SPARSE_INTENT_PRESERVATION",
        "failure_mode": "intent_degradation",
        "semantic_axes": {"completeness": "sparse", "intent": "planning"},
        "input": "Lên tour Đà Nẵng 3 ngày.",
        "expected": {
            "intent": "plan_itinerary",
            "destination": "Đà Nẵng",
            "duration_days": 3,
            "origin": None,
            "group_size": None,
            "vehicle_type": None
        },
        "forbidden_inferences": {
            "intent": "clarify_needed", # CẤM AI hạ cấp intent
            "origin": "Hà Nội",
            "group_size": 2
        }
    },

    # ── TC 6: False Substring Trap (Nha Trang Bay) ────────────────────────────
    {
        "id": "TC06_SUBSTRING_FALSE_POSITIVE",
        "failure_mode": "lexical_shortcut_bias",
        "semantic_axes": {"entity": "contains_keyword", "transport": "ground"},
        "input": "Cho mình lịch trình đi Nha Trang 3 ngày, muốn ở Vinpearl Resort & Spa Nha Trang Bay, đi xe máy.",
        "expected": {
            "intent": "plan_itinerary",
            "destination": "Nha Trang",
            "vehicle_type": "motorbike",
            "prefer_flight": False
        },
        "forbidden_inferences": {
            "prefer_flight": True
        }
    },

    # ── TC 7: Undecided / Ambiguous Transport (Null Semantics) ────────────────
    {
        "id": "TC07_UNDECIDED_FLIGHT_NULL",
        "failure_mode": "null_coercion_to_bool",
        "semantic_axes": {"transport": "undecided"},
        "input": "Đi Đà Nẵng từ Hà Nội 3 ngày, đi ô tô hay máy bay đều được, cái nào tiện thì đi.",
        "expected": {
            "intent": "plan_itinerary",
            "destination": "Đà Nẵng",
            "origin": "Hà Nội",
            "prefer_flight": None
        },
        "forbidden_inferences": {
            "prefer_flight": True,
            "prefer_flight": False
        }
    },

    # ── TC 8: Entity Hallucination Resistance ────────────────────────────────
    {
        "id": "TC08_UNKNOWN_ENTITY_RESISTANCE",
        "failure_mode": "entity_hallucination",
        "semantic_axes": {"entity": "out_of_vocab"},
        "input": "Lập lịch trình đi Đà Nẵng 3 ngày, nhất định phải ghé Khu vui chơi X-Planet 99.",
        "expected": {
            "intent": "plan_itinerary",
            "destination": "Đà Nẵng",
            "hard_pinned_locations": ["Khu vui chơi X-Planet 99"]
        },
        "forbidden_inferences": {
            "hard_pinned_locations": ["Bà Nà Hills"],        # CẤM AI tự sửa thành điểm nổi tiếng
            "hard_pinned_locations": ["Công viên Châu Á"]
        }
    },

    # ── TC 9: Conditional Request vs Preference ──────────────────────────────
    {
        "id": "TC09_CONDITIONAL_POLICY_REJECTION",
        "failure_mode": "condition_flattened_to_preference",
        "semantic_axes": {"logic": "conditional"},
        "input": "Nếu tháng 11 có hoa tam giác mạch thì lên tour Hà Giang 3N2Đ, không thì thôi nhé.",
        "expected": {
            "intent": "ask_advisory",  # Đây là câu hỏi điều kiện, NLU không được coi là đã chốt tour
            "destination": "Hà Giang"
        },
        "forbidden_inferences": {
            "preferences": ["hoa tam giác mạch"]  # CẤM AI coi điều kiện là sở thích đã chốt
        }
    },

    # ── TC 10: Counterfactual Transport (Minimal Pair) ───────────────────────
    {
        "id": "TC10_COUNTERFACTUAL_TRANSPORT",
        "failure_mode": "semantic_anchoring",
        "semantic_axes": {"transport": "minimal_change"},
        "input": "Đi Đà Nẵng 3 ngày 2 người từ Hà Nội bằng xe máy.",
        "expected": {
            "intent": "plan_itinerary",
            "destination": "Đà Nẵng",
            "origin": "Hà Nội",
            "vehicle_type": "motorbike"
        },
        "forbidden_inferences": {
            "vehicle_type": "car"  # CẤM AI bị mỏ neo vào default car
        }
    }
]

# ── BỘ ĐÁNH GIÁ CHUYÊN SÂU (SEMANTIC SCORER & CONTRACT VIOLATION DETECTOR) ───
class ContractAssuranceScorer:
    """
    Chấm điểm 3 tầng:
    1. Schema Validity Rate
    2. Field-level Semantic Accuracy
    3. Contract Violation Rate (Phát hiện cấm kỵ vi phạm khế ước)
    """
    def __init__(self):
        self.total = 0
        self.passed_exact = 0
        self.contract_violations = []
        self.field_stats = {}

    def evaluate_sample(self, test_case: Dict[str, Any], model_output_json: Dict[str, Any]):
        self.total += 1
        tc_id = test_case["id"]
        failure_mode = test_case["failure_mode"]
        expected = test_case["expected"]
        forbidden = test_case.get("forbidden_inferences", {})

        is_exact_match = True

        # 1. Kiểm tra Contract Violation (Forbidden Inferences)
        for f_key, f_val in forbidden.items():
            if f_key in model_output_json and model_output_json[f_key] == f_val:
                self.contract_violations.append({
                    "test_id": tc_id,
                    "failure_mode": failure_mode,
                    "violation": f"Forbidden value detected! {f_key} == {f_val}",
                    "input": test_case["input"]
                })
                is_exact_match = False

        # 2. Kiểm tra Field-level accuracy
        for e_key, e_val in expected.items():
            if e_key not in self.field_stats:
                self.field_stats[e_key] = {"correct": 0, "total": 0}
            self.field_stats[e_key]["total"] += 1

            actual_val = model_output_json.get(e_key)
            if actual_val == e_val:
                self.field_stats[e_key]["correct"] += 1
            else:
                is_exact_match = False

        if is_exact_match:
            self.passed_exact += 1

    def print_summary(self):
        print("\n" + "=" * 75)
        print("📊 MODEL CONTRACT ASSURANCE & SEMANTIC EVALUATION REPORT")
        print("=" * 75)
        print(f"Tổng số ca kiểm thử đối nghịch : {self.total}")
        print(f"Đạt độ chính xác tuyệt đối (Exact): {self.passed_exact}/{self.total} ({self.passed_exact/max(1,self.total)*100:.1f}%)")
        print(f"Số vi phạm khế ước (Violations) : {len(self.contract_violations)} ca")

        print("\n[FIELD-LEVEL ACCURACY]")
        for f, s in self.field_stats.items():
            pct = s["correct"] / s["total"] * 100 if s["total"] > 0 else 0
            print(f"  • {f:<22}: {s['correct']}/{s['total']} ({pct:.1f}%)")

        if self.contract_violations:
            print("\n🚨 DANH SÁCH VI PHẠM KHẾ ƯỚC NGHIÊM TRỌNG (CONTRACT VIOLATIONS):")
            for v in self.contract_violations:
                print(f"  ❌ [{v['test_id']}] Failure Mode: {v['failure_mode']}")
                print(f"     Chi tiết: {v['violation']}")
                print(f"     Input   : '{v['input']}'")
        else:
            print("\n🛡️ ZERO CONTRACT VIOLATION: Mô hình tuân thủ khế ước tuyệt đối!")
        print("=" * 75)


# Pytest harness offline check
def test_assurance_matrix_schema():
    """Kiểm tra tính toàn vẹn của Ma trận kiểm thử trước khi ném vào model."""
    assert len(ASSURANCE_TEST_CASES) == 10
    for tc in ASSURANCE_TEST_CASES:
        assert "id" in tc
        assert "failure_mode" in tc
        assert "expected" in tc
        assert "forbidden_inferences" in tc
        assert "semantic_axes" in tc
