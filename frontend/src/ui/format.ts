// Shared presentation copy helpers. Pluralization and id shortening
// change wording only — never the underlying facts or exported data.

/** "1 finding" / "3 findings" — avoids "(s)" walls in copy. */
export function plural(
  count: number,
  singular: string,
  pluralForm?: string,
): string {
  const word = count === 1 ? singular : (pluralForm ?? `${singular}s`);
  return `${count} ${word}`;
}

/** Append a terminal period when the sentence has none. */
export function ensurePeriod(text: string): string {
  const trimmed = text.trim();
  if (!trimmed) return trimmed;
  return /[.!?]$/.test(trimmed) ? trimmed : `${trimmed}.`;
}

/** Capitalize one status word ("high" -> "High") for display. */
export function titleWord(word: string): string {
  if (!word) return word;
  return word.charAt(0).toUpperCase() + word.slice(1);
}

/** Professional labels for analysis workflow states. */
export function workflowStatusLabel(status: string): string {
  if (status === 'vision_only') return 'Visual Observations Only';
  return titleWord(status);
}

/** Professional labels for assessment states. */
export function assessmentStatusLabel(status: string): string {
  return titleWord(status);
}

/** Card/brief heading for a verification action: the backend's
 *  concise structured title when present, else a word-safe
 *  first-sentence fallback. Never cuts mid-word; the full task always
 *  renders in the details below, so headings lose nothing. */
export function actionTitle(action: {
  title?: string;
  what: string;
  action: string;
}): string {
  const backend = (action.title ?? '').trim();
  if (backend) return backend;
  return firstSentence(action.what || action.action);
}

/** First sentence when short, else a word-boundary shortening. */
function firstSentence(text: string): string {
  const trimmed = text.trim();
  const first = trimmed.match(/^.*?[.!?](?=\s|$)/)?.[0]?.trim() ?? trimmed;
  if (first.length < trimmed.length && first.length <= 140) return first;
  if (trimmed.length <= 140) return trimmed;
  const cut = trimmed.slice(0, 137);
  const boundary = cut.lastIndexOf(' ');
  return `${(boundary > 60 ? cut.slice(0, boundary) : cut).trimEnd()}…`;
}

/** User-friendly text for an analysis failure. Maps timeout and
 *  service errors to plain guidance (the upload and focus areas are
 *  always kept, so retry never needs a re-upload); anything else falls
 *  back to the raw message so no diagnostic detail is hidden. */
export function friendlyErrorMessage(error: unknown, fallback: string): string {
  const raw = error instanceof Error ? error.message : '';
  const detail = raw.match(/"detail"\s*:\s*"([^"]*)"/)?.[1] ?? raw;
  if (/sam31_timeout|sam31.*timed?\s?out/i.test(detail)) {
    return (
      'Region detection timed out before finishing. ' +
      'Your image and settings are kept — try again.'
    );
  }
  if (/muse_spark_timeout|timed?\s?out/i.test(detail)) {
    return (
      'The image analysis timed out before finishing. ' +
      'Your image and focus areas are kept — wait a moment and try again.'
    );
  }
  if (/\b502\b/.test(raw) || /temporarily unavailable|service unavailable/i.test(detail)) {
    return (
      'The analysis service is temporarily unavailable. ' +
      'Your image and settings are kept — try again shortly.'
    );
  }
  if (/failed to fetch|networkerror|network request failed/i.test(raw)) {
    return (
      'The request could not reach the analysis service. ' +
      'Check your connection; your image and settings are kept.'
    );
  }
  return raw || fallback;
}

/** One labeled row of a damage-assessment narrative. */
export interface DamageNarrativeRow {
  label: string;
  text: string;
}

/** Labeled narrative rows for one damage assessment, shared by the
 *  dashboard card and the PDF brief so both read identically.
 *  Structured fields lead; older payloads without them fall back to
 *  the rationale and uncertainty alone. Provenance (finding and
 *  evidence ids) is never part of these rows — it renders in
 *  technical details and exports. */
export function damageNarrativeRows(assessment: {
  observed_condition?: string;
  rationale: string;
  uncertainty_note: string;
  recommended_verification?: string;
}): DamageNarrativeRow[] {
  const rows: DamageNarrativeRow[] = [];
  const observed = (assessment.observed_condition ?? '').trim();
  if (observed) rows.push({ label: 'Observed condition', text: observed });
  const rationale = assessment.rationale.trim();
  if (rationale) rows.push({ label: 'Assessment', text: rationale });
  const uncertainty = assessment.uncertainty_note.trim();
  if (uncertainty) rows.push({ label: 'Uncertainty', text: uncertainty });
  const verification = (assessment.recommended_verification ?? '').trim();
  if (verification) {
    rows.push({ label: 'Recommended verification', text: verification });
  }
  return rows;
}

