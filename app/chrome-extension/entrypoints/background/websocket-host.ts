import { NativeMessageType } from 'chrome-mcp-shared';
import { BACKGROUND_MESSAGE_TYPES } from '@/common/message-types';
import {
  WEBSOCKET_CONFIG,
  STORAGE_KEYS,
  ERROR_MESSAGES,
  SUCCESS_MESSAGES,
} from '@/common/constants';
import { handleCallTool } from './tools';
import { listPublished, getFlow } from './record-replay/flow-store';
import { acquireKeepalive } from './keepalive-manager';

const LOG_PREFIX = '[WebSocketHost]';

let ws: WebSocket | null = null;
export const HOST_NAME = 'com.chromemcp.nativehost'; // Keep for compatibility

// ==================== Reconnect Configuration ====================

const RECONNECT_BASE_DELAY_MS = WEBSOCKET_CONFIG.RECONNECT_BASE_DELAY_MS;
const RECONNECT_MAX_DELAY_MS = WEBSOCKET_CONFIG.RECONNECT_MAX_DELAY_MS;
const RECONNECT_MAX_FAST_ATTEMPTS = WEBSOCKET_CONFIG.RECONNECT_MAX_FAST_ATTEMPTS;
const RECONNECT_COOLDOWN_DELAY_MS = WEBSOCKET_CONFIG.RECONNECT_COOLDOWN_DELAY_MS;

// ==================== Auto-connect State ====================

let keepaliveRelease: (() => void) | null = null;
let autoConnectEnabled = true;
let autoConnectLoaded = false;
let ensurePromise: Promise<boolean> | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectAttempts = 0;
let manualDisconnect = false;

/**
 * Server status management interface
 */
interface ServerStatus {
  isRunning: boolean;
  port?: number;
  lastUpdated: number;
}

let currentServerStatus: ServerStatus = {
  isRunning: false,
  lastUpdated: Date.now(),
};

/**
 * Save server status to chrome.storage
 */
async function saveServerStatus(status: ServerStatus): Promise<void> {
  try {
    await chrome.storage.local.set({ [STORAGE_KEYS.SERVER_STATUS]: status });
  } catch (error) {
    console.error(ERROR_MESSAGES.SERVER_STATUS_SAVE_FAILED, error);
  }
}

/**
 * Load server status from chrome.storage
 */
async function loadServerStatus(): Promise<ServerStatus> {
  try {
    const result = await chrome.storage.local.get([STORAGE_KEYS.SERVER_STATUS]);
    if (result[STORAGE_KEYS.SERVER_STATUS]) {
      return result[STORAGE_KEYS.SERVER_STATUS];
    }
  } catch (error) {
    console.error(ERROR_MESSAGES.SERVER_STATUS_LOAD_FAILED, error);
  }
  return {
    isRunning: false,
    lastUpdated: Date.now(),
  };
}

/**
 * Broadcast server status change to all listeners
 */
function broadcastServerStatusChange(status: ServerStatus): void {
  chrome.runtime
    .sendMessage({
      type: BACKGROUND_MESSAGE_TYPES.SERVER_STATUS_CHANGED,
      payload: status,
    })
    .catch(() => {
      // Ignore errors if no listeners are present
    });
}

// ==================== Port Normalization ====================

/**
 * Normalize a port value to a valid port number or null.
 */
function normalizePort(value: unknown): number | null {
  const n =
    typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : Number.NaN;
  if (!Number.isFinite(n)) return null;
  const port = Math.floor(n);
  if (port <= 0 || port > 65535) return null;
  return port;
}

// ==================== Reconnect Utilities ====================

/**
 * Add jitter to a delay value to avoid thundering herd.
 */
function withJitter(ms: number): number {
  const ratio = 0.7 + Math.random() * 0.6;
  return Math.max(0, Math.round(ms * ratio));
}

/**
 * Calculate reconnect delay based on attempt number.
 * Uses exponential backoff with jitter, then switches to cooldown interval.
 */
function getReconnectDelayMs(attempt: number): number {
  if (attempt >= RECONNECT_MAX_FAST_ATTEMPTS) {
    return withJitter(RECONNECT_COOLDOWN_DELAY_MS);
  }
  const delay = Math.min(RECONNECT_BASE_DELAY_MS * Math.pow(2, attempt), RECONNECT_MAX_DELAY_MS);
  return withJitter(delay);
}

