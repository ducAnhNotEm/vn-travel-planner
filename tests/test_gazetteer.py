import pytest
from app.services.gazetteer import resolve_mention, Gazetteer, normalize_text, strip_accents

def test_normalize_and_strip():
    assert normalize_text("  Hà Nội, Việt Nam! ") == "hà nội việt nam"
    assert strip_accents("Đà Nẵng") == "Da Nang"
    assert strip_accents("Phú Quốc") == "Phu Quoc"

def test_resolve_official_provinces():
    res = resolve_mention("Hà Nội")
    assert res is not None
    assert res["province_code"] == 1
    assert "Hà Nội" in res["province_name"]

    res = resolve_mention("Đà Nẵng")
    assert res is not None
    assert res["province_code"] == 48

def test_resolve_abbreviations():
    assert resolve_mention("SG")["province_code"] == 79
    assert resolve_mention("TP.HCM")["province_code"] == 79
    assert resolve_mention("HN")["province_code"] == 1
    assert resolve_mention("PQ")["province_code"] == 91
    # DL va CT da loai khoi alias de tranh nham voi du lich / cong tac
    assert resolve_mention("DL") is None
    # DN va QN la tu viet tat mo ho -> province_code la None
    assert resolve_mention("ĐN")["province_code"] is None
    assert resolve_mention("ĐN")["is_ambiguous"] is True
    assert resolve_mention("QN")["province_code"] is None
    assert resolve_mention("QN")["is_ambiguous"] is True

def test_resolve_historical_provinces_and_popular_cities():
    # Phú Quốc / Kiên Giang -> An Giang (Code 91)
    assert resolve_mention("Phú Quốc")["province_code"] == 91
    assert resolve_mention("Kiên Giang")["province_code"] == 91

    # Hà Giang -> Tuyên Quang (Code 8)
    assert resolve_mention("Hà Giang")["province_code"] == 8

    # Bà Rịa - Vũng Tàu / Côn Đảo -> Hồ Chí Minh (Code 79)
    assert resolve_mention("Bà Rịa")["province_code"] == 79
    assert resolve_mention("Vũng Tàu")["province_code"] == 79
    assert resolve_mention("Côn Đảo")["province_code"] == 79

    # Hội An / Quảng Nam -> Đà Nẵng (Code 48)
    assert resolve_mention("Hội An")["province_code"] == 48
    assert resolve_mention("Quảng Nam")["province_code"] == 48

    # Phan Thiết / Mũi Né -> Lâm Đồng (Code 68)
    assert resolve_mention("Phan Thiết")["province_code"] == 68
    assert resolve_mention("Mũi Né")["province_code"] == 68

def test_resolve_places():
    # Trực tiếp địa danh từ database
    res = resolve_mention("Bãi Sao Phú Quốc")
    assert res is not None
    assert res["province_code"] == 91

    res = resolve_mention("Tháp Trầm Hương")
    assert res is not None
    assert res["province_code"] == 56  # Khánh Hòa

def test_none_or_empty():
    assert resolve_mention(None) is None
    assert resolve_mention("") is None
    assert resolve_mention("   ") is None
    assert resolve_mention("nơi nào đó không có thật xyz123") is None
