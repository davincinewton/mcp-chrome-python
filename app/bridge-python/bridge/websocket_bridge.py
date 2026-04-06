import asyncio
import json
import uuid
import logging
from typing import Any, Dict, Optional, Callable, Awaitable
import websockets
from .base import ExtensionBridge

logger = logging.getLogger("ws-bridge")

class WebSocketBridge(ExtensionBridge):
    """
    Implements the bridge communication using WebSockets.
    Listens for a connection from the Chrome Extension.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 12307):
        self.host = host
        self.port = port
        self._connection: Optional[websockets.WebSocketServerProtocol] = None
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._message_handler: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None
        self._server: Optional[websockets.server.WebSocketServer] = None
        self._running = False

    def set_message_handler(self, handler: Callable[[Dict[str, Any]], Awaitable[None]]) -> None:
        self._message_handler = handler

    async def start(self) -> None:
        """Starts the WebSocket server and manages the extension connection."""
        self._running = True
        print(f"[WS Bridge] Starting WebSocket server on ws://{self.host}:{self.port}...")

        async with websockets.serve(self._handle_connection, self.host, self.port) as server:
            self._server = server
            print(f"[WS Bridge] Server is listening. Waiting for extension to connect...")
            # Keep the start method running while the server is active
            await asyncio.Future()  # Run forever

    async def _handle_connection(self, websocket: websockets.WebSocketServerProtocol):
        """Handles the lifecycle of a single WebSocket connection."""
        print(f"[WS Bridge] Extension connected from {websocket.remote_address}")
        self._connection = websocket

        try:
            async for message in websocket:
                await self._process_incoming_message(message)
        except websockets.ConnectionClosed:
            print(f"[WS Bridge] Extension connection closed")
        except Exception as e:
            print(f"[WS Bridge] Error in connection loop: {e}")
        finally:
            self._connection = None
            # Fail any pending requests on disconnect
            for future in self._pending_requests.values():
                if not future.done():
                    future.set_exception(RuntimeError("Extension disconnected"))
            self._pending_requests.clear()

    async def _process_incoming_message(self, raw_message: str):
        """Parses and dispatches incoming JSON messages."""
        try:
            message = json.loads(raw_message)
            print(f"[WS Bridge] <<< Received: {json.dumps(message)}")

            if not isinstance(message, dict):
                print("[WS Bridge] Warning: Received non-object JSON")
                return

            # Handle Response
            response_to_id = message.get("responseToRequestId")
            if response_to_id:
                future = self._pending_requests.pop(response_to_id, None)
                if future and not future.done():
                    if "error" in message:
                        future.set_exception(RuntimeError(message["error"]))
                    else:
                        future.set_result(message.get("payload"))
                return

            # Handle Directive/Request
            if self._message_handler:
                await self._message_handler(message)
            else:
                print("[WS Bridge] No message handler registered")

        except json.JSONDecodeError:
            print(f"[WS Bridge] Error: Failed to decode JSON: {raw_message}")
        except Exception as e:
            print(f"[WS Bridge] Error processing message: {e}")

    async def send_message(self, message: Dict[str, Any]) -> None:
        """Sends a JSON message to the connected extension."""
        if not self._connection:
            print("[WS Bridge] Cannot send message: No extension connected")
            return

        try:
            payload = json.dumps(message)
            print(f"[WS Bridge] >>> Sent: {payload}")
            await self._connection.send(payload)
        except Exception as e:
            print(f"[WS Bridge] Error sending message: {e}")

    async def send_request(self, payload: Any, message_type: str = 'request_data', timeout: float = 30.0) -> Any:
        """Sends a request and waits for a response using requestId."""
        if not self._connection:
            raise RuntimeError("No extension connected")

        request_id = str(uuid.uuid4())
        future = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future

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
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        print("[WS Bridge] Server shut down")
