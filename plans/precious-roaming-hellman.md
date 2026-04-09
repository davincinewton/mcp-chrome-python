# Plan: Port Native Server to Python

## Context

The current Node.js native server uses a complex "shim" script approach to find the Node.js runtime on the user's machine. This leads to "bonding" failures when installed from source, as the absolute paths in the Chrome Native Messaging Manifest often become invalid or the shim fails to locate the correct Node.js executable.

The goal is to port the server to Python and bundle it into a **standalone binary** (using PyInstaller/Nuitka). This removes the need for shims, removes the dependency on a pre-installed Node.js runtime, and creates a robust 1:1 functional link between the Chrome Extension and the server.

## Recommended Approach

### 1. Core Architecture

The server will be rewritten in Python using an asynchronous architecture to mirror the current Node.js event loop.

- **Framework**: FastAPI for the HTTP/SSE transport layer.
- **MCP Protocol**: Official `mcp` Python SDK.
- **Data Validation**: Pydantic for mirroring `chrome-mcp-shared` TypeScript interfaces.
- **Binary Protocol**: `struct` and `sys.stdin.buffer`/`sys.stdout.buffer` for the 4-byte LE length-prefixed Chrome Native Messaging.

### 2. Implementation Details

#### Native Messaging Bridge (`app/bridge/native_messaging.py`)

- Implement a binary reader that reads a 4-byte little-endian unsigned integer, then reads $N$ bytes of JSON.
- Implement a binary writer that prefixes JSON payloads with the 4-byte length header.
- Use `asyncio.Future` and a UUID-based mapping to handle asynchronous request/response matching between the MCP server and the Chrome extension.

#### MCP Server Logic (`app/mcp/server.py`)

- Implement `ChromeMcpServer` using the `mcp` SDK.
- **Tool Proxying**: Implement a handler that forwards `CallToolRequest` messages to the Native Messaging Bridge.
- **Dynamic Tools**: Implement tool discovery by querying the extension via `rr_list_published_flows` and mapping flow variables to JSON Schema.

#### Transport Layer (`app/api/main.py`)

- Implement the following FastAPI endpoints:
  - `GET /ping`: Health check.
  - `GET /sse`: SSE session initialization.
  - `POST /messages`: MCP message delivery for specific sessions.
  - `POST /mcp`: Standard MCP HTTP POST requests.
  - `GET /ask-extension`: Direct bridge proxy.
- Integrate `SseServerTransport` with `sse-starlette`.

#### Registration & Distribution (`scripts/build_binary.py`)

- Use `PyInstaller` with the `--onefile` flag to create a standalone executable.
- Implement a `--register` CLI flag that:
  - Determines the absolute path of the binary.
  - Writes the Chrome Native Messaging Manifest JSON to the correct OS-specific directory.
  - (Windows) Updates the Registry.

### 3. Critical Files to Create/Modify

- `app/bridge/native_messaging.py`: The core binary protocol and request tracker.
- `app/mcp/server.py`: The MCP SDK server and tool proxy logic.
- `app/api/main.py`: FastAPI endpoints and SSE integration.
- `app/schemas/shared.py`: Pydantic models mirroring `chrome-mcp-shared`.
- `scripts/build_binary.py`: Build script and registration logic.

### 4. Verification Plan

1. **Protocol Validation**: Use a mock script to send 4-byte LE prefixed messages to the Python server and verify correct JSON parsing.
2. **Extension Bonding**: Run the `--register` command and verify that the Chrome Extension can successfully connect to the server.
3. **Tool Execution**: Trigger an MCP tool call via an MCP client (e.g., Claude Desktop) and verify it reaches the Chrome extension and returns a result.
4. **Dynamic Tools**: Record a flow in the extension, restart the server, and verify the new tool appears in the MCP `list_tools` response.
5. **Binary Test**: Distribute the compiled binary to a machine without Python/Node installed and verify it still functions.
