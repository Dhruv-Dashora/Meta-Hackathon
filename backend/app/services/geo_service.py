"""Geo helpers: safe operator-GeoJSON validation (no geometry analysis).

Operator-supplied GeoJSON is validated for size, structure, geometry
types, and coordinate ranges only. This module performs NO spatial
computation: no distances, areas, proximity, or accessibility claims.
Validated content is always labeled operator-provided and unverified.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.core.errors import SentinelError

ALLOWED_GEOMETRY_TYPES = frozenset(
    {
        "Point",
        "MultiPoint",
        "LineString",
        "MultiLineString",
        "Polygon",
        "MultiPolygon",
        "GeometryCollection",
    }
)

MAX_GEOJSON_DEPTH = 6
MAX_GEOJSON_FEATURES = 2000


class GeoValidationError(SentinelError):
    """Malformed, oversized, or out-of-range operator GeoJSON."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(code, message)
        self.status_code = status_code


@dataclass(frozen=True)
class GeoValidationInfo:
    feature_count: int
    geometry_types: list[str]


def validate_geojson_bytes(data: bytes, *, max_bytes: int) -> GeoValidationInfo:
    """Validate operator GeoJSON; raise GeoValidationError on problems."""
    if not data or not data.strip():
        raise GeoValidationError("empty_geojson", "GeoJSON file is empty.")
    if len(data) > max_bytes:
        raise GeoValidationError(
            "geojson_too_large",
            f"GeoJSON exceeds the {max_bytes}-byte limit.",
            status_code=413,
        )
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise GeoValidationError(
            "invalid_geojson", "GeoJSON is not valid JSON."
        ) from exc
    return _validate_document(parsed)


def _validate_document(doc: object) -> GeoValidationInfo:
    if not isinstance(doc, dict):
        raise GeoValidationError(
            "invalid_geojson", "GeoJSON top level must be an object."
        )
    kind = doc.get("type")
    if kind == "FeatureCollection":
        features = doc.get("features")
        if not isinstance(features, list):
            raise GeoValidationError(
                "invalid_geojson", "FeatureCollection needs a features list."
            )
        if len(features) > MAX_GEOJSON_FEATURES:
            raise GeoValidationError(
                "geojson_too_large",
                f"GeoJSON exceeds {MAX_GEOJSON_FEATURES} features.",
                status_code=413,
            )
        types: set[str] = set()
        for index, feature in enumerate(features):
            types.update(_validate_feature(feature, index))
        return GeoValidationInfo(
            feature_count=len(features), geometry_types=sorted(types)
        )
    if kind == "Feature":
        types = _validate_feature(doc, 0)
        return GeoValidationInfo(
            feature_count=1, geometry_types=sorted(types)
        )
    if isinstance(kind, str) and kind in ALLOWED_GEOMETRY_TYPES:
        _validate_geometry(doc, 0)
        return GeoValidationInfo(feature_count=0, geometry_types=[kind])
    raise GeoValidationError(
        "invalid_geojson",
        "GeoJSON type must be FeatureCollection, Feature, or a geometry.",
    )


def _validate_feature(feature: object, index: int) -> set[str]:
    if not isinstance(feature, dict) or feature.get("type") != "Feature":
        raise GeoValidationError(
            "invalid_geojson", f"Feature at index {index} is malformed."
        )
    geometry = feature.get("geometry")
    if geometry is None:
        return set()
    if not isinstance(geometry, dict):
        raise GeoValidationError(
            "invalid_geojson", f"Feature {index} has a malformed geometry."
        )
    _validate_geometry(geometry, 0)
    kind = geometry.get("type")
    return {kind} if isinstance(kind, str) else set()


def _validate_geometry(geometry: dict, depth: int) -> None:
    if depth > MAX_GEOJSON_DEPTH:
        raise GeoValidationError(
            "invalid_geojson", "GeoJSON nesting exceeds the depth limit."
        )
    kind = geometry.get("type")
    if kind not in ALLOWED_GEOMETRY_TYPES:
        raise GeoValidationError(
            "invalid_geojson", f"Geometry type {kind!r} is not allowed."
        )
    if kind == "GeometryCollection":
        geometries = geometry.get("geometries")
        if not isinstance(geometries, list):
            raise GeoValidationError(
                "invalid_geojson", "GeometryCollection needs a geometries list."
            )
        for sub in geometries:
            if not isinstance(sub, dict):
                raise GeoValidationError(
                    "invalid_geojson", "GeometryCollection holds a bad geometry."
                )
            _validate_geometry(sub, depth + 1)
        return
    _validate_coordinates(geometry.get("coordinates"), depth)


def _validate_coordinates(coords: object, depth: int) -> None:
    if depth > MAX_GEOJSON_DEPTH:
        raise GeoValidationError(
            "invalid_geojson", "GeoJSON nesting exceeds the depth limit."
        )
    if not isinstance(coords, list) or not coords:
        raise GeoValidationError(
            "invalid_geojson", "Geometry coordinates are malformed."
        )
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in coords):
        lon, lat = float(coords[0]), float(coords[1]) if len(coords) > 1 else None
        if lat is None:
            raise GeoValidationError(
                "invalid_geojson", "Position needs at least lon/lat."
            )
        if not -180.0 <= lon <= 180.0 or not -90.0 <= lat <= 90.0:
            raise GeoValidationError(
                "invalid_geojson", "Position lon/lat out of range."
            )
        return
    for sub in coords:
        _validate_coordinates(sub, depth + 1)
