"""Condition assessment: damage reads + three separate priorities.

Deterministic text grounding over finding text (label + description).
No model calls.

Grounding rules:
- Evidence is the label plus the observed description sections only:
  ``Inferred impact:`` lines are hypotheses and never ground a read
  (the prompt planner excludes them for the same reason).
- A damage cue counts only in a clause that also names the assessed
  feature family (evidence link). Cues about other features, or about
  nothing identifiable, never set a category.
- Negation suppresses cues ("no visible collapse"); uncertainty downgrades
  strong cues to ``possible_damage`` ("possibly collapsed").
- Damage reads cover assessable infrastructure only (buildings,
  roads/bridges, vehicles, utilities). Water, people, and generic
  nouns are never damage-assessed.
- Rescue ``high`` requires a people-word AND an explicit immediate-danger
  cue in one clause. Person-alone observations are routine (low), never
  rescue urgency; findings with no person evidence are undetermined,
  never low. Proximity, entrapment, victimhood, casualties, locations,
  or deployment are never inferred beyond what the text states.
- Access and image-review urgencies are separate from rescue, each with
  its own evidence gates, basis, rationale, unknowns, and review flag.
"""

from __future__ import annotations

import re
from typing import Sequence

from app.schemas.common import Finding
from app.schemas.incident import (
    AccessAttention,
    DamageAssessment,
    DamageCategory,
    RescueAttention,
    RescuePriority,
    ReviewAttention,
)

MAX_DAMAGE_ASSESSMENTS = 8
MAX_RESCUE_PRIORITIES = 12
MAX_ACCESS_PRIORITIES = 12
MAX_REVIEW_PRIORITIES = 12

# Clause-local analysis (same splitter style as the prompt planner).
_WORD_RE = re.compile(r"[a-z0-9]+")

_NEGATION_BEFORE = frozenset(
    {
        "no",
        "not",
        "without",
        "absent",
        "none",
        "never",
        "neither",
        "nor",
        "lacks",
        "lack",
        "missing",
    }
)
_NEGATION_AFTER = frozenset({"absent", "missing"})
_BEFORE_WINDOW = 3
_AFTER_WINDOW = 2

_UNCERTAINTY_WORDS = frozenset(
    {
        "possible",
        "possibly",
        "maybe",
        "uncertain",
        "uncertainty",
        "suspected",
        "suspect",
        "apparent",
        "apparently",
        "seeming",
        "seems",
        "appear",
        "appears",
        "looks",
        "likely",
        "probable",
        "probably",
        "potential",
        "potentially",
        "may",
        "might",
        "could",
    }
)

# Strong cues (certain phrasing -> apparent major damage).
_STRONG_DAMAGE_CUES = (
    "collapse",
    "collapsed",
    "collapsing",
    "rubble",
    "destroyed",
    "demolished",
    "washout",
    "washed away",
    "breach",
    "breached",
    "pancaked",
    "split apart",
)

# Moderate cues (certain phrasing -> possible damage).
_MODERATE_DAMAGE_CUES = (
    "damage",
    "damaged",
    "crack",
    "cracks",
    "cracked",
    "cracking",
    "debris",
    "broken",
    "flooded",
    "flooding",
    "submerged",
    "blocked",
    "blockage",
    "tilt",
    "tilted",
    "leaning",
    "buckled",
    "buckling",
    "scour",
    "scoured",
    "eroded",
    "erosion",
    "undermined",
    "sagging",
    "shattered",
    "charred",
    "burnt",
    "burned",
    "scorched",
    # Fire family appended last so existing cue precedence is preserved.
    "fire",
    "burning",
    "flames",
)

# Standalone intact language (same clause as the feature).
_INTACT_WORDS = frozenset({"intact", "undamaged", "passable"})

_PEOPLE_WORDS = frozenset(
    {
        "person",
        "persons",
        "people",
        "human",
        "humans",
        "pedestrian",
        "pedestrians",
        "child",
        "children",
        "resident",
        "residents",
    }
)

# Explicit immediate-danger cues (same clause as a people-word -> high).
_DANGER_CUES = (
    "trapped",
    "buried",
    "stranded",
    "injured",
    "injury",
    "injuries",
    "drown",
    "drowning",
    "drowned",
    "clinging",
    "calling for help",
    "waving for help",
    "needs rescue",
    "need rescue",
    "unable to move",
    "swept away",
    "caught in",
)

# Risk context for medium rescue priority (plausible exposure / access).
_RISK_WORDS = frozenset(
    {
        "damage",
        "damaged",
        "debris",
        "flood",
        "flooded",
        "flooding",
        "floodwater",
        "crack",
        "cracked",
        "collapse",
        "collapsed",
        "landslide",
        "blocked",
        "blockage",
        "destroyed",
        "breach",
        "breached",
        "washout",
        "mudslide",
        "rubble",
        "submerged",
        "fire",
        "burning",
        "flames",
        "hazard",
        "hazardous",
        "danger",
        "dangerous",
        "risk",
        "river",
        "stream",
        "water",
    }
)

