"""
HVACBot skin — service booking + technician dispatch for Swift Fix HVAC.

Differences from HealthBot:
- Caller picks SERVICE TYPE (not a technician — that's auto-assigned)
- Caller provides ADDRESS and PHONE (not just phone lookup)
- Time windows (8am–12pm) instead of exact appointment times
- check_service_status replaces verify_insurance
"""
import json
import uuid
from datetime import date, timedelta, datetime
from pathlib import Path
from app.models.intent import ClassificationResult

TECHNICIANS_FILE = Path(__file__).parent.parent.parent / "mock_data" / "technicians.json"
REQUESTS_FILE    = Path(__file__).parent.parent.parent / "mock_data" / "service_requests.json"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_techs() -> dict:
    return json.loads(TECHNICIANS_FILE.read_text())

def _load_requests() -> dict:
    return json.loads(REQUESTS_FILE.read_text())

def _save_requests(data: dict) -> None:
    REQUESTS_FILE.write_text(json.dumps(data, indent=2))


# ── System context ────────────────────────────────────────────────────────────

def _build_date_reference() -> str:
    today = date.today()
    entries = []
    for i in range(14):
        d = today + timedelta(days=i)
        label = "Today" if i == 0 else d.strftime("%a")
        entries.append(f"{label}={d.strftime('%Y-%m-%d')}")
    return ", ".join(entries)


def _system_context() -> str:
    today = date.today().strftime("%A, %B %d, %Y")
    date_ref = _build_date_reference()
    return (
        f"Today is {today}. "
        f"Date reference for the next 14 days: {date_ref}. "
        "When a caller says a day name, use this reference for the exact date. "
        "You are Alex, an AI assistant for Swift Fix HVAC — a professional heating "
        "and cooling service company. "
        "You help customers book service visits and check the status of existing requests. "
        "You have already greeted the caller — never re-introduce yourself mid-conversation. "
        "When booking a service visit, collect in this order: "
        "1) What is the issue or service needed? "
        "2) What is the service address? "
        "3) Best callback number (confirm if they say 'same as this one'). "
        "4) Preferred date or time window. "
        "Do NOT ask the caller to pick a technician — that is assigned automatically. "
        "Speak naturally and warmly — never use numbered lists out loud. "
        "Keep responses brief and conversational. "
        "If a caller is frustrated or the issue is urgent/emergency, offer to escalate "
        "to a live dispatcher immediately."
    )


SYSTEM_CONTEXT = _system_context()


# ── Tool handlers ─────────────────────────────────────────────────────────────

def get_available_slots(date_str: str | None = None) -> str:
    """Return available technician slots with day names embedded."""
    data = _load_techs()
    slots = data["available_slots"]
    if date_str:
        slots = [s for s in slots if s["date"] == date_str]

    today = date.today()
    ref = ", ".join(
        f"{(today + timedelta(days=i)).strftime('%A')}={(today + timedelta(days=i)).strftime('%Y-%m-%d')}"
        for i in range(14)
    )

    enriched = []
    for s in slots[:5]:
        try:
            day_name = datetime.strptime(s["date"], "%Y-%m-%d").strftime("%A %B %d")
        except Exception:
            day_name = s["date"]
        enriched.append({
            "date": s["date"],
            "day": day_name,
            "window": s["window"].replace("–", "-"),  # normalize for Claude
        })

    header = f"TODAY IS {today.strftime('%A %B %d %Y')}. Day reference: {ref}."
    if not enriched:
        return f"{header} No available slots for that date. Try another day."
    return f"{header} Available slots: {json.dumps(enriched)}"


def _norm_window(w: str) -> str:
    """Normalize window format — treat em dash and hyphen as the same.
    e.g. '8am-12pm' and '8am–12pm' both become '8am-12pm'
    Also handle spaces: '8am - 12pm' → '8am-12pm'
    """
    return w.replace("–", "-").replace("—", "-").replace(" - ", "-").replace(" ", "").lower()


