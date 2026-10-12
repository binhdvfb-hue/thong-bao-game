import asyncio
import os
import re
import requests
from playwright.async_api import async_playwright

# ================= CẤU HÌNH CHUNG =================
CHAT_ID = "5410388834"
URL = "https://" + "service.dungpham.com.vn/thong-bao"
SEEN_FILE = "seen.txt"

# 1. Cấu hình Bot 1: Canh đồ nhân vật zzpeacezz (Super 2)
TOKEN_PLAYER = "8859551015" + ":" + "AAF_BlAuGkhSMGtZ2mg" + "DdOfZ16AqLCF8LsI"
PLAYER_NAME = "zzpeacezz"
PLAYER_SERVER = "Super 2"
PLAYER_CATEGORY = "Hệ thống"

# 2. Cấu hình Bot 2: Canh Boss (2 sao)
TOKEN_BOSS = "8958519390" + ":" + "AAGhRyJarXhpV4kIhSM" + "HUzp1-plpPqtCFjU"
BOSS_SERVER = "2 sao"
BOSS_CATEGORY = "Boss"
# ==================================================

def send_telegram(token: str, message: str):
    """Gửi thông báo về đúng Bot Telegram tương ứng"""
    try:
        requests.get(f"https://api.telegram.org/bot{token}/deleteWebhook", timeout=10)
        api_url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        r = requests.post(api_url, json=payload, timeout=10)
        if r.status_code != 200:
            print(f"[Lỗi gửi Telegram]: {r.text}")
    except Exception as e:
        print(f"[Lỗi kết nối Telegram]: {e}")

def normalize_notification(raw_text: str) -> str:
    """Loại bỏ chữ '- X phút trước' hoặc '- Vừa cập nhật' để không báo trùng"""
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

async def remove_backdrop(page):
    """Xóa lớp phủ chào mừng chặn màn hình nếu có"""
    await page.evaluate("""() => {
        const backdrops = document.querySelectorAll('.official-welcome-backdrop, [class*="backdrop"], [class*="modal"]');
        backdrops.forEach(el => el.remove());
    }""")
    await page.wait_for_timeout(800)

async def check_player(page, seen_notifications):
    """Nhiệm vụ 1: Quét thông báo nhân vật zzpeacezz tại Super 2"""
    print(f"🔍 [1/2] Đang kiểm tra nhân vật {PLAYER_NAME} ({PLAYER_SERVER})...")
    first_run_player = not any(k.startswith("[PLAYER]") for k in seen_notifications)

    if first_run_player:
        send_telegram(
            TOKEN_PLAYER,
            f"✅ <b>Bot Theo Dõi Nhân Vật đã kết nối!</b>\n"
            f"👤 Nhân vật: <b>{PLAYER_NAME}</b>\n"
            f"🌐 Máy chủ: <b>{PLAYER_SERVER}</b> | Danh mục: <b>{PLAYER_CATEGORY}</b>"
        )
        seen_notifications.add("[PLAYER]_INIT")

    await page.goto(URL, wait_until="networkidle", timeout=60000)
    await remove_backdrop(page)

    # Chọn máy chủ Super 2
    try:
        srv_item = page.get_by_text(PLAYER_SERVER, exact=True).first
        if await srv_item.count() > 0:
            await srv_item.scroll_into_view_if_needed()
            await srv_item.click(force=True)
            await page.wait_for_timeout(1000)
    except Exception as ex:
        print(f"Lọc máy chủ Player: {ex}")

    # Chọn danh mục Hệ thống
    try:
        cat_dropdown = page.locator("text=Danh mục").locator("..").locator("input, [role='combobox'], .ant-select, select, div[class*='select']").first
        if await cat_dropdown.count() > 0:
            await cat_dropdown.click(force=True)
            await page.wait_for_timeout(500)
            cat_opt = page.locator(f"text='{PLAYER_CATEGORY}'").first
            if await cat_opt.count() > 0:
                await cat_opt.click(force=True)
                await page.wait_for_timeout(1000)
    except Exception as ex:
        print(f"Lọc danh mục Player: {ex}")

    # Nhập tên zzpeacezz và bấm Tìm
    input_box = page.locator("input[type='text'], input[type='search'], input:not([type])").first
    if await input_box.count() > 0:
        await input_box.fill(PLAYER_NAME)

    search_btn = page.locator("button:has-text('Tìm')").first
    if await search_btn.count() > 0:
        await search_btn.click(force=True)
    elif await input_box.count() > 0:
        await input_box.press("Enter")

    await page.wait_for_timeout(3000)

    body_text = await page.locator("body").inner_text()
    pattern = re.compile(
        rf"({PLAYER_NAME}.*?Thời gian xuất hiện\s*·?\s*\d{{2}}/\d{{2}}/\d{{4}}\s*-\s*\d{{2}}:\d{{2}}:\d{{2}}[^\n]*)",
        re.IGNORECASE | re.DOTALL
    )
    matches = pattern.findall(body_text)

    if not matches:
        print(f"⏳ Chưa có thông báo mới cho {PLAYER_NAME}.")
    else:
        for match in reversed(matches):
            clean_msg = re.sub(r'\s*\n\s*', '\n', match.strip())
            unique_key = "[PLAYER]_" + normalize_notification(clean_msg).replace("\n", " | ")

            if unique_key not in seen_notifications:
                seen_notifications.add(unique_key)
                if first_run_player:
                    if match == matches[0]:
                        send_telegram(TOKEN_PLAYER, f"🔔 <b>[Thông báo gần nhất hiện tại]:</b>\n\n{clean_msg}")
                else:
                    send_telegram(TOKEN_PLAYER, f"🎉 <b>THÔNG BÁO MỚI RƠI ĐỒ:</b>\n\n{clean_msg}")

