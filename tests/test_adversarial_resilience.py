"""
ADVERSARIAL RESILIENCE & STRESS TEST SUITE (PYTEST COMPATIBLE)
Standard: Top 0.1% Elite Engineering Standard & AGENTS.md
Harness: Challenger 2
"""

import os
import sys
import time
import math
import json
import threading
from typing import Dict, Any, List
from unittest.mock import patch, MagicMock

import pytest
import requests
from fastapi.testclient import TestClient

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.main import app
from app.services.flight_transit_service import (
    get_ground_directions,
    enrich_plan_with_flight_transit,
    build_flight_transit_pipeline,
    find_nearest_airport,
    find_gateway_airport,
    haversine_distance,
    decode_polyline,
    generate_flight_arc,
    LRUCache,
    _DIRECTIONS_CACHE,
    GroundTransitLeg,
    FlightLeg,
    DoorToDoorFlightPipeline
)
from app.services.travel_calculator import generate_multi_day_plan

client = TestClient(app)


class TestAdversarialResilience:
    """Stress tests on malformed API keys, upstream crashes, network timeouts, and HTML responses"""

    @pytest.fixture(autouse=True)
    def clean_cache(self):
        _DIRECTIONS_CACHE.clear()

    def test_explicit_garbage_api_key_geodesic_fallback(self):
        leg = get_ground_directions(
            origin_coords=(21.0285, 105.8542),
            dest_coords=(21.2178, 105.8026),
            vehicle="car",
            origin_name="Hà Nội Center",
            dest_name="Noi Bai Airport",
            api_key="garbage_key_999"
        )
        assert isinstance(leg, GroundTransitLeg)
        assert leg.is_fallback is True
        assert len(leg.polyline) == 2
        assert leg.polyline[0] == [21.0285, 105.8542]
        assert leg.polyline[1] == [21.2178, 105.8026]
        assert leg.distance_km > 20.0
        assert leg.duration_minutes > 15
        assert len(leg.options) == 3

    @pytest.mark.parametrize("status_code", [401, 403, 500, 502, 503])
    def test_upstream_http_status_errors(self, status_code):
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.json.return_value = {"error": f"HTTP {status_code}"}
        with patch("app.services.flight_transit_service.requests.get", return_value=mock_resp):
            leg = get_ground_directions(
                origin_coords=(16.0611, 108.2208),
                dest_coords=(15.8800, 108.3380),
                api_key="key_err"
            )
            assert leg.is_fallback is True
            assert len(leg.polyline) == 2
            assert leg.distance_km > 0

    @pytest.mark.parametrize("exc", [
        requests.exceptions.ConnectTimeout("Connect timeout"),
        requests.exceptions.ReadTimeout("Read timeout"),
        requests.exceptions.ConnectionError("DNS failed"),
        requests.exceptions.ChunkedEncodingError("Stream broken")
    ])
    def test_network_connectivity_exceptions(self, exc):
        with patch("app.services.flight_transit_service.requests.get", side_effect=exc):
            leg = get_ground_directions(
                origin_coords=(10.7769, 106.7009),
                dest_coords=(10.8185, 106.6588),
                api_key="key_exc"
            )
            assert leg.is_fallback is True
            assert len(leg.polyline) == 2

    def test_upstream_html_response_handling(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = json.JSONDecodeError("Expecting value", "<html>502 Bad Gateway</html>", 0)
        with patch("app.services.flight_transit_service.requests.get", return_value=mock_resp):
            leg = get_ground_directions(
                origin_coords=(21.0285, 105.8542),
                dest_coords=(21.2178, 105.8026),
                api_key="key_html"
            )
            assert leg.is_fallback is True


class TestPerformanceBenchmark:
    """Benchmark tests validating sub-50ms warm cache response and sub-1.5s endpoint latency"""

    def test_lru_cache_p99_latency_under_50ms(self):
        _DIRECTIONS_CACHE.clear()
        coords_a = (21.0285, 105.8542)
        coords_b = (21.2178, 105.8026)
        get_ground_directions(coords_a, coords_b, vehicle="car", api_key="invalid_seed")

        warm_latencies = []
        for _ in range(500):
            t0 = time.perf_counter()
            _ = get_ground_directions(coords_a, coords_b, vehicle="car")
            warm_latencies.append((time.perf_counter() - t0) * 1000.0)

        warm_latencies.sort()
        p99 = warm_latencies[int(len(warm_latencies) * 0.99)]
        assert p99 < 50.0, f"P99 latency must be < 50ms, got {p99}ms"

    def test_e2e_api_endpoint_latency_on_warm_cache(self):
        payload = {
            "prompt_keywords": ["Cầu Rồng", "Bà Nà Hills"],
            "days": 2,
            "group_size": 2,
            "vehicle_type": "car",
            "origin_lat": 21.0285,
            "origin_lng": 105.8542,
            "origin_name": "Hà Nội"
        }
        # Warm
        r1 = client.post("/api/plan/calculate", json=payload)
        assert r1.status_code == 200

        t0 = time.perf_counter()
        r2 = client.post("/api/plan/calculate", json=payload)
        dur_ms = (time.perf_counter() - t0) * 1000.0
        assert r2.status_code == 200
        assert dur_ms < 1500.0, f"API endpoint response time must be < 1.5s, got {dur_ms}ms"
        assert dur_ms < 100.0, f"Warm cache response time must be < 100ms, got {dur_ms}ms"


class TestEdgeCaseValidation:
    """Stress tests on endpoint edge cases: null coordinates, out-of-bounds, boundaries, invalid group size"""

    def test_null_coordinates_fallback(self):
        payload = {
            "prompt_keywords": ["Cầu Rồng"],
            "days": 1,
            "group_size": 2,
            "origin_lat": None,
            "origin_lng": None
        }
        resp = client.post("/api/plan/calculate", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "flight_transit" in data
        assert data["flight_transit"]["origin_airport"]["iata_code"] == "HAN"

    def test_out_of_bounds_extreme_coordinates(self):
        payload = {
            "prompt_keywords": ["Cầu Rồng"],
            "days": 1,
            "group_size": 2,
            "origin_lat": 999.0,
            "origin_lng": -500.0
        }
        resp = client.post("/api/plan/calculate", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "flight_transit" in data

    def test_empty_prompt_keywords_rejected_with_400(self):
        payload = {"prompt_keywords": [], "days": 1, "group_size": 2}
        resp = client.post("/api/plan/calculate", json=payload)
        assert resp.status_code == 400

    @pytest.mark.parametrize("group_size,expected_code", [
        (1, 200),
        (20, 200),
        (0, 422),
        (-1, 422),
        (21, 422),
    ])
    def test_group_size_boundary(self, group_size, expected_code):
        payload = {"prompt_keywords": ["Chùa Một Cột"], "days": 1, "group_size": group_size}
        resp = client.post("/api/plan/calculate", json=payload)
        assert resp.status_code == expected_code
