import logging
import os
from datetime import datetime
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
from ocr_processor import extract_order_info
from sheet_writer import write_to_sheet

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Lưu trạng thái xử lý theo từng nhóm (chat_id)
# batch_state[chat_id] = {"ok": [...], "fail": 0}
batch_state: dict = {}


def get_state(chat_id: int) -> dict:
    if chat_id not in batch_state:
        batch_state[chat_id] = {"ok": [], "fail": 0, "start_time": datetime.now()}
    return batch_state[chat_id]


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.photo:
        return

    chat_id = message.chat_id
    photo = message.photo[-1]  # Độ phân giải cao nhất

    try:
        photo_file = await context.bot.get_file(photo.file_id)
        photo_bytes = await photo_file.download_as_bytearray()

        result = await extract_order_info(bytes(photo_bytes))
        state = get_state(chat_id)

        if result:
            row_num = write_to_sheet(result)
            if row_num:
                state["ok"].append({
                    "stt": result.get("so_thu_tu", "?"),
                    "ten": result.get("ten_khach", "?"),
                    "tong": result.get("tong_tien_fmt", "?"),
                })
            else:
                state["fail"] += 1
        else:
            state["fail"] += 1

    except Exception as e:
        logger.error(f"Error processing photo: {e}")
        get_state(message.chat_id)["fail"] += 1


async def handle_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /xong — gửi tổng kết và reset trạng thái."""
    chat_id = update.message.chat_id
    state = batch_state.get(chat_id)

    if not state or (len(state["ok"]) == 0 and state["fail"] == 0):
        await update.message.reply_text("ℹ️ Chưa có ảnh nào được gửi kể từ lần /xong trước.")
        return

    ok_list = state["ok"]
    fail_count = state["fail"]
    total = len(ok_list) + fail_count
    today = datetime.now().strftime('%d-%m-%Y')

    # Dòng tổng kết
    lines = [
        f"📋 <b>Tổng kết lô ảnh — {today}</b>",
        f"━━━━━━━━━━━━━━━",
        f"✅ Thành công: <b>{len(ok_list)}/{total}</b> ảnh",
    ]

    if fail_count > 0:
        lines.append(f"❌ Lỗi / không đọc được: <b>{fail_count}</b> ảnh")

    # Danh sách các đơn đã ghi (tối đa 20 dòng để không quá dài)
    if ok_list:
        lines.append(f"━━━━━━━━━━━━━━━")
        lines.append(f"<b>Các đơn đã ghi vào Sheet:</b>")
        for i, item in enumerate(ok_list[:20], 1):
            lines.append(f"{i}. STT <b>{item['stt']}</b> | {item['ten']} | {item['tong']}")
        if len(ok_list) > 20:
            lines.append(f"... và {len(ok_list) - 20} đơn khác")

    lines.append(f"━━━━━━━━━━━━━━━")
    lines.append(f"📊 Xem chi tiết: Sheet tab <b>{today}</b>")

    await update.message.reply_text("\n".join(lines), parse_mode='HTML')

    # Reset trạng thái cho lần gửi tiếp theo
    batch_state.pop(chat_id, None)


async def handle_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lệnh /reset — huỷ đếm lô hiện tại (nếu gửi nhầm)."""
    chat_id = update.message.chat_id
    batch_state.pop(chat_id, None)
    await update.message.reply_text("🔄 Đã reset. Gửi ảnh mới là bắt đầu lô tiếp theo.")


def main():
    token = os.environ['TELEGRAM_BOT_TOKEN']
    app = Application.builder().token(token).build()

    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(CommandHandler("xong", handle_done))
    app.add_handler(CommandHandler("reset", handle_reset))

    logger.info("✅ OCR Order Bot đã khởi động.")
    app.run_polling(allowed_updates=["message"])


if __name__ == '__main__':
    main()
