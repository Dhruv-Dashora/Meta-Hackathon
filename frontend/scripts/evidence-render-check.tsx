// Focused regression check for evidence rendering (runs under Node
// with react-dom/server — no browser, no new dependencies).
//
// Guards the EvidenceViewer crash where the evidence object was passed
// through the reserved React `ref` prop (stripped before it reaches the
// component, so `ref.evidence_id` threw a TypeError and blanked the
// app). Rendering the real component here throws the same way if the
// reserved-prop misuse ever returns.
import { renderToString } from 'react-dom/server';
import EvidenceViewer from '../src/components/EvidenceViewer';
import PrintBrief from '../src/export/PrintBrief';
import type { IncidentDossier } from '../src/types/incident';
import { ErrorBoundary } from '../src/ui/ErrorBoundary';
import { actionTitle, friendlyErrorMessage } from '../src/ui/format';

function assertOk(condition: unknown, message: string): void {
  if (!condition) {
    throw new Error(`assertion failed: ${message}`);
  }
}

const EVIDENCE_ID =
  'sha256:9f2c4a1b7e3d5f6a8c0b1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e';

const refs = [
  {
    evidence_id: EVIDENCE_ID,
    modality: 'image' as const,
    uri_or_hash: EVIDENCE_ID,
    captured_at: null,
  },
];

// 1. Real evidence metadata renders (id preserved, short hash shown).
const html = renderToString(<EvidenceViewer refs={refs} />);
assertOk(html.includes('image'), 'modality must render');
assertOk(
  html.includes('sha256:9f2c4a1b'),
  'short hash of the real evidence_id must render',
);
assertOk(html.includes(EVIDENCE_ID), 'full id must stay in attributes');
assertOk(html.includes('Copy'), 'copy control must render');

// 2. Genuinely empty evidence renders the empty state, without throwing.
const empty = renderToString(<EvidenceViewer refs={[]} />);
assertOk(
  empty.includes('No evidence references available.'),
  'empty refs must render the empty state',
);

// 3. Missing/null entries never crash and invent no placeholder ids.
const sparse = renderToString(
  <EvidenceViewer refs={[null, undefined] as unknown as typeof refs} />,
);
assertOk(
  sparse.includes('No evidence references available.'),
  'null entries must fall back to the empty state',
);
assertOk(
  !sparse.includes('evidence-0'),
  'fallback React keys must never leak into the UI',
);

// 4. Partial metadata degrades honestly (no crash, no invented id).
const partial = renderToString(
  <EvidenceViewer
    refs={[
      { evidence_id: '', modality: 'image', uri_or_hash: '' } as unknown as (typeof refs)[number],
    ]}
  />,
);
assertOk(
  partial.includes('unavailable'),
  'missing hashes must render as unavailable',
);

// 5. The error boundary renders children on the healthy path.
const healthy = renderToString(
  <ErrorBoundary>
    <p>healthy child</p>
  </ErrorBoundary>,
);
assertOk(healthy.includes('healthy child'), 'boundary must pass children through');

// 6. Long-content print brief: complete instructions, locations, and
// uncertainty render verbatim — never cut mid-word, ellipsized, or
// dropped — with full technical ids in provenance.
const LONG_LOCATION =
  'lower third of the image along the northern roadside embankment directly beneath ' +
  'the fractured concrete retaining wall and above the partially obstructed mountain ' +
  'roadway where loose sediment has accumulated across both travel lanes near the bend marker';
const LONG_TASK =
  'Determine whether the embankment has lost structural support along the northern roadside edge; ' +
  'check whether the roadway below remains passable for ground teams and supplies in both directions; ' +
  'confirm the extent of sediment accumulation across the travel lanes near the bend marker';
const LONG_UNKNOWN =
  'Whether the embankment will continue to move under additional rainfall is unknown and the stability ' +
  'of the fractured retaining wall above the roadway cannot be confirmed from this single image alone';
const LONG_FINDING_ID = 'vision-1-abcdef123456';
const SECOND_FINDING_ID = 'vision-2-46b9bc73f215';

