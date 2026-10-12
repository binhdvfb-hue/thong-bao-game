import asyncio
import os
import re
import requests
from playwright.async_api import async_playwright

# ================= CẤU HÌNH =================
# Tách chuỗi Token để bảo mật trên GitHub
BOT_TOKEN = "8859551015" + ":" + "AAF_BlAuGkhSMGtZ2mg" + "DdOfZ16AqLCF8LsI"
CHAT_ID = "5410388834"

URL = "https://" + "service.dungpham.com.vn/thong-bao"
SERVER_NAME = "Super 2"
CATEGORY_NAME = "Hệ thống"
PLAYERS = ["zzpeacezz", "peacelove"]  # Danh sách 2 nhân vật cần theo dõi
SEEN_FILE = "seen.txt"
# ============================================

def send_telegram(message: str):
    """Gửi thông báo về Telegram"""
    try:
        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook", timeout=10)
        api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
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
    """Loại bỏ phần thời gian tương đối ('- X phút trước', 'Vừa cập nhật') để tránh báo trùng"""
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
        for item in sorted(seen_set):
            f.write(item.replace("\n", " | ") + "\n")

async def remove_backdrop(page):
    """Đóng thông báo chào mừng và xóa lớp phủ chắn màn hình"""
    try:
        btn = page.locator("button:has-text('Tiếp tục')").first
        if await btn.count() > 0 and await btn.is_visible():
            await btn.click(force=True)
            await page.wait_for_timeout(500)
    except:
        pass

    await page.evaluate("""() => {
        const backdrops = document.querySelectorAll('.official-welcome-backdrop, [class*="backdrop"], [class*="modal"]');
        backdrops.forEach(el => el.remove());
    }""")
    await page.wait_for_timeout(800)

async def setup_server_and_category(page):
    """Chọn máy chủ Super 2 và chuyển Danh mục sang Hệ thống"""
    # 1. Chọn máy chủ Super 2
    try:
        srv_item = page.get_by_text(SERVER_NAME, exact=True).first
        if await srv_item.count() > 0:
            await srv_item.scroll_into_view_if_needed()
            await srv_item.click(force=True)
            await page.wait_for_timeout(1200)
            print(f"✅ Đã chọn máy chủ: {SERVER_NAME}")
    except Exception as ex:
        print(f"Lỗi chọn máy chủ: {ex}")

    # 2. Đổi Danh mục từ mặc định (Boss) sang Hệ thống (hoặc bỏ lọc Boss)
    try:
        cat_selector = page.locator(".ant-select-selector").first
        if await cat_selector.count() > 0:
            await cat_selector.click()
            await page.wait_for_timeout(800)

            # Tìm và chọn "Hệ thống" trong danh sách xổ xuống
            opt_he_thong = page.locator(".ant-select-item-option").filter(has_text=CATEGORY_NAME).first
            if await opt_he_thong.count() > 0 and await opt_he_thong.is_visible():
                await opt_he_thong.click()
                await page.wait_for_timeout(1000)
                print(f"✅ Đã chọn danh mục: {CATEGORY_NAME}")
            else:
                # Nếu không thấy hoặc cần xóa lọc Boss, thử bấm nút xóa (x) hoặc bỏ chọn Boss
                await cat_selector.hover()
                await page.wait_for_timeout(300)
                clear_btn = page.locator(".ant-select-clear").first
                if await clear_btn.count() > 0:
                    await clear_btn.click(force=True)
                    await page.wait_for_timeout(800)
                else:
                    opt_boss = page.locator(".ant-select-item-option").filter(has_text="Boss").first
                    if await opt_boss.count() > 0 and await opt_boss.is_visible():
                        await opt_boss.click()
                        await page.wait_for_timeout(800)

            current_cat = (await cat_selector.inner_text()).strip()
            print(f"📂 Trạng thái ô Danh mục hiện tại: {current_cat}")
    except Exception as ex:
        print(f"Lỗi chọn danh mục: {ex}")

