import requests
import re

SOURCE_URL = "https://raw.githubusercontent.com/t23-02/bongda/refs/heads/main/bongda.m3u"
# Giữ User Agent dính liền để Tivi không bị cắt link
USER_AGENT = "Mozilla/5.0_Windows_NT_10.0" 

def main():
    print("🚀 Đang soi kính lúp kéo file M3U từ kho t23-02...")
    try:
        res = requests.get(SOURCE_URL, timeout=15)
        res.encoding = 'utf-8'
        content = res.text
    except Exception as e:
        print(f"❌ Lỗi mạng khi tải file gốc: {e}")
        return

    # CHIÊU MỚI: Bổ toàn bộ file thành từng cục (mỗi cục là 1 trận đấu)
    # Không đọc từng dòng nữa để tránh loạn nhịp
    blocks = content.split("#EXTINF")
    
    out_lines = ["#EXTM3U"]
    gavang_count = 0
    
    # Bỏ qua cục đầu tiên vì nó chỉ là chữ #EXTM3U
    for block in blocks[1:]:
        block_lower = block.lower()
        
        # RADAR TẦM RỘNG: Quét có chữ gà, gavang, hoặc gv (bao gồm gv08, gv1111...)
        if "gà" in block_lower or "gv" in block_lower or "gavang" in block_lower:
            
            # Tách cục này ra thành các dòng để lấy thông tin
            lines = block.strip().splitlines()
            first_line = lines[0] 
            
            # 1. Bắt Logo và Tên trận
            logo_match = re.search(r'tvg-logo="([^"]+)"', first_line)
            logo_url = logo_match.group(1) if logo_match else "https://gavangtv.com/logo.png"
            display_name = first_line.split(",")[-1].strip()
            
            # 2. KHÔNG DÙNG TÊN MIỀN CŨ NỮA - TÌM TÊN MIỀN ĐỘNG TỪ FILE GỐC
            dynamic_referer = "https://gavang.tv/" # Dự phòng
            clean_url = ""
            
            for line in lines:
                # Soi xem thằng tay to kia đang dùng Referer gì (gv1111 hay gv08) thì chôm y hệt
                if "http-referer=" in line.lower():
                    ref_match = re.search(r'http-referer=(https?://[^\s]+)', line, re.I)
                    if ref_match:
                        dynamic_referer = ref_match.group(1)
                        
                # Lấy link stream video
                if line.startswith("http"):
                    # Gọt sạch sẽ cái đuôi | cũ đi để ép đuôi mới của mình vào
                    clean_url = line.split("|")[0].strip()
            
            # 3. Ép gia vị chuẩn chỉ lên Tivi
            if clean_url:
                origin = dynamic_referer.rstrip('/')
                # Cú pháp ép đuôi bất tử cho TiviMate / OTT Navigator
                fixed_url = f"{clean_url}|Referer={dynamic_referer}&Origin={origin}&User-Agent={USER_AGENT}"
                
                out_lines.append(f'#EXTINF:-1 tvg-logo="{logo_url}", {display_name}')
                out_lines.append(f'#EXTVLCOPT:http-referer={dynamic_referer}')
                out_lines.append(f'#EXTVLCOPT:http-user-agent={USER_AGENT}')
                out_lines.append(fixed_url)
                
                gavang_count += 1

    # CHỐT SỔ
    if gavang_count > 0:
        with open("gavang_live.m3u", "w", encoding="utf-8") as f:
            f.write("\n".join(out_lines))
        print(f"🎉 Vét sạch! Trích xuất thành công {gavang_count} trận Gà Vàng.")
    else:
        error_m3u = "#EXTM3U\n#EXTINF:-1 tvg-logo=\"https://gavangtv.com/logo.png\", ❌ Lỗi: File gốc trắng trơn không có Gà Vàng\nhttps://devimages.apple.com.edgekey.net/streaming/examples/bipbop_16x9/bipbop_16x9_variant.m3u8"
        with open("gavang_live.m3u", "w", encoding="utf-8") as f:
            f.write(error_m3u)
        print("❌ Radar không quét được trận nào, đã ép file cảnh báo.")

if __name__ == "__main__":
    main()
