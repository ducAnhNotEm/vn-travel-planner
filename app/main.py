from fastapi import FastAPI
from app.routers import planner_router

app = FastAPI(
    title="Vietnam Travel Planner API",
    description="Hệ thống lập lịch trình du lịch thông minh, tối ưu đường đi & tính toán chi phí di chuyển, ngân sách chuyến đi.",
    version="1.0.0"
)

import os
from fastapi.responses import FileResponse

app.include_router(planner_router.router)

FRONTEND_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "index.html")

@app.get("/")
def root():
    if os.path.exists(FRONTEND_PATH):
        return FileResponse(FRONTEND_PATH)
    return {
        "message": "Welcome to Vietnam Travel Planner API!",
        "docs_url": "/docs"
    }

