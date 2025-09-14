import logging
import os
import tempfile
import aiohttp
import uuid
import pathlib
import asyncio
from typing import Dict, Optional, Tuple

# Define base directory
BASE_DIR = pathlib.Path(__file__).parent
MEDIA_DIR = BASE_DIR / 'static' / 'media'

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

async def _process_media(message_data: Dict, client, config: Dict) -> Optional[Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]]:
    """
    Helper function to process media files from WhatsApp.
    Saves the media locally for the UI and uploads it to Google for the model.
    Returns a tuple of (google_uri, local_uri, mime_type, filename).
    """
    media_type = message_data.get('type')
    if not media_type or media_type not in ["image", "video", "audio", "document"]:
         return None, None, None, None

    media_content = message_data.get(media_type, {})
    media_id = media_content.get('id')
    filename = media_content.get('filename') # Get filename for documents
    if not media_id:
         return None, None, None, None

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
            
            if not media_url or not mime_type:
                return None, None, None, None

            # Determine file extension
            ext_map = {
                'image/jpeg': 'jpg', 'image/png': 'png', 'image/gif': 'gif',
                'video/mp4': 'mp4', 'audio/mpeg': 'mp3', 'audio/ogg': 'ogg',
                'application/pdf': 'pdf', 'text/plain': 'txt'
            }
            ext_name = ext_map.get(mime_type, 'bin') # Default to .bin for unknown types

            # Download media content
            async with session.get(media_url, headers=headers) as media_response:
                media_response.raise_for_status()
                file_bytes = await media_response.read()

            # 1. Save locally for UI access
            local_filename = f"{uuid.uuid4()}.{ext_name}"
            local_path = MEDIA_DIR / local_filename
            with open(local_path, 'wb') as f:
                f.write(file_bytes)
            local_uri = f"/static/media/{local_filename}"
            logging.info(f"Media saved locally to {local_path}")

            # 2. Upload to Google for AI processing
            google_uri = None
            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext_name}") as temp_file:
                temp_file.write(file_bytes)
                temp_file_path = temp_file.name
            
            try:
                file_upload = client.files.upload(file=temp_file_path)
                while file_upload.state != "ACTIVE":
                    await asyncio.sleep(1)
                    file_upload = client.files.get(name=file_upload.name)
                google_uri = file_upload.uri
                logging.info(f"Media uploaded to Google with URI: {google_uri}")
            finally:
                os.remove(temp_file_path)

            return google_uri, local_uri, mime_type, filename

      except aiohttp.ClientError as e:
          logging.error(f"Error fetching WhatsApp media: {e}")
          return None, None, None, None
