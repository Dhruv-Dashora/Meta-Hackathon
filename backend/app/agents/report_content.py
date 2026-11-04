"""Report content rules: deterministic hazard-aware prose (no model calls).

Shared by the impact and reporting agents so concern text, review
objectives, headlines, scene descriptions, gaps, and unknowns use one
vocabulary. Every rule is evidence-gated:

- Signals come from the condition-assessment grounding pipeline
  (word-boundary, clause-local, negation-aware): negated cues never
  count, and hedged cues keep conditional wording.
- Quiet or negated-only scenes abstain: headlines and gaps state that
  no hazard assessment is supported instead of forcing a read.
- No new factual claims: prose restates finding labels and verbatim
  excerpts (qualifiers preserved) plus segmentation counts.
"""

from __future__ import annotations

from app.agents.condition_assessment import (
    DANGER_CUES,
    MODERATE_DAMAGE_CUES,
    PEOPLE_WORDS,
    STRONG_DAMAGE_CUES,
    UNCERTAINTY_WORDS,
    clause_has_unnegated,
    finding_has_unnegated,
    finding_mentions_person,
    has_substance,
    text_clauses,
)
from app.schemas.common import Finding

# Standing-water cues: depth/extent/trend questions (never mere
# river/stream/water mentions, which alone are not hazard evidence).
FLOOD_CUES: tuple[str, ...] = (
    "flood",
    "floods",
    "flooding",
    "floodwater",
    "flooded",
    "submerged",
    "inundated",
    "inundation",
)

