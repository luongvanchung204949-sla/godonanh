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

BƯỚC 2 — Nếu hợp lệ, trích xuất 5 trường sau:

1. "ma_don": mã đơn hàng in sẵn, dạng "#HD..." — lấy đầy đủ
2. "ten_khach": tên khách (sau nhãn "Khách hàng:" hoặc "Khách") — KHÔNG phải tên shop Mylan Vintage
3. "so_dien_thoai": SĐT của khách (sau "Số điện thoại:") — KHÔNG phải SĐT shop 0336927690
   QUAN TRỌNG: Giữ nguyên số 0 đầu tiên. SĐT Việt Nam luôn bắt đầu bằng 0 (10 chữ số).
   Ví dụ đúng: "0702464545" — Ví dụ SAI: "702464545"
4. "dia_chi": địa chỉ đầy đủ (sau "Địa chỉ:"), để "" nếu không có
5. "so_tien": object chứa TẤT CẢ các dòng tiền xuất hiện trên phiếu theo đúng nhãn.
   Các nhãn thường gặp: "tam_tinh", "tien_coc", "phi_van_chuyen", "tong"
   Mỗi giá trị là số nguyên, bỏ dấu chấm/phẩy và chữ "vnđ".

   Ví dụ phiếu có: Tạm tính 74.000 / Tiền cọc 100.000 / Phí ship 35.000 / Tổng 9.000
   → "so_tien": {"tam_tinh": 74000, "tien_coc": 100000, "phi_van_chuyen": 35000, "tong": 9000}

   Ví dụ phiếu có: Tạm tính 60.000 / Phí ship 35.000 / Tổng 95.000
   → "so_tien": {"tam_tinh": 60000, "phi_van_chuyen": 35000, "tong": 95000}

Ví dụ output đúng:
{"ma_don": "#HD260629182", "ten_khach": "Vy Nguyen", "so_dien_thoai": "0937743792", "dia_chi": "138/4 khu Phố 10, Phường Tân Biên, TP Biên Hòa, Đồng Nai", "so_tien": {"tam_tinh": 74000, "tien_coc": 100000, "phi_van_chuyen": 35000, "tong": 9000}}

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


def rotate_image(image_bytes: bytes, degrees: int) -> bytes:
    """Xoay ảnh theo số độ chỉ định (90, 180, 270)."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = img.rotate(degrees, expand=True)
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=95)
        return output.getvalue()
    except Exception as e:
        print(f"[Rotate {degrees}] Error: {e}")
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
            # Trích STT từ mã đơn: #HD260628165 → bỏ "#HD" + 6 số ngày → còn "165"
            ma_don = data.get('ma_don', '')
            match = re.match(r'#?HD\d{6}(\d+)', ma_don)
            data['stt'] = match.group(1) if match else ma_don

            # Lấy tong_tien từ object so_tien (Python tự extract, không để Claude chọn)
            so_tien = data.get('so_tien', {})
            tong = so_tien.get('tong', data.get('tong_tien', 0))
            data['tong_tien'] = tong
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
    image_bytes = fix_image_rotation(image_bytes)

    blur_score = detect_blur(image_bytes)
    print(f"[Blur detect] Score = {blur_score:.1f}")
    if blur_score < BLUR_THRESHOLD:
        return {"_blur": True, "_blur_score": round(blur_score, 1)}

    result = await call_claude(image_bytes)

    # Nếu sai → thử lần lượt các góc xoay: 180°, 90°, 270°
    if result and (result.get('_wrong_format') or is_result_wrong(result)):
        for degrees in [180, 90, 270]:
            print(f"[Rotation] Thử xoay {degrees}° và OCR lại")
            rotated = rotate_image(image_bytes, degrees)
            result2 = await call_claude(rotated)
            if result2 and not result2.get('_wrong_format') and not is_result_wrong(result2):
                result = result2
                print(f"[Rotation] Xoay {degrees}° thành công")
                break

    return result
