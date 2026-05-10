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
    try:
        text = text.replace('\\"', '"').replace("\\'", "'").replace('\\/', '/')
        return json.loads(text)
    except:
        return None

def extract_match_info_from_html(html):
    soup = BeautifulSoup(html, 'html.parser')
    logo_url = ""
    meta_img = soup.find('meta', property='og:image')
    if meta_img:
        logo_url = meta_img.get('content', '')

    time_str = "[Đang cập nhật]"
    time_sort = datetime.now()
    time_match = re.search(r'(\d{2}:\d{2})\s+(\d{1,2}/\d{1,2}(?:/\d{4})?)', html)
    if time_match:
        time_str = f"[{time_match.group(1)} {time_match.group(2)}]"
        try:
            t = time_match.group(1)
            d = time_match.group(2)
            if len(d) <= 5: d = f"{d}/{datetime.now().year}"
            time_sort = datetime.strptime(f"{t} {d}", "%H:%M %d/%m/%Y")
        except: pass
    return logo_url, time_str, time_sort

def extract_all_m3u8(url):
    print(f"  Đang quét luồng: {url}")
    try:
        res = requests.get(url, impersonate="chrome110", timeout=15)
        html = res.text
        streams = []
        seen = set()

        json_blocks = re.findall(r'\{[^{]*?\.m3u8[^{]*?\}', html, re.IGNORECASE)
        for block in json_blocks:
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

        if not streams:
            raw_data = re.findall(r'["\']([^"\']+)["\'].*?(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', html, re.I)
            for b_name, b_url in raw_data:
                u = b_url.replace('\\/', '/')
                if len(b_name) < 20 and u not in seen:
                    streams.append({'url': u, 'name': b_name.strip()})
                    seen.add(u)

        if not streams:
            for l in re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', html):
                l = l.replace('\\/', '/')
                if l not in seen:
                    streams.append({'url': l, 'name': "Server Dự Phòng"})
                    seen.add(l)

        for s in streams:
            s['name'] = s['name'].replace("CƯỢC NGAY", "").replace("Gavang", "").strip()
            
        return streams, html
    except Exception as e: 
        print(f"  Lỗi khi đọc trận đấu: {e}")
        return [], ""

def get_matches():
    print(f"🚀 Đang quét danh sách trận từ {TARGET_URL}...")
    try:
        res = requests.get(TARGET_URL, impersonate="chrome110", timeout=20)
        
        # IN LOG KIỂM TRA MÁY CHỦ
        print(f"👉 Trạng thái máy chủ Gavang trả về: Code {res.status_code}")
        if res.status_code == 403 or "cloudflare" in res.text.lower() or "just a moment" in res.text.lower():
            print("⚠️ CẢNH BÁO: IP của GitHub đã bị Cloudflare chặn. Chúng ta cần dùng Proxy!")
        
        soup = BeautifulSoup(res.text, 'html.parser')
        matches = []
        
        all_links = soup.find_all('a', href=True)
        print(f"👉 Hệ thống tìm thấy tổng cộng {len(all_links)} đường link trên trang chủ.")
        
        for a_tag in all_links:
            href = a_tag['href']
            # Gavang đôi khi dùng /truc-tiep/ hoặc /match/
            if '/truc-tiep/' in href or '/truoc-tran/' in href:
                full_link = href if href.startswith('http') else f"{TARGET_URL.rstrip('/')}{href}"
                raw_name = a_tag.get('title') or a_tag.text.strip()
                if len(raw_name) < 5:
                    slug = href.split('/')[-1]
                    slug_name = re.sub(r'-[a-z0-9]{10,}$', '', slug)
                    raw_name = slug_name.replace('-', ' ').title()

                clean_name = re.sub(r'\s+', ' ', raw_name).strip()
                if not any(m['url'] == full_link for m in matches):
                    matches.append({
                        'url': full_link, 
                        'title': clean_name,
                        'time': '', 'logo': '', 'sort': datetime.now() 
                    })
        
        print(f"👉 Lọc được {len(matches)} trận đấu hợp lệ.")
        return matches
    except Exception as e:
        print(f"❌ Lỗi trang chủ: {e}"); return []

def main():
    matches = get_matches()
    if not matches: 
        print("❌ KẾT LUẬN: KHÔNG CÓ TRẬN NÀO ĐƯỢC TÌM THẤY! Chương trình tự động dừng.")
        return

    playlist = "#EXTM3U\n"
    count = 0
    
    for m in matches:
        print(f"-> Đang xử lý trận: {m['title']}")
        links, match_html = extract_all_m3u8(m['url'])
        
        if links and match_html:
            logo, time_str, time_sort = extract_match_info_from_html(match_html)
            m['logo'] = logo
            m['time'] = time_str
            m['sort'] = time_sort

            for s in links:
                blv = f" ({s['name']})" if s['name'] and s['name'] not in ["Luồng Chính", "Server Dự Phòng"] else ""
                display_name = f"{m['time']} {m['title']}{blv}"
                
                playlist += f'#EXTINF:-1 tvg-logo="{m["logo"]}", {display_name}\n'
                
                origin_url = "/".join(TARGET_URL.split("/")[:3])
                playlist += f'#EXTVLCOPT:http-user-agent={UA}\n'
                playlist += f'#EXTVLCOPT:http-referer={TARGET_URL}/\n'
                playlist += f'#EXTVLCOPT:http-origin={origin_url}\n'
                
                final_url = s["url"]
                if "|" not in final_url:
                    final_url += f"|Referer={TARGET_URL}/&Origin={origin_url}&User-Agent={UA}"
                
                playlist += f'{final_url}\n'
            count += 1
            
    if count > 0:
        with open("gavang_live.m3u", "w", encoding="utf-8") as f:
            f.write(playlist)
        print(f"\n🎉 HOÀN TẤT! Đã gắp xong {count} trận từ Gà Vàng.")
    else:
        print("\n❌ LỖI GẮP VIDEO: Cấu trúc JSON có thể đã bị thay đổi, không lấy được link M3U8 nào!")

if __name__ == "__main__":
    main()
