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
           # Preserve args as-is without stripping backslashes
           # Add id for persistence
           content_dict["parts"].append({"type": "function_call", "name": part.function_call.name, "arguments": args, "id": getattr(part.function_call, 'id', None)})
        elif part.function_response:
            content_dict["parts"].append({"type": "function_response", "name": part.function_response.name, "response": part.function_response.response, "id": getattr(part.function_response, 'id', None)})
    
    return content_dict

def _create_parts_from_dict(parts_list: List[Dict]) -> List[types.Part]:
    """Helper function to create parts from a list of dictionaries."""
    return [
        types.Part.from_text(text=part['text']) if part['type'] == 'text' else
        types.Part.from_uri(file_uri=part['file_uri'], mime_type=part['mime_type']) if part['type'] == 'FileData' else
        _create_fc_part(part) if part['type'] == 'function_call' else
        _create_fr_part(part)
        for part in parts_list
        if part.get('type')  # Skip parts without a type (e.g. local_media)
    ]

def _create_fc_part(part_dict: Dict) -> types.Part:
    fc = types.Part.from_function_call(name=part_dict['name'], args=part_dict['arguments'])
    if part_dict.get('id'):
        fc.function_call.id = part_dict['id']
    return fc

def _create_fr_part(part_dict: Dict) -> types.Part:
    fr = types.Part.from_function_response(name=part_dict['name'], response=part_dict['response'])
    if part_dict.get('id'):
        fr.function_response.id = part_dict['id']
    return fr

def _create_error_response(tool_name: str, message: str) -> types.Part:
    """Helper function to create a function response for errors."""
    return types.Part.from_function_response(
        name=tool_name,
        response={'result': f"Error: {message}"}
    )
