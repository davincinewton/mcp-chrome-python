# Server Improvements: Logging, Health Check, Validation, and Memory Safety

## Context

The Python bridge has several areas for improvement:

1. **Logging inconsistency** - Multiple `logging.basicConfig()` calls, different log levels, custom handler only in `main.py`
2. **Minimal health check** - `/ping` returns static "ok" without connection status
3. **No tool argument validation** - Arguments passed through unvalidated to extension
4. **Potential memory leak** - `_pending_requests` dict can grow unbounded

## Approach

### 4. Unified Logging Configuration

**Create:** `logging_config.py`

```python
"""Unified logging configuration for the Chrome MCP Bridge."""
import logging
import os
import sys
from pathlib import Path
from typing import Optional


def get_log_path() -> Path:
    """Get log file path in user's data directory."""
    home = os.environ.get("HOME") or os.environ.get("USERPROFILE") or "/tmp"
    if home == "/tmp":
        try:
            home = str(Path.home())
        except Exception:
            home = "/tmp"
    log_dir = Path(home) / ".local" / "share" / "chrome-mcp"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "bridge.log"


class DualHandler(logging.Handler):
    """Custom handler that writes to both file and stdout."""

    def __init__(self, log_file: Optional[str] = None):
        super().__init__()
        self.log_file = log_file or str(get_log_path())

    def emit(self, record: logging.LogRecord):
        msg = self.format(record)
        # Write to stdout with flush
        print(msg, flush=True)
        # Write to file with flush
        try:
            with open(self.log_file, 'a') as f:
                f.write(msg + '\n')
                f.flush()
        except Exception:
            print(f"Failed to write to log file", file=sys.stderr, flush=True)


def setup_logging(level: Optional[str] = None, log_file: Optional[str] = None):
    """
    Set up unified logging configuration.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR). Defaults to env LOG_LEVEL or INFO.
        log_file: Path to log file. Defaults to user data directory.
    """
    # Get log level
    if level is None:
        level = os.environ.get("LOG_LEVEL", "INFO").upper()

    log_level = getattr(logging, level.upper(), logging.INFO)

    # Get log file path
    file_path = log_file or str(get_log_path())

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(log_level)

    # Add dual handler (stdout + file)
    handler = DualHandler(file_path)
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    root_logger.addHandler(handler)

    # Set default level for all existing loggers
    for logger_name in logging.root.manager.loggerDict:
        logger = logging.getLogger(logger_name)
        if isinstance(logger, logging.Logger):
            logger.setLevel(log_level)
```

**Changes:**

| File                         | Changes                                                                               |
| ---------------------------- | ------------------------------------------------------------------------------------- |
| `main.py`                    | Import `setup_logging`; Call at startup; Remove `DualHandler` class and `basicConfig` |
| `api/main.py`                | Remove `logging.basicConfig()`; Just use `logging.getLogger()`                        |
| `mcp_server_logic.py`        | Remove `logging.basicConfig()`; Just use `logging.getLogger()`                        |
| `bridge/websocket_bridge.py` | Replace `print()` statements with logger calls                                        |

---

### 5. Enhanced Health Check Endpoint

**Modify:** `/ping` endpoint in `api/main.py`

```python
@app.get("/ping")
async def ping():
    """Enhanced health check with connection status and metrics."""
    import time

    # Calculate uptime
    uptime_seconds = None
    if state.uptime_start:
        uptime_seconds = time.time() - state.uptime_start

    # Calculate time since last activity
    last_activity_ago = None
    if state.last_activity:
        last_activity_ago = time.time() - state.last_activity

    # Determine overall status
    status = "healthy"
    if not state.ws_connected and state.uptime_start:
        # Server running but no extension connection
        status = "degraded"
    if state.http_task and state.http_task.done():
        status = "unhealthy"

    return {
        "status": status,
        "timestamp": time.time(),
        "uptime_seconds": round(uptime_seconds, 2) if uptime_seconds else None,
        "last_activity_ago_seconds": round(last_activity_ago, 2) if last_activity_ago else None,
        "services": {
            "http": "running" if state.http_task and not state.http_task.done() else "stopped",
            "websocket": "connected" if state.ws_connected else "disconnected",
            "extension": "running" if state.is_running else "stopped"
        },
        "metrics": {
            "pending_requests": len(state.bridge._pending_requests) if hasattr(state.bridge, '_pending_requests') else 0,
            "active_sessions": len(state.sessions)
        }
    }
```

**Optional:** Add `/health` endpoint with same info for clients preferring separate health check.

---

### 8. Tool Argument Validation

**Create:** `schemas/tool_arguments.py`

Pydantic models for tools with complex arguments. Start with highest-complexity tools:

