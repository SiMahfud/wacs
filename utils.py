import json
from typing import Dict, List
from google.genai import types

def content_to_dict(content: types.Content) -> dict:
    """Converts a types.Content object to a dictionary."""
    content_dict = {
        "role": content.role,
        "parts": []
    }
    for part in content.parts:
        if part.text:
          content_dict["parts"].append({ "type": "text", "text": part.text})
        elif part.file_data:
            content_dict["parts"].append({"type": "FileData", "file_uri": part.file_data.file_uri, "mime_type": part.file_data.mime_type})
        elif part.function_call:
           args = part.function_call.args
           if isinstance(args, str):
             args = args.replace("\\", "")
           elif isinstance(args, dict):
            for key, value in args.items():
                if isinstance(value, str):
                    args[key] = value.replace("\\", "")
           content_dict["parts"].append({"type": "function_call", "name": part.function_call.name, "arguments": args})
        elif part.function_response:
            content_dict["parts"].append({"type": "function_response", "name": part.function_response.name, "response": part.function_response.response})
    
    return content_dict

def _create_parts_from_dict(parts_list: List[Dict]) -> List[types.Part]:
    """Helper function to create parts from a list of dictionaries."""
    return [
        types.Part.from_text(text=part['text']) if part['type'] == 'text' else
        types.Part.from_uri(file_uri=part['file_uri'], mime_type=part['mime_type']) if part['type'] == 'FileData' else
        types.Part.from_function_call(name=part['name'], args=part['arguments']) if part['type'] == 'function_call' else
        types.Part.from_function_response(name=part['name'], response=part['response'])
        for part in parts_list
    ]

def _create_error_response(tool_name: str, message: str) -> types.Part:
    """Helper function to create a function response for errors."""
    return types.Part.from_function_response(
        name=tool_name,
        response={'result': f"Error: {message}"}
    )
