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

if not USER or not PASSWORD:
    raise Exception("環境変数が設定されていません")

# 日本時間で「今日から7日後」を計算（16日なら23日）
jst = pytz.timezone('Asia/Tokyo')
target_date = datetime.now(jst) + timedelta(days=7)
target_day = target_date.day

# =========================
# メイン処理
# =========================
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    # ブラウザ設定（タイムゾーンは一応Tokyoにするが、IPで上書きされる可能性を考慮）
    context = browser.new_context(
        timezone_id="Asia/Tokyo",
        locale="ja-JP",
        viewport={'width': 1280, 'height': 800}
    )
    page = context.new_page()

    try:
        print(f"🚀 予約開始: 日本時間 ターゲット {target_day}日")
        page.goto("https://gym-sanctuary.com/reserve/", wait_until="networkidle")
        
        # iframeのロード待機（長めに設定）
        page.wait_for_timeout(10000)
        frame = page.frame_locator("iframe").first

        # -------------------------
        # 日付選択
        # -------------------------
        # カレンダーから target_day を探す
        # 4月などの年号と被らないようフィルタリング
        date_locator = frame.locator(f'button:has-text("{target_day}"), [role="button"]:has-text("{target_day}")').filter(has_not_text="2026")
        
        try:
            date_locator.first.wait_for(timeout=20000)
            date_locator.first.scroll_into_view_if_needed()
            date_locator.first.click(force=True, delay=200)
            print(f"✅ 日付 {target_day}日 をクリックしました")
        except:
            print(f"❌ 日付 {target_day}日 が見つかりません。")
            page.screenshot(path="debug_screenshot.png")
            exit(1)

        # クリック後、時間枠が出るまでしっかり待機
        page.wait_for_timeout(10000)

        # -------------------------
        # 時間選択（数字抽出ロジック）
        # -------------------------
        # 全てのボタン要素を取得して1つずつ中身をチェックする
        all_buttons = frame.locator('div[role="button"]').all()
        
        selected = False
        print(f"🔎 時間ボタンをスキャン中... (合計 {len(all_buttons)}個)")

        for btn in all_buttons:
            raw_text = btn.inner_text().lower()
            # 正規表現で数字だけを抜き出す (例: "01:00am" -> "0100", "1:00" -> "100")
            digits = "".join(re.findall(r"\d+", raw_text))
            
            # 午後(pm)は除外する（1:00pmを避けるため）
            if "pm" in raw_text:
                continue
            
            # 抽出した数字が "100" か "0100" なら、それが日本の深夜1時
            if digits in ["100", "0100"]:
                print(f"🎯 ターゲットを発見しました: '{raw_text}' (数字判定: {digits})")
                btn.click(delay=200)
                selected = True
                break

        if not selected:
            # 失敗した場合はデバッグ情報を出力
            found_texts = [b.inner_text().replace("\n", " ") for b in all_buttons]
            print(f"❌ 1:00に該当する枠が見つかりませんでした。 見つかったボタン: {found_texts}")
            page.screenshot(path="debug_screenshot.png")
            exit(1)

        page.wait_for_timeout(5000)

        # -------------------------
        # フォーム入力
        # -------------------------
        print("📝 フォーム入力開始...")
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

        # 予約ボタン
        reserve_btn = frame.locator('button:has-text("予約")')
        reserve_btn.click(delay=200)
        print("👆 予約確認画面へ移動中...")

        # -------------------------
        # 確認コード
        # -------------------------
        print("⌛ Gmailから認証コードを取得中...")
        code = None
        for _ in range(36):  # 約3分間
            code = get_code_safe(USER, PASSWORD)
            if code:
                print(f"🔑 認証コード取得成功: {code}")
                break
            time.sleep(5)

        if not code:
            print("❌ コードが取得できませんでした。")
            page.screenshot(path="debug_screenshot.png")
            exit(1)

        # 最終送信
        frame.get_by_label("確認コード").fill(code)
        # Googleの「送信」ボタンは jsname で指定するのが確実
        submit_btn = frame.locator('button[jsname="LdrfDc"]')
        submit_btn.click(delay=200)
        print("🎉 予約完了！お疲れ様でした。")
        
        page.wait_for_timeout(5000)

    except Exception as e:
        print(f"🚨 エラー発生: {e}")
        page.screenshot(path="error_screenshot.png")
        raise e
