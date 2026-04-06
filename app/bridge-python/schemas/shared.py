from enum import Enum
from typing import Any, Optional, Dict, List, Union
from pydantic import BaseModel, Field

# Constants mirror from app/native-server/src/constant/index.ts
NATIVE_SERVER_PORT = 12306
DEFAULT_REQUEST_TIMEOUT = 15.0  # seconds
EXTENSION_REQUEST_TIMEOUT = 20.0 # seconds
PROCESS_DATA_TIMEOUT = 20.0      # seconds
SERVER_HOST = '127.0.0.1'

class NativeMessageType(str, Enum):
    START = 'start'
    STARTED = 'started'
    STOP = 'stop'
    STOPPED = 'stopped'
    PING = 'ping'
    PONG = 'pong'
    ERROR = 'error'

class NativeMessage(BaseModel):
    """
    Base structure for messages exchanged between the
    Native Server and the Chrome Extension.
    """
    type: str
    payload: Any = None
    requestId: Optional[str] = None
    responseToRequestId: Optional[str] = None

class ToolSchema(BaseModel):
    """
    Mirror of the tool definition schema.
    """
    name: str
    description: str
    inputSchema: Dict[str, Any]

class FlowVariable(BaseModel):
    """
    Variables defined within a recorded flow.
    """
    label: str
    type: str
    rules: Optional[List[Dict[str, Any]]] = None
    defaultValue: Optional[Any] = None

class FlowTool(ToolSchema):
    """
    Tools generated from recorded flows.
    """
    flowId: str
    slug: str
