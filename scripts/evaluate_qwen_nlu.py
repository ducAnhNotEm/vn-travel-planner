"""
VN Travel Planner — Automated Model Evaluation Script (Post-Fine-Tune)
======================================================================
Dùng để benchmark trực tiếp checkpoint Qwen-7B (qua Ollama REST API hoặc vLLM).
Đo lường:
1. Syntactic Correctness (Valid JSON Rate)
2. Semantic Accuracy từng Field (destination, vehicle, flight...)
3. Contract Violation Rate (Phát hiện model vi phạm ranh giới Parser vs Decision Maker)
"""

import json
import requests
import sys
from pathlib import Path

# Thêm đường dẫn gốc
sys.path.append(str(Path(__file__).parent.parent))
from tests.test_semantic_nlu_benchmarks import ASSURANCE_TEST_CASES, ContractAssuranceScorer

OLLAMA_ENDPOINT = "http://localhost:11434/api/chat"
MODEL_NAME = "vn-travel-qwen:7b"

def query_model(user_prompt: str) -> str:
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "system",
                "content": "Bạn là NLU Engine chuyên dụng cho hệ thống Travel AI Việt Nam. Phân tích yêu cầu và trả về duy nhất chuỗi JSON hợp lệ."
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ],
        "stream": False,
        "options": {
            "temperature": 0.0  # Zero temperature cho deterministic inference
        }
    }
    try:
        res = requests.post(OLLAMA_ENDPOINT, json=payload, timeout=10)
        if res.status_code == 200:
            return res.json().get("message", {}).get("content", "").strip()
        else:
            return f"HTTP_ERROR_{res.status_code}"
    except Exception as e:
        return f"CONNECTION_ERROR: {e}"

def run_evaluation():
    print("=" * 75)
    print(f"🚀 BẮT ĐẦU CHẠY MODEL ASSURANCE BENCHMARK TRÊN '{MODEL_NAME}'")
    print("=" * 75)

    scorer = ContractAssuranceScorer()
    parse_errors = 0

    for tc in ASSURANCE_TEST_CASES:
        print(f"Testing [{tc['id']}] ... ", end="", flush=True)
        raw_output = query_model(tc["input"])

        # Làm sạch markdown nếu có
        clean_json_str = raw_output.replace("```json", "").replace("```", "").strip()
        
        try:
            parsed_json = json.loads(clean_json_str)
            scorer.evaluate_sample(tc, parsed_json)
            print("DONE")
        except json.JSONDecodeError:
            print("FAILED (JSON PARSE ERROR)")
            parse_errors += 1

    scorer.print_summary()
    print(f"\n[SYNTACTIC INTEGRITY] Lỗi cú pháp JSON: {parse_errors}/{len(ASSURANCE_TEST_CASES)}")

if __name__ == "__main__":
    run_evaluation()