def book_service(
    customer_name: str,
    phone: str,
    address: str,
    service_type: str,
    date_str: str,
    window: str,
) -> str:
    """Book a service visit. Auto-assigns a technician."""
    data = _load_techs()

    # Find a matching slot — normalize both sides so dash variants match
    slot = next(
        (s for s in data["available_slots"]
         if s["date"] == date_str and _norm_window(s["window"]) == _norm_window(window)),
        None,
    )
    if not slot:
        # Return available slots so Claude can offer alternatives
        available = [
            f"{s['day'] if 'day' in s else s['date']} {s['window']}"
            for s in data["available_slots"][:3]
        ]
        options = ", ".join(available) if available else "no slots currently available"
        return f"That window isn't available. Other options: {options}."

    # Remove the slot from availability
    data["available_slots"].remove(slot)
    TECHNICIANS_FILE.write_text(json.dumps(data, indent=2))

    # Look up technician name
    tech = next((t for t in data["technicians"] if t["id"] == slot["technician_id"]), None)
    tech_name = tech["name"] if tech else "our technician"

    # Create the service request
    requests_data = _load_requests()
    req = {
        "id": f"req-{uuid.uuid4().hex[:6]}",
        "customer_name": customer_name,
        "phone": phone,
        "address": address,
        "service_type": service_type,
        "date": date_str,
        "window": window,
        "technician_id": slot["technician_id"],
        "status": "confirmed",
        "notes": "",
    }
    requests_data["service_requests"].append(req)
    _save_requests(requests_data)

    return (
        f"Booked! {tech_name} will arrive at {address} on {date_str} "
        f"between {window} for {service_type}. "
        f"Confirmation ID: {req['id']}. "
        f"You'll receive a call 30 minutes before arrival."
    )


def check_service_status(phone: str) -> str:
    """Look up service request status by phone number."""
    data = _load_requests()
    req = next(
        (r for r in data["service_requests"] if r["phone"] == phone),
        None,
    )
    if not req:
        return "I couldn't find a service request for this number. Can you give me your confirmation ID?"
    return (
        f"Your {req['service_type']} request (ID: {req['id']}) is {req['status']}. "
        f"It's scheduled for {req['date']} between {req['window']} at {req['address']}."
    )


# ── Skin interface (matches HealthBot pattern) ────────────────────────────────

def handle_schedule(classification: ClassificationResult, caller_phone: str) -> str:
    entities = classification.extracted_entities
    date_str = entities.get("date", "")
    window   = entities.get("window", "")

    if not date_str:
        return get_available_slots()

    if not window:
        return get_available_slots(date_str)

    return book_service(
        customer_name=entities.get("customer_name", "Customer"),
        phone=caller_phone,
        address=entities.get("address", "Address not provided"),
        service_type=entities.get("service_type", "General service"),
        date_str=date_str,
        window=window,
    )


def handle_resolve(classification: ClassificationResult, caller_phone: str) -> str:
    return check_service_status(caller_phone)


# ── Vapi assistant config ─────────────────────────────────────────────────────

def assistant_config(webhook_url: str) -> dict:
    return {
        "name": "Alex",
        "model": {
            "provider": "anthropic",
            "model": "claude-sonnet-4-5",
            "systemPrompt": _system_context(),
            "temperature": 0.3,
        },
        "voice": {
            "provider": "11labs",
            "voiceId": "adam",   # professional male voice
        },
        "firstMessage": (
            "Thank you for calling Swift Fix HVAC. "
            "I'm Alex, an AI assistant. "
            "How can I help you today?"
        ),
        "endCallMessage": "Thanks for calling Swift Fix. Stay comfortable!",
        "endCallPhrases": ["goodbye", "bye", "that's all", "thank you bye"],
        "maxDurationSeconds": 180,
        "transcriber": {
            "provider": "deepgram",
            "model": "nova-2",
            "language": "en-US",
        },
        "serverUrl": f"{webhook_url}/vapi/webhook",
        "functions": [
            {
                "name": "check_availability",
                "description": "Check available technician time windows.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "description": "Date in YYYY-MM-DD format"}
                    },
                },
                "serverUrl": f"{webhook_url}/vapi/webhook",
            },
            {
                "name": "book_service",
                "description": "Book a technician visit for the customer.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "customer_name": {"type": "string"},
                        "address":       {"type": "string", "description": "Full service address"},
                        "service_type":  {"type": "string", "description": "e.g. AC repair, furnace repair"},
                        "date":          {"type": "string", "description": "YYYY-MM-DD"},
                        "window":        {"type": "string", "description": "Time window e.g. 8am–12pm"},
                    },
                    "required": ["customer_name", "address", "service_type", "date", "window"],
                },
                "serverUrl": f"{webhook_url}/vapi/webhook",
            },
            {
                "name": "check_service_status",
                "description": "Check the status of an existing service request.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "phone": {"type": "string"},
                    },
                },
                "serverUrl": f"{webhook_url}/vapi/webhook",
            },
        ],
    }
