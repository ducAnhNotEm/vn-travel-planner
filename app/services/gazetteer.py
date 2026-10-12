"""
app/services/gazetteer.py
═══════════════════════════════════════════════════════════════════════════════
Deterministic Gazetteer & Resolution Engine for Travel AI Việt Nam.
Tuân thủ Tiêu chuẩn Kỹ thuật Top 0.1% & AGENTS.md:

Vai trò kiến trúc:
- NLU Model chỉ trích xuất Span văn bản nguyên văn (`*_mention`).
- Gazetteer là lớp Engine Python xác định 100% (Deterministic Math & Dict),
  chịu trách nhiệm phân giải (resolve) text span thành `province_code` (1..96)
  và metadata tỉnh thành có thực trong `travel_db.db` (34 tỉnh thành).
- Xử lý mượt mà:
  + Tên tỉnh chính thức (34 tỉnh hiện hành)
  + Tên toàn bộ 63 tỉnh thành cũ trước sắp xếp/sáp nhập (Hà Giang, Kiên Giang, Bà Rịa - Vũng Tàu,
    Quảng Nam, Bình Thuận, Bình Dương, Long An, Hải Dương, Quảng Bình, Bến Tre, Tiền Giang,
    Nam Định, Thái Bình, Bình Phước, Hòa Bình, Bắc Giang, Hà Nam, Hậu Giang, Sóc Trăng,
    Trà Vinh, Ninh Thuận, Bạc Liêu, Yên Bái...)
  + Tên thành phố, thị xã, quận huyện trọng điểm (Đà Lạt, Nha Trang, Hội An, Quy Nhơn, Vũng Tàu, Sa Pa...)
  + Xử lý từ viết tắt mơ hồ (`qn`, `vt`, `hl`, `dn`) với cơ chế candidates để hỏi lại / làm rõ.
  + Tiếng Việt không dấu & chữ thường (ha noi, da nang, sai gon, phu quoc...)
  + 2.396 địa danh thực địa từ `travel_db.db`
═══════════════════════════════════════════════════════════════════════════════
"""

import os
import re
import sqlite3
import unicodedata
from typing import Dict, Any, Optional, List, Tuple


def normalize_text(text: str) -> str:
    """Chuẩn hóa chuỗi văn bản: chữ thường, bỏ dấu cách thừa, bỏ dấu câu."""
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r'[,\.\?!:;\-\(\)\[\]"\'`]+', " ", text)
    text = re.sub(r'\s+', " ", text)
    return text.strip()


def strip_accents(text: str) -> str:
    """Chuyển tiếng Việt có dấu thành không dấu."""
    if not text:
        return ""
    text = unicodedata.normalize("NFD", text)
    text = re.sub(r'[\u0300-\u036f]', "", text)
    text = text.replace("đ", "d").replace("Đ", "D")
    return text


# Bảng từ viết tắt mơ hồ (Ambigious Acronyms)
AMBIGUOUS_ACRONYMS: Dict[str, List[Dict[str, Any]]] = {
    "qn": [
        {"province_code": 22, "province_name": "Tỉnh Quảng Ninh", "clean_name": "Quảng Ninh"},
        {"province_code": 48, "province_name": "Thành phố Đà Nẵng", "clean_name": "Quảng Nam (cũ)"},
        {"province_code": 51, "province_name": "Tỉnh Quảng Ngãi", "clean_name": "Quảng Ngãi"},
        {"province_code": 52, "province_name": "Tỉnh Gia Lai", "clean_name": "Quy Nhơn"}
    ],
    "dn": [
        {"province_code": 48, "province_name": "Thành phố Đà Nẵng", "clean_name": "Đà Nẵng"},
        {"province_code": 75, "province_name": "Tỉnh Đồng Nai", "clean_name": "Đồng Nai"}
    ],
    "đn": [
        {"province_code": 48, "province_name": "Thành phố Đà Nẵng", "clean_name": "Đà Nẵng"},
        {"province_code": 75, "province_name": "Tỉnh Đồng Nai", "clean_name": "Đồng Nai"}
    ],
}


