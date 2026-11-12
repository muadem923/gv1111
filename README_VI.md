# LiveXTV GitHub Scanner v0.2.0

Bản viết lại sau khi hạ tầng cũ chết (Render backend suspend, Streamed đóng cửa 27/10/2026).
Nguồn mới: `https://api.ppv.st/api/streams` (API công khai, không auth).

## Cơ chế

`/api/streams` → lọc kênh/streams đang live (`always_live` hoặc đã bắt đầu, chưa kết thúc)
→ mỗi stream lấy iframe chính + tối đa `LIVEXTV_MAX_SOURCES_PER_MATCH` substreams
→ Chrome/Chromium headless mở embed, bắt request `.m3u8` (kể cả URL inline trong HTML)
→ `ffprobe` xác minh với `Referer` = origin của embed + User-Agent
→ chỉ PASS mới ghi vào `livextv.m3u` (giữ tên file như bản cũ).

M3U xuất kèm:

```m3u
#EXTVLCOPT:http-referrer=<origin embed>
#EXTVLCOPT:http-user-agent=Mozilla/5.0 ...
```

## Chạy trên GitHub

1. Thay các file trong repo bằng nội dung thư mục này (workflow tại `.github/workflows/livextv.yml`).
2. Actions → LiveXTV M3U Refresh → Run workflow.
3. Xem `scan_report.json`, `livextv.m3u`, `state/livextv_last_good.json` (artifact `livextv-scan-<run>`).

Workflow chỉ chạy khi trigger tay (`workflow_dispatch`) — cron tự động của GitHub đã bỏ vì thất thường;
tự đặt cron bên ngoài gọi API dispatch nếu muốn chạy định kỳ.
Runner không bị chặn bởi AV cục bộ nên nhánh browser chạy bình thường.

## Biến môi trường

```text
LIVEXTV_API_BASE            mặc định https://api.ppv.st/api
LIVEXTV_MAX_MATCHES         số stream live tối đa (30)
LIVEXTV_MAX_SOURCES_PER_MATCH  số substreams mỗi stream (2)
LIVEXTV_MAX_EMBEDS          tổng embed tối đa (45)
LIVEXTV_BROWSER_WAIT_SECONDS   thời gian chờ request media (7)
LIVEXTV_LAST_GOOD_TTL_SECONDS  giữ entry cũ tối đa (900)
LIVEXTV_LIVE_WINDOW_BEFORE_SECONDS  cửa sổ trận đã bắt đầu không có ends_at (10800)
LIVEXTV_LIVE_GRACE_AFTER_SECONDS    grace sau ends_at (1800)
LIVEXTV_MEDIA_REFERER       ghi đè referer khi ffprobe (mặc định: origin embed)
LIVEXTV_DRY_RUN=1           chỉ dò API, không mở browser/ffprobe
```

## Last-good

Giữ entry đã verified tối đa 900s khi API lỗi. Khi API sống, entry không còn trong
danh sách hiện tại sẽ bị loại (không hồi sinh kênh đã chết).

## Giới hạn

- Không reverse/bypass DRM, wasm lock hay đăng nhập; chỉ quan sát request công khai của player.
- Embed host của hệ ppv thay đổi thường xuyên và có thể bị AV chặn ở máy cục bộ;
  nếu player đổi cơ chế phát, nhánh capture cần cập nhật theo.
- Secure URL có thể chết nhanh; `upstream_dead` là trạng thái bình thường.
- App IPTV phải hỗ trợ Referer/User-Agent từ `#EXTVLCOPT`.