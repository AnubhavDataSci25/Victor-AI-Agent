"""
Converts Victor's tool registry into Google GenAI Tool declarations
for the Gemini Live API function-calling interface.
"""

from google.genai import types

from app.tools.base import BaseTool, Tool
from app.tools.tool_setup import build_tool_registry


def get_gemini_tools() -> list[types.Tool]:
    """
    Build a populated tool registry and convert every registered tool
    into a Gemini FunctionDeclaration.

    - BaseTool (v2): uses get_schema() which returns {name, description, parameters}
    - Tool (v1): builds a JSON schema from the Pydantic args_model
    """
    registry = build_tool_registry()
    function_declarations = []

    for tool_name, tool_instance in registry.get_all_tools().items():
        if isinstance(tool_instance, BaseTool):
            schema = tool_instance.get_schema()
            func_decl = types.FunctionDeclaration(
                name=schema["name"],
                description=schema["description"],
                parameters=schema.get("parameters", {}),
            )
        elif isinstance(tool_instance, Tool):
            # Build JSON schema from Pydantic model
            json_schema = tool_instance.args_model.model_json_schema()
            # Strip Pydantic metadata keys that Gemini doesn't expect
            params = {
                "type": "object",
                "properties": json_schema.get("properties", {}),
                "required": json_schema.get("required", []),
            }
            func_decl = types.FunctionDeclaration(
                name=tool_instance.name,
                description=tool_instance.description,
                parameters=params,
            )
        else:
            continue

        function_declarations.append(func_decl)

    return [types.Tool(function_declarations=function_declarations)]