import logging
import json
import aiomysql
from typing import Optional, List, Tuple
from google.genai import types

from utils import content_to_dict, _create_parts_from_dict

# Custom Exception for Database
class DatabaseError(Exception):
    pass

async def execute_sql_query(db_pool, sql_query: str, params: Optional[tuple] = None) -> Optional[List[Tuple]]:
    """Fungsi untuk mengeksekusi query SQL ke database."""
    sql_query = sql_query.replace("\\", "")
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

async def save_chat_to_db(db_pool, chat_id: str, user: types.Content, bot: types.Content):
    """Fungsi untuk menyimpan chat ke database."""
    try:
       user_json = json.dumps(content_to_dict(user))
       bot_json = json.dumps(content_to_dict(bot))

       async with db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
               # Insert chat baru
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
            # Skip rows where user or bot might be null (e.g. admin messages)
            if not row['user'] or not row['bot']:
                continue
            user_content = json.loads(row['user'])
            bot_content = json.loads(row['bot'])
            
            user_parts = _create_parts_from_dict(user_content['parts'])
            bot_parts = _create_parts_from_dict(bot_content['parts'])
            
            contents.append(types.Content(role=user_content['role'], parts=user_parts))
            contents.append(types.Content(role=bot_content['role'], parts=bot_parts))
        return contents
    except aiomysql.Error as err:
        logging.error(f"Error retrieving chat history from database: {err}")
        raise DatabaseError(f"Error retrieving chat history from database: {err}")
    except Exception as e:
        logging.exception(f"An unexpected error occurred: {e}")
        raise DatabaseError(f"An unexpected error occurred: {e}")

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

async def get_all_chat_ids(db_pool) -> Optional[List[str]]:
    """Fungsi untuk mengambil semua chat_id unik dari database."""
    try:
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                query = "SELECT DISTINCT chat_id FROM chat_history ORDER BY chat_id ASC"
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
                query = "SELECT user, bot FROM chat_history WHERE chat_id = %s ORDER BY id ASC"
                await cursor.execute(query, (chat_id,))
                results = await cursor.fetchall()

        if not results:
            return None
        
        history = []
        for row in results:
            history.append({
                'user': json.loads(row['user']) if row['user'] else None,
                'bot': json.loads(row['bot']) if row['bot'] else None
            })
        return history
    except aiomysql.Error as err:
        logging.error(f"Error retrieving chat history for admin: {err}")
        raise DatabaseError(f"Error retrieving chat history for admin: {err}")

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

async def save_admin_reply(db_pool, chat_id: str, admin_text: str):
    """Menyimpan balasan dari admin ke chat history."""
    try:
        # Pesan admin disimpan di kolom 'bot', dengan kolom 'user' menandakan aksi admin
        admin_reply_content = types.Content(role="model", parts=[types.Part.from_text(admin_text)])
        bot_json = json.dumps(content_to_dict(admin_reply_content))

        async with db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                query = "INSERT INTO chat_history (chat_id, user, bot) VALUES (%s, NULL, %s)"
                await cursor.execute(query, (chat_id, bot_json))
                await conn.commit()
    except aiomysql.Error as err:
        logging.error(f"Error saving admin reply: {err}")
        raise DatabaseError(f"Error saving admin reply: {err}")

async def save_user_message_only(db_pool, chat_id: str, user_content: types.Content):
    """Menyimpan pesan dari user saja, saat admin sedang mengontrol."""
    try:
        user_json = json.dumps(content_to_dict(user_content))
        async with db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # Hanya user yang diisi, bot diisi NULL
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
