from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from app.services.travel_calculator import generate_trip_plan

router = APIRouter(prefix="/api/plan", tags=["Travel Planner"])

class TripPlanRequest(BaseModel):
    prompt_keywords: List[str]  # Ví dụ: ["Grand Phoenix", "Chùa Dâu", "Chợ Suối Hoa", "Tân Lương Sơn"]
    vehicle_type: str = "car"   # 'car', 'bus', 'taxi', 'motorbike'

@router.post("/calculate")
def calculate_plan(req: TripPlanRequest):
    if not req.prompt_keywords:
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp danh sách địa điểm cần đi.")
    
    result = generate_trip_plan(req.prompt_keywords, req.vehicle_type)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
        
    return result
