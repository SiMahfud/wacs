import asyncio
import logging
import json
import os
import time
import csv
import io
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

# --- Rate Limiter ---
rate_limit_store = defaultdict(list)

def check_rate_limit(chat_id: str) -> bool:
    """Returns True if the user is rate-limited."""
    now = time.time()
    window = config.RATE_LIMIT_WINDOW
    max_requests = config.RATE_LIMIT_MAX
    
    # Clean old entries
    rate_limit_store[chat_id] = [t for t in rate_limit_store[chat_id] if now - t < window]
    
    if len(rate_limit_store[chat_id]) >= max_requests:
        return True
    
    rate_limit_store[chat_id].append(now)
    return False

# --- WebSocket Helper ---
async def broadcast_to_websockets(app, message: dict):
    """Safely broadcast message to all connected WebSocket clients."""
    ws_list = list(app.get('websockets', []))
    for ws in ws_list:
        try:
            if not ws.closed:
                await ws.send_json(message)
        except Exception as e:
            logging.warning(f"Error broadcasting to WebSocket: {e}")

# --- Auth Middleware ---
def check_auth(request) -> bool:
    """Check if the request has valid session auth."""
    session = request.get('session', {})
    return session.get('authenticated', False)

# --- Logika Inti Bot ---
async def generate_gemini_response(content: types.Content, chat_id: str, app: web.Application, user_message_dict: dict, chat_history: Optional[List[types.Content]] = None):
    """Generates a Gemini response and handles potential tool calls."""
    global db_pool
    wa_config = config.get_whatsapp_config()
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

        save_user_dict = user_message_dict if user_message_dict else content_to_dict(content)
        await database.save_chat_to_db(db_pool, chat_id, save_user_dict, candidate.content)
        
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
        await broadcast_to_websockets(app, bot_message_broadcast)

        response_text = "".join(part.text + "\n" for part in res_parts if part.text)
        if response_text.strip():
            await whatsapp_service.send_whatsapp_message(chat_id, response_text.strip(), wa_config)
        
        # Handle Function Calls
        function_calls = [part.function_call for part in res_parts if part.function_call]
        if function_calls:
            function_responses = []
            for fc in function_calls:
                logging.info(f"Executing tool: {fc.name} with args: {fc.args}")
                fc_res_part = await tools.handle_tool_call(fc, db_pool, client)
                function_responses.append(fc_res_part)
            
            tool_content = types.Content(role="tool", parts=function_responses)
            await generate_gemini_response(tool_content, chat_id, app, {}, chat_history=contents + [candidate.content])

    except Exception as e:
        logging.exception("Error in generate_gemini_response:")
        wa_config = config.get_whatsapp_config()
        await whatsapp_service.send_whatsapp_message(chat_id, "Maaf, terjadi kesalahan saat memproses permintaan Anda.", wa_config)

