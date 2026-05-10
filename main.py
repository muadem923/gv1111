from curl_cffi import requests
from bs4 import BeautifulSoup
import re
import codecs
from datetime import datetime
import json

# --- CẤU HÌNH HỆ THỐNG GÀ VÀNG TV ---
TARGET_URL = "https://xem1.gv08.live"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def parse_json_safely(text):
    """Hàm phụ trợ để parse JSON an toàn từ các chuỗi regex"""
    try:
        # Xóa các ký tự thừa thường gặp khi bóc regex
        text = text.replace('\\"', '"').replace("\\'", "'").replace('\\/', '/')
        return json.loads(text)
    except:
        return None

def extract_match_info_from_html(html):
    """Bóc tách thời gian và Logo từ thẻ meta/html vì URL của Gavang không có thời gian"""
    soup = BeautifulSoup(html, 'html.parser')
    
    # Bóc Logo từ thẻ meta og:image (chính xác nhất cho trang chi tiết)
    logo_url = ""
    meta_img = soup.find('meta', property='og:image')
    if meta_img:
        logo_url = meta_img.get('content', '')

    # Tìm thời gian (Thường nằm trong thẻ span/div có class chứa chữ time hoặc datetime)
    time_str = "[Đang cập nhật]"
    time_sort = datetime.now()
    
    # Dùng regex tìm chuỗi thời gian phổ biến trong HTML (VD: 20:30 15/05/2024)
    time_match = re.search(r'(\d{2}:\d{2})\s+(\d{1,2}/\d{1,2}(?:/\d{4})?)', html)
    if time_match:
        time_str = f"[{time_match.group(1)} {time_match.group(2)}]"
        try:
            # Cố gắng parse để lấy sort_value
            t = time_match.group(1)
            d = time_match.group(2)
            if len(d) <= 5: # Chỉ có ngày/tháng
                d = f"{d}/{datetime.now().year}"
            time_sort = datetime.strptime(f"{t} {d}", "%H:%M %d/%m/%Y")
        except: pass

    return logo_url, time_str, time_sort

