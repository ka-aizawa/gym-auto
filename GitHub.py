from playwright.sync_api import sync_playwright
from datetime import datetime, timedelta
import imaplib
import email
import re
import time
import os
import pytz
from email.header import decode_header

# =========================
# Gmailコード取得
# =========================
def get_code_safe(user, password):
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(user, password)
        mail.select("inbox")
        result, data = mail.search(None, "ALL")
        mail_ids = data[0].split()

        for mail_id in reversed(mail_ids[-5:]):
            result, msg_data = mail.fetch(mail_id, "(RFC822)")
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)

            subject = msg.get("Subject", "")
            decoded_subject = ""
            for part, enc in decode_header(subject):
                if isinstance(part, bytes):
                    decoded_subject += part.decode(enc or "utf-8", errors="ignore")
                else:
                    decoded_subject += part

            if "予約確認コード" not in decoded_subject:
                continue

            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() in ["text/plain", "text/html"]:
                        payload = part.get_payload(decode=True)
                        if payload:
                            body += payload.decode(errors="ignore")
            else:
                body = msg.get_payload(decode=True).decode(errors="ignore")

            match = re.search(r"\b\d{6}\b", body)
            if match:
                return match.group()

    except Exception as e:
        print("メール取得エラー:", e)

    return None

# =========================
# 環境変数
# =========================
USER = os.getenv("GMAIL_USER")
PASSWORD = os.getenv("GMAIL_PASSWORD")

if not USER or not PASSWORD:
    raise Exception("環境変数が設定されていません")

# =========================
# JST基準：7日後
# =========================
jst = pytz.timezone('Asia/Tokyo')
target_date = datetime.now(jst) + timedelta(days=7)
target_day = target_date.day

TARGET_HOUR = 2
TARGET_MIN = 0

# =========================
# 時刻パース
# =========================
def parse_time(text):
    text = text.lower().strip()
    match = re.search(r'(\d{1,2}):(\d{2})', text)
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2))

    if "pm" in text and hour != 12:
        hour += 12
    if "am" in text and hour == 12:
        hour = 0

    return hour, minute

# =========================
# メイン処理
# =========================
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)

    context = browser.new_context(
        timezone_id="Asia/Tokyo",
        locale="ja-JP",
        geolocation={"longitude": 139.6917, "latitude": 35.6895},
        permissions=["geolocation"],
        viewport={'width': 1280, 'height': 800}
    )

    page = context.new_page()

    try:
        print(f"🚀 予約開始: {target_day}日 02:00")

        page.goto("https://gym-sanctuary.com/reserve/", wait_until="networkidle")
        page.wait_for_timeout(8000)
        page.screenshot(path="./01_loaded.png")

        frame = page.frame_locator("iframe").first

        # -------------------------
        # 日付選択
        # -------------------------
        date_locator = frame.locator(f'button:has-text("{target_day}")')
        date_locator.first.wait_for(timeout=20000)
        date_locator.first.click(force=True)

        print(f"✅ 日付 {target_day}日 クリック")
        page.wait_for_timeout(8000)
        page.screenshot(path="./02_date_selected.png")

        # -------------------------
        # 時間選択
        # -------------------------
        all_buttons = frame.locator('button:has-text(":")').all()

        print(f"🔎 ボタン数: {len(all_buttons)}")

        selected = False

        for btn in all_buttons:
            raw = btn.inner_text()
            print("->", raw)

            parsed = parse_time(raw)
            if not parsed:
                continue

            hour, minute = parsed

            if hour == TARGET_HOUR and minute == TARGET_MIN:
                print(f"🎯 時間発見: {raw}")
                btn.click()
                selected = True
                break

        if not selected:
            print("❌ 02:00が見つからない")
            page.screenshot(path="./error_time.png")
            exit(1)

        page.wait_for_timeout(5000)
        page.screenshot(path="./03_time_selected.png")

        # -------------------------
        # フォーム入力
        # -------------------------
        frame.locator('input[type="email"]').wait_for(timeout=10000)

        name_inputs = frame.locator('input[type="text"]:visible')
        if name_inputs.count() >= 2:
            name_inputs.nth(0).fill("Aizawa")
            name_inputs.nth(1).fill("Katsushi")

        frame.locator('input[type="email"]:visible').fill(USER)

        try:
            frame.get_by_role("textbox", name="利用人数").fill("1")
        except:
            pass

        page.screenshot(path="./04_form_filled.png")

        frame.locator('button:has-text("予約")').click()
        print("📨 予約ボタン押下")

        page.wait_for_timeout(5000)
        page.screenshot(path="./05_after_reserve_click.png")

        # -------------------------
        # コード取得
        # -------------------------
        print("⌛ コード待機")

        code = None
        for _ in range(36):
            code = get_code_safe(USER, PASSWORD)
            if code:
                print(f"🔑 コード取得: {code}")
                break
            time.sleep(5)

        if not code:
            print("❌ コード取得失敗")
            page.screenshot(path="./error_code.png")
            exit(1)

        # iframe再取得
        frame = page.frame_locator("iframe").last

        code_input = frame.get_by_label("確認コード")
        code_input.fill(code)

        print("入力確認:", code_input.input_value())

        page.screenshot(path="./06_code_input.png")

        # 送信
        frame.locator('button[jsname="LdrfDc"]').click()
        print("📨 送信クリック")

        page.wait_for_timeout(8000)
        page.screenshot(path="./07_after_submit.png")

        # -------------------------
        # 成功判定
        # -------------------------
        try:
            page.wait_for_selector("text=予約", timeout=15000)
            print("🎉 予約成功確認！")
        except:
            print("❌ 成功判定できず")
            page.screenshot(path="./error_final.png")
            exit(1)

    except Exception as e:
        print(f"🚨 エラー: {e}")
        page.screenshot(path="./error_exception.png")
        raise e

    finally:
        # 🔥 必ず最後にスクショ
        page.screenshot(path="./99_final.png")
        print("📸 最終スクショ保存")
