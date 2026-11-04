"""Deterministic prompt planner: findings -> SAM 3.1 concept prompts.

Selection ranks positively observed concepts by expected assessment
contribution, not by a fixed demo order or confidence alone:

1. User-requested targets first (``user_requested`` provenance), within
   the prompt cap. Equivalent concepts (house/building, rubble/debris)
   dedupe with the operator wording preserved in ``requested_as``.
2. Automatic picks (``automatic``) for positively observed, SAM-suitable
   concepts in the finding label plus Observed / Affected feature /
   Location sections. Inferred-impact text never triggers automatic
   prompts. Candidates rank by operational tier, then Muse Spark
   confidence (uncalibrated triage signal, no threshold), then prompt
   name:
   - Tier 0: people with an explicit danger cue in the same clause
     (possible immediate risk triage).
   - Tier 1: people observed (human-exposure assessment).
   - Tier 2: primary hazard extent (river/floodwater, debris) and
     infrastructure (building/road/bridge/vehicle) with damage or
     hazard context in the same clause (damage / access assessment).
     Hazards do not automatically outrank credible infrastructure:
     same tier, so confidence decides.
   - Tier 3: neutral infrastructure without damage or hazard context.
3. One optional exploratory prompt (``exploratory``) for an unmentioned
   access route, only when no automatic prompt was planned, an observed
   obscured-access cue (buried/blocked/covered/obscured/...) suggests a
   possibly hidden route, no road/bridge/building is already planned,
   and budget remains. No slot is reserved; most runs have no
   exploratory prompt, and road is never a per-landslide fallback.

Observed-concept to SAM-prompt mapping (evidence-grounded; SAM 3.1 text
prompts take one short concrete noun per request, so abstract hazard
zones are never prompted):
- floodwater/flood/water/stream/river -> ``river`` (water extent).
- debris/rubble -> ``debris`` (hazard-material piles; preserves a
  "landslide debris" observation via its concrete noun instead of
  substituting rocks or mud, which would change the target).
- building/house/structure/... -> ``building`` (standing or collapsed
  structures; rubble piles additionally map to ``debris``).
- bridge/overpass -> ``bridge``; road/highway/... -> ``road``;
  vehicle/car/... -> ``vehicle``; people/person/... -> ``people``.
- Unsupported, so no automatic prompt: bare event nouns without
  material (landslide/landslip/mudslide alone), amorphous stuff with
  gradational boundaries (mud/sediment/silt), scattered clasts alone
  (rocks/boulders: discrete objects that do not delineate the deposit),
  and abstract zones (hazard zone/affected area). Operators may still
  request any of these free-form via user targets.

Why fixed checklists mislead: a static road-first order promotes a
marginal road mention above people exposure, building damage, debris,
or flood extent, and keyword scans over inferred text promote
hypothetical mentions. This planner keeps only positive observations,
filters negated / conditional / disclaimer clauses, and lets
operational tier lead with confidence second.

Rules:
- Pure function of findings, confidences, and user targets.
- Negated keywords (no/not/without/absent/none/never/neither/lacks/
  missing within 3 words before, absent/missing/not visible/not present
  after) never trigger.
- Conditional clauses (if/whether/hypothetical/assuming/suppose,
  "in case") and safety-advice clauses ("do not ...") never trigger;
  plain uncertainty (possible/maybe/uncertain) still triggers because
  the observation is present but hedged.
- Hyphenated compounds tokenize whole (``human-made`` never matches
  ``human``), and ``pedestrian`` immediately before a bridge-family noun
  names infrastructure, not an observed person.
- A label-only assertion is vetoed when the finding description denies
  the same concept (``label: people`` plus ``no people visible``
  selects nothing for people).
- Prompts dedupe; output follows tier/confidence/name order.
- At most ``MAX_SAM_PROMPTS`` prompts; the caller marks the rest skipped.
- No fallback: zero segmentable observations (and no justified
  exploratory) means zero prompts, never an invented default. A missing
  or zero-match outcome never implies object absence.
- SAM geometry is never read as damage, blockage, exposure, hazard
  extent, or verified-boundary evidence; linkage stays
  ``prompt_trigger_only`` downstream, and masks are never presented as
  verified hazard boundaries, confirmed damage, or confirmed exposure.
"""

from __future__ import annotations

import re
from typing import Sequence

from app.schemas.common import Finding
from app.schemas.unified_analysis import PromptDecision, PromptProvenance

MAX_SAM_PROMPTS = 3

