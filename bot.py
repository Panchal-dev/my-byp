# bot.py
import re
import asyncio
import signal
import sys
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram.error import Conflict, NetworkError

# Bot token (replace with a new token from @BotFather if conflicts persist)
TOKEN = "7462282759:AAHfdKJF5YsB0siG1puT5VYyzbqKGOr-wQ0"

# Regular expression for arolinks.com URLs
AROLINKS_REGEX = r'^https?://(www\.)?arolinks\.com/.+'

# Validate Telegram link (mirrors Tampermonkey's isValidTelegramLink)
def is_valid_telegram_link(link):
    """
    Validates a Telegram link, ensuring it’s not fake or invalid.
    Accepts links with %20 (e.g., https://t.me/%204iGNIBw2xbQyYzll).
    Excludes known fake links from banners.
    """
    if not link:
        print("Validation failed: Link is None or empty")
        return False
    fake_links = [
        "https://telegram.me/+GkPKT8jJ-wBmNThl",
        "https://t.me/+GkPKT8jJ-wBmNThl"
    ]
    is_telegram_link = "t.me/" in link.lower() or "telegram.me/" in link.lower()
    has_invite_code = bool(re.search(r"[+][A-Za-z0-9_-]+|%20[A-Za-z0-9_-]+|[A-Za-z0-9_-]{5,}", link))
    is_valid = (
        is_telegram_link and
        has_invite_code and
        len(link) > 15 and
        link not in fake_links and
        link != "javascript:void(0)"
    )
    print(f"Validating link {link}: {'Valid' if is_valid else 'Invalid'}")
    return is_valid

# Extract final link (mimics Tampermonkey's handlePage4)
async def extract_final_link(url):
    """
    Extracts the final Telegram link from an arolinks.com page.
    Implements Method 1 (poll #get-link), Method 2 (click #get-link), and fallback (firstp.url).
    Waits for countdown timer like waitForTimer.
    Uses Playwright for dynamic JavaScript rendering.
    """
    async with async_playwright() as p:
        browser = None
        try:
            # Launch headless browser (Chromium for reliability)
            browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-setuid-sandbox'])
            context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            page = await context.new_page()
            
            # Navigate to URL
            print(f"Navigating to {url}")
            await page.goto(url, wait_until="networkidle", timeout=15000)

            # Log all Telegram links for debugging
            all_links = await page.evaluate('''() => {
                return Array.from(document.querySelectorAll('a[href*="t.me"], a[href*="telegram.me"]')).map(a => a.href);
            }''')
            print(f"All Telegram links found: {all_links}")

            # Wait for timer (up to 5 seconds, like waitForTimer)
            try:
                await page.wait_for_function(
                    '''() => {
                        const timer = document.querySelector("#countdown, .countdown-timer");
                        return !timer || timer.style.display === "none" || timer.textContent.trim() === "0" || !timer.textContent.match(/[1-9]/);
                    }''',
                    timeout=5000
                )
                print("Timer completed, hidden, or zeroed")
            except PlaywrightTimeoutError:
                print("Timer wait timeout, proceeding with link extraction")
            except Exception as e:
                print(f"Timer wait failed: {e}, proceeding")

            # Method 1: Poll #get-link or #link1s href (up to 5 seconds, like pollForGetLink)
            final_link = None
            start_time = asyncio.get_event_loop().time()
            print("Starting Method 1: Polling #get-link/#link1s")
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
                print("Method 1 failed, attempting Method 2: Click and redirect")
                try:
                    # Ensure #get-link is clickable
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
                    
                    # Poll for href changes post-click
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
                        print(f"Post-click href: {href or 'None'}")
                        await asyncio.sleep(0.1)
                    if not final_link:
                        print("No valid href after click")
                except Exception as e:
                    print(f"Method 2 failed: {e}")

            # Fallback: Check firstp.url from scripts
            if not final_link:
                print("Method 2 failed, checking dynamic URL (fallback)")
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
                if not final_link:
                    print("No valid dynamic URL found")

            return final_link
        except Exception as e:
            print(f"Error extracting link: {e}")
            return None
        finally:
            if browser:
                try:
                    await browser.close()
                except:
                    print("Failed to close browser, continuing")

# Start command handler
async def start(update, context):
    """
    Handles the /start command, greeting the user.
    """
    await update.message.reply_text("Send me an arolinks.com link, and I'll find the final Telegram link!")

# Message handler for links
async def handle_message(update, context):
    """
    Processes user messages, checking for arolinks.com URLs and extracting final links.
    """
    text = update.message.text
    if not re.match(AROLINKS_REGEX, text, re.IGNORECASE):
        print(f"Invalid input received: {text}")
        await update.message.reply_text("Please send a valid arolinks.com link.")
        return

    print(f"Processing link: {text}")
    await update.message.reply_text("Processing your link, please wait...")

    final_link = await extract_final_link(text)
    if final_link:
        print(f"Sending final link to user: {final_link}")
        await update.message.reply_text(f"Final Link: {final_link}")
    else:
        print("No final link found")
        await update.message.reply_text("Could not find the final link. Please try again or check the URL.")

# Error handler
async def error_handler(update, context):
    """
    Handles bot errors, including conflicts and network issues.
    Prevents crashes by logging and retrying where appropriate.
    """
    error = context.error
    if isinstance(error, Conflict):
        print("Conflict error: Another bot instance detected. Waiting 10 seconds before retry...")
        await asyncio.sleep(10)
        # Do not raise; let polling continue
    elif isinstance(error, NetworkError):
        print(f"Network error: {error}. Retrying after 2 seconds...")
        await asyncio.sleep(2)
    else:
        print(f"Unexpected error: {error}")

# Shutdown handler
async def shutdown(application):
    """
    Gracefully shuts down the bot, stopping polling and closing connections.
    """
    print("Shutting down bot...")
    await application.stop()
    await application.updater.stop()
    print("Bot stopped.")

# Main function
def main():
    """
    Initializes and runs the Telegram bot with polling.
    Handles shutdown signals to prevent lingering instances.
    """
    try:
        # Build application with token
        application = Application.builder().token(TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_error_handler(error_handler)
        
        # Handle shutdown signals (SIGINT, SIGTERM)
        def handle_shutdown():
            asyncio.run_coroutine_threadsafe(shutdown(application), loop=asyncio.get_event_loop())
            sys.exit(0)
        
        signal.signal(signal.SIGINT, lambda s, f: handle_shutdown())
        signal.signal(signal.SIGTERM, lambda s, f: handle_shutdown())
        
        print("Bot started...")
        # Run polling with drop_pending_updates to clear stale sessions
        application.run_polling(allowed_updates=["message"], drop_pending_updates=True)
    except Exception as e:
        print(f"Fatal error in main: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()