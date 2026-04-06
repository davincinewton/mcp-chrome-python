#!/usr/bin/env python3
"""Minimal test binary to verify Chrome can launch it."""
import sys
import os
import json
from pathlib import Path

# Write to log file IMMEDIATELY - before anything else
LOG_FILE = Path.home() / ".local" / "share" / "chrome-mcp" / "test_launch.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

def log(msg):
    """Write to log file with flush"""
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(f"{msg}\n")
            f.flush()
    except:
        pass

def write_response(message_dict):
    """Write a length-prefixed JSON response to stdout"""
    json_bytes = json.dumps(message_dict).encode('utf-8')
    length = len(json_bytes)
    # Write 4-byte little-endian header
    sys.stdout.buffer.write(length.to_bytes(4, 'little'))
    # Write the JSON message
    sys.stdout.buffer.write(json_bytes)
    sys.stdout.buffer.flush()
    log(f"-> Sent response ({length} bytes): {message_dict}")

try:
    log("=== BINARY LAUNCHED ===")
    log(f"PID: {os.getpid()}")
    log(f"argv: {sys.argv}")
    log(f"cwd: {os.getcwd()}")
    log(f"stdin available: {sys.stdin is not None}")
    log(f"stdout available: {sys.stdout is not None}")
except Exception as e:
    log(f"ERROR in initial log: {e}")

print("Test launch ready, waiting for Chrome messages...", flush=True)
log("Waiting for Chrome messages...")

try:
    while True:
        # Read 4-byte header
        header = sys.stdin.buffer.read(4)
        if len(header) < 4:
            log(f"Got {len(header)} bytes header (EOF or partial)")
            break
        length = int.from_bytes(header, 'little')
        log(f"Received header: {length} bytes")

        # Read the message
        message = sys.stdin.buffer.read(length)
        if len(message) < length:
            log(f"Got only {len(message)} of {length} bytes (EOF)")
            break

        try:
            message_dict = json.loads(message.decode('utf-8'))
            log(f"Received message: {message_dict}")
            print(f"Got: {message_dict}", flush=True)

            # Send an ACK back to Chrome
            write_response({
                "type": "ACK",
                "message": "Test binary received your message!",
                "echo": message_dict
            })

        except json.JSONDecodeError as e:
            log(f"Failed to decode JSON: {e}")
            log(f"Raw message: {message}")

except Exception as e:
    log(f"ERROR reading stdin: {e}")
    print(f"Error reading stdin: {e}", file=sys.stderr)

log("Binary exiting (should not happen)")
