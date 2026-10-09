"""
Top 0.1% Architecture: Selective Media Ingestion & WebP Optimization (Step A)
Downloads Top 5 Hero Images from CDN, converts to modern WebP format,
and measures file compression, visual dimensions, and quality.
"""
import os
import io
import time
import requests
from PIL import Image

TARGETS = [
    {
        "offset": 1,
        "id": "IMG000004",
        "name": "Cột mốc A Pa Chải",
        "province": "Điện Biên",
        "filename": "cot_co_a_pa_chai.webp"
    },
    {
        "offset": 48,
        "id": "IMG000052",
        "name": "Khu di tích Ải Chi Lăng",
        "province": "Lạng Sơn",
        "filename": "ai_chi_lang.webp"
    },
    {
        "offset": 91,
        "id": "IMG000094",
        "name": "Làng Pháp Bà Nà Hills",
        "province": "Đà Nẵng",
        "filename": "ba_na_hills.webp"
    },
    {
        "offset": 94,
        "id": "IMG000097",
        "name": "Cầu Vàng Bà Nà Hills",
        "province": "Đà Nẵng",
        "filename": "cau_vang_ba_na.webp"
    },
    {
        "offset": 2604,
        "id": "IMG002834",
        "name": "Bãi biển Cửa Đại",
        "province": "Quảng Nam",
        "filename": "bai_bien_cua_dai.webp"
    }
]

def harvest_and_compress():
    out_dir = "frontend/static/images/places"
    os.makedirs(out_dir, exist_ok=True)
    
    print("=" * 75)
    print("BƯỚC A: THỰC NGHIỆM TẢI & NÉN WEBP CHO TOP 5 ẢNH QUÁN QUÂN")
    print("=" * 75 + "\n")

    results = []

    for item in TARGETS:
        t0 = time.time()
        print(f"[*] Đang lấy dữ liệu {item['name']} ({item['id']})...")
        
        # 1. Lấy URL ảnh từ CDN Hugging Face
        api_url = f"https://datasets-server.huggingface.co/rows?dataset=Qhuy204/VQA_VN_Destination&config=default&split=train&offset={item['offset']}&limit=1"
        resp = requests.get(api_url, timeout=15)
        row_data = resp.json()['rows'][0]['row']
        img_info = row_data['image']
        img_src = img_info['src']
        
        # 2. Tải byte ảnh gốc
        img_resp = requests.get(img_src, timeout=15)
        raw_bytes = img_resp.content
        raw_size_kb = len(raw_bytes) / 1024
        
        # 3. Mở bằng Pillow & Chuyển sang WebP
        pil_img = Image.open(io.BytesIO(raw_bytes))
        width, height = pil_img.size
        orig_format = pil_img.format or "JPEG"
        
        # Đảm bảo hệ màu RGB (tránh lỗi nếu là RGBA hoặc P)
        if pil_img.mode in ("RGBA", "P"):
            pil_img = pil_img.convert("RGB")
            
        save_path = os.path.join(out_dir, item['filename'])
        # Nén WebP chuẩn Web: quality=82, method=6 (nén tối đa)
        pil_img.save(save_path, format="WEBP", quality=82, method=6)
        
        webp_size_kb = os.path.getsize(save_path) / 1024
        saved_pct = ((raw_size_kb - webp_size_kb) / raw_size_kb) * 100
        elapsed = time.time() - t0

        results.append({
            "name": item["name"],
            "province": item["province"],
            "id": item["id"],
            "dimensions": f"{width}x{height}",
            "raw_size": raw_size_kb,
            "webp_size": webp_size_kb,
            "saved_pct": saved_pct,
            "path": save_path,
            "time": elapsed
        })
        print(f"    -> Đã lưu {save_path} ({width}x{height}) | Gốc: {raw_size_kb:.1f} KB -> WebP: {webp_size_kb:.1f} KB (Giảm {saved_pct:.1f}%)\n")

    print("=" * 75)
    print("BÁO CÁO TỔNG KẾT BƯỚC A (TỐI ƯU HÓA HÌNH ẢNH WEBP)")
    print("=" * 75)
    total_raw = sum(r['raw_size'] for r in results)
    total_webp = sum(r['webp_size'] for r in results)
    avg_saved = ((total_raw - total_webp) / total_raw) * 100

    for idx, r in enumerate(results, 1):
        print(f"[{idx}] 📸 {r['name'].upper()} ({r['province']})")
        print(f"     ID: {r['id']} | Kích thước: {r['dimensions']} px")
        print(f"     Dung lượng gốc: {r['raw_size']:.1f} KB ➔ WebP: {r['webp_size']:.1f} KB (-{r['saved_pct']:.1f}%)")
        print(f"     Đường dẫn file: {r['path']}")
        print("-" * 75)

    print(f"\n🎯 TỔNG KẾT: 5 bức ảnh chất lượng cao sau khi nén chỉ còn: {total_webp:.1f} KB (Trung bình {total_webp/5:.1f} KB/ảnh)!")
    print(f"🚀 Tỉ lệ tiết kiệm băng thông: {avg_saved:.1f}% so với ảnh gốc.")

if __name__ == "__main__":
    harvest_and_compress()
