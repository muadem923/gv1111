from curl_cffi import requests
from bs4 import BeautifulSoup
import re
import urllib.parse

TARGET_URL = "https://xem1.gv08.live"

def fetch_smart(url):
    """Hàm tải nội dung lách qua Cloudflare"""
    encoded_url = urllib.parse.quote(url, safe='/:?=&')
    APIS = [
        url,
        f"https://api.codetabs.com/v1/proxy?quest={url}"
    ]
    for api in APIS:
        try:
            res = requests.get(api, impersonate="chrome120", timeout=15)
            if res.status_code == 200 and len(res.text) > 100: 
                return res.text
        except: pass
    return ""

def main():
    print("🕵️ ĐANG KHỞI ĐỘNG MÁY QUÉT TIA X TÌM API BÍ MẬT...")
    html = fetch_smart(TARGET_URL)
    if not html:
        print("❌ Lỗi: Không thể truy cập trang chủ!")
        return
        
    soup = BeautifulSoup(html, 'html.parser')
    scripts = soup.find_all('script', src=True)
    print(f"👉 Tìm thấy {len(scripts)} file Javascript. Đang bóc tách từng file...")

    found = False
    for s in scripts:
        js_url = s['src']
        if js_url.startswith('//'): js_url = 'https:' + js_url
        elif not js_url.startswith('http'): js_url = TARGET_URL.rstrip('/') + '/' + js_url.lstrip('/')
        
        js_code = fetch_smart(js_url)
        if not js_code: continue
        
        # Bắt các link API giấu trong code (có chữ api hoặc json)
        links = re.findall(r'(https?://[a-zA-Z0-9\-\.\_]+(?:/api/|/v1/|/v2/|\.json)[^\s"\'\`\\]*)', js_code, re.I)
        # Bắt các endpoint dạng /api/xxx
        routes = re.findall(r'["\'\`](/api/[a-zA-Z0-9\-\.\_/\?]+)["\'\`]', js_code, re.I)
        # Bắt các link chứa từ khoá "matches", "live"
        matches = re.findall(r'(https?://[a-zA-Z0-9\-\.\_]+/[^\s"\'\`\\]*(?:matches|live)[^\s"\'\`\\]*\.json)', js_code, re.I)
        
        results = list(set(links + [TARGET_URL.rstrip('/') + r for r in routes] + matches))
        
        if results:
            print(f"\n🎯 TÓM ĐƯỢC {len(results)} LINK TRONG FILE: {js_url.split('/')[-1]}")
            for r in results:
                print(f"   🔗 {r}")
                found = True

    if not found:
        print("\n❌ Quét xong nhưng không phát hiện link API nào. Nó bị mã hóa quá sâu!")

if __name__ == "__main__":
    main()
