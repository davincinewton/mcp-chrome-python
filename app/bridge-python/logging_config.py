"""Unified logging configuration for the Chrome MCP Bridge."""
import logging
import os
import sys
from pathlib import Path
from typing import Optional


def get_log_path() -> Path:
    """Get log file path in user's data directory."""
    home = os.environ.get("HOME") or os.environ.get("USERPROFILE") or "/tmp"
    if home == "/tmp":
        try:
            home = str(Path.home())
        except Exception:
            home = "/tmp"
    log_dir = Path(home) / ".local" / "share" / "chrome-mcp"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "bridge.log"


class DualHandler(logging.Handler):
    """Custom handler that writes to both file and stdout."""

    def __init__(self, log_file: Optional[str] = None):
        super().__init__()
        self.log_file = log_file or str(get_log_path())

    def emit(self, record: logging.LogRecord):
        msg = self.format(record)
        # Write to stdout with flush
        print(msg, flush=True)
        # Write to file with flush
        try:
            with open(self.log_file, 'a') as f:
                f.write(msg + '\n')
                f.flush()
        except Exception:
            print(f"Failed to write to log file", file=sys.stderr, flush=True)


def setup_logging(level: Optional[str] = None, log_file: Optional[str] = None):
    """
    Set up unified logging configuration.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR). Defaults to env LOG_LEVEL or INFO.
        log_file: Path to log file. Defaults to user data directory.
    """
    # Get log level
    if level is None:
        level = os.environ.get("LOG_LEVEL", "INFO").upper()

    log_level = getattr(logging, level.upper(), logging.INFO)

    # Get log file path
    file_path = log_file or str(get_log_path())

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(log_level)

    # Add dual handler (stdout + file)
    handler = DualHandler(file_path)
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    ))
    root_logger.addHandler(handler)

    # Set default level for all existing loggers
    for logger_name in logging.root.manager.loggerDict:
        logger = logging.getLogger(logger_name)
        if isinstance(logger, logging.Logger):
            logger.setLevel(log_level)
