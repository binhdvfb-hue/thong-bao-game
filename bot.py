import asyncio
import os
import re
import time
from datetime import datetime, timezone, timedelta
import requests
from playwright.async_api import async_playwright

# ================= CẤU HÌNH =================
BOT_TOKEN = "8859551015" + ":" + "AAF_BlAuGkhSMGtZ2mg" + "DdOfZ16AqLCF8LsI"
CHAT_ID = "5410388834"

URL = "https://" + "service.dungpham.com.vn/thong-bao"
SERVER_NAME = "Super 2"
PLAYERS = ["zzpeacezz", "peacelove"]
SEEN_FILE = "seen.txt"

LOOP_DURATION_MINUTES = 30    # Đứng canh liên tục 30 phút mỗi phiên
CHECK_INTERVAL_SECONDS = 120  # Quét lại mỗi 120 giây (2 phút/lần)
# ============================================

def get_vn_time() -> str:
    vn_tz = timezone(timedelta(hours=7))
    return datetime.now(vn_tz).strftime("%H:%M:%S - %d/%m/%Y")

def send_telegram(message: str):
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
    """Cắt bỏ phần '- X phút/giờ trước' hoặc '- Vừa cập nhật' để làm khóa chống trùng"""
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
    """Đóng thông báo chào mừng nếu có"""
    try:
        btn = page.locator("button:has-text('Tiếp tục')").first
        if await btn.count() > 0 and await btn.is_visible():
            await btn.click(force=True)
            await page.wait_for_timeout(500)
    except:
        pass

    await page.evaluate("""() => {
        const backdrops = document.querySelectorAll('.official-welcome-backdrop');
        backdrops.forEach(el => el.remove());
    }""")
    await page.wait_for_timeout(500)

async def select_server_and_clear_boss_filter(page):
    """Chọn máy chủ Super 2 và đưa Danh mục về 'Chọn danh mục' / 'Hệ thống' (thoát lọc Boss)"""
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

    # 2. Thoát bộ lọc "Boss" ở ô Danh mục
    try:
        # Cách A: Nếu trang dùng thẻ <select> chuẩn của HTML
        select_count = await page.locator("select").count()
        if select_count > 0:
            await page.evaluate("""() => {
                const sel = document.querySelector('select');
                if (!sel) return;
                for (let i = 0; i < sel.options.length; i++) {
                    const txt = sel.options[i].text.toLowerCase();
                    if (txt.includes('chọn danh mục') || txt.includes('hệ thống') || sel.options[i].value === '') {
                        sel.selectedIndex = i;
                        sel.dispatchEvent(new Event('change', { bubbles: true }));
                        break;
                    }
                }
            }""")
            await page.wait_for_timeout(1000)

        # Cách B: Nếu vẫn còn hiện ô "Tên Boss" (tức là Danh mục vẫn đang kẹt ở Boss)
        if await page.get_by_text("Tên Boss", exact=False).count() > 0:
            cat_label = page.get_by_text("Danh mục", exact=True).first
            if await cat_label.count() > 0:
                box = await cat_label.bounding_box()
                if box:
                    # Bấm thẳng vào hộp chọn nằm ngay bên dưới chữ "Danh mục"
                    await page.mouse.click(box["x"] + 60, box["y"] + box["height"] + 22)
                    await page.wait_for_timeout(800)

                    # Ưu tiên chọn "Chọn danh mục" hoặc "Hệ thống" hoặc bấm lại "Boss" để bỏ chọn
                    for opt_text in ["Chọn danh mục", "Hệ thống", "Tất cả"]:
                        opt = page.get_by_text(opt_text, exact=True).last
                        if await opt.count() > 0 and await opt.is_visible():
                            await opt.click(force=True)
                            await page.wait_for_timeout(1000)
                            break

                    # Nếu vẫn còn "Tên Boss", bấm vào mục "Boss" trong danh sách xổ xuống để tắt lọc Boss
                    if await page.get_by_text("Tên Boss", exact=False).count() > 0:
                        boss_opts = page.get_by_text("Boss", exact=True)
                        if await boss_opts.count() > 1:
                            await boss_opts.last.click(force=True)
                            await page.wait_for_timeout(1000)
    except Exception as ex:
        print(f"Lỗi chỉnh Danh mục: {ex}")