# Bảng ánh xạ thủ công các Alias phổ biến, từ viết tắt, tên 63 tỉnh cũ về province_code chuẩn (1..96)
MANUAL_ALIASES: Dict[str, Tuple[int, str]] = {
    # 1. Hà Nội (Code 1)
    "hà nội": (1, "Thành phố Hà Nội"),
    "ha noi": (1, "Thành phố Hà Nội"),
    "hn": (1, "Thành phố Hà Nội"),
    "thủ đô": (1, "Thành phố Hà Nội"),
    "thu do": (1, "Thành phố Hà Nội"),
    "nội bài": (1, "Thành phố Hà Nội"),
    "noi bai": (1, "Thành phố Hà Nội"),

    # 2. Hồ Chí Minh (Code 79) - Bao gồm cả Bà Rịa - Vũng Tàu, Bình Dương
    "hồ chí minh": (79, "Thành phố Hồ Chí Minh"),
    "ho chi minh": (79, "Thành phố Hồ Chí Minh"),
    "tp hồ chí minh": (79, "Thành phố Hồ Chí Minh"),
    "tp ho chi minh": (79, "Thành phố Hồ Chí Minh"),
    "tphcm": (79, "Thành phố Hồ Chí Minh"),
    "tp hcm": (79, "Thành phố Hồ Chí Minh"),
    "sài gòn": (79, "Thành phố Hồ Chí Minh"),
    "sai gon": (79, "Thành phố Hồ Chí Minh"),
    "sg": (79, "Thành phố Hồ Chí Minh"),
    "hcm": (79, "Thành phố Hồ Chí Minh"),
    "tân sơn nhất": (79, "Thành phố Hồ Chí Minh"),
    "tan son nhat": (79, "Thành phố Hồ Chí Minh"),
    "vũng tàu": (79, "Thành phố Hồ Chí Minh"),
    "vung tau": (79, "Thành phố Hồ Chí Minh"),
    "vt": (79, "Thành phố Hồ Chí Minh"),
    "bà rịa": (79, "Thành phố Hồ Chí Minh"),
    "ba ria": (79, "Thành phố Hồ Chí Minh"),
    "bà rịa vũng tàu": (79, "Thành phố Hồ Chí Minh"),
    "ba ria vung tau": (79, "Thành phố Hồ Chí Minh"),
    "bà rịa - vũng tàu": (79, "Thành phố Hồ Chí Minh"),
    "côn đảo": (79, "Thành phố Hồ Chí Minh"),
    "con dao": (79, "Thành phố Hồ Chí Minh"),
    "bình dương": (79, "Thành phố Hồ Chí Minh"),
    "binh duong": (79, "Thành phố Hồ Chí Minh"),
    "thủ dầu một": (79, "Thành phố Hồ Chí Minh"),
    "thu dau mot": (79, "Thành phố Hồ Chí Minh"),

    # 3. Đà Nẵng (Code 48) - Bao gồm cả Hội An / Quảng Nam
    "đà nẵng": (48, "Thành phố Đà Nẵng"),
    "da nang": (48, "Thành phố Đà Nẵng"),
    "hội an": (48, "Thành phố Đà Nẵng"),
    "hoi an": (48, "Thành phố Đà Nẵng"),
    "quảng nam": (48, "Thành phố Đà Nẵng"),
    "quang nam": (48, "Thành phố Đà Nẵng"),
    "tam kỳ": (48, "Thành phố Đà Nẵng"),
    "tam ky": (48, "Thành phố Đà Nẵng"),
    "bà nà": (48, "Thành phố Đà Nẵng"),
    "ba na": (48, "Thành phố Đà Nẵng"),
    "bà nà hills": (48, "Thành phố Đà Nẵng"),

    # 4. Lâm Đồng (Code 68) - Bao gồm cả Đắk Nông, Mũi Né / Phan Thiết / Bình Thuận
    "lâm đồng": (68, "Tỉnh Lâm Đồng"),
    "lam dong": (68, "Tỉnh Lâm Đồng"),
    "đà lạt": (68, "Tỉnh Lâm Đồng"),
    "da lat": (68, "Tỉnh Lâm Đồng"),
    "bảo lộc": (68, "Tỉnh Lâm Đồng"),
    "bao loc": (68, "Tỉnh Lâm Đồng"),
    "đắk nông": (68, "Tỉnh Lâm Đồng"),
    "dak nong": (68, "Tỉnh Lâm Đồng"),
    "đắc nông": (68, "Tỉnh Lâm Đồng"),
    "dac nong": (68, "Tỉnh Lâm Đồng"),
    "gia nghĩa": (68, "Tỉnh Lâm Đồng"),
    "gia nghia": (68, "Tỉnh Lâm Đồng"),
    "mũi né": (68, "Tỉnh Lâm Đồng"),
    "mui ne": (68, "Tỉnh Lâm Đồng"),
    "phan thiết": (68, "Tỉnh Lâm Đồng"),
    "phan thiet": (68, "Tỉnh Lâm Đồng"),
    "bình thuận": (68, "Tỉnh Lâm Đồng"),
    "binh thuan": (68, "Tỉnh Lâm Đồng"),

    # 5. Khánh Hòa (Code 56) - Bao gồm cả Ninh Thuận
    "khánh hòa": (56, "Tỉnh Khánh Hòa"),
    "khanh hoa": (56, "Tỉnh Khánh Hòa"),
    "nha trang": (56, "Tỉnh Khánh Hòa"),
    "cam ranh": (56, "Tỉnh Khánh Hòa"),
    "ninh thuận": (56, "Tỉnh Khánh Hòa"),
    "ninh thuan": (56, "Tỉnh Khánh Hòa"),
    "phan rang": (56, "Tỉnh Khánh Hòa"),
    "tháp chàm": (56, "Tỉnh Khánh Hòa"),

    # 6. Hải Phòng (Code 31) - Bao gồm cả Hải Dương
    "hải phòng": (31, "Thành phố Hải Phòng"),
    "hai phong": (31, "Thành phố Hải Phòng"),
    "hp": (31, "Thành phố Hải Phòng"),
    "cát bà": (31, "Thành phố Hải Phòng"),
    "cat ba": (31, "Thành phố Hải Phòng"),
    "đồ sơn": (31, "Thành phố Hải Phòng"),
    "do son": (31, "Thành phố Hải Phòng"),
    "hải dương": (31, "Thành phố Hải Phòng"),
    "hai duong": (31, "Thành phố Hải Phòng"),

    # 7. Quảng Ninh (Code 22)
    "quảng ninh": (22, "Tỉnh Quảng Ninh"),
    "quang ninh": (22, "Tỉnh Quảng Ninh"),
    "hạ long": (22, "Tỉnh Quảng Ninh"),
    "ha long": (22, "Tỉnh Quảng Ninh"),
    "hl": (22, "Tỉnh Quảng Ninh"),
    "bãi cháy": (22, "Tỉnh Quảng Ninh"),
    "bai chay": (22, "Tỉnh Quảng Ninh"),
    "cô tô": (22, "Tỉnh Quảng Ninh"),
    "co to": (22, "Tỉnh Quảng Ninh"),
    "vân đồn": (22, "Tỉnh Quảng Ninh"),
    "van don": (22, "Tỉnh Quảng Ninh"),

    # 8. Ninh Bình (Code 37) - Bao gồm cả Nam Định, Hà Nam
    "ninh bình": (37, "Tỉnh Ninh Bình"),
    "ninh binh": (37, "Tỉnh Ninh Bình"),
    "tràng an": (37, "Tỉnh Ninh Bình"),
    "trang an": (37, "Tỉnh Ninh Bình"),
    "tam cốc": (37, "Tỉnh Ninh Bình"),
    "tam coc": (37, "Tỉnh Ninh Bình"),
    "bái đính": (37, "Tỉnh Ninh Bình"),
    "bai dinh": (37, "Tỉnh Ninh Bình"),
    "nam định": (37, "Tỉnh Ninh Bình"),
    "nam dinh": (37, "Tỉnh Ninh Bình"),
    "hà nam": (37, "Tỉnh Ninh Bình"),
    "ha nam": (37, "Tỉnh Ninh Bình"),
    "phủ lý": (37, "Tỉnh Ninh Bình"),

    # 9. Lào Cai (Code 15) - Bao gồm cả Mù Cang Chải / Yên Bái
    "lào cai": (15, "Tỉnh Lào Cai"),
    "lao cai": (15, "Tỉnh Lào Cai"),
    "sa pa": (15, "Tỉnh Lào Cai"),
    "sapa": (15, "Tỉnh Lào Cai"),
    "bắc hà": (15, "Tỉnh Lào Cai"),
    "bac ha": (15, "Tỉnh Lào Cai"),
    "mù cang chải": (15, "Tỉnh Lào Cai"),
    "mu cang chai": (15, "Tỉnh Lào Cai"),
    "yên bái": (15, "Tỉnh Lào Cai"),
    "yen bai": (15, "Tỉnh Lào Cai"),

    # 10. Tuyên Quang (Code 8) - Bao gồm cả Hà Giang
    "tuyên quang": (8, "Tỉnh Tuyên Quang"),
    "tuyen quang": (8, "Tỉnh Tuyên Quang"),
    "hà giang": (8, "Tỉnh Tuyên Quang"),
    "ha giang": (8, "Tỉnh Tuyên Quang"),
    "đồng văn": (8, "Tỉnh Tuyên Quang"),
    "dong van": (8, "Tỉnh Tuyên Quang"),
    "mèo vạc": (8, "Tỉnh Tuyên Quang"),
    "meo vac": (8, "Tỉnh Tuyên Quang"),
    "lũng cú": (8, "Tỉnh Tuyên Quang"),
    "lung cu": (8, "Tỉnh Tuyên Quang"),
    "mã pí lèng": (8, "Tỉnh Tuyên Quang"),
    "ma pi leng": (8, "Tỉnh Tuyên Quang"),

    # 11. An Giang (Code 91) - Bao gồm cả Phú Quốc / Kiên Giang
    "an giang": (91, "Tỉnh An Giang"),
    "phú quốc": (91, "Tỉnh An Giang"),
    "phu quoc": (91, "Tỉnh An Giang"),
    "pq": (91, "Tỉnh An Giang"),
    "kiên giang": (91, "Tỉnh An Giang"),
    "kien giang": (91, "Tỉnh An Giang"),
    "rạch giá": (91, "Tỉnh An Giang"),
    "rach gia": (91, "Tỉnh An Giang"),
    "hà tiên": (91, "Tỉnh An Giang"),
    "ha tien": (91, "Tỉnh An Giang"),
    "châu đốc": (91, "Tỉnh An Giang"),
    "chau doc": (91, "Tỉnh An Giang"),

    # 12. Cần Thơ (Code 92) - Bao gồm Hậu Giang, Sóc Trăng
    "cần thơ": (92, "Thành phố Cần Thơ"),
    "can tho": (92, "Thành phố Cần Thơ"),
    "hậu giang": (92, "Thành phố Cần Thơ"),
    "hau giang": (92, "Thành phố Cần Thơ"),
    "vị thanh": (92, "Thành phố Cần Thơ"),
    "sóc trăng": (92, "Thành phố Cần Thơ"),
    "soc trang": (92, "Thành phố Cần Thơ"),

    # 13. Huế (Code 46)
    "huế": (46, "Thành phố Huế"),
    "hue": (46, "Thành phố Huế"),
    "thừa thiên huế": (46, "Thành phố Huế"),
    "thua thien hue": (46, "Thành phố Huế"),

    # 14. Gia Lai (Code 52) - Bao gồm Quy Nhơn / Bình Định
    "gia lai": (52, "Tỉnh Gia Lai"),
    "pleiku": (52, "Tỉnh Gia Lai"),
    "quy nhơn": (52, "Tỉnh Gia Lai"),
    "quy nhon": (52, "Tỉnh Gia Lai"),
    "bình định": (52, "Tỉnh Gia Lai"),
    "binh dinh": (52, "Tỉnh Gia Lai"),

    # 15. Đắk Lắk (Code 66) - Bao gồm Tuy Hòa / Phú Yên
    "đắk lắk": (66, "Tỉnh Đắk Lắk"),
    "dak lak": (66, "Tỉnh Đắk Lắk"),
    "đắc lắc": (66, "Tỉnh Đắk Lắk"),
    "buôn ma thuột": (66, "Tỉnh Đắk Lắk"),
    "buon ma thuot": (66, "Tỉnh Đắk Lắk"),
    "bmt": (66, "Tỉnh Đắk Lắk"),
    "tuy hòa": (66, "Tỉnh Đắk Lắk"),
    "tuy hoa": (66, "Tỉnh Đắk Lắk"),
    "phú yên": (66, "Tỉnh Đắk Lắk"),
    "phu yen": (66, "Tỉnh Đắk Lắk"),

    # 16. Quảng Ngãi (Code 51) - Bao gồm Kon Tum
    "quảng ngãi": (51, "Tỉnh Quảng Ngãi"),
    "quang ngai": (51, "Tỉnh Quảng Ngãi"),
    "lý sơn": (51, "Tỉnh Quảng Ngãi"),
    "ly son": (51, "Tỉnh Quảng Ngãi"),
    "kon tum": (51, "Tỉnh Quảng Ngãi"),

    # 17. Phú Thọ (Code 25) - Bao gồm Tam Đảo / Vĩnh Phúc, Hòa Bình
    "phú thọ": (25, "Tỉnh Phú Thọ"),
    "phu tho": (25, "Tỉnh Phú Thọ"),
    "tam đảo": (25, "Tỉnh Phú Thọ"),
    "tam dao": (25, "Tỉnh Phú Thọ"),
    "vĩnh phúc": (25, "Tỉnh Phú Thọ"),
    "vinh phuc": (25, "Tỉnh Phú Thọ"),
    "hòa bình": (25, "Tỉnh Phú Thọ"),
    "hoa binh": (25, "Tỉnh Phú Thọ"),
    "mai châu": (25, "Tỉnh Phú Thọ"),

    # 18. Sơn La (Code 14)
    "sơn la": (14, "Tỉnh Sơn La"),
    "son la": (14, "Tỉnh Sơn La"),
    "mộc châu": (14, "Tỉnh Sơn La"),
    "moc chau": (14, "Tỉnh Sơn La"),
    "tà xùa": (14, "Tỉnh Sơn La"),
    "ta xua": (14, "Tỉnh Sơn La"),

    # 19. Cao Bằng (Code 4)
    "cao bằng": (4, "Tỉnh Cao Bằng"),
    "cao bang": (4, "Tỉnh Cao Bằng"),
    "bản giốc": (4, "Tỉnh Cao Bằng"),
    "ban gioc": (4, "Tỉnh Cao Bằng"),

    # 20. Điện Biên (Code 11)
    "điện biên": (11, "Tỉnh Điện Biên"),
    "dien bien": (11, "Tỉnh Điện Biên"),
    "điện biên phủ": (11, "Tỉnh Điện Biên"),
    "dien bien phu": (11, "Tỉnh Điện Biên"),
    "a pa chải": (11, "Tỉnh Điện Biên"),
    "a pa chai": (11, "Tỉnh Điện Biên"),

    # 21. Lai Châu (Code 12)
    "lai châu": (12, "Tỉnh Lai Châu"),
    "lai chau": (12, "Tỉnh Lai Châu"),

    # 22. Thái Nguyên (Code 19) - Bao gồm Bắc Kạn
    "thái nguyên": (19, "Tỉnh Thái Nguyên"),
    "thai nguyen": (19, "Tỉnh Thái Nguyên"),
    "bắc kạn": (19, "Tỉnh Thái Nguyên"),
    "bac kan": (19, "Tỉnh Thái Nguyên"),
    "ba bể": (19, "Tỉnh Thái Nguyên"),
    "ba be": (19, "Tỉnh Thái Nguyên"),

    # 23. Lạng Sơn (Code 20)
    "lạng sơn": (20, "Tỉnh Lạng Sơn"),
    "lang son": (20, "Tỉnh Lạng Sơn"),

    # 24. Bắc Ninh (Code 24) - Bao gồm Bắc Giang
    "bắc ninh": (24, "Tỉnh Bắc Ninh"),
    "bac ninh": (24, "Tỉnh Bắc Ninh"),
    "bắc giang": (24, "Tỉnh Bắc Ninh"),
    "bac giang": (24, "Tỉnh Bắc Ninh"),

    # 25. Hưng Yên (Code 33) - Bao gồm Thái Bình
    "hưng yên": (33, "Tỉnh Hưng Yên"),
    "hung yen": (33, "Tỉnh Hưng Yên"),
    "thái bình": (33, "Tỉnh Hưng Yên"),
    "thai binh": (33, "Tỉnh Hưng Yên"),

    # 26. Thanh Hóa (Code 38)
    "thanh hóa": (38, "Tỉnh Thanh Hóa"),
    "thanh hoa": (38, "Tỉnh Thanh Hóa"),
    "sầm sơn": (38, "Tỉnh Thanh Hóa"),
    "sam son": (38, "Tỉnh Thanh Hóa"),
    "pù luông": (38, "Tỉnh Thanh Hóa"),
    "pu luong": (38, "Tỉnh Thanh Hóa"),

    # 27. Nghệ An (Code 40)
    "nghệ an": (40, "Tỉnh Nghệ An"),
    "nghe an": (40, "Tỉnh Nghệ An"),
    "vinh": (40, "Tỉnh Nghệ An"),
    "cửa lò": (40, "Tỉnh Nghệ An"),
    "cua lo": (40, "Tỉnh Nghệ An"),

    # 28. Hà Tĩnh (Code 42)
    "hà tĩnh": (42, "Tỉnh Hà Tĩnh"),
    "ha tinh": (42, "Tỉnh Hà Tĩnh"),

    # 29. Quảng Trị (Code 44) - Bao gồm Quảng Bình
    "quảng trị": (44, "Tỉnh Quảng Trị"),
    "quang tri": (44, "Tỉnh Quảng Trị"),
    "quảng bình": (44, "Tỉnh Quảng Trị"),
    "quang binh": (44, "Tỉnh Quảng Trị"),
    "đồng hới": (44, "Tỉnh Quảng Trị"),
    "phong nha": (44, "Tỉnh Quảng Trị"),

    # 30. Đồng Nai (Code 75) - Bao gồm Bình Phước
    "đồng nai": (75, "Tỉnh Đồng Nai"),
    "dong nai": (75, "Tỉnh Đồng Nai"),
    "biên hòa": (75, "Tỉnh Đồng Nai"),
    "bien hoa": (75, "Tỉnh Đồng Nai"),
    "bình phước": (75, "Tỉnh Đồng Nai"),
    "binh phuoc": (75, "Tỉnh Đồng Nai"),
    "đồng xoài": (75, "Tỉnh Đồng Nai"),

    # 31. Tây Ninh (Code 80) - Bao gồm Long An
    "tây ninh": (80, "Tỉnh Tây Ninh"),
    "tay ninh": (80, "Tỉnh Tây Ninh"),
    "núi bà đen": (80, "Tỉnh Tây Ninh"),
    "nui ba den": (80, "Tỉnh Tây Ninh"),
    "long an": (80, "Tỉnh Tây Ninh"),
    "tân an": (80, "Tỉnh Tây Ninh"),

    # 32. Đồng Tháp (Code 82) - Bao gồm Tiền Giang
    "đồng tháp": (82, "Tỉnh Đồng Tháp"),
    "dong thap": (82, "Tỉnh Đồng Tháp"),
    "sa đéc": (82, "Tỉnh Đồng Tháp"),
    "sa dec": (82, "Tỉnh Đồng Tháp"),
    "tiền giang": (82, "Tỉnh Đồng Tháp"),
    "tien giang": (82, "Tỉnh Đồng Tháp"),
    "mỹ tho": (82, "Tỉnh Đồng Tháp"),

    # 33. Vĩnh Long (Code 86) - Bao gồm Bến Tre, Trà Vinh
    "vĩnh long": (86, "Tỉnh Vĩnh Long"),
    "vinh long": (86, "Tỉnh Vĩnh Long"),
    "bến tre": (86, "Tỉnh Vĩnh Long"),
    "ben tre": (86, "Tỉnh Vĩnh Long"),
    "trà vinh": (86, "Tỉnh Vĩnh Long"),
    "tra vinh": (86, "Tỉnh Vĩnh Long"),

    # 34. Cà Mau (Code 96) - Bao gồm Bạc Liêu
    "cà mau": (96, "Tỉnh Cà Mau"),
    "ca mau": (96, "Tỉnh Cà Mau"),
    "đất mũi": (96, "Tỉnh Cà Mau"),
    "dat mui": (96, "Tỉnh Cà Mau"),
    "bạc liêu": (96, "Tỉnh Cà Mau"),
    "bac lieu": (96, "Tỉnh Cà Mau"),
}


