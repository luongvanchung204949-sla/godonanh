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

batch_state: dict = {}


def get_state(chat_id: int) -> dict:
    if chat_id not in batch_state:
        batch_state[chat_id] = {"ok": [], "fail": 0, "blur": [], "wrong_fmt": 0, "start_time": datetime.now()}
    return batch_state[chat_id]


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.photo:
        return

    chat_id = message.chat_id
    photo = message.photo[-1]

    try:
        photo_file = await context.bot.get_file(photo.file_id)
        photo_bytes = await photo_file.download_as_bytearray()
        result = await extract_order_info(bytes(photo_bytes))
        state = get_state(chat_id)

        if result is None:
            state["fail"] += 1

        elif result.get("_wrong_format"):
            await message.reply_text(
                "⛔ Ảnh này không phải phiếu CHOTDON.VN (phiếu viết tay hoặc định dạng khác).\n"
                "Bot chỉ xử lý phiếu in từ hệ thống CHOTDON.VN."
            )
            state["wrong_fmt"] += 1

        elif result.get("_blur"):
            score = result.get("_blur_score", 0)
            await message.reply_text(
                f"⚠️ Ảnh này bị mờ (độ sắc nét: {score}), không đọc được chính xác.\n"
                f"Vui lòng chụp lại và gửi lại ảnh này."
            )
            state["blur"].append(score)

        else:
            row_num = write_to_sheet(result)
            if row_num:
                state["ok"].append({
                    "stt": result.get("stt", "?"),
                    "ten": result.get("ten_khach", "?"),
                    "tong": result.get("tong_tien_fmt", "?"),
                })
            else:
                state["fail"] += 1

    except Exception as e:
        logger.error(f"Error processing photo: {e}")
        get_state(message.chat_id)["fail"] += 1


async def handle_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    state = batch_state.get(chat_id)

    total_processed = (
        len(state["ok"]) + state["fail"] + len(state["blur"]) + state["wrong_fmt"]
        if state else 0
    )

    if not state or total_processed == 0:
        await update.message.reply_text("ℹ️ Chưa có ảnh nào được gửi kể từ lần /xong trước.")
        return

    ok_list = state["ok"]
    fail_count = state["fail"]
    blur_count = len(state["blur"])
    wrong_fmt_count = state["wrong_fmt"]
    total = len(ok_list) + fail_count + blur_count + wrong_fmt_count
    today = datetime.now().strftime('%d-%m-%Y')

    lines = [
        f"📋 <b>Tổng kết lô ảnh — {today}</b>",
        f"━━━━━━━━━━━━━━━",
        f"✅ Thành công: <b>{len(ok_list)}/{total}</b> ảnh",
    ]
    if blur_count > 0:
        lines.append(f"📷 Ảnh mờ cần chụp lại: <b>{blur_count}</b> ảnh")
    if wrong_fmt_count > 0:
        lines.append(f"⛔ Không phải phiếu CHOTDON.VN: <b>{wrong_fmt_count}</b> ảnh")
    if fail_count > 0:
        lines.append(f"❌ Lỗi khác: <b>{fail_count}</b> ảnh")

    if ok_list:
        lines.append(f"━━━━━━━━━━━━━━━")
        lines.append(f"<b>Các đơn đã ghi vào Sheet:</b>")
        for i, item in enumerate(ok_list[:20], 1):
            lines.append(f"{i}. {item["stt"]} | {item['ten']} | {item['tong']}")
        if len(ok_list) > 20:
            lines.append(f"... và {len(ok_list) - 20} đơn khác")

    lines.append(f"━━━━━━━━━━━━━━━")
    lines.append(f"📊 Xem chi tiết: Sheet tab <b>{today}</b>")

    await update.message.reply_text("\n".join(lines), parse_mode='HTML')
    batch_state.pop(chat_id, None)


async def handle_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