async def handle_whatsapp_message(message_data: dict, app: web.Application):
    """Handles incoming WhatsApp messages based on control status."""
    global db_pool
    recipient_number = message_data['from']
    wa_config = config.get_whatsapp_config()
    
    try:
        # Check rate limit
        if check_rate_limit(recipient_number):
            await whatsapp_service.send_whatsapp_message(
                recipient_number, 
                "⏳ Anda terlalu sering mengirim pesan. Silakan tunggu sebentar.", 
                wa_config
            )
            return

        control_status = await database.get_control_status(db_pool, recipient_number)
        
        parts = []
        message_text = None
        local_uri_for_ui = None
        mime_type_for_ui = None
        filename_for_ui = None

        if message_data.get('type') == 'text':
            message_text = message_data.get('text', {}).get('body')
            if message_text and message_text.strip().lower() == 'clear':
                media_uris = await database.get_all_media_uris_for_chat(db_pool, recipient_number)
                await database.delete_chat_history_from_db(db_pool, recipient_number)
                
                for uri in media_uris:
                    try:
                        file_path = BASE_DIR / uri.lstrip('/')
                        if os.path.exists(file_path):
                            os.remove(file_path)
                            logging.info(f"Deleted media file: {file_path}")
                    except Exception as e:
                        logging.error(f"Error deleting media file {uri}: {e}")

                await whatsapp_service.send_whatsapp_message(recipient_number, "Riwayat percakapan dan media Anda telah berhasil dihapus.", wa_config)
                return
            
            # Check auto-reply rules first
            if message_text:
                auto_reply = await database.check_auto_reply(db_pool, message_text)
                if auto_reply:
                    await whatsapp_service.send_whatsapp_message(recipient_number, auto_reply, wa_config)
                    # Save to history
                    user_dict = {"role": "user", "parts": [{"type": "text", "text": message_text}]}
                    bot_content = types.Content(role="model", parts=[types.Part.from_text(text=auto_reply)])
                    await database.save_chat_to_db(db_pool, recipient_number, user_dict, bot_content)
                    return
            
            parts.append(types.Part.from_text(text=message_text))

        media_result = await whatsapp_service._process_media(message_data, client, wa_config)
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
            await broadcast_to_websockets(app, message_to_broadcast)
            await database.save_user_message_only(db_pool, recipient_number, user_message_dict)
        elif control_status == 'bot':
            logging.info(f"Chat for {recipient_number} is bot-controlled. Notifying UI and generating AI response.")
            await broadcast_to_websockets(app, message_to_broadcast)

            chat_history = await database.get_chat_history_from_db(db_pool, recipient_number)
            await generate_gemini_response(content, recipient_number, app, user_message_dict, chat_history)

        if is_new_conversation:
            new_conversation_broadcast = {
                'type': 'new_conversation',
                'data': {
                    'chat_id': recipient_number
                }
            }
            await broadcast_to_websockets(app, new_conversation_broadcast)

    except Exception as e:
        logging.exception("Error processing message:")
        await whatsapp_service.send_whatsapp_message(recipient_number, "Maaf, terjadi kesalahan.", wa_config)

# --- WhatsApp Webhook ---
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

# --- Admin Pages ---
async def admin_login_page(request):
    """Serve the login page."""
    login_path = TEMPLATES_DIR / 'login.html'
    try:
        with open(login_path, 'r', encoding='utf-8') as f:
            return web.Response(text=f.read(), content_type='text/html')
    except FileNotFoundError:
        return web.Response(text="Login page not found.", status=404)

async def admin_login_handler(request):
    """Handle login POST request."""
    data = await request.json()
    username = data.get('username')
    password = data.get('password')
    
    if username == config.ADMIN_USERNAME and password == config.ADMIN_PASSWORD:
        # Set cookie-based auth
        response = web.json_response({'success': True})
        response.set_cookie('admin_auth', 'authenticated', max_age=86400, httponly=True)
        return response
    else:
        return web.json_response({'success': False, 'error': 'Invalid credentials'}, status=401)

async def admin_logout_handler(request):
    """Handle logout."""
    response = web.json_response({'success': True})
    response.del_cookie('admin_auth')
    return response

def require_auth(handler):
    """Decorator to require authentication for admin endpoints."""
    async def wrapper(request):
        auth_cookie = request.cookies.get('admin_auth')
        if auth_cookie != 'authenticated':
            return web.json_response({'error': 'Unauthorized'}, status=401)
        return await handler(request)
    return wrapper

async def admin_dashboard(request):
    """Serve admin dashboard (requires auth cookie)."""
    auth_cookie = request.cookies.get('admin_auth')
    if auth_cookie != 'authenticated':
        # Redirect to login
        raise web.HTTPFound('/admin/login')
    
    index_path = TEMPLATES_DIR / 'index.html'
    try:
        with open(index_path, 'r', encoding='utf-8') as f:
            return web.Response(text=f.read(), content_type='text/html')
    except FileNotFoundError:
        return web.Response(text="Admin page not found.", status=404)