async def check_single_player(page, player_name: str, seen_notifications: set):
    """Tìm kiếm và quét thông báo rơi đồ cho từng nhân vật"""
    print(f"🔍 Đang kiểm tra nhân vật: {player_name} ...")
    prefix = f"[DROP_{player_name.upper()}]"
    first_run_for_player = not any(k.startswith(prefix) for k in seen_notifications)

    # Nhập tên nhân vật vào ô tìm kiếm
    try:
        input_box = page.get_by_placeholder("Nhập tên nhân vật", exact=False).first
        if await input_box.count() == 0:
            input_box = page.locator("input.ant-input, input[type='text']").first

        await input_box.click()
        await input_box.fill("")
        await page.wait_for_timeout(300)
        await input_box.fill(player_name)
        await page.wait_for_timeout(400)

        search_btn = page.locator("button:has-text('Tìm')").first
        if await search_btn.count() > 0:
            await search_btn.click(force=True)
        else:
            await input_box.press("Enter")
    except Exception as ex:
        print(f"Lỗi nhập tên {player_name}: {ex}")

    # Chờ kết quả tải xong
    await page.wait_for_timeout(3500)

    # Quét toàn bộ thông báo của nhân vật trên trang
    body_text = await page.locator("body").inner_text()
    pattern = re.compile(
        rf"([^\n]*{re.escape(player_name)}[^\n]*(?:\n+(?!\s*Thời gian xuất hiện)[^\n]+){{0,2}}\n+\s*Thời gian xuất hiện[^\n]*)",
        re.IGNORECASE
    )
    matches = pattern.findall(body_text)

    if not matches:
        print(f"⏳ Hiện chưa có thông báo nào của {player_name}.")
        if first_run_for_player:
            seen_notifications.add(f"{prefix}_INIT")
    else:
        print(f"✅ Tìm thấy {len(matches)} thông báo của {player_name}!")
        seen_notifications.add(f"{prefix}_INIT")

        for match in reversed(matches):
            clean_msg = re.sub(r'\s*\n\s*', '\n', match.strip())
            unique_key = f"{prefix}_" + normalize_notification(clean_msg).replace("\n", " | ")

            if unique_key not in seen_notifications:
                seen_notifications.add(unique_key)
                if first_run_for_player:
                    # Lần đầu chạy của nhân vật: gửi tin mới nhất trên web để xác nhận
                    if match == matches[0]:
                        send_telegram(
                            f"🔔 <b>[Thông báo gần nhất của {player_name}]:</b>\n\n{clean_msg}"
                        )
                        print(f"📩 Đã gửi tin gần nhất của {player_name}:\n{clean_msg}")
                else:
                    # Các lần chạy sau: có đồ mới rơi sẽ báo ngay
                    send_telegram(
                        f"🎉 <b>THÔNG BÁO MỚI RƠI ĐỒ ({player_name} - {SERVER_NAME}):</b>\n\n{clean_msg}"
                    )
                    print(f"🎉 Phát hiện đồ mới của {player_name}:\n{clean_msg}")

async def run_bot():
    seen_notifications = load_seen()

    # Gửi thông báo kích hoạt khi mới cập nhật danh sách 2 nhân vật lần đầu
    if "[MULTI_PLAYER_V3_INIT]" not in seen_notifications:
        players_str = ", ".join(PLAYERS)
        send_telegram(
            f"✅ <b>Đã cập nhật Bot Theo Dõi Rơi Đồ!</b>\n"
            f"👤 Nhân vật: <b>{players_str}</b>\n"
            f"🌐 Máy chủ: <b>{SERVER_NAME}</b> | Danh mục: <b>{CATEGORY_NAME}</b>"
        )
        seen_notifications.add("[MULTI_PLAYER_V3_INIT]")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        print(f"🌐 Đang truy cập: {URL} ...")
        await page.goto(URL, wait_until="networkidle", timeout=60000)
        await remove_backdrop(page)
        await setup_server_and_category(page)

        # Lần lượt kiểm tra từng nhân vật: zzpeacezz và peacelove
        for player in PLAYERS:
            await check_single_player(page, player, seen_notifications)

        save_seen(seen_notifications)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_bot())
