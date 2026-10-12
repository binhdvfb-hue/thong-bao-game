import asyncio
import os
import re
import time
from datetime import datetime, timezone, timedelta
import requests
from playwright.async_api import async_playwright

BOT_TOKEN = "8859551015" + ":" + "AAF_BlAuGkhSMGtZ2mg" + "DdOfZ16AqLCF8LsI"
CHAT_ID = "5410388834"

URL = "https://service.dungpham.com.vn/thong-bao"
SERVER_NAME = "Super 2"
PLAYERS = ["zzpeacezz", "peacelove"]
SEEN_FILE = "seen.txt"

LOOP_DURATION_MINUTES = 30
CHECK_INTERVAL_SECONDS = 120

def get_vn_time() -> str:
    vn_tz = timezone(timedelta(hours=7))
    return datetime.now(vn_tz).strftime("%H:%M:%S - %d/%m/%Y")

def send_telegram(message: str):
    try:
        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook", timeout=10)
        api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}
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
        for item in sorted(seen_set):
            f.write(item.replace("\n", " | ") + "\n")

async def clean_page_and_select_server(page):
    # Đóng modal/backdrop
    await page.evaluate("""() => {
        document.querySelectorAll('.official-welcome-backdrop, [class*="backdrop"], [class*="modal"]').forEach(e => e.remove());
        const btns = Array.from(document.querySelectorAll('button'));
        const closeBtn = btns.find(b => b.textContent.includes('Tiếp tục') || b.textContent.includes('Đóng'));
        if (closeBtn) closeBtn.click();
    }""")
    await page.wait_for_timeout(500)

    # Chọn máy chủ Super 2
    try:
        srv_item = page.get_by_text(SERVER_NAME, exact=True).first
        if await srv_item.count() > 0:
            await srv_item.scroll_into_view_if_needed()
            await srv_item.click(force=True)
            await page.wait_for_timeout(1000)
    except Exception as ex:
        print(f"Lỗi chọn server: {ex}")

async def reset_category_filter(page):
    # Buộc xóa bộ lọc Danh mục bằng JS (tìm button clear hoặc reset combobox)
    await page.evaluate("""() => {
        // Tìm và nhấn nút xóa (x) của selector danh mục nếu có
        const clearBtns = document.querySelectorAll('.ant-select-clear, [class*="clear"], [aria-label="close"]');
        clearBtns.forEach(b => b.click());

        // Nếu là thẻ select truyền thống
        document.querySelectorAll('select').forEach(sel => {
            sel.value = '';
            sel.dispatchEvent(new Event('change', { bubbles: true }));
        });
    }""")
    await page.wait_for_timeout(500)

    # Nếu trên giao diện vẫn còn hiển thị chữ "Boss", click để hủy chọn
    try:
        boss_label = page.locator("div, span").filter(has_text=re.compile(r"^Boss$")).first
        if await boss_label.count() > 0 and await boss_label.is_visible():
            await boss_label.click(force=True)
            await page.wait_for_timeout(500)
    except:
        pass

async def check_single_player(page, player_name: str, seen_notifications: set):
    prefix = f"[DROP_V6_{player_name.upper()}]"
    first_run_for_player = not any(k.startswith(prefix) for k in seen_notifications)
    found_new_drop = False
    latest_info = "Chưa có dữ liệu trên bảng"

    await reset_category_filter(page)

    # Điền tên nhân vật trực tiếp qua JS và gửi form để tránh kẹt tương tác
    success_input = await page.evaluate(f"""(name) => {{
        const inputs = Array.from(document.querySelectorAll('input'));
        const target = inputs.find(i => i.placeholder && i.placeholder.includes('tên nhân vật')) || inputs[0];
        if (!target) return false;
        
        target.focus();
        target.value = name;
        target.dispatchEvent(new Event('input', {{ bubbles: true }}));
        target.dispatchEvent(new Event('change', {{ bubbles: true }}));
        return true;
    }}""", player_name)

    if not success_input:
        input_box = page.locator("input").first
        await input_box.fill(player_name)

    await page.wait_for_timeout(300)

    # Nhấn nút Tìm
    search_btn = page.locator("button:has-text('Tìm')").first
    if await search_btn.count() > 0:
        await search_btn.click(force=True)
    else:
        await page.keyboard.press("Enter")

    await page.wait_for_timeout(3500)

    # Đọc toàn bộ nội dung hiển thị
    body_text = await page.locator("body").inner_text()
    
    # Bắt dòng rơi đồ chứa tên nhân vật kèm thời gian xuất hiện
    pattern = re.compile(
        rf"([^\n]*{re.escape(player_name)}[^\n]*[\s\S]{{0,150}}?Thời gian xuất hiện[^\n]*)",
        re.IGNORECASE
    )
    matches = pattern.findall(body_text)

    if matches:
        seen_notifications.add(f"{prefix}_INIT")
        newest_raw = re.sub(r'\s*\n\s*', '\n', matches[0].strip())
        time_match = re.search(r"Thời gian xuất hiện\s*·?\s*([^\n]+)", newest_raw)
        latest_info = time_match.group(1).strip() if time_match else newest_raw

        for match in reversed(matches):
            clean_msg = re.sub(r'\s*\n\s*', '\n', match.strip())
            unique_key = f"{prefix}_" + normalize_notification(clean_msg).replace("\n", " | ")

            if unique_key not in seen_notifications:
                seen_notifications.add(unique_key)
                if first_run_for_player:
                    if match == matches[0]:
                        send_telegram(f"🔔 <b>[Đã kết nối dữ liệu của {player_name}]:</b>\n\n{clean_msg}")
                else:
                    found_new_drop = True
                    send_telegram(f"🎉 <b>THÔNG BÁO MỚI RƠI ĐỒ ({player_name}):</b>\n\n{clean_msg}")

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

        await page.goto(URL, wait_until="networkidle", timeout=60000)
        await clean_page_and_select_server(page)

        cycle = 1
        while time.time() < end_time:
            if cycle > 1:
                try:
                    refresh_btn = page.locator("button:has-text('Làm mới')").first
                    if await refresh_btn.count() > 0:
                        await refresh_btn.click(force=True)
                        await page.wait_for_timeout(2000)
                    await clean_page_and_select_server(page)
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
            cycle += 1

            if time.time() + CHECK_INTERVAL_SECONDS < end_time:
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)
            else:
                break

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_bot())