/**
 * Clear the reconnect timer if active.
 */
function clearReconnectTimer(): void {
  if (!reconnectTimer) return;
  clearTimeout(reconnectTimer);
  reconnectTimer = null;
}

/**
 * Reset reconnect state after successful connection.
 */
function resetReconnectState(): void {
  reconnectAttempts = 0;
  clearReconnectTimer();
}

// ==================== Keepalive Management ====================

/**
 * Sync keepalive hold based on autoConnectEnabled state.
 * When auto-connect is enabled, we hold a keepalive reference to keep SW alive.
 */
function syncKeepaliveHold(): void {
  if (autoConnectEnabled) {
    if (!keepaliveRelease) {
      keepaliveRelease = acquireKeepalive('websocket-host');
      console.debug(`${LOG_PREFIX} Acquired keepalive`);
    }
    return;
  }
  if (keepaliveRelease) {
    try {
      keepaliveRelease();
      console.debug(`${LOG_PREFIX} Released keepalive`);
    } catch {
      // Ignore
    }
    keepaliveRelease = null;
  }
}

// ==================== Auto-connect Settings ====================

/**
 * Load the autoConnectEnabled setting from storage.
 */
async function loadAutoConnectEnabled(): Promise<boolean> {
  try {
    const result = await chrome.storage.local.get([STORAGE_KEYS.NATIVE_AUTO_CONNECT_ENABLED]);
    const raw = result[STORAGE_KEYS.NATIVE_AUTO_CONNECT_ENABLED];
    if (typeof raw === 'boolean') return raw;
  } catch (error) {
    console.warn(`${LOG_PREFIX} Failed to load autoConnectEnabled`, error);
  }
  return true; // Default to enabled
}

/**
 * Set the autoConnectEnabled setting and persist to storage.
 */
async function setAutoConnectEnabled(enabled: boolean): Promise<void> {
  autoConnectEnabled = enabled;
  autoConnectLoaded = true;
  try {
    await chrome.storage.local.set({ [STORAGE_KEYS.NATIVE_AUTO_CONNECT_ENABLED]: enabled });
    console.debug(`${LOG_PREFIX} Set autoConnectEnabled=${enabled}`);
  } catch (error) {
    console.warn(`${LOG_PREFIX} Failed to persist autoConnectEnabled`, error);
  }
  syncKeepaliveHold();
}

// ==================== Port Preference ====================

/**
 * Get the preferred port for connecting to bridge server.
 * Priority: explicit override > user preference > last known port > default
 */
async function getPreferredPort(override?: unknown): Promise<number> {
  const explicit = normalizePort(override);
  if (explicit) return explicit;

  try {
    const result = await chrome.storage.local.get([
      STORAGE_KEYS.NATIVE_SERVER_PORT,
      STORAGE_KEYS.SERVER_STATUS,
    ]);

    const userPort = normalizePort(result[STORAGE_KEYS.NATIVE_SERVER_PORT]);
    if (userPort) return userPort;

    const status = result[STORAGE_KEYS.SERVER_STATUS] as Partial<ServerStatus> | undefined;
    const statusPort = normalizePort(status?.port);
    if (statusPort) return statusPort;
  } catch (error) {
    console.warn(`${LOG_PREFIX} Failed to read preferred port`, error);
  }

  const inMemoryPort = normalizePort(currentServerStatus.port);
  if (inMemoryPort) return inMemoryPort;

  return 12306; // Default MCP HTTP port
}

// ==================== Reconnect Scheduling ====================

/**
 * Schedule a reconnect attempt with exponential backoff.
 */
function scheduleReconnect(reason: string): void {
  if (ws) return;
  if (manualDisconnect) return;
  if (!autoConnectEnabled) return;
  if (reconnectTimer) return;

  const delay = getReconnectDelayMs(reconnectAttempts);
  console.debug(
    `${LOG_PREFIX} Reconnect scheduled in ${delay}ms (attempt=${reconnectAttempts}, reason=${reason})`,
  );

  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    if (ws) return;
    if (manualDisconnect || !autoConnectEnabled) return;

    reconnectAttempts += 1;
    void ensureConnected(`reconnect:${reason}`).catch(() => {});
  }, delay);
}

// ==================== Server Status Update ====================

