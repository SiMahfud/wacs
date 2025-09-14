import asyncio
import logging
import json
import aiohttp
import aiohttp.web
import aiomysql
from google import genai
from google.genai import types
from google.genai.types import GenerateContentConfig
from typing import Optional, List

# Import dari modul-modul yang telah dibuat
import config
import database
import tools
import whatsapp_service

# Konfigurasi library dan inisialisasi Klien
client = genai.Client(api_key=config.GOOGLE_API_KEY)

# Variabel global untuk koneksi database
db_pool = None

# Konfigurasi logging
logging.basicConfig(level=logging.INFO)

async def generate_gemini_response(content: types.Content, chat_id: int, chat_history: Optional[List[types.Content]] = None):
    """Generates a Gemini response with optional chat history."""
    global db_pool
    try:
        contents = chat_history + [content] if chat_history else [content]
        response = client.models.generate_content(
            model=config.GOOGLE_MODEL,
            contents=contents,
            config=GenerateContentConfig(
                temperature=1,
                max_output_tokens=6000,
                system_instruction=config.SYSTEM_PROMPT,
                tools=[tools.db_tool, tools.extra_tools],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True
                ),
                safety_settings=[
                    types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_HARASSMENT', threshold='BLOCK_NONE'),
                ],
            ),
        )
        res_parts = response.candidates[0].content.parts
        response_text = "".join(part.text + "\n" for part in res_parts if part.text)
        function_call_parts = [part.function_call for part in res_parts if part.function_call]
        
        await database.save_chat_to_db(db_pool, chat_id, content, response.candidates[0].content)
        
        if response_text:
            await whatsapp_service.send_whatsapp_message(chat_id, response_text, vars(config))
        
        if function_call_parts:
             function_response_parts = []
             for function_call in function_call_parts:
                fc_res = await tools.handle_tool_call(function_call, db_pool, client)
                function_response_parts.append(fc_res)
             
             fc_content = types.Content(role="tool", parts=function_response_parts)
             await generate_gemini_response(fc_content, chat_id, chat_history=contents + [response.candidates[0].content])

    except Exception as e:
        logging.exception("Error generating Gemini response:")
        await whatsapp_service.send_whatsapp_message(chat_id, "Maaf, terjadi kesalahan saat memproses permintaan Anda.", vars(config))

async def handle_whatsapp_message(message_data: dict):
    """Handles incoming WhatsApp messages."""
    global db_pool
    try:
        recipient_number = message_data['from']
        parts = []
        message_text = None

        if message_data.get('type') == 'text':
            message_text = message_data.get('text', {}).get('body')
            if message_text and message_text.strip().lower() == 'clear':
                await database.delete_chat_history_from_db(db_pool, recipient_number)
                await whatsapp_service.send_whatsapp_message(recipient_number, "Riwayat percakapan Anda telah berhasil dihapus.", vars(config))
                return
            parts.append(types.Part.from_text(text=message_text))

        media_result = await whatsapp_service._process_media(message_data, client, vars(config))
        if media_result:
            media_url, mime_type = media_result
            media_type = message_data.get('type')

            if media_url and mime_type:
                caption = message_data.get(media_type, {}).get('caption')
                if caption:
                    parts.append(types.Part.from_text(text=caption))
                else:
                    parts.append(types.Part.from_text(text="perhatikan ini."))
                parts.append(types.Part.from_uri(file_uri=media_url, mime_type=mime_type))
        
        if not parts:
            await whatsapp_service.send_whatsapp_message(recipient_number, "Maaf, I couldn't understand your input.", vars(config))
            return
       
        content = types.Content(role="user", parts=parts)
        chat_history = await database.get_chat_history_from_db(db_pool, recipient_number)
        await generate_gemini_response(content, recipient_number, chat_history)

    except database.DatabaseError as e:
         logging.error(f"Error processing message: {e}")
         await whatsapp_service.send_whatsapp_message(recipient_number, "Maaf, terjadi kesalahan saat memproses permintaan Anda.", vars(config))
    except Exception as e:
        logging.exception("Error processing message:")
        await whatsapp_service.send_whatsapp_message(recipient_number, "Maaf, terjadi kesalahan saat memproses pesan Anda.", vars(config))

async def whatsapp_webhook_handler(request):
    """Handles incoming WhatsApp webhook requests."""
    if request.method == 'GET':
        verify_token = request.query.get('hub.verify_token')
        challenge = request.query.get('hub.challenge')
        
        if verify_token == config.WHATSAPP_VERIFY_TOKEN:
            return aiohttp.web.Response(text=challenge, status=200)
        else:
            return aiohttp.web.Response(text='Error, invalid verification token', status=403)
    elif request.method == 'POST':
        try:
          data = await request.json()
          logging.info(f"Received WhatsApp webhook: {data}")
          if data.get("entry"):
            for entry in data.get("entry"):
                 for change in entry.get("changes"):
                      if change.get("value", {}).get("messages"):
                          for message in change.get("value", {}).get("messages"):
                            await handle_whatsapp_message(message)
        except Exception as e:
          logging.exception(f"Error handling webhook: {e}")

        return aiohttp.web.Response(status=200)

async def main():
    global db_pool
    db_pool = await aiomysql.create_pool(
        host=config.MYSQL_HOST,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,
        db=config.MYSQL_DATABASE,
        autocommit=True,
        loop=asyncio.get_event_loop()
    )
    
    app = aiohttp.web.Application()
    app.add_routes([aiohttp.web.get('/whatsapp/webhook', whatsapp_webhook_handler),
                    aiohttp.web.post('/whatsapp/webhook', whatsapp_webhook_handler)])

    runner = aiohttp.web.AppRunner(app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, 'localhost', 8123)
    await site.start()

    logging.info("Server started, listening on http://localhost:8123")
    
    try:
       while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logging.info("Server is shutting down.")
    finally:
        await runner.cleanup()
        if db_pool:
            db_pool.close()
            await db_pool.wait_closed()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Process interrupted by user.")