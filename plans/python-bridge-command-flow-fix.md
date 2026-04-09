# Python Bridge Command Flow Fix - Plan

## Context

The Python bridge (`app/bridge-python/`) is designed to replace the Node.js native server (`app/native-server/`) while maintaining the same communication protocols. However, there are critical gaps in the implementation that prevent the MCP client from receiving the static tool list and properly executing tools.

The issue: When an MCP client calls `tools/list`, it receives an empty array `[]` instead of the full tool list. This is because the Python implementation's `_get_static_tools()` method returns an empty list, while the Node.js implementation properly imports and returns `TOOL_SCHEMAS` from the shared package.

## Problem Analysis

### Current Working State (Node.js Bridge)

**Path: MCP Client → Node.js Server → Extension → Back**

1. **MCP Client sends `tools/list` request** to `http://127.0.0.1:12306/mcp`
2. **Node.js `register-tools.ts`** handles the request:
   - Calls `listDynamicFlowTools()` to get dynamic flow tools from extension
   - Returns `([...TOOL_SCHEMAS, ...dynamicTools])` where `TOOL_SCHEMAS` is imported from `chrome-mcp-shared`
3. **MCP Client receives full tool list** with all 30+ browser automation tools

### Current Broken State (Python Bridge)

1. **MCP Client sends `tools/list` request** to `http://127.0.0.1:12306/mcp`
2. **Python `mcp_server_logic.py`** handles the request:
   - `_get_static_tools()` returns `[]` (empty!)
   - `_list_dynamic_flow_tools()` may work if extension is connected
3. **MCP Client receives empty or partial tool list**

### Root Causes Identified

#### For `tools/list`:

1. **Missing Static Tools Schema**: Python's `_get_static_tools()` returns `[]` instead of mirroring the TypeScript `TOOL_SCHEMAS`
2. **Import Path Issue**: `mcp_server_logic.py` imports from `bridge.native_messaging` but should use `bridge.websocket_bridge` (or be configurable)
3. **Type Mismatch**: TypeScript `TOOL_SCHEMAS` uses MCP SDK `Tool` type; Python needs equivalent `mcp.types.Tool` objects

#### For `tools/call`:

4. **Critical Bug - Wrong Return Type**: Python's `_handle_tool_call()` returns a `dict` (`{content: [...], isError: ...}`), but the Python MCP SDK treats dicts as **structured content**, not as `CallToolResult`. This causes:
   - The `isError` flag to be lost (always becomes `False`)
   - The response to be JSON-serialized and wrapped incorrectly
   - Error responses from tools to appear as successful to the MCP client

5. **Missing `isError` Check**: The code only checks `response.get("status") == "success"` but doesn't verify `response["data"]["isError"]` from the extension

## Solution

### Critical Files to Modify

| File                                    | Changes                                                       |
| --------------------------------------- | ------------------------------------------------------------- |
| `app/bridge-python/mcp_server_logic.py` | Fix imports, return Tool objects, fix CallToolResult handling |
| `app/bridge-python/schemas/shared.py`   | Add complete TOOL_SCHEMAS mirroring TS definitions            |
| `app/bridge-python/api/main.py`         | Ensure WebSocketBridge is used (not NativeMessagingBridge)    |

### Implementation Steps

#### Step 1: Create Complete Tool Schemas in Python (`schemas/shared.py`)

Add a Python representation of all static tools from `packages/shared/src/tools.ts`. Copy all tool definitions from `packages/shared/src/tools.ts` into Python format:

```python
from mcp.types import Tool

TOOL_SCHEMAS: list[Tool] = [
    Tool(
        name="chrome_navigate",
        description="Navigate to a URL...",
        inputSchema={"type": "object", "properties": {...}, "required": []}
    ),
    # ... all 30+ tools (chrome_screenshot, chrome_click_element, etc.)
]
```

This mirrors the TypeScript `TOOL_SCHEMAS` array exported from `packages/shared/src/tools.ts`.

#### Step 2: Fix ChromeMcpServer (`mcp_server_logic.py`)

**Fix the imports:**

```python
# Change from:
from mcp.types import Tool, TextContent
from bridge.native_messaging import NativeMessagingBridge
# To:
from mcp.types import Tool, TextContent, CallToolResult
from bridge.websocket_bridge import WebSocketBridge
from bridge.base import ExtensionBridge  # Use abstract base for type
```

**Fix `__init__` type hint:**

```python
def __init__(self, bridge: ExtensionBridge):  # Accept any bridge implementation
```

**Fix `_get_static_tools()`:**

```python
from schemas.shared import TOOL_SCHEMAS

def _get_static_tools(self) -> List[Tool]:
    return TOOL_SCHEMAS  # Return actual tools, not empty list
```

**Fix `_handle_tool_call()` - CRITICAL:**
The current implementation returns `dict` which the MCP SDK treats as structured content. Must return `CallToolResult`:

```python
async def _handle_tool_call(self, name: str, args: Dict[str, Any]) -> CallToolResult:
    try:
        # Handle dynamic flow tools (name starts with flow.)
        if name.startswith("flow."):
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
                content=[TextContent(type="text", text=f"Error: {proxy_res.get('error')}")],
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
                content=[TextContent(type="text", text=f"Error: {response.get('error')}")],
                isError=True
            )

    except Exception as e:
        logger.error(f"Error executing tool {name}: {e}")
        return CallToolResult(
            content=[TextContent(type="text", text=f"Error calling tool: {str(e)}")],
            isError=True
        )
```