# --- API Handlers ---
@require_auth
async def get_conversations(request):
    global db_pool
    try:
        chat_ids = await database.get_all_chat_ids(db_pool)
        # Get labels for each chat
        result = []
        for cid in chat_ids:
            label = await database.get_chat_label(db_pool, cid)
            result.append({'id': cid, 'label': label})
        return web.json_response(result)
    except database.DatabaseError as e:
        return web.json_response({'error': str(e)}, status=500)

@require_auth
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

@require_auth
async def get_control_status_handler(request):
    chat_id = request.match_info.get('chat_id')
    status = await database.get_control_status(db_pool, chat_id)
    return web.json_response({'controlled_by': status})

@require_auth
async def set_control_status_handler(request):
    chat_id = request.match_info.get('chat_id')
    data = await request.json()
    new_status = data.get('status')
    if new_status not in ['bot', 'admin']:
        return web.json_response({'error': 'Invalid status'}, status=400)
    
    await database.set_control_status(db_pool, chat_id, new_status)
    return web.json_response({'success': True, 'new_status': new_status})

@require_auth
async def admin_reply_handler(request):
    chat_id = request.match_info.get('chat_id')
    data = await request.json()
    text = data.get('text')
    if not text:
        return web.json_response({'error': 'Text is required'}, status=400)

    wa_config = config.get_whatsapp_config()
    try:
        await whatsapp_service.send_whatsapp_message(chat_id, text, wa_config)
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
        await broadcast_to_websockets(request.app, message_to_broadcast)
            
        return web.json_response({'success': True})
    except Exception as e:
        logging.error(f"Error sending admin reply: {e}")
        return web.json_response({'error': 'Failed to send message'}, status=500)

@require_auth
async def delete_conversation_handler(request):
    """Delete a conversation and its media."""
    global db_pool
    chat_id = request.match_info.get('chat_id')
    try:
        media_uris = await database.get_all_media_uris_for_chat(db_pool, chat_id)
        for uri in media_uris:
            try:
                file_path = BASE_DIR / uri.lstrip('/')
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                logging.error(f"Error deleting media file {uri}: {e}")
        
        await database.delete_conversation(db_pool, chat_id)
        
        await broadcast_to_websockets(request.app, {
            'type': 'conversation_deleted',
            'data': {'chat_id': chat_id}
        })
        
        return web.json_response({'success': True})
    except database.DatabaseError as e:
        return web.json_response({'error': str(e)}, status=500)

# --- Search ---
@require_auth
async def search_messages_handler(request):
    global db_pool
    chat_id = request.match_info.get('chat_id')
    query = request.query.get('q', '')
    if not query:
        return web.json_response({'error': 'Search query is required'}, status=400)
    try:
        results = await database.search_chat_messages(db_pool, chat_id, query)
        return web.json_response(results)
    except database.DatabaseError as e:
        return web.json_response({'error': str(e)}, status=500)

# --- Labels ---
@require_auth
async def set_label_handler(request):
    global db_pool
    chat_id = request.match_info.get('chat_id')
    data = await request.json()
    label = data.get('label', '')
    try:
        await database.set_chat_label(db_pool, chat_id, label)
        return web.json_response({'success': True, 'label': label})
    except database.DatabaseError as e:
        return web.json_response({'error': str(e)}, status=500)

# --- WebSocket ---
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
        if ws in request.app['websockets']:
            request.app['websockets'].remove(ws)
        logging.info("Global WebSocket connection closed.")

    return ws

# --- Chat Summary ---
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

@require_auth
async def get_stats_handler(request):
    global db_pool
    try:
        chat_ids = await database.get_all_chat_ids(db_pool)
        active_chats = len(chat_ids)
        
        start_time = request.app.get('start_time')
        uptime_seconds = time.time() - start_time if start_time else 0
        
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

@require_auth
async def generate_summary_handler(request):
    global db_pool
    chat_id = request.match_info.get('chat_id')
    try:
         summary = await generate_chat_summary(db_pool, chat_id, client)
         return web.json_response({'summary': summary})
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

