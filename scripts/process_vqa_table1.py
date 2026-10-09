"""
Top 0.1% Architecture: Decoupled Multithreaded VQA Knowledge Mining (Table 1: All 6 Shards)
Processes all 29,759 samples across 6 Parquet shards concurrently via HTTP Range requests.
Zero Image Download (Total network transfer ~25 MB instead of 9.8 GB).
"""
import io
import os
import sys
import json
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import pyarrow.parquet as pq

# HTTP Range File Reader for remote columnar access
class HttpRangeFile(io.RawIOBase):
    def __init__(self, url):
        self.session = requests.Session()
        head_resp = self.session.head(url, allow_redirects=True, timeout=15)
        self.url = head_resp.url
        self.length = int(head_resp.headers.get('content-length', 0))
        self.pos = 0
        self.total_bytes_read = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def seek(self, offset, whence=io.SEEK_SET):
        if whence == io.SEEK_SET:
            self.pos = offset
        elif whence == io.SEEK_CUR:
            self.pos += offset
        elif whence == io.SEEK_END:
            self.pos = self.length + offset
        return self.pos

    def tell(self):
        return self.pos

    def readinto(self, b):
        size = len(b)
        if self.pos >= self.length:
            return 0
        end = min(self.pos + size - 1, self.length - 1)
        headers = {'Range': f'bytes={self.pos}-{end}'}
        r = self.session.get(self.url, headers=headers, timeout=30)
        if r.status_code not in (200, 206):
            raise IOError(f'HTTP error {r.status_code} on range {self.pos}-{end}')
        data = r.content
        b[:len(data)] = data
        self.pos += len(data)
        self.total_bytes_read += len(data)
        return len(data)


# Rewritten Hero Image Scoring Function (Top 0.1% Standard)
def score_hero_image(desc: str, full_text: str, poi_name: str) -> tuple[int, list[str]]:
    desc_l = desc.lower()
    score = 0
    reasons = []

    # 1. RÀNG BUỘC ÂM (VETO / PHẠT NẶNG)
    if any(k in desc_l for k in ["ban đêm", "trời tối", "hoàng hôn", "tối màu", "thiếu sáng", "chập tối", "bóng râm tối"]):
        score -= 40
        reasons.append("[-] Trừ 40: Trời tối / hoàng hôn thiếu sáng")
    if any(k in desc_l for k in ["thân cây đổ", "bị chắn", "đường mòn bị", "rác", "che khuất"]):
        score -= 50
        reasons.append("[-] Trừ 50: Vật cản / ảnh lỗi")
    if any(k in desc_l for k in ["người phụ nữ trẻ đang ngồi", "nhóm khoảng 15 người", "hàng người đang đứng", "tạo dáng chụp ảnh", "đứng trước cổng chào"]):
        score -= 20
        reasons.append("[-] Trừ 20: Người chiếm tiền cảnh che khuất công trình")

    # 2. RÀNG BUỘC DƯƠNG (CỘNG ĐIỂM THEO CHỦ THỂ)
    keywords_by_type = [
        "cột cờ", "lá cờ đỏ sao vàng", "cột mốc biên giới", "bệ hình bát giác",
        "lâu đài", "cầu vàng", "làng pháp", "cáp treo", "ngôi chùa", "tượng phật",
        "bãi biển", "thác nước", "đập nước", "hồ nước", "núi đá vôi", "đèo", "lăng tẩm"
    ]
    matched_subject = [k for k in keywords_by_type if k in desc_l]
    if matched_subject:
        score += 35
        reasons.append(f"[+] Cộng 35: Thấy rõ chủ thể ({', '.join(matched_subject[:2])})")

    # Ánh sáng ban ngày & Bầu trời trong xanh
    if any(k in desc_l for k in ["bầu trời trong xanh", "trời xanh trong vắt", "mây trắng bồng bềnh", "ánh nắng"]):
        score += 20
        reasons.append("[+] Cộng 20: Ánh sáng ban ngày, trời trong xanh")

    # Góc máy toàn cảnh / flycam / drone
    if any(k in desc_l for k in ["drone view", "từ trên cao (drone view)", "từ trên cao", "toàn cảnh từ trên cao"]):
        score += 25
        reasons.append("[+] Cộng 25: Góc drone view toàn cảnh bao quát")
    elif any(k in desc_l for k in ["toàn cảnh", "sừng sững", "hùng vĩ"]):
        score += 15
        reasons.append("[+] Cộng 15: Góc toàn cảnh hùng vĩ")

    return score, reasons