# Canonical SAM vocabulary. Dict order is NOT the ranking; tiers below decide.
# Plurals included: matching is word-boundary based, so "houses" must hit.
PROMPT_KEYWORDS: dict[str, list[str]] = {
    "road": [
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
    ],
    "river": [
        "river",
        "rivers",
        "floodwater",
        "floodwaters",
        "flood",
        "floods",
        "stream",
        "streams",
        "water",
        "waters",
    ],
    "building": [
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
        # Visible components of partly visible structures: recognizing
        # them selects the same "building" prompt; it never replaces
        # building prompts wholesale.
        "roof",
        "roofs",
        "rooftop",
        "rooftops",
    ],
    "vehicle": [
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
    ],
    "people": [
        "person",
        "persons",
        "people",
        "human",
        "humans",
        "pedestrian",
        "pedestrians",
    ],
    "debris": [
        "debris",
        "rubble",
    ],
    "bridge": [
        "bridge",
        "bridges",
        "overpass",
        "overpasses",
    ],
}

# User-target synonyms: operator wording -> canonical vocab prompt.
# Terms with no entry pass through to SAM verbatim as free-form prompts.
TARGET_ALIASES: dict[str, str] = {
    "house": "building",
    "houses": "building",
    "buildings": "building",
    "hut": "building",
    "huts": "building",
    "shed": "building",
    "sheds": "building",
    "structure": "building",
    "structures": "building",
    "car": "vehicle",
    "cars": "vehicle",
    "truck": "vehicle",
    "trucks": "vehicle",
    "bus": "vehicle",
    "buses": "vehicle",
    "jeep": "vehicle",
    "jeeps": "vehicle",
    "vehicles": "vehicle",
    "roadway": "road",
    "roadways": "road",
    "highway": "road",
    "highways": "road",
    "street": "road",
    "streets": "road",
    "lane": "road",
    "lanes": "road",
    "roads": "road",
    "stream": "river",
    "streams": "river",
    "flood": "river",
    "floods": "river",
    "floodwater": "river",
    "floodwaters": "river",
    "water": "river",
    "waters": "river",
    "rivers": "river",
    "person": "people",
    "persons": "people",
    "human": "people",
    "humans": "people",
    "pedestrian": "people",
    "pedestrians": "people",
    "rubble": "debris",
    "bridges": "bridge",
    "overpass": "bridge",
    "overpasses": "bridge",
}

MAX_USER_TARGETS = 3
MAX_USER_TARGET_CHARS = 40

_NEGATION_BEFORE = {
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
_NEGATION_AFTER = {"absent", "missing"}
_BEFORE_WINDOW = 3
_AFTER_WINDOW = 2
# Hyphen-aware tokens: "human-made" stays one token so compound
# fragments never match ("human" must mean a person, not a material).
_WORD_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

# Conditional / hypothetical markers: the clause speculates rather than
# observes. Narrow on purpose so plain uncertainty still triggers.
_HYPOTHETICAL_WORDS = frozenset(
    {"if", "whether", "hypothetical", "hypothetically", "assuming", "suppose"}
)
_HYPOTHETICAL_PHRASES = ("in case",)

# Damage cues marking affected infrastructure (same clause). Mirrors the
# condition-assessment grounding vocabulary for consistency.
_DAMAGE_CUES = (
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
    # Fire family appended last (mirrors the condition-assessment
    # grounding vocabulary; existing cue precedence is preserved).
    "fire",
    "burning",
    "flames",
)

# Hazard context (actual hazard indicators, never mere water-feature
# mentions): infrastructure sharing a clause with one of these counts as
# affected. Mirrors the narrowed people-hazard grounding set.
_HAZARD_CUES = frozenset(
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
        "mudslide",
        "blocked",
        "blockage",
        "destroyed",
        "breach",
        "breached",
        "washout",
        "rubble",
        "submerged",
        "hazard",
        "hazardous",
        "danger",
        "dangerous",
        "risk",
    }
)

# Explicit immediate-danger cues (same clause as people -> tier 0).
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

_PEDESTRIAN_KEYWORDS = frozenset({"pedestrian", "pedestrians"})
# Infrastructure sense of "pedestrian": only the immediately-following
# bridge-family noun suppresses, so "pedestrian on the bridge" and
# "pedestrian crossing the road" (a real observed person) still trigger.
_PEDESTRIAN_STRUCTURE_FOLLOW = frozenset(
    {"bridge", "bridges", "overpass", "overpasses"}
)

_INFRASTRUCTURE_PROMPTS = frozenset({"building", "road", "vehicle", "bridge"})
# Exploratory checks an unmentioned access route: roads are the most
# likely missed linear infrastructure and gate field access.
EXPLORATORY_PROMPT = "road"

