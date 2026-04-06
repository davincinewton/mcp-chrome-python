import asyncio
import argparse
import logging
import os
import sys
from pathlib import Path
import uvicorn
from api.main import main_app as app, state
from utils import register_binary

# Set up log file in user's local data directory
# Use environment variable with fallback to avoid crashes if $HOME is not set
def get_log_dir():
    """Get log directory, with fallback for when running from Chrome."""
    home = os.environ.get("HOME") or os.environ.get("USERPROFILE") or "/tmp"
    if home == "/tmp":
        # Fallback for missing env vars - use a known path
        try:
            home = str(Path.home())
        except Exception:
            home = "/tmp"
    return Path(home) / ".local" / "share" / "chrome-mcp"

LOG_DIR = get_log_dir()
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = str(LOG_DIR / "bridge.log")  # Use string path for compatibility

# Custom handler that writes to both file and stdout with explicit flushing
class DualHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        # Write to stdout with flush
        print(msg, flush=True)
        # Write to file with flush
        try:
            with open(LOG_FILE, 'a') as f:
                f.write(msg + '\n')
                f.flush()
        except Exception as e:
            print(f"Failed to write to log file: {e}", file=sys.stderr, flush=True)

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("mcp-entry")
logger.handlers.clear()
logger.addHandler(DualHandler())
logger.setLevel(logging.DEBUG)
logger.info(f"Chrome MCP Bridge starting, log file: {LOG_FILE}")

# Server state
http_server: uvicorn.Server | None = None
http_server_running = False

async def start_http_server(port: int = 12306):
    """Start the FastAPI HTTP server."""
    global http_server, http_server_running

    if http_server_running:
        logger.info(f"HTTP server already running on port {port}")
        return

    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=port,
        log_level="info",
        lifespan="off"
    )
    http_server = uvicorn.Server(config)
    logger.info(f"Starting MCP HTTP/SSE Server on port {port}...")
    await http_server.serve()
    http_server_running = True
    logger.info(f"HTTP server is now running on port {port}")

async def stop_http_server():
    """Stop the FastAPI HTTP server."""
    global http_server, http_server_running

    if http_server and http_server_running:
        logger.info("Stopping HTTP server...")
        http_server.should_exit = True
        await asyncio.sleep(0.5)  # Give it time to shut down
        http_server_running = False
        logger.info("HTTP server stopped")

async def handle_bridge_message(message: dict):
    """Handle messages from the Chrome extension via Native Messaging."""
    logger.debug(f"<<< Received message from extension: {message}")

    msg_type = message.get("type")
    payload = message.get("payload", {})

    if msg_type == "start":
        port = payload.get("port", 12306)
        logger.info(f"Received 'start' command from extension (port: {port})")
        state.is_running = True
        # Protocol: must use 'server_started' not 'started'
        response = {"type": "server_started", "payload": {"port": port}}
        await state.bridge.send_message(response)
        logger.debug(f">>> Sent response to extension: {response}")

    elif msg_type == "stop":
        logger.info("Received 'stop' command from extension")
        state.is_running = False
        # Note: HTTP/MCP server keeps running; just respond with server_stopped
        response = {"type": "server_stopped"}
        await state.bridge.send_message(response)
        logger.debug(f">>> Sent response to extension: {response}")

    elif msg_type == "ping_from_extension":
        logger.debug("Received 'ping_from_extension'")
        response = {"type": "pong_to_extension"}
        await state.bridge.send_message(response)
        logger.debug(f">>> Sent response to extension: {response}")

    elif "requestId" in message:
        # This is a request that expects a response - log it
        logger.debug(f"Received request with ID: {message.get('requestId')}, type: {msg_type}")

    else:
        logger.warning(f"Unhandled message type: {msg_type}")

async def main():
    """
    The main entry point for the Python Bridge.
    Starts BOTH the WebSocket Bridge and HTTP server.
    """
    logger.info("=" * 50)
    logger.info("Chrome MCP WebSocket Bridge Starting...")
    logger.info("=" * 50)

    # Set up the bridge message handler
    state.bridge.set_message_handler(handle_bridge_message)

    # Start the HTTP server (non-blocking)
    logger.info("Starting HTTP server...")
    http_task = asyncio.create_task(start_http_server(12306))

    # Give HTTP server a moment to bind
    await asyncio.sleep(0.5)

    # Start the WebSocket Bridge
    # Since WebSocketBridge.start() is a long-running server loop,
    # we wrap it in a task or just await it as the final blocking call.
    logger.info("Starting WebSocket Bridge on port 12307...")
    logger.info("Waiting for Chrome extension to connect via WebSocket...")
    logger.info("=" * 50)

    try:
        await state.bridge.start()
    except Exception as e:
        logger.error(f"WebSocket Bridge encountered a fatal error: {e}")


def main_cli():
    """Handle CLI arguments and dispatch accordingly."""
    parser = argparse.ArgumentParser(description="Chrome MCP Native Server")
    parser.add_argument("--register", action="store_true", help="Register the binary with Chrome and exit")

    args = parser.parse_args()

    if args.register:
        register_binary()
    else:
        asyncio.run(main())

if __name__ == "__main__":
    try:
        main_cli()
    except KeyboardInterrupt:
        logger.info("\nShutting down...")
        pass