```python
"""Pydantic models for tool argument validation."""
from typing import Any, Dict, Optional, List, Literal, Union
from pydantic import BaseModel, Field, field_validator


class Coordinates(BaseModel):
    x: float
    y: float


class Modifiers(BaseModel):
    altKey: bool = False
    ctrlKey: bool = False
    metaKey: bool = False
    shiftKey: bool = False


class ChromeComputerArgs(BaseModel):
    """Arguments for chrome_computer tool."""
    action: Literal[
        "left_click", "right_click", "double_click", "triple_click",
        "left_click_drag", "scroll", "scroll_to", "type", "key",
        "fill", "fill_form", "hover", "wait", "resize_page", "zoom", "screenshot"
    ]
    tabId: Optional[int] = None
    background: bool = False
    ref: Optional[str] = None
    coordinates: Optional[Coordinates] = None
    startCoordinates: Optional[Coordinates] = None
    startRef: Optional[str] = None
    scrollDirection: Optional[Literal["up", "down", "left", "right"]] = None
    scrollAmount: Optional[int] = Field(None, ge=1, le=10)
    text: Optional[str] = None
    repeat: Optional[int] = Field(None, ge=1, le=100)
    modifiers: Optional[Modifiers] = None
    # ... other fields


class ChromeReadPageArgs(BaseModel):
    """Arguments for chrome_read_page tool."""
    filter: Optional[Literal["interactive"]] = None
    depth: Optional[int] = Field(None, ge=0)
    refId: Optional[str] = None
    tabId: Optional[int] = None
    windowId: Optional[int] = None


# Add more models as needed
```

**Modification:** `mcp_server_logic.py`

```python
from schemas.tool_arguments import (
    ChromeComputerArgs, ChromeReadPageArgs,
    # ... other models
)

TOOL_VALIDATORS = {
    "chrome_computer": ChromeComputerArgs,
    "chrome_read_page": ChromeReadPageArgs,
    # ... other tools
}

async def _handle_tool_call(self, name: str, args: Dict[str, Any]) -> CallToolResult:
    try:
        # Validate arguments if validator exists
        validator = TOOL_VALIDATORS.get(name)
        if validator:
            try:
                validated_args = validator(**args)
                args = validated_args.model_dump()
            except ValidationError as e:
                return CallToolResult(
                    content=[TextContent(type="text", text=f"Invalid arguments: {e}")],
                    isError=True
                )

        # ... rest of tool call logic
```

---

### 9. Prevent Memory Leak in Pending Requests

**Modification:** `bridge/websocket_bridge.py`

```python
import time

class WebSocketBridge(ExtensionBridge):
    MAX_PENDING_REQUESTS = 1000
    STALE_REQUEST_TIMEOUT = 300  # 5 minutes

    def __init__(self, host: str = "127.0.0.1", port: int = 12307):
        # ... existing init
        self._pending_requests: Dict[str, tuple[asyncio.Future, float]] = {}  # Store (future, timestamp)

    async def send_request(self, payload: Any, message_type: str = 'request_data', timeout: float = 30.0) -> Any:
        if not self._connection:
            raise RuntimeError("No extension connected")

        # Check limit
        if len(self._pending_requests) >= self.MAX_PENDING_REQUESTS:
            logger.warning(f"Too many pending requests: {len(self._pending_requests)}")
            raise RuntimeError(f"Too many pending requests (max: {self.MAX_PENDING_REQUESTS})")

        request_id = str(uuid.uuid4())
        future = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = (future, time.time())

        # ... rest of send_request

    async def _process_incoming_message(self, raw_message: str):
        # ... existing parsing

        response_to_id = message.get("responseToRequestId")
        if response_to_id:
            entry = self._pending_requests.pop(response_to_id, None)
            if entry:
                future, _ = entry  # Extract future, discard timestamp
                if not future.done():
                    if "error" in message:
                        future.set_exception(RuntimeError(message["error"]))
                    else:
                        future.set_result(message.get("payload"))
            else:
                logger.warning(f"Response for unknown request ID: {response_to_id}")

    def cleanup(self) -> None:
        """Clean up stale requests periodically."""
        now = time.time()
        stale_ids = [
            req_id for req_id, (future, timestamp) in self._pending_requests.items()
            if now - timestamp > self.STALE_REQUEST_TIMEOUT
        ]
        if stale_ids:
            logger.warning(f"Cleaning up {len(stale_ids)} stale pending requests")
            for req_id in stale_ids:
                future, _ = self._pending_requests.pop(req_id)
                if not future.done():
                    future.set_exception(RuntimeError("Request timed out"))
```

---

## Files to Modify

| File                         | Changes                                                        |
| ---------------------------- | -------------------------------------------------------------- |
| `logging_config.py`          | **NEW** - Unified logging setup                                |
| `main.py`                    | Use `setup_logging()`; Remove `DualHandler` class              |
| `api/main.py`                | Remove `basicConfig()`; Enhance `/ping` endpoint               |
| `mcp_server_logic.py`        | Remove `basicConfig()`; Add validation                         |
| `bridge/websocket_bridge.py` | Replace `print()` with logger; Add limits and cleanup          |
| `schemas/tool_arguments.py`  | **NEW** - Pydantic validators                                  |
| `schemas/shared.py`          | Add constants: `MAX_PENDING_REQUESTS`, `STALE_REQUEST_TIMEOUT` |

---

## Verification

1. **Logging:** Start server, verify logs appear in both stdout and file
2. **Health:** `curl http://127.0.0.1:12306/ping` - check response structure
3. **Validation:** Call tool with invalid args - should return error
4. **Memory:** Send >1000 pending requests - should reject with error
