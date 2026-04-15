from playwright.sync_api import sync_playwright
from datetime import datetime, timedelta
import imaplib
import email
import re
import time
import os
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

target_day = (datetime.now() + timedelta(days=7)).day


# =========================
# メイン処理
# =========================
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    page.goto("https://gym-sanctuary.com/reserve/")
    page.wait_for_timeout(5000)

    frame = page.frame_locator("iframe")

    # -------------------------
    # 日付選択
    # -------------------------
    date_btn = frame.locator(f"text={target_day}").first
    date_btn.wait_for(timeout=20000)
    date_btn.click()

    print("日付選択OK")

# -------------------------
# iframe取得（修正版）
# -------------------------
frame = page.frame_locator('iframe').first
frame.locator("body").wait_for(timeout=20000)

page.wait_for_timeout(5000)

# -------------------------
# 時間取得
# -------------------------
time_buttons = frame.locator('div[role="button"]:has-text(":")')

count = time_buttons.count()
print("時間ボタン数:", count)

if count == 0:
    print("❌ 時間が取得できない（iframe or UI問題）")
    browser.close()
    exit()

print("利用可能時間一覧:")

selected = False

for i in range(count):
    btn = time_buttons.nth(i)
    try:
        text = btn.inner_text()
        print(f"{i}: {text}")

        if "02:00" in text:
            btn.click()
            print("時間選択OK")
            selected = True
            break

    except:
        continue

if not selected:
    print("❌ 指定時間なし")

page.screenshot(path="debug.png")
    
    browser.close()
    exit()

    page.wait_for_timeout(2000)

    # -------------------------
    # フォーム入力
    # -------------------------
    name_inputs = frame.locator('input[type="text"]:visible')
    name_inputs.nth(0).fill("Aizawa")
    name_inputs.nth(1).fill("Katsushi")

    frame.locator('input[type="email"]:visible').fill(USER)
    frame.get_by_role("textbox", name="利用人数").fill("1")

    print("フォーム入力OK")

    # -------------------------
    # 予約ボタン
    # -------------------------
    reserve_btn = frame.locator('button:has-text("予約")')
    reserve_btn.wait_for(timeout=10000)
    reserve_btn.click()

    print("予約ボタン押下")

    # -------------------------
    # 確認コード待機
    # -------------------------
    frame.get_by_label("確認コード").wait_for(timeout=20000)

    print("⌛ コード待機開始（最大180秒）")

    code = None
    for _ in range(36):
        code = get_code_safe(USER, PASSWORD)
        if code:
            print("✅ コード取得:", code)
            break
        time.sleep(5)

    if not code:
        print("❌ コード取得失敗")
        browser.close()
        exit()

    page.wait_for_timeout(2000)

    # -------------------------
    # コード入力
    # -------------------------
    code_input = frame.get_by_label("確認コード")
    code_input.wait_for(timeout=10000)
    code_input.fill(code)

    print("コード入力OK")

    # -------------------------
    # 送信
    # -------------------------
    submit_btn = frame.locator('button[jsname="LdrfDc"]')
    submit_btn.wait_for(timeout=10000)
    submit_btn.click()

    print("🎉 予約完了")

    page.wait_for_timeout(5000)
    browser.close()
