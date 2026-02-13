from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class SmithEvent(BaseModel):
    """Base class for all system events."""

    type: str
    timestamp: datetime = Field(default_factory=datetime.now)
    run_id: str
    trace_id: Optional[str] = None


class StatusEvent(SmithEvent):
    """General status update."""

    type: str = "status"
    message: str


class StepStartEvent(SmithEvent):
    """A tool is about to start."""

    type: str = "step_start"
    step_index: int
    step_id: str
    tool: str
    function: str
    input: Dict[str, Any]


class StepCompleteEvent(SmithEvent):
    """A tool finished execution."""

    type: str = "step_complete"
    step_index: int
    step_id: str
    tool: str
    status: str  # success, error
    result: Any
    duration: float


class ErrorEvent(SmithEvent):
    """Something went wrong."""

    type: str = "error"
    error: str
    details: Optional[str] = None