**Key changes:**

1. Return `CallToolResult` instead of `List[TextContent]` or raw `dict`
2. Preserve the `isError` flag from the extension response
3. Set `isError=True` for all error cases

#### Step 3: Verify WebSocketBridge Integration (`api/main.py`)

The `api/main.py` already correctly uses `WebSocketBridge`. Verify the instantiation:

```python
class ServerState:
    def __init__(self):
        self.bridge = WebSocketBridge()  # Correct - not NativeMessagingBridge
        self.mcp_server = ChromeMcpServer(self.bridge)
```

#### Step 4: Verify Message Flow

The message protocol is already correctly implemented:

**Outbound (Python → Extension):**

```python
# Python sends:
{
    "type": "call_tool",
    "payload": {"name": "chrome_click_element", "args": {...}},
    "requestId": "uuid-123"
}
```

**Inbound (Extension → Python):**

```python
# Extension responds:
{
    "responseToRequestId": "uuid-123",
    "payload": {
        "status": "success",
        "message": "Tool executed",
        "data": [{"type": "text", "text": "..."}]
    }
}
```

This protocol matches the Node.js implementation in `native-messaging-host.ts`.

## Verification Plan

### Test 1: Tools List (Discovery)

```bash
curl -s -X POST http://127.0.0.1:12306/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'

curl -s -X POST http://127.0.0.1:12306/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' | jq '.result.tools | length'
```

Expected: Should return ~30+ tools (not 0)

### Test 2: Successful Tool Execution

```bash
curl -s -X POST http://127.0.0.1:12306/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"chrome_navigate","arguments":{"url":"https://example.com"}}}' | jq '.result'
```

Expected:

- `result.content[0].text` contains the navigation result
- `result.isError` is `false`

### Test 3: Error Tool Execution (Verify isError Flag)

```bash
curl -s -X POST http://127.0.0.1:12306/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"chrome_click_element","arguments":{}}}' | jq '.result'
```

Expected:

- `result.isError` is `true` (this is the critical fix - previously would be `false`!)
- Error message is in `result.content[0].text`

### Test 4: Full MCP Client Integration

1. Configure Claude Desktop with the Python bridge MCP server
2. Open a new chat and ask: "Navigate to https://example.com"
3. Verify the tool is discovered and executes correctly
4. Check that error responses (e.g., invalid tool arguments) properly show `isError=true`

## Architecture Diagram

```
┌─────────────┐      HTTP/MCP       ┌──────────────────────────┐
│ MCP Client  │◄─── POST /mcp ──────│  api/main.py (FastAPI)   │
│ (Claude)    │  SSE Response       │  - /mcp endpoint         │
└─────────────┘                      │  - /ping                 │
                                     │  - /ask-extension        │
                                     └──────────┬───────────────┘
                                                │
                                    ┌───────────▼──────────┐
                                    │ mcp_server_logic.py  │
                                    │ ChromeMcpServer      │
                                    │ - list_tools()       │
                                    │ - call_tool()        │
                                    └──────────┬───────────┘
                                               │
                                    ┌──────────▼──────────┐
                                    │ websocket_bridge.py │
                                    │ WebSocketBridge     │
                                    │ Port: 12307         │
                                    └──────────┬──────────┘
                                               │ WebSocket
                                               │
┌──────────────────────────────────────────────┴────────────────────────────┐
│                         Chrome Extension                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │ websocket-host.ts                                                    │ │
│  │ - Connects to ws://127.0.0.1:12307                                   │ │
│  │ - Handles CALL_TOOL messages                                         │ │
│  │ - Returns response with responseToRequestId                          │ │
│  └──────────────────────┬───────────────────────────────────────────────┘ │
│                         │                                                  │
│  ┌──────────────────────▼───────────────────────────────────────────────┐ │
│  │ tools/index.ts                                                       │ │
│  │ - handleCallTool(name, args)                                         │ │
│  │ - Dispatches to specific tool                                        │ │
│  └──────────────────────┬───────────────────────────────────────────────┘ │
│                         │                                                  │
│  ┌──────────────────────▼───────────────────────────────────────────────┐ │
│  │ tools/browser/*.ts                                                   │ │
│  │ - clickTool, fillTool, navigateTool, etc.                            │ │
│  │ - execute() returns ToolResult                                       │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────────┘
```

## Summary of Changes

1. **`app/bridge-python/schemas/shared.py`**:
   - Add complete `TOOL_SCHEMAS` array with all 30+ static tools from TypeScript

2. **`app/bridge-python/mcp_server_logic.py`**:
   - Fix import to use `ExtensionBridge` (abstract base) instead of `NativeMessagingBridge`
   - Implement `_get_static_tools()` to return actual `TOOL_SCHEMAS`
   - **CRITICAL**: Fix `_handle_tool_call()` to return `CallToolResult` instead of raw `dict`
   - Preserve `isError` flag from extension responses

3. **No changes needed to `api/main.py`**: Already correctly uses `WebSocketBridge`

## Impact

### Before Fix:

- `tools/list` returns empty array → MCP client sees no available tools
- `tools/call` loses `isError` flag → errors appear as success
- Python MCP SDK treats dict as structured content → incorrect response format

### After Fix:

- `tools/list` returns 30+ tools → MCP client discovers all browser automation tools
- `tools/call` preserves `isError` flag → errors are properly reported
- Response format matches Node.js implementation → full compatibility
