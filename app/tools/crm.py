"""
CRM / patient lookup tool backed by mock_data/patients.json.
For the portfolio this is read-only; a real implementation would hit
your CRM API here.
"""
import json
from pathlib import Path

PATIENTS_FILE = Path(__file__).parent.parent.parent / "mock_data" / "patients.json"


def _load() -> dict:
    return json.loads(PATIENTS_FILE.read_text())


def get_patient_by_phone(phone: str) -> dict | None:
    data = _load()
    return next((p for p in data["patients"] if p["phone"] == phone), None)


def verify_insurance(patient_id: str) -> dict:
    """Return insurance verification status for a patient."""
    data = _load()
    patient = next((p for p in data["patients"] if p["id"] == patient_id), None)
    if not patient:
        return {"verified": False, "reason": "Patient not found"}
    return {
        "verified": patient["insurance_verified"],
        "provider": patient["insurance_provider"],
        "insurance_id": patient["insurance_id"],
    }
