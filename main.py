from playwright.sync_api import sync_playwright
import json

TARGET_URL = "https://xem1.gv08.live"
# Có thể đổi lại thành xem1.gv03.live nếu gv08 bị sập

def handle_response(response):
    """Máy nghe lén: Bắt toàn bộ các gói tin API và JSON trả về"""
    try:
        # Lọc ra các gói tin có chứa dữ liệu JSON hoặc API
        content_type = response.headers.get("content-type", "")
        url = response.url
        
        if "application/json" in content_type or ".json" in url or "api" in url.lower():
            print(f"\n🎯 BẮT ĐƯỢC LINK API: {url}")
            
            # Cố gắng đọc thử 150 ký tự đầu tiên của cục dữ liệu xem có chữ "Gà Vàng", "Azzurri" hay tên đội bóng không
            try:
                data = response.json()
                data_str = json.dumps(data, ensure_ascii=False)
                if len(data_str) > 20:
                    print(f"   => Dữ liệu bên trong: {data_str[:150]}...")
            except:
                pass
                
        # Nếu vô tình bắt được luôn link M3U8 thì báo ngay
        if ".m3u8" in url:
            print(f"\n🎬 QUÁ NGON! BẮT ĐƯỢC LINK VIDEO TRỰC TIẾP: {url}")
    except:
        pass

def main():
    print("🕵️ ĐANG KÍCH HOẠT RADAR NGHE LÉN MẠNG (NETWORK INTERCEPTOR)...")
    with sync_playwright() as p:
        # Bật trình duyệt ẩn, gắn khiên chống phát hiện bot
        browser = p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        # Gắn "máy nghe lén" vào trang web
        page.on("response", handle_response)
        
        print(f"👉 Đang cho Robot thâm nhập: {TARGET_URL}")
        try:
            page.goto(TARGET_URL, wait_until="networkidle", timeout=30000)
            print("⏳ Đang nằm vùng đợi dữ liệu tải về (10 giây)...")
            page.wait_for_timeout(10000)
        except Exception as e:
            print(f"❌ Lỗi mạng: {e}")
        finally:
            browser.close()
            print("\n✅ Kết thúc phiên nghe lén!")

if __name__ == "__main__":
    main()