/**
 * Mark server as stopped and broadcast the change.
 */
async function markServerStopped(reason: string): Promise<void> {
  currentServerStatus = {
    isRunning: false,
    port: currentServerStatus.port,
    lastUpdated: Date.now(),
  };
  try {
    await saveServerStatus(currentServerStatus);
  } catch {
    // Ignore
  }
  broadcastServerStatusChange(currentServerStatus);
  console.debug(`${LOG_PREFIX} Server marked stopped (${reason})`);
}

// ==================== Core Ensure Function ====================

/**
 * Ensure WebSocket connection is established.
 * This is the main entry point for auto-connect logic.
 *
 * @param trigger - Description of what triggered this call (for logging)
 * @param portOverride - Optional explicit port to use
 * @returns Whether the connection is now established
 */
async function ensureConnected(trigger: string, portOverride?: unknown): Promise<boolean> {
  // Concurrency protection: only one ensure flow at a time
  if (ensurePromise) return ensurePromise;

  ensurePromise = (async () => {
    // Load auto-connect setting if not yet loaded
    if (!autoConnectLoaded) {
      autoConnectEnabled = await loadAutoConnectEnabled();
      autoConnectLoaded = true;
      syncKeepaliveHold();
    }

    // If auto-connect is disabled, do nothing
    if (!autoConnectEnabled) {
      console.debug(`${LOG_PREFIX} Auto-connect disabled, skipping ensure (trigger=${trigger})`);
      return false;
    }

    // Sync keepalive hold
    syncKeepaliveHold();

    // Already connected
    if (ws && ws.readyState === WebSocket.OPEN) {
      console.debug(`${LOG_PREFIX} Already connected (trigger=${trigger})`);
      return true;
    }

    // Get the port to use
    const port = await getPreferredPort(portOverride);
    console.debug(`${LOG_PREFIX} Attempting connection on port ${port} (trigger=${trigger})`);

    // Attempt connection
    connectWebSocket(port);
    console.debug(`${LOG_PREFIX} Connection initiated (trigger=${trigger})`);
    // Note: Don't reset reconnect state here. Wait for SERVER_STARTED confirmation.
    return true;
  })().finally(() => {
    ensurePromise = null;
  });

  return ensurePromise;
}

/**
 * Connect to the WebSocket server
 * @param port - The HTTP/MCP port to use (default 12306)
 */
