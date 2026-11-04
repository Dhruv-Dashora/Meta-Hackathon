"""Impact Agent: deterministic evidence-grounded reasoning (no model calls).

Reads Muse Spark findings, SAM segmentation outcomes, and optional
operator geo context. Produces strictly separated outputs:

- ``observed_hazards``: restatements of finding observations with a
  controlled hazard category (observed feature, mechanism, visible
  damage, exposed infrastructure, human exposure, unknown /
  unclassified). Never new claims.
- ``exposure_concerns``: conditional inferences only, selected by
  negation-aware, word-boundary predicates over visible features
  (road, river, building, vehicle, utility, people, general). Every
  concern carries its unconfirmed premise (``condition``), evidence
  + finding ids, an ``unverified`` status, and a linked verification
  action. SAM geometry may localize a concern but never establishes
  exposure, damage, blockage, or severity — and a zero/failed/skipped
  SAM result is never read as object absence. No concern asserts
  confirmed damage, casualties, blockage, or severity.
- ``verification_actions``: actionable human-review tasks with what /
  why / unknown / suggested safe method / priority rationale.
  Evidence-selected categories; overlapping same-objective evidence
  is grouped with all ids retained, and distinct objectives are never
  merged.
- ``damage_assessments``: provisional reads for assessable
  infrastructure only (see condition_assessment).
- ``rescue_priorities`` / ``access_priorities`` / ``review_priorities``:
  three separate urgencies (human danger, access/infrastructure,
  image review), each with basis, rationale, unknowns, and a review
  flag.

All text matching shares the condition-assessment grounding pipeline:
word-boundary, clause-aware, negation-aware. No brittle substring
rules. Uncertainty is preserved, never silently dropped.

The agent never filters or rewrites finding observations: risk-related
words in observations are legitimate evidence, not conclusions.
"""

from __future__ import annotations

from app.agents.base import AgentResult, BaseAgent
from app.agents.condition_assessment import (
    CONCERN_FAMILY_KEYWORDS,
    DANGER_CUES,
    MODERATE_DAMAGE_CUES,
    PEOPLE_WORDS,
    RISK_WORDS,
    STRONG_DAMAGE_CUES,
    access_priorities,
    clause_has_unnegated,
    damage_assessments,
    finding_has_unnegated,
    finding_mentions_person,
    finding_text as _shared_finding_text,
    rescue_priorities,
    review_priorities,
    text_clauses,
    text_raw_clauses,
)
from app.agents.report_content import (
    action_title,
    concern_objective,
    finding_review_texts,
    finding_signals,
    location_excerpt as _location_excerpt,
    people_in_danger as _people_with_danger,
)
from app.orchestrator.validators import METHOD_SUGGESTIONS
from app.schemas.common import Finding
from app.schemas.incident import (
    ExposureConcern,
    GeoContext,
    GeoStatus,
    HazardCategory,
    ObservedHazard,
    VerificationAction,
)
from app.schemas.unified_analysis import PromptSegmentation, PromptStatus

MAX_CONCERNS = 6
MAX_ACTIONS = 16

# Comprehensive risk cues for concern selection (shared pipeline:
# strong + moderate damage cues plus narrowed risk context — mere
# water-feature mentions alone never count as risk). Word-boundary,
# negation-aware matching only — never substring.
_RISK_CUES: tuple[str, ...] = (
    STRONG_DAMAGE_CUES
    + MODERATE_DAMAGE_CUES
    + tuple(sorted(w for w in RISK_WORDS if w not in {"river", "stream", "water"}))
)

# Mechanism cues for hazard classification: natural/process terms
# distinct from damage to a feature.
_MECHANISM_CUES: tuple[str, ...] = (
    "flood",
    "floods",
    "flooding",
    "floodwater",
    "landslide",
    "landslides",
    "mudslide",
    "mudslides",
    "erosion",
    "eroded",
    "scour",
    "scoured",
    "avalanche",
    "lahar",
)

_FAMILY_ORDER = ("road", "river", "building", "vehicle", "utility")

