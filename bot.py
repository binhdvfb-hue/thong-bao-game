import asyncio
import os
import re
import requests
from playwright.async_api import async_playwright

# ================= CẤU HÌNH =================
BOT_TOKEN = "8859551015:AAF_BlAuGkhSMGtZ2mgDdOfZ16AqLCF8LsI"
CHAT_ID = "5410388834"  # Đã điền sẵn ID Telegram của bạn

URL = "https://" + "service.dungpham.com.vn/thong-bao"
PLAYER_NAME = "zzpeacezz"
SERVER_NAME = "Super 2"
CATEGORY_NAME = "Hệ thống"
SEEN_FILE = "seen.txt"
# ============================================

def send_telegram(message: str):
    """Gửi thông báo trực tiếp về Telegram qua Chat ID cố định"""
    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        requests.post(api_url, json=payload, timeout=10)
    except Exception as e:
        print(f"[Lỗi gửi Telegram]: {e}")

def normalize_notification(raw_text: str) -> str:
    cleaned = re.sub(
        r'\s*-\s*(\d+\s*(giây|phút|giờ|ngày|tháng|năm)\s*trước|Vừa cập nhật).*',
        '',
        raw_text,
        flags=re.IGNORECASE
    )
    return cleaned.strip()

def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_seen(seen_set):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        for item in seen_set:
            f.write(item.replace("\n", " | ") + "\n")

async def run_bot():
    print("🔄 Đang khởi động bot quét dữ liệu...")
    
    first_run = not os.path.exists(SEEN_FILE)
    seen_notifications = load_seen()

    if first_run:
        send_telegram(
            f"✅ <b>Bot GitHub đã kết nối thành công!</b>\n"
            f"Đang theo dõi nhân vật <b>{PLAYER_NAME}</b>\n"
            f"🌐 Máy chủ: <b>{SERVER_NAME}</b> | Danh mục: <b>{CATEGORY_NAME}</b>"
        )

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        print(f"🌐 Đang truy cập: {URL} ...")
        await page.goto(URL, wait_until="networkidle", timeout=60000)

        # Đóng bảng thông báo chào mừng ("Tiếp tục") nếu có
        try:
            btn_continue = page.locator("button:has-text('Tiếp tục'), text='Tiếp tục'")
            if await btn_continue.count() > 0 and await btn_continue.first.is_visible():
                await btn_continue.first.click()
                await page.wait_for_timeout(500)
        except:
            pass

        # 1. Chọn Máy chủ "Super 2"
        try:
            selects = page.locator("select")
            if await selects.count() > 0:
                for i in range(await selects.count()):
                    opts = await selects.nth(i).locator("option").all_inner_texts()
                    for opt in opts:
                        if SERVER_NAME.lower() in opt.lower():
                            await selects.nth(i).select_option(label=opt)
                            break
            else:
                srv_dropdown = page.locator("text=/máy chủ|server/i").locator("..").locator("input, [role='combobox'], .ant-select, select, div[class*='select']").first
                if await srv_dropdown.count() > 0:
                    await srv_dropdown.click()
                    await page.wait_for_timeout(500)
                    srv_opt = page.locator(f"text=/{SERVER_NAME}/i").first
                    if await srv_opt.count() > 0:
                        await srv_opt.click()
        except Exception as ex:
            print(f"Lọc máy chủ: {ex}")

        # 2. Chọn Danh mục "Hệ thống"
        try:
            cat_dropdown = page.locator("text=Danh mục").locator("..").locator("input, [role='combobox'], .ant-select, select, div[class*='select']").first
            if await cat_dropdown.count() > 0:
                await cat_dropdown.click()
                await page.wait_for_timeout(500)
                cat_opt = page.locator(f"text='{CATEGORY_NAME}'").first
                if await cat_opt.count() > 0:
                    await cat_opt.click()
        except Exception as ex:
            print(f"Lọc danh mục: {ex}")

        # 3. Nhập tên nhân vật
        input_box = page.locator("input[type='text'], input[type='search'], input:not([type])").first
        if await input_box.count() > 0:
            await input_box.fill(PLAYER_NAME)

        # 4. Bấm nút "Tìm"
        search_btn = page.locator("button:has-text('Tìm')").first
        if await search_btn.count() > 0:
            await search_btn.click()
        else:
            await input_box.press("Enter")

        # Chờ 3 giây cho kết quả trả về
        await page.wait_for_timeout(3000)

        # 5. Quét thông báo
        body_text = await page.locator("body").inner_text()
        pattern = re.compile(
            rf"({PLAYER_NAME}.*?Thời gian xuất hiện\s*·?\s*\d{{2}}/\d{{2}}/\d{{4}}\s*-\s*\d{{2}}:\d{{2}}:\d{{2}}[^\n]*)",
            re.IGNORECASE | re.DOTALL
        )
        matches = pattern.findall(body_text)

        if not matches:
            print("⏳ Chưa có thông báo nào khớp trên trang.")
        else:
            for match in reversed(matches):
                clean_msg = re.sub(r'\s*\n\s*', '\n', match.strip())
                unique_key = normalize_notification(clean_msg).replace("\n", " | ")

                if unique_key not in seen_notifications:
                    seen_notifications.add(unique_key)
                    if first_run:
                        if match == matches[0]:
                            send_telegram(f"🔔 <b>[Thông báo gần nhất hiện tại]:</b>\n\n{clean_msg}")
                            print(f"📩 Đã gửi tin gần nhất về Telegram:\n{clean_msg}")
                    else:
                        send_telegram(f"🎉 <b>THÔNG BÁO MỚI RƠI ĐỒ:</b>\n\n{clean_msg}")
                        print(f"🎉 Phát hiện mới:\n{clean_msg}")

        save_seen(seen_notifications)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_bot())
