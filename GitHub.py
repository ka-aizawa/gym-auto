from playwright.sync_api import sync_playwright
from datetime import datetime, timedelta
import imaplib
import email
import re
import time
import os
from email.header import decode_header

# =========================
# Gmailコード取得（安全版）
# =========================
def get_code_safe(user, password):
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(user, password)
        mail.select("inbox")

        result, data = mail.search(None, "ALL")
        mail_ids = data[0].split()

        # 最新5件だけ見る（高速化）
        for mail_id in reversed(mail_ids[-5:]):
            result, msg_data = mail.fetch(mail_id, "(RFC822)")
            raw_email = msg_data[0][1]

            msg = email.message_from_bytes(raw_email)

            # 件名デコード
            subject = msg.get("Subject", "")
            decoded_subject = ""
            for part, enc in decode_header(subject):
                if isinstance(part, bytes):
                    decoded_subject += part.decode(enc or "utf-8", errors="ignore")
                else:
                    decoded_subject += part

            if "予約確認コード" not in decoded_subject:
                continue

            # 本文取得
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() in ["text/plain", "text/html"]:
                        payload = part.get_payload(decode=True)
                        if payload:
                            body += payload.decode(errors="ignore")
            else:
                body = msg.get_payload(decode=True).decode(errors="ignore")

            # 6桁コード抽出
            match = re.search(r"\b\d{6}\b", body)
            if match:
                return match.group()

    except Exception as e:
        print("⚠️ メール取得エラー:", e)

    return None


# =========================
# 環境変数（GitHub Secrets）
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
    browser = p.chromium.launch(headless=True)  # ★重要（クラウド用）
    context = browser.new_context()
    page = context.new_page()

    page.goto("https://gym-sanctuary.com/reserve/")
    page.wait_for_timeout(5000)

    frame = page.frame_locator("iframe")

    # -------------------------
    # 日付・時間選択
    # -------------------------
    frame.locator(f"text={target_day}").first.click()
    frame.locator("text=02:00").first.click()
    page.wait_for_timeout(2000)

    # -------------------------
    # フォーム入力
    # -------------------------
    name_inputs = frame.locator('input[type="text"]:visible')
    name_inputs.nth(0).fill("Aizawa")
    name_inputs.nth(1).fill("Katsushi")

    frame.locator('input[type="email"]:visible').fill(USER)
    frame.get_by_role("textbox", name="利用人数").fill("1")

    # -------------------------
    # 予約ボタン押下
    # -------------------------
    frame.locator('button:has-text("予約")').click()

    # -------------------------
    # 確認コード入力欄待機
    # -------------------------
    frame.get_by_label("確認コード").wait_for(timeout=20000)

    print("⌛ コード待機開始（最大180秒）")

    # -------------------------
    # コード取得（最大3分）
    # -------------------------
    code = None
    for _ in range(36):  # 5秒 × 36 = 180秒
        code = get_code_safe(USER, PASSWORD)
        if code:
            print("✅ コード取得:", code)
            break
        time.sleep(5)

    if not code:
        print("❌ コード取得失敗")
        browser.close()
        exit()

    # UI安定待ち
    page.wait_for_timeout(2000)

    # -------------------------
    # コード入力
    # -------------------------
    frame.get_by_label("確認コード").fill(code)

    # -------------------------
    # 送信ボタン（確定版）
    # -------------------------
    frame.locator('button[jsname="LdrfDc"]').wait_for()
    frame.locator('button[jsname="LdrfDc"]').click()

    print("🎉 予約完了")

    page.wait_for_timeout(5000)
    browser.close()