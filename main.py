import requests

# Link M3U gốc của kho t23-02
SOURCE_URL = "https://raw.githubusercontent.com/t23-02/bongda/refs/heads/main/bongda.m3u"

# Chế bộ Header "Giấy thông hành" giả danh đang xem trên trình duyệt
REFERER = "https://xem1.gv08.live/"
ORIGIN = "https://xem1.gv08.live"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

def main():
    print("🚀 Đang đi chôm file M3U từ kho t23-02...")
    try:
        res = requests.get(SOURCE_URL, timeout=15)
        res.encoding = 'utf-8'
        lines = res.text.splitlines()
    except Exception as e:
        print(f"❌ Lỗi mạng khi tải file gốc: {e}")
        return

    print("🔪 Đang xào nấu, cắt riêng thịt Gà Vàng và bơm Header...")
    
    out_lines = ["#EXTM3U"]
    current_info = ""
    gavang_count = 0
    
    for line in lines:
        line = line.strip()
        if not line: continue
        
        # Đọc thông tin trận đấu (thẻ EXTINF)
        if line.startswith("#EXTINF"):
            current_info = line
            continue
            
        # Lọc bỏ mấy cái code cũ rác rưởi của file gốc
        if line.startswith("#EXTVLCOPT"):
            continue
            
        # Xử lý khi gặp link video
        if line.startswith("http"):
            if current_info:
                # Dùng radar soi xem có phải họ nhà Gà Vàng không
                info_lower = current_info.lower()
                if "gà vàng" in info_lower or "gavang" in info_lower or "gà " in info_lower or "gv0" in line.lower():
                    
                    # 1. Cắt bỏ râu ria lộn xộn của link gốc (nếu có)
                    clean_url = line.split("|")[0]
                    
                    # 2. XÀO NẤU: Ép cứng Header vào đuôi link bằng dấu |
                    # App OTT nhìn thấy cái này bắt buộc phải ngoan ngoãn giả dạng trình duyệt
                    fixed_url = f"{clean_url}|Referer={REFERER}&Origin={ORIGIN}&User-Agent={USER_AGENT}"
                    
                    # Đóng gói lại thành block mới xịn xò hơn
                    out_lines.append(current_info)
                    out_lines.append(f'#EXTVLCOPT:http-referer={REFERER}')
                    out_lines.append(f'#EXTVLCOPT:http-user-agent={USER_AGENT}')
                    out_lines.append(fixed_url)
                    
                    gavang_count += 1
                    
            # Dọn dẹp để đón trận tiếp theo
            current_info = ""

    # Xuất thành phẩm
    if gavang_count > 0:
        with open("gavang_live.m3u", "w", encoding="utf-8") as f:
            f.write("\n".join(out_lines))
        print(f"🎉 Nấu xong! Trích xuất thành công {gavang_count} trận Gà Vàng đã fix lỗi chạy.")
    else:
        print("❌ Không tìm thấy Gà Vàng trong file gốc, hoặc nó đổi cấu trúc.")

if __name__ == "__main__":
    main()
