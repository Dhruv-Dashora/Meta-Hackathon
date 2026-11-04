// Print-only incident brief: a linear, conditional PDF document rendered
// from the in-hand dossier. Pure presentation — zero network or model
// calls. The caller wraps this in `.print-only`; screen keeps the
// interactive dashboard. Every action prints in full (instructions,
// unknowns, method); labels lead the narrative while full technical
// ids stay in the provenance section. Region geometry alone remains
// JSON-only.
import { parseDescription } from '../components/FindingCard';
import type {
  ActionPriority,
  DamageCategory,
  IncidentDossier,
  VerificationAction,
} from '../types/incident';
import type { Finding } from '../types/sentinel';
import { CONFIDENCE_HELP_TEXT } from '../ui/ConfidenceHelp';
import {
  actionTitle,
  analysisStageSummaries,
  analysisTechnicalDetails,
  assessmentStatusLabel,
  damageNarrativeRows,
  ensurePeriod,
  findingDisplayNames,
  gapTopicLabel,
  groupInformationGaps,
  plural,
  resolveFindingReferences,
  titleWord,
  workflowStatusLabel,
} from '../ui/format';

const PRIORITY_ORDER: Record<ActionPriority, number> = {
  high: 0,
  medium: 1,
  low: 2,
};

const DAMAGE_LABEL: Record<DamageCategory, string> = {
  no_visible_damage: 'No visible damage',
  possible_damage: 'Possible damage',
  apparent_major_damage: 'Apparent major damage',
  cannot_assess: 'Cannot assess',
};