PROVINCE_KEYWORDS = {
    "Hà Nội": ["hà nội", "hoàn kiếm", "tây hồ", "ba đình"],
    "Hồ Chí Minh": ["hồ chí minh", "tp.hcm", "sài gòn", "bến thành"],
    "Đà Nẵng": ["đà nẵng", "bà nà", "ngũ hành sơn", "sơn trà"],
    "Điện Biên": ["điện biên", "mường nhé", "a pa chải"],
    "Lạng Sơn": ["lạng sơn", "chi lăng", "mẫu sơn"],
    "Khánh Hòa": ["khánh hòa", "nha trang", "diên khánh", "am chúa", "cam ranh"],
    "Ninh Bình": ["ninh bình", "tràng an", "tam cốc", "bích động", "bái đính"],
    "Quảng Ninh": ["quảng ninh", "hạ long", "cô tô", "yên tử"],
    "Lào Cai": ["lào cai", "sapa", "sa pa", "fansipan", "bắc hà"],
    "Hà Giang": ["hà giang", "mã pí lèng", "đồng văn", "lũng cú"],
    "Lâm Đồng": ["lâm đồng", "đà lạt", "langbiang"],
    "Bình Định": ["bình định", "quy nhơn", "eo gió", "kỳ co"],
    "Phú Yên": ["phú yên", "gành đá đĩa", "bãi môn", "mũi điện"],
    "Quảng Nam": ["quảng nam", "hội an", "mỹ sơn"],
    "Thừa Thiên Huế": ["huế", "thừa thiên huế", "sông hương", "kinh thành"],
    "Kiên Giang": ["kiên giang", "phú quốc", "nam du"],
    "Bà Rịa - Vũng Tàu": ["vũng tàu", "bà rịa", "côn đảo"],
    "An Giang": ["an giang", "châu đốc", "trà sư"],
    "Cần Thơ": ["cần thơ", "cái răng", "ninh kiều"]
}

STOPWORDS = {"bức ảnh này cho tôi", "nó", "ảnh này", "địa điểm", "vị trí", "đây", "địa danh chưa xác định", "bức ảnh", "khung cảnh", "hình ảnh"}

