"""
HealthBot skin — patient appointment scheduling + insurance verification.

A "skin" supplies:
  - SYSTEM_CONTEXT  : injected into every Claude call
  - handle_schedule : called when intent == "schedule"
  - handle_resolve  : called when intent == "resolve"
  - assistant_config: Vapi assistant definition (returned on assistant-request)
"""
import json
from datetime import date
from app.models.intent import ClassificationResult
from app.tools import calendar, crm


def _system_context() -> str:
    """Build system prompt with today's date injected so Claude uses the right year."""
    today = date.today().strftime("%A, %B %d, %Y")  # e.g. "Friday, May 22, 2026"
    return (
        f"Today's date is {today}. "
        "You are HealthBot, a friendly medical receptionist for Sunrise Family Clinic. "
        "You help patients schedule appointments, answer questions about their upcoming visits, "
        "and verify insurance coverage. "
        "The clinic has exactly two doctors: Dr. John and Dr. Nguyen. "
        "Never ask which Dr. John — there is only one. "
        "When a caller wants to book an appointment, always ask for their full name "
        "if they have not already provided it. Pass their name as patient_name when calling book_appointment. "
        "When a caller mentions a date without a year, always assume the current year. "
        "Always be empathetic, HIPAA-aware (never repeat sensitive data aloud unnecessarily), "
        "and keep responses brief for phone delivery."
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