# Narrowed hazard words for person+hazard medium: actual hazard
# indicators only, never mere water-feature mentions. Person-alone
# with only river/stream/water context stays routine (low).
_PEOPLE_HAZARD_WORDS = frozenset(
    w for w in _RISK_WORDS if w not in {"river", "stream", "water"}
)

# Assessable infrastructure families for damage (buildings,
# roads/bridges, vehicles, utilities). Water, people, and generic
# nouns are never damage-assessed. Plurals included: matching is
# word-boundary based, so substring fallbacks never apply.
_DAMAGE_FAMILY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "building": (
        "building",
        "buildings",
        "house",
        "houses",
        "structure",
        "structures",
        "hut",
        "huts",
        "shed",
        "sheds",
    ),
    "road": (
        "road",
        "roads",
        "roadway",
        "roadways",
        "highway",
        "highways",
        "street",
        "streets",
        "lane",
        "lanes",
        "bridge",
        "bridges",
        "overpass",
        "overpasses",
        "culvert",
        "culverts",
    ),
    "vehicle": (
        "vehicle",
        "vehicles",
        "car",
        "cars",
        "truck",
        "trucks",
        "bus",
        "buses",
        "jeep",
        "jeeps",
    ),
    "utility": (
        "utility",
        "utilities",
        "power",
        "pole",
        "poles",
        "transformer",
        "transformers",
        "line",
        "lines",
        "pipe",
        "pipes",
        "pipeline",
        "pipelines",
        "wire",
        "wires",
        "pylon",
        "pylons",
    ),
}

_DAMAGE_FAMILIES = ("building", "road", "vehicle", "utility")

# Display asset per family when the clause names no more specific term.
_FAMILY_ASSET = {
    "building": "building",
    "road": "road or bridge",
    "vehicle": "vehicle",
    "utility": "utility infrastructure",
}

# Observed-condition classes: surrounding water, cover, or blockage must
# never read as structural damage. Strong cues are all direct visible
# damage; moderate cues split by class below, defaulting to
# visible damage for anything not listed.
_INUNDATION_CUES = frozenset({"flooded", "flooding", "submerged"})
_OBSTRUCTION_CUES = frozenset({"blocked", "blockage"})
_COVER_CUES = frozenset({"debris"})

_CONDITION_CLASSES = (
    "visible_damage",
    "inundation",
    "obstruction",
    "surrounding_material",
    "intact",
    "unassessed",
)

# Structured narrative fragments per condition class. The merge keeps the
# full observed clause as a verbatim quote for evidence grounding; these
# fragments supply the professional read around it. No finding ids or
# rule mechanics appear in any fragment.
_OBSERVED_TEMPLATES = {
    "visible_damage": "Damage indicators visible at the {asset}",
    "inundation": "Standing water visible at the {asset}",
    "obstruction": "Possible obstruction of the {asset}",
    "surrounding_material": "Mud or debris visible around the {asset}",
    "intact": "No visible damage to the {asset} at available resolution",
    "unassessed": "{Asset} mentioned without assessable detail",
}

_UNCERTAINTY_TEMPLATES = {
    "visible_damage": (
        "Single-image observation at available resolution; extent "
        "and structural meaning are unconfirmed."
    ),
    "possible_visible_damage": (
        "Single-image observation at available resolution; whether "
        "this is damage, and its extent, are unconfirmed."
    ),
    "inundation": (
        "Single-image observation; water depth, extent, and any "
        "underlying damage are unconfirmed. Standing water alone "
        "does not establish structural damage."
    ),
    "obstruction": (
        "Single-image observation; whether passage is blocked, and "
        "whether the structure itself is damaged, are unconfirmed."
    ),
    "surrounding_material": (
        "Single-image observation; whether the asset itself is "
        "damaged is unconfirmed. Surrounding mud or debris does "
        "not establish structural damage."
    ),
    "intact": (
        "No visible damage is not confirmed structural safety; "
        "hidden or out-of-frame damage cannot be ruled out."
    ),
    "unassessed": (
        "Insufficient evidence; a clearer view or on-site check is needed."
    ),
}

_VERIFICATION_TEMPLATES = {
    "visible_damage": (
        "A qualified person should inspect the {asset} on site to "
        "confirm damage extent and structural safety."
    ),
    "inundation": (
        "Confirm whether the {asset} sustained damage; standing "
        "water alone does not establish structural damage."
    ),
    "obstruction": (
        "Confirm whether passage is obstructed and whether the "
        "{asset} itself is damaged."
    ),
    "surrounding_material": (
        "Confirm whether the {asset} itself is damaged; surrounding "
        "mud or debris does not establish structural damage."
    ),
    "intact": (
        "Hidden or out-of-frame damage cannot be ruled out without "
        "inspection."
    ),
    "unassessed": (
        "Obtain a clearer view or on-site check before any conclusion."
    ),
}