# Semantic Metadata Extractor from QA turns
def parse_conversations(row_id: str, convs_raw) -> dict:
    if isinstance(convs_raw, str):
        convs = json.loads(convs_raw)
    else:
        convs = convs_raw

    full_text = " ".join([t.get("content", "") for t in convs])
    full_text_lower = full_text.lower()
    visual_desc = convs[1].get("content", "") if len(convs) > 1 else ""

    poi_name = None
    province = None
    coords = None

    for i in range(len(convs) - 1):
        q = convs[i].get("content", "").strip().lower()
        a = convs[i+1].get("content", "").strip()
        
        if any(term in q for term in ["đây là vị trí gì", "tên đầy đủ và vị trí", "đây là đâu", "tên của nơi này"]) and not poi_name:
            clean_a = a.split(",")[0].strip()
            if clean_a.lower() not in STOPWORDS and len(clean_a) > 2:
                poi_name = clean_a
        
        m_q = re.search(r"(?:dữ liệu nổi bật về|dữ liệu về|thông tin về|chi tiết chung về|biết gì về|diễn tả)\s+([A-ZÀ-Ỹa-zà-ỹ0-9\s–\-\'\"]+?)(?:[\.\?\:]|$)", q)
        if m_q and not poi_name:
            cand = m_q.group(1).strip().strip('"').strip("'")
            if cand.lower() not in STOPWORDS and len(cand) > 2:
                poi_name = cand

        if any(term in q for term in ["tọa lạc ở đâu", "vị trí (thành phố)", "thuộc tỉnh", "ở tỉnh nào"]) and not province:
            province = a.split(",")[0].strip()
            
        if "tọa độ" in q and not coords:
            m = re.search(r"(\d{1,2}\.\d{3,6})\s*,\s*(\d{2,3}\.\d{3,6})", a)
            if m:
                coords = [float(m.group(1)), float(m.group(2))]

    if not poi_name or poi_name.lower() in STOPWORDS:
        m_vis = re.search(r"(?:bức ảnh chụp|ảnh chụp)\s+(?:từ trên cao|toàn cảnh|cận cảnh|góc thấp|từ góc thấp)?\s*(?:khu du lịch|quần thể|cột cờ|cột mốc|bãi biển|chùa|đền|đập|hồ|cầu|đèo)?\s*([A-ZÀ-Ỹ][A-ZÀ-Ỹa-zà-ỹ0-9\s–\-]+?)(?:,|\.|\s+với|\s+nằm|\s+tại|\s+ở)", visual_desc)
        if m_vis:
            cand = m_vis.group(1).strip()
            if cand.lower() not in STOPWORDS and len(cand) > 3:
                poi_name = cand

    if not poi_name or poi_name.lower() in STOPWORDS:
        poi_name = "Địa danh chưa xác định"
    else:
        poi_name = poi_name.split(",")[0].strip()

    # Nhận diện Tỉnh dựa trên từ điển địa danh
    clean_province = province or "Việt Nam"
    for prov_name, kws in PROVINCE_KEYWORDS.items():
        if any(kw in full_text_lower for kw in kws):
            clean_province = prov_name
            break

    # Đa chiều thuộc tính
    climates = [kw for kw in ["mát mẻ quanh năm", "se lạnh", "sương mù", "nhiệt độ thấp", "nắng ấm", "hoàng hôn", "bình minh", "trong xanh"] if kw in full_text_lower]
    terrain = [kw for kw in ["đỉnh núi", "sườn núi", "đá vôi", "hồ nước", "bờ đập", "thung lũng", "ven biển", "bãi biển", "rừng", "núi chúa", "thác nước", "đèo", "vực"] if kw in full_text_lower]
    culture = [kw for kw in ["ngã ba biên giới", "di tích lịch sử", "làng pháp", "chùa cổ", "đền thờ", "thánh mẫu", "quân đội", "kháng chiến", "kiến trúc gothic", "lăng tẩm"] if kw in full_text_lower]
    activities = [kw for kw in ["cáp treo", "đi bộ", "check-in", "nghỉ dưỡng", "vui chơi giải trí", "thờ cúng", "chụp ảnh", "cầu vàng", "săn mây", "trekking", "tắm biển", "cắm trại"] if kw in full_text_lower]
    viewpoints = [kw for kw in ["toàn cảnh từ trên cao", "toàn cảnh", "chụp cận cảnh", "chụp từ phía sau", "drone view", "góc nhìn từ trên cao"] if kw in visual_desc.lower()]

    score, reasons = score_hero_image(visual_desc, full_text, poi_name)

    return {
        "id": row_id,
        "poi_name": poi_name,
        "province": clean_province,
        "coords": coords,
        "visual_desc": visual_desc,
        "climates": list(set(climates)),
        "terrain": list(set(terrain)),
        "culture": list(set(culture)),
        "activities": list(set(activities)),
        "viewpoints": list(set(viewpoints)),
        "hero_score": score,
        "hero_reasons": reasons
    }


def fetch_and_parse_shard(shard_idx: int) -> list[dict]:
    url = f"https://huggingface.co/datasets/Qhuy204/VQA_VN_Destination/resolve/main/data/train-{shard_idx:05d}-of-00006.parquet"
    print(f"[{shard_idx}/5] Opening shard {shard_idx} over HTTP range...")
    t0 = time.time()
    hf_file = HttpRangeFile(url)
    pf = pq.ParquetFile(hf_file)
    tbl = pf.read(columns=['id', 'conversations'])
    df = tbl.to_pandas()
    
    parsed = []
    for _, row in df.iterrows():
        it = parse_conversations(row['id'], row['conversations'])
        parsed.append(it)
    
    elapsed = time.time() - t0
    mb = hf_file.total_bytes_read / (1024 * 1024)
    print(f"[{shard_idx}/5] Completed {len(parsed)} rows in {elapsed:.1f}s ({mb:.2f} MB transferred)")
    return parsed


