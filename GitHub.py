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
# 環境変数・設定
# =========================
USER = os.getenv("GMAIL_USER")
PASSWORD = os.getenv("GMAIL_PASSWORD")
TARGET_TIME = "1:00am"  # 予約したい時間

if not USER or not PASSWORD:
    raise Exception("環境変数が設定されていません")

# 7日後の日付を取得
target_day = (datetime.now() + timedelta(days=7)).day

# =========================
# メイン処理
# =========================
with sync_playwright() as p:
    # タイムゾーンを日本に設定して起動
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(timezone_id="Asia/Tokyo")
    page = context.new_page()

    try:
        print(f"🚀 予約開始: ターゲット {target_day}日 {TARGET_TIME}")
        page.goto("https://gym-sanctuary.com/reserve/", wait_until="networkidle")
        page.wait_for_timeout(5000)

        frame = page.frame_locator("iframe").first

        # -------------------------
        # 日付選択
        # -------------------------
        date_btn = frame.locator(f"text={target_day}").first
        date_btn.wait_for(timeout=20000)
        date_btn.click()
        print(f"✅ 日付選択完了: {target_day}日")

        # クリック後の読み込み待ち
        page.wait_for_timeout(5000)

        # -------------------------
        # 時間取得
        # -------------------------
        # スクショに基づき、am/pmを含むボタンを探す
        time_button_selector = 'div[role="button"]:has-text("am"), div[role="button"]:has-text("pm")'
        
        try:
            # 最初のボタンが出るまで最大20秒待つ
            frame.locator(time_button_selector).first.wait_for(timeout=20000)
        except:
            print("⚠️ 時間ボタンが表示されませんでした。")
            page.screenshot(path="debug_screenshot.png")
            exit(1)

        time_buttons = frame.locator(time_button_selector)
        count = time_buttons.count()
        print(f"📊 見つかった時間枠数: {count}")

        selected = False
        for i in range(count):
            btn = time_buttons.nth(i)
            # テキストを抽出してクリーンアップ（例: "1:00am"）
            time_text = btn.inner_text().replace("\n", "").strip().lower()
            print(f"  [{i}]: {time_text}")

            if TARGET_TIME.lower() in time_text:
                btn.click()
                print(f"✅ 時間選択完了: {time_text}")
                selected = True
                break

        if not selected:
            print(f"❌ 指定時間({TARGET_TIME})が見つかりませんでした。")
            page.screenshot(path="debug_screenshot.png")
            exit(1)

        page.wait_for_timeout(3000)

        # -------------------------
        # フォーム入力
        # -------------------------
        name_inputs = frame.locator('input[type="text"]:visible')
        name_inputs.first.wait_for(timeout=10000)
        
        if name_inputs.count() >= 2:
            name_inputs.nth(0).fill("Aizawa")
            name_inputs.nth(1).fill("Katsushi")

        frame.locator('input[type="email"]:visible').fill(USER)
        
        try:
            # 利用人数入力
            frame.get_by_role("textbox", name="利用人数").fill("1")
        except:
            pass

        print("✅ フォーム入力完了")

        # -------------------------
        # 予約ボタン
        # -------------------------
        reserve_btn = frame.locator('button:has-text("予約")')
        reserve_btn.click()
        print("👆 予約ボタンを押しました")

        # -------------------------
        # 確認コード待機
        # -------------------------
        print("⌛ メールからコードを取得中...")
        code = None
        for _ in range(36):  # 3分間チェック
            code = get_code_safe(USER, PASSWORD)
            if code:
                print(f"🔑 コード取得成功: {code}")
                break
            time.sleep(5)

        if not code:
            print("❌ タイムアウト: コードが届きませんでした")
            page.screenshot(path="debug_screenshot.png")
            exit(1)

        # コード入力
        code_input = frame.get_by_label("確認コード")
        code_input.wait_for(timeout=10000)
        code_input.fill(code)
        
        # 最終送信
        submit_btn = frame.locator('button[jsname="LdrfDc"]')
        submit_btn.click()
        print("🎉 予約処理が完了しました！")
        
        page.wait_for_timeout(5000)

    except Exception as e:
        print(f"🚨 エラー発生: {e}")
        page.screenshot(path="error_screenshot.png")
        raise e