async def check_boss(page, seen_notifications):
    """Nhiệm vụ 2: Quét Boss tại máy chủ 2 sao"""
    print(f"🔍 [2/2] Đang kiểm tra Boss tại máy chủ {BOSS_SERVER}...")
    first_run_boss = not any(k.startswith("[BOSS]") for k in seen_notifications)

    if first_run_boss:
        send_telegram(
            TOKEN_BOSS,
            f"✅ <b>Bot Săn Boss đã kết nối thành công!</b>\n"
            f"🌐 Máy chủ: <b>{BOSS_SERVER}</b>\n"
            f"📂 Danh mục: <b>{BOSS_CATEGORY}</b>"
        )
        seen_notifications.add("[BOSS]_INIT")

    # Tải lại trang để đặt lại bộ lọc mặc định (Danh mục mặc định là Boss)
    await page.goto(URL, wait_until="networkidle", timeout=60000)
    await remove_backdrop(page)

    # Chọn chính xác máy chủ "2 sao"
    try:
        srv_item = page.get_by_text(BOSS_SERVER, exact=True).first
        if await srv_item.count() > 0:
            await srv_item.scroll_into_view_if_needed()
            await srv_item.click(force=True)
            await page.wait_for_timeout(2500)
    except Exception as ex:
        print(f"Lỗi chọn máy chủ Boss: {ex}")

    body_text = await page.locator("body").inner_text()
    pattern = re.compile(
        r"(Boss:\s*[^\n]+\s*\n+\s*Map:\s*[^\n]+\s*\n+\s*Thời gian xuất hiện\s*·?\s*\d{2}/\d{2}/\d{4}\s*-\s*\d{2}:\d{2}:\d{2}[^\n]*)",
        re.IGNORECASE
    )
    matches = pattern.findall(body_text)

    if not matches:
        print(f"⏳ Chưa có thông báo Boss tại {BOSS_SERVER}.")
    else:
        new_bosses = []
        for match in reversed(matches):
            clean_msg = re.sub(r'\s*\n\s*', '\n', match.strip())
            unique_key = "[BOSS]_" + normalize_notification(clean_msg).replace("\n", " | ")

            if unique_key not in seen_notifications:
                seen_notifications.add(unique_key)
                new_bosses.append(clean_msg)

        if new_bosses:
            if first_run_boss:
                latest_preview = "\n\n".join(new_bosses[-3:])
                send_telegram(
                    TOKEN_BOSS,
                    f"🔔 <b>[Danh sách Boss gần nhất - {BOSS_SERVER}]:</b>\n\n{latest_preview}"
                )
            else:
                for boss_msg in new_bosses:
                    send_telegram(
                        TOKEN_BOSS,
                        f"🔥 <b>BOSS XUẤT HIỆN ({BOSS_SERVER}):</b>\n\n{boss_msg}"
                    )

async def run_all():
    seen_notifications = load_seen()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        # Chạy lần lượt cả 2 nhiệm vụ
        await check_player(page, seen_notifications)
        await check_boss(page, seen_notifications)

        save_seen(seen_notifications)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_all())
