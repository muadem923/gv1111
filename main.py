from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import re
from datetime import datetime

TARGET_URL = "https://xem1.gv08.live"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def get_html_with_robot(url, wait_time=5000):
    """Mở Chrome ẩn, đợi JS render xong thì lấy HTML"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=UA, viewport={'width': 1920, 'height': 1080})
        page = context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(wait_time) # Đợi x giây cho web tự vẽ giao diện
            html = page.content()
            browser.close()
            return html
        except Exception as e:
            print(f"❌ Lỗi mạng khi Robot vào trang: {e}")
            browser.close()
            return ""

def extract_match_info(html):
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

def extract_m3u8(html):
    streams, seen = [], set()
    # Tìm trực tiếp mọi link m3u8 sau khi đã render
    links = re.findall(r'(https?://[^\s"\'<>]*\.m3u8[^\s"\'<>]*)', html, re.I)
    for l in links:
        l = l.replace('\\/', '/')
        if l not in seen:
            streams.append({'url': l, 'name': "Luồng Trực Tiếp"})
            seen.add(l)
    return streams

def main():
    print("🤖 ĐANG KÍCH HOẠT ROBOT PLAYWRIGHT...")
    print(f"👉 Đang mở cổng vào trang chủ: {TARGET_URL}")
    
    html = get_html_with_robot(TARGET_URL, wait_time=5000)
    if not html: return
    
    soup = BeautifulSoup(html, 'html.parser')
    matches = []
    seen_urls = set()
    
    # Lúc này web đã hiện hình, cứ phang thẳng thẻ <a> mà lấy link
    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href']
        if '/truc-tiep/' in href or '/truoc-tran/' in href:
            full_link = href if href.startswith('http') else f"{TARGET_URL.rstrip('/')}{href}"
            raw_name = a_tag.get('title') or a_tag.text.strip()
            
            if len(raw_name) < 5:
                slug = href.split('/')[-1]
                slug_name = re.sub(r'-[a-z0-9]{10,}$', '', slug)
                raw_name = slug_name.replace('-', ' ').title()

            clean_name = re.sub(r'\s+', ' ', raw_name).strip()
            if full_link not in seen_urls:
                matches.append({'url': full_link, 'title': clean_name, 'time': '', 'logo': '', 'sort': datetime.now()})
                seen_urls.add(full_link)

    print(f"✅ Robot nhặt được {len(matches)} trận đấu!")
    if not matches: return

    playlist = "#EXTM3U\n"
    count = 0
    
    for m in matches:
        print(f"-> Đang mổ bụng trận: {m['title']}")
        # Cho Robot vào thẳng trang trận đấu, đợi 6 giây cho load video
        match_html = get_html_with_robot(m['url'], wait_time=6000) 
        links = extract_m3u8(match_html)
        
        if links:
            logo, time_str, time_sort = extract_match_info(match_html)
            m['logo'] = logo
            m['time'] = time_str
            m['sort'] = time_sort

            for s in links:
                display_name = f"{m['time']} {m['title']}"
                playlist += f'#EXTINF:-1 tvg-logo="{m["logo"]}", {display_name}\n'
                origin_url = "/".join(TARGET_URL.split("/")[:3])
                playlist += f'#EXTVLCOPT:http-user-agent={UA}\n'
                playlist += f'#EXTVLCOPT:http-referer={TARGET_URL}/\n'
                playlist += f'#EXTVLCOPT:http-origin={origin_url}\n'
                
                final_url = s["url"]
                if "|" not in final_url: final_url += f"|Referer={TARGET_URL}/&Origin={origin_url}&User-Agent={UA}"
                playlist += f'{final_url}\n'
            count += 1
            
    if count > 0:
        with open("gavang_live.m3u", "w", encoding="utf-8") as f:
            f.write(playlist)
        print(f"\n🎉 CHIẾN THẮNG! Gắp thành công {count} trận m3u8.")
    else:
        print("\n❌ Thấy trận đấu nhưng không vét được m3u8 nào!")

if __name__ == "__main__":
    main()