const briefDossier: IncidentDossier = {
  incident_id: 'img-longcontent',
  image: {
    width: 640,
    height: 480,
    mime_type: 'image/png',
    evidence_id: EVIDENCE_ID,
  },
  vision_source: 'fresh_analysis',
  vision_workflow_status: 'completed',
  incident_status: 'completed',
  situation_summary: {
    headline: 'Possible slope debris (roadside embankment); extent unconfirmed.',
    observed: `Observed roadside embankment: ${LONG_LOCATION}.`,
    unknowns: LONG_UNKNOWN,
  },
  findings: [
    {
      finding_id: LONG_FINDING_ID,
      label: 'roadside embankment',
      description:
        `Observed: embankment slumping toward the road.\n` +
        `Affected feature: roadside embankment\n` +
        `Location in image: ${LONG_LOCATION}`,
      confidence: { value: 0.8, scale: '0-1', calibrated: false },
      uncertainty_notes: LONG_UNKNOWN,
      evidence_refs: [
        {
          evidence_id: EVIDENCE_ID,
          modality: 'image',
          uri_or_hash: EVIDENCE_ID,
          captured_at: null,
        },
      ],
      observed_at: null,
      analyzed_at: null,
      review_status: 'pending',
    },
    {
      finding_id: SECOND_FINDING_ID,
      label: 'people near road',
      description: 'Observed: people near the road.',
      confidence: { value: 0.6, scale: '0-1', calibrated: false },
      uncertainty_notes: 'Number and condition of any people are unconfirmed.',
      evidence_refs: [
        {
          evidence_id: EVIDENCE_ID,
          modality: 'image',
          uri_or_hash: EVIDENCE_ID,
          captured_at: null,
        },
      ],
      observed_at: null,
      analyzed_at: null,
      review_status: 'pending',
    },
  ],
  finding_groups: [],
  information_gaps: [
    {
      topic: 'capture_time',
      detail: 'Image capture time is not recorded.',
      why_matters: 'Recency determines how urgently findings need review.',
      status: 'unknown',
    },
    {
      topic: 'water_conditions',
      detail: 'Water depth, extent, and trend are not measured.',
      why_matters: 'Determines crossing safety and nearby exposure.',
      status: 'unknown',
    },
    {
      topic: 'human_exposure',
      detail:
        'Number, condition, and exact location of any people are unconfirmed.',
      why_matters: 'People safety takes precedence over other checks.',
      status: 'unknown',
    },
    {
      topic: 'incident_location',
      detail: 'Location is operator-provided and not independently verified.',
      why_matters: 'Follow-up cannot be directed without a location.',
      status: 'unverified',
    },
  ],
  segmentation_summary: [],
  segmentations: [],
  observed_hazards: [],
  exposure_concerns: [],
  damage_assessments: [
    {
      assessment_id: 'dmg-1',
      feature: 'road',
      target_label: 'roadside embankment',
      basis_finding_ids: [LONG_FINDING_ID],
      basis_evidence_ids: [EVIDENCE_ID],
      category: 'possible_damage',
      rationale: `Provisional read of the slumping fill with qualifiers kept (${LONG_LOCATION}).`,
      provisional: true,
      uncertainty_note: LONG_UNKNOWN,
      observed_condition: `Mud and sediment visible around the roadside embankment (${LONG_LOCATION}).`,
      condition_class: 'surrounding_material',
      recommended_verification:
        'Confirm whether the embankment itself is damaged; surrounding mud or debris does not establish structural damage.',
    },
  ],
  access_priorities: [
    {
      attention_id: 'acc-1',
      priority: 'high',
      basis_finding_ids: [LONG_FINDING_ID],
      basis_evidence_ids: [EVIDENCE_ID],
      rationale: 'Route access past the outlined region is unconfirmed.',
      requires_human_review: true,
    },
  ],
  review_priorities: [],
  degraded_sections: ['Access assessment'],
  rescue_priorities: [
    {
      attention_id: 'att-2',
      priority: 'medium',
      basis_finding_ids: [SECOND_FINDING_ID],
      basis_evidence_ids: [EVIDENCE_ID],
      rationale: `Finding '${SECOND_FINDING_ID}' mentions people with a plausible hazard context ('people near the road'); exposure is not established. Requires timely human verification.`,
      requires_human_review: true,
    },
  ],
  geo_context: {
    status: 'unavailable',
    location_label: '',
    latitude: null,
    longitude: null,
    geojson_feature_count: null,
    provenance: 'operator-provided, unverified',
    note: 'No geospatial context was provided with this image.',
  },
  uncertainty_notes: [LONG_UNKNOWN],
  verification_actions: [
    {
      action_id: 'verify-finding-long',
      action: `Human review of the roadside embankment: ${LONG_TASK}.`,
      reason: 'AI observation is unverified until human review.',
      title: 'Roadside Embankment Assessment',
      priority: 'high',
      related_finding_ids: [LONG_FINDING_ID],
      what: `${LONG_TASK} (${LONG_FINDING_ID}).`,
      why_operational: 'Road access determines whether ground teams can move.',
      unknown: LONG_UNKNOWN,
      method: 'Compare with a second image angle of the same scene.',
      priority_reason: 'Risk-flagged observation needs timely confirmation.',
    },
    {
      action_id: 'verify-geo-context',
      action: 'Obtain operator location context to ground follow-up.',
      reason: 'No geospatial context was provided with this image.',
      title: 'Location Context Request',
      priority: 'low',
      related_finding_ids: [],
      what: 'Ask the image source for a location label or coordinates.',
      why_operational: 'Location context focuses verification on the right area.',
      unknown: 'Where this image was taken.',
      method: 'Ask the image source for location or time details.',
      priority_reason: 'Helpful context; not blocking for image review.',
    },
  ],
  evidence_ledger: [
    { evidence_id: EVIDENCE_ID, modality: 'image', source: 'upload' },
  ],
  agent_trail: [
    {
      agent: 'vision',
      status: 'ok',
      duration_s: 1.23,
      notes: '2 findings, 1 prompt, status completed.',
    },
    {
      agent: 'impact',
      status: 'ok',
      duration_s: 0.04,
      notes: '0 concerns, 2 actions, 1 damage read.',
    },
    {
      agent: 'reporting',
      status: 'ok',
      duration_s: 0.01,
      notes: 'incident_status completed.',
    },
  ],
  warnings: [],
};

