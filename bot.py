import asyncio
import os
import re
import requests
from playwright.async_api import async_playwright

BOT_TOKEN = "8944313202:AAGs_AEQgDrM0POTUh09wPq6vOXHoBQVSXc"
URL = "https://service.dungpham.com.vn/thong-bao"
PLAYER_NAME = "zzpeacezz"
SERVER_NAME = "Super 2"
CATEGORY_NAME = "Hệ thống"
SEEN_FILE = "seen.txt"

def get_chat_id():
    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    try:
        res = requests.get(api_url, timeout=10).json()
        results = res.get("result", [])
        for item in reversed(results):
            msg = item.get("message") or item.get("edited_message")
            if msg and "chat" in msg:
                return str(msg["chat"]["id"])
    except:
        pass
    return None

def send_telegram(chat_id: str, message: str):
    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(api_url, json=payload, timeout=10)
    except:
        pass

def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_seen(seen_set):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        for item in seen_set:
            f.write(item + "\n")

def normalize(text):
    return re.sub(r'\s*-\s*\d+\s*(giây|phút|giờ|ngày|tháng|năm)\s*trước.*', '', text, flags=re.IGNORECASE).strip()

async def main():
    chat_id = get_chat_id()
    if not chat_id:
        print("Chưa tìm thấy Chat ID Telegram (bạn nhớ nhắn tin cho bot trước nhé).")
        return

    seen = load_seen()
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        
        await page.goto(URL, wait_until="networkidle", timeout=60000)

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
                srv_dropdown = page.locator("text=/máy chủ|server/i").locator("..").locator("input, [role='combobox'], select").first
                if await srv_dropdown.count() > 0:
                    await srv_dropdown.click()
                    await page.wait_for_timeout(500)
                    srv_opt = page.locator(f"text=/{SERVER_NAME}/i").first
                    if await srv_opt.count() > 0:
                        await srv_opt.click()
        except:
            pass

        try:
            cat_dropdown = page.locator("text=Danh mục").locator("..").locator("input, [role='combobox'], select").first
            if await cat_dropdown.count() > 0:
                await cat_dropdown.click()
                await page.wait_for_timeout(500)
                cat_opt = page.locator(f"text='{CATEGORY_NAME}'").first
                if await cat_opt.count() > 0:
                    await cat_opt.click()
        except:
            pass

        input_box = page.locator("input[type='text'], input[type='search'], input:not([type])").first
        if await input_box.count() > 0:
            await input_box.fill(PLAYER_NAME)

        search_btn = page.locator("button:has-text('Tìm')").first
        if await search_btn.count() > 0:
            await search_btn.click()
        else:
            await input_box.press("Enter")

        await page.wait_for_timeout(3000)

        body_text = await page.locator("body").inner_text()
        pattern = re.compile(
            rf"({PLAYER_NAME}.*?Thời gian xuất hiện\s*·?\s*\d{{2}}/\d{{2}}/\d{{4}}\s*-\s*\d{{2}}:\d{{2}}:\d{{2}}[^\n]*)",
            re.IGNORECASE | re.DOTALL
        )
        matches = pattern.findall(body_text)

        if matches:
            for match in reversed(matches):
                clean_msg = re.sub(r'\s*\n\s*', '\n', match.strip())
                key = normalize(clean_msg)

                if key not in seen:
                    seen.add(key)
                    send_telegram(chat_id, f"🎉 <b>THÔNG BÁO MỚI RƠI ĐỒ:</b>\n\n{clean_msg}")

        save_seen(seen)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
