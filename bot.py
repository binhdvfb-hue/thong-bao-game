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

URL = "https://service.dungpham.com.vn/thong-bao"
SERVER_NAME = "Super 2"
CATEGORY_NAME = "Hệ thống"
PLAYERS = ["zzpeacezz", "peacelove"]
SEEN_FILE = "seen.txt"

LOOP_DURATION_MINUTES = 30    # Chạy liên tục 30 phút mỗi ca
CHECK_INTERVAL_SECONDS = 600  # 600 giây = 10 phút quét và thông báo 1 lần
# ============================================

def get_vn_time() -> str:
    vn_tz = timezone(timedelta(hours=7))
    return datetime.now(vn_tz).strftime("%H:%M:%S - %d/%m/%Y")

def send_telegram(message: str):
    """Gửi tin nhắn văn bản về Telegram"""
    try:
        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook", timeout=10)
        api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
        requests.post(api_url, json=payload, timeout=10)
    except Exception as e:
        print(f"[Lỗi gửi Telegram]: {e}")

def send_telegram_photo(photo_path: str, caption: str):
    """Gửi ảnh chụp màn hình kèm nội dung thông báo rơi đồ về Telegram"""
    try:
        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook", timeout=10)
        api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
        with open(photo_path, "rb") as img:
            r = requests.post(
                api_url,
                data={
                    "chat_id": CHAT_ID,
                    "caption": caption,
                    "parse_mode": "HTML"
                },
                files={"photo": img},
                timeout=25
            )
        if r.status_code != 200:
            print(f"[Lỗi gửi ảnh Telegram, chuyển sang gửi chữ]: {r.text}")
            send_telegram(caption)
    except Exception as e:
        print(f"[Lỗi kết nối gửi ảnh Telegram]: {e}")
        send_telegram(caption)

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
        for item in sorted(seen_set):
            f.write(item.replace("\n", " | ") + "\n")

async def close_welcome_popup(page):
    """Đóng bảng chào mừng an toàn"""
    try:
        for text in ["Tiếp tục", "Đóng", "Đã hiểu", "OK"]:
            btn = page.get_by_role("button", name=text, exact=False).first
            if await btn.count() > 0 and await btn.is_visible():
                await btn.click(force=True)
                await page.wait_for_timeout(800)
    except:
        pass

    await page.evaluate("""() => {
        document.querySelectorAll('.official-welcome-backdrop').forEach(el => {
            el.style.display = 'none';
            el.style.pointerEvents = 'none';
        });
    }""")
    await page.wait_for_timeout(500)

async def setup_filters(page):
    """Chọn máy chủ Super 2 và chuyển Danh mục sang Hệ thống / Chọn danh mục"""
    await close_welcome_popup(page)

    # 1. Chọn máy chủ Super 2
    try:
        srv_item = page.get_by_text(SERVER_NAME, exact=True).first
        if await srv_item.count() > 0:
            await srv_item.scroll_into_view_if_needed()
            await srv_item.click(force=True)
            await page.wait_for_timeout(1500)
            print(f"✅ Đã chọn máy chủ: {SERVER_NAME}")
    except Exception as ex:
        print(f"Lỗi chọn máy chủ: {ex}")

    # 2. Chỉnh ô Danh mục (bỏ lọc Boss hoặc chọn Hệ thống)
    try:
        if await page.locator("select").count() > 0:
            sel = page.locator("select").first
            try:
                await sel.select_option(label=CATEGORY_NAME)
            except:
                await sel.select_option(index=0)
            await page.wait_for_timeout(1000)
        else:
            cat_label = page.get_by_text("Danh mục", exact=True).first
            if await cat_label.count() > 0:
                box = await cat_label.bounding_box()
                if box:
                    await page.mouse.click(box["x"] + 80, box["y"] + box["height"] + 22)
                    await page.wait_for_timeout(800)

                    clicked_opt = False
                    for opt_name in [CATEGORY_NAME, "Chọn danh mục", "Tất cả"]:
                        opt = page.get_by_text(opt_name, exact=True).last
                        if await opt.count() > 0 and await opt.is_visible():
                            await opt.click(force=True)
                            clicked_opt = True
                            await page.wait_for_timeout(1000)
                            break

                    if not clicked_opt:
                        boss_opts = page.get_by_text("Boss", exact=True)
                        if await boss_opts.count() > 1:
                            await boss_opts.last.click(force=True)
                            await page.wait_for_timeout(1000)
    except Exception as ex:
        print(f"Lỗi chỉnh Danh mục: {ex}")

