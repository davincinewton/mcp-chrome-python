# Chrome Extension WebSocket Conversion Plan

## Overview

Replace Chrome Native Messaging (`chrome.runtime.connectNative`) with WebSocket connections to the Python bridge on `ws://127.0.0.1:12307`.

---

## Files to Create/Modify

### 1. New Files

**`app/chrome-extension/entrypoints/background/websocket-transport.ts`**

- New WebSocket client class that mirrors `NativeMessagingBridge` behavior
- Handles connection, reconnection, message sending/receiving
- Uses same `requestId`/`responseToRequestId` protocol

**`packages/shared/src/types.ts` (extend)**

- Add WebSocket configuration types

### 2. Files to Modify

| File                                                         | Changes                                                      |
| ------------------------------------------------------------ | ------------------------------------------------------------ |
| `app/chrome-extension/common/constants.ts`                   | Add `WEBSOCKET_HOST`, `WEBSOCKET_PORT` constants             |
| `app/chrome-extension/entrypoints/background/native-host.ts` | Replace `chrome.runtime.connectNative` with WebSocket client |
| `app/chrome-extension/entrypoints/background/index.ts`       | Update initialization if needed                              |
| `app/chrome-extension/entrypoints/popup/main.ts`             | Update ensure call (may not need changes)                    |
| `app/chrome-extension/entrypoints/sidepanel/main.ts`         | Update ensure call (may not need changes)                    |

---

## Implementation Steps

### Step 1: Add WebSocket Constants

**File: `app/chrome-extension/common/constants.ts`**

```typescript
export const WEBSOCKET_CONFIG = {
  HOST: '127.0.0.1',
  PORT: 12307,
  URL: () => `ws://127.0.0.1:12307`,
  RECONNECT_BASE_DELAY_MS: 500,
  RECONNECT_MAX_DELAY_MS: 60_000,
  RECONNECT_MAX_FAST_ATTEMPTS: 8,
  RECONNECT_COOLDOWN_DELAY_MS: 5 * 60_000,
};
```

### Step 2: Create WebSocket Transport Class

**File: `app/chrome-extension/entrypoints/background/websocket-transport.ts`**

```typescript
import { WEBSOCKET_CONFIG } from '@/common/constants';
import { NativeMessageType } from 'chrome-mcp-shared';

export class WebSocketTransport {
  private ws: WebSocket | null = null;
  private onMessageCallback: ((message: any) => void) | null = null;
  private onOpenCallback: (() => void) | null = null;
  private onCloseCallback: ((event: CloseEvent) => void) | null = null;
  private pendingRequests: Map<string, (response: any) => void> = new Map();

  public setOnMessage(callback: (message: any) => void) {
    this.onMessageCallback = callback;
  }
  public setOnOpen(callback: () => void) {
    this.onOpenCallback = callback;
  }
  public setOnClose(callback: (event: CloseEvent) => void) {
    this.onCloseCallback = callback;
  }

  public connect() {
    this.ws = new WebSocket(WEBSOCKET_CONFIG.URL());
    this.ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      this.onMessageCallback?.(message);
    };
    this.ws.onopen = () => {
      console.log('[WebSocket] Connected');
      this.onOpenCallback?.();
    };
    this.ws.onclose = (event) => {
      console.log('[WebSocket] Closed:', event.code, event.reason);
      this.onCloseCallback?.(event);
    };
  }

  public send(message: any) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
    }
  }

  public close() {
    this.ws?.close();
    this.ws = null;
  }

  public isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}
```

### Step 3: Update `native-host.ts`

**Key Changes:**

1. Replace `chrome.runtime.connectNative(HOST_NAME)` with `new WebSocketTransport().connect()`
2. Replace `nativePort.postMessage()` with `wsTransport.send()`
3. Replace `nativePort.onMessage.addListener()` with `wsTransport.setOnMessage()`
4. Replace `nativePort.onDisconnect.addListener()` with `wsTransport.setOnClose()`
5. Keep all message handling logic the same
6. Keep reconnection logic the same (adapted for WebSocket)

### Step 4: Update Keepalive Logic

The current code uses `acquireKeepalive('native-host')` when auto-connect is enabled. This should work the same way for WebSocket connections - hold keepalive while WebSocket connection is active.

### Step 5: Remove Native Messaging Manifest

After testing, remove or deprecate:

- `chrome-mcp-native-host.json` (native messaging manifest)
- Any registry/filesystem entries for native messaging

---

## Protocol Preservation

The WebSocket transport will use the **exact same** JSON message format:

```typescript
// Extension → Bridge
{ type: 'start', payload: { port: 12306 } }
{ type: 'ping_from_extension' }
{ type: 'stop' }
{ requestId: 'xxx', type: 'process_data', payload: {...} }

// Bridge → Extension
{ type: 'server_started', payload: { port: 12306 } }
{ type: 'pong_to_extension' }
{ type: 'server_stopped' }
{ responseToRequestId: 'xxx', payload: {...} }
{ type: 'process_data', requestId: 'xxx', payload: {...} }
```

---

## Testing Checklist

- [ ] WebSocket connection established successfully
- [ ] `start` command works (HTTP server starts)
- [ ] `ping` command works
- [ ] `stop` command works
- [ ] Reconnection logic works (kill bridge, verify auto-reconnect)
- [ ] Tool calls work via `process_data`
- [ ] File upload operations work via `forward_to_native`
- [ ] Flow listing works
- [ ] Service worker restart preserves state
- [ ] Popup/Sidepanel UI shows correct connection status

---

## Migration Path

1. **Phase 1**: Implement WebSocket transport alongside native messaging
2. **Phase 2**: Test thoroughly with both modes working
3. **Phase 3**: Switch extension to use WebSocket by default
4. **Phase 4**: Remove native messaging support (optional)
