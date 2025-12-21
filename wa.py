import asyncio
import logging
import json
import os
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
async def generate_gemini_response(content: types.Content, chat_id: str, app: web.Application, user_message_dict: dict, chat_history: Optional[List[types.Content]] = None):
    """Generates a Gemini response and handles potential tool calls."""
    global db_pool
    try:
        contents = chat_history + [content] if chat_history else [content]
        
        # Initial generate_content call
        response = client.models.generate_content(
            model=config.GOOGLE_MODEL,
            contents=contents,
            config=GenerateContentConfig(
                temperature=1,
                max_output_tokens=6000,
                system_instruction=config.SYSTEM_PROMPT,
                tools=[tools.db_tool, tools.extra_tools],
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                safety_settings=[
                    types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_NONE'),
                    types.SafetySetting(category='HARM_CATEGORY_HARASSMENT', threshold='BLOCK_NONE'),
                ],
            ),
        )

        candidate = response.candidates[0]
        res_parts = candidate.content.parts

        # Save conversation turn to DB
        # If user_message_dict is empty (recursive call), we save the tool response as the 'user' part
        save_user_dict = user_message_dict if user_message_dict else content_to_dict(content)
        await database.save_chat_to_db(db_pool, chat_id, save_user_dict, candidate.content)
        
        # Broadcast the bot message to the UI
        bot_message_broadcast = {
            'type': 'new_message',
            'data': {
                'chat_id': chat_id,
                'message': {
                    'user': None,
                    'bot': content_to_dict(candidate.content)
                }
            }
        }
        for ws in app['websockets']:
            await ws.send_json(bot_message_broadcast)

        # Send text response to WhatsApp if any
        response_text = "".join(part.text + "\n" for part in res_parts if part.text)
        if response_text.strip():
            await whatsapp_service.send_whatsapp_message(chat_id, response_text.strip(), vars(config))
        
        # Handle Function Calls
        function_calls = [part.function_call for part in res_parts if part.function_call]
        if function_calls:
            function_responses = []
            for fc in function_calls:
                logging.info(f"Executing tool: {fc.name} with args: {fc.args}")
                fc_res_part = await tools.handle_tool_call(fc, db_pool, client)
                function_responses.append(fc_res_part)
            
            # Create tool content with responses
            tool_content = types.Content(role="tool", parts=function_responses)
            
            # Recursive call with updated history (current candidate content + tool response)
            # Empty user_message_dict to avoid double saving the original user message
            await generate_gemini_response(tool_content, chat_id, app, {}, chat_history=contents + [candidate.content])

    except Exception as e:
        logging.exception("Error in generate_gemini_response:")
        await whatsapp_service.send_whatsapp_message(chat_id, "Maaf, terjadi kesalahan saat memproses permintaan Anda.", vars(config))

