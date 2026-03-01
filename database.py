import logging
import json
import aiomysql
from typing import Optional, List, Tuple, Dict
from google.genai import types

from utils import content_to_dict, _create_parts_from_dict

# Custom Exception for Database
class DatabaseError(Exception):
    pass

# --- Schema Migration ---
async def run_migrations(db_pool):
    """Runs database schema migrations on startup."""
    migrations = [
        # Add created_at to chat_history (1060 = duplicate column, silently ignored)
        """ALTER TABLE chat_history ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP""",
        # Add label to conversation_control
        """ALTER TABLE conversation_control ADD COLUMN label VARCHAR(50) DEFAULT NULL""",
        # Audit log table
        """CREATE TABLE IF NOT EXISTS audit_log (
            id INT AUTO_INCREMENT PRIMARY KEY,
            table_name VARCHAR(50) NOT NULL,
            action VARCHAR(20) NOT NULL,
            chat_id VARCHAR(50),
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
        # Auto-reply rules
        """CREATE TABLE IF NOT EXISTS auto_reply_rules (
            id INT AUTO_INCREMENT PRIMARY KEY,
            keyword VARCHAR(255) NOT NULL,
            response TEXT NOT NULL,
            is_active TINYINT(1) DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
        # Message templates
        """CREATE TABLE IF NOT EXISTS message_templates (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
        # Broadcast log
        """CREATE TABLE IF NOT EXISTS broadcast_log (
            id INT AUTO_INCREMENT PRIMARY KEY,
            message TEXT NOT NULL,
            recipients_count INT DEFAULT 0,
            status VARCHAR(20) DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
        # AI settings table
        """CREATE TABLE IF NOT EXISTS ai_settings (
            id INT AUTO_INCREMENT PRIMARY KEY,
            provider VARCHAR(50) NOT NULL DEFAULT 'gemini',
            model_name VARCHAR(100) DEFAULT NULL,
            api_key VARCHAR(255) DEFAULT NULL,
            system_prompt TEXT DEFAULT NULL,
            is_active TINYINT(1) DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
        # Default Gemini setting
        """INSERT IGNORE INTO ai_settings (provider, model_name, is_active) VALUES ('gemini', 'gemini-1.5-flash', 1)""",
    ]
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                for sql in migrations:
                    try:
                        await cursor.execute(sql)
                    except aiomysql.Error as e:
                        # Ignore "duplicate column" errors from ALTER TABLE
                        if e.args[0] != 1060:
                            logging.warning(f"Migration warning: {e}")
                await conn.commit()
        logging.info("Database migrations completed successfully.")
    except Exception as e:
        logging.error(f"Error running migrations: {e}")

# --- Core Query Execution ---
async def execute_sql_query(db_pool, sql_query: str, params: Optional[tuple] = None) -> Optional[List[Tuple]]:
    """Fungsi untuk mengeksekusi query SQL ke database."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                if params:
                    await cursor.execute(sql_query, params)
                else:
                    await cursor.execute(sql_query)
                
                if sql_query.strip().upper().startswith("SELECT"):
                    result = await cursor.fetchall()
                else:
                    await conn.commit()
                    result = [("Berhasil", f"Query berhasil dieksekusi, affected {cursor.rowcount} rows")]
                return result
    except aiomysql.Error as err:
        logging.error(f"Error executing SQL query: {err}")
        raise DatabaseError(f"Error executing SQL query: {err}")
    except Exception as e:
        logging.exception(f"An unexpected error occurred: {e}")
        raise DatabaseError(f"An unexpected error occurred: {e}")

# --- Chat History ---
async def save_chat_to_db(db_pool, chat_id: str, user_dict: Dict, bot_content: types.Content):
    """Fungsi untuk menyimpan chat ke database menggunakan dictionary untuk user."""
    try:
       user_json = json.dumps(user_dict)
       bot_json = json.dumps(content_to_dict(bot_content))

       async with db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                query = "INSERT INTO chat_history (chat_id, user, bot) VALUES (%s, %s, %s)"
                await cursor.execute(query, (chat_id, user_json, bot_json))
                await conn.commit()

    except aiomysql.Error as err:
        logging.error(f"Error saving chat to database: {err}")
        raise DatabaseError(f"Error saving chat to database: {err}")
    except Exception as e:
        logging.exception(f"An unexpected error occurred: {e}")
        raise DatabaseError(f"An unexpected error occurred: {e}")

async def get_chat_history_from_db(db_pool, chat_id: str) -> Optional[List[types.Content]]:
    """Fungsi untuk mengambil riwayat chat dari database."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                query = "SELECT user, bot FROM chat_history WHERE chat_id = %s ORDER BY id ASC"
                await cursor.execute(query, (chat_id,))
                results = await cursor.fetchall()

        if not results:
            return None
        
        contents = []
        for row in results:
            if not row['user'] or not row['bot']:
                continue
            user_content = json.loads(row['user'])
            bot_content = json.loads(row['bot'])

            user_parts = _create_parts_from_dict(user_content.get('parts', []))
            bot_parts = _create_parts_from_dict(bot_content.get('parts', []))
            
            contents.append(types.Content(role=user_content.get('role', 'user'), parts=user_parts))
            contents.append(types.Content(role=bot_content.get('role', 'model'), parts=bot_parts))
        return contents
    except aiomysql.Error as err:
        logging.error(f"Error retrieving chat history from database: {err}")
        raise DatabaseError(f"Error retrieving chat history from database: {err}")
    except Exception as e:
        logging.exception(f"An unexpected error occurred: {e}")
        raise DatabaseError(f"An unexpected error occurred: {e}")

async def get_chat_history_paginated(db_pool, chat_id: str, limit: int = 50, offset: int = 0) -> Optional[List[dict]]:
    """Mengambil riwayat chat dengan pagination untuk admin UI."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                count_query = "SELECT COUNT(*) as total FROM chat_history WHERE chat_id = %s"
                await cursor.execute(count_query, (chat_id,))
                count_result = await cursor.fetchone()
                total = count_result['total'] if count_result else 0

                query = "SELECT user, bot, created_at FROM chat_history WHERE chat_id = %s ORDER BY id ASC LIMIT %s OFFSET %s"
                await cursor.execute(query, (chat_id, limit, offset))
                results = await cursor.fetchall()

        if not results:
            return {'messages': [], 'total': total, 'limit': limit, 'offset': offset}
        
        history = []
        for row in results:
            created_at = row.get('created_at')
            history.append({
                'user': json.loads(row['user']) if row['user'] else None,
                'bot': json.loads(row['bot']) if row['bot'] else None,
                'timestamp': created_at.isoformat() if created_at else None
            })
        return {'messages': history, 'total': total, 'limit': limit, 'offset': offset}
    except aiomysql.Error as err:
        logging.error(f"Error retrieving paginated chat history: {err}")
        raise DatabaseError(f"Error retrieving paginated chat history: {err}")

async def delete_chat_history_from_db(db_pool, chat_id: str):
    """Fungsi untuk menghapus semua riwayat chat untuk chat_id tertentu."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                query = "DELETE FROM chat_history WHERE chat_id = %s"
                await cursor.execute(query, (chat_id,))
                await conn.commit()
                logging.info(f"Chat history for {chat_id} has been deleted.")
    except aiomysql.Error as err:
        logging.error(f"Error deleting chat history from database: {err}")
        raise DatabaseError(f"Error deleting chat history from database: {err}")
    except Exception as e:
        logging.exception(f"An unexpected error occurred while deleting chat history: {e}")
        raise DatabaseError(f"An unexpected error occurred while deleting chat history: {e}")

async def get_all_media_uris_for_chat(db_pool, chat_id: str) -> List[str]:
    """Fetches all local media URIs for a given chat_id before deletion."""
    uris = []
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                query = "SELECT user FROM chat_history WHERE chat_id = %s"
                await cursor.execute(query, (chat_id,))
                results = await cursor.fetchall()
        
        for row in results:
            if not row['user']:
                continue
            try:
                user_message = json.loads(row['user'])
                for part in user_message.get('parts', []):
                    if 'local_media' in part and 'uri' in part['local_media']:
                        uris.append(part['local_media']['uri'])
            except (json.JSONDecodeError, KeyError) as e:
                logging.warning(f"Could not parse media URI from user message: {e}")
        return uris
    except aiomysql.Error as err:
        logging.error(f"Error fetching media URIs for chat: {err}")
        raise DatabaseError(f"Error fetching media URIs for chat: {err}")

async def get_all_chat_ids(db_pool) -> Optional[List[str]]:
    """Fungsi untuk mengambil semua chat_id unik dari database."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                query = """
                    SELECT chat_id 
                    FROM chat_history 
                    GROUP BY chat_id 
                    ORDER BY MAX(created_at) DESC
                """
                await cursor.execute(query)
                results = await cursor.fetchall()
        return [row[0] for row in results] if results else []
    except aiomysql.Error as err:
        logging.error(f"Error retrieving all chat IDs: {err}")
        raise DatabaseError(f"Error retrieving all chat IDs: {err}")

async def get_chat_history_for_admin(db_pool, chat_id: str) -> Optional[List[dict]]:
    """Fungsi untuk mengambil riwayat chat dari database untuk admin UI."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                query = "SELECT user, bot, created_at FROM chat_history WHERE chat_id = %s ORDER BY id ASC"
                await cursor.execute(query, (chat_id,))
                results = await cursor.fetchall()

        if not results:
            return None
        
        history = []
        for row in results:
            created_at = row.get('created_at')
            history.append({
                'user': json.loads(row['user']) if row['user'] else None,
                'bot': json.loads(row['bot']) if row['bot'] else None,
                'timestamp': created_at.isoformat() if created_at else None
            })
        return history
    except aiomysql.Error as err:
        logging.error(f"Error retrieving chat history for admin: {err}")
        raise DatabaseError(f"Error retrieving chat history for admin: {err}")

# --- Conversation Control ---
async def get_control_status(db_pool, chat_id: str) -> str:
    """Mendapatkan status kendali untuk sebuah chat_id."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                query = "SELECT controlled_by FROM conversation_control WHERE chat_id = %s"
                await cursor.execute(query, (chat_id,))
                result = await cursor.fetchone()
        return result[0] if result else 'bot'
    except aiomysql.Error as err:
        logging.error(f"Error getting control status: {err}")
        raise DatabaseError(f"Error getting control status: {err}")

async def set_control_status(db_pool, chat_id: str, status: str):
    """Mengatur status kendali (bot/admin) untuk sebuah chat_id."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                query = "INSERT INTO conversation_control (chat_id, controlled_by) VALUES (%s, %s) ON DUPLICATE KEY UPDATE controlled_by = VALUES(controlled_by)"
                await cursor.execute(query, (chat_id, status))
                await conn.commit()
    except aiomysql.Error as err:
        logging.error(f"Error setting control status: {err}")
        raise DatabaseError(f"Error setting control status: {err}")

# --- Chat Labels ---
async def set_chat_label(db_pool, chat_id: str, label: str):
    """Set label for a conversation."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                query = "INSERT INTO conversation_control (chat_id, controlled_by, label) VALUES (%s, 'bot', %s) ON DUPLICATE KEY UPDATE label = VALUES(label)"
                await cursor.execute(query, (chat_id, label))
                await conn.commit()
    except aiomysql.Error as err:
        logging.error(f"Error setting chat label: {err}")
        raise DatabaseError(f"Error setting chat label: {err}")

async def get_chat_label(db_pool, chat_id: str) -> Optional[str]:
    """Get label for a conversation."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                query = "SELECT label FROM conversation_control WHERE chat_id = %s"
                await cursor.execute(query, (chat_id,))
                result = await cursor.fetchone()
        return result[0] if result else None
    except aiomysql.Error as err:
        logging.error(f"Error getting chat label: {err}")
        raise DatabaseError(f"Error getting chat label: {err}")

# --- Admin Messages ---
async def save_admin_reply(db_pool, chat_id: str, admin_text: str):
    """Menyimpan balasan dari admin ke chat history."""
    try:
        admin_reply_content = types.Content(role="model", parts=[types.Part.from_text(text=admin_text)])
        bot_json = json.dumps(content_to_dict(admin_reply_content))

        async with db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                query = "INSERT INTO chat_history (chat_id, user, bot) VALUES (%s, NULL, %s)"
                await cursor.execute(query, (chat_id, bot_json))
                await conn.commit()
    except aiomysql.Error as err:
        logging.error(f"Error saving admin reply: {err}")
        raise DatabaseError(f"Error saving admin reply: {err}")

async def save_user_message_only(db_pool, chat_id: str, user_message_dict: Dict):
    """Menyimpan pesan dari user saja (dalam bentuk dict), saat admin sedang mengontrol."""
    try:
        user_json = json.dumps(user_message_dict)
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                query = "INSERT INTO chat_history (chat_id, user, bot) VALUES (%s, %s, NULL)"
                await cursor.execute(query, (chat_id, user_json))
                await conn.commit()
    except aiomysql.Error as err:
        logging.error(f"Error saving user-only message: {err}")
        raise DatabaseError(f"Error saving user-only message: {err}")

async def chat_exists(db_pool, chat_id: str) -> bool:
    """Checks if a chat with the given chat_id already exists in the database."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                query = "SELECT 1 FROM chat_history WHERE chat_id = %s LIMIT 1"
                await cursor.execute(query, (chat_id,))
                result = await cursor.fetchone()
        return result is not None
    except aiomysql.Error as err:
        logging.error(f"Error checking if chat exists: {err}")
        raise DatabaseError(f"Error checking if chat exists: {err}")

# --- Audit Logging ---
async def save_audit_log(db_pool, table_name: str, action: str, chat_id: str = None, details: str = None):
    """Save an audit log entry for database modifications."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                query = "INSERT INTO audit_log (table_name, action, chat_id, details) VALUES (%s, %s, %s, %s)"
                await cursor.execute(query, (table_name, action, chat_id, details))
                await conn.commit()
    except aiomysql.Error as err:
        logging.warning(f"Error saving audit log: {err}")

# --- Search ---
async def search_chat_messages(db_pool, chat_id: str, search_query: str) -> List[dict]:
    """Search for messages containing a specific text in a conversation."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                query = """SELECT user, bot, created_at FROM chat_history 
                          WHERE chat_id = %s AND (user LIKE %s OR bot LIKE %s) 
                          ORDER BY id ASC"""
                search_param = f"%{search_query}%"
                await cursor.execute(query, (chat_id, search_param, search_param))
                results = await cursor.fetchall()
        
        matches = []
        for row in results:
            created_at = row.get('created_at')
            matches.append({
                'user': json.loads(row['user']) if row['user'] else None,
                'bot': json.loads(row['bot']) if row['bot'] else None,
                'timestamp': created_at.isoformat() if created_at else None
            })
        return matches
    except aiomysql.Error as err:
        logging.error(f"Error searching chat messages: {err}")
        raise DatabaseError(f"Error searching chat messages: {err}")

# --- Auto-Reply Rules ---
async def get_auto_reply_rules(db_pool) -> List[dict]:
    """Get all auto-reply rules."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("SELECT * FROM auto_reply_rules ORDER BY id ASC")
                results = await cursor.fetchall()
        rules = []
        for row in results:
            created_at = row.get('created_at')
            rules.append({
                'id': row['id'],
                'keyword': row['keyword'],
                'response': row['response'],
                'is_active': bool(row['is_active']),
                'created_at': created_at.isoformat() if created_at else None
            })
        return rules
    except aiomysql.Error as err:
        logging.error(f"Error getting auto-reply rules: {err}")
        raise DatabaseError(f"Error getting auto-reply rules: {err}")

async def save_auto_reply_rule(db_pool, keyword: str, response: str) -> int:
    """Save a new auto-reply rule. Returns the new rule ID."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                query = "INSERT INTO auto_reply_rules (keyword, response) VALUES (%s, %s)"
                await cursor.execute(query, (keyword, response))
                await conn.commit()
                return cursor.lastrowid
    except aiomysql.Error as err:
        logging.error(f"Error saving auto-reply rule: {err}")
        raise DatabaseError(f"Error saving auto-reply rule: {err}")

async def delete_auto_reply_rule(db_pool, rule_id: int):
    """Delete an auto-reply rule."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("DELETE FROM auto_reply_rules WHERE id = %s", (rule_id,))
                await conn.commit()
    except aiomysql.Error as err:
        logging.error(f"Error deleting auto-reply rule: {err}")
        raise DatabaseError(f"Error deleting auto-reply rule: {err}")

async def check_auto_reply(db_pool, message_text: str) -> Optional[str]:
    """Check if a message matches any active auto-reply rule. Returns response or None."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("SELECT keyword, response FROM auto_reply_rules WHERE is_active = 1")
                rules = await cursor.fetchall()
        
        if not rules:
            return None
        
        message_lower = message_text.lower()
        for rule in rules:
            if rule['keyword'].lower() in message_lower:
                return rule['response']
        return None
    except aiomysql.Error as err:
        logging.error(f"Error checking auto-reply: {err}")
        return None

# --- Message Templates ---
async def get_message_templates(db_pool) -> List[dict]:
    """Get all message templates."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("SELECT * FROM message_templates ORDER BY id ASC")
                results = await cursor.fetchall()
        templates = []
        for row in results:
            created_at = row.get('created_at')
            templates.append({
                'id': row['id'],
                'name': row['name'],
                'content': row['content'],
                'created_at': created_at.isoformat() if created_at else None
            })
        return templates
    except aiomysql.Error as err:
        logging.error(f"Error getting message templates: {err}")
        raise DatabaseError(f"Error getting message templates: {err}")

async def save_message_template(db_pool, name: str, content: str) -> int:
    """Save a new message template. Returns the new template ID."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                query = "INSERT INTO message_templates (name, content) VALUES (%s, %s)"
                await cursor.execute(query, (name, content))
                await conn.commit()
                return cursor.lastrowid
    except aiomysql.Error as err:
        logging.error(f"Error saving message template: {err}")
        raise DatabaseError(f"Error saving message template: {err}")

async def delete_message_template(db_pool, template_id: int):
    """Delete a message template."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("DELETE FROM message_templates WHERE id = %s", (template_id,))
                await conn.commit()
    except aiomysql.Error as err:
        logging.error(f"Error deleting message template: {err}")
        raise DatabaseError(f"Error deleting message template: {err}")

# --- Analytics ---
async def get_analytics_data(db_pool) -> dict:
    """Get analytics data for the dashboard."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                # Total messages
                await cursor.execute("SELECT COUNT(*) as total FROM chat_history")
                total_result = await cursor.fetchone()
                total_messages = total_result['total'] if total_result else 0

                # Total unique chats
                await cursor.execute("SELECT COUNT(DISTINCT chat_id) as total FROM chat_history")
                chats_result = await cursor.fetchone()
                total_chats = chats_result['total'] if chats_result else 0

                # Messages per day (last 7 days)
                await cursor.execute("""
                    SELECT DATE(created_at) as date, COUNT(*) as count 
                    FROM chat_history 
                    WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                    GROUP BY DATE(created_at) 
                    ORDER BY date ASC
                """)
                daily_results = await cursor.fetchall()
                daily_messages = [
                    {'date': row['date'].isoformat() if row['date'] else None, 'count': row['count']}
                    for row in daily_results
                ]

                # Top 5 most active chats
                await cursor.execute("""
                    SELECT chat_id, COUNT(*) as message_count 
                    FROM chat_history 
                    GROUP BY chat_id 
                    ORDER BY message_count DESC 
                    LIMIT 5
                """)
                top_chats = await cursor.fetchall()

        return {
            'total_messages': total_messages,
            'total_chats': total_chats,
            'daily_messages': daily_messages,
            'top_chats': [{'chat_id': r['chat_id'], 'count': r['message_count']} for r in top_chats]
        }
    except aiomysql.Error as err:
        logging.error(f"Error getting analytics data: {err}")
        raise DatabaseError(f"Error getting analytics data: {err}")

# --- Broadcast ---
async def save_broadcast_log(db_pool, message: str, recipients_count: int, status: str = 'sent'):
    """Save a broadcast log entry."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                query = "INSERT INTO broadcast_log (message, recipients_count, status) VALUES (%s, %s, %s)"
                await cursor.execute(query, (message, recipients_count, status))
                await conn.commit()
    except aiomysql.Error as err:
        logging.error(f"Error saving broadcast log: {err}")
        raise DatabaseError(f"Error saving broadcast log: {err}")

# --- Delete Conversation ---
async def delete_conversation(db_pool, chat_id: str):
    """Delete all data for a conversation (history + control)."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("DELETE FROM chat_history WHERE chat_id = %s", (chat_id,))
                await cursor.execute("DELETE FROM conversation_control WHERE chat_id = %s", (chat_id,))
                await conn.commit()
                logging.info(f"Conversation {chat_id} fully deleted.")
    except aiomysql.Error as err:
        logging.error(f"Error deleting conversation: {err}")
        raise DatabaseError(f"Error deleting conversation: {err}")

# --- AI Settings ---
async def get_ai_settings(db_pool) -> List[dict]:
    """Get all AI configured providers and their settings."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("SELECT * FROM ai_settings ORDER BY id ASC")
                return await cursor.fetchall()
    except aiomysql.Error as err:
        logging.error(f"Error getting AI settings: {err}")
        raise DatabaseError(f"Error getting AI settings: {err}")

async def get_active_ai_setting(db_pool) -> Optional[dict]:
    """Get the currently active AI provider setting."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cursor:
                await cursor.execute("SELECT * FROM ai_settings WHERE is_active = 1 LIMIT 1")
                return await cursor.fetchone()
    except aiomysql.Error as err:
        logging.error(f"Error getting active AI setting: {err}")
        raise DatabaseError(f"Error getting active AI setting: {err}")

async def save_ai_setting(db_pool, provider: str, model_name: str, api_key: str = None, system_prompt: str = None, is_active: bool = False, setting_id: int = None):
    """Save or update an AI provider setting."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                if is_active:
                    # Deactivate others if this one is active
                    await cursor.execute("UPDATE ai_settings SET is_active = 0")
                
                if setting_id:
                    # Update existing
                    query = """
                        UPDATE ai_settings 
                        SET provider = %s, model_name = %s, api_key = COALESCE(%s, api_key), 
                            system_prompt = %s, is_active = %s
                        WHERE id = %s
                    """
                    await cursor.execute(query, (provider, model_name, api_key, system_prompt, 1 if is_active else 0, setting_id))
                else:
                    # Insert new
                    query = """
                        INSERT INTO ai_settings (provider, model_name, api_key, system_prompt, is_active)
                        VALUES (%s, %s, %s, %s, %s)
                    """
                    await cursor.execute(query, (provider, model_name, api_key, system_prompt, 1 if is_active else 0))
                
                await conn.commit()
    except aiomysql.Error as err:
        logging.error(f"Error saving AI setting: {err}")
        raise DatabaseError(f"Error saving AI setting: {err}")

async def delete_ai_setting(db_pool, setting_id: int):
    """Delete an AI provider setting."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("DELETE FROM ai_settings WHERE id = %s", (setting_id,))
                await conn.commit()
    except aiomysql.Error as err:
        logging.error(f"Error deleting AI setting: {err}")
        raise DatabaseError(f"Error deleting AI setting: {err}")

async def set_active_ai_provider(db_pool, provider_id: int):
    """Set a specific AI provider as active."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("UPDATE ai_settings SET is_active = 0")
                await cursor.execute("UPDATE ai_settings SET is_active = 1 WHERE id = %s", (provider_id,))
                await conn.commit()
    except aiomysql.Error as err:
        logging.error(f"Error setting active AI provider: {err}")
        raise DatabaseError(f"Error setting active AI provider: {err}")