const brief = renderToString(<PrintBrief dossier={briefDossier} imageUrl={null} />);
assertOk(
  brief.includes('lower third of the image') && brief.includes('near the bend marker'),
  'long locations must render head and tail verbatim',
);
assertOk(
  brief.includes('accumulation across the travel lanes near the bend marker'),
  'long compound instructions must render in full',
);
assertOk(
  brief.includes('cannot be confirmed from this single image alone'),
  'long uncertainty text must render in full',
);
assertOk(
  brief.includes('Roadside Embankment Assessment'),
  'structured action title must render',
);
assertOk(
  brief.includes('verify-finding-long') && brief.includes('verify-geo-context'),
  'every action (not just the top three) must print with its task reference',
);
assertOk(
  brief.includes(EVIDENCE_ID) && brief.includes(LONG_FINDING_ID),
  'full technical ids must stay in the provenance section',
);
assertOk(!brief.includes('…'), 'print output must never contain ellipsis truncation');
assertOk(
  brief.includes('Observed condition:') &&
    brief.includes('Mud and sediment visible around the roadside embankment') &&
    brief.includes('near the bend marker'),
  'structured observed condition must print verbatim',
);
assertOk(
  brief.includes('Recommended verification:') &&
    brief.includes('does not establish structural damage'),
  'structured verification guidance must print',
);