async def check_single_player(page, player_name: str, seen_notifications: set):
    prefix = f"[DROP_V8_{player_name.upper()}]"
    first_run_for_player = not any(k.startswith(prefix) for k in seen_notifications)
    found_new_drop = False
    latest_info = "Chưa có dữ liệu trên bảng"

    # Nhập tên nhân vật bằng thao tác bàn phím thật
    try:
        input_box = page.locator("input").first
        await input_box.scroll_into_view_if_needed()
        await input_box.click(force=True)
        await page.wait_for_timeout(200)

        await page.keyboard.press("Control+A")
        await page.keyboard.press("Backspace")
        await input_box.fill("")
        await page.wait_for_timeout(200)

        await input_box.type(player_name, delay=60)
        await page.wait_for_timeout(500)

        search_btn = page.get_by_role("button", name="Tìm", exact=True).first
        if await search_btn.count() > 0:
            await search_btn.click(force=True)
        else:
            await page.keyboard.press("Enter")
    except Exception as ex:
        print(f"Lỗi nhập tên {player_name}: {ex}")

    await page.wait_for_timeout(4000)

    # Quét nội dung thông báo trên trang
    body_text = await page.locator("body").inner_text()
    lines = [line.strip() for line in body_text.splitlines() if line.strip()]

    matches = []
    for i, line in enumerate(lines):
        if player_name.lower() in line.lower() and len(line) > len(player_name) + 6:
            for j in range(1, 3):
                if i + j < len(lines):
                    next_line = lines[i + j]
                    if "thời gian" in next_line.lower() or re.search(r"\d{2}/\d{2}/\d{4}", next_line):
                        matches.append(f"{line}\n{next_line}")
                        break

    if matches:
        seen_notifications.add(f"{prefix}_INIT")
        newest_msg = matches[0]
        time_match = re.search(r"Thời gian xuất hiện\s*·?\s*([^\n]+)", newest_msg, re.IGNORECASE)
        latest_info = time_match.group(1).strip() if time_match else newest_msg.replace("\n", " - ")

        shot_path = f"drop_{player_name}.png"

        for match in reversed(matches):
            unique_key = f"{prefix}_" + normalize_notification(match).replace("\n", " | ")
            if unique_key not in seen_notifications:
                seen_notifications.add(unique_key)
                if first_run_for_player:
                    # Lần đầu kết nối: chụp màn hình kèm thông báo gần nhất trên web
                    if match == matches[0]:
                        await page.screenshot(path=shot_path, full_page=False)
                        send_telegram_photo(
                            shot_path,
                            f"🔔 <b>[Thông báo gần nhất của {player_name}]:</b>\n\n{match}"
                        )
                else:
                    # Khi có đồ mới rơi: chụp ngay màn hình làm bằng chứng và gửi kèm tin nhắn!
                    found_new_drop = True
                    await page.screenshot(path=shot_path, full_page=False)
                    send_telegram_photo(
                        shot_path,
                        f"🎉 <b>THÔNG BÁO MỚI RƠI ĐỒ ({player_name} - {SERVER_NAME}):</b>\n\n{match}"
                    )

    return found_new_drop, latest_info

async def run_bot():
    seen_notifications = load_seen()
    # Số lượt quét trong 30 phút (quét ngay lúc bật ở phút 0, sau đó quét ở phút 10, 20, 30 -> tổng 4 lượt)
    total_cycles = (LOOP_DURATION_MINUTES * 60) // CHECK_INTERVAL_SECONDS + 1

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1366, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)
        await setup_filters(page)

        for cycle in range(1, total_cycles + 1):
            print(f"\n🔄 --- Lượt quét thứ {cycle}/{total_cycles} ({get_vn_time()}) ---")

            if cycle > 1:
                try:
                    refresh_btn = page.locator("button:has-text('Làm mới')").first
                    if await refresh_btn.count() > 0:
                        await refresh_btn.click(force=True)
                        await page.wait_for_timeout(2500)
                    await setup_filters(page)
                except Exception as ex:
                    print(f"Refresh error: {ex}")

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
                    f"Chưa có món đồ mới nào cho <b>{names_str}</b>.\n\n"
                    f"📌 <i>Mốc gần nhất trên web:</i>\n{summary_text}"
                )

            save_seen(seen_notifications)

            # Nghỉ đúng 10 phút (600 giây) trước khi sang lượt quét tiếp theo
            if cycle < total_cycles:
                print(f"⏱️ Đang đợi {CHECK_INTERVAL_SECONDS // 60} phút cho lượt quét tiếp theo...")
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_bot())
