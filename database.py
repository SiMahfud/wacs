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

async def save_chat_to_db(db_pool, chat_id: int, user: types.Content, bot: types.Content):
    """Fungsi untuk menyimpan chat ke database, maksimal 10 chat, dan menghapus yang terlama jika ada yang baru."""
    try:
       user_json = json.dumps(content_to_dict(user))
       bot_json = json.dumps(content_to_dict(bot))

       async with db_pool.acquire() as conn:
            async with conn.cursor() as cursor:
               # Insert chat baru
                query = "INSERT INTO chat_history (chat_id, user, bot) VALUES (%s, %s, %s)"
                await cursor.execute(query, (chat_id, user_json, bot_json))
                await conn.commit()

               # Hitung jumlah chat untuk chat_id ini
                await cursor.execute("SELECT COUNT(*) FROM chat_history WHERE chat_id = %s", (chat_id,))
                count = (await cursor.fetchone())[0]

                # Jika lebih dari 10, hapus chat yang paling lama
                if count > 10:
                    await cursor.execute("SELECT id FROM chat_history WHERE chat_id = %s ORDER BY id ASC LIMIT 1", (chat_id,))
                    oldest_id = (await cursor.fetchone())[0]
                    await cursor.execute("DELETE FROM chat_history WHERE id = %s", (oldest_id,))
                    await conn.commit()

    except aiomysql.Error as err:
        logging.error(f"Error saving chat to database: {err}")
        raise DatabaseError(f"Error saving chat to database: {err}")
    except Exception as e:
        logging.exception(f"An unexpected error occurred: {e}")
        raise DatabaseError(f"An unexpected error occurred: {e}")

async def get_chat_history_from_db(db_pool, chat_id: int) -> Optional[List[types.Content]]:
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

async def delete_chat_history_from_db(db_pool, chat_id: int):
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