_CONCERN_PRIORITY: dict[str, str] = {
    "people": "high",
    "road": "high",
    "river": "high",
    "building": "high",
    "vehicle": "medium",
    "utility": "high",
    "general": "medium",
}

_WHY_OPERATIONAL: dict[str, str] = {
    "people": "People safety takes precedence over all other checks.",
    "road": "Road access determines whether ground teams and supplies can move.",
    "river": "River conditions affect crossing safety and nearby areas.",
    "building": "Structure condition affects shelter and safety decisions.",
    "vehicle": "Activity context helps interpret whether the area is in use.",
    "utility": "Utility condition affects safety and service decisions.",
    "general": "Unmeasured observations need review before any operational use.",
}

_UNKNOWN_BY_FEATURE: dict[str, str] = {
    "people": "Number, condition, and exact location of any people.",
    "road": "Whether the road is passable; the road's identity.",
    "river": "Water extent, depth, and trend.",
    "building": "Damage extent and whether structures are occupied.",
    "vehicle": "Why vehicles are present; no occupancy is claimed.",
    "utility": "Whether utilities are affected; service impact unconfirmed.",
    "general": "Operational relevance of the observation.",
}

_METHOD_BY_FEATURE: dict[str, str] = {
    "people": "Contact local responders and verify in person with local guidance.",
    "road": "Inspect on site from a safe location with local guidance.",
    "river": "Observe from a distance; do not approach the water.",
    "building": "Inspect on site from a safe location with local guidance.",
    "vehicle": "Compare with a second image angle of the same scene.",
    "utility": "Inspect on site from a safe location with local guidance.",
    "general": "Compare with a second image angle of the same scene.",
}

_PRIORITY_REASON: dict[str, str] = {
    "people": "People-related observations always rank first.",
    "road": "Access questions are time-sensitive and passage is unconfirmed.",
    "river": "Water conditions can change quickly; extent is unconfirmed.",
    "building": "Structure safety affects shelter decisions.",
    "vehicle": "Contextual; verify after access and safety questions.",
    "utility": "Utility safety affects nearby activity decisions.",
    "general": "Relevance unconfirmed; review after specific concerns.",
}

assert set(_METHOD_BY_FEATURE.values()) <= METHOD_SUGGESTIONS


def _finding_text(finding: Finding) -> str:
    return _shared_finding_text(finding)


def _evidence_ids(finding: Finding) -> list[str]:
    return [ref.evidence_id for ref in finding.evidence_refs]


def _family_of(finding: Finding) -> str | None:
    """First matching family (finding-level, unnegated, word-boundary).

    Finding-level (not clause-local): the vision format splits the
    affected feature across description lines, so family and risk cues
    may sit in different clauses while remaining semantically linked.
    Damage reads stay clause-local (direct evidence); concerns are
    conditional questions and use finding-level evidence.
    """
    for family in _FAMILY_ORDER:
        keywords = CONCERN_FAMILY_KEYWORDS[family]
        if finding_has_unnegated(finding, keywords):
            return family
    return None


def _has_risk(finding: Finding) -> bool:
    """Unnegated risk cue anywhere in the finding (word-boundary)."""
    return finding_has_unnegated(finding, _RISK_CUES)


def _has_people(finding: Finding) -> bool:
    """Unnegated person mention (negation-aware, word-boundary)."""
    return finding_mentions_person(finding)