/** Human-readable evidence label per finding id, numbered in dossier
 *  order ("Visual Observation 1", ...). Every view must build this from
 *  the same finding list so numbering maps to the correct findings. */
export function findingDisplayNames(
  findings: { finding_id: string }[],
): Map<string, string> {
  return new Map(
    findings.map((f, i) => [f.finding_id, `Visual Observation ${i + 1}`]),
  );
}

/** Replace exact finding-id tokens in backend text with their display
 *  names. Only standalone tokens match: ids embedded in longer
 *  references (such as `verify-finding-<id>` task ids) are left
 *  untouched. Unknown ids pass through unchanged. */
export function resolveFindingReferences(
  text: string,
  names: Map<string, string>,
): string {
  if (!text || names.size === 0) return text;
  const ids = [...names.keys()].sort((a, b) => b.length - a.length);
  let out = text;
  for (const id of ids) {
    const escaped = id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const pattern = new RegExp(
      `(?<![A-Za-z0-9_-])${escaped}(?![A-Za-z0-9_-])`,
      'g',
    );
    out = out.replace(pattern, names.get(id) as string);
  }
  return out;
}

/** One pipeline stage for the Analysis Summary. */
export interface AnalysisStageSummary {
  stage: string;
  status: 'completed' | 'partial' | 'failed' | 'skipped';
  summary: string;
}

/** Concise per-stage summaries (Visual Analysis, Segmentation, Impact
 *  Assessment, Reporting) shared by the dashboard and the PDF brief.
 *  Derived from the agent trail plus dossier-level outcomes, so stages
 *  read correctly even when the trail is unavailable. */
export function analysisStageSummaries(input: {
  agent_trail: { agent: string; status: string }[];
  findings_count: number;
  segmentations: { status: string; detection_count: number }[];
  vision_workflow_status: string;
  vision_source: string;
  incident_status: string;
  concerns_count: number;
  actions_count: number;
}): AnalysisStageSummary[] {
  const trailStatus = (agent: string): string | null =>
    input.agent_trail.find((t) => t.agent === agent)?.status ?? null;

  const vision =
    trailStatus('vision') === 'failed'
      ? {
          stage: 'Visual Analysis',
          status: 'failed' as const,
          summary: 'Visual analysis failed; no observations recorded.',
        }
      : {
          stage: 'Visual Analysis',
          status: 'completed' as const,
          summary:
            `${plural(input.findings_count, 'visual observation')} recorded` +
            (input.vision_source === 'cached_reuse'
              ? ' (reused earlier analysis)'
              : ''),
        };

  const okLayers = input.segmentations.filter((s) => s.status === 'ok');
  const okRegions = okLayers.reduce((n, s) => n + s.detection_count, 0);
  let segmentation: AnalysisStageSummary;
  if (input.vision_workflow_status === 'completed') {
    segmentation = {
      stage: 'Segmentation',
      status: 'completed',
      summary:
        okLayers.length > 0
          ? `${plural(okRegions, 'region')} across ${plural(okLayers.length, 'category', 'categories')}`
          : 'Ran cleanly; no matching regions identified',
    };
  } else if (input.vision_workflow_status === 'partial') {
    segmentation = {
      stage: 'Segmentation',
      status: 'partial',
      summary: `${plural(okRegions, 'region')} measured; some categories unavailable`,
    };
  } else if (input.segmentations.length > 0) {
    segmentation = {
      stage: 'Segmentation',
      status: 'partial',
      summary: 'Segmentation produced no usable regions; visual observations only',
    };
  } else {
    segmentation = {
      stage: 'Segmentation',
      status: 'skipped',
      summary: 'No segmentation targets identified',
    };
  }

  const impactTrail = trailStatus('impact');
  let impact: AnalysisStageSummary;
  if (impactTrail === 'failed') {
    impact = {
      stage: 'Impact Assessment',
      status: 'failed',
      summary: 'Impact step failed; concerns and damage reads unavailable',
    };
  } else if (
    impactTrail === 'ok' ||
    input.incident_status === 'completed' ||
    input.concerns_count + input.actions_count > 0
  ) {
    impact = {
      stage: 'Impact Assessment',
      status: 'completed',
      summary:
        input.concerns_count > 0
          ? `${plural(input.concerns_count, 'concern')}, ${plural(input.actions_count, 'verification action')} prepared`
          : `${plural(input.actions_count, 'verification action')} prepared; no concerns identified`,
    };
  } else {
    impact = {
      stage: 'Impact Assessment',
      status: 'failed',
      summary: 'Impact step failed; concerns and damage reads unavailable',
    };
  }

  const reporting: AnalysisStageSummary = {
    stage: 'Reporting',
    status: 'completed',
    summary: 'Incident brief assembled',
  };
  return [vision, segmentation, impact, reporting];
}

