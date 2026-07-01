import anthropic
import base64
import json
import os
import re
import io
import numpy as np
from PIL import Image, ImageOps, ImageFilter

client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])

BLUR_THRESHOLD = 100

PROMPT = """Đây là ảnh phiếu giao hàng.

BƯỚC 1 — Kiểm tra định dạng:
Phiếu hợp lệ cần có ĐẦY ĐỦ:
- Logo hoặc chữ "CHOTDON.VN" (có thể ở cuối hoặc đầu phiếu tùy chiều ảnh)
- Mã đơn hàng dạng "#HD..." (ví dụ: #HD26062741)
- Các trường thông tin được IN sẵn (không phải viết tay hoàn toàn)

Nếu KHÔNG có → trả về: {"_wrong_format": true}

BƯỚC 2 — Nếu hợp lệ, trích xuất:
- "so_thu_tu": số viết tay bằng bút lớn (2-3 chữ số, thường ở góc phiếu)
- "ten_khach": tên khách (sau "Khách hàng:" hoặc "Khách") — KHÔNG phải tên shop
- "so_dien_thoai": SĐT khách (sau "Số điện thoại:") — KHÔNG phải SĐT shop
- "dia_chi": địa chỉ (sau "Địa chỉ:"), để "" nếu không có
- "tong_tien": số tiền trên dòng CÓ NHÃN "Tổng" — lấy đúng số này, KHÔNG tự tính toán

Lưu ý về "tong_tien":
  Phiếu có thể có: Tạm tính, Tiền cọc, Phí vận chuyển, và cuối cùng là Tổng.
  Chỉ lấy số tiền ở dòng "Tổng" — đây là số khách cần trả, đã trừ cọc và cộng ship.
  Ví dụ: Tạm tính 158.000 / Tiền cọc 100.000 / Phí ship 37.000 / Tổng 95.000
  → tong_tien = 95000 (không phải 158000 hay 195000)

Lưu ý về tên/SĐT shop:
  "Mylan Vintage" và "0336927690" là thông tin shop, KHÔNG phải khách hàng.

Ví dụ output:
{"so_thu_tu": "142", "ten_khach": "Nhat Khanh", "so_dien_thoai": "0702464545", "dia_chi": "32 Ngô Nhân Tịnh, P. Phú Hậu, TP Huế", "tong_tien": 95000}

Chỉ trả về JSON thuần túy, không markdown, không giải thích."""


def fix_image_rotation(image_bytes: bytes) -> bytes:
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = ImageOps.exif_transpose(img)
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=95)
        return output.getvalue()
    except Exception as e:
        print(f"[Rotation fix] Error: {e}")
        return image_bytes


def rotate_180(image_bytes: bytes) -> bytes:
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = img.rotate(180)
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=95)
        return output.getvalue()
    except Exception as e:
        print(f"[Rotate 180] Error: {e}")
        return image_bytes


def detect_blur(image_bytes: bytes) -> float:
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert('L')
        edges = img.filter(ImageFilter.FIND_EDGES)
        arr = np.array(edges, dtype=np.float64)
        return float(arr.var())
    except Exception as e:
        print(f"[Blur detect] Error: {e}")
        return 9999.0


def is_result_wrong(data: dict) -> bool:
    """Phát hiện kết quả sai do ảnh bị xoay ngược."""
    ten = (data.get('ten_khach') or '').lower()
    sdt = (data.get('so_dien_thoai') or '').replace(' ', '').replace('-', '')
    shop_keywords = ['mylan', 'vintage', 'zhang', 'page']
    shop_phones = ['0336927690', '336927690']
    if any(k in ten for k in shop_keywords):
        return True
    if sdt in shop_phones:
        return True
    return False


async def call_claude(image_bytes: bytes) -> dict | None:
    try:
        image_b64 = base64.standard_b64encode(image_bytes).decode('utf-8')
        response = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=500,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": PROMPT},
                    ],
                }
            ],
        )
        text = response.content[0].text.strip()
        text = re.sub(r'```(?:json)?|```', '', text).strip()
        data = json.loads(text)

        if not data.get('_wrong_format'):
            tong = data.get('tong_tien', 0)
            try:
                data['tong_tien_fmt'] = f"{int(tong):,} vnđ".replace(',', '.')
            except (ValueError, TypeError):
                data['tong_tien_fmt'] = str(tong)

        return data

    except json.JSONDecodeError as e:
        print(f"[OCR] JSON parse error: {e}")
        return None
    except Exception as e:
        print(f"[OCR] Error: {e}")
        return None


async def extract_order_info(image_bytes: bytes) -> dict | None:
    # Bước 1: Xoay theo EXIF nếu có
    image_bytes = fix_image_rotation(image_bytes)

    # Bước 2: Kiểm tra độ mờ
    blur_score = detect_blur(image_bytes)
    print(f"[Blur detect] Score = {blur_score:.1f}")
    if blur_score < BLUR_THRESHOLD:
        return {"_blur": True, "_blur_score": round(blur_score, 1)}

    # Bước 3: OCR lần 1
    result = await call_claude(image_bytes)

    # Bước 4: Nếu sai định dạng HOẶC đọc nhầm tên shop → thử xoay 180° OCR lại
    # (ảnh ngược: CHOTDON.VN logo bị lộn → Claude không nhận ra → báo sai định dạng)
    needs_rotation = result and (result.get('_wrong_format') or is_result_wrong(result))

    if needs_rotation:
        print("[Rotation] Thử xoay 180° và OCR lại")
        rotated = rotate_180(image_bytes)
        result2 = await call_claude(rotated)

        # Dùng kết quả mới nếu đọc được và không sai
        if result2 and not result2.get('_wrong_format') and not is_result_wrong(result2):
            result = result2
            print("[Rotation] Xoay 180° thành công")

    return result
