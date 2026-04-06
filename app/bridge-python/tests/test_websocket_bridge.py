import asyncio
import json
import websockets
import sys
import os

# Ensure we're importing from the bridge-python root directory
script_dir = os.path.dirname(os.path.abspath(__file__))
bridge_root = os.path.dirname(script_dir)
sys.path.insert(0, bridge_root)

from main import state, start_http_server, handle_bridge_message, stop_http_server

async def test_websocket_bridge_end_to_end():
    print("[TEST] Starting end-to-end WebSocket bridge test...")

    # 1. Setup: Set up the handler manually
    state.bridge.set_message_handler(handle_bridge_message)

    # Start HTTP server in background
    print("[TEST] Starting HTTP server on port 12306...")
    http_task = asyncio.create_task(start_http_server(12306))

    # Start WebSocket server in background
    print("[TEST] Starting WebSocket server on port 12307...")
    ws_task = asyncio.create_task(state.bridge.start())

    await asyncio.sleep(1)  # Give servers time to start

    try:
        # 2. Connect a mock extension client
        print("[TEST] Connecting WebSocket client...")
        async with websockets.connect("ws://127.0.0.1:12307") as websocket:
            print("[TEST] Connected to bridge")

            # 3. Test 'start' command (Extension -> Bridge)
            print("[TEST] Sending 'start' command...")
            start_msg = json.dumps({"type": "start", "payload": {"port": 12306}})
            await websocket.send(start_msg)

            response = await websocket.recv()
            resp_json = json.loads(response)
            print(f"[TEST] Received response: {resp_json}")
            assert resp_json["type"] == "server_started", f"Expected server_started, got {resp_json}"
            assert state.is_running is True, "state.is_running should be True after start"

            # 4. Test 'send_request' (Bridge -> Extension -> Bridge)
            print("[TEST] Testing request-response cycle...")
            test_payload = {"action": "get_page_title"}

            # Start listening for the request on the client side
            async def client_respond():
                req = await websocket.recv()
                req_json = json.loads(req)
                print(f"[TEST] Client received request: {req_json}")

                # Respond with matching requestId
                resp = {
                    "responseToRequestId": req_json["requestId"],
                    "payload": "Mock Page Title"
                }
                await websocket.send(json.dumps(resp))
                print("[TEST] Client sent response")

            # Run the response logic and the bridge request concurrently
            client_task = asyncio.create_task(client_respond())

            result = await state.bridge.send_request(
                test_payload,
                message_type="process_data"
            )

            await client_task
            print(f"[TEST] Bridge received result: {result}")
            assert result == "Mock Page Title", f"Expected 'Mock Page Title', got {result}"

        print("\n[TEST] ALL TESTS PASSED!")

    finally:
        # Cleanup
        print("[TEST] Cleaning up...")
        ws_task.cancel()
        await stop_http_server()
        http_task.cancel()
        try:
            await ws_task
        except asyncio.CancelledError:
            pass
        try:
            await http_task
        except asyncio.CancelledError:
            pass
        print("[TEST] Cleanup complete")

if __name__ == "__main__":
    asyncio.run(test_websocket_bridge_end_to_end())
