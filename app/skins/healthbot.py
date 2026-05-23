"""
HealthBot skin — patient appointment scheduling + insurance verification.

A "skin" supplies:
  - SYSTEM_CONTEXT  : injected into every Claude call
  - handle_schedule : called when intent == "schedule"
  - handle_resolve  : called when intent == "resolve"
  - assistant_config: Vapi assistant definition (returned on assistant-request)
"""
import json
from datetime import date, timedelta
from app.models.intent import ClassificationResult
from app.tools import calendar, crm


def _build_date_reference() -> str:
    """
    Build a dynamic 14-day date reference so Claude always knows
    the correct day-to-date mapping without any hardcoded dates.
    e.g. "Tue=May 26, Wed=May 27, Thu=May 28, Fri=May 29, ..."
    """
    today = date.today()
    entries = []
    for i in range(14):
        d = today + timedelta(days=i)
        label = "Today" if i == 0 else d.strftime("%a")
        entries.append(f"{label}={d.strftime('%b %d')}")
    return ", ".join(entries)


def _system_context() -> str:
    """Build system prompt with today's date and rolling 14-day calendar injected."""
    today = date.today().strftime("%A, %B %d, %Y")
    date_ref = _build_date_reference()
    return (
        f"Today is {today}. "
        f"Date reference for the next 14 days: {date_ref}. "
        "When a caller says a day name like 'Tuesday' or 'next Friday', "
        "use this reference to find the exact date — never guess. "
        "You are Mike, an AI assistant and friendly medical receptionist "
        "for Sunrise Family Clinic. "
        "The clinic has two doctors: Dr. John and Dr. Nguyen. "
        "You have already greeted the caller — never re-introduce yourself "
        "or say hello again mid-conversation. "
        "Before booking any appointment, you MUST ask for the caller's full name "
        "if they have not said it. Do not skip this step. "
        "Pass the caller's name as patient_name when calling book_appointment. "
        "Speak naturally and warmly — never use numbered lists or bullet points. "
        "Keep responses short and conversational, like a real receptionist on the phone. "
        "Always be empathetic and HIPAA-aware."
    )


# Module-level constant for compatibility with classifier/responder imports
SYSTEM_CONTEXT = _system_context()


def handle_schedule(classification: ClassificationResult, caller_phone: str) -> str:
    """Book or look up an appointment based on extracted entities."""
    entities = classification.extracted_entities
    date = entities.get("date")

    # If they asked to check availability, return open slots.
    if not entities.get("doctor") and not entities.get("time"):
        slots = calendar.get_available_slots(date)
        if not slots:
            return "I'm sorry, we don't have any open slots for that date. Can I check another day for you?"
        slot_list = ", ".join(f"{s['date']} at {s['time']} with {s['doctor']}" for s in slots[:3])
        return f"We have openings on {slot_list}. Which one works for you?"

    # Try to book with all required fields.
    patient = crm.get_patient_by_phone(caller_phone)
    patient_name = patient["name"] if patient else entities.get("name", "Unknown")

    try:
        appt = calendar.book_appointment(
            patient_name=patient_name,
            phone=caller_phone,
            service=entities.get("service", "General visit"),
            date=entities.get("date", ""),
            time=entities.get("time", ""),
            doctor=entities.get("doctor", ""),
        )
        return (
            f"You're all set! I've booked a {appt['service']} appointment "
            f"for {appt['date']} at {appt['time']} with {appt['doctor']}. "
            "You'll receive a confirmation shortly."
        )
    except ValueError as e:
        return f"I'm sorry, that slot is no longer available. {str(e)} Let me find you another time."


def handle_resolve(classification: ClassificationResult, caller_phone: str) -> str:
    """Answer status / insurance queries."""
    entities = classification.extracted_entities
    query_type = entities.get("query_type", "").lower()

    # Insurance verification request.
    if "insurance" in query_type or "coverage" in query_type:
        patient = crm.get_patient_by_phone(caller_phone)
        if not patient:
            return "I couldn't find your records with this phone number. Can you confirm the number on file?"
        result = crm.verify_insurance(patient["id"])
        if result["verified"]:
            return f"Good news — your {result['provider']} insurance is verified and on file."
        return (
            f"Your {result['provider']} insurance hasn't been verified yet. "
            "Would you like me to transfer you to our billing team?"
        )

    # Existing appointment lookup.
    appt = calendar.get_appointment_by_phone(caller_phone)
    if appt:
        return (
            f"I have you down for a {appt['service']} appointment "
            f"on {appt['date']} at {appt['time']} with {appt['doctor']}. "
            "Is there anything else I can help you with?"
        )

    return "I don't see any upcoming appointments for your number. Would you like to schedule one?"


# ── Vapi assistant definition ─────────────────────────────────────────────────
# Returned verbatim on Vapi's "assistant-request" webhook.
# Vapi will use this assistant config for the rest of the call.

def assistant_config(webhook_url: str) -> dict:
    """
    Build the Vapi assistant payload.

    webhook_url: publicly accessible URL of this FastAPI server,
                 e.g. https://abc123.ngrok.io
    """
    return {
        "name": "HealthBot",
        "model": {
            "provider": "anthropic",
            "model": "claude-sonnet-4-5",
            "systemPrompt": SYSTEM_CONTEXT,
            "temperature": 0.3,
        },
        "voice": {
            "provider": "11labs",
            "voiceId": "rachel",   # warm, professional female voice
        },
        "firstMessage": (
            "Thank you for calling Sunrise Family Clinic. "
            "This is HealthBot. How can I help you today?"
        ),
        "endCallMessage": "Thank you for calling. Have a wonderful day!",
        "endCallPhrases": ["goodbye", "bye", "that's all", "thank you bye"],
        "maxDurationSeconds": 180,   # 3-minute cap — protects against runaway costs
        "transcriber": {
            "provider": "deepgram",
            "model": "nova-2",
            "language": "en-US",
        },
        "serverUrl": f"{webhook_url}/vapi/webhook",
        "serverUrlSecret": None,   # set VAPI_WEBHOOK_SECRET in env and add here
        # Instruct Vapi to call our webhook for function calls instead of
        # handling them internally.
        "functions": [
            {
                "name": "check_availability",
                "description": "Check available appointment slots.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "description": "Date in YYYY-MM-DD format"}
                    },
                },
                "serverUrl": f"{webhook_url}/vapi/webhook",
            },
            {
                "name": "book_appointment",
                "description": "Book an appointment for the caller.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string"},
                        "time": {"type": "string"},
                        "doctor": {"type": "string"},
                        "service": {"type": "string"},
                    },
                    "required": ["date", "time", "doctor"],
                },
                "serverUrl": f"{webhook_url}/vapi/webhook",
            },
            {
                "name": "verify_insurance",
                "description": "Check whether the caller's insurance is on file.",
                "parameters": {"type": "object", "properties": {}},
                "serverUrl": f"{webhook_url}/vapi/webhook",
            },
        ],
    }
