import gspread
from google.oauth2.service_account import Credentials
import os
import json
from datetime import datetime

SCOPES = [
    'https://spreadsheets.google.com/feeds',
    'https://www.googleapis.com/auth/drive',
]

HEADERS = ['STT', 'Tên khách', 'Số điện thoại', 'Địa chỉ', 'Tổng tiền', 'Thời gian nhập']


def get_worksheet():
    creds_json = os.environ['GOOGLE_SERVICE_ACCOUNT_JSON']
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    gc = gspread.authorize(creds)

    sheet_id = os.environ['GOOGLE_SHEET_ID']
    spreadsheet = gc.open_by_key(sheet_id)

    # Tab theo ngày: 01-07-2026
    today = datetime.now().strftime('%d-%m-%Y')

    try:
        worksheet = spreadsheet.worksheet(today)
    except gspread.exceptions.WorksheetNotFound:
        # Tạo tab mới nếu chưa có
        worksheet = spreadsheet.add_worksheet(title=today, rows=500, cols=10)
        worksheet.append_row(HEADERS)
        worksheet.format('A1:F1', {
            'textFormat': {'bold': True},
            'backgroundColor': {'red': 0.27, 'green': 0.51, 'blue': 0.71},
        })

    return worksheet


def write_to_sheet(data: dict) -> int | None:
    try:
        worksheet = get_worksheet()
        now = datetime.now().strftime('%H:%M:%S')

        row = [
            data.get('stt', ''),
            data.get('ten_khach', ''),
            data.get('so_dien_thoai', ''),
            data.get('dia_chi', ''),
            data.get('tong_tien', ''),
            now,
        ]
        worksheet.append_row(row, value_input_option='USER_ENTERED')

        # Trả về số dòng hiện tại (trừ 1 dòng header)
        all_rows = worksheet.get_all_values()
        return len(all_rows) - 1

    except Exception as e:
        print(f"[Sheet] Write error: {e}")
        return None
