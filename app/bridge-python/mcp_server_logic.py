import asyncio
import logging
from typing import Any, Dict, List
from mcp.server import Server
from mcp.types import Tool, TextContent, CallToolResult
from bridge.base import ExtensionBridge
from schemas.tool_schemas import TOOL_SCHEMAS
from schemas.tool_arguments import TOOL_VALIDATORS
from pydantic import ValidationError

logger = logging.getLogger("mcp-server")

class ChromeMcpServer:
    """
    MCP Server implementation that proxies tool calls to the Chrome Extension
    via the WebSocket Bridge.
    """
    def __init__(self, bridge: ExtensionBridge):
        self.bridge = bridge
        self.server = Server("ChromeMcpServer")
        self._setup_handlers()

    def _setup_handlers(self):
        """Registers MCP request handlers."""
        # List tools handler
        @self.server.list_tools()
        async def handle_list_tools() -> List[Tool]:
            # Combine static tools (placeholder for now) and dynamic tools
            static_tools = self._get_static_tools()
            dynamic_tools = await self._list_dynamic_flow_tools()
            return static_tools + dynamic_tools

        # Call tool handler
        @self.server.call_tool()
        async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> CallToolResult:
            return await self._handle_tool_call(name, arguments)

    def _get_static_tools(self) -> List[Tool]:
        """
        Returns a list of static tools defined in the shared schemas.
        Mirrors the logic from TOOL_SCHEMAS in TypeScript packages/shared/src/tools.ts
        """
        return TOOL_SCHEMAS

    async def _list_dynamic_flow_tools(self) -> List[Tool]:
        """
        Queries the Chrome extension for recorded flows and converts them to MCP tools.
        """
        try:
            response = await self.bridge.send_request({}, "rr_list_published_flows", timeout=20.0)
            if response and response.get("status") == "success" and isinstance(response.get("items"), list):
                tools = []
                for item in response["items"]:
                    name = f"flow.{item['slug']}"
                    description = (
                        (item.get("meta") or {}).get("tool", {}).get("description") or
                        item.get("description") or
                        "Recorded flow"
                    )

                    properties = {}
                    required = []

                    for v in item.get("variables", []):
                        key = v.get("key")
                        if not key: continue

                        desc = v.get("label") or key
                        typ = (v.get("type") or "string").lower()

                        prop = {"description": desc}
                        if typ == "boolean": prop["type"] = "boolean"
                        elif typ == "number": prop["type"] = "number"
                        elif typ == "enum":
                            prop["type"] = "string"
                            rules = v.get("rules") or {}
                            if isinstance(rules.get("enum"), list):
                                prop["enum"] = rules["enum"]
                        elif typ == "array":
                            prop["type"] = "array"
                            prop["items"] = {"type": "string"}
                        else:
                            prop["type"] = "string"

                        if v.get("default") is not None:
                            prop["default"] = v["default"]

                        rules = v.get("rules") or {}
                        if rules.get("required"):
                            required.append(key)

                        properties[key] = prop

                    # Standard run options
                    properties["tabTarget"] = {"type": "string", "enum": ["current", "new"], "default": "current"}
                    properties["refresh"] = {"type": "boolean", "default": False}
                    properties["captureNetwork"] = {"type": "boolean", "default": False}
                    properties["returnLogs"] = {"type": "boolean", "default": False}
                    properties["timeoutMs"] = {"type": "number", "minimum": 0}

                    tools.append(Tool(
                        name=name,
                        description=description,
                        inputSchema={"type": "object", "properties": properties, "required": required}
                    ))
                return tools
        except Exception as e:
            logger.error(f"Error listing dynamic flow tools: {e}")
            return []

    async def _handle_tool_call(self, name: str, args: Dict[str, Any]) -> CallToolResult:
        """
        Handles tool execution by proxying the call to the Chrome extension.
        Returns CallToolResult with proper isError flag preservation.
        """
        # Validate arguments if a validator exists for this tool
        validator = TOOL_VALIDATORS.get(name)
        if validator:
            try:
                validated_args = validator(**args)
                args = validated_args.model_dump(exclude_none=True)
            except ValidationError as e:
                return CallToolResult(
                    content=[TextContent(type="text", text=f"Invalid arguments: {e}")],
                    isError=True
                )

        try:
            # Handle dynamic flow tools (name starts with flow.)
            if name.startswith("flow."):
                # 1. Resolve flow slug to ID
                resp = await self.bridge.send_request({}, "rr_list_published_flows", timeout=20.0)
                items = resp.get("items", []) if resp else []
                slug = name[len("flow."):]
                match = next((it for it in items if it.get("slug") == slug), None)

                if not match:
                    return CallToolResult(
                        content=[TextContent(type="text", text=f"Flow not found for tool {name}")],
                        isError=True
                    )

                flow_args = {"flowId": match["id"], "args": args}
                proxy_res = await self.bridge.send_request(
                    {"name": "record_replay_flow_run", "args": flow_args},
                    message_type="call_tool",
                    timeout=120.0
                )

                if proxy_res.get("status") == "success":
                    tool_result = proxy_res.get("data", {})
                    return CallToolResult(
                        content=tool_result.get("content", []),
                        isError=tool_result.get("isError", False)
                    )

                return CallToolResult(
                    content=[TextContent(type="text", text=f"Error calling dynamic flow tool: {proxy_res.get('error')}")],
                    isError=True
                )

            # Standard tool proxy
            response = await self.bridge.send_request(
                {"name": name, "args": args},
                message_type="call_tool",
                timeout=120.0
            )

            if response.get("status") == "success":
                tool_result = response.get("data", {})
                return CallToolResult(
                    content=tool_result.get("content", []),
                    isError=tool_result.get("isError", False)
                )
            else:
                return CallToolResult(
                    content=[TextContent(type="text", text=f"Error calling tool: {response.get('error')}")],
                    isError=True
                )

        except Exception as e:
            logger.error(f"Error executing tool {name}: {e}")
            return CallToolResult(
                content=[TextContent(type="text", text=f"Error calling tool: {str(e)}")],
                isError=True
            )
