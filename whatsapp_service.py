import logging
import os
import tempfile
import aiohttp
from typing import Dict, Optional, Tuple

async def send_whatsapp_message(recipient_number: str, text: str, config: Dict, media_url: Optional[str] = None, mime_type: Optional[str] = None):
    """Function to send a WhatsApp message."""
    headers = {
        "Authorization": f"Bearer {config['WHATSAPP_BEARER_TOKEN']}",
        "Content-Type": "application/json"
    }
    
    payload = {
      "messaging_product": "whatsapp",
      "recipient_type": "individual",
      "to": recipient_number,
    }
    
    if media_url:
        payload["type"] = "image" if mime_type.startswith("image") else "video" if mime_type.startswith("video") else "audio" if mime_type.startswith("audio") else "document"
        payload[payload["type"]] = {
            "link": media_url
        }
    else:
        payload["type"] = "text"
        payload["text"] = {
              "body": text
        }
    
    async with aiohttp.ClientSession() as session:
        try:
            url = f"{config['WHATSAPP_API_URL']}/{config['WHATSAPP_API_VERSION']}/{config['WHATSAPP_PHONE_NUMBER_ID']}/messages"
            async with session.post(url, headers=headers, json=payload) as response:
                response.raise_for_status()
                response_data = await response.json()
        except aiohttp.ClientError as e:
           logging.error(f"Error sending WhatsApp message: {e}")

async def _process_media(message_data: Dict, client, config: Dict) -> Optional[Tuple[Optional[str], Optional[str]]]:
    """Helper function to process media files from WhatsApp."""
    media_type = message_data.get('type')
    if not media_type or media_type not in ["image", "video", "audio", "document"]:
         return None, None

    media_id = message_data.get(media_type, {}).get('id')
    if not media_id:
         return None, None

    headers = {
      "Authorization": f"Bearer {config['WHATSAPP_BEARER_TOKEN']}",
    }

    url = f"{config['WHATSAPP_API_URL']}/{config['WHATSAPP_API_VERSION']}/{media_id}"
    async with aiohttp.ClientSession() as session:
      try:
        async with session.get(url, headers=headers) as response:
            response.raise_for_status()
            media_info = await response.json()
            media_url = media_info.get("url")
            mime_type = media_info.get("mime_type")
            ext_name = ''
            if mime_type == 'image/jpeg':
                ext_name = 'jpg'
            elif mime_type == 'image/png':
                ext_name = 'png'
            elif mime_type == 'image/gif':
                ext_name = 'gif'
            elif mime_type == 'video/mp4':
                ext_name = 'mp4'
            elif mime_type == 'audio/mpeg':
                ext_name = 'mp3'
            elif mime_type == 'audio/ogg':
                ext_name = 'ogg'
            elif mime_type == 'application/pdf':
                ext_name = 'pdf'
            elif mime_type == 'text/plain':
                ext_name = 'txt'
            if media_url:
                async with session.get(media_url, headers=headers) as media_response:
                    media_response.raise_for_status()
                    file_bytes = await media_response.read()
                    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext_name}")
                    temp_file.write(file_bytes)
                    temp_file.close()
                    file_upload = client.files.upload(file=temp_file.name)
                    os.remove(temp_file.name)
                    while file_upload.state != "ACTIVE":
                        await asyncio.sleep(1)
                        file_upload = client.files.get(name=file_upload.name)
                    return file_upload.uri, mime_type
            else:
                return None, None
      except aiohttp.ClientError as e:
          logging.error(f"Error fetching WhatsApp media: {e}")
          return None, None
