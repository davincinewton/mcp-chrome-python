# MCP Chrome Bridge

Chrome MCP Native Server - Bridges Chrome extension with MCP-compatible AI assistants.

## Overview

This Python native messaging host enables AI assistants (via Model Context Protocol) to interact with your Chrome browser through the Chrome MCP extension.

## Installation

### From PyPI

```bash
pip install mcp-chrome-bridge
```

### From GitHub (Latest)

```bash
pip install git+https://github.com/davincinewton/mcp-chrome-python.git#subdirectory=app/bridge-python
```

### From Local Repository

From within the `mcp-chrome` repository:

```bash
cd app/bridge-python
pip install -e .
```

Or install directly from the built distribution:

```bash
pip install dist/mcp_chrome_bridge-*.whl
```

## Usage

### 1. Register with Chrome

After installation, register the native host with Chrome:

```bash
mcp-chrome-bridge --register
```

This creates the necessary manifest file in your Chrome NativeMessagingHosts directory:

- **Linux:** `~/.config/google-chrome/NativeMessagingHosts/`
- **macOS:** `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/`
- **Windows:** `%APPDATA%\Google\Chrome\NativeMessagingHosts\`

### 2. Start the Server

```bash
mcp-chrome-bridge
```

The server will:

- Listen on WebSocket port **12307** for Chrome extension connections
- Start an HTTP/SSE server on port **12306** for MCP interactions

### 3. Configure Your AI Assistant

Add the following to your MCP client configuration (e.g., Claude Code, Cursor, etc.):

```json
{
  "mcpServers": {
    "chrome": {
      "url": "http://127.0.0.1:12306/mcp"
    }
  }
}
```

## Development

### Prerequisites

- Python 3.10 or higher

### Install Development Dependencies

```bash
pip install -e ".[dev]"
```

### Running from Source (without installation)

```bash
cd app/bridge-python
python main.py
```

### Run Tests

```bash
pytest tests/
```

### Code Formatting

```bash
black .
ruff check --fix
```

### Build Distribution

```bash
python -m build
```

This creates:

- `dist/mcp_chrome_bridge-*.tar.gz` (source distribution)
- `dist/mcp_chrome_bridge-*.whl` (wheel distribution)

### Publish to PyPI

```bash
pip install twine
python -m twine upload dist/*
```

## Architecture

```
bridge-python/
├── main.py              # CLI entry point, orchestrates server startup
├── api/
│   └── main.py          # FastAPI HTTP server for MCP streamable-http
├── bridge/
│   ├── base.py          # Abstract bridge interface
│   ├── native_messaging.py  # Chrome Native Messaging protocol
│   └── websocket_bridge.py  # WebSocket server for extension
├── schemas/
│   ├── shared.py        # Shared data models
│   └── tool_schemas.py  # MCP tool definitions
├── mcp_server_logic.py  # MCP server implementation
├── utils.py             # Utilities (register_binary, etc.)
└── bridge_python/       # Package wrapper for PyPI
    ├── __init__.py
    └── __main__.py      # Console script entry point
```

## Available Tools

Once running, the bridge exposes Chrome automation tools:

- `chrome_read_page` - Get accessibility tree of visible elements
- `chrome_computer` - Mouse/keyboard interaction and screenshots
- `chrome_navigate` - Navigate to URLs, refresh, back/forward
- `chrome_screenshot` - Capture screenshots
- `chrome_bookmark_*` - Bookmark management
- `chrome_history` - Browse history search
- `chrome_javascript` - Execute JavaScript in page context
- And many more...

Dynamic tools are also available for recorded Replay.flows.

## License

MIT
