"""
FastAPI webhook server for Voice AI Support Agent.

Flow per call:
  Vapi → POST /vapi/webhook  (assistant-request | function-call | status-update | end-of-call-report)
  → intent classifier (Claude)
  → tool execution (calendar / CRM)
  → response generator (Claude)
  → JSON back to Vapi → Vapi speaks it to caller
"""
import hashlib
import hmac
import json
import logging
import os
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from app.agents.classifier import classify_intent
from app.agents.responder import generate_response
from app.models.intent import Intent
from app.models.vapi import VapiMessageType, VapiWebhookPayload

# ── Skin registry ────────────────────────────────────────────────────────────
# Add HVACBot and ClaimsBot here when built.
from app.skins import healthbot as _healthbot

SKINS = {
    "healthbot": _healthbot,
}

ACTIVE_SKIN_NAME = os.getenv("ACTIVE_SKIN", "healthbot")
skin = SKINS[ACTIVE_SKIN_NAME]

# ── App setup ────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Voice AI Support Agent",
    description="Vapi webhook handler powering HealthBot / HVACBot / ClaimsBot",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory conversation store keyed by Vapi call ID.
# Each value is a list of {"role": "user"|"assistant", "content": str} dicts.
_call_history: dict[str, list[dict]] = {}

WEBHOOK_SECRET = os.getenv("VAPI_WEBHOOK_SECRET", "")
PUBLIC_URL = os.getenv("PUBLIC_URL", "https://your-ngrok-url.ngrok.io")


# ── Signature verification ───────────────────────────────────────────────────

def _verify_signature(body: bytes, signature: str | None) -> bool:
    """Verify Vapi's HMAC-SHA256 webhook signature. Skip if secret not set."""
    if not WEBHOOK_SECRET:
        return True
    if not signature:
        return False
    expected = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    return {"status": "ok", "skin": ACTIVE_SKIN_NAME}


@app.post("/vapi/webhook")
async def vapi_webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("x-vapi-signature")

    if not _verify_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload_dict = json.loads(body)
    logger.info("Vapi event: %s", payload_dict.get("message", {}).get("type"))

    message = payload_dict.get("message", {})
    msg_type = message.get("type")

    # ── assistant-request: Vapi asks us to define the assistant ───────────────
    if msg_type == VapiMessageType.ASSISTANT_REQUEST:
        config = skin.assistant_config(PUBLIC_URL)
        return {"assistant": config}

    # ── function-call: old Vapi format ───────────────────────────────────────
    if msg_type == VapiMessageType.FUNCTION_CALL:
        caller_phone = message.get("call", {}).get("customer", {}).get("number", "")
        fn = message.get("functionCall", {})
        fn_name = fn.get("name", "")
        fn_params = fn.get("parameters", {})

        logger.info("Function call: %s params=%s", fn_name, fn_params)
        result = _handle_function_call(fn_name, fn_params, caller_phone)
        return {"result": result}

    # ── tool-calls: new Vapi agent builder format ─────────────────────────────
    if msg_type == VapiMessageType.TOOL_CALLS:
        caller_phone = message.get("call", {}).get("customer", {}).get("number", "")
        tool_call_list = message.get("toolCallList", [])
        results = []

        for tool_call in tool_call_list:
            fn_name = tool_call.get("function", {}).get("name", "")
            # Vapi sends arguments as a JSON string — parse it
            raw_args = tool_call.get("function", {}).get("arguments", "{}")
            try:
                fn_params = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                fn_params = {}

            logger.info("Tool call: %s params=%s", fn_name, fn_params)
            result = _handle_function_call(fn_name, fn_params, caller_phone)
            results.append({
                "toolCallId": tool_call.get("id", ""),
                "result": result,
            })

        return {"results": results}

    # ── transcript: real-time partial transcripts (we use end-of-turn) ────────
    if msg_type == VapiMessageType.TRANSCRIPT:
        # Vapi sends "final" transcripts at end of each speaker turn.
        if message.get("transcriptType") == "final":
            call_id = message.get("call", {}).get("id", "unknown")
            caller_phone = message.get("call", {}).get("customer", {}).get("number", "")
            transcript = message.get("transcript", "")

            response_text = _process_transcript(call_id, caller_phone, transcript)
            logger.info("Response: %s", response_text)
            # Transcript events don't drive the voice response directly —
            # that's handled by the assistant's LLM + function calls.
            # We log here for debugging / analytics.
        return Response(status_code=200)

    # ── status-update ─────────────────────────────────────────────────────────
    if msg_type == VapiMessageType.STATUS_UPDATE:
        status = message.get("status")
        call_id = message.get("call", {}).get("id", "unknown")
        logger.info("Call %s status → %s", call_id, status)
        if status == "ended":
            _call_history.pop(call_id, None)
        return Response(status_code=200)

    # ── end-of-call-report ────────────────────────────────────────────────────
    if msg_type == VapiMessageType.END_OF_CALL_REPORT:
        call_id = message.get("call", {}).get("id", "unknown")
        reason = message.get("endedReason", "unknown")
        summary = message.get("summary", "")
        logger.info("Call %s ended. Reason: %s. Summary: %s", call_id, reason, summary)
        _call_history.pop(call_id, None)
        return Response(status_code=200)

    # ── hang event ────────────────────────────────────────────────────────────
    if msg_type == VapiMessageType.HANG:
        return {"message": "I'm still here. Take your time."}

    return Response(status_code=200)


