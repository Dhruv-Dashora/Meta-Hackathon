"""Incident dossier schemas for multi-agent disaster response.

Status semantics (two distinct levels):
- ``vision_workflow_status`` is the unified visual-evidence outcome
  (``completed`` / ``partial`` / ``vision_only``): did SAM segmentation
  run cleanly alongside the Muse Spark findings?
- ``incident_status`` is the overall assessment outcome:
  - ``completed``: vision, impact, and reporting all succeeded and every
    critical dossier section is available.
  - ``partial``: vision succeeded but impact failed, so exposure concerns
    are unavailable and the dossier carries only observed evidence plus
    fallback review actions. A dossier is NEVER marked completed when a
    required agent fails. (Reporting failure yields no dossier at all —
    an explicit error instead.)
- ``degraded_sections`` names dossier sections with partial content loss
  (rejected conclusions, pruned actions, validation gaps, capped lists),
  plus ``impact`` when the impact step failed outright. A ``completed``
  dossier with a non-empty list ran every agent but still needs the
  flagged sections read with extra care.

Claim discipline:
- ``ObservedHazard`` restates finding observations with evidence ids. It
  adds no new claims.
- ``ExposureConcern`` is always conditional (``condition`` states the
  unconfirmed premise), always ``unverified``, always cites evidence and
  finding ids, and always links a ``verification_action_id``. Concerns
  missing any of these are rejected by validators, never rendered.
- ``GeoContext`` echoes operator-supplied values labeled as unverified.
  Image contents are NEVER inferred to correspond to supplied coordinates.
"""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import Finding
from app.schemas.segmentation import SegmentImageInfo
from app.schemas.unified_analysis import (
    PromptProvenance,
    PromptSegmentation,
    PromptStatus,
    WorkflowStatus,
)


class IncidentStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"


class GeoStatus(str, Enum):
    PROVIDED = "provided"
    UNAVAILABLE = "unavailable"


class AgentStepStatus(str, Enum):
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"


class GeoContext(BaseModel):
    """Operator-supplied location context — always unverified, never inferred."""

    status: GeoStatus
    location_label: str = ""
    latitude: float | None = None
    longitude: float | None = None
    geojson_feature_count: int | None = None
    provenance: Literal["operator-provided, unverified"] = (
        "operator-provided, unverified"
    )
    note: str = ""


class HazardCategory(str, Enum):
    """Controlled hazard-interpretation categories.

    Separates what was seen (observed_feature), how it may have
    formed (mechanism), what damage is visible (visible_damage),
    what infrastructure is exposed (exposed_infrastructure), and
    what human exposure is indicated (human_exposure). ``unknown``
    / ``unclassified`` are explicit allowed outcomes when evidence
    is negated, hedged beyond use, or fits no category — the
    classifier never forces a specific read.
    """

    OBSERVED_FEATURE = "observed_feature"
    MECHANISM = "mechanism"
    VISIBLE_DAMAGE = "visible_damage"
    EXPOSED_INFRASTRUCTURE = "exposed_infrastructure"
    HUMAN_EXPOSURE = "human_exposure"
    UNKNOWN = "unknown"
    UNCLASSIFIED = "unclassified"


class ObservedHazard(BaseModel):
    """Restatement of finding observations. Adds no new claims."""

    hazard_id: str
    finding_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    summary: str = ""
    category: HazardCategory = HazardCategory.UNKNOWN


class ExposureConcern(BaseModel):
    """One conditional, unverified inference with evidence and a review action."""

    concern_id: str
    condition: str
    concern: str
    basis_finding_ids: list[str] = Field(default_factory=list)
    basis_evidence_ids: list[str] = Field(default_factory=list)
    status: Literal["unverified"] = "unverified"
    verification_action_id: str
    feature: str = "general"


