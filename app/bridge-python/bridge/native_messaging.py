import asyncio
import sys
import json
import struct
import uuid
import logging
from typing import Any, Optional, Dict, Callable, Awaitable
from schemas.shared import DEFAULT_REQUEST_TIMEOUT

logger = logging.getLogger("native-bridge")

class NativeMessagingBridge:
    """
    Handles the binary communication with the Chrome Extension using the
    Chrome Native Messaging protocol (4-byte LE length prefix).
    """
    MAX_MESSAGE_SIZE_BYTES = 16 * 1024 * 1024  # 16MB

    def __init__(self):
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._message_handler: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None
        self._running = False

    def set_message_handler(self, handler: Callable[[Dict[str, Any]], Awaitable[None]]):
        """Sets the callback function to handle incoming messages from the extension."""
        self._message_handler = handler

    async def start(self):
        """Starts the async reading loop from stdin."""
        self._running = True
        try:
            await self._read_loop()
        except asyncio.CancelledError:
            pass
        finally:
            await self.cleanup()

    async def _read_loop(self):
        """Reads from stdin and parses the 4-byte LE prefixed JSON messages."""
        loop = asyncio.get_event_loop()
        # We use run_in_executor for blocking stdin.read calls or use a stream reader
        # For Python 3.7+, asyncio.get_event_loop().connect_read_pipe is ideal but
        # complex for stdin. We'll use a thread-based reader for robustness with PyInstaller.

        while self._running:
            try:
                # 1. Read the 4-byte length header
                header = await loop.run_in_executor(None, self._read_exact, 4)
                if not header:
                    break

                length = struct.unpack('<I', header)[0]

                if length <= 0 or length > self.MAX_MESSAGE_SIZE_BYTES:
                    self.send_error(f"Invalid message length: {length}")
                    # Attempt to resync by clearing buffer (though stdin is a stream)
                    continue

                # 2. Read the JSON payload
                payload_bytes = await loop.run_in_executor(None, self._read_exact, length)
                if not payload_bytes:
                    break

                try:
                    message = json.loads(payload_bytes.decode('utf-8'))
                    logger.debug(f"<< Received {length} bytes from extension: {message}")
                    await self._handle_incoming_message(message)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse message: {e}")
                    self.send_error(f"Failed to parse message: {str(e)}")

            except Exception as e:
                logger.error(f"Error in read loop: {e}")
                break

    def _read_exact(self, n: int) -> Optional[bytes]:
        """Blocking helper to read exactly n bytes from stdin.buffer."""
        data = b''
        while len(data) < n:
            chunk = sys.stdin.buffer.read(n - len(data))
            if not chunk:
                return None
            data += chunk
        return data

    async def _handle_incoming_message(self, message: Dict[str, Any]):
        """Dispatches messages to pending requests or the main message handler."""
        if not isinstance(message, dict):
            self.send_error("Invalid message format: expected JSON object")
            return

        # Handle Response: If it's a response to a request we sent
        response_to_id = message.get("responseToRequestId")
        if response_to_id:
            future = self._pending_requests.pop(response_to_id, None)
            if future and not future.done():
                if "error" in message:
                    future.set_exception(RuntimeError(message["error"]))
                else:
                    future.set_result(message.get("payload"))
            return

        # Handle Directive/Request: Forward to the registered handler
        if self._message_handler:
            await self._message_handler(message)
        else:
            # If no handler is set, we might just log it or ignore it
            pass

    async def send_request(self, payload: Any, message_type: str = 'request_data', timeout: float = DEFAULT_REQUEST_TIMEOUT) -> Any:
        """
        Sends a request to the extension and waits for a response.
        """
        request_id = str(uuid.uuid4())
        future = asyncio.get_event_loop().create_future()
        self._pending_requests[request_id] = future

        self.send_message({
            "type": message_type,
            "payload": payload,
            "requestId": request_id
        })

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise TimeoutError(f"Request {request_id} timed out after {timeout}s")

    def send_message(self, message: Dict[str, Any]):
        """Sends a JSON message to the extension with the 4-byte LE length prefix."""
        try:
            payload_bytes = json.dumps(message).encode('utf-8')
            length = len(payload_bytes)
            header = struct.pack('<I', length)

            # Atomic write to stdout.buffer
            sys.stdout.buffer.write(header + payload_bytes)
            sys.stdout.buffer.flush()
            logger.debug(f">>> Sent {length} bytes to extension: {message}")
        except Exception as e:
            logger.error(f"Failed to send message: {e}")

    def send_error(self, error_message: str):
        """Sends an explicit error message to the extension."""
        self.send_message({
            "type": "error_from_native_host",
            "payload": {"message": error_message}
        })

    async def cleanup(self):
        """Cleans up pending requests and shuts down."""
        self._running = False
        for future in self._pending_requests.values():
            if not future.done():
                future.set_exception(RuntimeError("Native host is shutting down."))
        self._pending_requests.clear()
