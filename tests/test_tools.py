import asyncio
import unittest
from unittest.mock import AsyncMock, patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from google.genai import types
import tools

class TestTools(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        """Set up reusable mocks."""
        self.mock_db_pool = AsyncMock()
        self.mock_genai_client = MagicMock()

    @patch('tools.execute_sql_query', new_callable=AsyncMock)
    async def test_handle_db_gukar_tool_success(self, mock_execute_sql):
        """Tests the db_gukar_tool with a valid search_term."""
        mock_execute_sql.return_value = [{'nama': 'Budi', 'nip': '123', 'mengajar': 'Matematika'}]
        args = {"search_term": "budi"}
        
        result_part = await tools._handle_db_gukar_tool(args, self.mock_db_pool)

        mock_execute_sql.assert_called_once()
        self.assertEqual(result_part.function_response.name, "db_gukar_tool")
        self.assertIn("Budi", result_part.function_response.response['result'])

    @patch('tools.execute_sql_query', new_callable=AsyncMock)
    async def test_handle_db_gukar_tool_custom_columns(self, mock_execute_sql):
        """Tests that only whitelisted columns are used."""
        mock_execute_sql.return_value = [{'nama': 'Budi', 'email': 'budi@test.com'}]
        args = {"search_term": "budi", "columns": ["nama", "email", "MALICIOUS_COL"]}
        
        result_part = await tools._handle_db_gukar_tool(args, self.mock_db_pool)

        # MALICIOUS_COL should be stripped
        call_args = mock_execute_sql.call_args
        sql = call_args[0][1]
        self.assertNotIn("MALICIOUS_COL", sql)
        self.assertIn("`nama`", sql)
        self.assertIn("`email`", sql)

    @patch('tools.execute_sql_query', new_callable=AsyncMock)
    async def test_handle_db_siswa_tool_success(self, mock_execute_sql):
        """Tests the db_siswa_tool with a search_term."""
        mock_execute_sql.return_value = [{'nama': 'Ani', 'nisn': '001'}]
        args = {"search_term": "ani"}
        
        result_part = await tools._handle_db_siswa_tool(args, self.mock_db_pool)

        mock_execute_sql.assert_called_once()
        self.assertIn("Ani", result_part.function_response.response['result'])

    @patch('tools.execute_sql_query', new_callable=AsyncMock)
    async def test_handle_db_siswa_tool_missing_args(self, mock_execute_sql):
        """Tests that missing args returns an error."""
        args = {}
        result_part = await tools._handle_db_siswa_tool(args, self.mock_db_pool)
        self.assertIn("Error", result_part.function_response.response['result'])

    @patch('tools.save_audit_log', new_callable=AsyncMock)
    @patch('tools.execute_sql_query', new_callable=AsyncMock)
    async def test_handle_db_update_tool_column_whitelist(self, mock_execute_sql, mock_audit):
        """Tests that update tool rejects non-whitelisted columns."""
        args = {
            "table_name": "siswa",
            "updates": {"DROP TABLE siswa; --": "hack"},
            "where_clause": {"nisn": "123"}
        }
        
        result_part = await tools._handle_db_update_tool(args, self.mock_db_pool)

        mock_execute_sql.assert_not_called()
        self.assertIn("Error", result_part.function_response.response['result'])
        self.assertIn("not allowed", result_part.function_response.response['result'])

    @patch('tools.save_audit_log', new_callable=AsyncMock)
    @patch('tools.execute_sql_query', new_callable=AsyncMock)
    async def test_handle_db_update_tool_valid(self, mock_execute_sql, mock_audit):
        """Tests a valid update operation."""
        mock_execute_sql.return_value = [("Berhasil", "affected 1 rows")]
        args = {
            "table_name": "siswa",
            "updates": {"nama": "Budi Santoso"},
            "where_clause": {"nisn": "123"}
        }
        
        result_part = await tools._handle_db_update_tool(args, self.mock_db_pool)

        mock_execute_sql.assert_called_once()
        self.assertIn("Berhasil", result_part.function_response.response['result'])
        mock_audit.assert_called_once()

    @patch('tools.save_audit_log', new_callable=AsyncMock)
    @patch('tools.execute_sql_query', new_callable=AsyncMock)
    async def test_handle_db_insert_tool_column_whitelist(self, mock_execute_sql, mock_audit):
        """Tests that insert tool rejects non-whitelisted columns."""
        args = {
            "table_name": "gukar",
            "data": {"malicious_column": "bad_value"}
        }
        
        result_part = await tools._handle_db_insert_tool(args, self.mock_db_pool)

        mock_execute_sql.assert_not_called()
        self.assertIn("not allowed", result_part.function_response.response['result'])

    @patch('tools.save_audit_log', new_callable=AsyncMock)
    @patch('tools.execute_sql_query', new_callable=AsyncMock)
    async def test_handle_db_insert_tool_table_not_allowed(self, mock_execute_sql, mock_audit):
        """Tests that non-allowed tables are rejected."""
        args = {
            "table_name": "admin_users",
            "data": {"name": "hacker"}
        }
        
        result_part = await tools._handle_db_insert_tool(args, self.mock_db_pool)

        mock_execute_sql.assert_not_called()
        self.assertIn("Table not allowed", result_part.function_response.response['result'])

    @patch('asyncio.create_subprocess_shell', new_callable=AsyncMock)
    async def test_handle_cctv_tool_restart(self, mock_subprocess):
        """Tests the cctv_tool restart command."""
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b'success', b'')
        mock_process.returncode = 0
        mock_subprocess.return_value = mock_process

        args = {"command": "restart"}
        result_part = await tools._handle_cctv_tool(args)

        mock_subprocess.assert_called_once_with(
            'pm2 restart "Super Simpel NVR"',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.assertIn("berhasil direstart", result_part.function_response.response['result'])

    @patch('asyncio.create_subprocess_shell', new_callable=AsyncMock)
    async def test_handle_cctv_tool_stop(self, mock_subprocess):
        """Tests the cctv_tool stop command."""
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b'success', b'')
        mock_process.returncode = 0
        mock_subprocess.return_value = mock_process

        args = {"command": "stop"}
        result_part = await tools._handle_cctv_tool(args)

        mock_subprocess.assert_called_once_with(
            'pm2 stop "Super Simpel NVR"',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.assertIn("berhasil dihentikan", result_part.function_response.response['result'])

    @patch('tools.os.unlink')
    @patch('tools.tempfile.NamedTemporaryFile')
    @patch('tools.pyautogui.screenshot')
    async def test_handle_ss_tool_success(self, mock_screenshot, mock_tempfile, mock_unlink):
        """Tests the screenshot tool."""
        mock_file = MagicMock()
        mock_file.name = "/tmp/fake_screenshot.png"
        mock_tempfile.return_value.__enter__.return_value = mock_file

        mock_uploaded_file = MagicMock()
        mock_uploaded_file.uri = "files/fake_uri"
        self.mock_genai_client.files.upload.return_value = mock_uploaded_file

        args = {"command": "screenshot"}
        result_part = await tools._handle_ss_tool(args, self.mock_genai_client)

        mock_screenshot.assert_called_once()
        self.assertEqual(result_part.function_response.response['result'], "files/fake_uri")


if __name__ == '__main__':
    unittest.main()
