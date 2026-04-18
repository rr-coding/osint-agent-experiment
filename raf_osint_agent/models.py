from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime, timezone


RAFUnitType = Literal[
    "squadron", "station", "wing", "group",
    "flight", "training_unit", "headquarters", "other"
]


class RAFAsset(BaseModel):
    name: str
    type: RAFUnitType
    service: str = "royal_air_force"
    asset_class: Optional[str] = Field(None, alias="class")
    location_description: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    confidence_score: Optional[float] = None
    confidence_rationale: Optional[str] = None
    source_urls: List[str] = Field(default_factory=list)
    date_observed: Optional[str] = None
    last_updated: Optional[str] = None

    model_config = {"populate_by_name": True}

    def has_location(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    def to_output_dict(self) -> dict:
        return {
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
        }


class AgentState(BaseModel):
    assets: List[RAFAsset] = Field(default_factory=list)
    fetched_urls: List[str] = Field(default_factory=list)
    searched_queries: List[str] = Field(default_factory=list)
    iteration: int = 0
    complete: bool = False
    completion_summary: Optional[str] = None

    def assets_with_locations(self) -> List[RAFAsset]:
        return [a for a in self.assets if a.has_location()]

    def assets_without_locations(self) -> List[RAFAsset]:
        return [a for a in self.assets if not a.has_location()]

    def get_asset_by_name(self, name: str) -> Optional[RAFAsset]:
        for asset in self.assets:
            if asset.name.lower() == name.lower():
                return asset
        return None

    def upsert_asset(self, new_asset: RAFAsset) -> bool:
        """Add or update an asset. Returns True if it was a new addition."""
        existing = self.get_asset_by_name(new_asset.name)
        if existing:
            if new_asset.location_description and not existing.location_description:
                existing.location_description = new_asset.location_description
            new_conf = new_asset.confidence_score or 0.0
            existing_conf = existing.confidence_score or 0.0
            if new_asset.latitude is not None and (
                existing.latitude is None or new_conf > existing_conf
            ):
                existing.latitude = new_asset.latitude
                existing.longitude = new_asset.longitude
                existing.confidence_score = new_asset.confidence_score
                existing.confidence_rationale = new_asset.confidence_rationale
            if new_asset.asset_class and not existing.asset_class:
                existing.asset_class = new_asset.asset_class
            for url in new_asset.source_urls:
                if url not in existing.source_urls:
                    existing.source_urls.append(url)
            if new_asset.date_observed:
                existing.date_observed = new_asset.date_observed
            existing.last_updated = new_asset.last_updated or datetime.now(timezone.utc).isoformat() + "Z"
            return False
        else:
            if not new_asset.last_updated:
                new_asset.last_updated = datetime.now(timezone.utc).isoformat() + "Z"
            self.assets.append(new_asset)
            return True

    def summary(self) -> str:
        total = len(self.assets)
        with_loc = len(self.assets_with_locations())
        without_loc = len(self.assets_without_locations())
        return (
            f"Assets found: {total} total | {with_loc} with locations | "
            f"{without_loc} missing locations | "
            f"URLs fetched: {len(self.fetched_urls)} | "
            f"Searches run: {len(self.searched_queries)}"
        )