# --- Analytics ---
@require_auth
async def get_analytics_handler(request):
    global db_pool
    try:
        data = await database.get_analytics_data(db_pool)
        return web.json_response(data)
    except database.DatabaseError as e:
        return web.json_response({'error': str(e)}, status=500)

# --- Broadcast ---
@require_auth
async def broadcast_handler(request):
    global db_pool
    data = await request.json()
    message = data.get('message')
    if not message:
        return web.json_response({'error': 'Message is required'}, status=400)
    
    wa_config = config.get_whatsapp_config()
    try:
        chat_ids = await database.get_all_chat_ids(db_pool)
        sent = 0
        for cid in chat_ids:
            try:
                await whatsapp_service.send_whatsapp_message(cid, message, wa_config)
                sent += 1
                await asyncio.sleep(0.5)  # Rate limit between sends
            except Exception as e:
                logging.error(f"Error broadcasting to {cid}: {e}")
        
        await database.save_broadcast_log(db_pool, message, sent, 'sent')
        return web.json_response({'success': True, 'sent_to': sent, 'total': len(chat_ids)})
    except Exception as e:
        return web.json_response({'error': str(e)}, status=500)

# --- Export Chat ---
@require_auth
async def export_chat_handler(request):
    global db_pool
    chat_id = request.match_info.get('chat_id')
    export_format = request.query.get('format', 'csv')
    
    try:
        history = await database.get_chat_history_for_admin(db_pool, chat_id)
        if not history:
            return web.json_response({'error': 'No history found'}, status=404)
        
        if export_format == 'csv':
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(['Timestamp', 'Role', 'Message'])
            
            for item in history:
                timestamp = item.get('timestamp', '')
                if item.get('user') and item['user'].get('parts'):
                    for part in item['user']['parts']:
                        if part.get('text'):
                            writer.writerow([timestamp, 'User', part['text']])
                if item.get('bot') and item['bot'].get('parts'):
                    for part in item['bot']['parts']:
                        if part.get('text'):
                            role = 'Admin' if item['bot'].get('role') == 'admin' else 'Bot'
                            writer.writerow([timestamp, role, part['text']])
            
            csv_content = output.getvalue()
            return web.Response(
                text=csv_content,
                content_type='text/csv',
                headers={'Content-Disposition': f'attachment; filename="chat_{chat_id}.csv"'}
            )
        else:
            # JSON export
            return web.json_response(history, headers={
                'Content-Disposition': f'attachment; filename="chat_{chat_id}.json"'
            })
    except database.DatabaseError as e:
        return web.json_response({'error': str(e)}, status=500)

# --- Templates CRUD ---
@require_auth
async def get_templates_handler(request):
    global db_pool
    try:
        templates = await database.get_message_templates(db_pool)
        return web.json_response(templates)
    except database.DatabaseError as e:
        return web.json_response({'error': str(e)}, status=500)

@require_auth
async def create_template_handler(request):
    global db_pool
    data = await request.json()
    name = data.get('name')
    content = data.get('content')
    if not name or not content:
        return web.json_response({'error': 'Name and content are required'}, status=400)
    try:
        template_id = await database.save_message_template(db_pool, name, content)
        return web.json_response({'success': True, 'id': template_id})
    except database.DatabaseError as e:
        return web.json_response({'error': str(e)}, status=500)

@require_auth
async def delete_template_handler(request):
    global db_pool
    template_id = request.match_info.get('template_id')
    try:
        await database.delete_message_template(db_pool, int(template_id))
        return web.json_response({'success': True})
    except database.DatabaseError as e:
        return web.json_response({'error': str(e)}, status=500)

# --- Auto-Reply CRUD ---
@require_auth
async def get_auto_replies_handler(request):
    global db_pool
    try:
        rules = await database.get_auto_reply_rules(db_pool)
        return web.json_response(rules)
    except database.DatabaseError as e:
        return web.json_response({'error': str(e)}, status=500)