// Compound "do A; do B" / numbered tasks as sequential steps.
// Presentational only — wording is never altered.
function splitSteps(text: string): string[] {
  const numbered = text
    .split(/\s*(?=\d+\.\s)/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (numbered.length > 1 && numbered.every((s) => /^\d+\.\s/.test(s))) {
    return numbered.map((s) => s.replace(/^\d+\.\s/, ''));
  }
  const parts = text
    .split(/\s*;\s*/)
    .map((s) => s.trim())
    .filter(Boolean);
  if (parts.length > 1 && parts.every((s) => s.length > 3)) return parts;
  return [text.trim()];
}

function printSummaryStatus(status: string, count: number): string {
  if (status === 'ok') return plural(count, 'region');
  if (status === 'zero_matches') return 'No matching regions identified';
  if (status === 'failed') return 'Unavailable';
  return 'Not analyzed';
}

// Capture time comes from the evidence, recorded at capture — distinct
// from when this brief was generated. Missing timestamps are stated,
// never guessed.
function captureTimes(dossier: IncidentDossier): string[] {
  const times = new Set<string>();
  for (const f of dossier.findings) {
    if (f.observed_at) times.add(f.observed_at);
    for (const ref of f.evidence_refs) {
      if (ref.captured_at) times.add(ref.captured_at);
    }
  }
  return [...times];
}

function Section({
  n,
  title,
  children,
}: {
  n: number;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section aria-label={title}>
      <h3 className="print-section-title">
        {n}. {title}
      </h3>
      {children}
    </section>
  );
}

// Compact observation item for print: label, status, verbatim
// observation, image-relative location when present, score.
// Uncertainty and provenance collapse to one line each.
function BriefFinding({
  finding,
  sequence,
}: {
  finding: Finding;
  sequence?: number;
}) {
  const { observed, feature, location } = parseDescription(
    finding.description ?? '',
  );
  return (
    <li className="print-item">
      <p>
        <strong>
          {sequence != null ? `Visual Observation ${sequence} — ` : ''}
          {finding.label}
        </strong>{' '}
        — {titleWord(finding.review_status.replace(/_/g, ' '))}
        {', '}
        Confidence Score {String(finding.confidence.value)}
      </p>
      {observed && <p>{observed}</p>}
      {feature && (
        <p>
          Affected feature: {feature}
        </p>
      )}
      {location && <p>Location in image: {location}</p>}
      {finding.uncertainty_notes && (
        <p className="print-dim">Uncertainty: {finding.uncertainty_notes}</p>
      )}
    </li>
  );
}

function TopAction({
  action,
  names,
}: {
  action: VerificationAction;
  names?: Map<string, string>;
}) {
  const resolve = (text: string) =>
    names ? resolveFindingReferences(text, names) : text;
  const task = resolve(action.what || action.action);
  const steps = splitSteps(task);
  // Detailed actions may run long (compound steps), so they paginate
  // naturally instead of holding together like compact items.
  return (
    <li className="print-item print-flow">
      <p>
        <strong>
          [{titleWord(action.priority)} Priority] {actionTitle(action)}
        </strong>
      </p>
      {steps.length > 1 ? (
        <ol className="print-steps">
          {steps.map((step, i) => (
            <li key={`${i}-${step.slice(0, 24)}`}>{step}</li>
          ))}
        </ol>
      ) : (
        actionTitle(action) !== task.trim() && <p>What to check: {task}</p>
      )}
      <p>Why it matters: {resolve(action.why_operational || action.reason)}</p>
      {action.unknown && <p>Unknown: {resolve(action.unknown)}</p>}
      {action.method && (
        <p>Suggested method (requires local judgment): {resolve(action.method)}</p>
      )}
      <p className="print-dim">{resolve(action.priority_reason)}</p>
      <p className="print-dim">Task reference: {action.action_id}</p>
    </li>
  );
}

export default function PrintBrief({
  dossier,
  imageUrl,
}: {
  dossier: IncidentDossier;
  imageUrl: string | null;
}) {
  const generatedAt = new Date().toLocaleString();
  const ranked = [...dossier.verification_actions].sort(
    (a, b) => PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority],
  );
  const labels = new Map(dossier.findings.map((f) => [f.finding_id, f.label]));
  const names = findingDisplayNames(dossier.findings);
  const sequence = new Map<string, number>(
    dossier.findings.map((f, i) => [f.finding_id, i + 1]),
  );
  // Numbered observation reference ("Visual Observation 2 — label"),
  // falling back to the bare label for unknown ids.
  const observationRef = (id: string): string => {
    const name = names.get(id);
    const label = labels.get(id) ?? 'observation';
    return name ? `${name} — ${label}` : label;
  };
  const taskById = new Map(
    dossier.verification_actions.map((a) => [a.action_id, actionTitle(a)]),
  );
  const byId = new Map<string, Finding>(
    dossier.findings.map((f) => [f.finding_id, f]),
  );
  const captured = captureTimes(dossier);
  const partial = dossier.incident_status !== 'completed';
  const okLayers = dossier.segmentations.filter((s) => s.status === 'ok');
  const okRegions = okLayers.reduce((n, s) => n + s.detections.length, 0);

  let section = 0;
  const next = () => {
    section += 1;
    return section;
  };

  return (
    <div className="print-brief">
      <div className="print-cover">
        <p className="print-kicker">
          Himalayan Sentinel — incident brief (provisional)
        </p>
        <h2 className="print-title">Incident {dossier.incident_id}</h2>
        <p className="print-meta">
          Brief generated {generatedAt}. Assessment{' '}
          {assessmentStatusLabel(dossier.incident_status)}; image analysis{' '}
          {workflowStatusLabel(dossier.vision_workflow_status)} (
          {dossier.vision_source === 'cached_reuse'
            ? 'reused results'
            : 'new analysis'}
          ). Human verification required; nothing here is confirmed.
        </p>
        <dl className="print-facts">
          <div>
            <dt>Source image</dt>
            <dd>
              {dossier.image.width}×{dossier.image.height} px,{' '}
              {dossier.image.mime_type}
            </dd>
          </div>
          <div>
            <dt>Image captured</dt>
            <dd>
              {captured.length > 0
                ? captured.join('; ')
                : 'Not recorded (capture time unknown)'}
            </dd>
          </div>
          <div>
            <dt>Contents</dt>
            <dd>
              {plural(dossier.findings.length, 'visual observation')},{' '}
              {plural(dossier.exposure_concerns.length, 'conditional concern')}
              , {plural(ranked.length, 'verification action')}.
            </dd>
          </div>
          <div>
            <dt>Location</dt>
            <dd>
              {dossier.geo_context.status === 'provided'
                ? `Operator-provided, unverified${dossier.geo_context.location_label ? `: ${dossier.geo_context.location_label}` : ''}`
                : 'Unavailable — image is not placed on a map'}
            </dd>
          </div>
        </dl>
        {partial && (
          <p className="print-alert">
            Partial analysis: one or more steps failed or were skipped. Gaps
            are listed below; treat missing sections as unknown, not as
            all-clear.
          </p>
        )}
      </div>

      <Section n={next()} title="Executive summary">
        <p>
          <strong>{dossier.situation_summary.headline}</strong>
        </p>
        <p>
          <strong>Observed:</strong> {dossier.situation_summary.observed}
        </p>
        <p>
          <strong>Unknown:</strong> {dossier.situation_summary.unknowns}
        </p>
        {dossier.warnings.length > 0 && (
          <ul className="print-list">
            {dossier.warnings.map((w) => (
              <li key={w}>Warning: {w}</li>
            ))}
          </ul>
        )}
      </Section>

      <Section n={next()} title="Evidence image">
        {imageUrl ? (
          <figure className="print-figure">
            <img
              src={imageUrl}
              alt="Incident evidence photograph"
              className="print-image"
            />
            <figcaption>
              {dossier.segmentations.length === 0 &&
                'No detected regions were produced (visual observations only).'}
              {dossier.segmentations.length > 0 &&
                `${plural(dossier.segmentations.length, 'detection category', 'detection categories')} (${plural(okRegions, 'region')} across ${plural(okLayers.length, 'successful category', 'successful categories')}). Outlined regions are visual guides only and never confirm an observation.`}
            </figcaption>
          </figure>
        ) : (
          <p>No image preview available in this brief.</p>
        )}
        {dossier.segmentation_summary.length > 0 && (
          <ul className="print-list">
            {dossier.segmentation_summary.map((s) => (
              <li key={s.prompt}>
                “{s.prompt}”: {printSummaryStatus(s.status, s.detection_count)}
              </li>
            ))}
          </ul>
        )}
      </Section>

      {ranked.length > 0 && (
        <Section n={next()} title="Verification priorities">
          <p className="print-dim">
            Manual checklist in priority order — complete each item in
            person. Methods are suggestions requiring local judgment.
          </p>
          <ol className="print-list">
            {ranked.map((a) => (
              <TopAction key={a.action_id} action={a} names={names} />
            ))}
          </ol>
        </Section>
      )}

      {dossier.damage_assessments.length > 0 && (
        <Section n={next()} title="Provisional damage assessment">
          <p className="print-dim">
            Provisional observations linked to evidence, not engineering
            findings. “No visible damage” does not confirm safety.
          </p>
          <ul className="print-list">
            {dossier.damage_assessments.map((d) => (
              <li key={d.assessment_id} className="print-item">
                <p>
                  <strong>
                    [Provisional] {d.target_label || d.feature} —{' '}
                    {DAMAGE_LABEL[d.category]}
                  </strong>
                </p>
                {damageNarrativeRows(d).map((row) => (
                  <p
                    key={row.label}
                    className={row.label === 'Assessment' ? undefined : 'print-dim'}
                  >
                    <strong>{`${row.label}:`}</strong> {row.text}
                  </p>
                ))}
                {d.basis_finding_ids.length > 0 && (
                  <p className="print-dim">
                    Supporting observations:{' '}
                    {d.basis_finding_ids.map(observationRef).join('; ')}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {dossier.rescue_priorities.length > 0 && (
        <Section n={next()} title="Human-exposure assessment">
          <p className="print-dim">
            Urgency of human review — never rescue orders. Every item
            requires human review.
          </p>
          <ul className="print-list">
            {dossier.rescue_priorities.map((r) => (
              <li key={r.attention_id} className="print-item">
                <p>
                  <strong>[{titleWord(r.priority)} Review Priority]</strong>{' '}
                  {resolveFindingReferences(r.rationale, names)}
                </p>
                {r.basis_finding_ids.length > 0 && (
                  <p className="print-dim">
                    Supporting observations:{' '}
                    {r.basis_finding_ids.map(observationRef).join('; ')}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section n={next()} title="Observed hazards and evidence">
        {dossier.observed_hazards.length > 0 && (
          <ul className="print-list">
            {dossier.observed_hazards.map((h) => (
              <li key={h.hazard_id}>
                {h.summary}
                {h.finding_ids.length > 0 && (
                  <span className="print-dim">
                    {' '}
                    (Linked observations:{' '}
                    {h.finding_ids.map(observationRef).join('; ')})
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
        {dossier.findings.length === 0 ? (
          <p>No visual observations identified in this image.</p>
        ) : (
          <>
            <p className="print-dim">{CONFIDENCE_HELP_TEXT}</p>
            {dossier.finding_groups.length > 0 ? (
              dossier.finding_groups.map((g) => (
                <div key={g.group_id}>
                  <h4 className="print-subhead">{g.title}</h4>
                  <ul className="print-list">
                    {g.finding_ids.map(
                      (fid) =>
                        byId.has(fid) && (
                          <BriefFinding
                            key={fid}
                            finding={byId.get(fid)!}
                            sequence={sequence.get(fid)}
                          />
                        ),
                    )}
                  </ul>
                </div>
              ))
            ) : (
              <ul className="print-list">
                {dossier.findings.map((f, i) => (
                  <BriefFinding
                    key={f.finding_id}
                    finding={f}
                    sequence={i + 1}
                  />
                ))}
              </ul>
            )}
          </>
        )}
      </Section>

      {dossier.exposure_concerns.length > 0 && (
        <Section n={next()} title="Conditional exposure concerns">
          <p className="print-dim">
            Unverified inference, not observed facts: each concern states an
            unconfirmed “if” premise and must be verified before any action.
          </p>
          <ul className="print-list">
            {dossier.exposure_concerns.map((c) => (
              <li key={c.concern_id} className="print-item">
                <p>
                  <strong>[Unverified] {c.feature}</strong>
                </p>
                <p>
                  <strong>Unconfirmed premise:</strong>{' '}
                  {ensurePeriod(c.condition)}
                </p>
                <p>
                  <strong>Possible consequence:</strong>{' '}
                  {ensurePeriod(c.concern)}
                </p>
                <p className="print-dim">
                  Linked verification task:{' '}
                  {taskById.get(c.verification_action_id) ??
                    'see Verification priorities'}
                </p>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section n={next()} title="Location & unverified information">
        <h4 className="print-subhead">Location</h4>
        {dossier.geo_context.status === 'provided' ? (
          <p>
            Operator-provided, unverified
            {dossier.geo_context.location_label &&
              `: ${dossier.geo_context.location_label}`}
            {dossier.geo_context.latitude != null &&
              ` (${dossier.geo_context.latitude}, ${dossier.geo_context.longitude})`}
            {dossier.geo_context.geojson_feature_count != null &&
              `, ${plural(dossier.geo_context.geojson_feature_count, 'GeoJSON feature')}`}
            . {dossier.geo_context.note}
          </p>
        ) : (
          <p>
            Unavailable — {dossier.geo_context.note} The image is not
            placed on a map.
          </p>
        )}
        <p className="print-dim">
          Observation locations are positions within the image, not map
          coordinates — they never place the image geographically.
        </p>
        {groupInformationGaps(dossier.information_gaps).map((group) => (
          <div key={group.heading}>
            <h4 className="print-subhead">{group.heading}</h4>
            <ul className="print-list">
              {group.items.map((g) => (
                <li key={g.topic}>
                  <strong>{`[${titleWord(g.status)}] ${gapTopicLabel(g.topic)}`}</strong>
                  {`: ${g.detail}`}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </Section>

      <Section n={next()} title="Analysis summary">
        <ul className="print-list">
          {analysisStageSummaries({
            agent_trail: dossier.agent_trail,
            findings_count: dossier.findings.length,
            segmentations: dossier.segmentations.map((s) => ({
              status: s.status,
              detection_count: s.detections.length,
            })),
            vision_workflow_status: dossier.vision_workflow_status,
            vision_source: dossier.vision_source,
            incident_status: dossier.incident_status,
            concerns_count: dossier.exposure_concerns.length,
            actions_count: dossier.verification_actions.length,
          }).map((s) => (
            <li key={s.stage}>
              <strong>{`${s.stage} [${titleWord(s.status)}]`}</strong>
              {`: ${s.summary}`}
            </li>
          ))}
        </ul>
        <h4 className="print-subhead">Technical details</h4>
        <ul className="print-list">
          {analysisTechnicalDetails({
            agent_trail: dossier.agent_trail,
            vision_source: dossier.vision_source,
            analysis_ref: dossier.analysis_ref,
            vision_workflow_status: dossier.vision_workflow_status,
            incident_status: dossier.incident_status,
          }).map((line, i) => (
            <li key={`${i}-${line.slice(0, 24)}`} className="print-dim">
              {line}
            </li>
          ))}
        </ul>
      </Section>

      <Section n={next()} title="Technical provenance and limitations">
        <ul className="print-list">
          <li>
            Source: {dossier.vision_source === 'cached_reuse' ? 'reused' : 'new'} image
            analysis; analysis {workflowStatusLabel(dossier.vision_workflow_status)}; assessment{' '}
            {assessmentStatusLabel(dossier.incident_status)}.
          </li>
          <li>
            {dossier.geo_context.status === 'provided' ? (
              <>
                Location operator-provided and unverified
                {dossier.geo_context.latitude != null &&
                  ` (${dossier.geo_context.latitude}, ${dossier.geo_context.longitude})`}
                {dossier.geo_context.geojson_feature_count != null &&
                  `, ${plural(dossier.geo_context.geojson_feature_count, 'GeoJSON feature')}`}
                . {dossier.geo_context.note}
              </>
            ) : (
              <>
                Location unavailable — {dossier.geo_context.note} The image
                is not placed on a map.
              </>
            )}
          </li>
          <li>
            Observation locations are positions within the image, not map
            coordinates — they never place the image geographically.
          </li>
          {dossier.uncertainty_notes.map((note, i) => (
            <li key={`${i}-${note.slice(0, 24)}`}>{note}</li>
          ))}
          {dossier.degraded_sections &&
            dossier.degraded_sections.length > 0 && (
              <li>
                {`Degraded sections: ${dossier.degraded_sections.join(', ')} — treat those sections with extra care.`}
              </li>
            )}
          <li>
            Evidence ledger: {plural(dossier.evidence_ledger.length, 'item')}.
          </li>
          {dossier.evidence_ledger.map((e) => (
            <li key={e.evidence_id}>
              <code>{e.evidence_id}</code> — {e.modality} ({e.source})
            </li>
          ))}
          {dossier.findings.length > 0 && (
            <li>
              Observation references:{' '}
              {dossier.findings
                .map(
                  (f) =>
                    `${names.get(f.finding_id)} — ${f.label} (${f.finding_id})`,
                )
                .join('; ')}
            </li>
          )}
          <li>Region geometry is in the JSON export of this report.</li>
        </ul>
        <p className="print-dim">
          Limitations: every assessment here is provisional and unverified;
          confidence scores reflect model assessments, not verified
          probabilities; outlined regions are visual guides only; suggested
          methods require local judgment.
        </p>
      </Section>

      <p className="print-footer">
        End of brief — generated {generatedAt}, capture time listed
        separately above. Full region geometry is in the JSON export of
        this report.
      </p>
    </div>
  );
}
