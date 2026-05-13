import datetime
import os
import re

import gspread
from flask import Flask, abort, request
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import FileMessage, JoinEvent, MessageEvent, TextMessage, TextSendMessage
from oauth2client.service_account import ServiceAccountCredentials


LINE_CHANNEL_ACCESS_TOKEN = 'gQCIduqRTEeTTuGsb2Lzu1HDCYjXy/rFYTs2AJ4PqYzpTr/z0CeKH7fei7ANqatfLiDRBjcHZ6ddHp63EUx9IAz8ihbnj9RGPkO9bPI/ht54Xz8V9T4ljNnevzOilFM7WlcSg983CYXimz6Wu7WraAdB04t89/1O/w1cDnyilFU='
LINE_CHANNEL_SECRET = '6193d996f3609b069c00a6f5a0741b7b'
GOOGLE_SHEET_NAME = 'ระบบนับจำนวนเคส'
CREDENTIALS_FILE = 'credentials.json'

SUMMARY_COMMANDS = ["สรุปยอด", "เช็คยอด", "ยอดวันนี้"]

QUESTION_WORDS = [
    "ไหม", "มั้ย", "มั๊ย", "ยัง", "หรอ", "รึเปล่า", "หรือเปล่า",
    "ได้ปะ", "ได้ป่ะ", "รึยัง", "หรือยัง", "?", "สอบถาม", "ขอ",
    "ด้วย", "หน่อย", "ป่ะ", "ปะ", "หรือไม่", "ใช่ไหม", "แจ้ง", "ขอบคุณ",
    "รอผล", "รอ", "การ", "ไม่", "ก่อน", "เช็ค", "จาก", "หลัง", "ไม่อนุมัติ",
    "นะคะ", "นะค่ะ", "แล้ว"
]

APPROVE_KEYWORDS = [
    "อนุมัติ", "อนุมัติครับ", "อนุมัติค่ะ", "อนุมัต", "อนมัติ",
    "ทำระบบได้เลย"
]

RELEASE_KEYWORDS = [
    "ปล่อยเครื่อง", "ปล่อยได้", "ปล่อยเลย", "ปล่อยเคส", "ปล่อย", "ปลอ่ย", "ปลอย",
    "รบกวนแจ้งลูกค้าก่อน","ห้ามลูกค้าออกจาก iCloud โดยไม่มีเหตุจำเป็น"
]

IGNORE_FILE_KEYWORDS = ["IT4", "หนังสือให้ความยินยอม"]

app = Flask(__name__)
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)


