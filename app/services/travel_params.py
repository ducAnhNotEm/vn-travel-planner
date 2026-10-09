"""
NGUỒN SỰ THẬT DUY NHẤT cho tham số vận hành (Single Source of Truth).

Mọi service (road_trip_service, travel_calculator, router) và tài liệu (AGENTS.md §4, §10)
PHẢI đọc từ file này. Muốn đổi ngưỡng → đổi ở đây, rồi cập nhật AGENTS.md cho khớp.
"""

# ── Thời lượng chuyến đi ──────────────────────────────────────────────────────
MIN_TRIP_DAYS = 1
MAX_TRIP_DAYS = 14          # Đủ cho road trip xuyên Việt (≈6 ngày lái khứ hồi + tham quan)

# ── Road trip & An toàn sinh học tài xế ───────────────────────────────────────
ROAD_TRIP_THRESHOLD_KM = 300.0     # Dưới ngưỡng: đi thẳng trong ngày, không tách ngày lái
MAX_CONTINUOUS_DRIVE_HRS = 3.5     # Lái liên tục tối đa trước khi bắt buộc dừng nghỉ
MANDATORY_BREAK_MINS = 30
MAX_DAILY_DRIVE_HRS = 8.0
SAFE_DAILY_KM = {"car": 400, "motorbike": 280, "van": 380}   # Km đường bộ an toàn/ngày
LONG_HAUL_TORTUOSITY = 1.35        # Hệ số đường bộ/chim bay cho chặng liên tỉnh dài

# ── Khách sạn ─────────────────────────────────────────────────────────────────
HOTEL_FAR_ONE_WAY_KM = 35.0        # Từ ngưỡng này mới báo "xa khách sạn" (AGENTS §4: 30–40 km)
HOTEL_MIN_SAVING_KM = 20.0         # Đổi khách sạn chỉ khi tiết kiệm ≥ ngưỡng này (AGENTS §4)
DEFAULT_ROOM_RATE_VND = 750_000    # Chỉ dùng khi khách chưa chọn khách sạn có giá trong DB
