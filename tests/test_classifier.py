"""
Unit tests for intent classifier.
These run without hitting the Claude API — we mock the Anthropic client.
"""
import json
from unittest.mock import MagicMock, patch
import pytest
from app.models.intent import Intent
from app.agents.classifier import classify_intent
from app.skins.healthbot import SYSTEM_CONTEXT


def _make_mock_response(intent: str, confidence: float, entities: dict = {}):
    tool_use_block = MagicMock()
    tool_use_block.type = "tool_use"
    tool_use_block.input = {
        "intent": intent,
        "confidence": confidence,
        "reasoning": "Test reasoning.",
        "extracted_entities": entities,
    }
    response = MagicMock()
    response.content = [tool_use_block]
    return response


@patch("app.agents.classifier._client")
def test_schedule_intent(mock_client):
    mock_client.messages.create.return_value = _make_mock_response(
        "schedule", 0.95, {"date": "tomorrow", "service": "checkup"}
    )
    result = classify_intent("I'd like to book an appointment for tomorrow", SYSTEM_CONTEXT)
    assert result.intent == Intent.SCHEDULE
    assert result.confidence == 0.95
    assert result.extracted_entities["service"] == "checkup"


@patch("app.agents.classifier._client")
def test_low_confidence_escalates(mock_client, monkeypatch):
    monkeypatch.setenv("ESCALATION_THRESHOLD", "0.5")
    mock_client.messages.create.return_value = _make_mock_response("schedule", 0.3)
    result = classify_intent("Um... I'm not sure what I need", SYSTEM_CONTEXT)
    assert result.intent == Intent.ESCALATE


@patch("app.agents.classifier._client")
def test_resolve_intent(mock_client):
    mock_client.messages.create.return_value = _make_mock_response(
        "resolve", 0.88, {"query_type": "insurance coverage"}
    )
    result = classify_intent("Is my Blue Cross insurance on file?", SYSTEM_CONTEXT)
    assert result.intent == Intent.RESOLVE
