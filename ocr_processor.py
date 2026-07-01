import anthropic
import base64
import json
import os
import re
import io
from PIL import Image, ImageOps
import cv2
import numpy as np

client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])

# Ngưỡng phát hiện ảnh mờ — giá trị càng thấp càng mờ
# Dưới 80: ảnh mờ, không đọc được chính xác
BLUR_THRESHOLD = 80

PROMPT = """Đây là ảnh phiếu giao hàng. Hãy trích xuất chính xác các thông tin sau và trả về JSON:

- "so_thu_tu": số viết tay bằng bút lớn ở góc trên bên phải tờ phiếu (thường là 2-3 chữ số)
- "ten_khach": tên khách hàng (sau nhãn "Khách hàng:" hoặc "Khách")
- "so_dien_thoai": số điện thoại (sau nhãn "Số điện thoại:")
- "dia_chi": địa chỉ đầy đủ (sau nhãn "Địa chỉ:"), nếu không có thì để chuỗi rỗng ""
- "tong_tien": số nguyên ở dòng "Tổng" (chỉ lấy số, bỏ "vnđ", bỏ dấu chấm/phẩy)

Ví dụ output đúng:
{"so_thu_tu": "65", "ten_khach": "Huỳnh Lâm", "so_dien_thoai": "0905826436", "dia_chi": "", "tong_tien": -28000}
{"so_thu_tu": "99", "ten_khach": "Minh Ngo", "so_dien_thoai": "0333868936", "dia_chi": "Cầu suối lở, Võ Tánh 1, Vĩnh Lương, TP. Nha Trang, Khánh Hòa", "tong_tien": 122000}

Chỉ trả về JSON thuần túy, không markdown, không giải thích."""


def fix_image_rotation(image_bytes: bytes) -> bytes:
    """Tự động xoay ảnh về đúng chiều dựa theo EXIF."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = ImageOps.exif_transpose(img)  # Xoay theo EXIF
        output = io.BytesIO()
        img.save(output, format='JPEG', quality=95)
        return output.getvalue()
    except Exception as e:
        print(f"[Rotation fix] Error: {e} — dùng ảnh gốc")
        return image_bytes


def detect_blur(image_bytes: bytes) -> float:
    """Tính độ sắc nét của ảnh bằng Laplacian variance. Càng thấp càng mờ."""
    try:
        img_array = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return 999  # Không decode được thì coi như sắc nét
        score = cv2.Laplacian(img, cv2.CV_64F).var()
        return score
    except Exception as e:
        print(f"[Blur detect] Error: {e}")
        return 999


async def extract_order_info(image_bytes: bytes) -> dict | None:
    # Bước 1: Tự động xoay ảnh về đúng chiều
    image_bytes = fix_image_rotation(image_bytes)

    # Bước 2: Kiểm tra độ mờ
    blur_score = detect_blur(image_bytes)
    if blur_score < BLUR_THRESHOLD:
        print(f"[Blur detect] Score={blur_score:.1f} — ảnh quá mờ, bỏ qua")
        return {"_blur": True, "_blur_score": round(blur_score, 1)}

    # Bước 3: Gửi Claude OCR
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
                        {
                            "type": "text",
                            "text": PROMPT,
                        },
                    ],
                }
            ],
        )

        text = response.content[0].text.strip()
        text = re.sub(r'```(?:json)?|```', '', text).strip()

        data = json.loads(text)

        # Format tong_tien để hiển thị đẹp
        tong = data.get('tong_tien', 0)
        try:
            data['tong_tien_fmt'] = f"{int(tong):,} vnđ".replace(',', '.')
        except (ValueError, TypeError):
            data['tong_tien_fmt'] = str(tong)

        return data

    except json.JSONDecodeError as e:
        print(f"[OCR] JSON parse error: {e} | Raw: {text}")
        return None
    except Exception as e:
        print(f"[OCR] Error: {e}")
        return None
