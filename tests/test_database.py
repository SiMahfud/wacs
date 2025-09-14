import unittest
from unittest.mock import AsyncMock
import json

# Add the root directory to the path to allow imports from the main project
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from google.genai import types
from database import execute_sql_query, save_chat_to_db, get_chat_history_from_db, delete_chat_history_from_db, DatabaseError

class TestDatabase(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        """Set up a reusable mock pool for all tests."""
        self.mock_cursor = AsyncMock()
        
        self.mock_conn = AsyncMock()
        self.mock_conn.cursor.return_value = self.mock_cursor
        
        self.mock_pool = AsyncMock()
        # Configure the object returned by acquire() to be an async context manager
        self.mock_pool.acquire.return_value.__aenter__.return_value = self.mock_conn
        self.mock_pool.acquire.return_value.__aexit__.return_value = None

    async def test_execute_sql_query_select(self):
        """Tests a successful SELECT query."""
        self.mock_cursor.fetchall.return_value = [{'id': 1, 'name': 'test'}]
        
        sql = "SELECT * FROM users"
        result = await execute_sql_query(self.mock_pool, sql)

        self.mock_cursor.execute.assert_called_once_with(sql, None)
        self.assertEqual(result, [{'id': 1, 'name': 'test'}])

    async def test_execute_sql_query_insert(self):
        """Tests a successful INSERT query."""
        self.mock_cursor.rowcount = 1

        sql = "INSERT INTO users (name) VALUES (%s)"
        params = ('test',)
        result = await execute_sql_query(self.mock_pool, sql, params=params)

        self.mock_cursor.execute.assert_called_once_with(sql, params)
        self.mock_conn.commit.assert_called_once()
        self.assertIn("Berhasil", result[0][0])
        self.assertIn("affected 1 rows", result[0][1])

    async def test_get_chat_history_found(self):
        """Tests retrieving chat history when it exists."""
        user_content = {"role": "user", "parts": [{"type": "text", "text": "Hello"}]}
        bot_content = {"role": "model", "parts": [{"type": "text", "text": "Hi there"}]}
        db_return_value = [
            {'user': json.dumps(user_content), 'bot': json.dumps(bot_content)}
        ]
        self.mock_cursor.fetchall.return_value = db_return_value

        chat_id = 12345
        history = await get_chat_history_from_db(self.mock_pool, chat_id)

        self.mock_cursor.execute.assert_called_once_with(
            "SELECT user, bot FROM chat_history WHERE chat_id = %s ORDER BY id ASC", (chat_id,)
        )
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].role, 'user')
        self.assertEqual(history[0].parts[0].text, 'Hello')
        self.assertEqual(history[1].role, 'model')
        self.assertEqual(history[1].parts[0].text, 'Hi there')

    async def test_delete_chat_history(self):
        """Tests the deletion of chat history."""
        chat_id = 12345
        await delete_chat_history_from_db(self.mock_pool, chat_id)

        self.mock_cursor.execute.assert_called_once_with(
            "DELETE FROM chat_history WHERE chat_id = %s", (chat_id,)
        )
        self.mock_conn.commit.assert_called_once()


if __name__ == '__main__':
    unittest.main()