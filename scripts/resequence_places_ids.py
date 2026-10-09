import sqlite3

def resequence_places():
    db_path = "travel_db.db"
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    print("[*] Bắt đầu sắp xếp lại ID cho bảng places...")
    c.execute("PRAGMA foreign_keys = OFF;")
    conn.commit()

    # 1. Tạo bảng tạm với cấu trúc y hệt
    c.execute("""
    CREATE TABLE places_resequenced (
        id INTEGER NOT NULL, 
        google_place_id VARCHAR(100), 
        province_code INTEGER NOT NULL, 
        ward_code INTEGER, 
        name VARCHAR(255) NOT NULL, 
        category VARCHAR(18) NOT NULL, 
        is_must_visit BOOLEAN, 
        badge_label VARCHAR(100), 
        lat FLOAT NOT NULL, 
        lng FLOAT NOT NULL, 
        address VARCHAR(500), 
        rating FLOAT, 
        review_count INTEGER, 
        image_url TEXT, 
        typical_time_spent VARCHAR(100), 
        popular_times JSON, 
        tags JSON, 
        price_range TEXT, 
        prices TEXT, 
        phone_number VARCHAR(50), 
        website VARCHAR(500), 
        source_provider VARCHAR(50), 
        source_place_id VARCHAR(200), 
        verification_status VARCHAR(20) DEFAULT 'unverified', 
        verified_at VARCHAR(30), 
        google_maps_url VARCHAR(500), 
        PRIMARY KEY (id), 
        FOREIGN KEY(province_code) REFERENCES provinces (code) ON DELETE CASCADE, 
        FOREIGN KEY(ward_code) REFERENCES wards (code) ON DELETE SET NULL
    );
    """)

    # 2. Insert dữ liệu với id tuần tự từ 1 đến N theo thứ tự id cũ
    c.execute("""
    INSERT INTO places_resequenced (
        id, google_place_id, province_code, ward_code, name, category,
        is_must_visit, badge_label, lat, lng, address, rating, review_count,
        image_url, typical_time_spent, popular_times, tags, price_range,
        prices, phone_number, website, source_provider, source_place_id,
        verification_status, verified_at, google_maps_url
    )
    SELECT 
        ROW_NUMBER() OVER (ORDER BY id ASC) as id,
        google_place_id, province_code, ward_code, name, category,
        is_must_visit, badge_label, lat, lng, address, rating, review_count,
        image_url, typical_time_spent, popular_times, tags, price_range,
        prices, phone_number, website, source_provider, source_place_id,
        verification_status, verified_at, google_maps_url
    FROM places;
    """)
    conn.commit()

    # 3. Thay thế bảng cũ
    c.execute("DROP TABLE places;")
    c.execute("ALTER TABLE places_resequenced RENAME TO places;")
    conn.commit()

    # 4. Tái lập Indexes
    c.execute("CREATE UNIQUE INDEX ix_places_google_place_id ON places (google_place_id);")
    c.execute("CREATE INDEX ix_places_id ON places (id);")
    conn.commit()

    c.execute("PRAGMA foreign_keys = ON;")
    conn.commit()

    c.execute("VACUUM;")
    conn.commit()

    # Kiểm tra lại
    c.execute("SELECT COUNT(*), MIN(id), MAX(id) FROM places")
    count, min_id, max_id = c.fetchone()
    conn.close()

    print(f"[+] Hoàn tất! Số lượng: {count}, Min ID: {min_id}, Max ID: {max_id}")
    assert count == 2396
    assert min_id == 1
    assert max_id == 2396

if __name__ == "__main__":
    resequence_places()
