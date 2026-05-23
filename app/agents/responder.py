"""
Response generator — given an intent result and optional tool output,
asks Claude to produce a short, natural voice response for the caller.
"""
import os
import anthropic
from app.models.intent import ClassificationResult, Intent

_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# Vapi speaks these back to the caller, so keep them conversational and brief.
_ESCALATION_TEMPLATE = (
    "I'm going to connect you with one of our team members who can better help you. "
    "Please hold for just a moment."
)


def generate_response(
    classification: ClassificationResult,
    skin_context: str,
    tool_output: str | None = None,
    conversation_history: list[dict] | None = None,
) -> str:
    """
    Generate a caller-facing voice response.

    Args:
        classification: Output from classify_intent().
        skin_context: Domain system prompt for the active skin.
        tool_output: Serialised result from whichever tool was called, if any.
        conversation_history: Prior turns for context continuity.

    Returns:
        A short string Vapi will speak aloud to the caller.
    """
    if classification.intent == Intent.ESCALATE:
        return _ESCALATION_TEMPLATE

    system_prompt = (
        f"{skin_context}\n\n"
        "You are speaking to a caller over the phone. "
        "Reply in 1–3 short sentences. No bullet points, no markdown. "
        "Be warm, professional, and concise."
    )

    tool_block = f"\n\n[Tool result]: {tool_output}" if tool_output else ""
    user_content = (
        f"Intent classified as '{classification.intent.value}'. "
        f"Entities: {classification.extracted_entities}."
        f"{tool_block}\n\n"
        "Generate the voice response to give back to the caller."
    )

    messages = list(conversation_history or [])
    messages.append({"role": "user", "content": user_content})

    response = _client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=200,
        system=system_prompt,
        messages=messages,
    )

    return response.content[0].text.strip()
