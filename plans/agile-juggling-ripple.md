# Consolidate Server State Management

## Context

The Python bridge has multiple, unsynchronized state tracking mechanisms:

1. **`state.is_running`** (in `api/main.py` ServerState) - Tracks server running state from extension perspective
2. **`WebSocketBridge._running`** (in `bridge/websocket_bridge.py`) - Internal WebSocket bridge state, NOT synchronized with `state.is_running`
3. **`http_task`/`ws_task`** (in `main.py`) - Task references for graceful shutdown, separate from `state.server_tasks` which tracks named MCP sessions
4. **`shutdown_event`** (in `main.py`) - Defined but never used

This creates potential for inconsistent state and makes reasoning about server health difficult.

## Approach

### Recommended: Extend ServerState to Centralize All State

Instead of creating a new unified state class, extend the existing `ServerState` in `api/main.py` to include:

- Task references (`http_task`, `ws_task`)
- Connection status (`ws_connected`)
- Timestamps (`uptime_start`, `last_activity`)

This leverages the existing singleton `state` that is already imported in `main.py`.

### Changes Summary

**1. Extend `ServerState` class** (`api/main.py`)

Add these properties:

```python
class ServerState:
    def __init__(self):
        self.bridge = WebSocketBridge()
        self.mcp_server = ChromeMcpServer(self.bridge)
        self.default_transport: StreamableHTTPServerTransport | None = None
        self.default_server_task: asyncio.Task | None = None
        self.sessions: dict[str, StreamableHTTPServerTransport] = {}
        self.server_tasks: dict[str, asyncio.Task] = {}

        # Server lifecycle state
        self.is_running: bool = False  # Extension start/stop status
        self.http_task: asyncio.Task | None = None  # HTTP server task
        self.ws_task: asyncio.Task | None = None  # WebSocket server task
        self.ws_connected: bool = False  # WebSocket connection status
        self.uptime_start: float | None = None  # Server start timestamp
        self.last_activity: float | None = None  # Last message timestamp
```

**2. Remove duplicate globals** (`main.py`)

Remove:

```python
http_task: asyncio.Task | None = None
ws_task: asyncio.Task | None = None
shutdown_event = asyncio.Event()
```

**3. Update task assignment** (`main.py`)

Change from local `http_task`/`ws_task` to `state.http_task`/`state.ws_task`:

```python
# In main():
state.http_task = asyncio.create_task(start_http_server(12306))
state.ws_task = asyncio.create_task(state.bridge.start())
```

**4. Update cleanup** (`main.py`)

Reference tasks from state:

```python
if state.ws_task and not state.ws_task.done():
    state.ws_task.cancel()
    ...
if state.http_task and not state.http_task.done():
    state.http_task.cancel()
    ...
```

**5. Add activity tracking** (`bridge/websocket_bridge.py`)

Update `last_activity` and `ws_connected` on connection events:

```python
# In _handle_connection():
self._running = True
state.ws_connected = True
state.last_activity = time.time()

# In cleanup():
state.ws_connected = False
```

**6. Update imports** (`main.py`)

Remove unused `shutdown_event` reference.

## Files to Modify

| File                         | Changes                                             |
| ---------------------------- | --------------------------------------------------- |
| `api/main.py`                | Extend `ServerState` class with new properties      |
| `main.py`                    | Remove local state vars, use `state.*` instead      |
| `bridge/websocket_bridge.py` | Update `ws_connected` and `last_activity` on events |

## Verification

1. Start the bridge: `python main.py`
2. Verify no import errors
3. Check that `state.http_task` and `state.ws_task` are set correctly
4. Verify cleanup properly cancels tasks via state references
5. Run existing tests: `pytest tests/`