def run_full_pipeline():
    print("=" * 70)
    print("BẮT ĐẦU QUÉT TOÀN BỘ 6 SHARDS DATASET VQA (29,759 MẪU)")
    print("=" * 70)
    start_time = time.time()

    all_records = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(fetch_and_parse_shard, i): i for i in range(6)}
        for future in as_completed(futures):
            shard_idx = futures[future]
            try:
                records = future.result()
                all_records.extend(records)
            except Exception as e:
                print(f"[-] Error processing shard {shard_idx}: {e}")

    total_time = time.time() - start_time
    print(f"\n>>> ĐÃ XỬ LÝ TOÀN BỘ {len(all_records):,} MẪU TRONG {total_time:.1f}s! <<<")

    # 1. Ghi BẢNG 1 TOÀN BỘ ra JSONL
    out_table1_path = "data/vqa_table1_conversations.jsonl"
    os.makedirs("data", exist_ok=True)
    with open(out_table1_path, "w", encoding="utf-8") as f:
        for r in all_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"-> Đã lưu Bảng 1 ({len(all_records):,} dòng) tại: {out_table1_path}")

    # 2. GOM CỤM TOÀN BỘ ĐỊA DANH
    clusters = defaultdict(list)
    for it in all_records:
        name = it['poi_name'].strip()
        # Chuẩn hóa tên các cụm lớn
        if "a pa chải" in name.lower(): name = "Cột cờ A Pa Chải (Cực Tây)"
        elif "bà nà hills" in name.lower() or "sun world" in name.lower(): name = "Bà Nà Hills"
        elif "cầu vàng" in name.lower(): name = "Cầu Vàng (Bà Nà Hills)"
        elif "am chúa" in name.lower(): name = "Khu di tích & Đập Am Chúa"
        elif "chi lăng" in name.lower(): name = "Khu di tích Ải Chi Lăng"
        elif "bích động" in name.lower() or "tam cốc" in name.lower(): name = "Tam Cốc - Chùa Bích Động"
        elif "fansipan" in name.lower() or "phan xi păng" in name.lower(): name = "Đỉnh Fansipan"
        elif "hạ long" in name.lower() or "vịnh hạ long" in name.lower(): name = "Vịnh Hạ Long"
        elif "mã pí lèng" in name.lower(): name = "Đèo Mã Pí Lèng"
        elif "eo gió" in name.lower(): name = "Eo Gió (Quy Nhơn)"
        elif "kỳ co" in name.lower(): name = "Bãi biển Kỳ Co"
        elif "gành đá đĩa" in name.lower() or "ghềnh đá đĩa" in name.lower(): name = "Gành Đá Đĩa"
        elif "cửa đại" in name.lower(): name = "Bãi biển Cửa Đại"
        
        clusters[name].append(it)

    clustered_places = {}
    for c_name, items in clusters.items():
        if c_name == "Địa danh chưa xác định" and len(items) > 100:
            continue
        best_img = max(items, key=lambda x: x['hero_score'])
        coords = next((it['coords'] for it in items if it['coords']), None)
        
        clustered_places[c_name] = {
            "canonical_name": c_name,
            "province": items[0]['province'],
            "coords": coords,
            "total_photos": len(items),
            "all_photo_ids": [it['id'] for it in items],
            "best_hero_image_id": best_img['id'],
            "hero_score": best_img['hero_score'],
            "hero_selection_reasons": best_img['hero_reasons'],
            "hero_visual_desc": best_img['visual_desc'],
            "aggregated_climates": list(set(c for it in items for c in it['climates'])),
            "aggregated_terrain": list(set(t for it in items for t in it['terrain'])),
            "aggregated_culture": list(set(cu for it in items for cu in it['culture'])),
            "aggregated_activities": list(set(a for it in items for a in it['activities'])),
        }

    # Sắp xếp các cụm theo số lượng ảnh nhiều nhất
    sorted_places = dict(sorted(clustered_places.items(), key=lambda x: x[1]['total_photos'], reverse=True))

    out_cluster_path = "data/vqa_clustered_places.json"
    with open(out_cluster_path, "w", encoding="utf-8") as f:
        json.dump(sorted_places, f, ensure_ascii=False, indent=2)
    print(f"-> Đã lưu Bảng Gom Cụm ({len(sorted_places)} địa danh) tại: {out_cluster_path}\n")

    # In báo cáo Top 10 địa danh có nhiều ảnh nhất
    print("=" * 75)
    print(f"TOP ĐỊA DANH TIÊU BIỂU TRÊN TOÀN BỘ DATASET (TỔNG {len(sorted_places)} ĐỊA DANH)")
    print("=" * 75)
    for idx, (c_name, data) in enumerate(list(sorted_places.items())[:12], 1):
        print(f"[{idx:02d}] 📍 {c_name.upper()} ({data['province']})")
        print(f"     📸 {data['total_photos']} ảnh | GPS: {data['coords']}")
        print(f"     🌤️ Khí hậu: {data['aggregated_climates'][:4]} | 🏔️ Địa hình: {data['aggregated_terrain'][:4]}")
        print(f"     🎯 Hoạt động: {data['aggregated_activities'][:4]}")
        print(f"     ⭐ ẢNH ĐẠI DIỆN: {data['best_hero_image_id']} (Điểm: {data['hero_score']})")
        print(f"     📖 Mô tả: {data['hero_visual_desc'][:120]}...")
        print("-" * 75)


if __name__ == "__main__":
    run_full_pipeline()