# Concern families for exposure reasoning (water affects access, so
# river stays here even though it is never damage-assessed).
_CONCERN_FAMILY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "road": _DAMAGE_FAMILY_KEYWORDS["road"],
    "river": (
        "river",
        "rivers",
        "floodwater",
        "flood",
        "floods",
        "stream",
        "streams",
        "water",
        "waters",
    ),
    "building": _DAMAGE_FAMILY_KEYWORDS["building"],
    "vehicle": _DAMAGE_FAMILY_KEYWORDS["vehicle"],
    "utility": _DAMAGE_FAMILY_KEYWORDS["utility"],
}

# Access HIGH cues: explicit access-cut indicators (certain phrasing,
# same clause as infrastructure). Blockage is access-critical.
_ACCESS_HIGH_CUES = (
    "blocked",
    "blockage",
    "collapse",
    "collapsed",
    "collapsing",
    "destroyed",
    "demolished",
    "washout",
    "washed away",
    "breach",
    "breached",
    "split apart",
    "pancaked",
    "rubble",
)

# Public grounding API shared with the impact agent (single pipeline,
# no divergent substring rules). All matching is word-boundary,
# clause-local, and negation-aware.
ASSESSABLE_FEATURES = _DAMAGE_FAMILIES
CONDITION_CLASSES = _CONDITION_CLASSES
DAMAGE_FAMILY_KEYWORDS = _DAMAGE_FAMILY_KEYWORDS
CONCERN_FAMILY_KEYWORDS = _CONCERN_FAMILY_KEYWORDS
STRONG_DAMAGE_CUES = _STRONG_DAMAGE_CUES
MODERATE_DAMAGE_CUES = _MODERATE_DAMAGE_CUES
PEOPLE_WORDS = _PEOPLE_WORDS
DANGER_CUES = _DANGER_CUES
RISK_WORDS = _RISK_WORDS
PEOPLE_HAZARD_WORDS = _PEOPLE_HAZARD_WORDS
ACCESS_HIGH_CUES = _ACCESS_HIGH_CUES
UNCERTAINTY_WORDS = _UNCERTAINTY_WORDS

_SEVERITY = {
    DamageCategory.CANNOT_ASSESS: 0,
    DamageCategory.NO_VISIBLE_DAMAGE: 1,
    DamageCategory.POSSIBLE_DAMAGE: 2,
    DamageCategory.APPARENT_MAJOR_DAMAGE: 3,
}

_PRIORITY_RANK = {
    RescuePriority.UNDETERMINED: 0,
    RescuePriority.LOW: 1,
    RescuePriority.MEDIUM: 2,
    RescuePriority.HIGH: 3,
}


def _clauses(text: str) -> list[list[str]]:
    return [
        _WORD_RE.findall(chunk.lower()) for chunk in re.split(r"[.,;:\n]+", text)
    ]


def _raw_clauses(text: str) -> list[str]:
    return [chunk.strip() for chunk in re.split(r"[.,;:\n]+", text) if chunk.strip()]


def _keyword_spans(words: list[str], keyword: str) -> list[int]:
    parts = keyword.split()
    return [
        i
        for i in range(len(words) - len(parts) + 1)
        if words[i : i + len(parts)] == parts
    ]


def _is_negated(words: list[str], start: int, length: int) -> bool:
    before = words[max(0, start - _BEFORE_WINDOW) : start]
    if any(w in _NEGATION_BEFORE for w in before):
        return True
    after = words[start + length : start + length + _AFTER_WINDOW]
    if any(w in _NEGATION_AFTER for w in after):
        return True
    if len(after) >= 2 and after[0] == "not" and after[1] in {"visible", "present"}:
        return True
    return False


def _finding_text(finding: Finding) -> str:
    # Inferred-impact lines are hypotheses, never observations: the
    # prompt planner already excludes them, and this grounding pipeline
    # (damage, concerns, priorities, hazard class) must too, so that
    # speculative text can never ground an evidence-linked read.
    lines = [
        line
        for line in (finding.description or "").splitlines()
        if not line.strip().lower().startswith("inferred impact")
    ]
    return f"{finding.label}\n" + "\n".join(lines)


def _evidence_ids(finding: Finding) -> list[str]:
    return [ref.evidence_id for ref in finding.evidence_refs]


def _excerpt(raw_clause: str) -> str:
    # Single-line join only: the full clause is kept so rationale quotes
    # never cut mid-word or silently drop qualifiers.
    return " ".join(raw_clause.split())


def _clause_has(words: list[str], keyword: str) -> bool:
    return bool(_keyword_spans(words, keyword))


def _clause_has_unnegated(words: list[str], keyword: str) -> bool:
    parts = len(keyword.split())
    return any(
        not _is_negated(words, s, parts)
        for s in _keyword_spans(words, keyword)
    )


