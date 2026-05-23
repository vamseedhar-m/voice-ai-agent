"""
Pydantic models matching Vapi's webhook payload shapes.
Docs: https://docs.vapi.ai/webhooks
"""
from enum import Enum
from typing import Any
from pydantic import BaseModel


class VapiMessageType(str, Enum):
    ASSISTANT_REQUEST = "assistant-request"
    STATUS_UPDATE = "status-update"
    END_OF_CALL_REPORT = "end-of-call-report"
    FUNCTION_CALL = "function-call"   # old Vapi format
    TOOL_CALLS = "tool-calls"         # new Vapi agent builder format
    TRANSCRIPT = "transcript"
    HANG = "hang"


class VapiMessage(BaseModel):
    type: VapiMessageType
    call: dict[str, Any] | None = None
    # function-call specific
    functionCall: dict[str, Any] | None = None
    # transcript specific
    transcript: str | None = None
    # status-update specific
    status: str | None = None
    # end-of-call-report specific
    endedReason: str | None = None
    summary: str | None = None
    recordingUrl: str | None = None


class VapiWebhookPayload(BaseModel):
    message: VapiMessage


class AssistantResponse(BaseModel):
    """Response to Vapi's assistant-request — defines the assistant on the fly."""
    assistant: dict[str, Any]


class FunctionCallResponse(BaseModel):
    """Response to Vapi's function-call message."""
    result: str
