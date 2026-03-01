import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import json

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from google.genai import types
from database import (
    execute_sql_query, save_chat_to_db, get_chat_history_from_db,
    delete_chat_history_from_db, check_auto_reply, DatabaseError
)


def create_mock_pool():
    """Create a properly configured mock pool for async context managers."""
    mock_cursor = AsyncMock()
    
    # Create a mock that works as async context manager
    cursor_ctx = AsyncMock()
    cursor_ctx.__aenter__ = AsyncMock(return_value=mock_cursor)
    cursor_ctx.__aexit__ = AsyncMock(return_value=False)
    
    mock_conn = AsyncMock()
    # Make cursor() return our context manager regardless of args
    mock_conn.cursor = MagicMock(return_value=cursor_ctx)
    
    # Create connection context manager
    conn_ctx = AsyncMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)
    
    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock(return_value=conn_ctx)
    
    return mock_pool, mock_conn, mock_cursor


class TestDatabase(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_pool, self.mock_conn, self.mock_cursor = create_mock_pool()

    async def test_execute_sql_query_select(self):
        """Tests a successful SELECT query."""
        self.mock_cursor.fetchall.return_value = [{'id': 1, 'name': 'test'}]
        
        sql = "SELECT * FROM users"
        result = await execute_sql_query(self.mock_pool, sql)

        self.mock_cursor.execute.assert_called_once()
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

    async def test_execute_sql_query_preserves_backslash(self):
        """Tests that backslashes in queries are preserved (bug fix)."""
        self.mock_cursor.fetchall.return_value = []
        
        sql = "SELECT * FROM users WHERE path LIKE '%C:\\\\Users%'"
        await execute_sql_query(self.mock_pool, sql)

        called_sql = self.mock_cursor.execute.call_args[0][0]
        self.assertEqual(called_sql, sql)

    async def test_get_chat_history_found(self):
        """Tests retrieving chat history when it exists."""
        user_content = {"role": "user", "parts": [{"type": "text", "text": "Hello"}]}
        bot_content = {"role": "model", "parts": [{"type": "text", "text": "Hi there"}]}
        self.mock_cursor.fetchall.return_value = [
            {'user': json.dumps(user_content), 'bot': json.dumps(bot_content)}
        ]

        history = await get_chat_history_from_db(self.mock_pool, "12345")

        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].role, 'user')
        self.assertEqual(history[0].parts[0].text, 'Hello')
        self.assertEqual(history[1].role, 'model')
        self.assertEqual(history[1].parts[0].text, 'Hi there')

    async def test_get_chat_history_empty(self):
        """Tests retrieving chat history when none exists."""
        self.mock_cursor.fetchall.return_value = []
        
        history = await get_chat_history_from_db(self.mock_pool, "nonexistent")
        self.assertIsNone(history)

    async def test_delete_chat_history(self):
        """Tests the deletion of chat history."""
        await delete_chat_history_from_db(self.mock_pool, "12345")
        self.mock_cursor.execute.assert_called_once_with(
            "DELETE FROM chat_history WHERE chat_id = %s", ("12345",)
        )
        self.mock_conn.commit.assert_called_once()

    async def test_check_auto_reply_match(self):
        """Tests that auto-reply matches correctly."""
        self.mock_cursor.fetchall.return_value = [
            {'keyword': 'selamat pagi', 'response': 'Selamat pagi juga! 🌅'},
            {'keyword': 'jam berapa', 'response': 'Cek jam di HP ya.'}
        ]
        
        result = await check_auto_reply(self.mock_pool, "Selamat pagi semua!")
        self.assertEqual(result, 'Selamat pagi juga! 🌅')

    async def test_check_auto_reply_no_match(self):
        """Tests that auto-reply returns None when no keyword matches."""
        self.mock_cursor.fetchall.return_value = [
            {'keyword': 'selamat pagi', 'response': 'Pagi!'}
        ]
        
        result = await check_auto_reply(self.mock_pool, "Halo apa kabar")
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()