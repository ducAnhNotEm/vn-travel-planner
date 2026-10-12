import pytest
from app.services.gazetteer import Gazetteer

EXPECTED = {
    # mention : tên tỉnh sau sáp nhập (điền sau khi đối chiếu nguồn chính thức)
    'bắc kạn': 'Thái Nguyên',
    'đắk nông': 'Lâm Đồng',
    'hà giang': 'Tuyên Quang',
    'yên bái': 'Lào Cai',
    'bình dương': 'Hồ Chí Minh',
}

@pytest.mark.parametrize('mention,expected', EXPECTED.items())
def test_merge_mapping(mention, expected):
    g = Gazetteer('travel_db.db')
    res = g.resolve_mention(mention)
    assert res is not None, mention + ' không resolve được'
    assert expected.lower() in res['province_name'].lower()

def test_ambiguous_acronym():
    g = Gazetteer('travel_db.db')
    res = g.resolve_mention('qn')
    assert res is not None
    assert res['province_code'] is None
    assert res['is_ambiguous'] is True
