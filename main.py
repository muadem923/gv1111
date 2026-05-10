from curl_cffi import requests
from bs4 import BeautifulSoup
import re
import codecs
from datetime import datetime
import json
import urllib.parse

# --- CẤU HÌNH HỆ THỐNG GÀ VÀNG TV ---
TARGET_URL = "https://xem1.gv08.live"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def is_cloudflare(html):
    text = html.lower()
    return "cloudflare" in text or "just a moment" in text or "ray id" in text or "verify you are human" in text

def fetch_html_smart(url):
    """Chiến thuật lách Cloudflare bằng các Cổng API trung chuyển"""
    encoded_url = urllib.parse.quote(url, safe='/:?=&')
    
    # Danh sách 4 Cổng để thử lách luật
    APIS = [
        url,                                                 # 1. Đi cửa chính
        f"https://api.codetabs.com/v1/proxy?quest={url}",    # 2. Cửa phụ CodeTabs
        f"https://api.allorigins.win/raw?url={encoded_url}", # 3. Cửa phụ AllOrigins
        f"https://corsproxy.io/?{encoded_url}"               # 4. Cửa phụ CorsProxy
    ]
    
    for api in APIS:
        name = "Cổng Trực Tiếp" if api == url else api.split('/')[2]
        print(f"  -> Đang gọi cửa: {name} ...", end=" ")
        try:
            res = requests.get(api, impersonate="chrome120", timeout=20)
            # Nếu trả về code 200, không dính Cloudflare và nội dung đủ dài thì lấy luôn
            if res.status_code == 200 and not is_cloudflare(res.text) and len(res.text) > 1000:
                print("✅ Lọt Khe Thành Công!")
                return res.text
            else:
                print("❌ Bị chặn")
        except Exception:
            print("❌ Quá hạn (Timeout)")
            
    return None

def extract_match_info_from_html(html):
    soup = BeautifulSoup(html, 'html.parser')
    logo_url = ""
    meta_img = soup.find('meta', property='og:image')
    if meta_img: logo_url = meta_img.get('content', '')

    time_str = "[Đang cập nhật]"
    time_sort = datetime.now()
    time_match = re.search(r'(\d{2}:\d{2})\s+(\d{1,2}/\d{1,2}(?:/\d{4})?)', html)
    if time_match:
        time_str = f"[{time_match.group(1)} {time_match.group(2)}]"
        try:
            t, d = time_match.group(1), time_match.group(2)
            if len(d) <= 5: d = f"{d}/{datetime.now().year}"
            time_sort = datetime.strptime(f"{t} {d}", "%H:%M %d/%m/%Y")
        except: pass
    return logo_url, time_str, time_sort

def extract_all_m3u8(url):
    print(f"\nMổ xẻ trận: {url}")
    html = fetch_html_smart(url)
    if not html: return [], ""
    
    streams, seen = [], set()

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

def get_matches():
    print(f"🚀 Đang đột nhập trang chủ: {TARGET_URL}")
    html = fetch_html_smart(TARGET_URL)
    
    if not html:
        print("❌ Lỗi: Toàn bộ Cổng trung chuyển đều bị Cloudflare chặn đứng!")
        return []
        
    soup = BeautifulSoup(html, 'html.parser')
    matches = []
    
    all_links = soup.find_all('a', href=True)
    print(f"👉 Quét được {len(all_links)} link HTML thô.")
    
    for a_tag in all_links:
        href = a_tag['href']
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
                    'url': full_link, 'title': clean_name,
                    'time': '', 'logo': '', 'sort': datetime.now() 
                })
    
    print(f"👉 Lọc ra được {len(matches)} trận bóng hợp lệ.")
    return matches

def main():
    matches = get_matches()
    if not matches: 
        print("❌ KHÔNG TÌM THẤY TRẬN NÀO! Dừng chương trình.")
        return

    playlist = "#EXTM3U\n"
    count = 0
    
    for m in matches:
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
        print(f"\n🎉 HOÀN TẤT! Đã gắp thành công {count} trận từ Gà Vàng.")
    else:
        print("\n❌ LỖI VÉT LINK: Truy cập được nhưng không tìm thấy file đuôi .m3u8!")

if __name__ == "__main__":
    main()