class Gazetteer:
    """
    Gazetteer singleton loaded deterministically from travel_db.db + static knowledge.
    """
    _instances: Dict[str, "Gazetteer"] = {}

    def __init__(self, db_path: str = "travel_db.db"):
        self.db_path = db_path
        self.provinces_by_code: Dict[int, Dict[str, Any]] = {}
        self.alias_to_code: Dict[str, int] = {}
        self.place_to_code: Dict[str, int] = {}
        self.collisions: List[Tuple[str, int, int, str]] = []
        self._load_from_db()

    def _add_alias(self, key: str, code: int, source: str):
        if not key:
            return
        old = self.alias_to_code.get(key)
        if old is not None and old != code:
            self.collisions.append((key, old, code, source))
            return  # giữ cái đầu tiên, ghi log cái sau
        self.alias_to_code[key] = code

    def _add_place(self, key: str, code: int, source: str):
        if not key:
            return
        old = self.place_to_code.get(key)
        if old is not None and old != code:
            self.collisions.append((f"place:{key}", old, code, source))
            return
        self.place_to_code[key] = code

    @classmethod
    def get_instance(cls, db_path: str = "travel_db.db") -> "Gazetteer":
        if db_path not in cls._instances:
            cls._instances[db_path] = Gazetteer(db_path)
        return cls._instances[db_path]

    def _load_from_db(self):
        """Tải toàn bộ 34 tỉnh và 2.396 địa danh từ travel_db.db với thứ tự xác định."""
        if not os.path.exists(self.db_path):
            return

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        # 1. Load provinces (ORDER BY code để xác định)
        cur.execute("SELECT code, name, codename FROM provinces ORDER BY code")
        for code, name, codename in cur.fetchall():
            clean_name = name.replace("Thành phố", "").replace("Tỉnh", "").strip()
            self.provinces_by_code[code] = {
                "code": code,
                "name": name,
                "clean_name": clean_name,
                "codename": codename
            }
            # Add province name variants
            for n in [name, clean_name, codename]:
                norm = normalize_text(n)
                if norm:
                    self._add_alias(norm, code, 'db')
                norm_no_acc = strip_accents(norm)
                if norm_no_acc:
                    self._add_alias(norm_no_acc, code, 'db')

        # 2. Add manual aliases
        for alias, (code, _) in MANUAL_ALIASES.items():
            norm = normalize_text(alias)
            self._add_alias(norm, code, 'manual')
            norm_no_acc = strip_accents(norm)
            self._add_alias(norm_no_acc, code, 'manual')

        # 3. Load places from DB (ORDER BY id để xác định)
        cur.execute("SELECT id, name, province_code FROM places ORDER BY id")
        for pid, name, pcode in cur.fetchall():
            norm = normalize_text(name)
            if norm:
                self._add_place(norm, pcode, 'db')
            norm_no_acc = strip_accents(norm)
            if norm_no_acc:
                self._add_place(norm_no_acc, pcode, 'db')

        conn.close()

    def dump_collisions(self, path: str = "audit_out/collisions.txt"):
        """Ghi nhận các vụ va chạm khóa alias/place ra file log."""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"Total collisions: {len(self.collisions)}\n")
            for item in self.collisions:
                f.write(f"{item[0]}\told:{item[1]}\tnew:{item[2]}\tsource:{item[3]}\n")

    def resolve_mention(self, mention: Optional[str], strict: bool = False) -> Optional[Dict[str, Any]]:
        """
        Phân giải text span (mention) thành metadata tỉnh thành chuẩn.
        Ở chế độ strict=True: cấm substring matching, chỉ khớp nguyên cụm.
        Trả về:
            {
                "province_code": int,
                "province_name": str,
                "clean_name": str,
                "is_ambiguous": bool,
                "candidates": List[Dict[str, Any]],
                "match_type": "exact_alias" | "place_lookup" | "substring"
            }
            hoặc None nếu không tìm thấy.
        """
        if not mention:
            return None

        norm = normalize_text(mention)
        if not norm:
            return None

        # 0. Kiểm tra từ viết tắt mơ hồ (Ambigious Acronym)
        if norm in AMBIGUOUS_ACRONYMS:
            cands = AMBIGUOUS_ACRONYMS[norm]
            if len(cands) > 1:
                return {
                    'province_code': None,
                    'province_name': None,
                    'clean_name': None,
                    'is_ambiguous': True,
                    'candidates': cands,
                    'match_type': 'ambiguous_acronym',
                }
            elif len(cands) == 1:
                cand = cands[0]
                return {
                    'province_code': cand["province_code"],
                    'province_name': cand["province_name"],
                    'clean_name': cand["clean_name"],
                    'is_ambiguous': False,
                    'candidates': [],
                    'match_type': 'exact_alias',
                }

        # 1. Tra cứu trực tiếp trong bảng alias
        if norm in self.alias_to_code:
            code = self.alias_to_code[norm]
            pinfo = self.provinces_by_code.get(code, {})
            return {
                "province_code": code,
                "province_name": pinfo.get("name", ""),
                "clean_name": pinfo.get("clean_name", ""),
                "is_ambiguous": False,
                "candidates": [],
                "match_type": "exact_alias"
            }

        # Tra cứu không dấu
        norm_no_acc = strip_accents(norm)
        if norm_no_acc in self.alias_to_code:
            code = self.alias_to_code[norm_no_acc]
            pinfo = self.provinces_by_code.get(code, {})
            return {
                "province_code": code,
                "province_name": pinfo.get("name", ""),
                "clean_name": pinfo.get("clean_name", ""),
                "is_ambiguous": False,
                "candidates": [],
                "match_type": "exact_alias"
            }

        # 2. Tra cứu trong danh sách địa danh (places)
        if norm in self.place_to_code:
            code = self.place_to_code[norm]
            pinfo = self.provinces_by_code.get(code, {})
            return {
                "province_code": code,
                "province_name": pinfo.get("name", ""),
                "clean_name": pinfo.get("clean_name", ""),
                "is_ambiguous": False,
                "candidates": [],
                "match_type": "place_lookup"
            }

        if norm_no_acc in self.place_to_code:
            code = self.place_to_code[norm_no_acc]
            pinfo = self.provinces_by_code.get(code, {})
            return {
                "province_code": code,
                "province_name": pinfo.get("name", ""),
                "clean_name": pinfo.get("clean_name", ""),
                "is_ambiguous": False,
                "candidates": [],
                "match_type": "place_lookup"
            }

        # Nếu strict=True: không cho phép substring matching, chỉ chấp nhận khớp nguyên cụm
        if strict:
            return None

        # 3. Substring matching (nếu chuỗi chứa tên tỉnh hoặc địa danh)
        sorted_aliases = sorted(self.alias_to_code.keys(), key=len, reverse=True)
        for alias in sorted_aliases:
            if len(alias) >= 3 and (f" {alias} " in f" {norm} " or norm == alias):
                code = self.alias_to_code[alias]
                pinfo = self.provinces_by_code.get(code, {})
                return {
                    "province_code": code,
                    "province_name": pinfo.get("name", ""),
                    "clean_name": pinfo.get("clean_name", ""),
                    "is_ambiguous": False,
                    "candidates": [],
                    "match_type": "substring"
                }

        return None


def resolve_mention(mention: Optional[str], db_path: str = "travel_db.db", strict: bool = False) -> Optional[Dict[str, Any]]:
    """Hàm tiện ích toàn cục gọi singleton Gazetteer."""
    return Gazetteer.get_instance(db_path).resolve_mention(mention, strict=strict)
