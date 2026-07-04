"""
whatsapp_meta.py
Meta WhatsApp Cloud API utilities - send messages, verify signatures
"""

import os
import requests
import hmac
import hashlib
import logging

logger = logging.getLogger("uvicorn.error")

# Load from environment
META_WHATSAPP_ACCESS_TOKEN = os.getenv("META_WHATSAPP_ACCESS_TOKEN", "")
META_WHATSAPP_PHONE_NUMBER_ID = os.getenv("META_WHATSAPP_PHONE_NUMBER_ID", "")
META_APP_SECRET = os.getenv("META_APP_SECRET", "")
META_API_VERSION = os.getenv("META_API_VERSION", "v18.0")


def verify_signature(request_body: bytes, signature_header: str) -> bool:
    """
    Verify the HMAC-SHA256 signature for Meta webhook.
    Expects signature_header like 'sha256=<hex_string>'.
    """
    if not META_APP_SECRET:
        logger.warning("No app secret set, skipping signature verification")
        return True
    
    if signature_header.startswith('sha256='):
        signature_header = signature_header[7:]
    
    expected_signature = hmac.new(
        META_APP_SECRET.encode('utf-8'),
        request_body,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(expected_signature, signature_header)


def send_whatsapp_text(to: str, message: str) -> bool:
    """
    Send a WhatsApp text message via Meta Cloud API.
    Returns True if successful, False otherwise.
    """
    url = f"https://graph.facebook.com/{META_API_VERSION}/{META_WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {META_WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {
            "body": message
        }
    }
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        logger.info(f"Sent WhatsApp text message to {to}")
        return True
    except Exception as e:
        logger.error(f"Failed to send WhatsApp text message: {e}")
        return False


def send_whatsapp_image(to: str, image_bytes: bytes) -> bool:
    """
    Send a WhatsApp image via Meta Cloud API.
    Returns True if successful, False otherwise.
    """
    # Step 1: Upload media
    upload_url = f"https://graph.facebook.com/{META_API_VERSION}/{META_WHATSAPP_PHONE_NUMBER_ID}/media"
    files = {
        'file': ('image.png', image_bytes, 'image/png')
    }
    data = {
        'messaging_product': 'whatsapp'
    }
    headers = {
        "Authorization": f"Bearer {META_WHATSAPP_ACCESS_TOKEN}"
    }
    try:
        upload_response = requests.post(upload_url, headers=headers, data=data, files=files)
        upload_response.raise_for_status()
        media_id = upload_response.json()["id"]
        logger.info(f"Uploaded image, media ID: {media_id}")
    except Exception as e:
        logger.error(f"Failed to upload image to WhatsApp: {e}")
        return False

    # Step 2: Send the image message
    send_url = f"https://graph.facebook.com/{META_API_VERSION}/{META_WHATSAPP_PHONE_NUMBER_ID}/messages"
    send_headers = {
        "Authorization": f"Bearer {META_WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    send_data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": {
            "id": media_id
        }
    }
    try:
        send_response = requests.post(send_url, headers=send_headers, json=send_data)
        send_response.raise_for_status()
        logger.info(f"Sent WhatsApp image message to {to}")
        return True
    except Exception as e:
        logger.error(f"Failed to send WhatsApp image message: {e}")
        return False