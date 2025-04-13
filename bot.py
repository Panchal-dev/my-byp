# bot.py
import re
import asyncio
import signal
import sys
from pyppeteer import launch
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram.error import Conflict, NetworkError

# Bot token
TOKEN = "7462282759:AAEmVQN9xshWqf0GiDJ1ketczGmkUTShrBk"

# Regular expression for arolinks.com URLs
AROLINKS_REGEX = r'^https?://(www\.)?arolinks\.com/.+'

# Validate Telegram link (adapted from Tampermonkey script)
def is_valid_telegram_link(link):
    if not link:
        return False
    fake_links = [
        "https://telegram.me/+GkPKT8jJ-wBmNThl",
        "https://t.me/+GkPKT8jJ-wBmNThl"
    ]
    is_telegram_link = "t.me/" in link or "telegram.me/" in link
    has_invite_code = bool(re.search(r"[+][A-Za-z0-9_-]+|%20[A-Za-z0-9_-]+|[A-Za-z0-9_-]{5,}", link))
    return (
        is_telegram_link
        and has_invite_code
        and len(link) > 15
        and link not in fake_links
        and link != "javascript:void(0)"
    )

# Extract final link using Puppeteer (mimics handlePage4)
async def extract_final_link(url):
    browser = None
    try:
        # Launch headless browser
        browser = await launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox'],
            timeout=10000
        )
        page = await browser.newPage()
        
        # Set user agent and navigate
        await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        await page.goto(url, {'waitUntil': 'networkidle2', 'timeout': 15000})

        # Log all Telegram links
        all_links = await page.evaluate('''() => {
            return Array.from(document.querySelectorAll('a[href*="t.me"], a[href*="telegram.me"]')).map(a => a.href);
        }''')
        print(f"All Telegram links found: {all_links}")

        # Wait for timer (up to 5 seconds, like waitForTimer)
        try:
            await page.waitForFunction(
                '''() => {
                    const timer = document.querySelector("#countdown, .countdown-timer");
                    return !timer || timer.style.display === "none" || timer.textContent.trim() === "0" || !timer.textContent.match(/[1-9]/);
                }''',
                {'timeout': 5000}
            )
            print("Timer completed, hidden, or zeroed")
        except Exception as e:
            print(f"Timer wait failed: {e}, proceeding with link extraction")

        # Method 1: Poll #get-link or #link1s href (up to 5 seconds, like pollForGetLink)
        final_link = None
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < 5:
            href = await page.evaluate('''() => {
                const el = document.querySelector("#get-link, #link1s");
                return el ? el.href : null;
            }''')
            if href:
                print(f"#get-link href: {href}")
                if is_valid_telegram_link(href):
                    final_link = href
                    print(f"Valid #get-link href found (Method 1): {final_link}")
                    break
                else:
                    print(f"Invalid #get-link href: {href}")
            else:
                print("No #get-link element found yet")
            await asyncio.sleep(0.1)

        # Method 2: Simulate click and poll href (up to 2 seconds, like captureRedirectUrl)
        if not final_link:
            print("Method 1 failed, attempting Method 2 (click and redirect)")
            try:
                await page.evaluate('''() => {
                    const el = document.querySelector("#get-link, #link1s");
                    if (el) {
                        el.removeAttribute("disabled");
                        el.style.pointerEvents = "auto";
                        el.style.display = "block";
                        el.click();
                    }
                }''')
                print("Clicked #get-link element")
                
                start_time = asyncio.get_event_loop().time()
                last_href = None
                while asyncio.get_event_loop().time() - start_time < 2:
                    href = await page.evaluate('''() => {
                        const el = document.querySelector("#get-link, #link1s");
                        return el ? el.href : null;
                    }''')
                    if href and href != last_href and is_valid_telegram_link(href):
                        final_link = href
                        print(f"Valid post-click href found (Method 2): {final_link}")
                        break
                    last_href = href
                    await asyncio.sleep(0.1)
                if not final_link:
                    print("No valid href after click")
            except Exception as e:
                print(f"Method 2 failed: {e}")

        # Fallback: Check firstp.url
        if not final_link:
            print("Method 2 failed, checking dynamic URL")
            scripts = await page.evaluate('''() => {
                return Array.from(document.querySelectorAll("script")).map(s => s.textContent);
            }''')
            for script in scripts:
                match = re.search(r'firstp\s*=\s*{[^}]*url:\s*[\'"]([^\'"]+)[\'"]', script)
                if match:
                    dynamic_url = match.group(1)
                    if dynamic_url.startswith("tg://join?invite="):
                        dynamic_url = f"https://t.me/+{dynamic_url.split('invite=')[1]}"
                    print(f"Found dynamic URL: {dynamic_url}")
                    if is_valid_telegram_link(dynamic_url) and dynamic_url not in all_links:
                        final_link = dynamic_url
                        print(f"Valid fallback link: {final_link}")
                        break

        return final_link
    except Exception as e:
        print(f"Error extracting link: {e}")
        return None
    finally:
        if browser:
            try:
                await browser.close()
            except:
                pass

# Start command
async def start(update, context):
    await update.message.reply_text("Send me an arolinks.com link, and I'll find the final Telegram link!")

# Handle messages
async def handle_message(update, context):
    text = update.message.text
    if not re.match(AROLINKS_REGEX, text, re.IGNORECASE):
        await update.message.reply_text("Please send a valid arolinks.com link.")
        return

    await update.message.reply_text("Processing your link, please wait...")

    final_link = await extract_final_link(text)
    if final_link:
        await update.message.reply_text(f"Final Link: {final_link}")
    else:
        await update.message.reply_text("Could not find the final link. Please try again or check the URL.")

# Error handler
async def error_handler(update, context):
    error = context.error
    if isinstance(error, Conflict):
        print("Conflict error detected: Another bot instance is running. Retrying in 5 seconds...")
        await asyncio.sleep(5)
        # Attempt to restart polling
        raise error  # Let Application handle retry
    elif isinstance(error, NetworkError):
        print(f"Network error: {error}. Retrying...")
        await asyncio.sleep(2)
    else:
        print(f"Unexpected error: {error}")

# Shutdown handler
async def shutdown(application):
    print("Shutting down bot...")
    await application.stop()
    await application.updater.stop()
    print("Bot stopped.")

# Main function
def main():
    try:
        application = Application.builder().token(TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_error_handler(error_handler)
        
        # Handle shutdown signals
        def handle_shutdown():
            asyncio.run_coroutine_threadsafe(shutdown(application), loop=asyncio.get_event_loop())
            sys.exit(0)
        
        signal.signal(signal.SIGINT, lambda s, f: handle_shutdown())
        signal.signal(signal.SIGTERM, lambda s, f: handle_shutdown())
        
        print("Bot started...")
        application.run_polling(allowed_updates=["message"], drop_pending_updates=True)
    except Exception as e:
        print(f"Fatal error in main: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()