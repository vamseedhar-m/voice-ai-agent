# Voice AI Support Agent

A production-style voice agent that handles real inbound phone calls end-to-end.
Callers speak naturally; the agent classifies intent, calls tools, and resolves
or escalates — without human intervention.

Three domain skins on a shared architecture:

| Skin | Domain |
|------|--------|
| **HealthBot** | Patient appointment scheduling + insurance verification |
| **HVACBot** *(coming)* | Service booking + technician dispatch |
| **ClaimsBot** *(coming)* | Insurance claim intake + status lookup |

---

## Architecture

```
Caller → Vapi (phone/STT/TTS)
           ↓  POST /vapi/webhook
      FastAPI server
           ↓
    Intent Classifier          ← Claude (tool-call forces structured output)
    (schedule | resolve | escalate)
           ↓
    Tool Execution
    ├── calendar.py            ← mock JSON / Google Calendar
    └── crm.py                 ← mock patient/claim store
           ↓
    Response Generator         ← Claude (short, voice-optimized)
           ↓
      JSON → Vapi → TTS → Caller
```

### Key design decisions

- **Structured intent classification**: Claude is forced to call a `classify_intent`
  tool so the output is always machine-parseable JSON — no brittle regex on free text.
- **Confidence-based escalation**: if Claude's confidence falls below
  `ESCALATION_THRESHOLD` (default 0.4), the call is automatically routed to a human.
- **Skin pattern**: each skin (`healthbot.py`, etc.) supplies a `SYSTEM_CONTEXT`,
  `handle_schedule()`, `handle_resolve()`, and `assistant_config()`. Swap the active
  skin via `ACTIVE_SKIN` env var — no code changes.
- **Conversation memory**: per-call history is kept in memory (keyed by Vapi call ID)
  so Claude has multi-turn context within a single call.

---

## Quickstart

### 1. Install dependencies

```bash
cd voice-ai-agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Fill in ANTHROPIC_API_KEY and VAPI_API_KEY
```

### 3. Expose localhost with ngrok

```bash
ngrok http 8000
# Copy the https URL, e.g. https://abc123.ngrok.io
# Set PUBLIC_URL=https://abc123.ngrok.io in .env
```

### 4. Run the server

```bash
python run.py
# Server starts at http://0.0.0.0:8000
# Health check: curl http://localhost:8000/health
```

### 5. Run tests

```bash
pytest tests/ -v
```

---

## Vapi Configuration (step-by-step)

### Step 1 — Create a Vapi account

Sign up at https://vapi.ai — the free tier gives you a US phone number and
~$5 of usage credit, enough for dozens of test calls.

### Step 2 — Get a phone number

Dashboard → **Phone Numbers** → **Buy Number** → choose a US number.
Copy the **Phone Number ID** into your `.env`.

### Step 3 — Create the HealthBot assistant

**Option A — JSON editor (recommended)**

1. Dashboard → **Assistants** → **Create Assistant**
2. Click **JSON** tab
3. Paste the contents of `.vapi/healthbot_assistant.json`
4. Replace both `YOUR_PUBLIC_URL` with your ngrok/Railway URL
5. Save

**Option B — assistant-request webhook**

Set the phone number's **Assistant** to *"via server URL"* and enter
`https://YOUR_PUBLIC_URL/vapi/webhook`. Vapi will call your server on every
new call and use the assistant config your server returns dynamically.
This is how the `assistant-request` handler in `app/main.py` works.

### Step 4 — Assign the assistant to your phone number

Dashboard → **Phone Numbers** → click your number →
**Inbound** → select **HealthBot** → Save.

### Step 5 — Test it

Call your Vapi phone number. You should hear:
> "Thank you for calling Sunrise Family Clinic. This is HealthBot. How can I help you today?"

Try:
- *"I'd like to book an appointment for next Tuesday"*
- *"Is my insurance on file?"*
- *"I want to speak to a human"* (triggers escalation)

---

## Project structure

```
voice-ai-agent/
├── app/
│   ├── main.py              # FastAPI app + webhook router
│   ├── agents/
│   │   ├── classifier.py    # Intent classification via Claude tool-call
│   │   └── responder.py     # Voice response generation
│   ├── models/
│   │   ├── vapi.py          # Pydantic shapes for Vapi payloads
│   │   └── intent.py        # Intent enum + ClassificationResult
│   ├── tools/
│   │   ├── calendar.py      # Appointment CRUD (mock + Google Calendar)
│   │   └── crm.py           # Patient / insurance lookup
│   └── skins/
│       ├── healthbot.py     # HealthBot domain skin ✅
│       ├── hvacbot.py       # HVACBot skin (TODO)
│       └── claimsbot.py     # ClaimsBot skin (TODO)
├── mock_data/
│   ├── appointments.json    # Seed appointment + slot data
│   └── patients.json        # Seed patient + insurance data
├── tests/
│   ├── test_classifier.py   # Unit tests (mocked Claude)
│   └── test_calendar.py     # Integration tests for calendar tool
├── .vapi/
│   └── healthbot_assistant.json  # Paste-ready Vapi assistant config
├── .env.example
├── requirements.txt
└── run.py
```

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | ✅ | Anthropic API key |
| `VAPI_API_KEY` | ✅ | Vapi API key |
| `PUBLIC_URL` | ✅ | Publicly accessible URL for this server |
| `ACTIVE_SKIN` | — | `healthbot` (default) \| `hvacbot` \| `claimsbot` |
| `CALENDAR_BACKEND` | — | `mock` (default) \| `google_calendar` |
| `ESCALATION_THRESHOLD` | — | `0.4` (default) — confidence below this escalates |
| `VAPI_WEBHOOK_SECRET` | — | Optional HMAC secret for webhook verification |

---

## Extending to HVACBot / ClaimsBot

1. Copy `app/skins/healthbot.py` → `hvacbot.py` (or `claimsbot.py`)
2. Update `SYSTEM_CONTEXT`, `handle_schedule()`, `handle_resolve()`, and `assistant_config()`
3. Add matching mock data in `mock_data/`
4. Register the skin in the `SKINS` dict in `app/main.py`
5. Set `ACTIVE_SKIN=hvacbot` in `.env`

No other changes needed.

---

## Deploying to Railway (free tier)

```bash
# From voice-ai-agent/
railway login
railway init
railway up
railway domain   # Get your public URL
```

Set all env vars in Railway dashboard → Variables.
Update `PUBLIC_URL` and both Vapi `serverUrl` fields to the Railway URL.