export function connectWebSocket(port: number = 12306): void {
  console.log(`[DEBUG connectWebSocket] port = ${port}`);
  console.log(`[DEBUG connectWebSocket] ws = ${ws}`);

  if (ws && ws.readyState === WebSocket.OPEN) {
    console.log(`[DEBUG connectWebSocket] Already connected, returning`);
    return;
  }

  try {
    // Close existing connection if any
    if (ws) {
      ws.close();
      ws = null;
    }

    const wsUrl = `ws://127.0.0.1:${WEBSOCKET_CONFIG.PORT}`;
    console.log(`[DEBUG connectWebSocket] Connecting to ${wsUrl}`);
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log(`[DEBUG connectWebSocket] WebSocket opened`);
      // Send START message to initialize the bridge
      const startMsg = { type: NativeMessageType.START, payload: { port } };
      console.log(`[DEBUG connectWebSocket] Sending START message: ${JSON.stringify(startMsg)}`);
      ws?.send(JSON.stringify(startMsg));
    };

    ws.onmessage = async (event) => {
      try {
        const message = JSON.parse(event.data);
        console.log(`[DEBUG onmessage] Received: ${JSON.stringify(message)}`);

        if (message.type === NativeMessageType.PROCESS_DATA && message.requestId) {
          const requestId = message.requestId;
          const requestPayload = message.payload;

          ws?.send(
            JSON.stringify({
              responseToRequestId: requestId,
              payload: {
                status: 'success',
                message: SUCCESS_MESSAGES.TOOL_EXECUTED,
                data: requestPayload,
              },
            }),
          );
        } else if (message.type === NativeMessageType.CALL_TOOL && message.requestId) {
          const requestId = message.requestId;
          try {
            const result = await handleCallTool(message.payload);
            ws?.send(
              JSON.stringify({
                responseToRequestId: requestId,
                payload: {
                  status: 'success',
                  message: SUCCESS_MESSAGES.TOOL_EXECUTED,
                  data: result,
                },
              }),
            );
          } catch (error) {
            ws?.send(
              JSON.stringify({
                responseToRequestId: requestId,
                payload: {
                  status: 'error',
                  message: ERROR_MESSAGES.TOOL_EXECUTION_FAILED,
                  error: error instanceof Error ? error.message : String(error),
                },
              }),
            );
          }
        } else if (message.type === 'rr_list_published_flows' && message.requestId) {
          const requestId = message.requestId;
          try {
            const published = await listPublished();
            const items = [] as any[];
            for (const p of published) {
              const flow = await getFlow(p.id);
              if (!flow) continue;
              items.push({
                id: p.id,
                slug: p.slug,
                version: p.version,
                name: p.name,
                description: flow.description || '',
                variables: flow.variables || [],
                meta: flow.meta || {},
              });
            }
            ws?.send(
              JSON.stringify({
                responseToRequestId: requestId,
                payload: { status: 'success', items },
              }),
            );
          } catch (error: any) {
            ws?.send(
              JSON.stringify({
                responseToRequestId: requestId,
                payload: { status: 'error', error: error?.message || String(error) },
              }),
            );
          }
        } else if (message.type === NativeMessageType.SERVER_STARTED) {
          const port = message.payload?.port;
          currentServerStatus = {
            isRunning: true,
            port: port,
            lastUpdated: Date.now(),
          };
          await saveServerStatus(currentServerStatus);
          broadcastServerStatusChange(currentServerStatus);
          // Server is confirmed running - now we can reset reconnect state
          resetReconnectState();
          console.log(`${SUCCESS_MESSAGES.SERVER_STARTED} on port ${port}`);
        } else if (message.type === NativeMessageType.SERVER_STOPPED) {
          currentServerStatus = {
            isRunning: false,
            port: currentServerStatus.port, // Keep last known port for reconnection
            lastUpdated: Date.now(),
          };
          await saveServerStatus(currentServerStatus);
          broadcastServerStatusChange(currentServerStatus);
          console.log(SUCCESS_MESSAGES.SERVER_STOPPED);
        } else if (message.type === NativeMessageType.ERROR_FROM_NATIVE_HOST) {
          console.error('Error from bridge:', message.payload?.message || 'Unknown error');
        } else if (message.type === 'file_operation_response') {
          // Forward file operation response back to the requesting tool
          chrome.runtime.sendMessage(message).catch(() => {
            // Ignore if no listeners
          });
        }
      } catch (error) {
        console.error('[DEBUG onmessage] Error parsing message:', error);
      }
    };

    ws.onclose = (event) => {
      console.error(`[DEBUG onclose] DISCONNECTED! code=${event.code}, reason=${event.reason}`);
      console.warn(ERROR_MESSAGES.NATIVE_DISCONNECTED, event);
      ws = null;

      // Mark server as stopped since disconnection means server is down
      void markServerStopped('websocket_closed');

      // Handle reconnection based on disconnect reason
      if (manualDisconnect) {
        manualDisconnect = false;
        return;
      }
      if (!autoConnectEnabled) return;
      scheduleReconnect('websocket_closed');
    };

    ws.onerror = (error) => {
      console.error('[DEBUG onerror] WebSocket error:', error);
    };

    return;
  } catch (error: any) {
    console.error(`[DEBUG connectWebSocket] EXCEPTION CAUGHT:`, error);
    console.error(`[DEBUG connectWebSocket] Error message:`, error?.message);
    console.warn(ERROR_MESSAGES.NATIVE_CONNECTION_FAILED, error);
    ws = null;
  }
}

/**
 * Initialize WebSocket listeners and load initial state
 */
