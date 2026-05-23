"""Intent classification result shapes."""
from enum import Enum
from pydantic import BaseModel


class Intent(str, Enum):
    SCHEDULE = "schedule"
    RESOLVE = "resolve"
    ESCALATE = "escalate"


class ClassificationResult(BaseModel):
    intent: Intent
    confidence: float          # 0.0 – 1.0
    reasoning: str             # Claude's chain-of-thought (kept short)
    extracted_entities: dict   # e.g. {"date": "tomorrow", "service": "AC repair"}
