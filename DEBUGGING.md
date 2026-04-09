# Chrome MCP Server - Extension Debugging Guide

## Current Status

The extension is now built with additional debug logging.

## Steps to Debug

### 1. Verify Extension is Loaded

1. Open `chrome://extensions/`
2. Find "Chrome MCP Server" extension
3. If using unpacked version, make sure it's pointing to:
   ```
   /home/yl/mcp-chrome-python/app/chrome-extension/dist
   ```
4. **Click the refresh icon (🔄)** to reload the extension with the new debug logs

### 2. Verify Manifest is Correct

Check the manifest file:

```bash
cat ~/.config/google-chrome/NativeMessagingHosts/com.chromemcp.nativehost.json
```

Expected content:

```json
{
  "name": "com.chromemcp.nativehost",
  "description": "Chrome MCP Native Server (Python)",
  "path": "/home/yl/mcp-chrome-python/dist/mcp-chrome-bridge",
  "type": "stdio",
  "allowed_origins": ["<all_origins>"]
}
```

### 3. Open DevTools and Check Logs

1. Open the extension popup or side panel
2. Open Chrome DevTools:
   - Go to `chrome://extensions/`
   - Find "Chrome MCP Server"
   - Click "Inspect views: background page"
3. Clear the console
4. Click "Connect" in the extension

### 4. Expected Debug Output

You should see lines like:

```
[DEBUG connectNativeHost] HOST_NAME = com.chromemcp.nativehost
[DEBUG connectNativeHost] port = 12306
[DEBUG connectNativeHost] Calling chrome.runtime.connectNative('com.chromemcp.nativehost')
```

### 5. Check Log File

After clicking Connect, check if the bridge binary was launched:

```bash
tail -f ~/.local/share/chrome-mcp/bridge.log
```

If the binary launches, you should see:

```
Chrome MCP Bridge starting, log file: /home/yl/.local/share/chrome-mcp/bridge.log
==================================================
Chrome MCP Native Server (Python) Starting...
...
```

### 6. Check for Chrome Errors

If you see `[DEBUG onDisconnect] DISCONNECTED!` in the console, note the error message from `chrome.runtime.lastError`.

## Troubleshooting

### If "Specified native messaging host not found"

- Chrome may need to be fully restarted to reload native messaging hosts
- Close ALL Chrome windows and reopen

### If binary launches but immediately disconnects

- Check the log file for any errors
- Verify port 12306 is not in use: `lsof -i :12306`

### If no debug output appears

- Extension may not be reloaded - click refresh icon in chrome://extensions/
- DevTools may be attached to wrong context - ensure "background page" is selected