const STAGE_LABEL: Record<string, string> = {
  vision: 'Visual Analysis',
  impact: 'Impact Assessment',
  reporting: 'Reporting',
};

/** Raw diagnostics for the expandable Technical Details: per-stage
 *  timings and notes, the analysis source (including any cache id),
 *  and the workflow/assessment outcomes. */
export function analysisTechnicalDetails(input: {
  agent_trail: {
    agent: string;
    status: string;
    duration_s: number;
    notes: string;
  }[];
  vision_source: string;
  analysis_ref?: string | null;
  vision_workflow_status: string;
  incident_status: string;
}): string[] {
  const lines = input.agent_trail.map(
    (t) =>
      `${STAGE_LABEL[t.agent] ?? titleWord(t.agent)}: ${t.status}, ` +
      `${t.duration_s.toFixed(2)}s${t.notes ? ` — ${t.notes}` : ''}`,
  );
  lines.push(
    input.vision_source === 'cached_reuse'
      ? `Source: reused cached analysis${input.analysis_ref ? ` ${input.analysis_ref}` : ''} (no model calls)`
      : 'Source: new image analysis',
  );
  lines.push(
    `Image analysis ${workflowStatusLabel(input.vision_workflow_status)}; ` +
      `assessment ${assessmentStatusLabel(input.incident_status)}.`,
  );
  return lines;
}

/** Readable labels for information-gap topics (backend keys stay raw
 *  in the API and JSON export). Unknown topics degrade to titled
 *  words, never raw snake_case. */
const GAP_TOPIC_LABELS: Record<string, string> = {
  capture_time: 'Capture time',
  incident_location: 'Incident location',
  accessibility: 'Route accessibility',
  water_conditions: 'Water conditions',
  structural_condition: 'Structural condition',
  slope_conditions: 'Slope conditions',
  fire_conditions: 'Fire conditions',
  human_exposure: 'Human exposure',
  hazard_assessment: 'Hazard assessment',
  ground_truth: 'Field confirmation',
};

export function gapTopicLabel(topic: string): string {
  return (
    GAP_TOPIC_LABELS[topic] ??
    topic
      .split('_')
      .map((w) => titleWord(w))
      .join(' ')
  );
}

/** One grouped set of verification needs for display. */
export interface GapGroup {
  heading: string;
  items: { topic: string; detail: string; status: string }[];
}

const SCENE_GAP_TOPICS = new Set([
  'water_conditions',
  'structural_condition',
  'slope_conditions',
  'human_exposure',
  'hazard_assessment',
  'accessibility',
]);

/** Group gaps into scene conditions vs report context for display.
 *  The location gap is excluded: geographic context renders in its
 *  own block. Backend order is preserved within each group. */
export function groupInformationGaps(
  gaps: { topic: string; detail: string; status: string }[],
): GapGroup[] {
  const scene = gaps.filter(
    (g) => g.topic !== 'incident_location' && SCENE_GAP_TOPICS.has(g.topic),
  );
  const other = gaps.filter(
    (g) =>
      g.topic !== 'incident_location' &&
      !SCENE_GAP_TOPICS.has(g.topic) &&
      g.topic !== 'capture_time' &&
      g.topic !== 'ground_truth',
  );
  const context = gaps.filter(
    (g) => g.topic === 'capture_time' || g.topic === 'ground_truth',
  );
  const groups: GapGroup[] = [];
  if (scene.length + other.length > 0) {
    groups.push({ heading: 'Scene conditions to verify', items: [...scene, ...other] });
  }
  if (context.length > 0) {
    groups.push({ heading: 'Report context to confirm', items: context });
  }
  return groups;
}

/** Shorten a long internal id/hash for display; full value stays in
 *  `title` attributes, technical-details sections, and exports. */
export function shortId(id: string): string {
  if (id.length <= 20) return id;
  const [head, ...rest] = id.split(':');
  const tail = rest.join(':');
  if (tail) return `${head}:${tail.slice(0, 8)}…${tail.slice(-6)}`;
  if (head.length > 20) return `${id.slice(0, 12)}…${id.slice(-6)}`;
  return `${id.slice(0, 14)}…`;
}
