import asyncio
import unittest
from unittest.mock import AsyncMock, patch, MagicMock

# Add the root directory to the path to allow imports from the main project
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
        """Tests the db_gukar_tool with a valid SELECT query."""
        mock_execute_sql.return_value = [{'nama': 'Budi'}]
        args = {"sqlQuery": "SELECT nama FROM gukar WHERE nip = '123'"}
        
        result_part = await tools._handle_db_gukar_tool(args, self.mock_db_pool)

        mock_execute_sql.assert_called_once_with(self.mock_db_pool, args["sqlQuery"])
        self.assertEqual(result_part.function_response.name, "db_gukar_tool")
        self.assertIn("Budi", result_part.function_response.response['result'])

    @patch('tools.execute_sql_query', new_callable=AsyncMock)
    async def test_handle_db_gukar_tool_non_select(self, mock_execute_sql):
        """Tests that db_gukar_tool rejects non-SELECT queries."""
        args = {"sqlQuery": "UPDATE gukar SET nama = 'Budi'"}
        
        result_part = await tools._handle_db_gukar_tool(args, self.mock_db_pool)

        mock_execute_sql.assert_not_called()
        self.assertEqual(result_part.function_response.name, "db_gukar_tool")
        self.assertIn("Error:", result_part.function_response.response['result'])
        self.assertIn("hanya bisa digunakan untuk query SELECT", result_part.function_response.response['result'])

    @patch('asyncio.create_subprocess_shell', new_callable=AsyncMock)
    async def test_handle_cctv_tool_success(self, mock_subprocess):
        """Tests the cctv_tool with a successful command."""
        # Configure the mock process
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
        self.assertEqual(result_part.function_response.name, "cctv_tool")
        self.assertIn("berhasil direstart", result_part.function_response.response['result'])

    @patch('tools.os.unlink')
    @patch('tools.tempfile.NamedTemporaryFile')
    @patch('tools.pyautogui.screenshot')
    async def test_handle_ss_tool_success(self, mock_screenshot, mock_tempfile, mock_unlink):
        """Tests the screenshot tool to ensure it calls the correct libraries."""
        # Mock the temp file context manager
        mock_file = MagicMock()
        mock_file.name = "/tmp/fake_screenshot.png"
        mock_tempfile.return_value.__enter__.return_value = mock_file

        # Mock the genai client's upload method
        mock_uploaded_file = MagicMock()
        mock_uploaded_file.uri = "files/fake_uri"
        self.mock_genai_client.files.upload.return_value = mock_uploaded_file

        args = {"command": "screenshot"}
        result_part = await tools._handle_ss_tool(args, self.mock_genai_client)

        mock_screenshot.assert_called_once()
        mock_tempfile.assert_called_once_with(suffix='.png', delete=False)
        mock_screenshot.return_value.save.assert_called_once_with(mock_file.name)
        self.mock_genai_client.files.upload.assert_called_once_with(file=mock_file.name)
        mock_unlink.assert_called_once_with(mock_file.name)
        self.assertEqual(result_part.function_response.name, "ss_tool")
        self.assertEqual(result_part.function_response.response['result'], "files/fake_uri")


if __name__ == '__main__':
    unittest.main()