def _classify_hazard(finding: Finding) -> HazardCategory:
    """Controlled hazard category for one finding.

    Precedence: human exposure > visible damage > exposed
    infrastructure > mechanism > observed feature > unknown /
    unclassified. All cue checks are word-boundary and
    negation-aware; damage/exposure links require same-clause
    evidence. Vacuous findings are unknown; substantive findings
    fitting no category are unclassified.
    """
    from app.agents.condition_assessment import (
        PEOPLE_HAZARD_WORDS,
        UNCERTAINTY_WORDS,  # noqa: F401 (qualifier-aware: preserved)
    )

    text = _finding_text(finding)
    word_clauses = text_clauses(text)
    if not any(word_clauses):
        return HazardCategory.UNKNOWN

    infra_words: list[str] = []
    for keywords in CONCERN_FAMILY_KEYWORDS.values():
        infra_words.extend(keywords)

    human_exposure = False
    visible_damage = False
    exposed_infra = False
    mechanism = False
    observed_feature = False

    for words in word_clauses:
        if not words:
            continue
        person = any(clause_has_unnegated(words, w) for w in PEOPLE_WORDS)
        danger = any(clause_has_unnegated(words, c) for c in DANGER_CUES)
        hazard = any(
            clause_has_unnegated(words, w) for w in PEOPLE_HAZARD_WORDS
        )
        if person and (danger or hazard):
            human_exposure = True
        infra = any(clause_has_unnegated(words, w) for w in infra_words)
        damage = any(
            clause_has_unnegated(words, c)
            for c in STRONG_DAMAGE_CUES + MODERATE_DAMAGE_CUES
        )
        risk = any(clause_has_unnegated(words, w) for w in RISK_WORDS)
        if infra and damage:
            visible_damage = True
        elif infra and risk:
            exposed_infra = True
        if any(clause_has_unnegated(words, c) for c in _MECHANISM_CUES):
            mechanism = True
        if infra or person:
            observed_feature = True

    if human_exposure:
        return HazardCategory.HUMAN_EXPOSURE
    if visible_damage:
        return HazardCategory.VISIBLE_DAMAGE
    if exposed_infra:
        return HazardCategory.EXPOSED_INFRASTRUCTURE
    if mechanism:
        return HazardCategory.MECHANISM
    if observed_feature:
        return HazardCategory.OBSERVED_FEATURE
    # Substantive but fitting no category vs vacuous.
    from app.agents.condition_assessment import has_substance

    if has_substance(text):
        return HazardCategory.UNCLASSIFIED
    return HazardCategory.UNKNOWN


class ImpactAgent(BaseAgent):
    name = "impact"

    def run(self, payload: dict) -> AgentResult:
        findings: list[Finding] = list(payload.get("findings") or [])
        segmentations: list[PromptSegmentation] = list(
            payload.get("segmentations") or []
        )
        geo_context: GeoContext | None = payload.get("geo_context")
        geo_available = (
            geo_context is not None and geo_context.status == GeoStatus.PROVIDED
        )

        hazards = _observed_hazards(findings)
        concerns, concern_notes = _exposure_concerns(findings, segmentations)
        damage, damage_notes = damage_assessments(findings)
        rescue, rescue_notes = rescue_priorities(findings)
        access, access_notes = access_priorities(findings)
        review, review_notes = review_priorities(findings)
        actions = _verification_actions(
            findings, segmentations, concerns, geo_available
        )
        errors = (
            list(concern_notes)
            + list(damage_notes)
            + list(rescue_notes)
            + list(access_notes)
            + list(review_notes)
        )
        if len(actions) > MAX_ACTIONS:
            errors.append(
                f"impact_action_cap: {len(actions) - MAX_ACTIONS} lower-"
                "priority actions omitted."
            )
            actions = actions[:MAX_ACTIONS]
        return AgentResult(
            agent=self.name,
            findings=[],
            errors=errors,
            data={
                "observed_hazards": hazards,
                "exposure_concerns": concerns,
                "verification_actions": actions,
                "damage_assessments": damage,
                "rescue_priorities": rescue,
                "access_priorities": access,
                "review_priorities": review,
            },
        )


def _observed_hazards(findings: list[Finding]) -> list[ObservedHazard]:
    hazards: list[ObservedHazard] = []
    for index, finding in enumerate(findings):
        first_line = (finding.description or "").split("\n")[0].strip()
        hazards.append(
            ObservedHazard(
                hazard_id=f"haz-{index + 1}",
                finding_ids=[finding.finding_id],
                evidence_ids=_evidence_ids(finding),
                summary=(
                    f"{finding.label}: {first_line}"
                    if first_line
                    else finding.label
                ),
                category=_classify_hazard(finding),
            )
        )
    return hazards


