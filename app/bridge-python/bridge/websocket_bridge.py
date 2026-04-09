import asyncio
import json
import time
import uuid
import logging
from typing import Any, Dict, Optional, Callable, Awaitable, Tuple
import websockets
from .base import ExtensionBridge

logger = logging.getLogger("ws-bridge")

# Constants for memory leak prevention
MAX_PENDING_REQUESTS = 1000
STALE_REQUEST_TIMEOUT = 300  # 5 minutes

class WebSocketBridge(ExtensionBridge):
    """
    Implements the bridge communication using WebSockets.
    Listens for a connection from the Chrome Extension.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 12307):
        self.host = host
        self.port = port
        self._connection: Optional[websockets.WebSocketServerProtocol] = None
        # Store (future, timestamp) tuples for age tracking
        self._pending_requests: Dict[str, Tuple[asyncio.Future, float]] = {}
        self._message_handler: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None
        self._server: Optional[websockets.server.WebSocketServer] = None
        self._running = False
        self._connection_lock = asyncio.Lock()

    def set_message_handler(self, handler: Callable[[Dict[str, Any]], Awaitable[None]]) -> None:
        self._message_handler = handler

    async def start(self) -> None:
        """Starts the WebSocket server and manages the extension connection."""
        self._running = True
        logger.info(f"Starting WebSocket server on ws://{self.host}:{self.port}...")

        async with websockets.serve(self._handle_connection, self.host, self.port) as server:
            self._server = server
            logger.info("Server is listening. Waiting for extension to connect...")
            # Keep the start method running while the server is active
            await asyncio.Future()  # Run forever

    async def _handle_connection(self, websocket: websockets.WebSocketServerProtocol):
        """Handles the lifecycle of a single WebSocket connection."""
        from api.main import state

        async with self._connection_lock:
            logger.info(f"Extension connected from {websocket.remote_address}")

            # Close any existing connection before accepting a new one
            if self._connection is not None:
                logger.info("Closing previous connection before accepting new one")
                state.ws_connected = False
                try:
                    await self._connection.close()
                except Exception:
                    pass

            self._connection = websocket
            state.ws_connected = True
            state.last_activity = time.time()

        try:
            async for message in websocket:
                await self._process_incoming_message(message)
        except websockets.ConnectionClosed:
            logger.info("Extension connection closed")
        except Exception as e:
            logger.error(f"Error in connection loop: {e}")
        finally:
            async with self._connection_lock:
                self._connection = None
                state.ws_connected = False
            # Fail any pending requests on disconnect
            for future in self._pending_requests.values():
                if not future.done():
                    future.set_exception(RuntimeError("Extension disconnected"))
            self._pending_requests.clear()

    async def _process_incoming_message(self, raw_message: str):
        """Parses and dispatches incoming JSON messages."""
        from api.main import state

        try:
            message = json.loads(raw_message)
            state.last_activity = time.time()
            logger.debug(f"<<< Received: {json.dumps(message)}")

            if not isinstance(message, dict):
                logger.warning("Received non-object JSON")
                return

            # Handle Response
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
                return

            # Handle Directive/Request
            if self._message_handler:
                await self._message_handler(message)
            else:
                logger.warning("No message handler registered")

        except json.JSONDecodeError:
            logger.error(f"Failed to decode JSON: {raw_message}")
        except Exception as e:
            logger.error(f"Error processing message: {e}")

    async def send_message(self, message: Dict[str, Any]) -> None:
        """Sends a JSON message to the connected extension."""
        from api.main import state

        if not self._connection:
            logger.warning("Cannot send message: No extension connected")
            return

        try:
            payload = json.dumps(message)
            state.last_activity = time.time()
            logger.debug(f">>> Sent: {payload}")
            await self._connection.send(payload)
        except Exception as e:
            logger.error(f"Error sending message: {e}")

    async def send_request(self, payload: Any, message_type: str = 'request_data', timeout: float = 30.0) -> Any:
        """Sends a request and waits for a response using requestId."""
        if not self._connection:
            raise RuntimeError("No extension connected")

        # Check pending request limit
        if len(self._pending_requests) >= MAX_PENDING_REQUESTS:
            logger.warning(f"Too many pending requests: {len(self._pending_requests)} (max: {MAX_PENDING_REQUESTS})")
            raise RuntimeError(f"Too many pending requests (max: {MAX_PENDING_REQUESTS})")

        request_id = str(uuid.uuid4())
        future = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = (future, time.time())

        message = {
            "type": message_type,
            "payload": payload,
            "requestId": request_id
        }

        await self.send_message(message)

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise TimeoutError(f"Request {request_id} timed out after {timeout}s")

    async def cleanup(self) -> None:
        """Gracefully shuts down the WebSocket server."""
        from api.main import state

        self._running = False
        state.ws_connected = False

        # Clean up stale requests
        now = time.time()
        stale_ids = [
            req_id for req_id, (future, timestamp) in self._pending_requests.items()
            if now - timestamp > STALE_REQUEST_TIMEOUT
        ]
        if stale_ids:
            logger.warning(f"Cleaning up {len(stale_ids)} stale pending requests")
            for req_id in stale_ids:
                future, _ = self._pending_requests.pop(req_id)
                if not future.done():
                    future.set_exception(RuntimeError("Request timed out"))

        if self._server:
            self._server.close()
            await self._server.wait_closed()
        logger.info("Server shut down")