def get_worksheet(sheet_name):
    scope = [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/drive'
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    sheet = client.open(GOOGLE_SHEET_NAME)
    return sheet.worksheet(sheet_name)


def safe_cell(row, index):
    return row[index].strip() if len(row) > index and row[index] else ""


def sync_group_name(group_id):
    try:
        summary = line_bot_api.get_group_summary(group_id)
        current_line_name = summary.group_name
    except Exception:
        current_line_name = f"Group_{group_id[-4:]}"

    try:
        sh = get_worksheet('Shops')
        try:
            cell = sh.find(group_id)
            stored_name = sh.cell(cell.row, 2).value
            if stored_name != current_line_name:
                sh.update_cell(cell.row, 2, current_line_name)
            return current_line_name
        except Exception:
            sh.append_row([group_id, current_line_name])
            return current_line_name
    except Exception as e:
        print(f"Error syncing group name: {e}")
        return current_line_name


def extract_login_info(text):
    normalized_text = text.replace("\r\n", "\n")
    link_match = re.search(r'https?://[^\s]+', normalized_text, re.IGNORECASE)
    username_match = re.search(
        r'(?im)^\s*(?:user|username|ชื่อผู้ใช้)\s*[:：]\s*(.+?)\s*$',
        normalized_text
    )
    password_match = re.search(
        r'(?im)^\s*(?:pass|password|รหัสผ่าน)\s*[:：]\s*(.+?)\s*$',
        normalized_text
    )

    if not link_match or not username_match or not password_match:
        return None

    return {
        "link": link_match.group(0).strip(),
        "username": username_match.group(1).strip(),
        "password": password_match.group(1).strip(),
    }


def upsert_shop_login_info(group_id, current_shop_name, login_info):
    try:
        sh = get_worksheet('Shops')
        all_rows = sh.get_all_values()

        found_row_index = None
        existing_name = ""
        existing_link = ""
        existing_username = ""
        existing_password = ""

        for i, row in enumerate(all_rows, start=1):
            if safe_cell(row, 0) == group_id:
                found_row_index = i
                existing_name = safe_cell(row, 1)
                existing_link = safe_cell(row, 2)
                existing_username = safe_cell(row, 3)
                existing_password = safe_cell(row, 4)
                break

        updated_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if not found_row_index:
            sh.append_row([
                group_id,
                current_shop_name,
                login_info["link"],
                login_info["username"],
                login_info["password"],
                updated_at,
            ])
            return "created"

        has_changed = False

        if existing_name != current_shop_name:
            sh.update_cell(found_row_index, 2, current_shop_name)
            has_changed = True
        if existing_link != login_info["link"]:
            sh.update_cell(found_row_index, 3, login_info["link"])
            has_changed = True
        if existing_username != login_info["username"]:
            sh.update_cell(found_row_index, 4, login_info["username"])
            has_changed = True
        if existing_password != login_info["password"]:
            sh.update_cell(found_row_index, 5, login_info["password"])
            has_changed = True

        if has_changed:
            sh.update_cell(found_row_index, 6, updated_at)
            return "updated"

        return "unchanged"
    except Exception as e:
        print(f"Error upserting shop login info: {e}")
        return "error"


def record_contract_in_sheet(group_id, current_shop_name, contract_name, today_str):
    try:
        sh = get_worksheet('Log')
        all_rows = sh.get_all_values()

        found_row_index = None
        current_contract_count = 0
        existing_names = []

        for i, row in enumerate(all_rows[1:]):
            if str(row[0]) == today_str and str(row[1]) == group_id:
                found_row_index = i + 2
                try:
                    current_contract_count = int(row[5]) if len(row) > 5 and row[5] else 0
                except Exception:
                    current_contract_count = 0

                try:
                    raw_names = str(row[6]) if len(row) > 6 else ""
                    existing_names = [n.strip() for n in raw_names.split(',') if n.strip()]
                except Exception:
                    existing_names = []
                break

        if contract_name in existing_names:
            print(f"Duplicate contract ignored: {contract_name}")
            return False

        existing_names.append(contract_name)
        new_names_str = ",".join(existing_names)

        if found_row_index:
            sh.update_cell(found_row_index, 6, current_contract_count + 1)
            sh.update_cell(found_row_index, 7, new_names_str)
            print(f"Contract updated: {contract_name}")
        else:
            sh.append_row([today_str, group_id, current_shop_name, 0, 0, 1, new_names_str])
            print(f"New contract record: {contract_name}")

        return True
    except Exception as e:
        print(f"Error recording contract: {e}")
        return False


def classify_message(text):
    normalized_text = text.lower().strip()

    for word in QUESTION_WORDS:
        if word in normalized_text:
            return None

    for word in APPROVE_KEYWORDS:
        if word in normalized_text:
            return 'approve'

    for word in RELEASE_KEYWORDS:
        if word in normalized_text:
            return 'release'

    return None






@app.route("/")
def home():
    return "Hello, Boss! I am awake and working."


@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'


@handler.add(JoinEvent)
def handle_join(event):
    group_id = event.source.group_id
    group_name = sync_group_name(group_id)
    reply_msg = f"✅ บันทึกชื่อร้านเรียบร้อย:\n{group_name}\n\nเริ่มงานได้เลยครับ!"
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_msg))


