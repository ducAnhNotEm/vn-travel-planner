import sys
from app.database import SessionLocal
from app.models import Province, Ward, Place

def show_database_status():
    db = SessionLocal()
    try:
        total_provinces = db.query(Province).count()
        total_wards = db.query(Ward).count()
        total_places = db.query(Place).count()
        
        print("="*60)
        print("               BÁO CÁO TRẠNG THÁI CƠ SỞ DỮ LIỆU")
        print("="*60)
        print(f" Tổng số Tỉnh/Thành phố thuộc dự án: {total_provinces}")
        print(f" Tổng số Xã/Phường đã nạp:         {total_wards}")
        print(f" Tổng số Địa điểm du lịch đã nạp:   {total_places}")
        print("-" * 60)
        
        coastal_count = db.query(Province).filter_by(has_sea=True).count()
        major_count = db.query(Province).filter_by(province_type="MAJOR").count()
        
        print(f" Số Tỉnh/Thành phố CÓ BIỂN:         {coastal_count} / {total_provinces}")
        print(f" Số Đô thị lớn / Trung tâm du lịch: {major_count}")
        print("="*60)
        
    finally:
        db.close()

if __name__ == "__main__":
    show_database_status()
