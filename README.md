# OCR Order Bot — Hướng dẫn triển khai

## Mô tả
Bot Telegram tự động đọc ảnh phiếu giao hàng, trích xuất thông tin và ghi vào Google Sheet.
- Mỗi ngày tạo 1 tab mới theo định dạng: `01-07-2026`
- Dùng Claude Haiku để OCR — đọc được cả chữ in lẫn chữ viết tay

## Cấu trúc file
```
ocr-order-bot/
├── main.py            # Bot chính
├── ocr_processor.py   # Gọi Claude API để đọc ảnh
├── sheet_writer.py    # Ghi vào Google Sheet
├── requirements.txt
├── Procfile
└── README.md
```

## Các cột trong Google Sheet
| STT | Tên khách | Số điện thoại | Địa chỉ | Tổng tiền | Thời gian nhập |

---

## Bước 1 — Tạo Telegram Bot
1. Nhắn @BotFather → `/newbot`
2. Đặt tên bot (VD: `OCR Order Bot`)
3. Lưu lại **TOKEN**
4. Thêm bot vào nhóm Telegram → cấp quyền **Admin** (hoặc ít nhất quyền đọc tin nhắn)

---

## Bước 2 — Google Sheet & Service Account
1. Tạo Google Sheet mới, lưu lại **Sheet ID** (chuỗi dài trong URL)
2. Vào Google Cloud Console → chọn project → **APIs & Services** → **Enable APIs**:
   - Google Sheets API ✓
   - Google Drive API ✓
3. **Credentials** → **Create credentials** → **Service Account**
4. Vào Service Account vừa tạo → tab **Keys** → **Add Key** → **JSON**
5. Tải file JSON về máy
6. Mở Google Sheet → **Share** → dán email Service Account (dạng `xxx@yyy.iam.gserviceaccount.com`) → cấp quyền **Editor**

---

## Bước 3 — Deploy lên Railway
1. Tạo repo GitHub mới, push toàn bộ code lên
2. Vào [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
3. Chọn repo → Railway tự detect Procfile
4. Vào **Variables** → thêm 4 biến sau:

| Tên biến | Giá trị |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token từ BotFather |
| `ANTHROPIC_API_KEY` | API key Anthropic của anh |
| `GOOGLE_SHEET_ID` | ID của Google Sheet |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Toàn bộ nội dung file JSON (paste nguyên) |

5. **Deploy** → chờ build xong → bot tự chạy

---

## Kiểm tra hoạt động
- Gửi 1 ảnh phiếu vào nhóm Telegram
- Bot reply trong vòng ~3-5 giây với thông tin trích xuất được
- Kiểm tra Google Sheet — tab ngày hôm nay đã có dữ liệu

## Chi phí ước tính
- 150 ảnh/ngày × 30 ngày = 4.500 ảnh/tháng
- Claude Haiku: ~**$2–4/tháng**
- Railway: Free tier đủ dùng (hoặc ~$5/tháng nếu cần uptime 24/7)
