import sqlite3
import re

def preview_and_clean_db(apply_changes=False):
    db_path = "travel_db.db"
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("SELECT id, name, category, province_code FROM places ORDER BY id ASC")
    rows = c.fetchall()

    suffix_pattern = re.compile(r"\s+không$", re.IGNORECASE)

    modifications = []
    for pid, name, cat, prov_code in rows:
        curr = name.strip()
        has_suffix = bool(suffix_pattern.search(curr))
        cleaned_suffix = suffix_pattern.sub("", curr).strip() if has_suffix else curr
        
        # Kiểm tra viết thường toàn bộ
        is_all_lower = cleaned_suffix.islower()
        if is_all_lower:
            # Viết hoa từng từ cho danh từ riêng
            formatted_name = " ".join(w.capitalize() for w in cleaned_suffix.split())
        else:
            formatted_name = cleaned_suffix

        if formatted_name != name:
            modifications.append((pid, name, formatted_name, cat, prov_code))

    print("=" * 80)
    print(f"DANH SÁCH {len(modifications)} ĐỊA DANH SẼ ĐƯỢC LÀM SẠCH:")
    print("=" * 80)
    for pid, old, new, cat, prov in modifications[:30]:
        print(f"ID {pid:4d} | \"{old}\"  ==>  \"{new}\"")
    if len(modifications) > 30:
        print(f"... và {len(modifications) - 30} địa danh khác.")

    # Kiểm tra an toàn cho các địa danh hợp lệ có chữ 'không'
    c.execute("SELECT id, name FROM places WHERE name LIKE '%không%'")
    khong_places = c.fetchall()
    print("\n" + "=" * 80)
    print("KIỂM TRA CÁC ĐỊA DANH HỢP LỆ CÓ CHỮ 'KHÔNG':")
    for k_id, k_name in khong_places:
        mod = next((m for m in modifications if m[0] == k_id), None)
        status = f"Đổi thành '{mod[2]}'" if mod else "GIỮ NGUYÊN AN TOÀN"
        print(f"  ID {k_id:4d}: \"{k_name}\" -> {status}")
    print("=" * 80)

    if apply_changes:
        print(f"\n[*] Đang áp dụng cập nhật {len(modifications)} bản ghi vào travel_db.db...")
        c.execute("BEGIN TRANSACTION;")
        for pid, old, new, _, _ in modifications:
            c.execute("UPDATE places SET name = ? WHERE id = ?", (new, pid))
        conn.commit()
        print("[+] ĐÃ CẬP NHẬT THÀNH CÔNG VÀO DATABASE!")

    conn.close()
    return len(modifications)

if __name__ == "__main__":
    import sys
    apply = "--apply" in sys.argv
    preview_and_clean_db(apply_changes=apply)
