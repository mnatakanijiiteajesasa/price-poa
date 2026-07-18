"""
telegram_bot.py
Helper functions for interacting with the Telegram Bot API - verifying
incoming webhook requests and sending messages/photos back to users.

Replaces whatsapp_meta.py from the Meta WhatsApp integration.
"""

import os
import logging
import requests

logger = logging.getLogger("uvicorn.error")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
TELEGRAM_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def verify_telegram_secret(request_secret: str) -> bool:
    """
    Telegram doesn't sign payloads the way Meta does (no X-Hub-Signature-256).
    Instead, when you register your webhook via setWebhook you pass a
    `secret_token`. Telegram then sends that same value on every request in
    the `X-Telegram-Bot-Api-Secret-Token` header, and you just compare it.
    """
    if not TELEGRAM_WEBHOOK_SECRET:
        logger.warning("TELEGRAM_WEBHOOK_SECRET not set - refusing all requests")
        return False
    return request_secret == TELEGRAM_WEBHOOK_SECRET


def send_telegram_text(chat_id: int, text: str) -> bool:
    """Send a plain text message to a chat."""
    url = f"{TELEGRAM_API_BASE}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
    }
    try:
        # Sends POST request to Telegram API
        resp = requests.post(url, json=payload, timeout=10)
        # Raises an HTTPError if the HTTP request returned an unsuccessful status code
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.error(f"Failed to send Telegram text message: {e}")
        return False


def send_telegram_photo(chat_id: int, image_bytes: bytes, caption: str = None) -> bool:
    """Send a photo (e.g. generated infographic) to a chat."""
    url = f"{TELEGRAM_API_BASE}/sendPhoto"
    files = {"photo": ("infographic.png", image_bytes, "image/png")}
    data = {"chat_id": chat_id}
    if caption:
        data["caption"] = caption
    try:
        resp = requests.post(url, data=data, files=files, timeout=15)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.error(f"Failed to send Telegram photo: {e}")
        return False


def set_telegram_webhook(webhook_url: str) -> bool:
    """
    One-off helper to register your webhook URL with Telegram. Run this
    once after deploying (e.g. from a Python shell or a small script) -
    it does not need to run on every server start.

    Example:
        from telegram_bot import set_telegram_webhook
        set_telegram_webhook("https://yourdomain.com/webhook/telegram")
    """
    url = f"{TELEGRAM_API_BASE}/setWebhook"
    payload = {
        "url": webhook_url,
        "secret_token": TELEGRAM_WEBHOOK_SECRET,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        if result.get("ok"):
            logger.info(f"Telegram webhook set to {webhook_url}")
            return True
        logger.error(f"Telegram setWebhook rejected: {result}")
        return False
    except requests.RequestException as e:
        logger.error(f"Failed to set Telegram webhook: {e}")
        return False


def get_telegram_webhook_info() -> dict:
    """Handy debugging helper - shows Telegram's view of your current webhook."""
    url = f"{TELEGRAM_API_BASE}/getWebhookInfo"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        logger.error(f"Failed to get Telegram webhook info: {e}")
        return {}