def _clause_has_uncertainty(words: list[str]) -> bool:
    return any(w in _UNCERTAINTY_WORDS for w in words)


def finding_text(finding: Finding) -> str:
    """Label + description text for one finding."""
    return _finding_text(finding)


def finding_evidence_ids(finding: Finding) -> list[str]:
    """Evidence ids for one finding."""
    return _evidence_ids(finding)


def text_clauses(text: str) -> list[list[str]]:
    """Word lists per clause (negation never crosses clauses)."""
    return _clauses(text)


def text_raw_clauses(text: str) -> list[str]:
    """Raw clause strings for excerpts."""
    return _raw_clauses(text)


def clause_has_unnegated(words: list[str], keyword: str) -> bool:
    """Word-boundary unnegated keyword check for one clause."""
    return _clause_has_unnegated(words, keyword)


def clause_has_uncertainty(words: list[str]) -> bool:
    """Whether one clause carries hedging language."""
    return _clause_has_uncertainty(words)


def finding_has_unnegated(finding: Finding, keywords) -> bool:
    """Whether any clause holds any keyword unnegated."""
    for words in _clauses(_finding_text(finding)):
        if any(_clause_has_unnegated(words, kw) for kw in keywords):
            return True
    return False


def finding_mentions_person(finding: Finding) -> bool:
    """Unnegated person mention in any clause (negation-aware)."""
    return finding_has_unnegated(finding, _PEOPLE_WORDS)


def excerpt_clause(raw_clause: str) -> str:
    """Single-line excerpt for rationales (full clause, never cut)."""
    return _excerpt(raw_clause)


def has_substance(text: str) -> bool:
    """Whether text carries enough content for a routine read."""
    return _has_substance(text)


def family_clause_categories(
    findings: Sequence[Finding], family: str
) -> set[DamageCategory]:
    """Distinct per-clause damage categories observed for one family.

    Shared by the assessment merge and by validators, so the
    max-severity merge and the disagreement note can be cross-checked
    without duplicating grounding logic.
    """
    categories: set[DamageCategory] = set()
    family_words = _DAMAGE_FAMILY_KEYWORDS.get(family, ())
    if not family_words:
        return categories
    for finding in findings:
        text = _finding_text(finding)
        for clause_words, clause_raw in zip(_clauses(text), _raw_clauses(text)):
            if not any(
                _clause_has_unnegated(clause_words, kw) for kw in family_words
            ):
                continue
            entry = _assess_clause(
                finding, family, clause_words, _excerpt(clause_raw)
            )
            categories.add(entry["category"])
    return categories


def family_consensus_category(
    findings: Sequence[Finding], family: str
) -> DamageCategory | None:
    """Max-severity clause category for one family (None if unmentioned)."""
    categories = family_clause_categories(findings, family)
    if not categories:
        return None
    return max(categories, key=lambda c: _SEVERITY[c])


def damage_assessments(
    findings: Sequence[Finding],
) -> tuple[list[DamageAssessment], list[str]]:
    """One provisional read per mentioned assessable feature family."""
    candidates: dict[str, list[dict]] = {}
    for finding in findings:
        text = _finding_text(finding)
        word_clauses = _clauses(text)
        raw = _raw_clauses(text)
        for clause_words, clause_raw in zip(word_clauses, raw):
            for family in _DAMAGE_FAMILIES:
                family_words = _DAMAGE_FAMILY_KEYWORDS[family]
                if not any(
                    _clause_has_unnegated(clause_words, kw) for kw in family_words
                ):
                    continue
                entry = _assess_clause(
                    finding, family, clause_words, _excerpt(clause_raw)
                )
                candidates.setdefault(family, []).append(entry)
    assessments: list[DamageAssessment] = []
    notes: list[str] = []
    for family in _DAMAGE_FAMILIES:
        group = candidates.get(family, [])
        if not group:
            continue
        best = max(group, key=lambda e: _SEVERITY[e["category"]])
        distinct = {e["category"] for e in group} - {DamageCategory.CANNOT_ASSESS}
        basis_fids: list[str] = []
        basis_eids: list[str] = []
        for entry in group:
            if entry["finding_id"] not in basis_fids:
                basis_fids.append(entry["finding_id"])
            for eid in entry["evidence_ids"]:
                if eid not in basis_eids:
                    basis_eids.append(eid)
        uncertainty = best["uncertainty"]
        if len(distinct) > 1:
            disagreement = (
                "Observations disagree about this feature; "
                "human review must reconcile them."
            )
            uncertainty = f"{uncertainty} {disagreement}".strip()
        assessments.append(
            DamageAssessment(
                assessment_id=f"dmg-{family}",
                feature=family,
                target_label=family,
                basis_finding_ids=basis_fids,
                basis_evidence_ids=basis_eids,
                category=best["category"],
                rationale=best["rationale"],
                uncertainty_note=uncertainty,
                observed_condition=best["observed"],
                condition_class=best["condition_class"],
                recommended_verification=best["verification"],
            )
        )
    if len(assessments) > MAX_DAMAGE_ASSESSMENTS:
        notes.append(
            f"impact_damage_cap: {len(assessments) - MAX_DAMAGE_ASSESSMENTS} "
            "lower-priority damage reads omitted."
        )
        assessments = assessments[:MAX_DAMAGE_ASSESSMENTS]
    return assessments, notes


