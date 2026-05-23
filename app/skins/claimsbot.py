"""
ClaimsBot skin — insurance claim intake + policy comparison + decision.
Company: Shield Insurance | Agent: Jordan

Flow:
  1. Caller identifies themselves (phone lookup → policy found)
  2. Jordan collects incident details
  3. file_claim tool compares against policy rules
  4. Instant approve / partial / deny decision returned
  5. Claim record written to claims.json
"""
import json
import uuid
from datetime import date, timedelta, datetime
from pathlib import Path
from app.models.intent import ClassificationResult

POLICIES_FILE = Path(__file__).parent.parent.parent / "mock_data" / "policies.json"
CLAIMS_FILE   = Path(__file__).parent.parent.parent / "mock_data" / "claims.json"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_policies() -> dict:
    return json.loads(POLICIES_FILE.read_text())

def _load_claims() -> dict:
    return json.loads(CLAIMS_FILE.read_text())

def _save_claims(data: dict) -> None:
    CLAIMS_FILE.write_text(json.dumps(data, indent=2))


# ── System context ─────────────────────────────────────────────────────────────

def _system_context() -> str:
    today = date.today().strftime("%A, %B %d, %Y")
    return (
        f"Today is {today}. "
        "You are Jordan, an AI claims assistant for Shield Insurance. "
        "You help policyholders file new insurance claims and check existing claim status. "
        "You have already greeted the caller — never re-introduce yourself mid-conversation. "
        "When filing a new claim, naturally collect in this order: "
        "full name and policy number (or confirm via phone lookup), "
        "date of the incident, "
        "type of incident (collision, theft, weather damage, fire, medical), "
        "brief description of what happened, "
        "estimated damage or loss amount in dollars. "
        "Once you have all details, call file_claim to get an instant decision. "
        "Communicate the decision warmly and clearly — "
        "if approved, explain the payout after deductible; "
        "if denied, explain why and what isn't covered; "
        "if partial, explain the cap. "
        "Speak naturally — never use numbered lists out loud. "
        "Be empathetic — callers filing claims have often just had a difficult experience. "
        "Keep responses concise and clear."
    )


SYSTEM_CONTEXT = _system_context()


# ── Approval engine ───────────────────────────────────────────────────────────

# Maps what a caller might say → policy coverage key
INCIDENT_TYPE_MAP = {
    "collision":      "collision",
    "crash":          "collision",
    "accident":       "collision",
    "hit":            "collision",
    "theft":          "theft",
    "stolen":         "theft",
    "robbery":        "theft",
    "weather":        "weather_damage",
    "flood":          "weather_damage",
    "hail":           "weather_damage",
    "storm":          "weather_damage",
    "fire":           "fire",
    "medical":        "medical",
    "injury":         "medical",
    "hospital":       "medical",
}

def _map_incident_type(incident_type: str) -> str:
    """Normalize caller's incident description to a policy coverage key."""
    lower = incident_type.lower()
    for keyword, coverage_key in INCIDENT_TYPE_MAP.items():
        if keyword in lower:
            return coverage_key
    return incident_type.lower().replace(" ", "_")


def _evaluate_claim(policy: dict, incident_type: str, amount: float) -> dict:
    """
    Compare claim against policy rules.
    Returns decision dict with status, reason, and payout.
    """
    coverage = policy["coverage"]
    coverage_key = _map_incident_type(incident_type)
    deductible = coverage.get("deductible", 0)
    max_payout = coverage.get("max_payout", 0)

    # Check 1: Is this type of incident covered?
    if not coverage.get(coverage_key, False):
        return {
            "status": "denied",
            "reason": f"{incident_type.title()} is not covered under your {policy['policy_type']} policy.",
            "payout": 0,
        }

    # Check 2: Is the amount below the deductible?
    if amount <= deductible:
        return {
            "status": "denied",
            "reason": f"Claim amount (${amount:,.0f}) is at or below your deductible of ${deductible:,.0f}.",
            "payout": 0,
        }

    # Check 3: Calculate payout — cap at max_payout
    raw_payout = amount - deductible
    if raw_payout > max_payout:
        return {
            "status": "partial",
            "reason": (
                f"Claim approved but capped at your policy maximum of ${max_payout:,.0f}. "
                f"After your ${deductible:,.0f} deductible, payout is ${max_payout:,.0f}."
            ),
            "payout": max_payout,
        }

    return {
        "status": "approved",
        "reason": (
            f"{incident_type.title()} is covered under your policy. "
            f"After your ${deductible:,.0f} deductible, your payout is ${raw_payout:,.0f}."
        ),
        "payout": raw_payout,
    }


# ── Tool handlers ─────────────────────────────────────────────────────────────