# Slope-process cues: stability/debris/access questions.
LANDSLIDE_CUES: tuple[str, ...] = (
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

# Fire cues: active burning (smoke alone is ambiguous and excluded).
FIRE_CUES: tuple[str, ...] = ("fire", "burning", "flames")

# Fixed signal priority for deterministic headline/gap ordering.
_SIGNAL_ORDER = (
    "danger",
    "flood",
    "collapse",
    "landslide",
    "fire",
    "people",
    "debris",
)

_HAZARD_WORD = {
    "flood": "flooding",
    "collapse": "structural damage",
    "landslide": "slope debris",
    "fire": "fire",
    "debris": "damage or debris",
}

_UNKNOWN_SHORT = {
    "flood": "water extent unconfirmed",
    "collapse": "stability unconfirmed",
    "landslide": "extent unconfirmed",
    "fire": "extent unconfirmed",
    "debris": "extent unconfirmed",
}

_HAZARD_UNKNOWN = {
    "flood": "water depth, extent, and trend are unconfirmed",
    "collapse": (
        "structural stability, damage extent, and occupancy are unconfirmed"
    ),
    "landslide": "slope stability and debris extent are unconfirmed",
    "fire": "fire extent, spread, and structural effect are unconfirmed",
    "people": (
        "number, condition, and exact location of any people are unconfirmed"
    ),
}

# Actionable check per review feature (appended to the concern premise
# so the task states an objective instead of echoing the condition).
CONCERN_OBJECTIVES = {
    "road": "check whether the road is passable and identify the route",
    "river": "check water extent, depth, and trend",
    "building": "check structural stability and whether structures are occupied",
    "vehicle": "check area activity and context",
    "utility": "check utility damage and service impact",
    "people": "check the number, condition, and location of any people",
    "general": "check operational relevance",
}


def location_excerpt(finding: Finding) -> str:
    """Verbatim affected-feature/location excerpt (qualifiers preserved).

    Quotes the ``Affected feature:`` / ``Location in image:``
    description lines emitted by the vision agent. Verbatim quoting
    keeps uncertainty and negation qualifiers intact. The full text is
    always returned: safety-critical location detail is never cut
    mid-word or silently dropped, and long values wrap in the
    dashboard and print brief instead.
    """
    parts: list[str] = []
    for line in finding.description.split("\n"):
        stripped = line.strip()
        for prefix in ("Affected feature:", "Location in image:"):
            if stripped.startswith(prefix):
                value = stripped[len(prefix):].strip()
                if value:
                    parts.append(value)
    if not parts:
        first_line = (finding.description or "").split("\n")[0].strip()
        if first_line.removeprefix("Observed:").strip():
            parts.append(first_line.removeprefix("Observed:").strip())
        elif first_line:
            parts.append(first_line)
    return " — ".join(parts)


def people_in_danger(finding: Finding) -> bool:
    """People + explicit danger in one clause, unnegated, certain."""
    from app.agents.condition_assessment import finding_text

    text = finding_text(finding)
    for words in text_clauses(text):
        people = any(clause_has_unnegated(words, w) for w in PEOPLE_WORDS)
        danger = any(clause_has_unnegated(words, cue) for cue in DANGER_CUES)
        uncertain = any(w in UNCERTAINTY_WORDS for w in words)
        if people and danger and not uncertain:
            return True
    return False


def finding_signals(finding: Finding) -> frozenset[str]:
    """Evidence-gated hazard signals for one finding.

    Finding-level, word-boundary, negation-aware (the concern-level
    pipeline): cues may sit in different clauses from the feature and
    still count as conditional-question evidence. Returns a subset of
    ``danger`` / ``flood`` / ``collapse`` / ``landslide`` /
    ``people`` / ``debris``.
    """
    signals: set[str] = set()
    if people_in_danger(finding):
        signals.add("danger")
    if finding_has_unnegated(finding, FLOOD_CUES):
        signals.add("flood")
    if finding_has_unnegated(finding, STRONG_DAMAGE_CUES):
        signals.add("collapse")
    if finding_has_unnegated(finding, LANDSLIDE_CUES):
        signals.add("landslide")
    if finding_has_unnegated(finding, FIRE_CUES):
        signals.add("fire")
    if finding_mentions_person(finding):
        signals.add("people")
    # Generic risk indicator: any moderate cue other than the fire
    # family (a fire-only finding must not headline as "debris").
    if "fire" not in signals and finding_has_unnegated(
        finding,
        tuple(c for c in MODERATE_DAMAGE_CUES if c not in FIRE_CUES),
    ):
        signals.add("debris")
    return frozenset(signals)


def scene_headline(findings: list[Finding]) -> str:
    """Concise hazard-aware headline (conditional, abstains when unsafe).

    Names the top evidence-gated signals with their finding labels and
    states what is unconfirmed. Quiet, negated-only, or empty scenes
    state that no hazard assessment is supported.
    """
    if not findings:
        return "No findings: no supported assessment from this image."
    by_signal: dict[str, list[str]] = {s: [] for s in _SIGNAL_ORDER}
    quiet: list[str] = []
    unclear = 0
    for finding in findings:
        signals = finding_signals(finding)
        hazards = [s for s in _SIGNAL_ORDER if s in signals]
        if not hazards:
            if has_substance(f"{finding.label}\n{finding.description}"):
                quiet.append(finding.label)
            else:
                unclear += 1
            continue
        for signal in hazards:
            if signal == "people" and "danger" in signals:
                continue
            if finding.label not in by_signal[signal]:
                by_signal[signal].append(finding.label)
    clauses: list[str] = []
    if by_signal["danger"]:
        labels = ", ".join(by_signal["danger"])
        clauses.append(
            f"People possibly in danger ({labels}); condition unconfirmed"
        )
    if by_signal["people"]:
        labels = ", ".join(
            label
            for label in by_signal["people"]
            if label.casefold() != "people observed"
        )
        if labels:
            clauses.append(
                f"People observed ({labels}); safety review needed"
            )
        else:
            clauses.append("People observed; safety review needed")
    for signal in ("flood", "collapse", "landslide", "fire", "debris"):
        if by_signal[signal]:
            labels = ", ".join(by_signal[signal])
            clauses.append(
                f"Possible {_HAZARD_WORD[signal]} ({labels}); "
                f"{_UNKNOWN_SHORT[signal]}"
            )
    if not clauses:
        if quiet:
            shown = ", ".join(quiet)
            return f"Observed {shown}; no hazard indicators confirmed."
        return "No confirmed hazard: observations are negated or unclear."
    headline = ". ".join(clauses[:2])
    if len(clauses) > 2 or quiet or unclear:
        headline += ". Further observations need review"
    return headline + "."


def scene_observed(findings: list[Finding], segmentations: list) -> str:
    """Natural observed-scene description (restatement, no new claims).

    One sentence per finding with its verbatim excerpt, plus honest
    segmentation notes with proper plurals. Never counts findings.
    """
    sentences: list[str] = []
    for finding in findings:
        excerpt = location_excerpt(finding)
        if excerpt:
            sentences.append(f"Observed {finding.label}: {excerpt}.")
        else:
            sentences.append(f"Observed {finding.label}.")
    seg_bits = [segmentation_note(seg) for seg in segmentations]
    if seg_bits:
        sentences.append("Segmentation: " + "; ".join(seg_bits) + ".")
    if not sentences:
        return "Vision analysis returned no findings."
    if not findings:
        sentences.insert(0, "Vision analysis returned no findings.")
    return " ".join(sentences)


def segmentation_note(seg) -> str:
    """Honest one-clause note for one SAM outcome (never an absence claim)."""
    from app.schemas.unified_analysis import PromptStatus

    count = len(seg.detections)
    noun = "region" if count == 1 else "regions"
    if seg.status == PromptStatus.OK:
        return f"{count} '{seg.prompt}' {noun} measured"
    if seg.status == PromptStatus.ZERO_MATCHES:
        return f"'{seg.prompt}' segmentation matched nothing (not absence)"
    if seg.status == PromptStatus.FAILED:
        return f"'{seg.prompt}' segmentation failed"
    return f"'{seg.prompt}' was not segmented"


def scene_unknowns(
    findings: list[Finding], geo_provided: bool, segmentations: list
) -> str:
    """Explicit unknowns: base evidence limits plus hazard-specific gaps."""
    bits = ["Capture time is unknown"]
    if geo_provided:
        bits.append("incident location is operator-provided and unverified")
    else:
        bits.append("exact incident location is unknown")
    union: set[str] = set()
    for finding in findings:
        union |= set(finding_signals(finding))
    for signal in ("flood", "collapse", "landslide", "fire", "people"):
        if signal in union or (signal == "people" and "danger" in union):
            bits.append(_HAZARD_UNKNOWN[signal])
    road_relevant = any(seg.prompt == "road" for seg in segmentations) or any(
        "road" in f.label.lower() for f in findings
    )
    if road_relevant:
        bits.append("whether visible roads are passable is unconfirmed")
    bits.append("no field ground truth exists")
    return "; ".join(bits) + "."


def hazard_gaps(findings: list[Finding]) -> list[tuple[str, str, str, str]]:
    """Hazard-specific information gaps, deterministic topic order.

    Each entry is ``(topic, detail, why_matters, status)``. Scenes with
    no hazard signal get one explicit abstention gap instead of a
    forced assessment.
    """
    union: set[str] = set()
    for finding in findings:
        union |= set(finding_signals(finding))
    gaps: list[tuple[str, str, str, str]] = []
    if "flood" in union:
        gaps.append(
            (
                "water_conditions",
                "Water depth, extent, and trend are not measured.",
                "Determines crossing safety and nearby exposure.",
                "unknown",
            )
        )
    if "collapse" in union:
        gaps.append(
            (
                "structural_condition",
                "Structural stability and occupancy are unconfirmed.",
                "Decides shelter use and approach safety.",
                "unknown",
            )
        )
    if "landslide" in union:
        gaps.append(
            (
                "slope_conditions",
                "Slope stability and debris extent are unconfirmed.",
                "Additional movement could affect routes below.",
                "unknown",
            )
        )
    if "fire" in union:
        gaps.append(
            (
                "fire_conditions",
                "Fire extent, spread, and structural effect are "
                "unconfirmed.",
                "Active fire can threaten nearby structures and routes.",
                "unknown",
            )
        )
    if "people" in union or "danger" in union:
        gaps.append(
            (
                "human_exposure",
                "Number, condition, and exact location of any people "
                "are unconfirmed.",
                "People safety takes precedence over other checks.",
                "unknown",
            )
        )
    if not gaps:
        gaps.append(
            (
                "hazard_assessment",
                "No hazard is supported by these observations; no damage "
                "or access assessment is made.",
                "Prevents acting on absent evidence.",
                "unknown",
            )
        )
    return gaps


def finding_objective(finding: Finding) -> str:
    """Actionable review objective for one finding (evidence-gated)."""
    signals = finding_signals(finding)
    if "danger" in signals or "people" in signals:
        return "confirm whether people are present, and their number and condition"
    if "flood" in signals:
        return (
            "check standing-water extent and depth, and whether any road "
            "is passable"
        )
    if "collapse" in signals:
        return (
            "check structural condition, damage extent, and whether "
            "structures are occupied"
        )
    if "landslide" in signals:
        return "check debris extent and slope stability from a safe distance"
    if "debris" in signals:
        return "check damage extent and whether routes or structures are affected"
    if has_substance(f"{finding.label}\n{finding.description}"):
        return "confirm what is visible"
    return "confirm whether the observation shows anything usable"


def finding_review_texts(finding: Finding) -> tuple[str, str]:
    """Specific ``(action, what)`` for one finding's confirmation review.

    Names the label, id, verbatim excerpt, and evidence-gated objective
    instead of a generic confirm-everything task.
    """
    objective = finding_objective(finding)
    excerpt = location_excerpt(finding)
    action = (
        f"Human review of '{finding.label}' ({finding.finding_id}): "
        f"{objective}."
    )
    if excerpt:
        what = (
            f"At '{excerpt}' ({finding.finding_id}), {objective}; confirm "
            "the observation is accurate."
        )
    else:
        what = (
            f"For finding '{finding.label}' ({finding.finding_id}), "
            f"{objective}; confirm the observation is accurate."
        )
    return action, what


def concern_objective(feature: str) -> str:
    """Actionable check appended to one concern's review task."""
    return CONCERN_OBJECTIVES.get(feature, CONCERN_OBJECTIVES["general"])


_ACTION_TITLE_NOUN = {
    "concern_review": "Review",
    "finding_review": "Assessment",
    "people_safety": "People Safety Check",
    "segmentation_review": "Segmentation Review",
    "geo_context": "Location Context Request",
    "routine": "Routine Review",
}


def action_title(kind: str, subject: str = "") -> str:
    """Concise structured title for one verification action.

    Derived from the existing task type (``kind``) plus its subject —
    the finding label, concern feature, or SAM prompt — so headings
    stay short while the full instructions remain in ``what``/``action``.
    Unknown subjects fall back to generic wording, never to a slice of
    the task text.
    """
    noun = _ACTION_TITLE_NOUN.get(kind, "Review Task")
    cleaned = " ".join(subject.split())
    if kind == "finding_review":
        return f"{cleaned.title() if cleaned else 'Observation'} Assessment"
    if kind == "concern_review":
        return f"{cleaned.title() if cleaned else 'General'} Review"
    if kind == "segmentation_review":
        if cleaned:
            return f"{cleaned.title()} Segmentation Review"
        return "Segmentation Review"
    return noun