def _matched_asset(clause_words: list[str], family: str) -> str:
    """Most specific asset term named in the clause, else the family default."""
    for keyword in _DAMAGE_FAMILY_KEYWORDS.get(family, ()):
        if _clause_has_unnegated(clause_words, keyword):
            return keyword
    return _FAMILY_ASSET.get(family, family)


def _condition_class_for(cue: str) -> str:
    """Observed-condition class for one cited cue (never structural)."""
    if cue in _INUNDATION_CUES:
        return "inundation"
    if cue in _OBSTRUCTION_CUES:
        return "obstruction"
    if cue in _COVER_CUES:
        return "surrounding_material"
    return "visible_damage"


def _assess_clause(
    finding: Finding, family: str, clause_words: list[str], excerpt: str
) -> dict:
    fid = finding.finding_id
    eids = _evidence_ids(finding)
    asset = _matched_asset(clause_words, family)
    uncertain = any(w in _UNCERTAINTY_WORDS for w in clause_words)
    strong_hit = next(
        (
            cue
            for cue in _STRONG_DAMAGE_CUES
            if _clause_has_unnegated(clause_words, cue)
        ),
        None,
    )
    moderate_hit = next(
        (
            cue
            for cue in _MODERATE_DAMAGE_CUES
            if _clause_has_unnegated(clause_words, cue)
        ),
        None,
    )
    # Severity gates are unchanged; only the narrative is professional.
    # The verbatim clause quote keeps every read evidence-grounded while
    # finding ids and rule mechanics stay out of the prose.
    if strong_hit is not None and not uncertain:
        condition = "visible_damage"
        return {
            "category": DamageCategory.APPARENT_MAJOR_DAMAGE,
            "observed": _OBSERVED_TEMPLATES[condition].format(asset=asset),
            "condition_class": condition,
            "rationale": (
                f"Imagery shows '{excerpt}'. Provisional assessment: "
                "apparent major damage — not an engineering finding. "
                "Structural integrity is unconfirmed; requires human "
                "verification."
            ),
            "uncertainty": _UNCERTAINTY_TEMPLATES[condition],
            "verification": _VERIFICATION_TEMPLATES[condition].format(
                asset=asset
            ),
            "finding_id": fid,
            "evidence_ids": eids,
        }
    if strong_hit is not None or moderate_hit is not None:
        cue = strong_hit if strong_hit is not None else moderate_hit
        assert cue is not None
        condition = _condition_class_for(cue)
        hedge = " The observation uses uncertain wording." if uncertain else ""
        uncertainty = (
            _UNCERTAINTY_TEMPLATES["possible_visible_damage"]
            if condition == "visible_damage"
            else _UNCERTAINTY_TEMPLATES[condition]
        )
        return {
            "category": DamageCategory.POSSIBLE_DAMAGE,
            "observed": _OBSERVED_TEMPLATES[condition].format(asset=asset),
            "condition_class": condition,
            "rationale": (
                f"Imagery shows '{excerpt}'.{hedge} Provisional "
                "assessment: possible damage — not an engineering "
                "finding. Requires human verification before any "
                "operational use."
            ),
            "uncertainty": uncertainty,
            "verification": _VERIFICATION_TEMPLATES[condition].format(
                asset=asset
            ),
            "finding_id": fid,
            "evidence_ids": eids,
        }
    if _clause_states_intact(clause_words):
        return {
            "category": DamageCategory.NO_VISIBLE_DAMAGE,
            "observed": _OBSERVED_TEMPLATES["intact"].format(asset=asset),
            "condition_class": "intact",
            "rationale": (
                f"Imagery shows '{excerpt}'. Provisional assessment: no "
                "visible damage at available resolution. This does not "
                "confirm structural safety."
            ),
            "uncertainty": _UNCERTAINTY_TEMPLATES["intact"],
            "verification": _VERIFICATION_TEMPLATES["intact"],
            "finding_id": fid,
            "evidence_ids": eids,
        }
    return {
        "category": DamageCategory.CANNOT_ASSESS,
        "observed": _OBSERVED_TEMPLATES["unassessed"].format(
            asset=asset, Asset=asset[:1].upper() + asset[1:]
        ),
        "condition_class": "unassessed",
        "rationale": (
            f"The {asset} is mentioned without assessable damage detail "
            f"('{excerpt}'); condition cannot be assessed from this "
            "observation."
        ),
        "uncertainty": _UNCERTAINTY_TEMPLATES["unassessed"],
        "verification": _VERIFICATION_TEMPLATES["unassessed"],
        "finding_id": fid,
        "evidence_ids": eids,
    }


