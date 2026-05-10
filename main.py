from playwright.sync_api import sync_playwright
import json
import time

# Có thể linh hoạt đổi sang xem1.gv03.live nếu gv08 bị khóa
TARGET_URL = "https://xem1.gv08.live" 

def handle_response(response):
    try:
        url = response.url
        # Lọc bỏ các API rác của Google, Facebook để log cho sạch
        if "google" in url or "facebook" in url or "cloudflare" in url:
            return
            
        if "rapid-api" in url or "api" in url.lower() or ".json" in url:
            print(f"\n🎯 TÓM ĐƯỢC API BÍ MẬT: {url}")
            try:
                data = response.json()
                print(f"   => Dữ liệu (150 ký tự đầu): {json.dumps(data, ensure_ascii=False)[:150]}...")
            except: 
                pass
    except: 
        pass

def main():
    print("🕵️ ĐANG KÍCH HOẠT LỚP TÀNG HÌNH CHO ROBOT...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-infobars',
                '--no-sandbox',
                '--window-size=1920,1080',
            ]
        )
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1920, 'height': 1080},
            locale="vi-VN",
            timezone_id="Asia/Ho_Chi_Minh"
        )
        
        page = context.new_page()
        
        # TIÊM MÃ ĐỘC: Xóa mọi dấu vết Robot trong lõi trình duyệt
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.navigator.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'languages', { get: () => ['vi-VN', 'vi', 'en-US', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        """)
        
        # Gắn radar nghe lén
        page.on("response", handle_response)
        
        print(f"👉 Đang đột nhập lại vào: {TARGET_URL}")
        try:
            page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
            
            # Giả lập thao tác lướt web của người thật (Cuộn chuột)
            print("⏳ Đang giả lập lướt web đánh lừa hệ thống (chờ 10 giây)...")
            for i in range(5):
                page.mouse.wheel(0, 600)
                time.sleep(1)
            
            page.wait_for_timeout(5000)
        except Exception as e:
            print(f"❌ Lỗi truy cập: {e}")
        finally:
            browser.close()
            print("\n✅ Rút quân. Kết thúc phiên nghe lén!")

if __name__ == "__main__":
    main()
