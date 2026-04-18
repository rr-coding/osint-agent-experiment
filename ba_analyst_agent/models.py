from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime, timezone


ReadinessLevel = Literal["high", "medium", "low"]


class OperationType(BaseModel):
    id: str
    name: str
    description: str


class EnrichedAsset(BaseModel):
    # ── Original OSINT fields ─────────────────────────────────────────────────
    name: str
    service: str = "british_army"
    type: str
    asset_class: Optional[str] = Field(None, alias="class")
    location_description: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    confidence_score: Optional[float] = None
    confidence_rationale: Optional[str] = None
    source_urls: List[str] = Field(default_factory=list)
    date_observed: Optional[str] = None
    last_updated: Optional[str] = None

    # ── Analyst enrichment fields ─────────────────────────────────────────────
    unit_category: Optional[str] = None
    operational_readiness: Optional[ReadinessLevel] = None
    readiness_rationale: Optional[str] = None
    current_assignment: Optional[str] = None
    assignment_source: Optional[str] = None
    capability_scores: Dict[str, int] = Field(default_factory=dict)
    capability_rationale: Optional[str] = None

    # ── Army-specific optional fields ─────────────────────────────────────────
    parent_brigade: Optional[str] = None
    regimental_identity: Optional[str] = None
    vehicle_fleet: Optional[str] = None

    model_config = {"populate_by_name": True}

    def is_enriched(self) -> bool:
        return self.operational_readiness is not None and bool(self.capability_scores)

    def top_capability(self) -> Optional[str]:
        if not self.capability_scores:
            return None
        return max(self.capability_scores, key=lambda k: self.capability_scores[k])

    def to_output_dict(self) -> dict:
        d = {
            "name": self.name,
            "service": self.service,
            "type": self.type,
            "class": self.asset_class,
            "location_description": self.location_description,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "confidence_score": self.confidence_score,
            "confidence_rationale": self.confidence_rationale,
            "source_urls": self.source_urls,
            "date_observed": self.date_observed,
            "last_updated": self.last_updated,
            "unit_category": self.unit_category,
            "operational_readiness": self.operational_readiness,
            "readiness_rationale": self.readiness_rationale,
            "current_assignment": self.current_assignment,
            "assignment_source": self.assignment_source,
            "capability_scores": self.capability_scores,
            "capability_rationale": self.capability_rationale,
        }
        # Include optional service-specific fields when present
        if self.parent_brigade:
            d["parent_brigade"] = self.parent_brigade
        if self.regimental_identity:
            d["regimental_identity"] = self.regimental_identity
        if self.vehicle_fleet:
            d["vehicle_fleet"] = self.vehicle_fleet
        return d


class AnalystOutput(BaseModel):
    metadata: Dict[str, Any] = Field(default_factory=dict)
    assets: List[EnrichedAsset] = Field(default_factory=list)

    def to_output_dict(self) -> dict:
        return {
            "metadata": self.metadata,
            "assets": [a.to_output_dict() for a in self.assets],
        }