export const initWebSocketHostListener = () => {
  // Initialize server status from storage
  loadServerStatus()
    .then((status) => {
      currentServerStatus = status;
    })
    .catch((error) => {
      console.error(ERROR_MESSAGES.SERVER_STATUS_LOAD_FAILED, error);
    });

  // Auto-connect on SW activation (covers SW restart after idle termination)
  void ensureConnected('sw_startup').catch(() => {});

  // Auto-connect on Chrome browser startup
  chrome.runtime.onStartup.addListener(() => {
    void ensureConnected('onStartup').catch(() => {});
  });

  // Auto-connect on extension install/update
  chrome.runtime.onInstalled.addListener(() => {
    void ensureConnected('onInstalled').catch(() => {});
  });

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    // Allow UI to call tools directly
    if (message && message.type === 'call_tool' && message.name) {
      handleCallTool({ name: message.name, args: message.args })
        .then((res) => sendResponse({ success: true, result: res }))
        .catch((err) =>
          sendResponse({ success: false, error: err instanceof Error ? err.message : String(err) }),
        );
      return true;
    }

    const msgType = typeof message === 'string' ? message : message?.type;

    // ENSURE_NATIVE: Trigger ensure without changing autoConnectEnabled
    if (msgType === NativeMessageType.ENSURE_NATIVE) {
      const portOverride = typeof message === 'object' ? message.port : undefined;
      ensureConnected('ui_ensure', portOverride)
        .then((connected) => {
          sendResponse({ success: true, connected, autoConnectEnabled });
        })
        .catch((e) => {
          sendResponse({
            success: false,
            connected: ws?.readyState === WebSocket.OPEN,
            error: String(e),
          });
        });
      return true;
    }

    // CONNECT_NATIVE: Explicit user connect, re-enables auto-connect
    if (msgType === NativeMessageType.CONNECT_NATIVE) {
      const portOverride = typeof message === 'object' ? message.port : undefined;
      const normalized = normalizePort(portOverride);

      (async () => {
        // Explicit user connect: re-enable auto-connect
        await setAutoConnectEnabled(true);

        if (normalized) {
          // Best-effort: persist preferred port
          try {
            await chrome.storage.local.set({ [STORAGE_KEYS.NATIVE_SERVER_PORT]: normalized });
          } catch {
            // Ignore
          }
        }

        return ensureConnected('ui_connect', normalized ?? undefined);
      })()
        .then((connected) => {
          sendResponse({ success: true, connected });
        })
        .catch((e) => {
          sendResponse({
            success: false,
            connected: ws?.readyState === WebSocket.OPEN,
            error: String(e),
          });
        });
      return true;
    }

    if (msgType === NativeMessageType.PING_NATIVE) {
      const connected = ws?.readyState === WebSocket.OPEN;
      sendResponse({ connected, autoConnectEnabled });
      return true;
    }

    // DISCONNECT_NATIVE: Explicit user disconnect, disables auto-connect
    if (msgType === NativeMessageType.DISCONNECT_NATIVE) {
      (async () => {
        // Explicit user disconnect: disable auto-connect and stop reconnect loop
        await setAutoConnectEnabled(false);
        clearReconnectTimer();
        reconnectAttempts = 0;
        syncKeepaliveHold();

        if (ws) {
          // Only set manualDisconnect if we actually have a connection to disconnect.
          manualDisconnect = true;
          try {
            ws.close();
          } catch {
            // Ignore
          }
          ws = null;
        }
        await markServerStopped('manual_disconnect');
      })()
        .then(() => {
          sendResponse({ success: true });
        })
        .catch((e) => {
          sendResponse({ success: false, error: String(e) });
        });
      return true;
    }

    if (message.type === BACKGROUND_MESSAGE_TYPES.GET_SERVER_STATUS) {
      sendResponse({
        success: true,
        serverStatus: currentServerStatus,
        connected: ws?.readyState === WebSocket.OPEN,
      });
      return true;
    }

    if (message.type === BACKGROUND_MESSAGE_TYPES.REFRESH_SERVER_STATUS) {
      loadServerStatus()
        .then((storedStatus) => {
          currentServerStatus = storedStatus;
          sendResponse({
            success: true,
            serverStatus: currentServerStatus,
            connected: ws?.readyState === WebSocket.OPEN,
          });
        })
        .catch((error) => {
          console.error(ERROR_MESSAGES.SERVER_STATUS_LOAD_FAILED, error);
          sendResponse({
            success: false,
            error: ERROR_MESSAGES.SERVER_STATUS_LOAD_FAILED,
            serverStatus: currentServerStatus,
            connected: ws?.readyState === WebSocket.OPEN,
          });
        });
      return true;
    }

    // Forward file operation messages to bridge
    if (message.type === 'forward_to_native' && message.message) {
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(message.message));
        sendResponse({ success: true });
      } else {
        sendResponse({ success: false, error: 'WebSocket not connected' });
      }
      return true;
    }
  });
};
