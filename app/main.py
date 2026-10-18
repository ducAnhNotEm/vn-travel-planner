import os
from fastapi import FastAPI
from fastapi.responses import FileResponse
from app.routers import planner_router, map_router, auth_router, chat_router

app = FastAPI(
    title="Vietnam Travel Planner API",
    description="Hệ thống lập lịch trình du lịch thông minh, tối ưu đường đi & tính toán chi phí di chuyển, ngân sách chuyến đi.",
    version="1.0.0"
)

app.include_router(planner_router.router)
app.include_router(map_router.router)
app.include_router(auth_router.router, prefix="/api/auth", tags=["auth"])
app.include_router(chat_router.router, prefix="/api/chat", tags=["chat"])

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
FRONTEND_PATH = os.path.join(FRONTEND_DIR, "index.html")
PLAN_STREAM_PATH = os.path.join(FRONTEND_DIR, "plan_stream.js")

@app.get("/")
def root():
    if os.path.exists(FRONTEND_PATH):
        return FileResponse(FRONTEND_PATH)
    return {
        "message": "Welcome to Vietnam Travel Planner API!",
        "docs_url": "/docs"
    }

@app.get("/plan_stream.js")
def plan_stream_js():
    if os.path.exists(PLAN_STREAM_PATH):
        return FileResponse(PLAN_STREAM_PATH, media_type="application/javascript")
    return {"error": "plan_stream.js not found"}
