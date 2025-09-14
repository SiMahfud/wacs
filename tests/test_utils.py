import unittest
from google.genai import types

# Add the root directory to the path to allow imports from the main project
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils import content_to_dict, _create_parts_from_dict, _create_error_response

class TestUtils(unittest.TestCase):

    def test_create_error_response(self):
        """Tests the creation of a standardized error response."""
        tool_name = "test_tool"
        message = "This is an error"
        error_part = _create_error_response(tool_name, message)

        self.assertIsInstance(error_part, types.Part)
        self.assertEqual(error_part.function_response.name, tool_name)
        self.assertIn("Error:", error_part.function_response.response['result'])
        self.assertIn(message, error_part.function_response.response['result'])

    def test_content_to_dict_and_back(self):
        """Tests the conversion from Content to dict and back to Part list."""
        original_content = types.Content(
            role="user",
            parts=[
                types.Part.from_text(text="Hello there"),
                types.Part.from_function_call(
                    name="db_gukar_tool", 
                    args={"sqlQuery": "SELECT * FROM gukar"}
                )
            ]
        )

        # 1. Test content_to_dict
        content_dict = content_to_dict(original_content)
        
        self.assertEqual(content_dict['role'], "user")
        self.assertEqual(len(content_dict['parts']), 2)
        
        self.assertEqual(content_dict['parts'][0]['type'], 'text')
        self.assertEqual(content_dict['parts'][0]['text'], "Hello there")
        
        self.assertEqual(content_dict['parts'][1]['type'], 'function_call')
        self.assertEqual(content_dict['parts'][1]['name'], "db_gukar_tool")
        self.assertEqual(content_dict['parts'][1]['arguments']['sqlQuery'], "SELECT * FROM gukar")

        # 2. Test _create_parts_from_dict
        recreated_parts = _create_parts_from_dict(content_dict['parts'])
        self.assertEqual(len(recreated_parts), 2)
        self.assertIsInstance(recreated_parts[0], types.Part)
        self.assertIsInstance(recreated_parts[1], types.Part)

        # Check if the recreated parts match the original parts
        self.assertEqual(recreated_parts[0].text, original_content.parts[0].text)
        self.assertEqual(recreated_parts[1].function_call.name, original_content.parts[1].function_call.name)
        self.assertEqual(recreated_parts[1].function_call.args, original_content.parts[1].function_call.args)

if __name__ == '__main__':
    unittest.main()
