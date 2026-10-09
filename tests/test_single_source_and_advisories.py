import pytest
from app.services import travel_params as P
from app.services.travel_calculator import generate_multi_day_plan, evaluate_hotel_switching
from app.services.road_trip_service import check_road_trip_feasibility
from app.services.map_service import get_multi_stop_route, decode_polyline
from app.services.llm_service import explain_hotel_tradeoff, explain_roadtrip_tradeoff
from app.routers.planner_router import TripPlanRequest


def test_travel_params_single_source_of_truth():
    assert P.MIN_TRIP_DAYS == 1
    assert P.MAX_TRIP_DAYS == 14
    assert P.HOTEL_FAR_ONE_WAY_KM == 35.0
    assert P.HOTEL_MIN_SAVING_KM == 20.0
    assert P.ROAD_TRIP_THRESHOLD_KM == 300.0
    assert P.MAX_CONTINUOUS_DRIVE_HRS == 3.5
    assert P.SAFE_DAILY_KM["car"] == 400


def test_trip_plan_request_allows_up_to_14_days():
    req = TripPlanRequest(
        prompt_keywords=["Hồ Gươm"],
        days=14,
        vehicle_type="car"
    )
    assert req.days == 14
    assert req.selected_hotel_id is None


def test_road_trip_feasibility_returns_trade_offs_when_not_feasible():
    # Cự ly 800km, đi trong 2 ngày -> Chắc chắn không khả thi
    res = check_road_trip_feasibility(one_way_km=800.0, total_trip_days=2, vehicle="car")
    assert res["feasible"] is False
    assert res["severity"] == "CRITICAL"
    assert "trade_offs" in res
    assert len(res["trade_offs"]) == 3
    actions = [t["action"] for t in res["trade_offs"]]
    assert "FLY" in actions
    assert "MORE_DAYS" in actions
    assert "CLOSER_DEST" in actions


def test_map_service_multi_stop_route_and_decode():
    coords = [(21.0285, 105.8542), (21.0368, 105.8346)]
    route = get_multi_stop_route(coords, vehicle="car")
    assert "polyline" in route
    assert len(route["polyline"]) >= 2
    # Verify decode polyline
    encoded = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"
    decoded = decode_polyline(encoded)
    assert len(decoded) > 0


def test_generate_multi_day_plan_with_selected_hotel_anchor():
    plan = generate_multi_day_plan(
        prompt_keywords=["Văn Miếu", "Hoàng thành"],
        days=2,
        vehicle_type="car",
        selected_hotel_id=1
    )
    assert "error" not in plan
    assert len(plan["days"]) == 2
    # Verify route_polyline is attached
    for d in plan["days"]:
        assert "route_polyline" in d
    # Verify accommodation cost has hotel info
    assert plan["accommodation_cost"] is not None


def test_claude_llm_service_explanation_zero_crash():
    # Test hotel tradeoff explanation
    hotel_advice = explain_hotel_tradeoff(
        hotel_name="Khách sạn Grand Phoenix",
        day_num=2,
        cluster_name="Chùa Phật Tích",
        distance_km=42.0,
        commute_mins=95,
        alt_hotel_name="Khách sạn Mường Thanh"
    )
    assert len(hotel_advice) > 10

    # Test road trip feasibility explanation
    road_advice = explain_roadtrip_tradeoff(
        origin="Hà Nội",
        dest="Đà Nẵng",
        days=3,
        needed_days=6,
        one_way_km=780.0,
        vehicle="ô tô"
    )
    assert len(road_advice) > 10
