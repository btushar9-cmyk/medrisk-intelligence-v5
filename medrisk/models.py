"""Small data structures used by the local MedRisk Intelligence prototype."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class Evidence:
    doc_id: str
    source_file: str
    locator: str
    text: str
    record_types: List[str]
    event_date: Optional[str] = None


@dataclass(frozen=True)
class StructuredRecord:
    doc_id: str
    source_file: str
    locator: str
    record_type: str
    fields: Dict[str, Any]
    risk_score: Optional[float]
    risk_band: str


@dataclass(frozen=True)
class CaseRecord:
    db_id: int
    case_id: str
    title: str
    case_type: str
    status: str
    product_family: str
    part_number: str
    owner: str
    severity_concern: str
    description: str
    created_at: str
    updated_at: str
