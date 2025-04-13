import re
import time
import json
import logging
from datetime import datetime
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
from telegram.ext import Application, CommandHandler, MessageHandler, filters

# Bot token (provided by user)
TOKEN = "7462282759:AAEmVQN9xshWqf0GiDJ1ketczGmkUTShrBk"

# Configure logging to mimic Tampermonkey's logMessage
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    handlers=[
        logging.FileHandler("arolinks.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# In-memory log storage for debugging (like downloadLogs)
LOGS = []

def log_message(message):
    """
    Log a message with timestamp and store in memory.
    Args:
        message (str): Message to log.
    """
    timestamp = datetime.utcnow().isoformat()
    log_entry = f"[{timestamp}] {message}"
    logger.info(message)
    LOGS.append(log_entry)
    if len(LOGS) > 1000:  # Limit to 1000 logs
        LOGS.pop(0)

def download_logs():
    """
    Return logs as a string for debugging.
    Returns:
        str: Concatenated log entries.
    """
    try:
        log_message("Generating log file for debugging")
        return "\n".join(LOGS)
    except Exception as e:
        log_message(f"Error downloading logs: {e}")
        return ""

# Regular expression for validating arolinks.com URLs
AROLINKS_REGEX = r'^https?://(www\.)?arolinks\.com/.+'

def is_valid_arolinks_url(url):
    """
    Check if the URL is a valid arolinks.com link.
    Args:
        url (str): URL to validate.
    Returns:
        bool: True if valid, False otherwise.
    """
    try:
        valid = bool(re.match(AROLINKS_REGEX, url, re.IGNORECASE))
        log_message(f"Validating URL {url}: {'Valid' if valid else 'Invalid'}")
        return valid
    except Exception as e:
        log_message(f"URL validation error for {url}: {e}")
        return False

def is_valid_telegram_link(link, banner_links=None):
    """
    Validate if a link is a legitimate Telegram link.
    Args:
        link (str): URL to validate.
        banner_links (list): Links from banner elements to exclude.
    Returns:
        bool: True if valid, False otherwise.
    """
    if not link:
        log_message("Validation failed: Link is None")
        return False
    fake_links = [
        "https://telegram.me/+GkPKT8jJ-wBmNThl",
        "https://t.me/+GkPKT8jJ-wBmNThl"
    ]
    banner_links = banner_links or []
    try:
        is_telegram_link = "t.me/" in link.lower() or "telegram.me/" in link.lower()
        has_invite_code = bool(re.search(r"[+][A-Za-z0-9_-]+|%20[A-Za-z0-9_-]+|[A-Za-z0-9_-]{5,}", link))
        valid = (
            is_telegram_link and
            has_invite_code and
            len(link) > 15 and
            link not in fake_links and
            link not in banner_links and
            link.lower() != "javascript:void(0)"
        )
        log_message(f"Validating Telegram link {link}: {'Valid' if valid else 'Invalid'}")
        return valid
    except Exception as e:
        log_message(f"Telegram link validation error for {link}: {e}")
        return False

def wait_for_timer(soup, base_url, max_wait=5.0, interval=0.5):
    """
    Simulate waiting for the countdown timer to complete or hide.
    Refreshes the page to mimic client-side updates.
    Args:
        soup: BeautifulSoup object of the page.
        base_url (str): URL to fetch for refreshes.
        max_wait (float): Maximum wait time in seconds.
        interval (float): Polling interval in seconds.
    Returns:
        tuple: (bool, BeautifulSoup) Success flag and updated soup.
    """
    start_time = time.time()
    elapsed = 0
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        while elapsed < max_wait:
            timer = soup.select_one("#countdown, .countdown-timer")
            if not timer:
                log_message("No timer element found, proceeding")
                return True, soup
            display = timer.get("style", "")
            text = timer.get_text(strip=True)
            if "display: none" in display or text == "0" or not re.search(r"[1-9]", text):
                log_message("Timer completed, hidden, or zeroed")
                return True, soup
            elapsed = time.time() - start_time
            log_message(f"Waiting for timer: {text or 'N/A'} seconds remaining")
            time.sleep(interval)
            try:
                response = requests.get(base_url, timeout=10, headers=headers)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
            except Exception as e:
                log_message(f"Timer refresh error: {e}")
        log_message("Timer wait timeout, forcing bypass")
        return True, soup
    except Exception as e:
        log_message(f"Error waiting for timer: {e}")
        return False, soup

def poll_for_get_link(soup, base_url, max_wait=5.0, interval=0.1):
    """
    Poll for #get-link or #link1s href, refreshing the page to catch updates.
    Args:
        soup: BeautifulSoup object.
        base_url (str): URL to refresh.
        max_wait (float): Maximum wait time in seconds.
        interval (float): Polling interval in seconds.
    Returns:
        str: Valid href or None.
    """
    start_time = time.time()
    elapsed = 0
    last_href = None
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    banner_links = [a["href"] for a in soup.select('.banner-inner a[href*="t.me"], .banner-inner a[href*="telegram.me"]')]
    log_message(f"Banner links to exclude: {banner_links}")
    while elapsed < max_wait:
        try:
            get_link = soup.select_one("#get-link, #link1s")
            if get_link and get_link.get("href"):
                current_href = get_link["href"]
                if current_href != last_href:
                    log_message(f"#get-link href updated: {current_href}")
                    last_href = current_href
                if is_valid_telegram_link(current_href, banner_links):
                    log_message(f"Valid #get-link href found (Method 1): {current_href}")
                    return current_href
                log_message(f"Invalid #get-link href: {current_href}")
            else:
                log_message("No #get-link element found yet")
            elapsed = time.time() - start_time
            if elapsed < max_wait:
                time.sleep(interval)
                try:
                    response = requests.get(base_url, timeout=10, headers=headers)
                    response.raise_for_status()
                    soup = BeautifulSoup(response.text, "html.parser")
                except Exception as e:
                    log_message(f"Polling refresh error: {e}")
        except Exception as e:
            log_message(f"Error polling for #get-link: {e}")
        elapsed = time.time() - start_time
    log_message("Polling timeout for Method 1")
    return None

def simulate_interaction(soup, base_url, max_wait=2.0, interval=0.1):
    """
    Simulate clicking #get-link by re-fetching the page and polling for href updates.
    Args:
        soup: BeautifulSoup object.
        base_url (str): URL to refresh.
        max_wait (float): Maximum wait time in seconds.
        interval (float): Polling interval in seconds.
    Returns:
        str: Valid href or None.
    """
    start_time = time.time()
    elapsed = 0
    last_href = None
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    banner_links = [a["href"] for a in soup.select('.banner-inner a[href*="t.me"], .banner-inner a[href*="telegram.me"]')]
    log_message("Attempting Method 2 (simulated interaction)")
    try:
        # Initial page fetch to simulate click
        response = requests.get(base_url, timeout=10, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        while elapsed < max_wait:
            get_link = soup.select_one("#get-link, #link1s")
            if get_link and get_link.get("href"):
                current_href = get_link["href"]
                if current_href != last_href:
                    log_message(f"Post-interaction href updated: {current_href}")
                    last_href = current_href
                if is_valid_telegram_link(current_href, banner_links):
                    log_message(f"Valid href found (Method 2): {current_href}")
                    return current_href
                log_message(f"Invalid post-interaction href: {current_href}")
            else:
                log_message("No #get-link element found during interaction")
            elapsed = time.time() - start_time
            if elapsed < max_wait:
                time.sleep(interval)
                try:
                    response = requests.get(base_url, timeout=10, headers=headers)
                    response.raise_for_status()
                    soup = BeautifulSoup(response.text, "html.parser")
                except Exception as e:
                    log_message(f"Interaction refresh error: {e}")
        log_message("Interaction polling timeout")
        return None
    except Exception as e:
        log_message(f"Error during simulated interaction: {e}")
        return None

def extract_dynamic_url(soup):
    """
    Extract firstp.url from script tags as a fallback.
    Args:
        soup: BeautifulSoup object.
    Returns:
        str: Valid Telegram URL or None.
    """
    try:
        scripts = [script.text for script in soup.find_all("script") if script.text]
        banner_links = [a["href"] for a in soup.select('.banner-inner a[href*="t.me"], .banner-inner a[href*="telegram.me"]')]
        for script in scripts:
            match = re.search(r'firstp\s*=\s*{[^}]*url:\s*[\'"]([^\'"]+)[\'"]', script)
            if match:
                dynamic_url = match.group(1)
                log_message(f"Found dynamic URL: {dynamic_url}")
                if dynamic_url.startswith("tg://join?invite="):
                    dynamic_url = f"https://t.me/+{dynamic_url.split('invite=')[1]}"
                if is_valid_telegram_link(dynamic_url, banner_links):
                    log_message(f"Valid fallback link: {dynamic_url}")
                    return dynamic_url
                log_message(f"Invalid dynamic URL: {dynamic_url}")
        log_message("No valid dynamic URL found")
        return None
    except Exception as e:
        log_message(f"Error extracting dynamic URL: {e}")
        return None

async def extract_final_link(url):
    """
    Extract the final Telegram link from an arolinks.com URL.
    Args:
        url (str): Arolinks URL to process.
    Returns:
        str: Final Telegram link or None.
    """
    log_message(f"Processing URL: {url}")
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        # Initial page fetch
        response = requests.get(url, timeout=10, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        log_message("Fetched initial page successfully")

        # Log all Telegram links for debugging
        all_links = [a["href"] for a in soup.select('a[href*="t.me"], a[href*="telegram.me"]')]
        log_message(f"All Telegram links found: {all_links}")

        # Wait for timer (simulates client-side countdown)
        timer_success, soup = wait_for_timer(soup, url)
        if not timer_success:
            log_message("Timer wait failed, proceeding anyway")

        # Method 1: Poll for #get-link href
        final_link = poll_for_get_link(soup, url)
        if final_link:
            log_message(f"Final destination link (Method 1): {final_link}")
            return final_link

        # Method 2: Simulate interaction
        final_link = simulate_interaction(soup, url)
        if final_link:
            log_message(f"Final destination link (Method 2): {final_link}")
            return final_link

        # Fallback: Extract firstp.url
        final_link = extract_dynamic_url(soup)
        if final_link:
            log_message(f"Final destination link (Fallback): {final_link}")
            return final_link

        log_message("No valid link found after all methods")
        return None
    except Exception as e:
        log_message(f"Error extracting final link: {e}")
        return None

async def start(update, context):
    """
    Handle /start command.
    Args:
        update: Telegram update object.
        context: Telegram context object.
    """
    log_message(f"Received /start from user {update.effective_user.id}")
    await update.message.reply_text(
        "Send me an arolinks.com link, and I'll find the final Telegram link!"
    )

async def handle_message(update, context):
    """
    Handle incoming messages.
    Args:
        update: Telegram update object.
        context: Telegram context object.
    """
    text = update.message.text
    user_id = update.effective_user.id
    log_message(f"Received message from user {user_id}: {text}")

    if not is_valid_arolinks_url(text):
        log_message("Invalid arolinks.com URL received")
        await update.message.reply_text("Please send a valid arolinks.com link.")
        return

    await update.message.reply_text("Processing your link, please wait...")

    final_link = await extract_final_link(text)
    if final_link:
        log_message(f"Sending final link to user {user_id}: {final_link}")
        await update.message.reply_text(f"Final Link: {final_link}")
    else:
        log_message(f"Failed to find final link for user {user_id}")
        await update.message.reply_text(
            "Could not find the final link. Please try again or check the URL."
        )
        # Send logs for debugging
        logs = download_logs()
        if logs:
            await update.message.reply_document(
                document=logs.encode(),
                filename="arolinks.log",
                caption="Debug logs for troubleshooting"
            )

async def error_handler(update, context):
    """
    Handle bot errors.
    Args:
        update: Telegram update object.
        context: Telegram context object.
    """
    log_message(f"Error occurred: {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "An error occurred. Please try again later."
        )

def main():
    """
    Initialize and run the bot.
    """
    try:
        log_message("Starting bot initialization")
        application = Application.builder().token(TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_error_handler(error_handler)
        log_message("Bot started, entering polling mode")
        application.run_polling(allowed_updates=["message"])
    except Exception as e:
        log_message(f"Fatal error during bot initialization: {e}")

if __name__ == "__main__":
    main()