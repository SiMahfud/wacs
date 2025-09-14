import asyncio
import logging
import json
import aiohttp
from aiohttp import web
import aiomysql
from google import genai
from google.genai import types
from google.genai.types import GenerateContentConfig
from typing import Optional, List
import pathlib
from collections import defaultdict

# Import dari modul-modul yang telah dibuat
import config
import database
import tools
import whatsapp_service
from utils import content_to_dict

# Konfigurasi library dan inisialisasi Klien
client = genai.Client(api_key=config.GOOGLE_API_KEY)

# --- Variabel Global ---
db_pool = None
logging.basicConfig(level=logging.INFO)
BASE_DIR = pathlib.Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / 'templates'

# --- Logika Inti Bot ---
async def generate_gemini_response(content: types.Content, chat_id: str, chat_history: Optional[List[types.Content]] = None):
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

async def handle_whatsapp_message(message_data: dict, app: web.Application):
    """Handles incoming WhatsApp messages based on control status."""
    global db_pool
    recipient_number = message_data['from']
    
    try:
        control_status = await database.get_control_status(db_pool, recipient_number)
        
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
            return

        content = types.Content(role="user", parts=parts)

        # Check if this is a new conversation
        is_new_conversation = not await database.chat_exists(db_pool, recipient_number)

        if control_status == 'admin':
            logging.info(f"Chat for {recipient_number} is admin-controlled. Storing message and notifying UI.")
            await database.save_user_message_only(db_pool, recipient_number, content)
            message_to_broadcast = {
                'type': 'new_message',
                'data': {
                    'chat_id': recipient_number,
                    'message': {
                        'user': content_to_dict(content),
                        'bot': None
                    }
                }
            }
            for ws in app['websockets']:
                await ws.send_json(message_to_broadcast)
        elif control_status == 'bot':
            logging.info(f"Chat for {recipient_number} is bot-controlled. Generating AI response.")
            chat_history = await database.get_chat_history_from_db(db_pool, recipient_number)
            await generate_gemini_response(content, recipient_number, chat_history)

        if is_new_conversation:
            new_conversation_broadcast = {
                'type': 'new_conversation',
                'data': {
                    'chat_id': recipient_number
                }
            }
            for ws in app['websockets']:
                await ws.send_json(new_conversation_broadcast)

    except Exception as e:
        logging.exception("Error processing message:")
        await whatsapp_service.send_whatsapp_message(recipient_number, "Maaf, terjadi kesalahan.", vars(config))

async def whatsapp_webhook_handler(request):
    if request.method == 'GET':
        verify_token = request.query.get('hub.verify_token')
        challenge = request.query.get('hub.challenge')
        
        if verify_token == config.WHATSAPP_VERIFY_TOKEN:
            return web.Response(text=challenge, status=200)
        else:
            return web.Response(text='Error, invalid verification token', status=403)
    elif request.method == 'POST':
        try:
          data = await request.json()
          if data.get("entry"):
            for entry in data.get("entry"):
                 for change in entry.get("changes"):
                      if change.get("value", {}).get("messages"):
                          for message in change.get("value", {}).get("messages"):
                            await handle_whatsapp_message(message, request.app)
        except Exception as e:
          logging.exception(f"Error handling webhook: {e}")

        return web.Response(status=200)

async def admin_dashboard(request):
    index_path = TEMPLATES_DIR / 'index.html'
    try:
        with open(index_path, 'r') as f:
            return web.Response(text=f.read(), content_type='text/html')
    except FileNotFoundError:
        return web.Response(text="Admin page not found.", status=404)

async def get_conversations(request):
    global db_pool
    try:
        chat_ids = await database.get_all_chat_ids(db_pool)
        return web.json_response(chat_ids)
    except database.DatabaseError as e:
        return web.json_response({'error': str(e)}, status=500)

async def get_conversation_history(request):
    global db_pool
    chat_id = request.match_info.get('chat_id')
    if not chat_id:
        return web.json_response({'error': 'Chat ID is required'}, status=400)
    
    try:
        history = await database.get_chat_history_for_admin(db_pool, chat_id)
        if history is None:
            return web.json_response({'error': 'No history found for this chat ID'}, status=404)
        return web.json_response(history)
    except database.DatabaseError as e:
        return web.json_response({'error': str(e)}, status=500)

async def get_control_status_handler(request):
    chat_id = request.match_info.get('chat_id')
    status = await database.get_control_status(db_pool, chat_id)
    return web.json_response({'controlled_by': status})

async def set_control_status_handler(request):
    chat_id = request.match_info.get('chat_id')
    data = await request.json()
    new_status = data.get('status')
    if new_status not in ['bot', 'admin']:
        return web.json_response({'error': 'Invalid status'}, status=400)
    
    await database.set_control_status(db_pool, chat_id, new_status)
    return web.json_response({'success': True, 'new_status': new_status})

async def admin_reply_handler(request):
    chat_id = request.match_info.get('chat_id')
    data = await request.json()
    text = data.get('text')
    if not text:
        return web.json_response({'error': 'Text is required'}, status=400)

    try:
        await whatsapp_service.send_whatsapp_message(chat_id, text, vars(config))
        await database.save_admin_reply(db_pool, chat_id, text)
        
        message_to_broadcast = {
            'type': 'new_message',
            'data': {
                'chat_id': chat_id,
                'message': {
                    'user': None,
                    'bot': {'role': 'admin', 'parts': [{'text': text}]}
                }
            }
        }
        for ws in request.app['websockets']:
            await ws.send_json(message_to_broadcast)
            
        return web.json_response({'success': True})
    except Exception as e:
        logging.error(f"Error sending admin reply: {e}")
        return web.json_response({'error': 'Failed to send message'}, status=500)

async def global_websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    
    request.app['websockets'].append(ws)
    logging.info("Global WebSocket connection established.")

    try:
        async for msg in ws:
            pass
    except Exception as e:
        logging.error(f"Global WebSocket error: {e}")
    finally:
        request.app['websockets'].remove(ws)
        logging.info("Global WebSocket connection closed.")

    return ws

async def main():
    global db_pool
    db_pool = await aiomysql.create_pool(
        host=config.MYSQL_HOST, user=config.MYSQL_USER, password=config.MYSQL_PASSWORD,
        db=config.MYSQL_DATABASE, autocommit=True, loop=asyncio.get_event_loop()
    )
    
    app = web.Application()
    app['websockets'] = []

    app.add_routes([
        web.get('/whatsapp/webhook', whatsapp_webhook_handler),
        web.post('/whatsapp/webhook', whatsapp_webhook_handler),
        web.get('/admin', admin_dashboard),
        web.get('/api/conversations', get_conversations),
        web.get('/api/conversations/{chat_id}', get_conversation_history),
        web.get('/api/conversations/{chat_id}/control', get_control_status_handler),
        web.post('/api/conversations/{chat_id}/control', set_control_status_handler),
        web.post('/api/conversations/{chat_id}/reply', admin_reply_handler),
        web.get('/ws/all', global_websocket_handler),
    ])

    app.router.add_static('/static/', path=str(BASE_DIR / 'static'), name='static')

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, 'localhost', 8123)
    await site.start()

    logging.info("Server started, listening on http://localhost:8123")
    logging.info("Admin UI available at http://localhost:8123/admin")
    
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
