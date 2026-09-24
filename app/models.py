import enum
from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, Text, Enum, JSON
from sqlalchemy.orm import relationship
from app.database import Base

class ProvinceType(str, enum.Enum):
    MAJOR = "MAJOR"       # Thành phố lớn (Hà Nội, TP.HCM, Đà Nẵng, Quảng Ninh...)
    COASTAL = "COASTAL"   # Tỉnh giáp biển
    REGULAR = "REGULAR"   # Tỉnh bình thường

class PlaceCategory(str, enum.Enum):
    HISTORICAL_SITE = "HISTORICAL_SITE"      # Di tích lịch sử / Văn hóa (Lăng Bác, Dinh Độc Lập)
    SPECIALTY_FOOD = "SPECIALTY_FOOD"       # Ẩm thực đặc sản (Cốm, Phở, Bún chả)
    BEACH = "BEACH"                         # Bãi biển (Mỹ Khê, Bãi Sau)
    SEAFOOD_RESTAURANT = "SEAFOOD"          # Nhà hàng hải sản
    RESTAURANT = "RESTAURANT"               # Nhà hàng / Quán ăn thường
    MARKET = "MARKET"                       # Chợ (Chợ Bến Thành, Chợ đêm, Chợ hải sản)
    TEMPLE = "TEMPLE"                       # Chùa / Đền / Miếu
    HOTEL = "HOTEL"                         # Khách sạn / Resort / Homestay
    ATTRACTION = "ATTRACTION"               # Danh thắng / Điểm tham quan chung

class Province(Base):
    __tablename__ = "provinces"

    code = Column(Integer, primary_key=True, index=True)      # PK: 48 (Đà Nẵng), 27 (Bắc Ninh)
    name = Column(String(255), nullable=False)               # "Thành phố Đà Nẵng"
    codename = Column(String(100), nullable=False)           # "da_nang"
    city_name = Column(String(100))                           # "Da Nang"
    division_type = Column(String(50))                       # "thành phố trung ương", "tỉnh"
    
    is_in_project = Column(Boolean, default=True)             # True cho 34 tỉnh của dự án
    province_type = Column(Enum(ProvinceType), default=ProvinceType.REGULAR)
    has_sea = Column(Boolean, default=False)
    scrape_limit = Column(Integer, default=20)

    # Quan hệ 1 Tỉnh -> Nhiều Xã/Phường
    wards = relationship("Ward", back_populates="province", cascade="all, delete-orphan")
    # Quan hệ 1 Tỉnh -> Nhiều Địa điểm
    places = relationship("Place", back_populates="province", cascade="all, delete-orphan")

class Ward(Base):
    __tablename__ = "wards"

    code = Column(Integer, primary_key=True, index=True)     # PK: 4, 8
    province_code = Column(Integer, ForeignKey("provinces.code", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)               # "Phường Ba Đình"
    codename = Column(String(100))                             # "phuong_ba_dinh"
    division_type = Column(String(50))                       # "phường", "xã"

    # Quan hệ N Xã -> 1 Tỉnh
    province = relationship("Province", back_populates="wards")
    # Quan hệ 1 Xã -> Nhiều Địa điểm
    places = relationship("Place", back_populates="ward")

class Place(Base):
    __tablename__ = "places"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    google_place_id = Column(String(100), unique=True, index=True)
    
    # Khóa ngoại liên kết Tỉnh & Xã
    province_code = Column(Integer, ForeignKey("provinces.code", ondelete="CASCADE"), nullable=False)
    ward_code = Column(Integer, ForeignKey("wards.code", ondelete="SET NULL"), nullable=True)

    name = Column(String(255), nullable=False)
    category = Column(Enum(PlaceCategory), nullable=False)    # Phân loại rõ ràng
    
    # Nhận biết Địa điểm Nổi tiếng / Must-Visit
    is_must_visit = Column(Boolean, default=False)
    badge_label = Column(String(100), nullable=True)          # "⭐ Di tích Lịch sử Quốc gia"

    # Tọa độ GPS phục vụ Thuật toán Nearest Neighbor
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    
    address = Column(String(500))
    rating = Column(Float)
    review_count = Column(Integer)
    image_url = Column(Text)
    
    typical_time_spent = Column(String(100))                  # "45 min to 2.5 hr"
    popular_times = Column(JSON, nullable=True)                # Lưu mảng giờ bận rộn
    price_range = Column(String(100), nullable=True)           # "$67 - $95" hoặc "500.000đ - 1.800.000đ"
    prices = Column(JSON, nullable=True)                       # Danh sách các mức giá chi tiết từ các bên
    tags = Column(JSON, nullable=True)                         # Mảng thẻ tag ["van_hoa", "checkin"]


    # Quan hệ ngược về Tỉnh và Xã
    province = relationship("Province", back_populates="places")
    ward = relationship("Ward", back_populates="places")
