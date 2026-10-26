"""Pydantic schemas for the monitoring, alerting and drift endpoints (Agents 6 and 7)."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class FeedbackRequest(BaseModel):
    session_id: str
    feedback: Literal["correct", "incorrect"]
    notes: Optional[str] = Field(default=None, max_length=2000)
    reviewed_by: Optional[str] = Field(default=None, max_length=100)


class FeedbackResponse(BaseModel):
    id: int
    session_id: str
    feedback: str
    flagged_for_review: bool
    timestamp: datetime


class AlertRequest(BaseModel):
    alert_type: str = Field(..., max_length=50)
    severity: Literal["info", "warning", "critical"]
    message: str = Field(..., max_length=2000)
    session_id: Optional[str] = None
    timestamp: Optional[datetime] = None


class AlertResponse(BaseModel):
    id: int
    alert_type: str
    severity: str
    message: str
    status: Optional[str]
    session_id: Optional[str]
    timestamp: datetime
    acknowledged: bool