def _clause_states_intact(clause_words: list[str]) -> bool:
    if any(w in _INTACT_WORDS for w in clause_words):
        return True
    for cue in _STRONG_DAMAGE_CUES + _MODERATE_DAMAGE_CUES:
        parts = len(cue.split())
        for start in _keyword_spans(clause_words, cue):
            if _is_negated(clause_words, start, parts):
                return True
    return False


def rescue_priorities(
    findings: Sequence[Finding],
) -> tuple[list[RescueAttention], list[str]]:
    """One human-danger urgency per finding (or one undetermined).

    Strict gates: high needs people + explicit danger in one clause,
    certain; medium needs people + danger hedged, or people + a
    narrowed hazard cue in one clause. Person-alone is routine (low);
    findings with no person evidence are undetermined, never low.
    Access/infrastructure questions belong to access priorities, not
    rescue. No casualties, locations, or deployment are ever stated.
    """
    if not findings:
        return [
            RescueAttention(
                attention_id="att-empty",
                priority=RescuePriority.UNDETERMINED,
                rationale=(
                    "No findings available; urgency cannot be assessed. "
                    "Human review of the image is still required."
                ),
                unknowns="Whether any person is present or at risk.",
            )
        ], []
    ranked: list[RescueAttention] = []
    for index, finding in enumerate(findings):
        ranked.append(_rescue_for_finding(index, finding))
    notes: list[str] = []
    if len(ranked) > MAX_RESCUE_PRIORITIES:
        notes.append(
            f"impact_rescue_cap: {len(ranked) - MAX_RESCUE_PRIORITIES} "
            "lower-priority rescue reads omitted."
        )
        ranked = ranked[:MAX_RESCUE_PRIORITIES]
    return ranked, notes


def _rescue_for_finding(index: int, finding: Finding) -> RescueAttention:
    fid = finding.finding_id
    eids = _evidence_ids(finding)
    text = _finding_text(finding)
    word_clauses = _clauses(text)
    raw = _raw_clauses(text)
    best = RescuePriority.UNDETERMINED
    rationale = (
        f"Finding '{fid}' has insufficient detail to assess urgency; "
        "human review is needed to determine relevance."
    )
    unknowns = "Whether any person is present; relevance unconfirmed."
    for clause_words, clause_raw in zip(word_clauses, raw):
        candidate, text_, unknown_ = _rescue_for_clause(
            fid, clause_words, _excerpt(clause_raw)
        )
        if _PRIORITY_RANK[candidate] > _PRIORITY_RANK[best]:
            best, rationale, unknowns = candidate, text_, unknown_
    if best == RescuePriority.UNDETERMINED:
        if finding_mentions_person(finding) and _has_substance(text):
            best = RescuePriority.LOW
            rationale = (
                f"Finding '{fid}' ('{finding.label}') mentions people "
                "with no danger indication; routine human review for "
                "people safety."
            )
            unknowns = (
                "Number, condition, and exact circumstances of any "
                "people; no danger is indicated."
            )
        elif _has_substance(text):
            rationale = (
                f"Finding '{fid}' ('{finding.label}') shows no person "
                "evidence; rescue urgency cannot be determined from "
                "this observation."
            )
            unknowns = "Whether any person is present or at risk."
    return RescueAttention(
        attention_id=f"att-{index + 1}",
        priority=best,
        basis_finding_ids=[fid],
        basis_evidence_ids=eids,
        rationale=rationale,
        unknowns=unknowns,
    )


def _rescue_for_clause(
    fid: str, clause_words: list[str], excerpt: str
) -> tuple[RescuePriority, str, str]:
    people = any(
        _clause_has_unnegated(clause_words, word) for word in _PEOPLE_WORDS
    )
    danger = next(
        (
            cue
            for cue in _DANGER_CUES
            if _clause_has_unnegated(clause_words, cue)
        ),
        None,
    )
    uncertain = any(w in _UNCERTAINTY_WORDS for w in clause_words)
    hazard = any(
        _clause_has_unnegated(clause_words, word)
        for word in _PEOPLE_HAZARD_WORDS
    )
    if people and danger is not None:
        if uncertain:
            return (
                RescuePriority.MEDIUM,
                (
                    f"Finding '{fid}' hedges a possible-danger indication "
                    f"('{excerpt}'); timely human verification is needed "
                    "before any urgency claim."
                ),
                (
                    "Whether anyone is in danger; presence, condition, "
                    "and exact circumstances unconfirmed."
                ),
            )
        return (
            RescuePriority.HIGH,
            (
                f"Finding '{fid}' explicitly indicates possible immediate "
                f"danger ('{excerpt}'). Requires urgent authorized human "
                "assessment; presence, condition, and exact circumstances "
                "are not confirmed."
            ),
            (
                "Presence, condition, and exact circumstances of any "
                "people; danger not confirmed beyond the observation."
            ),
        )
    if people and hazard:
        return (
            RescuePriority.MEDIUM,
            (
                f"Finding '{fid}' mentions people with a plausible hazard "
                f"context ('{excerpt}'); exposure is not established. "
                "Requires timely human verification."
            ),
            (
                "Whether any person is exposed; number, condition, and "
                "exact circumstances unconfirmed."
            ),
        )
    return RescuePriority.UNDETERMINED, "", ""