def lookup_policy(phone: str) -> str:
    """Look up a policy by phone number."""
    data = _load_policies()
    policy = next((p for p in data["policies"] if p["phone"] == phone), None)
    if not policy:
        return "No policy found for this phone number. Can you provide your policy number?"
    return (
        f"Found policy {policy['policy_id']} for {policy['holder_name']}. "
        f"Policy type: {policy['policy_type']}. Status: {policy['status']}."
    )


def file_claim(
    phone: str,
    incident_date: str,
    incident_type: str,
    description: str,
    estimated_amount: float,
    policy_id: str | None = None,
) -> str:
    """
    File a claim, compare against policy, return instant decision.
    Writes approved/denied claim to claims.json.
    """
    # Find policy
    data = _load_policies()
    if policy_id:
        policy = next((p for p in data["policies"] if p["policy_id"] == policy_id), None)
    else:
        policy = next((p for p in data["policies"] if p["phone"] == phone), None)

    if not policy:
        return "I couldn't find your policy. Please provide your policy number."

    if policy["status"] != "active":
        return f"Your policy {policy['policy_id']} is not currently active. Please contact us to reinstate."

    # Evaluate the claim
    decision = _evaluate_claim(policy, incident_type, estimated_amount)

    # Write claim record
    claims_data = _load_claims()
    claim = {
        "claim_id": f"CLM-{uuid.uuid4().hex[:6].upper()}",
        "policy_id": policy["policy_id"],
        "holder_name": policy["holder_name"],
        "phone": phone,
        "incident_date": incident_date,
        "incident_type": incident_type,
        "description": description,
        "estimated_amount": estimated_amount,
        "status": decision["status"],
        "decision_reason": decision["reason"],
        "payout": decision["payout"],
        "filed_date": date.today().isoformat(),
    }
    claims_data["claims"].append(claim)
    _save_claims(claims_data)

    return (
        f"Claim {claim['claim_id']} filed. Decision: {decision['status'].upper()}. "
        f"{decision['reason']} "
        f"Your claim ID is {claim['claim_id']} — please save this for your records."
    )


def check_claim_status(phone: str) -> str:
    """Look up existing claim status by phone number."""
    data = _load_claims()
    # Get most recent claim for this phone
    user_claims = [c for c in data["claims"] if c["phone"] == phone]
    if not user_claims:
        return "I don't see any existing claims for this number. Would you like to file a new claim?"
    claim = user_claims[-1]
    return (
        f"Your most recent claim (ID: {claim['claim_id']}) for {claim['incident_type']} "
        f"on {claim['incident_date']} is {claim['status'].upper()}. "
        f"{claim['decision_reason']} "
        f"Filed on {claim['filed_date']}."
    )


# ── Skin interface ────────────────────────────────────────────────────────────

def handle_schedule(classification: ClassificationResult, caller_phone: str) -> str:
    # Claims don't schedule — treat as resolve
    return handle_resolve(classification, caller_phone)


def handle_resolve(classification: ClassificationResult, caller_phone: str) -> str:
    entities = classification.extracted_entities
    query = entities.get("query_type", "").lower()
    if "status" in query or "existing" in query:
        return check_claim_status(caller_phone)
    return lookup_policy(caller_phone)


# ── Vapi assistant config ─────────────────────────────────────────────────────

def assistant_config(webhook_url: str) -> dict:
    return {
        "name": "Jordan",
        "model": {
            "provider": "anthropic",
            "model": "claude-sonnet-4-5",
            "systemPrompt": _system_context(),
            "temperature": 0.3,
        },
        "voice": {
            "provider": "11labs",
            "voiceId": "bella",  # warm, professional female voice
        },
        "firstMessage": (
            "Thank you for calling Shield Insurance. "
            "I'm Jordan, an AI claims assistant. "
            "How can I help you today?"
        ),
        "endCallMessage": "Thank you for calling Shield Insurance. We'll be in touch shortly.",
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
                "name": "lookup_policy",
                "description": "Look up a customer's insurance policy by phone number.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "phone": {"type": "string"},
                    },
                },
                "serverUrl": f"{webhook_url}/vapi/webhook",
            },
            {
                "name": "file_claim",
                "description": "File a new insurance claim and get an instant approval decision.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "incident_date":     {"type": "string", "description": "Date of incident YYYY-MM-DD"},
                        "incident_type":     {"type": "string", "description": "e.g. collision, theft, weather damage, fire, medical"},
                        "description":       {"type": "string", "description": "Brief description of what happened"},
                        "estimated_amount":  {"type": "number", "description": "Estimated damage or loss in dollars"},
                        "policy_id":         {"type": "string", "description": "Policy ID if caller provides it"},
                    },
                    "required": ["incident_date", "incident_type", "description", "estimated_amount"],
                },
                "serverUrl": f"{webhook_url}/vapi/webhook",
            },
            {
                "name": "check_claim_status",
                "description": "Check the status of an existing insurance claim.",
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
