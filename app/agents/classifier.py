"""
Intent classifier — asks Claude to categorise the caller's message into
one of three intents: schedule | resolve | escalate.

We use a structured tool-call so Claude is forced to return machine-readable
JSON rather than freeform prose.
"""
import json
import os
import anthropic
from app.models.intent import ClassificationResult, Intent

_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# The classifier tool schema Claude must fill in.
_CLASSIFIER_TOOL = {
    "name": "classify_intent",
    "description": (
        "Classify the caller's intent and extract key entities from their message."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": ["schedule", "resolve", "escalate"],
                "description": (
                    "schedule = caller wants to book/reschedule/cancel an appointment; "
                    "resolve = caller has a question or status request answerable from data; "
                    "escalate = complaint, anger, or topic outside agent scope."
                ),
            },
            "confidence": {
                "type": "number",
                "description": "Confidence score 0.0–1.0.",
            },
            "reasoning": {
                "type": "string",
                "description": "One sentence explaining the classification.",
            },
            "extracted_entities": {
                "type": "object",
                "description": (
                    "Key-value pairs of entities pulled from the transcript, "
                    "e.g. {\"date\": \"tomorrow afternoon\", \"service\": \"oil change\"}."
                ),
            },
        },
        "required": ["intent", "confidence", "reasoning", "extracted_entities"],
    },
}


def classify_intent(
    transcript: str,
    skin_context: str,
    conversation_history: list[dict] | None = None,
    escalation_threshold: float | None = None,
) -> ClassificationResult:
    """
    Classify caller intent from a transcript snippet.

    Args:
        transcript: Latest caller utterance.
        skin_context: Domain description injected into the system prompt
                      (e.g. "You are HealthBot, a medical scheduling assistant").
        conversation_history: Prior turns as [{"role": "user"|"assistant", "content": "..."}].
        escalation_threshold: Override the env-level threshold for this call.
    """
    threshold = escalation_threshold or float(os.getenv("ESCALATION_THRESHOLD", "0.4"))

    system_prompt = (
        f"{skin_context}\n\n"
        "Your job RIGHT NOW is only to classify the caller's intent. "
        "Use the classify_intent tool. Do not speak to the caller."
    )

    messages = list(conversation_history or [])
    messages.append({"role": "user", "content": transcript})

    response = _client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=256,
        system=system_prompt,
        tools=[_CLASSIFIER_TOOL],
        tool_choice={"type": "tool", "name": "classify_intent"},
        messages=messages,
    )

    tool_use = next(b for b in response.content if b.type == "tool_use")
    data = tool_use.input

    # Force escalate when confidence falls below threshold.
    intent = Intent(data["intent"])
    if data["confidence"] < threshold and intent != Intent.ESCALATE:
        intent = Intent.ESCALATE
        data["reasoning"] = (
            f"Low confidence ({data['confidence']:.2f}) — escalating to human. "
            + data["reasoning"]
        )

    return ClassificationResult(
        intent=intent,
        confidence=data["confidence"],
        reasoning=data["reasoning"],
        extracted_entities=data.get("extracted_entities", {}),
    )