@require_auth
async def create_auto_reply_handler(request):
    global db_pool
    data = await request.json()
    keyword = data.get('keyword')
    response_text = data.get('response')
    if not keyword or not response_text:
        return web.json_response({'error': 'Keyword and response are required'}, status=400)
    try:
        rule_id = await database.save_auto_reply_rule(db_pool, keyword, response_text)
        return web.json_response({'success': True, 'id': rule_id})
    except database.DatabaseError as e:
        return web.json_response({'error': str(e)}, status=500)

@require_auth
async def delete_auto_reply_handler(request):
    global db_pool
    rule_id = request.match_info.get('rule_id')
    try:
        await database.delete_auto_reply_rule(db_pool, int(rule_id))
        return web.json_response({'success': True})
    except database.DatabaseError as e:
        return web.json_response({'error': str(e)}, status=500)

# --- Main Application ---
async def main():
    global db_pool
    db_pool = await aiomysql.create_pool(
        host=config.MYSQL_HOST, user=config.MYSQL_USER, password=config.MYSQL_PASSWORD,
        db=config.MYSQL_DATABASE, autocommit=True
    )

    # Run database migrations
    await database.run_migrations(db_pool)
    
    app = web.Application()
    app['websockets'] = []

    app.add_routes([
        # WhatsApp Webhook
        web.get('/whatsapp/webhook', whatsapp_webhook_handler),
        web.post('/whatsapp/webhook', whatsapp_webhook_handler),
        
        # Admin Auth
        web.get('/admin/login', admin_login_page),
        web.post('/admin/login', admin_login_handler),
        web.post('/admin/logout', admin_logout_handler),
        web.get('/admin', admin_dashboard),
        
        # Conversations API
        web.get('/api/conversations', get_conversations),
        web.get('/api/conversations/{chat_id}', get_conversation_history),
        web.delete('/api/conversations/{chat_id}', delete_conversation_handler),
        web.get('/api/conversations/{chat_id}/control', get_control_status_handler),
        web.post('/api/conversations/{chat_id}/control', set_control_status_handler),
        web.post('/api/conversations/{chat_id}/reply', admin_reply_handler),
        web.get('/api/conversations/{chat_id}/summarize', generate_summary_handler),
        web.get('/api/conversations/{chat_id}/search', search_messages_handler),
        web.post('/api/conversations/{chat_id}/label', set_label_handler),
        web.get('/api/conversations/{chat_id}/export', export_chat_handler),
        
        # Stats & Analytics
        web.get('/api/stats', get_stats_handler),
        web.get('/api/analytics', get_analytics_handler),
        
        # Broadcast
        web.post('/api/broadcast', broadcast_handler),
        
        # Templates
        web.get('/api/templates', get_templates_handler),
        web.post('/api/templates', create_template_handler),
        web.delete('/api/templates/{template_id}', delete_template_handler),
        
        # Auto-Reply
        web.get('/api/auto-replies', get_auto_replies_handler),
        web.post('/api/auto-replies', create_auto_reply_handler),
        web.delete('/api/auto-replies/{rule_id}', delete_auto_reply_handler),
        
        # WebSocket
        web.get('/ws/all', global_websocket_handler),
    ])

    app.router.add_static('/static/', path=str(BASE_DIR / 'static'), name='static')

    app['start_time'] = time.time()

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, 'localhost', 8123)
    await site.start()

    logging.info("Server started, listening on http://localhost:8123")
    logging.info("Admin UI available at http://localhost:8123/admin")
    logging.info("Login page at http://localhost:8123/admin/login")

    try:
       while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logging.info("Server is shutting down.")
    finally:
        # Graceful shutdown
        logging.info("Cleaning up resources...")
        
        # Close all websockets
        ws_list = list(app.get('websockets', []))
        for ws in ws_list:
            try:
                await ws.close()
            except Exception:
                pass
        
        await runner.cleanup()
        if db_pool:
            db_pool.close()
            await db_pool.wait_closed()
        logging.info("Shutdown complete.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Process interrupted by user.")
