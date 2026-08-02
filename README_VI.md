# LiveXTV GitHub Scanner v0.1.0 — bản thử nghiệm

Mục tiêu: tạo `livextv.m3u` trên GitHub Actions. API được dùng để lấy trận/source; Chromium chỉ mở các `embedUrl` thật để quan sát M3U8 công khai. Mỗi M3U8 chỉ được xuất nếu `ffprobe` bên ngoài Chromium đọc được bằng `Referer: https://embed.st/` + User-Agent Chrome.

## Cách cài vào repository GitHub

1. Tạo repository riêng cho LiveXTV (public nếu muốn dùng raw URL trực tiếp).
2. Upload **toàn bộ nội dung** của thư mục này vào root repository, gồm cả `.github/workflows/livextv.yml`.
3. Vào **Settings → Actions → General → Workflow permissions** và bảo đảm workflow có quyền ghi nội dung nếu chính sách repository yêu cầu.
4. Vào tab **Actions → LiveXTV M3U Refresh → Run workflow** để chạy thử thủ công.
5. Khi job thành công, repository sẽ có:
   - `livextv.m3u`
   - `scan_report.json`
   - `state/livextv_last_good.json`

Workflow cũng có lịch `2-57/5 * * * *` (xấp xỉ mỗi 5 phút; GitHub có thể chạy trễ).

## URL raw

Sau khi file đã được commit, raw URL có dạng:

`https://raw.githubusercontent.com/USER/REPO/refs/heads/main/livextv.m3u`

## Cơ chế

`/api/matches/live` → `/api/stream/{source}/{id}` → `embedUrl` → Chromium bắt secure M3U8 → `ffprobe` với Referer + UA → ghi M3U.

M3U có thêm:

```m3u
#EXTVLCOPT:http-referrer=https://embed.st/
#EXTVLCOPT:http-user-agent=Mozilla/5.0 ...
```

Ứng dụng IPTV cần hỗ trợ các header này. Nếu app bỏ qua `#EXTVLCOPT`, link có thể 403 dù workflow đã verify PASS.

## Last-good

Mặc định chỉ giữ entry cũ tối đa **900 giây (15 phút)**. Nếu API live chạy tốt và trận đã biến mất khỏi danh sách live, entry cũ bị loại ngay. Điều này tránh giữ secure URL chết hàng giờ.

Có thể chỉnh trong workflow:

- `LIVEXTV_MAX_MATCHES`
- `LIVEXTV_MAX_SOURCES_PER_MATCH`
- `LIVEXTV_MAX_EMBEDS`
- `LIVEXTV_BROWSER_WAIT_SECONDS`
- `LIVEXTV_LAST_GOOD_TTL_SECONDS`

## File cần gửi lại để audit

Nếu workflow chạy nhưng playlist không như mong đợi, tải artifact của run hoặc gửi:

- `scan_report.json`
- `livextv.m3u`

`scan_report.json` che secure token trong phần chẩn đoán; `livextv.m3u` và state phải chứa URL thật vì đó là đầu ra dùng để phát.

## Giới hạn

- Không reverse/bypass `lock.wasm`, DRM hoặc đăng nhập.
- Secure URL có thể thay đổi/expire nhanh nên lịch 5 phút chỉ là thử nghiệm.
- GitHub scheduled workflows không bảo đảm chạy chính xác từng 5 phút.
- Khả năng phát cuối cùng còn phụ thuộc ứng dụng IPTV có gửi Referer/User-Agent từ `#EXTVLCOPT` hay không.
