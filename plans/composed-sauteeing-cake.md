# Transition Bridge from Native Messaging to WebSockets

## Context

The current communication between the Chrome extension and the Python bridge relies on Chrome Native Messaging (stdin/stdout with 4-byte LE length prefix). This mechanism is cumbersome for development and deployment as it requires manifest files and OS-specific registry/filesystem configurations.

The goal is to replace this with a WebSocket server listening on `localhost:12307`. This allows the bridge to run as a standalone Python process that the extension connects to, simplifying the installation and debugging process while maintaining the existing JSON protocol (`requestId`/`responseToRequestId`).

## Implementation Plan

### 1. Define Bridge Abstraction

To ensure the rest of the application (MCP server, FastAPI endpoints) remains agnostic of the transport layer, we will introduce an abstract base class.

- **New File**: `app/bridge-python/bridge/base.py`
- **Class**: `ExtensionBridge(ABC)`
- **Required Methods**:
  - `async def start()`: Starts the transport server/listener.
  - `async def send_message(message: Dict[str, Any])`: Sends a JSON message to the extension.
  - `async def send_request(payload: Any, message_type: str = 'request_data', timeout: float = 30.0) -> Any`: Sends a request and waits for a response using `requestId` and `asyncio.Future`.
  - `def set_message_handler(self, handler: Callable[[Dict[str, Any]], Awaitable[None]])`: Registers the main message processor.
  - `async def cleanup()`: Shuts down the transport.

### 2. Implement WebSocket Bridge

- **New File**: `app/bridge-python/bridge/websocket_bridge.py`
- **Class**: `WebSocketBridge(ExtensionBridge)`
- **Implementation Details**:
  - Use the `websockets` library to implement a server on port `12307`.
  - Maintain a single active connection to the Chrome extension.
  - Implement the read loop that receives JSON and dispatches it to the handler or resolves pending `asyncio.Future` objects.
  - Mirror the `send_request` logic from `native_messaging.py`.

### 3. Update System Integration

- **`app/bridge-python/api/main.py`**:
  - Update `ServerState` to instantiate `WebSocketBridge` instead of `NativeMessagingBridge`.
- **`app/bridge-python/main.py`**:
  - Update the `main()` function to launch the `WebSocketBridge` server alongside the FastAPI server.
  - Since `WebSocketBridge.start()` will be a server loop, it should be run as an `asyncio.Task`.

### 4. Dependency Updates

- Add `websockets` to the project dependencies.

## Verification Plan

### 1. Unit & Integration Testing

- **New Test File**: `app/bridge-python/tests/test_websocket_bridge.py`
- **Test Cases**:
  - **Connectivity**: Verify the bridge starts and accepts a WebSocket connection.
  - **Unidirectional Messaging**: Verify `send_message` from bridge reaches the client.
  - **Request-Response Cycle**:
    - Bridge calls `send_request` $\rightarrow$ Client receives `requestId` $\rightarrow$ Client responds with `responseToRequestId` $\rightarrow$ Bridge resolves the future with the correct payload.
  - **End-to-End Flow**:
    - Start full bridge.
    - Use a test client to send the `start` command.
    - Call the `/ask-extension` HTTP endpoint and verify the response is routed through the WebSocket.

### 2. Manual Verification

- Run the bridge independently: `python app/bridge-python/main.py`.
- Use a WebSocket client (like `wscat` or a simple script) to send a `start` message and verify the bridge responds with `server_started`.
- Verify the log file at `~/.local/share/chrome-mcp/bridge.log` shows successful WebSocket connections.

## Critical Files

- `app/bridge-python/bridge/base.py` (New)
- `app/bridge-python/bridge/websocket_bridge.py` (New)
- `app/bridge-python/api/main.py`
- `app/bridge-python/main.py`
- `app/bridge-python/tests/test_websocket_bridge.py` (New)
