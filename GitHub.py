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
# 環境変数・設定
# =========================
USER = os.getenv("GMAIL_USER")
PASSWORD = os.getenv("GMAIL_PASSWORD")
TARGET_TIME = "1:00am"

if not USER or not PASSWORD:
    raise Exception("環境変数が設定されていません")

# 日本時間で「今日から7日後」を計算
jst = pytz.timezone('Asia/Tokyo')
target_date = datetime.now(jst) + timedelta(days=7)
target_day = target_date.day

# =========================
# メイン処理
# =========================
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    
    # 日本語環境・日本時間を設定
    context = browser.new_context(
        timezone_id="Asia/Tokyo",
        locale="ja-JP",
        viewport={'width': 1280, 'height': 800},
        extra_http_headers={"Accept-Language": "ja-JP,ja;q=0.9"}
    )
    
    # 【重要】ブラウザ内部のJavaScriptレベルでタイムゾーンを日本に偽装
    context.add_init_script("""
        Object.defineProperty(Intl.DateTimeFormat.prototype, 'resolvedOptions', {
            value: () => ({
                calendar: 'gregory',
                day: 'numeric',
                locale: 'ja-JP',
                month: 'numeric',
                numberingSystem: 'latn',
                timeZone: 'Asia/Tokyo',
                year: 'numeric'
            })
        });
    """)
    
    page = context.new_page()

    try:
        print(f"🚀 予約開始: ターゲット {target_day}日 {TARGET_TIME}")
        page.goto("https://gym-sanctuary.com/reserve/", wait_until="networkidle")
        
        # iframeのロード待機
        page.wait_for_timeout(7000)
        frame = page.frame_locator("iframe").first

        # 「空きがない」場合に「次の予約可能日へ」リンクがあれば押す
        jump_link = frame.get_by_text("Jump to the next bookable date")
        if jump_link.count() > 0:
            print("🔗 'Jump to the next bookable date' をクリック")
            jump_link.click()
            page.wait_for_timeout(5000)

        # -------------------------
        # 日付選択
        # -------------------------
        # カレンダー内の指定日ボタンを探す
        date_locator = frame.locator(f'button:has-text("{target_day}"), [role="button"]:has-text("{target_day}")').filter(has_not_text="April")
        
        try:
            date_locator.first.wait_for(timeout=15000)
            date_locator.first.scroll_into_view_if_needed()
            date_locator.first.click(force=True, delay=200)
            print(f"✅ 日付 {target_day}日 を選択")
        except:
            print(f"❌ 日付 {target_day}日 が見つかりません。")
            page.screenshot(path="debug_screenshot.png")
            exit(1)

        page.wait_for_timeout(8000)

        # -------------------------
        # 時間選択
        # -------------------------
        # まず何らかの時間ボタンが出るまで待つ
        try:
            frame.locator('div:has-text("am"), div:has-text("pm")').first.wait_for(timeout=20000)
        except:
            print("⚠️ 時間ボタンが一切表示されません。")
            page.screenshot(path="debug_screenshot.png")
            exit(1)

        # 指定時間をクリック
        time_btn = frame.locator(f'div[role="button"]:has-text("{TARGET_TIME}")').first
        
        if time_btn.count() > 0:
            time_btn.click(delay=200)
            print(f"✅ 時間 {TARGET_TIME} を選択")
        else:
            print(f"❌ {TARGET_TIME} のボタンが見つかりません。")
            page.screenshot(path="debug_screenshot.png")
            exit(1)

        page.wait_for_timeout(3000)

        # -------------------------
        # フォーム入力
        # -------------------------
        print("📝 フォーム入力中...")
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

        # 予約（次へ）ボタン
        reserve_btn = frame.locator('button:has-text("予約")')
        reserve_btn.click(delay=200)
        print("👆 予約確認画面へ")

        # -------------------------
        # 確認コード
        # -------------------------
        print("⌛ コード取得中...")
        code = None
        for _ in range(36):
            code = get_code_safe(USER, PASSWORD)
            if code:
                print(f"🔑 コード: {code}")
                break
            time.sleep(5)

        if not code:
            print("❌ コード取得失敗")
            page.screenshot(path="debug_screenshot.png")
            exit(1)

        # コード入力と最終送信
        frame.get_by_label("確認コード").fill(code)
        # 送信ボタンは jsname="LdrfDc" を狙う
        submit_btn = frame.locator('button[jsname="LdrfDc"]')
        submit_btn.click(delay=200)
        
        print("🎉 予約完了処理終了")
        page.wait_for_timeout(5000)

    except Exception as e:
        print(f"🚨 異常終了: {e}")
        page.screenshot(path="error_screenshot.png")
        raise e