def _exposure_concerns(
    findings: list[Finding],
    segmentations: list[PromptSegmentation],
) -> tuple[list[ExposureConcern], list[str]]:
    concerns: list[ExposureConcern] = []
    by_id = {f.finding_id: f for f in findings}
    seg_status = {seg.prompt: seg.status for seg in segmentations}

    def basis(linked_ids: list[str]) -> tuple[list[str], list[str]]:
        retained = [fid for fid in linked_ids if fid in by_id]
        evidence: list[str] = []
        for fid in retained:
            for eid in _evidence_ids(by_id[fid]):
                if eid not in evidence:
                    evidence.append(eid)
        return retained, evidence

    counter = 0
    omitted = 0

    def add_concern(
        feature: str, condition: str, concern: str, finding_ids: list[str]
    ) -> None:
        nonlocal counter, omitted
        if len(concerns) >= MAX_CONCERNS:
            omitted += 1
            return
        counter += 1
        fids, eids = basis(finding_ids)
        concerns.append(
            ExposureConcern(
                concern_id=f"exp-{counter}",
                condition=condition,
                concern=concern,
                basis_finding_ids=fids,
                basis_evidence_ids=eids,
                verification_action_id=f"verify-exp-{counter}",
                feature=feature,
            )
        )

    sam_anchored: set[str] = set()
    unanchored_notes: list[str] = []
    for seg in segmentations:
        if seg.status != PromptStatus.OK or not seg.detections:
            continue
        retained_links = [fid for fid in seg.linked_finding_ids if fid in by_id]
        if not retained_links:
            # Segmentation-only observation: regions were measured with
            # no triggering finding, so no concern is raised here — the
            # verification actions below request human review instead.
            # (Expected for operator-requested prompts; otherwise noted.)
            if seg.provenance.value != "user_requested":
                unanchored_noun = (
                    "region" if len(seg.detections) == 1 else "regions"
                )
                unanchored_notes.append(
                    f"impact_unanchored_segmentation:{seg.prompt}: measured "
                    f"{len(seg.detections)} {unanchored_noun} with no "
                    "retained triggering finding; review only."
                )
            continue
        if seg.prompt == "people":
            family = "people"
        elif seg.prompt in _FAMILY_ORDER:
            family = seg.prompt
        else:
            family = "general"
        n = len(seg.detections)
        labels = sorted(
            {by_id[fid].label for fid in retained_links}
        )
        excerpts = [
            _location_excerpt(by_id[fid])
            for fid in retained_links
            if _location_excerpt(by_id[fid])
        ]
        where = f" near '{excerpts[0]}'" if excerpts else ""
        observed = f" (observed: {', '.join(labels)})" if labels else ""
        linked_signals: set[str] = set()
        for fid in retained_links:
            linked_signals |= set(finding_signals(by_id[fid]))
        condition, concern = _sam_templates(
            family, seg.prompt, n, where, observed, frozenset(linked_signals)
        )
        add_concern(family, condition, concern, retained_links)
        sam_anchored.update(retained_links)

    for finding in findings:
        families: list[str] = []
        if finding.finding_id not in sam_anchored:
            # Already covered by a SAM-anchored concern above; skip the
            # duplicate so each finding yields one feature concern.
            primary = _family_of(finding)
            risky = _has_risk(finding)
            if primary is not None and risky:
                families.append(primary)
            elif primary is None and risky:
                families.append("general")
        if _has_people(finding):
            # People safety is always raised as its own concern: SAM
            # geometry only localizes regions and never settles
            # people-safety questions.
            families.append("people")
        for family in families:
            excerpt = _location_excerpt(finding)
            where = f" ({excerpt})" if excerpt else ""
            condition, concern = _finding_templates(
                family,
                finding.label,
                where,
                seg_status,
                finding_signals(finding),
            )
            add_concern(
                family, condition, concern, [finding.finding_id]
            )
    notes: list[str] = list(unanchored_notes)
    if omitted:
        notes.append(
            f"impact_concern_cap: {omitted} lower-priority concerns omitted."
        )
    return concerns, notes