class DamageCategory(str, Enum):
    NO_VISIBLE_DAMAGE = "no_visible_damage"
    POSSIBLE_DAMAGE = "possible_damage"
    APPARENT_MAJOR_DAMAGE = "apparent_major_damage"
    CANNOT_ASSESS = "cannot_assess"


class DamageAssessment(BaseModel):
    """Provisional damage read for one infrastructure feature family.

    Never an engineering finding: every assessment carries its evidence
    basis, is explicitly provisional, and ``no_visible_damage`` never
    means confirmed safety (see ``uncertainty_note``).

    The main narrative (``observed_condition`` + ``rationale``) reads as
    an evidence-grounded field report: what asset, what was directly
    observed, and the provisional read. Finding ids and rule mechanics
    never appear in prose; they stay in ``basis_finding_ids`` /
    ``basis_evidence_ids`` and the JSON export. ``condition_class`` is
    the machine-readable observed-condition kind: ``visible_damage``,
    ``inundation``, ``obstruction``, ``surrounding_material``,
    ``intact``, or ``unassessed``. ``recommended_verification`` states
    the human check that must follow.
    """

    assessment_id: str
    feature: str = "general"
    target_label: str = ""
    basis_finding_ids: list[str] = Field(default_factory=list)
    basis_evidence_ids: list[str] = Field(default_factory=list)
    category: DamageCategory
    rationale: str = ""
    provisional: Literal[True] = True
    uncertainty_note: str = ""
    observed_condition: str = ""
    condition_class: str = ""
    recommended_verification: str = ""


class RescuePriority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNDETERMINED = "undetermined"


class RescueAttention(BaseModel):
    """Human-verification urgency for one finding (or the empty analysis).

    ``high`` requires explicit evidence-grounded indication of possible
    immediate human danger — never mere person/hazard co-occurrence, and
    never inferred proximity, entrapment, or victimhood. Person-alone
    observations are routine (low), never rescue urgency; findings with
    no person evidence are undetermined, never low. Every priority
    requires authorized human review.
    """

    attention_id: str
    priority: RescuePriority
    basis_finding_ids: list[str] = Field(default_factory=list)
    basis_evidence_ids: list[str] = Field(default_factory=list)
    rationale: str = ""
    unknowns: str = ""
    requires_human_review: Literal[True] = True


class AccessAttention(BaseModel):
    """Access/infrastructure verification urgency for one finding.

    Separate from rescue: rates whether routes, structures, vehicles,
    or utilities need timely field verification. Never asserts
    casualties, locations, or deployment. Every priority requires
    authorized human review.
    """

    attention_id: str
    priority: RescuePriority
    basis_finding_ids: list[str] = Field(default_factory=list)
    basis_evidence_ids: list[str] = Field(default_factory=list)
    rationale: str = ""
    unknowns: str = ""
    requires_human_review: Literal[True] = True


class ReviewAttention(BaseModel):
    """Image-review urgency for one finding (or the empty analysis).

    Separate from rescue and access: rates how promptly a human
    should review the image observation itself. Risk-flagged
    observations rank above quiet ones; vacuous findings are
    undetermined. Every priority requires human review.
    """

    review_id: str
    priority: RescuePriority
    basis_finding_ids: list[str] = Field(default_factory=list)
    basis_evidence_ids: list[str] = Field(default_factory=list)
    rationale: str = ""
    unknowns: str = ""
    requires_human_review: Literal[True] = True