# Obscured-access cues justifying the exploratory route check: the
# observation suggests ground or passage hidden under cover, blockage,
# or failure — not merely that a hazard event was named. Bare event
# nouns (landslide/mudslide/flood) and bare materials (debris/mud) do
# not justify it: debris already prompts automatically, and a named
# event alone is not evidence of a hidden route.
_EXPLORATORY_CUES = (
    "blocked",
    "blockage",
    "buried",
    "covered",
    "obscured",
    "obscuring",
    "obstructed",
    "obstruction",
    "cut off",
    "washed away",
    "washout",
    "submerged",
    "collapse",
    "collapsed",
    "collapsing",
)


def _clauses(text: str) -> list[list[str]]:
    """Word lists per clause; negation never crosses a clause boundary."""
    return [
        _WORD_RE.findall(chunk.lower())
        for chunk in re.split(r"[.,;:\n]+", text)
    ]


def _keyword_spans(words: list[str], keyword: str) -> list[int]:
    """Start indexes where the (possibly multi-word) keyword occurs."""
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
    # "road not visible" / "road not present" trailing pattern.
    if len(after) >= 2 and after[0] == "not" and after[1] in {"visible", "present"}:
        return True
    return False


def _is_hypothetical(words: list[str]) -> bool:
    if any(w in _HYPOTHETICAL_WORDS for w in words):
        return True
    joined = " ".join(words)
    if any(phrase in joined for phrase in _HYPOTHETICAL_PHRASES):
        return True
    # Safety advice ("do not approach ...") is not an observation.
    if len(words) >= 2 and words[0] == "do" and words[1] in {"not", "nt"}:
        return True
    return False


def _has_unnegated(words: list[str], keyword: str) -> bool:
    parts = len(keyword.split())
    return any(
        not _is_negated(words, start, parts)
        for start in _keyword_spans(words, keyword)
    )


def _prompt_spans(words: list[str], prompt: str, keyword: str) -> list[int]:
    """Keyword spans, minus infrastructure senses of "pedestrian"."""
    spans = _keyword_spans(words, keyword)
    if prompt == "people" and keyword in _PEDESTRIAN_KEYWORDS:
        spans = [
            s
            for s in spans
            if not (
                s + 1 < len(words)
                and words[s + 1] in _PEDESTRIAN_STRUCTURE_FOLLOW
            )
        ]
    return spans


def _observed_description(finding: Finding) -> str:
    """Observed description lines; inferred impact excluded."""
    observed_lines = [
        line
        for line in (finding.description or "").splitlines()
        if not line.strip().lower().startswith("inferred impact")
    ]
    return "\n".join(observed_lines)


def _observed_text(finding: Finding) -> str:
    """Label plus observed sections; inferred impact excluded.

    Vision descriptions embed ``Observed:`` / ``Affected feature:`` /
    ``Location in image:`` / ``Inferred impact:`` lines. Only the first
    three (plus the label) count as positive observations for automatic
    prompts; inferred lines are hypothetical by construction.
    """
    return f"{finding.label}\n{_observed_description(finding)}"


def _confidence_of(finding: Finding) -> float:
    try:
        value = float(finding.confidence.value)
    except (TypeError, ValueError):
        return 0.5
    if value != value:  # NaN
        return 0.5
    return min(1.0, max(0.0, value))


def _tier(prompt: str, *, danger: bool, affected: bool) -> int:
    if prompt == "people":
        return 0 if danger else 1
    if prompt in ("river", "debris"):
        return 2
    return 2 if affected else 3