def _sam_templates(
    family: str,
    prompt: str,
    n: int,
    where: str,
    observed: str,
    signals: frozenset[str],
) -> tuple[str, str]:
    """Feature- and hazard-specific segmentation-supported concerns.

    The condition keeps the measured-region premise with its verbatim
    excerpt; the consequence names the evidence-gated hazard question
    (standing water, debris blockage, instability) instead of repeating
    one generic impact sentence.
    """
    noun = "region" if n == 1 else "regions"
    verb = "is" if n == 1 else "are"
    if family == "road":
        condition = (
            f"If the {n} segmented '{prompt}' {noun}{where} {verb} part "
            "of routes in active use near the incident"
        )
        if "flood" in signals:
            return (
                condition,
                "then standing water may cover the route"
                f"{observed}; whether the road is passable, and water "
                "depth, are not confirmed from this image",
            )
        if "landslide" in signals:
            return (
                condition,
                "then slope debris may block the route"
                f"{observed}; whether the road is passable is not "
                "confirmed from this image",
            )
        if "collapse" in signals or "debris" in signals:
            return (
                condition,
                "then debris or damage may block passage"
                f"{observed}; whether the road is passable is not "
                "confirmed from this image",
            )
        return (
            condition,
            "then road access in the visible area may be affected"
            f"{observed}; whether the road is passable is not confirmed "
            "from this image",
        )
    if family == "river":
        return (
            f"If the {n} segmented '{prompt}' {noun}{where} {verb} water "
            "affecting nearby land or crossings",
            "then water extent, depth, and trend may affect nearby "
            f"crossings{observed}; extent is not confirmed from this image",
        )
    if family == "building":
        condition = (
            f"If the {n} segmented '{prompt}' {noun}{where} {verb} "
            "structures in use"
        )
        if "collapse" in signals:
            return (
                condition,
                "then the structure may be unstable"
                f"{observed}; structural damage and occupancy are not "
                "confirmed from this image",
            )
        return (
            condition,
            "then building condition may need review"
            f"{observed}; damage is not confirmed from this image",
        )
    if family == "vehicle":
        return (
            f"If the {n} segmented '{prompt}' {noun}{where} indicate "
            "activity in the area",
            "then the area may be in active use"
            f"{observed}; context and occupancy are not confirmed from "
            "this image",
        )
    if family == "utility":
        return (
            f"If the {n} segmented '{prompt}' {noun}{where} {verb} "
            "utilities in service",
            "then utility condition may need review"
            f"{observed}; damage and service impact are not confirmed "
            "from this image",
        )
    if family == "people":
        return (
            f"If the {n} segmented '{prompt}' {noun}{where} show "
            "people in the affected visible area",
            "then their safety may need urgent review"
            f"{observed}; presence and condition are not confirmed "
            "from this image",
        )
    return (
        f"If the {n} segmented '{prompt}' {noun}{where} {verb} relevant "
        "to the incident",
        "then the visible area may need review"
        f"{observed}; relevance is not confirmed from this image",
    )