// 9. Report presentation: numbered observation names (never raw ids in
// narrative), grouped verification needs with readable labels, and a
// stage-based analysis summary with separate technical details.
assertOk(
  brief.includes('Visual Observation 1') &&
    brief.includes('Visual Observation 2'),
  'observations must carry dossier-order numbers',
);
assertOk(
  brief.includes('(Visual Observation 1)') &&
    !brief.includes(`bend marker (${LONG_FINDING_ID})`),
  'task text must resolve finding ids to display names',
);
assertOk(
  !brief.includes(`Finding '${SECOND_FINDING_ID}'`) &&
    brief.includes('Visual Observation 2'),
  'urgency rationales must resolve finding ids to display names',
);
assertOk(
  brief.includes('Visual Observation 1 — roadside embankment') &&
    brief.includes('Visual Observation 2 — people near road'),
  'supporting-observation lines must use numbered names',
);
assertOk(
  brief.includes(LONG_FINDING_ID) && brief.includes(SECOND_FINDING_ID),
  'full finding ids must stay in the provenance mapping',
);
assertOk(
  brief.includes('Analysis summary') &&
    brief.includes('Visual Analysis') &&
    brief.includes('Segmentation') &&
    brief.includes('Impact Assessment') &&
    brief.includes('Reporting') &&
    brief.includes('[Completed]'),
  'analysis stages must summarize with clear statuses',
);
assertOk(
  brief.includes('Technical details') &&
    brief.includes('1.23s') &&
    brief.includes('2 findings, 1 prompt, status completed.'),
  'timings and diagnostics must stay in technical details',
);
assertOk(
  brief.includes('unverified information') &&
    brief.includes('Scene conditions to verify') &&
    brief.includes('Report context to confirm'),
  'location and verification needs must group separately',
);
assertOk(
  brief.includes('Capture time') &&
    brief.includes('Human exposure') &&
    brief.includes('Water conditions') &&
    !brief.includes('capture_time') &&
    !brief.includes('human_exposure') &&
    !brief.includes('water_conditions'),
  'gap topics must render as readable labels',
);
assertOk(
  !brief.includes('People safety takes precedence over other checks.') &&
    !brief.includes('not independently verified'),
  'repetitive gap explanations and duplicate location text must go',
);
assertOk(
  brief.includes('Degraded sections: Access assessment'),
  'degraded sections must print in technical provenance',
);

// 7. Action headings prefer the backend title; the fallback never cuts
// mid-word.
assertOk(
  actionTitle({ title: 'Roadside Embankment Assessment', what: LONG_TASK, action: '' }) ===
    'Roadside Embankment Assessment',
  'backend title must win over task text',
);
assertOk(
  actionTitle({ what: 'Check the road.', action: '' }) === 'Check the road.',
  'short tasks must render whole',
);
const fallback = actionTitle({ what: LONG_TASK, action: '' });
assertOk(fallback.endsWith('…'), 'long untitled tasks must mark continuation');
const stem = fallback.slice(0, -1);
assertOk(
  LONG_TASK.startsWith(stem) && LONG_TASK[stem.length] === ' ',
  'fallback shortening must land on a word boundary',
);

// 8. Failure copy stays friendly for timeouts and outages while
// unknown errors keep their raw diagnostic text.
const sparkTimeout = new Error(
  'API 502: /api/disaster-response/analyze-and-segment — ' +
    '{"detail":"vision_failed: muse_spark_timeout: Muse Spark request timed out."}',
);
const friendly = friendlyErrorMessage(sparkTimeout, 'Analysis failed.');
assertOk(
  friendly.includes('timed out') && friendly.includes('kept'),
  'spark timeouts must map to friendly retry guidance',
);
assertOk(
  !friendly.includes('muse_spark_timeout') && !friendly.includes('API 502'),
  'friendly text must not leak raw codes or paths',
);
assertOk(
  friendlyErrorMessage(new Error('API 502: /api/x'), 'X').includes(
    'temporarily unavailable',
  ),
  'bare 502s must map to the outage message',
);
assertOk(
  friendlyErrorMessage(new Error('targets_too_many: at most 3'), 'X').includes(
    'targets_too_many',
  ),
  'unmapped errors must keep raw detail',
);
assertOk(
  friendlyErrorMessage(new Error('Failed to fetch'), 'X').includes(
    'could not reach',
  ),
  'network failures must map to the connectivity message',
);

console.log('evidence-render-check: 9 sections passed');