# ── Internal helpers ─────────────────────────────────────────────────────────

def _process_transcript(call_id: str, caller_phone: str, transcript: str) -> str:
    """
    Full pipeline: classify intent → call tool → generate response.
    Maintains per-call conversation history for context.
    """
    history = _call_history.setdefault(call_id, [])

    classification = classify_intent(
        transcript=transcript,
        skin_context=skin.SYSTEM_CONTEXT,
        conversation_history=history,
    )
    logger.info("Intent: %s (%.2f) — %s", classification.intent, classification.confidence, classification.reasoning)

    tool_output: str | None = None

    if classification.intent == Intent.SCHEDULE:
        tool_output = skin.handle_schedule(classification, caller_phone)
    elif classification.intent == Intent.RESOLVE:
        tool_output = skin.handle_resolve(classification, caller_phone)
    # ESCALATE — no tool, generate_response handles it via template.

    response = generate_response(
        classification=classification,
        skin_context=skin.SYSTEM_CONTEXT,
        tool_output=tool_output,
        conversation_history=history,
    )

    # Append turn to history for continuity.
    history.append({"role": "user", "content": transcript})
    history.append({"role": "assistant", "content": response})

    return response


def _handle_function_call(fn_name: str, params: dict, caller_phone: str) -> str:
    """
    Dispatch Vapi function calls to the appropriate tool.
    These are triggered by Vapi's LLM when it decides to call a declared function.
    """
    from app.tools import calendar as cal, crm

    # Normalize all keys to lowercase so "Time" and "time" both work
    params = {k.lower(): v for k, v in params.items()}

    if fn_name == "get_today_date":
        from datetime import date as _date, timedelta, datetime
        today = _date.today()
        days = []
        for i in range(14):
            d = today + timedelta(days=i)
            label = "Today" if i == 0 else d.strftime("%A")
            days.append(f"{label} = {d.strftime('%Y-%m-%d')} ({d.strftime('%B %d')})")
        return f"Today is {today.strftime('%A, %B %d, %Y')}. Next 14 days: " + "; ".join(days)

    if fn_name == "check_availability":
        from datetime import date as _date, datetime
        slots = cal.get_available_slots(params.get("date"))
        if not slots:
            return "No available slots found for that date."
        # Add human-readable day name to each slot so Claude never has to calculate it
        enriched = []
        for s in slots[:5]:
            try:
                day_name = datetime.strptime(s["date"], "%Y-%m-%d").strftime("%A %B %d")
            except Exception:
                day_name = s["date"]
            enriched.append({**s, "day": day_name})
        return json.dumps(enriched)

    if fn_name == "book_appointment":
        patient = crm.get_patient_by_phone(caller_phone)
        # Priority: name from conversation > name from CRM > fallback
        name = params.get("patient_name") or (patient["name"] if patient else "Caller")
        try:
            appt = cal.book_appointment(
                patient_name=name,
                phone=caller_phone,
                service=params.get("service", "General visit"),
                date=params["date"],
                time=params["time"],
                doctor=params["doctor"],
            )
            return f"Appointment confirmed: {appt['service']} on {appt['date']} at {appt['time']} with {appt['doctor']}."
        except ValueError as e:
            return f"Booking failed: {str(e)}"

    if fn_name == "verify_insurance":
        patient = crm.get_patient_by_phone(caller_phone)
        if not patient:
            return "No patient record found for this phone number."
        result = crm.verify_insurance(patient["id"])
        return json.dumps(result)

    return f"Unknown function: {fn_name}"