async def handle_whatsapp_message(message_data: dict, app: web.Application):
    """Handles incoming WhatsApp messages based on control status."""
    global db_pool
    recipient_number = message_data['from']
    
    try:
        control_status = await database.get_control_status(db_pool, recipient_number)
        
        parts = []
        message_text = None
        local_uri_for_ui = None
        mime_type_for_ui = None
        filename_for_ui = None

        if message_data.get('type') == 'text':
            message_text = message_data.get('text', {}).get('body')
            if message_text and message_text.strip().lower() == 'clear':
                # 1. Get all media file URIs for this chat
                media_uris = await database.get_all_media_uris_for_chat(db_pool, recipient_number)
                
                # 2. Delete the chat history from the database
                await database.delete_chat_history_from_db(db_pool, recipient_number)
                
                # 3. Delete the actual media files
                for uri in media_uris:
                    try:
                        # Construct absolute path: BASE_DIR + /static/media/file.jpg -> BASE_DIR/static/media/file.jpg
                        file_path = BASE_DIR / uri.lstrip('/')
                        if os.path.exists(file_path):
                            os.remove(file_path)
                            logging.info(f"Deleted media file: {file_path}")
                        else:
                            logging.warning(f"Media file not found for deletion: {file_path}")
                    except Exception as e:
                        logging.error(f"Error deleting media file {uri}: {e}")

                await whatsapp_service.send_whatsapp_message(recipient_number, "Riwayat percakapan dan media Anda telah berhasil dihapus.", vars(config))
                return
            parts.append(types.Part.from_text(text=message_text))

        media_result = await whatsapp_service._process_media(message_data, client, vars(config))
        if media_result:
            google_uri, local_uri, mime_type, filename = media_result
            if google_uri and mime_type:
                local_uri_for_ui = local_uri
                mime_type_for_ui = mime_type
                filename_for_ui = filename
                media_type = message_data.get('type')
                caption = message_data.get(media_type, {}).get('caption')
                if caption:
                    parts.append(types.Part.from_text(text=caption))
                else:
                    parts.append(types.Part.from_text(text="perhatikan ini."))
                parts.append(types.Part.from_uri(file_uri=google_uri, mime_type=mime_type))
        
        if not parts:
            return

        content = types.Content(role="user", parts=parts)
        user_message_dict = content_to_dict(content)

        if local_uri_for_ui:
            user_message_dict['parts'].append({
                'local_media': {
                    'uri': local_uri_for_ui,
                    'mime_type': mime_type_for_ui,
                    'filename': filename_for_ui
                }
            })

        is_new_conversation = not await database.chat_exists(db_pool, recipient_number)

        message_to_broadcast = {
            'type': 'new_message',
            'data': {
                'chat_id': recipient_number,
                'message': {
                    'user': user_message_dict,
                    'bot': None
                }
            }
        }

        if control_status == 'admin':
            logging.info(f"Chat for {recipient_number} is admin-controlled. Storing message and notifying UI.")
            for ws in app['websockets']:
                await ws.send_json(message_to_broadcast)
            await database.save_user_message_only(db_pool, recipient_number, user_message_dict)
        elif control_status == 'bot':
            logging.info(f"Chat for {recipient_number} is bot-controlled. Notifying UI and generating AI response.")
            for ws in app['websockets']:
                await ws.send_json(message_to_broadcast)

            chat_history = await database.get_chat_history_from_db(db_pool, recipient_number)
            await generate_gemini_response(content, recipient_number, app, user_message_dict, chat_history)

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



async def generate_chat_summary(db_pool, chat_id, client):
    """Generates a summary of the chat using Gemini."""
    history = await database.get_chat_history_from_db(db_pool, chat_id)
    if not history:
        return "No chat history found."
    
    prompt = "Please summarize the following conversation between a user and an AI assistant. Focus on the user's main intent and the outcome."
    contents = [types.Content(role='user', parts=[types.Part.from_text(text=prompt)])] + history
    
    try:
        response = client.models.generate_content(
            model=config.GOOGLE_MODEL,
            contents=contents,
            config=GenerateContentConfig(temperature=0.5, max_output_tokens=1000)
        )
        return response.text
    except Exception as e:
        logging.error(f"Error generating summary: {e}")
        return "Error generating summary."

async def get_stats_handler(request):
    global db_pool
    try:
        chat_ids = await database.get_all_chat_ids(db_pool)
        active_chats = len(chat_ids)
        
        # Calculate uptime
        start_time = request.app.get('start_time')
        uptime_seconds = asyncio.get_event_loop().time() - start_time if start_time else 0
        
        # Format uptime
        days, remainder = divmod(uptime_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{int(days)}d {int(hours)}h {int(minutes)}m"

        return web.json_response({
            'active_chats': active_chats,
            'uptime': uptime_str,
            'model': config.GOOGLE_MODEL
        })
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

async def generate_summary_handler(request):
    global db_pool
    chat_id = request.match_info.get('chat_id')
    try:
         summary = await generate_chat_summary(db_pool, chat_id, client)
         return web.json_response({'summary': summary})
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

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
        web.get('/api/conversations/{chat_id}/summarize', generate_summary_handler),
        web.get('/api/stats', get_stats_handler),
        web.get('/ws/all', global_websocket_handler),
    ])

    app.router.add_static('/static/', path=str(BASE_DIR / 'static'), name='static')

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, 'localhost', 8123)
    await site.start()

    logging.info("Server started, listening on http://localhost:8123")
    logging.info("Admin UI available at http://localhost:8123/admin")
    
    app['start_time'] = asyncio.get_event_loop().time()

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
