"""
Pydantic models for tool argument validation.

These models provide type validation for tool arguments before they are
forwarded to the Chrome extension.
"""
from typing import Any, Dict, Optional, List, Literal, Union
from pydantic import BaseModel, Field, field_validator


class Coordinates(BaseModel):
    """Viewport coordinates."""
    x: float
    y: float


class Modifiers(BaseModel):
    """Modifier keys state."""
    altKey: bool = False
    ctrlKey: bool = False
    metaKey: bool = False
    shiftKey: bool = False


class ElementInput(BaseModel):
    """Input element reference with value."""
    ref: str
    value: str


class ChromeReadPageArgs(BaseModel):
    """Arguments for chrome_read_page tool."""
    filter: Optional[Literal["interactive"]] = None
    depth: Optional[int] = Field(None, ge=0, description="Maximum DOM depth to traverse (integer >= 0)")
    refId: Optional[str] = None
    tabId: Optional[int] = None
    windowId: Optional[int] = None


class ChromeComputerArgs(BaseModel):
    """Arguments for chrome_computer tool."""
    action: Literal[
        "left_click", "right_click", "double_click", "triple_click",
        "left_click_drag", "scroll", "scroll_to", "type", "key",
        "fill", "fill_form", "hover", "wait", "resize_page", "zoom", "screenshot"
    ]
    tabId: Optional[int] = None
    background: bool = False
    ref: Optional[str] = None
    coordinates: Optional[Coordinates] = None
    startCoordinates: Optional[Coordinates] = None
    startRef: Optional[str] = None
    scrollDirection: Optional[Literal["up", "down", "left", "right"]] = None
    scrollAmount: Optional[int] = Field(None, ge=1, le=10, description="Scroll ticks (1-10)")
    text: Optional[str] = None
    repeat: Optional[int] = Field(None, ge=1, le=100, description="Repeat count (1-100)")
    modifiers: Optional[Modifiers] = None
    selector: Optional[str] = None
    value: Optional[Union[str, bool, int]] = None
    elements: Optional[List[ElementInput]] = None
    width: Optional[int] = None
    height: Optional[int] = None
    appear: Optional[bool] = None
    timeout: Optional[int] = Field(None, ge=0, le=120000, description="Timeout in ms (max 120000)")
    duration: Optional[float] = Field(None, ge=0, le=30, description="Wait duration in seconds (max 30)")


class ChromeClickElementArgs(BaseModel):
    """Arguments for chrome_click_element tool."""
    selector: Optional[str] = None
    selectorType: Optional[Literal["css", "xpath"]] = None
    ref: Optional[str] = None
    coordinates: Optional[Coordinates] = None
    double: bool = False
    button: Optional[Literal["left", "right", "middle"]] = None
    modifiers: Optional[Modifiers] = None
    waitForNavigation: bool = False
    timeout: Optional[int] = Field(None, ge=0, description="Timeout in ms")
    tabId: Optional[int] = None
    windowId: Optional[int] = None
    frameId: Optional[int] = None


class ChromeFillOrSelectArgs(BaseModel):
    """Arguments for chrome_fill_or_select tool."""
    value: Union[str, int, float, bool]
    selector: Optional[str] = None
    selectorType: Optional[Literal["css", "xpath"]] = None
    ref: Optional[str] = None
    tabId: Optional[int] = None
    windowId: Optional[int] = None
    frameId: Optional[int] = None


class ChromeKeyboardArgs(BaseModel):
    """Arguments for chrome_keyboard tool."""
    keys: str
    selector: Optional[str] = None
    selectorType: Optional[Literal["css", "xpath"]] = None
    delay: Optional[int] = Field(None, ge=0, description="Delay between keystrokes in ms")
    tabId: Optional[int] = None
    windowId: Optional[int] = None
    frameId: Optional[int] = None


class ChromeConsoleArgs(BaseModel):
    """Arguments for chrome_console tool."""
    url: Optional[str] = None
    tabId: Optional[int] = None
    windowId: Optional[int] = None
    background: bool = False
    includeExceptions: bool = True
    maxMessages: Optional[int] = Field(None, ge=1, description="Maximum messages to capture")
    mode: Optional[Literal["snapshot", "buffer"]] = None
    buffer: Optional[bool] = None
    clear: bool = False
    clearAfterRead: bool = False
    pattern: Optional[str] = None
    onlyErrors: bool = False
    limit: Optional[int] = Field(None, ge=1, description="Limit returned messages")


class ChromeNetworkCaptureArgs(BaseModel):
    """Arguments for chrome_network_capture tool."""
    action: Literal["start", "stop"]
    needResponseBody: bool = False
    url: Optional[str] = None
    maxCaptureTime: Optional[int] = Field(None, ge=0, description="Maximum capture time in ms")
    inactivityTimeout: Optional[int] = Field(None, ge=0, description="Inactivity timeout in ms (0 to disable)")
    includeStatic: bool = False


class ChromeGifRecorderArgs(BaseModel):
    """Arguments for chrome_gif_recorder tool."""
    action: Literal["start", "stop", "status", "auto_start", "capture", "clear", "export"]
    tabId: Optional[int] = None
    fps: Optional[int] = Field(None, ge=1, le=30, description="Frames per second (1-30)")
    durationMs: Optional[int] = Field(None, ge=0, le=60000, description="Duration in ms (max 60000)")
    maxFrames: Optional[int] = Field(None, ge=1, le=300, description="Max frames (max 300)")
    width: Optional[int] = Field(None, ge=1, le=1920, description="Output width (max 1920)")
    height: Optional[int] = Field(None, ge=1, le=1080, description="Output height (max 1080)")
    maxColors: Optional[int] = None
    filename: Optional[str] = None
    download: bool = True


