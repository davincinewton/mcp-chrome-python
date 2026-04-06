from abc import ABC, abstractmethod
from typing import Any, Dict, Callable, Awaitable

class ExtensionBridge(ABC):
    """
    Abstract base class for the bridge communication between the
    MCP server and the Chrome Extension.
    """

    @abstractmethod
    async def start(self) -> None:
        """Starts the transport server/listener."""
        pass

    @abstractmethod
    async def send_message(self, message: Dict[str, Any]) -> None:
        """Sends a JSON message to the extension."""
        pass

    @abstractmethod
    async def send_request(self, payload: Any, message_type: str = 'request_data', timeout: float = 30.0) -> Any:
        """Sends a request and waits for a response using requestId and asyncio.Future."""
        pass

    @abstractmethod
    def set_message_handler(self, handler: Callable[[Dict[str, Any]], Awaitable[None]]) -> None:
        """Registers the main message processor."""
        pass

    @abstractmethod
    async def cleanup(self) -> None:
        """Shuts down the transport."""
        pass
