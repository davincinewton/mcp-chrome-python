"""CLI entry point for mcp-chrome-bridge."""
import sys
from pathlib import Path

# Add parent directory to path so we can import the flat modules
# This allows the package to work whether installed or run from source
_parent_dir = Path(__file__).resolve().parent
if str(_parent_dir) not in sys.path:
    sys.path.insert(0, str(_parent_dir))

# Now import from the flat structure
from main import main_cli


def main():
    """Main entry point for the console script."""
    main_cli()


if __name__ == "__main__":
    main()
