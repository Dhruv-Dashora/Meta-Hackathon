"""Vision Agent: single-image disaster evidence analysis via Muse Spark."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.agents.base import AgentResult, BaseAgent
from app.core.errors import SentinelError
from app.schemas.common import Confidence, EvidenceRef, Finding, ReviewStatus
from app.services.muse_spark_client import MuseSparkClient

VISION_INSTRUCTION = """\
You are analyzing a single disaster-scene image for Himalayan Sentinel \
triage. Systematically examine three categories and report each \
distinct observation as its own finding:
1. Environmental hazards: floodwater, landslide debris, slope failure, \
erosion, fire or smoke, and other relevant visible hazards.
2. Infrastructure: roads, bridges, buildings, vehicles, utilities, \
and visible damage or blockage.
3. Visible human presence: people clearly visible in the image.



Rules:

- Describe only what is directly visible as observations, and keep \
inferred impacts in a separate field.
- In the observed text, name the condition directly observable \
(inundated, partly buried, obstructed, displaced, exposed \
components, or apparently damaged) and the specific visible \
feature; avoid generic labels such as "damage" alone, and do \
not state a cause the image does not show.
- Report one finding per distinct feature instance. Keep \
genuinely different locations or conditions as separate \
findings; never repeat the same observation, and do not split \
one feature into overlapping findings.
- An asset near water, debris, or a slope failure is not \
thereby damaged: state only the relationship the image actually \
supports, and record the rest as uncertain.
- When people are clearly visible, record a distinct finding (for \
example label "people observed") with the image-relative location \
and observable circumstances (approximate count as seen, posture or \
activity as seen, nearby visible hazards). Do not bury human \
presence inside a hazard or infrastructure description.
- Use explicit people words ("people" or "person") whenever humans \
are observed, including ambiguous cases.
- If figures are distant, obscured, or ambiguous, record one hedged \
finding, describe the uncertainty in the uncertainty notes, and \
lower the confidence. If no people are visible, record no people \
finding.
- Never claim to identify buried or trapped people.
- Never infer injuries, entrapment, rescue needs, or immediate \
danger merely from human presence.
- Never predict future disasters from this single image.
- If unsure about something, say so in the uncertainty notes.

Respond with JSON only, no other text, in this shape:
{"findings": [{"label": str, "observed": str, "affected_feature": str, \
"location_in_image": str, "inferred_impact": str, "confidence": number \
0-1, "uncertainty_notes": str}]}
Confidence is an uncalibrated triage signal, not a probability.
If no damage, hazard, or visible people are present, return \
{"findings": []}."""

SINGLE_IMAGE_LIMITATIONS = (
    "Single-image analysis only: occluded areas cannot be assessed, capture "
    "time and location are unverified, and nearby context is missing. "
    "Buried or trapped people cannot be identified from this image, and no "
    "future-disaster prediction is made. Human review required."
)

_DEFAULT_CONFIDENCE = 0.5


class VisionAgent(BaseAgent):
    name = "vision"

    def __init__(self, client: MuseSparkClient | None = None) -> None:
        self._client = client

    def run(self, payload: dict) -> AgentResult:
        image_data_url = payload.get("image_data_url")
        if not image_data_url or not isinstance(image_data_url, str):
            return AgentResult(agent=self.name, errors=["Missing 'image_data_url'."])
        evidence_id = str(
            payload.get("evidence_id") or _evidence_id_for(image_data_url)
        )
        client = self._client or MuseSparkClient()
        try:
            output_text = client.analyze_image(image_data_url, VISION_INSTRUCTION)
        except SentinelError as exc:
            return AgentResult(agent=self.name, errors=[f"{exc.code}: {exc.message}"])
        except Exception as exc:  # fail safely; never leak internals
            return AgentResult(
                agent=self.name, errors=[f"vision_failed: {type(exc).__name__}"]
            )
        try:
            items = _parse_findings_json(output_text)
        except ValueError as exc:
            return AgentResult(
                agent=self.name, errors=[f"invalid_model_output: {exc}"]
            )
        findings: list[Finding] = []
        skipped = 0
        for index, item in enumerate(items):
            finding = _to_finding(item, index, evidence_id)
            if finding is None:
                skipped += 1
                continue
            findings.append(finding)
        errors: list[str] = []
        if skipped and not findings:
            errors.append("Model returned no usable findings.")
        return AgentResult(agent=self.name, findings=findings, errors=errors)


def _evidence_id_for(image_data_url: str) -> str:
    digest = hashlib.sha256(image_data_url.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _parse_findings_json(output_text: str) -> list[Any]:
    """Parse the model's JSON into a list of raw finding dicts."""
    text = output_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]  # drop opening fence
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]  # drop closing fence
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"output is not valid JSON: {exc}") from exc
    items: Any = parsed.get("findings") if isinstance(parsed, dict) else None
    if items is None and isinstance(parsed, list):
        items = parsed
    if not isinstance(items, list):
        raise ValueError("expected {'findings': [...]} or a JSON list")
    return items


def _to_finding(item: Any, index: int, evidence_id: str) -> Finding | None:
    """Map one raw model finding to the Finding schema; None if unusable."""
    if not isinstance(item, dict):
        return None
    label = item.get("label")
    observed = item.get("observed")
    if not isinstance(label, str) or not label.strip():
        return None
    if not isinstance(observed, str) or not observed.strip():
        return None
    confidence = _coerce_confidence(item.get("confidence"))
    affected = _clean(item.get("affected_feature"))
    location = _clean(item.get("location_in_image"))
    inferred = _clean(item.get("inferred_impact"))
    description = f"Observed: {observed.strip()}"
    if affected:
        description += f"\nAffected feature: {affected}"
    if location:
        description += f"\nLocation in image: {location}"
    if inferred:
        description += f"\nInferred impact: {inferred}"
    notes = _clean(item.get("uncertainty_notes"))
    uncertainty = f"{notes}\n{SINGLE_IMAGE_LIMITATIONS}" if notes else (
        SINGLE_IMAGE_LIMITATIONS
    )
    return Finding(
        finding_id=f"vision-{index + 1}-{evidence_id[-12:]}",
        label=label.strip(),
        description=description,
        confidence=Confidence(value=confidence),
        uncertainty_notes=uncertainty,
        evidence_refs=[
            EvidenceRef(
                evidence_id=evidence_id,
                modality="image",
                uri_or_hash=evidence_id,
                captured_at=None,
            )
        ],
        observed_at=None,
        analyzed_at=datetime.now(timezone.utc),
        review_status=ReviewStatus.PENDING,
    )


def _clean(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _coerce_confidence(value: Any) -> float:
    """Clamp model confidence to 0-1; default when missing or invalid."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _DEFAULT_CONFIDENCE
    if number != number:  # NaN
        return _DEFAULT_CONFIDENCE
    return min(1.0, max(0.0, number))