class ChromeJavascriptArgs(BaseModel):
    """Arguments for chrome_javascript tool."""
    code: str
    tabId: Optional[int] = None
    timeoutMs: Optional[int] = Field(None, ge=0, description="Timeout in ms")
    maxOutputBytes: Optional[int] = Field(None, ge=1, description="Max output bytes")


class ChromeNavigateArgs(BaseModel):
    """Arguments for chrome_navigate tool."""
    url: Optional[str] = None
    newWindow: bool = False
    tabId: Optional[int] = None
    windowId: Optional[int] = None
    background: bool = False
    width: Optional[int] = None
    height: Optional[int] = None
    refresh: bool = False


class ChromeCloseTabsArgs(BaseModel):
    """Arguments for chrome_close_tabs tool."""
    tabIds: Optional[List[int]] = None
    url: Optional[str] = None


class ChromeSwitchTabArgs(BaseModel):
    """Arguments for chrome_switch_tab tool."""
    tabId: int
    windowId: Optional[int] = None


class ChromeHandleDialogArgs(BaseModel):
    """Arguments for chrome_handle_dialog tool."""
    action: Literal["accept", "dismiss"]
    promptText: Optional[str] = None


class ChromeHistoryArgs(BaseModel):
    """Arguments for chrome_history tool."""
    text: Optional[str] = None
    startTime: Optional[str] = None
    endTime: Optional[str] = None
    maxResults: Optional[int] = Field(None, ge=1, description="Max results (default 100)")
    excludeCurrentTabs: bool = False


class ChromeBookmarkSearchArgs(BaseModel):
    """Arguments for chrome_bookmark_search tool."""
    query: Optional[str] = None
    maxResults: Optional[int] = Field(None, ge=1, description="Max results (default 50)")
    folderPath: Optional[str] = None


class ChromeBookmarkAddArgs(BaseModel):
    """Arguments for chrome_bookmark_add tool."""
    url: Optional[str] = None
    title: Optional[str] = None
    parentId: Optional[str] = None
    createFolder: bool = False


class ChromeBookmarkDeleteArgs(BaseModel):
    """Arguments for chrome_bookmark_delete tool."""
    bookmarkId: Optional[str] = None
    url: Optional[str] = None
    title: Optional[str] = None


class ChromeHandleDownloadArgs(BaseModel):
    """Arguments for chrome_handle_download tool."""
    filenameContains: Optional[str] = None
    timeoutMs: Optional[int] = Field(None, ge=0, le=300000, description="Timeout in ms (max 300000)")
    waitForComplete: bool = True


class ChromeUploadFileArgs(BaseModel):
    """Arguments for chrome_upload_file tool."""
    selector: str
    tabId: Optional[int] = None
    windowId: Optional[int] = None
    filePath: Optional[str] = None
    fileUrl: Optional[str] = None
    base64Data: Optional[str] = None
    fileName: Optional[str] = "uploaded-file"
    multiple: bool = False


class ChromeRequestElementSelectionArgs(BaseModel):
    """Arguments for chrome_request_element_selection tool."""
    requests: List[Dict[str, Any]]  # List of {id, name, description}
    timeoutMs: Optional[int] = Field(None, ge=0, le=600000, description="Timeout in ms (max 600000)")
    tabId: Optional[int] = None
    windowId: Optional[int] = None


class ChromePerformanceStartTraceArgs(BaseModel):
    """Arguments for performance_start_trace tool."""
    reload: Optional[bool] = None
    autoStop: Optional[bool] = None
    durationMs: Optional[int] = None


class ChromePerformanceStopTraceArgs(BaseModel):
    """Arguments for performance_stop_trace tool."""
    saveToDownloads: bool = True
    filenamePrefix: Optional[str] = None


class ChromePerformanceAnalyzeInsightArgs(BaseModel):
    """Arguments for performance_analyze_insight tool."""
    insightName: Optional[str] = None
    timeoutMs: Optional[int] = None


# Mapping of tool names to their argument validators
TOOL_VALIDATORS = {
    "chrome_read_page": ChromeReadPageArgs,
    "chrome_computer": ChromeComputerArgs,
    "chrome_click_element": ChromeClickElementArgs,
    "chrome_fill_or_select": ChromeFillOrSelectArgs,
    "chrome_keyboard": ChromeKeyboardArgs,
    "chrome_console": ChromeConsoleArgs,
    "chrome_network_capture": ChromeNetworkCaptureArgs,
    "chrome_gif_recorder": ChromeGifRecorderArgs,
    "chrome_javascript": ChromeJavascriptArgs,
    "chrome_navigate": ChromeNavigateArgs,
    "chrome_close_tabs": ChromeCloseTabsArgs,
    "chrome_switch_tab": ChromeSwitchTabArgs,
    "chrome_handle_dialog": ChromeHandleDialogArgs,
    "chrome_history": ChromeHistoryArgs,
    "chrome_bookmark_search": ChromeBookmarkSearchArgs,
    "chrome_bookmark_add": ChromeBookmarkAddArgs,
    "chrome_bookmark_delete": ChromeBookmarkDeleteArgs,
    "chrome_handle_download": ChromeHandleDownloadArgs,
    "chrome_upload_file": ChromeUploadFileArgs,
    "chrome_request_element_selection": ChromeRequestElementSelectionArgs,
    "performance_start_trace": ChromePerformanceStartTraceArgs,
    "performance_stop_trace": ChromePerformanceStopTraceArgs,
    "performance_analyze_insight": ChromePerformanceAnalyzeInsightArgs,
}