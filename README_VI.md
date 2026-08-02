# LiveXTV GitHub Scanner v0.1.3 — bản thử nghiệm

## Thay đổi v0.1.3

- Phân loại kết quả media rõ ràng trong `scan_report.json`:
  - `verified`: `ffprobe` đọc được A/V.
  - `upstream_dead`: browser/ffprobe nhận 404 hoặc 410.
  - `client_restricted`: 401/403/429, thường là hạn chế client/header/runner.
  - `transport_timeout`: timeout khi xác minh.
  - `media_unverified`: đã thấy M3U8 nhưng chưa xác minh được.
  - `player_no_media`: player không tạo request media.
- Nếu `/api/matches/live` có ít hơn `LIVEXTV_MIN_SOURCE_PAIRS` source (mặc định 6), scanner tự lấy thêm một số trận gần thời gian hiện tại từ `/api/matches/all`.
- Fallback `/matches/all` chỉ dùng các trận có timestamp trong cửa sổ mặc định: 3 giờ trước đến 4 giờ sau thời điểm quét, bỏ các match đã có trong `/matches/live`.
- Các trận fallback **không được tin mặc định**: chỉ link `ffprobe` PASS mới được ghi vào `livextv.m3u`.
- `scan_report.json` có thêm `live_matches`, `nearby_fallback_matches`, `nearby_fallback_used` và `classification_counts`.

## Cơ chế

`/api/matches/live` → nếu source quá ít thì bổ sung `/api/matches/all` gần giờ hiện tại → `/api/stream/{source}/{id}` → `embedUrl` → Chrome/Chromium bắt secure M3U8 request → `ffprobe` trực tiếp với `Referer: https://embed.st/` + User-Agent → chỉ PASS mới ghi M3U.

M3U xuất thêm:

```m3u
#EXTVLCOPT:http-referrer=https://embed.st/
#EXTVLCOPT:http-user-agent=Mozilla/5.0 ...
```

## Cài vào GitHub

1. Thay toàn bộ file bản cũ trong repo bằng nội dung thư mục này, giữ `.github/workflows/livextv.yml`.
2. Vào **Settings → Actions → General → Workflow permissions** và cho workflow quyền ghi repository nếu cần.
3. Vào **Actions → LiveXTV M3U Refresh → Run workflow**.
4. Kiểm tra `scan_report.json`, `livextv.m3u`, `state/livextv_last_good.json`.

Workflow mặc định chạy khoảng mỗi 5 phút (`2-57/5 * * * *`). GitHub có thể chạy trễ.

## Các biến mới

```text
LIVEXTV_NEARBY_FALLBACK=1
LIVEXTV_MIN_SOURCE_PAIRS=6
LIVEXTV_NEARBY_MAX_MATCHES=8
LIVEXTV_NEARBY_WINDOW_BEFORE_SECONDS=10800
LIVEXTV_NEARBY_WINDOW_AFTER_SECONDS=14400
```

Có thể giảm `LIVEXTV_NEARBY_MAX_MATCHES` nếu muốn giảm số player Chromium phải mở.

## Last-good

Mặc định giữ entry cũ tối đa 900 giây. Nếu live API chạy thành công và match đã biến mất khỏi danh sách live, entry cũ không được hồi sinh. Entry từ fallback chỉ tồn tại khi lượt hiện tại xác minh lại được, tránh giữ trận ngoài live list quá lâu.

## Giới hạn

- Không reverse/bypass `lock.wasm`, DRM hoặc đăng nhập.
- Secure URL có thể chết nhanh; `upstream_dead` là trạng thái bình thường nếu source LiveXTV đã hết hạn.
- App IPTV phải hỗ trợ Referer/User-Agent từ `#EXTVLCOPT`.
