"""
MCP Streamable HTTP Server for Chrome MCP Bridge.
Uses streamable-http transport with JSON responses.
"""
import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.applications import Starlette
from starlette.responses import Response, JSONResponse
from starlette.requests import Request as StarletteRequest
from starlette.routing import Route
from starlette.types import Scope, Receive, Send

from mcp.server.streamable_http import StreamableHTTPServerTransport

from bridge.websocket_bridge import WebSocketBridge
from mcp_server_logic import ChromeMcpServer
from schemas.shared import EXTENSION_REQUEST_TIMEOUT

logger = logging.getLogger("mcp-api")


class ServerState:
    def __init__(self):
        self.bridge = WebSocketBridge()
        self.mcp_server = ChromeMcpServer(self.bridge)
        # Default transport for stateless MCP interactions
        self.default_transport: StreamableHTTPServerTransport | None = None
        self.default_server_task: asyncio.Task | None = None
        # Named sessions for clients that want session persistence
        self.sessions: dict[str, StreamableHTTPServerTransport] = {}
        self.server_tasks: dict[str, asyncio.Task] = {}

        # Server lifecycle state
        self.is_running: bool = False  # Extension start/stop status
        self.http_task: asyncio.Task | None = None  # HTTP server task
        self.ws_task: asyncio.Task | None = None  # WebSocket server task
        self.ws_connected: bool = False  # WebSocket connection status
        self.uptime_start: float | None = None  # Server start timestamp
        self.last_activity: float | None = None  # Last message timestamp


state = ServerState()


async def mcp_handler(scope: Scope, receive: Receive, send: Send):
    """ASGI handler for MCP streamable-http endpoint."""
    request = StarletteRequest(scope)
    method = scope.get("method", "")
    session_id = request.headers.get("mcp-session-id")

    if method == "DELETE":
        # Handle DELETE
        if not session_id or session_id not in state.sessions:
            response = Response(
                '{"error":"Invalid session"}',
                status_code=400,
                media_type="application/json",
            )
            await response(scope, receive, send)
            return

        transport = state.sessions.pop(session_id, None)
        if transport:
            await transport.close()

        task = state.server_tasks.pop(session_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        logger.info(f"Session deleted: {session_id}")
        response = Response(status_code=204)
        await response(scope, receive, send)
        return

    # Check for named session
    if session_id and session_id in state.sessions:
        transport = state.sessions[session_id]
    elif session_id:
        # Invalid session
        response = Response(
            '{"error":"Invalid session"}',
            status_code=400,
            media_type="application/json",
        )
        await response(scope, receive, send)
        return
    else:
        # Use default transport for stateless MCP
        if state.default_transport is None:
            # Create default transport on first request
            transport = StreamableHTTPServerTransport(
                mcp_session_id=None,
                is_json_response_enabled=True,
            )
            state.default_transport = transport

            async def run_default_server():
                async with transport.connect() as (read_stream, write_stream):
                    await state.mcp_server.server.run(
                        read_stream=read_stream,
                        write_stream=write_stream,
                        initialization_options=state.mcp_server.server.create_initialization_options(),
                    )

            state.default_server_task = asyncio.create_task(run_default_server())
            # Give the task a moment to enter the connect() context
            await asyncio.sleep(0.05)
        transport = state.default_transport

    # Let transport handle the request directly using ASGI interface
    await transport.handle_request(
        scope=scope,
        receive=receive,
        send=send,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[API] Starting MCP FastAPI application")
    yield
    print("[API] Shutting down")
    # Clean up default server task
    if state.default_server_task:
        state.default_server_task.cancel()
        try:
            await state.default_server_task
        except asyncio.CancelledError:
            pass
    # Clean up all server tasks
    for task in state.server_tasks.values():
        task.cancel()
    await asyncio.gather(*state.server_tasks.values(), return_exceptions=True)
    # Close default transport
    if state.default_transport:
        await state.default_transport.close()
    # Close all session transports
    for transport in state.sessions.values():
        await transport.close()
    await state.bridge.cleanup()


# Create main FastAPI app
app = FastAPI(title="Chrome MCP WebSocket Bridge", lifespan=lifespan)

# Custom CORS config that allows requests with no origin (e.g., curl, server-to-server)
# This matches the Node.js implementation
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_origin_regex=r".*",  # Allow any origin including none
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


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

    # Get pending requests count
    pending_requests = 0
    if hasattr(state.bridge, '_pending_requests'):
        pending_requests = len(state.bridge._pending_requests)

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
            "pending_requests": pending_requests,
            "active_sessions": len(state.sessions)
        }
    }


@app.get("/ask-extension")
async def ask_extension(data: str = __import__("fastapi").Query(...)):
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if not state.is_running:
        raise HTTPException(status_code=500, detail="Server not running")

    try:
        result = await state.bridge.send_request(
            parsed, message_type="process_data", timeout=EXTENSION_REQUEST_TIMEOUT
        )
        return {"status": "success", "data": result}
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Timeout")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Use FastAPI's route replacement to add raw ASGI handler
# Remove any existing /mcp routes first
app.router.routes = [r for r in app.router.routes if not hasattr(r, 'path') or '/mcp' not in str(r.path)]

# Add raw ASGI route using Starlette's Route with callable endpoint
from starlette.routing import Route as StarletteRoute

# Route doesn't work with ASGI callables, so use a different approach
# Mount a Starlette app that handles /mcp

from starlette.middleware import Middleware

# Create a composite app that handles /mcp separately
class CompositeApp:
    """Composite app that routes /mcp to mcp_handler, everything else to FastAPI."""

    def __init__(self, fastapi_app):
        self.fastapi_app = fastapi_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http" and scope["path"] == "/mcp":
            await mcp_handler(scope, receive, send)
        else:
            await self.fastapi_app(scope, receive, send)


# Wrap the FastAPI app with our composite handler
composite_app = CompositeApp(app)

# Replace the uvicorn app reference
import sys
original_app = app
app = composite_app

# For uvicorn to work properly, we need to export the composite app
# Let's create a module-level reference
main_app = composite_app