def access_priorities(
    findings: Sequence[Finding],
) -> tuple[list[AccessAttention], list[str]]:
    """One access/infrastructure urgency per finding (or one undetermined).

    Separate from rescue: high needs infrastructure + an explicit
    access-cut cue (blockage, destruction) in one clause, certain;
    medium needs infrastructure + damage evidence or hedged
    access-cut language. Infrastructure-alone is routine (low);
    findings with no infrastructure evidence are undetermined.
    """
    if not findings:
        return [
            AccessAttention(
                attention_id="acc-empty",
                priority=RescuePriority.UNDETERMINED,
                rationale=(
                    "No findings available; access urgency cannot be "
                    "assessed. Human review of the image is required."
                ),
                unknowns="Whether any route or structure needs verification.",
            )
        ], []
    ranked: list[AccessAttention] = []
    for index, finding in enumerate(findings):
        ranked.append(_access_for_finding(index, finding))
    notes: list[str] = []
    if len(ranked) > MAX_ACCESS_PRIORITIES:
        notes.append(
            f"impact_access_cap: {len(ranked) - MAX_ACCESS_PRIORITIES} "
            "lower-priority access reads omitted."
        )
        ranked = ranked[:MAX_ACCESS_PRIORITIES]
    return ranked, notes


def _access_for_finding(index: int, finding: Finding) -> AccessAttention:
    fid = finding.finding_id
    eids = _evidence_ids(finding)
    text = _finding_text(finding)
    word_clauses = _clauses(text)
    raw = _raw_clauses(text)
    best = RescuePriority.UNDETERMINED
    rationale = (
        f"Finding '{fid}' has insufficient detail to assess access "
        "urgency; human review is needed."
    )
    unknowns = "Whether any route or structure needs verification."
    mentions_infra = False
    for clause_words, clause_raw in zip(word_clauses, raw):
        family = _infra_family_in_clause(clause_words)
        if family is not None:
            mentions_infra = True
        candidate, text_, unknown_ = _access_for_clause(
            fid, family, clause_words, _excerpt(clause_raw)
        )
        if _PRIORITY_RANK[candidate] > _PRIORITY_RANK[best]:
            best, rationale, unknowns = candidate, text_, unknown_
    if best == RescuePriority.UNDETERMINED:
        if mentions_infra and _has_substance(text):
            best = RescuePriority.LOW
            rationale = (
                f"Finding '{fid}' ('{finding.label}') names "
                "infrastructure with no damage indication; routine "
                "verification."
            )
            unknowns = (
                "Whether the route or structure is usable; identity "
                "and condition unconfirmed."
            )
        elif _has_substance(text):
            rationale = (
                f"Finding '{fid}' ('{finding.label}') shows no "
                "infrastructure evidence; access urgency cannot be "
                "determined."
            )
    return AccessAttention(
        attention_id=f"acc-{index + 1}",
        priority=best,
        basis_finding_ids=[fid],
        basis_evidence_ids=eids,
        rationale=rationale,
        unknowns=unknowns,
    )


def _infra_family_in_clause(clause_words: list[str]) -> str | None:
    for family, keywords in _DAMAGE_FAMILY_KEYWORDS.items():
        if any(_clause_has_unnegated(clause_words, kw) for kw in keywords):
            return family
    return None


def _access_for_clause(
    fid: str, family: str | None, clause_words: list[str], excerpt: str
) -> tuple[RescuePriority, str, str]:
    if family is None:
        return RescuePriority.UNDETERMINED, "", ""
    uncertain = any(w in _UNCERTAINTY_WORDS for w in clause_words)
    high_hit = next(
        (
            cue
            for cue in _ACCESS_HIGH_CUES
            if _clause_has_unnegated(clause_words, cue)
        ),
        None,
    )
    moderate_hit = next(
        (
            cue
            for cue in _MODERATE_DAMAGE_CUES
            if _clause_has_unnegated(clause_words, cue)
        ),
        None,
    )
    strong_hit = next(
        (
            cue
            for cue in _STRONG_DAMAGE_CUES
            if _clause_has_unnegated(clause_words, cue)
        ),
        None,
    )
    if high_hit is not None and not uncertain:
        return (
            RescuePriority.HIGH,
            (
                f"Finding '{fid}' indicates '{high_hit}' linked to "
                f"'{family}' in one observation ('{excerpt}'); timely "
                "field verification of access is needed."
            ),
            (
                "Whether the route or structure is usable; extent, "
                "identity, and trend unconfirmed."
            ),
        )
    if high_hit is not None or moderate_hit is not None or strong_hit is not None:
        cue = high_hit or strong_hit or moderate_hit
        hedge = " (uncertain wording)" if uncertain else ""
        return (
            RescuePriority.MEDIUM,
            (
                f"Finding '{fid}' describes '{cue}' linked to '{family}' "
                f"in one observation{hedge} ('{excerpt}'); verification "
                "of access or condition is needed."
            ),
            (
                "Whether the route or structure is affected; extent "
                "and usability unconfirmed."
            ),
        )
    return RescuePriority.UNDETERMINED, "", ""


