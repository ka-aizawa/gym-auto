from playwright.sync_api import sync_playwright
from datetime import datetime, timedelta
import imaplib
import email
import re
import time
import os
import pytz  # タイムゾーン用に追加
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
TARGET_TIME = "1:00am"

if not USER or not PASSWORD:
    raise Exception("環境変数が設定されていません")

# 日本時間で「今日から7日後」の日付(day)を確実に取得
jst = pytz.timezone('Asia/Tokyo')
target_date = datetime.now(jst) + timedelta(days=7)
target_day = target_date.day

# =========================
# メイン処理
# =========================
with sync_playwright() as p:
    # タイムゾーンを日本に設定してブラウザ起動
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(timezone_id="Asia/Tokyo")
    page = context.new_page()

    try:
        print(f"🚀 予約タスク開始: ターゲット {target_day}日 {TARGET_TIME}")
        page.goto("https://gym-sanctuary.com/reserve/", wait_until="networkidle")
        page.wait_for_timeout(5000)

        # iframeを取得
        frame = page.frame_locator("iframe").first

        # -------------------------
        # 日付選択
        # -------------------------
        # その日のボタンを特定（テキストが完全に一致するものを探す）
        date_btn = frame.locator(f"text={target_day}").first
        date_btn.wait_for(timeout=20000)
        
        # 少し長押し気味にクリックして確実に反応させる
        date_btn.click(delay=150)
        print(f"✅ 日付選択ボタン({target_day}日)を押しました")

        # 重要：日付クリック後、時間が表示されるまで長めに待機
        page.wait_for_timeout(10000)

        # -------------------------
        # 時間取得
        # -------------------------
        # iframeを再認識
        frame = page.frame_locator("iframe").first
        time_button_selector = 'div[role="button"]:has-text("am"), div[role="button"]:has-text("pm")'
        
        try:
            print("⌛ 時間ボタンの出現を待機中...")
            frame.locator(time_button_selector).first.wait_for(timeout=30000)
        except:
            print("⚠️ 時間ボタンが時間内に表示されませんでした。")
            page.screenshot(path="debug_screenshot.png")
            exit(1)

        time_buttons = frame.locator(time_button_selector)
        count = time_buttons.count()
        print(f"📊 見つかった時間枠数: {count}")

        selected = False
        for i in range(count):
            btn = time_buttons.nth(i)
            time_text = btn.inner_text().replace("\n", "").strip().lower()
            print(f"  [{i}]: {time_text}")

            if TARGET_TIME.lower() in time_text:
                btn.click(delay=100)
                print(f"✅ 時間選択完了: {time_text}")
                selected = True
                break

        if not selected:
            print(f"❌ 指定時間({TARGET_TIME})が見つかりません。")
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
            frame.get_by_role("textbox", name="利用人数").fill("1")
        except:
            pass

        print("✅ フォーム入力完了")

        # -------------------------
        # 予約ボタン
        # -------------------------
        reserve_btn = frame.locator('button:has-text("予約")')
        reserve_btn.click(delay=100)
        print("👆 予約確認画面へ進みます")

        # -------------------------
        # 確認コード待機
        # -------------------------
        print("⌛ Gmailからコードを取得中...")
        code = None
        for _ in range(36):
            code = get_code_safe(USER, PASSWORD)
            if code:
                print(f"🔑 コード取得成功: {code}")
                break
            time.sleep(5)

        if not code:
            print("❌ コードが届きませんでした")
            page.screenshot(path="debug_screenshot.png")
            exit(1)

        # コード入力
        code_input = frame.get_by_label("確認コード")
        code_input.wait_for(timeout=10000)
        code_input.fill(code)
        
        # 最終送信
        submit_btn = frame.locator('button[jsname="LdrfDc"]')
        submit_btn.click(delay=100)
        print("🎉 予約完了！")
        
        page.wait_for_timeout(5000)

    except Exception as e:
        print(f"🚨 エラー: {e}")
        page.screenshot(path="error_screenshot.png")
        raise e
