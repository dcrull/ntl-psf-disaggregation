from __future__ import annotations

from dataclasses import dataclass
from math import cos, radians


@dataclass(frozen=True)
class BoundingBox:
    """WGS84 bounding box in west, south, east, north order."""

    west: float
    south: float
    east: float
    north: float

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.west, self.south, self.east, self.north)


def bbox_from_center_radius(lat: float, lon: float, radius_km: float) -> BoundingBox:
    """Approximate a city extent from a center point and radius.

    The preview workflow only needs a lightweight search/crop envelope. Later
    ingestion can replace this with a stricter analysis grid.
    """

    if radius_km <= 0:
        raise ValueError("radius_km must be positive")
    lat_delta = radius_km / 110.574
    lon_scale = max(cos(radians(lat)), 0.01)
    lon_delta = radius_km / (111.320 * lon_scale)
    return BoundingBox(
        west=max(-180.0, lon - lon_delta),
        south=max(-90.0, lat - lat_delta),
        east=min(180.0, lon + lon_delta),
        north=min(90.0, lat + lat_delta),
    )
