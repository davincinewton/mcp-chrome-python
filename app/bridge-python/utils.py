"""Shared utilities for the Chrome MCP Native Server."""
import os
import sys
import json
import platform
from pathlib import Path

HOST_NAME = "com.chromemcp.nativehost"
DESCRIPTION = "Chrome MCP Native Server (Python)"
EXTENSION_ID = "hbdgbgagpkpjffpklnamcljpakneikee"

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

    manifest = {
        "name": HOST_NAME,
        "description": DESCRIPTION,
        "path": exe_path,
        "type": "stdio",
        # For development, allow all origins (includes unpacked extensions)
        # For production, replace with: ["chrome-extension://hbdgbgagpkpjffpklnamcljpakneikee/"]
        "allowed_origins": ["<all_origins>"]
    }

    manifest_path = get_manifest_path()
    try:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
        print(f"Successfully wrote manifest to: {manifest_path}")
    except Exception as e:
        print(f"Failed to write manifest: {e}", file=sys.stderr)
        sys.exit(1)

    if platform.system() == "Windows":
        # Windows requires a registry key pointing to the manifest
        import winreg
        try:
            key_path = rf"Software\Google\Chrome\NativeMessagingHosts\{HOST_NAME}"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest_path))
            print("Successfully updated Windows Registry")
        except Exception as e:
            print(f"Failed to update Windows Registry: {e}", file=sys.stderr)
            sys.exit(1)