class VerificationAction(BaseModel):
    """One human-review action, ordered by priority for the operator.

    Additive detail fields (all defaulted): ``what`` states the check,
    ``why_operational`` its operational motive, ``unknown`` what stays
    unresolved, ``method`` a safe verification suggestion requiring local
    judgment, ``priority_reason`` the deterministic ranking rationale, and
    ``related_finding_ids`` the structured evidence linkage.

    ``kind`` makes the task role explicit so validators can ground each
    action appropriately: ``concern_review`` actions verify one retained
    exposure concern (``concern_id`` back-link, finding basis required);
    ``finding_review`` / ``people_safety`` verify finding observations
    (finding basis required); ``segmentation_review`` asks a human to look
    at SAM geometry for one prompt (``prompt`` required; geometry alone
    never proves damage, danger, or identity); ``geo_context`` /
    ``routine`` are finding-independent follow-ups.

    ``title`` is a concise structured heading derived from ``kind`` plus
    its subject (finding label, concern feature, or SAM prompt). Display
    layers use it instead of slicing task text; the complete
    instructions always remain in ``what``/``action``.
    """

    action_id: str
    action: str
    reason: str
    title: str = ""
    priority: Literal["high", "medium", "low"] = "medium"
    related_finding_ids: list[str] = Field(default_factory=list)
    what: str = ""
    why_operational: str = ""
    unknown: str = ""
    method: str = ""
    priority_reason: str = ""
    kind: Literal[
        "concern_review",
        "finding_review",
        "people_safety",
        "segmentation_review",
        "geo_context",
        "routine",
    ] = "finding_review"
    concern_id: str | None = None
    prompt: str | None = None


class AgentTrailEntry(BaseModel):
    """Audit record for one orchestrated agent step."""

    agent: str
    status: AgentStepStatus
    duration_s: float = 0.0
    notes: str = ""


class SegmentationSummary(BaseModel):
    """Per-prompt SAM outcome counts. Geometry only — never a verdict."""

    prompt: str
    status: PromptStatus
    detection_count: int = 0
    linked_finding_ids: list[str] = Field(default_factory=list)
    provenance: PromptProvenance = PromptProvenance.AUTOMATIC


class EvidenceLedgerEntry(BaseModel):
    """One evidence item backing the dossier."""

    evidence_id: str
    modality: str
    source: str


class SituationSummary(BaseModel):
    """Concise grounded summary: observed facts vs explicit unknowns."""

    headline: str = ""
    observed: str = ""
    unknowns: str = ""


class FindingGroup(BaseModel):
    """Related findings grouped for review (display aid, not new evidence)."""

    group_id: str
    title: str
    finding_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class InformationGap(BaseModel):
    """One explicitly missing or unverified piece of information."""

    topic: str
    detail: str
    why_matters: str
    status: Literal["unknown", "unverified", "verified"] = "unknown"


class IncidentDossier(BaseModel):
    """Response for POST /api/disaster-response/assess-incident."""

    incident_id: str
    image: SegmentImageInfo
    analysis_ref: str | None = None
    vision_source: Literal["fresh_analysis", "cached_reuse"] = "fresh_analysis"
    vision_workflow_status: WorkflowStatus
    incident_status: IncidentStatus
    situation_summary: SituationSummary = Field(default_factory=SituationSummary)
    findings: list[Finding] = Field(default_factory=list)
    finding_groups: list[FindingGroup] = Field(default_factory=list)
    information_gaps: list[InformationGap] = Field(default_factory=list)
    segmentation_summary: list[SegmentationSummary] = Field(default_factory=list)
    segmentations: list[PromptSegmentation] = Field(default_factory=list)
    observed_hazards: list[ObservedHazard] = Field(default_factory=list)
    exposure_concerns: list[ExposureConcern] = Field(default_factory=list)
    damage_assessments: list[DamageAssessment] = Field(default_factory=list)
    rescue_priorities: list[RescueAttention] = Field(default_factory=list)
    access_priorities: list[AccessAttention] = Field(default_factory=list)
    review_priorities: list[ReviewAttention] = Field(default_factory=list)
    geo_context: GeoContext
    uncertainty_notes: list[str] = Field(default_factory=list)
    verification_actions: list[VerificationAction] = Field(default_factory=list)
    evidence_ledger: list[EvidenceLedgerEntry] = Field(default_factory=list)
    agent_trail: list[AgentTrailEntry] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    degraded_sections: list[str] = Field(default_factory=list)