async def check_single_player(page, player_name: str, seen_notifications: set):
    """
    Trả về (found_new_drop: bool, latest_time_str: str)
    """
    prefix = f"[DROP_V5_{player_name.upper()}]"
    first_run_for_player = not any(k.startswith(prefix) for k in seen_notifications)
    found_new_drop = False
    latest_info = "Chưa có dữ liệu trên bảng"

    # Đảm bảo không bị kẹt ở mục Boss trước khi tìm
    if await page.get_by_text("Tên Boss", exact=False).count() > 0:
        await select_server_and_clear_boss_filter(page)

    # Nhập tên nhân vật vào ô tìm kiếm và bấm Tìm
    try:
        input_box = page.get_by_placeholder("Nhập tên nhân vật", exact=False).first
        if await input_box.count() == 0:
            input_box = page.locator("input[type='search'], input[type='text'], input").first

        await input_box.click()
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Backspace")
        await input_box.fill(player_name)
        await page.wait_for_timeout(400)

        # Bấm cả phím Enter và nút Tìm
        await input_box.press("Enter")
        search_btn = page.get_by_role("button", name="Tìm", exact=True).first
        if await search_btn.count() > 0:
            await search_btn.click(force=True)
    except Exception as ex:
        print(f"Lỗi nhập tên {player_name}: {ex}")

    await page.wait_for_timeout(3500)

    # Quét danh sách thông báo của nhân vật
    body_text = await page.locator("body").inner_text()
    pattern = re.compile(
        rf"([^\n]*{re.escape(player_name)}[^\n]*[\s\S]{{0,200}}?Thời gian xuất hiện[^\n]*)",
        re.IGNORECASE
    )
    matches = pattern.findall(body_text)

    if not matches:
        print(f"⏳ Không tìm thấy dòng thông báo nào của {player_name}.")
    else:
        print(f"✅ Đọc được {len(matches)} thông báo của {player_name} trên web!")
        seen_notifications.add(f"{prefix}_INIT")

        # Lấy thời gian của thông báo mới nhất trên đầu bảng để báo cáo
        newest_raw = re.sub(r'\s*\n\s*', '\n', matches[0].strip())
        time_match = re.search(r"Thời gian xuất hiện\s*·?\s*([^\n]+)", newest_raw)
        if time_match:
            latest_info = time_match.group(1).strip()
        else:
            latest_info = newest_raw

        for match in reversed(matches):
            clean_msg = re.sub(r'\s*\n\s*', '\n', match.strip())
            unique_key = f"{prefix}_" + normalize_notification(clean_msg).replace("\n", " | ")

            if unique_key not in seen_notifications:
                seen_notifications.add(unique_key)
                if first_run_for_player:
                    # Lần đầu chạy bản V5: gửi ngay thông báo mới nhất trên web (13:04:06) để xác nhận!
                    if match == matches[0]:
                        send_telegram(
                            f"🔔 <b>[Đã đọc thành công thông báo gần nhất của {player_name}]:</b>\n\n{clean_msg}"
                        )
                else:
                    found_new_drop = True
                    send_telegram(
                        f"🎉 <b>THÔNG BÁO MỚI RƠI ĐỒ ({player_name} - {SERVER_NAME}):</b>\n\n{clean_msg}"
                    )

    return found_new_drop, latest_info

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
        await select_server_and_clear_boss_filter(page)

        cycle = 1
        while time.time() < end_time:
            print(f"\n🔄 --- Lượt quét thứ {cycle} ({get_vn_time()}) ---")

            if cycle > 1:
                try:
                    refresh_btn = page.locator("button:has-text('Làm mới')").first
                    if await refresh_btn.count() > 0:
                        await refresh_btn.click(force=True)
                        await page.wait_for_timeout(2000)
                    await select_server_and_clear_boss_filter(page)
                except Exception as ex:
                    print(f"Làm mới trang: {ex}")

            no_drop_players = []
            latest_summary = []

            for player in PLAYERS:
                has_new, latest_info = await check_single_player(page, player, seen_notifications)
                latest_summary.append(f"• <b>{player}</b>: {latest_info}")
                if not has_new:
                    no_drop_players.append(player)

            if no_drop_players:
                names_str = ", ".join(no_drop_players)
                summary_text = "\n".join(latest_summary)
                send_telegram(
                    f"⏳ <b>[Quét lần #{cycle} - {get_vn_time()}]</b>\n"
                    f"Chưa có thêm món đồ mới nào rơi cho <b>{names_str}</b>.\n\n"
                    f"📌 <i>Mốc gần nhất trên web đang hiển thị:</i>\n{summary_text}"
                )

            save_seen(seen_notifications)
            cycle += 1

            if time.time() + CHECK_INTERVAL_SECONDS < end_time:
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)
            else:
                break

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_bot())