def extract_all_m3u8(url):
    """Mổ xẻ trang Gà Vàng để lấy link video và BLV"""
    print(f"  Đang quét luồng: {url}")
    try:
        res = requests.get(url, impersonate="chrome110", timeout=15)
        html = res.text
        streams = []
        seen = set()

        # --- CHIẾN THUẬT 1: VÉT CẠN JSON/NEXT_DATA ---
        # Tìm các mảng chứa tên BLV và Link m3u8 (Rất phổ biến ở Gavang/Xoilac)
        # Regex tìm các block JSON có chứa '.m3u8'
        json_blocks = re.findall(r'\{[^{]*?\.m3u8[^{]*?\}', html, re.IGNORECASE)
        for block in json_blocks:
            # Cố gắng tìm Name/Tên BLV trong block đó
            name_match = re.search(r'["\'](?:name|title|server_name)["\']\s*:\s*["\']([^"\']+)["\']', block, re.I)
            link_match = re.search(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', block, re.I)
            
            if link_match:
                link = link_match.group(1).replace('\\/', '/')
                name = name_match.group(1) if name_match else "Luồng Chính"
                try: name = codecs.decode(name.encode(), 'unicode_escape')
                except: pass
                
                if link not in seen:
                    streams.append({'url': link, 'name': name.strip()})
                    seen.add(link)

        # --- CHIẾN THUẬT 2: TÌM TRỰC TIẾP TRONG SCRIPT BẤT KỲ ---
        # Đôi khi link giấu trong biến javascript bình thường
        if not streams:
            blv_map = {}
            # Bẫy tên BLV nằm gần link URL
            raw_data = re.findall(r'["\']([^"\']+)["\'].*?(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', html, re.I)
            for b_name, b_url in raw_data:
                u = b_url.replace('\\/', '/')
                if len(b_name) < 20 and u not in seen: # Tên BLV thường ngắn
                    streams.append({'url': u, 'name': b_name.strip()})
                    seen.add(u)

        # --- CHIẾN THUẬT 3: VÉT LƯỚI CHÓT TOÀN BỘ HTML ---
        if not streams:
            for l in re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', html):
                l = l.replace('\\/', '/')
                if l not in seen:
                    streams.append({'url': l, 'name': "Server Dự Phòng"})
                    seen.add(l)

        # Lọc kết quả và dọn dẹp tên
        for s in streams:
            s['name'] = s['name'].replace("CƯỢC NGAY", "").replace("Gavang", "").strip()
            
        return streams, html
    except Exception as e: 
        print(f"Lỗi khi đọc trận đấu: {e}")
        return [], ""

def get_matches():
    """Quét trang chủ lấy danh sách trận đấu"""
    print(f"🚀 Đang quét danh sách trận từ {TARGET_URL}...")
    try:
        res = requests.get(TARGET_URL, impersonate="chrome110", timeout=20)
        soup = BeautifulSoup(res.text, 'html.parser')
        matches = []
        
        # Gavang thường dùng thẻ a có class chứa chữ 'match' hoặc link có 'truc-tiep'
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            if '/truc-tiep/' in href:
                full_link = href if href.startswith('http') else f"{TARGET_URL.rstrip('/')}{href}"
                
                # Bóc tên trận đấu từ URL hoặc thuộc tính title
                raw_name = a_tag.get('title') or a_tag.text.strip()
                if len(raw_name) < 5:
                    # Lấy từ slug URL: san-jose-earthquakes-vs-vancouver-whitecaps-vjxm...
                    slug = href.split('/')[-1]
                    slug_name = re.sub(r'-[a-z0-9]{10,}$', '', slug) # Xóa ID ở đuôi
                    raw_name = slug_name.replace('-', ' ').title()

                clean_name = re.sub(r'\s+', ' ', raw_name).strip()
                
                if not any(m['url'] == full_link for m in matches):
                    matches.append({
                        'url': full_link, 
                        'title': clean_name,
                        # Sẽ cập nhật time và logo khi vào trang chi tiết
                        'time': '', 'logo': '', 'sort': datetime.now() 
                    })
        
        return matches
    except Exception as e:
        print(f"Lỗi trang chủ: {e}"); return []

def main():
    matches = get_matches()
    if not matches: return

    playlist = "#EXTM3U\n"
    count = 0
    
    # Rút gọn danh sách test (Bỏ dòng này nếu muốn chạy full)
    # matches = matches[:5] 
    
    for m in matches:
        print(f"-> Đang xử lý: {m['title']}")
        links, match_html = extract_all_m3u8(m['url'])
        
        if links and match_html:
            # Cập nhật thông tin Logo và Thời gian từ trang chi tiết
            logo, time_str, time_sort = extract_match_info_from_html(match_html)
            m['logo'] = logo
            m['time'] = time_str
            m['sort'] = time_sort

            for s in links:
                blv = f" ({s['name']})" if s['name'] and s['name'] not in ["Luồng Chính", "Server Dự Phòng"] else ""
                display_name = f"{m['time']} {m['title']}{blv}"
                
                playlist += f'#EXTINF:-1 tvg-logo="{m["logo"]}", {display_name}\n'
                
                # Ép Header cho Gà Vàng TV
                origin_url = "/".join(TARGET_URL.split("/")[:3]) # Lấy domain gốc
                playlist += f'#EXTVLCOPT:http-user-agent={UA}\n'
                playlist += f'#EXTVLCOPT:http-referer={TARGET_URL}/\n'
                playlist += f'#EXTVLCOPT:http-origin={origin_url}\n'
                
                final_url = s["url"]
                if "|" not in final_url:
                    final_url += f"|Referer={TARGET_URL}/&Origin={origin_url}&User-Agent={UA}"
                
                playlist += f'{final_url}\n'
            count += 1
            
    with open("gavang_live.m3u", "w", encoding="utf-8") as f:
        f.write(playlist)
    print(f"\n🎉 HOÀN TẤT! Đã gắp xong {count} trận từ Gà Vàng.")

if __name__ == "__main__":
    main()
