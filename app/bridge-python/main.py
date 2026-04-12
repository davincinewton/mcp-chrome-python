import asyncio
import argparse
import logging
import os
import signal
import sys
from pathlib import Path
import uvicorn
from api.main import main_app as app, state
from logging_config import setup_logging

# Set up unified logging at module load time
setup_logging()
logger = logging.getLogger("mcp-entry")

# Note: Task references now stored in state object (state.http_task, state.ws_task)

async def start_http_server(port: int = 12306):
    """Start the FastAPI HTTP server."""
    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=port,
        log_level="info",
        lifespan="off"
    )
    server = uvicorn.Server(config)
    logger.info(f"Starting MCP HTTP/SSE Server on port {port}...")
    await server.serve()
    logger.info(f"HTTP server stopped on port {port}")


async def cleanup(timeout: float = 3.0) -> None:
    """
    Gracefully shutdown all running tasks.

    Args:
        timeout: Maximum time to wait for graceful shutdown before force kill.
    """
    logger.info("Starting graceful shutdown...")

    # Cancel WebSocket bridge task first (stop accepting new connections)
    if state.ws_task and not state.ws_task.done():
        logger.info("Stopping WebSocket bridge...")
        state.ws_task.cancel()
        try:
            await asyncio.wait_for(state.ws_task, timeout=timeout)
        except asyncio.CancelledError:
            logger.info("WebSocket bridge cancelled")
        except asyncio.TimeoutError:
            logger.warning("WebSocket bridge shutdown timed out, forcing")
            state.ws_task.cancel()

    # Cancel HTTP server task
    if state.http_task and not state.http_task.done():
        logger.info("Stopping HTTP server...")
        state.http_task.cancel()
        try:
            await asyncio.wait_for(state.http_task, timeout=timeout)
        except asyncio.CancelledError:
            logger.info("HTTP server cancelled")
        except asyncio.TimeoutError:
            logger.warning("HTTP server shutdown timed out, forcing")
            state.http_task.cancel()

    # Cleanup bridge resources
    try:
        await state.bridge.cleanup()
        logger.info("Bridge resources cleaned up")
    except Exception as e:
        logger.error(f"Error during bridge cleanup: {e}")

    logger.info("Graceful shutdown complete")


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
    import time

    logger.info("=" * 50)
    logger.info("MCP Chrome Bridge Starting...")
    logger.info("=" * 50)

    # Set up the bridge message handler
    state.bridge.set_message_handler(handle_bridge_message)

    # Record uptime start time
    state.uptime_start = time.time()

    # Start the HTTP server (non-blocking)
    logger.info("Starting HTTP server...")
    state.http_task = asyncio.create_task(start_http_server(12306))

    # Give HTTP server a moment to bind
    await asyncio.sleep(0.5)

    # Start the WebSocket Bridge
    # Since WebSocketBridge.start() is a long-running server loop,
    # we wrap it in a task or just await it as the final blocking call.
    logger.info("Starting WebSocket Bridge...")
    logger.info("Waiting for Chrome extension to connect via WebSocket...")
    logger.info("=" * 50)

    try:
        state.ws_task = asyncio.create_task(state.bridge.start())
        await state.ws_task
    except asyncio.CancelledError:
        # Expected during graceful shutdown - suppress this
        pass
    except Exception as e:
        logger.error(f"WebSocket Bridge encountered a fatal error: {e}")
    finally:
        # Trigger cleanup on any exit
        await cleanup()


def main_cli():
    """Handle CLI arguments and dispatch accordingly."""
    parser = argparse.ArgumentParser(description="MCP Chrome Bridge - Connect Chrome extension to AI assistants")
    parser.add_argument("--register", action="store_true", help=argparse.SUPPRESS)

    args = parser.parse_args()

    # --register is deprecated and no longer needed
    asyncio.run(main())


async def run_with_signal_handling():
    """Run the main function with proper signal handling for graceful shutdown."""
    loop = asyncio.get_running_loop()

    # Set up signal handlers for Unix-like systems
    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(handle_signal()))
    else:
        # Windows fallback: handle Ctrl+C via exception
        pass

    await main()


async def handle_signal():
    """Handle shutdown signals gracefully."""
    logger.info("\nReceived shutdown signal, cleaning up...")
    await cleanup(timeout=5.0)


if __name__ == "__main__":
    try:
        asyncio.run(run_with_signal_handling())
    except KeyboardInterrupt:
        # Expected during graceful shutdown - suppress this
        pass