def derive_sam_prompts(
    findings: Sequence[Finding], max_prompts: int = MAX_SAM_PROMPTS
) -> list[PromptDecision]:
    """Derive ordered automatic SAM prompts (pure, capped, no exploratory)."""
    hits: dict[str, list[dict]] = {p: [] for p in PROMPT_KEYWORDS}
    denials: dict[str, set[str]] = {p: set() for p in PROMPT_KEYWORDS}
    for finding in findings:
        confidence = _confidence_of(finding)
        clause_sources = [(True, words) for words in _clauses(finding.label or "")]
        clause_sources += [
            (False, words) for words in _clauses(_observed_description(finding))
        ]
        for from_label, words in clause_sources:
            if _is_hypothetical(words):
                continue
            clause_danger = any(
                _has_unnegated(words, cue) for cue in _DANGER_CUES
            )
            clause_affected = any(
                _has_unnegated(words, cue) for cue in _DAMAGE_CUES
            ) or any(
                _has_unnegated(words, cue) for cue in sorted(_HAZARD_CUES)
            )
            for prompt, keywords in PROMPT_KEYWORDS.items():
                hit_keyword: str | None = None
                for keyword in keywords:
                    spans = _prompt_spans(words, prompt, keyword)
                    if any(
                        not _is_negated(words, s, len(keyword.split()))
                        for s in spans
                    ):
                        hit_keyword = keyword
                        break
                    if not from_label and any(
                        _is_negated(words, s, len(keyword.split()))
                        for s in spans
                    ):
                        denials[prompt].add(finding.finding_id)
                if hit_keyword is None:
                    continue
                hits[prompt].append(
                    {
                        "fid": finding.finding_id,
                        "keyword": hit_keyword,
                        "conf": confidence,
                        "from_label": from_label,
                        "danger": clause_danger,
                        "affected": clause_affected,
                    }
                )
    ranked: list[tuple[int, float, str]] = []
    decisions: dict[str, PromptDecision] = {}
    for prompt in PROMPT_KEYWORDS:
        prompt_hits = hits[prompt]
        if not prompt_hits:
            continue
        desc_fids = {h["fid"] for h in prompt_hits if not h["from_label"]}
        # A label-only assertion is vetoed when the same finding's
        # description denies the concept; findings are independent, so
        # one finding's denial never vetoes another's assertion.
        kept = [
            h
            for h in prompt_hits
            if not (
                h["from_label"]
                and h["fid"] in denials[prompt]
                and h["fid"] not in desc_fids
            )
        ]
        if not kept:
            continue
        triggers: list[str] = []
        for h in kept:
            if h["fid"] not in triggers:
                triggers.append(h["fid"])
        matched: list[str] = []
        for h in kept:
            if h["keyword"] not in matched:
                matched.append(h["keyword"])
        danger = prompt == "people" and any(h["danger"] for h in kept)
        affected = prompt in _INFRASTRUCTURE_PROMPTS and any(
            h["affected"] for h in kept
        )
        ranked.append(
            (
                _tier(prompt, danger=danger, affected=affected),
                -max(h["conf"] for h in kept),
                prompt,
            )
        )
        decisions[prompt] = PromptDecision(
            prompt=prompt,
            triggered_by=triggers,
            matched_keywords=matched,
            provenance=PromptProvenance.AUTOMATIC,
        )
    ranked.sort()
    return [decisions[prompt] for _, _, prompt in ranked[: max(0, max_prompts)]]


def _exploratory_justification(findings: Sequence[Finding]) -> list[str]:
    """Finding ids with observed obscured-access cues (unnegated)."""
    justifying: list[str] = []
    for finding in findings:
        for words in _clauses(_observed_text(finding)):
            if _is_hypothetical(words):
                continue
            if any(_has_unnegated(words, cue) for cue in _EXPLORATORY_CUES):
                justifying.append(finding.finding_id)
                break
    return justifying


def canonicalize_target(raw_target: str) -> str:
    """Map operator wording to a canonical prompt (aliases resolve)."""
    return TARGET_ALIASES.get(raw_target.strip().lower(), raw_target.strip().lower())


def plan_sam_prompts(
    findings: Sequence[Finding],
    user_targets: Sequence[str] = (),
    max_prompts: int = MAX_SAM_PROMPTS,
) -> list[PromptDecision]:
    """Full SAM plan: user targets, automatic picks, optional exploratory.

    Equivalent concepts dedupe to one prompt (user wording wins and is
    preserved in ``requested_as``). Unknown user terms pass through to SAM
    verbatim as free-form prompts. At most one exploratory access-route
    check is appended when no automatic prompt was planned, an observed
    obscured-access cue justifies it, no road/bridge/building is already
    planned, and budget remains. Pure function of its inputs.
    """
    plan: list[PromptDecision] = []
    covered: set[str] = set()
    for raw in user_targets:
        term = raw.strip().lower()
        if not term or term in covered:
            continue
        canonical = TARGET_ALIASES.get(term, term)
        if canonical in covered:
            continue
        covered.add(term)
        covered.add(canonical)
        plan.append(
            PromptDecision(
                prompt=canonical,
                triggered_by=[],
                matched_keywords=[],
                provenance=PromptProvenance.USER_REQUESTED,
                requested_as=raw.strip(),
            )
        )
    for decision in derive_sam_prompts(findings, max_prompts=len(PROMPT_KEYWORDS)):
        if decision.prompt in covered:
            continue
        covered.add(decision.prompt)
        plan.append(decision)
    has_automatic = any(
        decision.provenance == PromptProvenance.AUTOMATIC for decision in plan
    )
    if (
        len(plan) < max(0, max_prompts)
        and not has_automatic
        and EXPLORATORY_PROMPT not in covered
        and "building" not in covered
        and "bridge" not in covered
    ):
        justifying = _exploratory_justification(findings)
        if justifying:
            plan.append(
                PromptDecision(
                    prompt=EXPLORATORY_PROMPT,
                    triggered_by=justifying,
                    matched_keywords=[],
                    provenance=PromptProvenance.EXPLORATORY,
                )
            )
    return plan[: max(0, max_prompts)]
