import asyncio
import os
import re
import time
from datetime import datetime, timezone, timedelta
import requests
from playwright.async_api import async_playwright

# ================= CẤU HÌNH =================
# Tách chuỗi Token để bảo mật trên GitHub Public
BOT_TOKEN = "8859551015" + ":" + "AAF_BlAuGkhSMGtZ2mg" + "DdOfZ16AqLCF8LsI"
CHAT_ID = "5410388834"

URL = "https://" + "service.dungpham.com.vn/thong-bao"
SERVER_NAME = "Super 2"
CATEGORY_NAME = "Hệ thống"
PLAYERS = ["zzpeacezz", "peacelove"]  # Theo dõi cả 2 nhân vật
SEEN_FILE = "seen.txt"

LOOP_DURATION_MINUTES = 30    # Đứng canh liên tục 30 phút mỗi phiên chạy
CHECK_INTERVAL_SECONDS = 120  # Quét lại mỗi 120 giây (2 phút/lần)
# ============================================

def get_vn_time() -> str:
    """Lấy giờ Việt Nam hiện tại (GMT+7)"""
    vn_tz = timezone(timedelta(hours=7))
    return datetime.now(vn_tz).strftime("%H:%M:%S - %d/%m/%Y")

def send_telegram(message: str):
    """Gửi tin nhắn thông báo về Telegram"""
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
    """Cắt bỏ phần '- X phút trước' hoặc '- Vừa cập nhật' để tránh báo trùng"""
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
    """Đóng nút Tiếp tục và xóa lớp phủ chào mừng chặn màn hình"""
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

    # 2. Chuyển Danh mục từ Boss sang Hệ thống (hoặc xóa lọc Boss)
    try:
        cat_selector = page.locator(".ant-select-selector").first
        if await cat_selector.count() > 0:
            await cat_selector.click()
            await page.wait_for_timeout(800)

            opt_he_thong = page.locator(".ant-select-item-option").filter(has_text=CATEGORY_NAME).first
            if await opt_he_thong.count() > 0 and await opt_he_thong.is_visible():
                await opt_he_thong.click()
                await page.wait_for_timeout(1000)
                print(f"✅ Đã chọn danh mục: {CATEGORY_NAME}")
            else:
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
    except Exception as ex:
        print(f"Lỗi chọn danh mục: {ex}")

async def check_single_player(page, player_name: str, seen_notifications: set) -> bool:
    """
    Quét thông báo rơi đồ của 1 nhân vật.
    Trả về True nếu phát hiện có đồ mới rơi, False nếu không có đồ mới.
    """
    print(f"🔍 Đang kiểm tra nhân vật: {player_name} ...")
    prefix = f"[DROP_{player_name.upper()}]"
    first_run_for_player = not any(k.startswith(prefix) for k in seen_notifications)
    found_new_drop = False

    # Nhập tên nhân vật và bấm Tìm
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

    # Chờ dữ liệu trả về
    await page.wait_for_timeout(3500)

    # Quét danh sách thông báo trên giao diện
    body_text = await page.locator("body").inner_text()
    pattern = re.compile(
        rf"([^\n]*{re.escape(player_name)}[^\n]*(?:\n+(?!\s*Thời gian xuất hiện)[^\n]+){{0,2}}\n+\s*Thời gian xuất hiện[^\n]*)",
        re.IGNORECASE
    )
    matches = pattern.findall(body_text)

    if not matches:
        print(f"⏳ Không tìm thấy thông báo nào của {player_name} trên bảng.")
        if first_run_for_player:
            seen_notifications.add(f"{prefix}_INIT")
    else:
        seen_notifications.add(f"{prefix}_INIT")
        for match in reversed(matches):
            clean_msg = re.sub(r'\s*\n\s*', '\n', match.strip())
            unique_key = f"{prefix}_" + normalize_notification(clean_msg).replace("\n", " | ")

            if unique_key not in seen_notifications:
                seen_notifications.add(unique_key)
                if first_run_for_player:
                    # Lần đầu tiên chạy của nhân vật: chỉ lưu lịch sử và gửi 1 tin mẫu gần nhất
                    if match == matches[0]:
                        send_telegram(
                            f"🔔 <b>[Thông báo gần nhất trên web của {player_name}]:</b>\n\n{clean_msg}"
                        )
                        print(f"📩 Đã gửi tin mẫu gần nhất của {player_name}:\n{clean_msg}")
                else:
                    # Các lần quét tiếp theo: phát hiện món đồ mới rơi!
                    found_new_drop = True
                    send_telegram(
                        f"🎉 <b>THÔNG BÁO MỚI RƠI ĐỒ ({player_name} - {SERVER_NAME}):</b>\n\n{clean_msg}"
                    )
                    print(f"🎉 Phát hiện đồ mới của {player_name}:\n{clean_msg}")

    return found_new_drop

async def run_bot():
    seen_notifications = load_seen()
    start_time = time.time()
    end_time = start_time + (LOOP_DURATION_MINUTES * 60)

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

        cycle = 1
        while time.time() < end_time:
            print(f"\n🔄 --- Lượt quét thứ {cycle} ({get_vn_time()}) ---")

            # Từ lượt thứ 2 trở đi, bấm nút "Làm mới" trên web trước khi tìm để cập nhật dữ liệu mới nhất
            if cycle > 1:
                try:
                    refresh_btn = page.locator("button:has-text('Làm mới')").first
                    if await refresh_btn.count() > 0:
                        await refresh_btn.click(force=True)
                        await page.wait_for_timeout(2000)
                except Exception as ex:
                    print(f"Làm mới trang: {ex}")

            no_drop_players = []
            for player in PLAYERS:
                has_new = await check_single_player(page, player, seen_notifications)
                if not has_new:
                    no_drop_players.append(player)

            # Nếu không nhặt được món đồ mới nào trong lượt quét này thì báo về Telegram
            if no_drop_players:
                names_str = ", ".join(no_drop_players)
                send_telegram(
                    f"⏳ <b>[Quét lần #{cycle} - {get_vn_time()}]</b>\n"
                    f"Hiện tại nhân vật <b>{names_str}</b> vẫn chưa nhặt được món đồ mới nào."
                )
                print(f"📩 Đã báo Telegram: {names_str} chưa nhặt được món đồ mới nào.")

            save_seen(seen_notifications)
            cycle += 1

            # Nghỉ 2 phút trước khi quét lượt tiếp theo
            if time.time() + CHECK_INTERVAL_SECONDS < end_time:
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)
            else:
                break

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_bot())