def _finding_templates(
    family: str,
    label: str,
    where: str,
    seg_status: dict[str, PromptStatus],
    signals: frozenset[str],
) -> tuple[str, str]:
    """Feature- and hazard-specific templates (never absence claims)."""
    measurement = _measurement_note(family, seg_status)
    if family == "road":
        condition = (
            f"If the observed '{label}'{where} affects road access in use"
        )
        if "flood" in signals:
            return (
                condition,
                "then standing water may cover the road; "
                f"{measurement} water depth and whether the road is "
                "passable are not confirmed",
            )
        if "landslide" in signals:
            return (
                condition,
                "then slope debris may block the road; "
                f"{measurement} whether the road is passable is not confirmed",
            )
        if "collapse" in signals or "debris" in signals:
            return (
                condition,
                "then debris or damage may block passage; "
                f"{measurement} whether the road is passable is not confirmed",
            )
        return (
            condition,
            "then passage may be affected; "
            f"{measurement} whether the road is passable is not confirmed",
        )
    if family == "river":
        return (
            f"If the observed '{label}'{where} indicates water affecting "
            "nearby land or crossings",
            "then water extent, depth, and trend may affect nearby "
            f"crossings; {measurement} extent is not confirmed",
        )
    if family == "building":
        condition = (
            f"If the observed '{label}'{where} indicates structure damage"
        )
        if "collapse" in signals:
            return (
                condition,
                "then the structure may be unstable; "
                f"{measurement} structural damage and occupancy are "
                "not confirmed",
            )
        return (
            condition,
            "then building condition may need review; "
            f"{measurement} damage is not confirmed",
        )
    if family == "vehicle":
        return (
            f"If the observed '{label}'{where} indicates activity in the area",
            "then the area may be in active use; "
            f"{measurement} context is not confirmed",
        )
    if family == "utility":
        return (
            f"If the observed '{label}'{where} indicates utility damage "
            "or disruption",
            "then utility condition may need review; "
            f"{measurement} damage and service impact are not confirmed",
        )
    if family == "people":
        return (
            f"If people mentioned in '{label}'{where} are in the affected "
            "visible area",
            "then their safety may need urgent review; presence and "
            "condition are not confirmed from this image",
        )
    return (
        f"If the observed '{label}'{where} affects routes or structures "
        "in use",
        "then local access or safety in the visible area may be "
        "affected; severity is not confirmed from this image",
    )


def _measurement_note(family: str, seg_status: dict[str, PromptStatus]) -> str:
    """Honest SAM-coverage note: non-measurement is never absence."""
    status = seg_status.get(family)
    if status is None:
        return (
            f"'{family}' areas were not measured by segmentation; this "
            "does not mean they are absent;"
        )
    if status == PromptStatus.ZERO_MATCHES:
        return (
            f"'{family}' segmentation matched nothing; this does not mean "
            f"'{family}' areas are absent;"
        )
    if status == PromptStatus.FAILED:
        return (
            f"'{family}' segmentation failed, so nothing was measured; "
            "this does not mean absence;"
        )
    return (
        f"'{family}' segmentation did not run for this image; this does "
        "not mean absence;"
    )


def _concern_priority(
    concern: ExposureConcern, by_id: dict[str, Finding]
) -> str:
    """Evidence-gated priority for one concern's review action.

    People concerns rank high only with people + explicit danger in
    one clause (certain); person-alone concerns rank medium (routine
    people-safety review, distinct from rescue urgency). Other
    features use the static operational map: access/shelter/utility
    questions are time-sensitive (high), activity context and
    unclassified observations are routine (medium).
    """
    if concern.feature == "people":
        for fid in concern.basis_finding_ids:
            finding = by_id.get(fid)
            if finding is not None and _people_with_danger(finding):
                return "high"
        return "medium"
    return _CONCERN_PRIORITY.get(concern.feature, "medium")