@handler.add(MessageEvent, message=FileMessage)
def handle_file(event):
    if event.source.type != 'group':
        return

    file_name = event.message.file_name
    if not file_name.lower().endswith('.pdf'):
        return

    for keyword in IGNORE_FILE_KEYWORDS:
        if keyword in file_name:
            print(f"Ignored file (Blacklist): {file_name}")
            return

    if '_' in file_name:
        contract_name = file_name.split('_')[0].strip()
    else:
        contract_name = os.path.splitext(file_name)[0].strip()

    group_id = event.source.group_id
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    current_shop_name = sync_group_name(group_id)
    record_contract_in_sheet(group_id, current_shop_name, contract_name, today_str)


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    if event.source.type != 'group':
        return

    group_id = event.source.group_id
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    current_shop_name = sync_group_name(group_id)

    login_info = extract_login_info(text)
    if login_info:
        upsert_shop_login_info(group_id, current_shop_name, login_info)
        return

    if "contract_signature.php" in text and "contract_code=" in text:
        match = re.search(r'contract_code=([^&\s]+)', text)
        if match:
            contract_name = match.group(1).strip()
            record_contract_in_sheet(group_id, current_shop_name, contract_name, today_str)
            return

    if "m-leasing.net/sign-application/" in text:
        match = re.search(r'sign-application/([^?\s]+)', text)
        if match:
            contract_name = match.group(1).strip()
            record_contract_in_sheet(group_id, current_shop_name, contract_name, today_str)
            return

    msg_type = classify_message(text)
    if not msg_type and text not in SUMMARY_COMMANDS:
        return

    if msg_type:
        try:
            sh = get_worksheet('Log')
            all_rows = sh.get_all_values()

            found_row_index = None
            current_approve = 0
            current_release = 0

            for i, row in enumerate(all_rows[1:]):
                if str(row[0]) == today_str and str(row[1]) == group_id:
                    found_row_index = i + 2

                    if row[2] != current_shop_name:
                        sh.update_cell(found_row_index, 3, current_shop_name)

                    try:
                        current_approve = int(row[3]) if row[3] else 0
                    except Exception:
                        current_approve = 0
                    try:
                        current_release = int(row[4]) if row[4] else 0
                    except Exception:
                        current_release = 0
                    break

            if found_row_index:
                if msg_type == 'approve':
                    sh.update_cell(found_row_index, 4, current_approve + 1)
                elif msg_type == 'release':
                    sh.update_cell(found_row_index, 5, current_release + 1)
            else:
                if msg_type == 'approve':
                    sh.append_row([today_str, group_id, current_shop_name, 1, 0, 0, ""])
                elif msg_type == 'release':
                    sh.append_row([today_str, group_id, current_shop_name, 0, 1, 0, ""])
        except Exception as e:
            print(f"Error writing to sheet: {e}")
        return

    try:
        sh = get_worksheet('Log')
        all_rows = sh.get_all_values()

        approve_count = 0
        release_count = 0
        contract_count = 0

        for row in all_rows[1:]:
            if str(row[0]) == today_str and str(row[1]) == group_id:
                try:
                    approve_count = int(row[3]) if row[3] else 0
                except Exception:
                    approve_count = 0
                try:
                    release_count = int(row[4]) if row[4] else 0
                except Exception:
                    release_count = 0
                try:
                    contract_count = int(row[5]) if len(row) > 5 and row[5] else 0
                except Exception:
                    contract_count = 0
                break

        msg = f"📊 สรุปยอดวันนี้ ({today_str})\n"
        msg += f"🏠 {current_shop_name}\n"
        msg += "------------------\n"
        msg += f"✅ อนุมัติ: {approve_count} เคส\n"
        msg += f"📦 ปล่อยเครื่อง: {release_count} เครื่อง\n"
        msg += f"📝 สัญญา: {contract_count} ฉบับ"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))
    except Exception:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="เกิดข้อผิดพลาดในการดึงข้อมูลครับ")
        )


if __name__ == "__main__":
    app.run()
