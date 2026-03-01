import logging
import json
import os
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, Union
import aiohttp
from google import genai
from google.genai import types
import config

class AIProvider(ABC):
    @abstractmethod
    async def generate_content(self, contents: List[Any], system_instruction: str = None, tools: List[Any] = None) -> Any:
        pass

class GeminiProvider(AIProvider):
    def __init__(self, api_key: str, model_name: str):
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name

    async def generate_content(self, contents: List[types.Content], system_instruction: str = None, tools: List[Any] = None) -> Any:
        try:
            config_params = {
                "model": self.model_name,
                "contents": contents,
                "config": types.GenerateContentConfig(
                    temperature=1,
                    max_output_tokens=6000,
                    system_instruction=system_instruction,
                    tools=tools,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                    safety_settings=[
                        types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH', threshold='BLOCK_NONE'),
                        types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='BLOCK_NONE'),
                        types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_NONE'),
                        types.SafetySetting(category='HARM_CATEGORY_HARASSMENT', threshold='BLOCK_NONE'),
                    ],
                )
            }
            return self.client.models.generate_content(**config_params)
        except Exception as e:
            logging.error(f"Gemini generation error: {e}")
            raise

class OpenRouterProvider(AIProvider):
    def __init__(self, api_key: str, model_name: str):
        self.api_key = api_key
        self.model_name = model_name
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"

    async def generate_content(self, contents: List[Any], system_instruction: str = None, tools: List[Any] = None) -> Any:
        # Convert Gemini-style contents to OpenAI-style
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        
        for content in contents:
            if content.role == "tool":
                for part in content.parts:
                    if hasattr(part, 'function_response') and part.function_response:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": getattr(part.function_response, 'id', part.function_response.name),
                            "name": part.function_response.name,
                            "content": json.dumps(part.function_response.response) if isinstance(part.function_response.response, dict) else str(part.function_response.response)
                        })
                continue

            role = "assistant" if content.role == "model" else content.role
            parts_text = ""
            tool_calls = []
            
            # parts can be a list or a single object depending on how it's passed
            parts = content.parts if isinstance(content.parts, list) else [content.parts]
            
            for part in parts:
                if hasattr(part, 'text') and part.text:
                    parts_text += part.text
                if hasattr(part, 'function_call') and part.function_call:
                    tool_calls.append({
                        "id": getattr(part.function_call, 'id', part.function_call.name),
                        "type": "function",
                        "function": {
                            "name": part.function_call.name,
                            "arguments": json.dumps(part.function_call.args)
                        }
                    })
            
            msg = {"role": role}
            if parts_text:
                msg["content"] = parts_text
            else:
                msg["content"] = None # Some APIs require content to be present or null
                
            if tool_calls:
                msg["tool_calls"] = tool_calls
            messages.append(msg)

        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": 1,
        }

        openai_tools = self._convert_tools(tools)
        if openai_tools:
            payload["tools"] = openai_tools
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(self.api_url, json=payload, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    res_msg = data['choices'][0]['message']
                    text = res_msg.get('content')
                    tool_calls = res_msg.get('tool_calls')
                    return self._create_mock_gemini_response(text, tool_calls)
                else:
                    error_text = await response.text()
                    logging.error(f"OpenRouter error: {error_text}")
                    raise Exception(f"OpenRouter API error: {response.status}")

    def _convert_tools(self, gemini_tools: List[Any]) -> List[Dict]:
        if not gemini_tools:
            return None
        openai_tools = []
        for tool in gemini_tools:
            # gemini_tools can be a list of Tools or a single Tool
            # Each Tool has function_declarations
            fds = getattr(tool, 'function_declarations', [])
            for fd in fds:
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": fd.name,
                        "description": fd.description,
                        "parameters": self._convert_schema(fd.parameters)
                    }
                })
        return openai_tools

    def _convert_schema(self, schema: Any) -> Dict:
        if not schema:
            return {"type": "object", "properties": {}}
        
        # schema is often a types.Schema object
        stype = getattr(schema, 'type', 'OBJECT').lower()
        res = {"type": stype}
        
        if hasattr(schema, 'properties') and schema.properties:
            res["properties"] = {k: self._convert_schema(v) for k, v in schema.properties.items()}
        
        if hasattr(schema, 'required') and schema.required:
            res["required"] = schema.required
            
        if hasattr(schema, 'items') and schema.items:
            res["items"] = self._convert_schema(schema.items)
            
        if hasattr(schema, 'description') and schema.description:
            res["description"] = schema.description
            
        return res

    def _create_mock_gemini_response(self, text: str, tool_calls: List[Dict] = None):
        class MockFunctionCall:
            def __init__(self, name, args, id=None):
                self.name = name
                self.args = args
                self.id = id
        class MockPart:
            def __init__(self, t):
                self.text = t
                self.function_call = None
                self.function_response = None
                self.file_data = None
                self.inline_data = None
        class MockContent:
            def __init__(self, t, tcs=None):
                self.parts = []
                if t:
                    self.parts.append(MockPart(t))
                if tcs:
                    for tc in tcs:
                        tc_name = tc['function']['name']
                        tc_args = json.loads(tc['function']['arguments']) if isinstance(tc['function']['arguments'], str) else tc['function']['arguments']
                        fc = MockFunctionCall(tc_name, tc_args, id=tc['id'])
                        p = MockPart(None)
                        p.function_call = fc
                        self.parts.append(p)
                self.role = "model"
        class MockCandidate:
            def __init__(self, t, tcs=None):
                self.content = MockContent(t, tcs)
        class MockResponse:
            def __init__(self, t, tcs=None):
                self.candidates = [MockCandidate(t, tcs)]
                self.text = t
        return MockResponse(text, tool_calls)

class AIService:
    _instance = None
    _provider = None

    def __init__(self, db_setting: Optional[dict] = None):
        if db_setting:
            self._provider = self._create_provider(db_setting)
        else:
            # Fallback to .env/config
            self._provider = GeminiProvider(config.GOOGLE_API_KEY, config.GOOGLE_MODEL)

    def _create_provider(self, setting: dict) -> AIProvider:
        provider_name = setting['provider'].lower()
        api_key = setting['api_key'] or (config.GOOGLE_API_KEY if provider_name == 'gemini' else None)
        model_name = setting['model_name'] or (config.GOOGLE_MODEL if provider_name == 'gemini' else "gpt-3.5-turbo")

        if provider_name == 'gemini':
            return GeminiProvider(api_key, model_name)
        elif provider_name == 'openrouter':
            return OpenRouterProvider(api_key, model_name)
        elif provider_name == 'openai':
            # OpenAI is similar to OpenRouter but different URL
            p = OpenRouterProvider(api_key, model_name)
            p.api_url = "https://api.openai.com/v1/chat/completions"
            return p
        else:
            logging.warning(f"Unknown provider {provider_name}, falling back to Gemini")
            return GeminiProvider(config.GOOGLE_API_KEY, config.GOOGLE_MODEL)

    async def generate_content(self, contents: List[Any], system_instruction: str = None, tools: List[Any] = None) -> Any:
        return await self._provider.generate_content(contents, system_instruction, tools)
