import anthropic
import base64
import json
import os
import re

client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])

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


async def extract_order_info(image_bytes: bytes) -> dict | None:
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
        # Xử lý trường hợp model trả thêm markdown code fence
        text = re.sub(r'```(?:json)?|```', '', text).strip()

        data = json.loads(text)

        # Format tong_tien để hiển thị đẹp trong Telegram
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
