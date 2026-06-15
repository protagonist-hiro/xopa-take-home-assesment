from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List


class CallCreate(BaseModel):
    from_number: str = Field(..., alias="from", min_length=1, max_length=50)
    to_number: str = Field(..., alias="to", min_length=1, max_length=50)
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class StateEvent(BaseModel):
    call_id: str
    from_state: Optional[str]
    to_state: str
    timestamp: str


class CallResponse(BaseModel):
    call_id: str
    status: str
    from_number: str
    to_number: str
    websocket_url: str
    created_at: str
    recording_url: Optional[str] = None
    state_history: List[Dict[str, Any]] = []


class MetricsResponse(BaseModel):
    active_calls: int
    total_calls: int
    cps_current: Dict[str, int]
    pending_uploads: int
    completed_calls: int