def _verification_actions(
    findings: list[Finding],
    segmentations: list[PromptSegmentation],
    concerns: list[ExposureConcern],
    geo_available: bool,
) -> list[VerificationAction]:
    actions: list[VerificationAction] = []

    def add(
        action_id: str,
        action: str,
        reason: str,
        priority: str,
        related: list[str] | None = None,
        what: str = "",
        why_operational: str = "",
        unknown: str = "",
        method: str = "",
        priority_reason: str = "",
        kind: str = "finding_review",
        concern_id: str | None = None,
        prompt: str | None = None,
        title: str = "",
    ) -> None:
        actions.append(
            VerificationAction(
                action_id=action_id,
                action=action,
                reason=reason,
                title=title,
                priority=priority,  # type: ignore[arg-type]
                related_finding_ids=list(related or []),
                what=what,
                why_operational=why_operational,
                unknown=unknown,
                method=method,
                priority_reason=priority_reason,
                kind=kind,  # type: ignore[arg-type]
                concern_id=concern_id,
                prompt=prompt,
            )
        )

    by_id = {f.finding_id: f for f in findings}
    # Distinct objectives are never merged: each concern keeps its own
    # review (grouped only when several findings share one concern,
    # retaining every id), each finding keeps its own confirmation
    # review, and people-safety, segmentation, geo, and routine tasks
    # stay separate. Overlap grouping retains all evidence; it never
    # folds one objective into another.
    for concern in concerns:
        feature = concern.feature
        priority = _concern_priority(concern, by_id)
        premise = concern.condition.removeprefix("If ").removeprefix("if ")
        basis_excerpts = [
            _location_excerpt(by_id[fid])
            for fid in concern.basis_finding_ids
            if fid in by_id and _location_excerpt(by_id[fid])
        ]
        where_part = (
            f" at '{basis_excerpts[0]}'" if basis_excerpts else ""
        )
        if len(concern.basis_finding_ids) > 1:
            joined = ", ".join(concern.basis_finding_ids)
            reason = (
                f"Grouped review for findings {joined} sharing one "
                f"'{feature}' question. All grouped evidence is retained. "
                f"Unverified question: {concern.concern}."
            )
        else:
            reason = (
                f"Unverified {feature} question: {concern.concern}."
            )
        add(
            concern.verification_action_id,
            f"Field-verify concern '{concern.concern_id}' "
            f"({feature}{where_part}) before acting on it.",
            reason,
            priority,
            related=list(concern.basis_finding_ids),
            what=(
                f"Determine whether {premise}, and "
                f"{concern_objective(feature)}."
            ),
            why_operational=_WHY_OPERATIONAL.get(feature, ""),
            unknown=_UNKNOWN_BY_FEATURE.get(feature, ""),
            method=_METHOD_BY_FEATURE.get(feature, ""),
            priority_reason=_PRIORITY_REASON.get(feature, ""),
            kind="concern_review",
            concern_id=concern.concern_id,
            title=action_title("concern_review", feature),
        )
    for finding in findings:
        if _has_people(finding):
            add(
                f"verify-people-{finding.finding_id}",
                "Verify any people-related observation in person before "
                "any prioritization display.",
                f"Finding '{finding.finding_id}' mentions people; people "
                "findings require human verification.",
                "high",
                related=[finding.finding_id],
                what=(
                    f"Confirm whether people are present near "
                    f"'{finding.label}' ({finding.finding_id})."
                ),
                why_operational=_WHY_OPERATIONAL["people"],
                unknown=_UNKNOWN_BY_FEATURE["people"],
                method=_METHOD_BY_FEATURE["people"],
                priority_reason=_PRIORITY_REASON["people"],
                kind="people_safety",
                title=action_title("people_safety"),
            )
        risky = _has_risk(finding)
        review_action, review_what = finding_review_texts(finding)
        add(
            f"verify-finding-{finding.finding_id}",
            review_action,
            "AI observation is unverified until human review.",
            "high" if risky else "medium",
            related=[finding.finding_id],
            what=review_what,
            why_operational=(
                "Unverified AI observations must be confirmed before "
                "operational use."
            ),
            unknown="Whether the observation is accurate and relevant.",
            method="Compare with a second image angle of the same scene.",
            priority_reason=(
                "Risk-flagged observation needs timely confirmation."
                if risky
                else "Routine confirmation; no risk indicators observed."
            ),
            title=action_title("finding_review", finding.label),
        )
    for seg in segmentations:
        seg_related = [fid for fid in seg.linked_finding_ids if fid in by_id]
        if seg.status == PromptStatus.FAILED:
            add(
                f"verify-seg-{seg.prompt}",
                f"Re-examine '{seg.prompt}' visually: automated "
                "segmentation failed.",
                seg.error or "SAM request failed.",
                "medium",
                related=seg_related,
                what=f"Manually assess '{seg.prompt}' areas in the image.",
                why_operational=(
                    "Failed segmentation leaves this feature unmeasured."
                ),
                unknown=f"Whether '{seg.prompt}' areas are affected.",
                method="Re-run analysis after obtaining clearer imagery.",
                priority_reason="Unmeasured feature; review after confirmed evidence.",
                kind="segmentation_review",
                prompt=seg.prompt,
                title=action_title("segmentation_review", seg.prompt),
            )
        elif seg.status == PromptStatus.ZERO_MATCHES:
            add(
                f"verify-seg-{seg.prompt}",
                f"Prompt '{seg.prompt}' matched nothing: confirm visually; "
                "this does not mean the object is absent.",
                "Zero SAM matches may mean absence, a poor prompt, or an "
                "occluded view — never assume absence.",
                "low",
                related=seg_related,
                what=f"Confirm whether '{seg.prompt}' is visible in the image.",
                why_operational="Rules out prompt or visibility issues.",
                unknown=f"Whether '{seg.prompt}' is present but unmatched.",
                method="Compare with a second image angle of the same scene.",
                priority_reason="Informational; no positive evidence to chase.",
                kind="segmentation_review",
                prompt=seg.prompt,
                title=action_title("segmentation_review", seg.prompt),
            )
        elif seg.status == PromptStatus.SKIPPED:
            add(
                f"verify-seg-{seg.prompt}",
                f"Prompt '{seg.prompt}' was not segmented: assess manually.",
                seg.error or "Prompt skipped.",
                "medium",
                related=seg_related,
                what=f"Manually assess '{seg.prompt}' areas in the image.",
                why_operational="Skipped segmentation leaves this feature unmeasured.",
                unknown=f"Whether '{seg.prompt}' areas are affected.",
                method="Re-run analysis after obtaining clearer imagery.",
                priority_reason="Unmeasured feature; review after confirmed evidence.",
                kind="segmentation_review",
                prompt=seg.prompt,
                title=action_title("segmentation_review", seg.prompt),
            )
        elif (
            seg.status == PromptStatus.OK
            and seg.detections
            and not seg_related
        ):
            # Segmentation-only observation: regions were measured with
            # no triggering finding, so this justifies a review request
            # with honest provenance — never a concern or a verdict.
            origin = (
                "operator-requested"
                if seg.provenance.value == "user_requested"
                else "automatic"
            )
            seg_noun = (
                "region" if len(seg.detections) == 1 else "regions"
            )
            add(
                f"verify-seg-{seg.prompt}",
                f"Review {len(seg.detections)} segmented '{seg.prompt}' "
                f"{seg_noun} with no triggering finding: confirm visually.",
                f"Segmentation-only observation from an {origin} prompt; "
                "geometry alone proves nothing about damage, presence, "
                "or identity.",
                "medium",
                related=[],
                what=(
                    f"Visually interpret the {len(seg.detections)} "
                    f"'{seg.prompt}' {seg_noun} and confirm whether the "
                    f"{origin} prompt fits this image."
                ),
                why_operational=(
                    "Measured but uninterpreted regions need human review "
                    "before any operational use."
                ),
                unknown=(
                    f"Whether the '{seg.prompt}' regions correspond to "
                    "anything operationally relevant."
                ),
                method="Compare with a second image angle of the same scene.",
                priority_reason=(
                    "Measured regions need interpretation; review after "
                    "finding-based evidence."
                ),
                kind="segmentation_review",
                prompt=seg.prompt,
                title=action_title("segmentation_review", seg.prompt),
            )
    if not geo_available:
        add(
            "verify-geo-context",
            "Obtain operator location context (label or coordinates) to "
            "ground follow-up.",
            "No geospatial context was provided with this image.",
            "medium",
            what="Ask the image source for a location label or coordinates.",
            why_operational="Location context focuses verification on the right area.",
            unknown="Where this image was taken.",
            method="Ask the image source for location or time details.",
            priority_reason="Helpful context; not blocking for image review.",
            kind="geo_context",
            title=action_title("geo_context"),
        )
    if not findings and not segmentations:
        add(
            "verify-routine",
            "No findings or segmentations: routine review only, no urgent "
            "action indicated.",
            "Vision analysis returned no usable evidence.",
            "low",
            what="Confirm the image shows no actionable evidence.",
            why_operational="Closes the review loop on empty analyses.",
            unknown="Nothing specific; general scene check.",
            method="",
            priority_reason="No evidence to prioritize.",
            kind="routine",
            title=action_title("routine"),
        )
    return actions
