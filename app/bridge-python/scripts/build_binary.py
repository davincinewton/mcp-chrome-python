import os
import sys
import json
import subprocess
import shutil
import platform
import logging
from pathlib import Path

# Configuration
HOST_NAME = "com.chromemcp.nativehost"
DESCRIPTION = "Chrome MCP Native Server (Python)"
EXTENSION_ID = "hbdgbgagpkpjffpklnamcljpakneikee"
BINARY_NAME = "mcp-chrome-bridge"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("build-binary")

def get_manifest_path():
    """Returns the OS-specific path for the Chrome Native Messaging Manifest."""
    os_type = platform.system()
    home = Path.home()

    if os_type == "Windows":
        # %APPDATA%\Google\Chrome\NativeMessagingHosts\
        return Path(os.environ.get("APPDATA", "")) / "Google" / "Chrome" / "NativeMessagingHosts" / f"{HOST_NAME}.json"
    elif os_type == "Darwin": # macOS
        # ~/Library/Application Support/Google/Chrome/NativeMessagingHosts\
        return home / "Library" / "Application Support" / "Google" / "Chrome" / "NativeMessagingHosts" / f"{HOST_NAME}.json"
    elif os_type == "Linux":
        # ~/.config/google-chrome/NativeMessagingHosts\
        return home / ".config" / "google-chrome" / "NativeMessagingHosts" / f"{HOST_NAME}.json"
    else:
        raise OSError(f"Unsupported OS: {os_type}")

def register_binary():
    """Registers the current binary with Google Chrome."""
    # Get the absolute path of the current executable
    if getattr(sys, 'frozen', False):
        # If running as a PyInstaller bundle
        exe_path = sys.executable
    else:
        # If running as a script (for testing)
        exe_path = os.path.abspath(__file__)

    logger.info(f"Registering binary at: {exe_path}")

    manifest = {
        "name": HOST_NAME,
        "description": DESCRIPTION,
        "path": exe_path,
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{EXTENSION_ID}/"]
    }

    manifest_path = get_manifest_path()
    try:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
        logger.info(f"Successfully wrote manifest to: {manifest_path}")
    except Exception as e:
        logger.error(f"Failed to write manifest: {e}")
        sys.exit(1)

    if platform.system() == "Windows":
        # Windows requires a registry key pointing to the manifest
        import winreg
        try:
            key_path = rf"Software\Google\Chrome\NativeMessagingHosts\{HOST_NAME}"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest_path))
            logger.info("Successfully updated Windows Registry")
        except Exception as e:
            logger.error(f"Failed to update Windows Registry: {e}")
            sys.exit(1)

def build_binary():
    """Bundles the application into a standalone binary using PyInstaller."""
    try:
        import PyInstaller.__main__
    except ImportError:
        logger.error("PyInstaller not found. Please install it: pip install pyinstaller")
        sys.exit(1)

    # Entry point for the binary
    entry_point = "app/bridge-python/main.py"
    # Note: In a real implementation, we'd create a separate wrapper that
    # starts the FastAPI server and the Bridge loop together.

    args = [
        entry_point,
        '--onefile',
        '--name', BINARY_NAME,
        '--collect-all', 'mcp',
        # Console window enabled for debugging (no --noconsole)
    ]

    logger.info(f"Building binary with args: {args}")
    PyInstaller.__main__.run(args)
    logger.info("Binary build completed successfully.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Build and register Chrome MCP Native Server")
    parser.add_argument("--build", action="store_true", help="Build the standalone binary")
    parser.add_argument("--register", action="store_true", help="Register the current binary with Chrome")

    args = parser.parse_args()

    if args.build:
        build_binary()
    elif args.register:
        register_binary()
    else:
        parser.print_help()
