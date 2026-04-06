#!/usr/bin/env python3
"""
Manual WebSocket client to test the bridge.
Usage: ./test_client.py [command]
Commands: start, ping, stop
"""

import asyncio
import websockets
import json
import sys

HOST = "ws://127.0.0.1:12307"

async def send_start():
    """Send 'start' command to begin the bridge."""
    async with websockets.connect(HOST) as ws:
        print(f"[Client] Connected to {HOST}")

        msg = {"type": "start", "payload": {"port": 12306}}
        print(f"[Client] Sending: {json.dumps(msg)}")
        await ws.send(json.dumps(msg))

        resp = await ws.recv()
        print(f"[Client] Received: {resp}")

async def send_ping():
    """Send 'ping' command to check connection."""
    async with websockets.connect(HOST) as ws:
        print(f"[Client] Connected to {HOST}")

        msg = {"type": "ping_from_extension"}
        print(f"[Client] Sending: {json.dumps(msg)}")
        await ws.send(json.dumps(msg))

        resp = await ws.recv()
        print(f"[Client] Received: {resp}")

async def send_stop():
    """Send 'stop' command to stop the bridge."""
    async with websockets.connect(HOST) as ws:
        print(f"[Client] Connected to {HOST}")

        msg = {"type": "stop"}
        print(f"[Client] Sending: {json.dumps(msg)}")
        await ws.send(json.dumps(msg))

        resp = await ws.recv()
        print(f"[Client] Received: {resp}")

async def main(command):
    if command == "start":
        await send_start()
    elif command == "ping":
        await send_ping()
    elif command == "stop":
        await send_stop()
    else:
        print(f"Unknown command: {command}")
        print("Usage: ./test_client.py [start|ping|stop]")
        sys.exit(1)

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    asyncio.run(main(cmd))
