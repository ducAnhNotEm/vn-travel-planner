from fastapi import FastAPI
from app.routers import planner_router

app = FastAPI(
    title="Vietnam Travel Planner API",
    description="Hệ thống lập lịch trình du lịch thông minh, tối ưu đường đi & tính toán chi phí di chuyển, ngân sách chuyến đi.",
    version="1.0.0"
)

app.include_router(planner_router.router)

@app.get("/")
def root():
    return {
        "message": "Welcome to Vietnam Travel Planner API!",
        "docs_url": "/docs"
    }