def review_priorities(
    findings: Sequence[Finding],
) -> tuple[list[ReviewAttention], list[str]]:
    """One image-review urgency per finding (or one undetermined).

    Separate from rescue and access: rates how promptly a human
    should review the observation itself. Danger or major-damage
    language ranks first; risk-flagged observations rank next;
    quiet substantive observations are routine; vacuous findings
    are undetermined.
    """
    if not findings:
        return [
            ReviewAttention(
                review_id="rev-empty",
                priority=RescuePriority.UNDETERMINED,
                rationale=(
                    "No findings available; review urgency cannot be "
                    "assessed. Human review of the image is required."
                ),
                unknowns="What the image shows.",
            )
        ], []
    ranked: list[ReviewAttention] = []
    for index, finding in enumerate(findings):
        ranked.append(_review_for_finding(index, finding))
    notes: list[str] = []
    if len(ranked) > MAX_REVIEW_PRIORITIES:
        notes.append(
            f"impact_review_cap: {len(ranked) - MAX_REVIEW_PRIORITIES} "
            "lower-priority review reads omitted."
        )
        ranked = ranked[:MAX_REVIEW_PRIORITIES]
    return ranked, notes


def _review_for_finding(index: int, finding: Finding) -> ReviewAttention:
    fid = finding.finding_id
    eids = _evidence_ids(finding)
    text = _finding_text(finding)
    word_clauses = _clauses(text)
    raw = _raw_clauses(text)
    best = RescuePriority.UNDETERMINED
    rationale = (
        f"Finding '{fid}' has insufficient detail to assess review "
        "urgency; human review is needed."
    )
    unknowns = "What the observation shows; relevance unconfirmed."
    for clause_words, clause_raw in zip(word_clauses, raw):
        candidate, text_, unknown_ = _review_for_clause(
            fid, clause_words, _excerpt(clause_raw)
        )
        if _PRIORITY_RANK[candidate] > _PRIORITY_RANK[best]:
            best, rationale, unknowns = candidate, text_, unknown_
    if best == RescuePriority.UNDETERMINED and _has_substance(text):
        best = RescuePriority.LOW
        rationale = (
            f"Finding '{fid}' ('{finding.label}') shows no danger or "
            "damage indicators; routine human review."
        )
        unknowns = "Whether the observation is accurate and relevant."
    return ReviewAttention(
        review_id=f"rev-{index + 1}",
        priority=best,
        basis_finding_ids=[fid],
        basis_evidence_ids=eids,
        rationale=rationale,
        unknowns=unknowns,
    )


def _review_for_clause(
    fid: str, clause_words: list[str], excerpt: str
) -> tuple[RescuePriority, str, str]:
    danger = next(
        (
            cue
            for cue in _DANGER_CUES
            if _clause_has_unnegated(clause_words, cue)
        ),
        None,
    )
    strong = next(
        (
            cue
            for cue in _STRONG_DAMAGE_CUES
            if _clause_has_unnegated(clause_words, cue)
        ),
        None,
    )
    if danger is not None or strong is not None:
        cue = danger if danger is not None else strong
        return (
            RescuePriority.HIGH,
            (
                f"Finding '{fid}' flags '{cue}' ('{excerpt}'); prompt "
                "human review is needed before any operational use."
            ),
            "Whether the flagged observation is accurate and relevant.",
        )
    moderate = next(
        (
            cue
            for cue in _MODERATE_DAMAGE_CUES
            if _clause_has_unnegated(clause_words, cue)
        ),
        None,
    )
    risk = any(
        _clause_has_unnegated(clause_words, word) for word in _RISK_WORDS
    )
    people = any(
        _clause_has_unnegated(clause_words, word) for word in _PEOPLE_WORDS
    )
    if moderate is not None or risk or people:
        cue = moderate or "risk-flagged observation"
        return (
            RescuePriority.MEDIUM,
            (
                f"Finding '{fid}' is risk-flagged ('{cue}' in "
                f"'{excerpt}'); timely human review is needed."
            ),
            "Whether the observation is accurate and relevant.",
        )
    return RescuePriority.UNDETERMINED, "", ""


def _has_substance(text: str) -> bool:
    words = _WORD_RE.findall(text.lower())
    content = [w for w in words if len(w) > 2]
    return len(content) >= 4
