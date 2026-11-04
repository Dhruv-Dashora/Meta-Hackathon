import { useState } from 'react';
import FindingCard from './FindingCard';
import IncidentViewer from './IncidentViewer';
import { ExportBar } from '../export/ExportBar';
import PrintBrief from '../export/PrintBrief';
import { Badge } from '../ui/Badge';
import { Card, SectionTitle } from '../ui/Card';
import { ConfidenceNote } from '../ui/ConfidenceHelp';
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
  shortId,
  titleWord,
  workflowStatusLabel,
} from '../ui/format';
import type {
  ActionPriority,
  DamageAssessment,
  DamageCategory,
  ExposureConcern,
  IncidentDossier,
  RescueAttention,
  RescuePriority,
  VerificationAction,
} from '../types/incident';
import type { Finding } from '../types/sentinel';

const PRIORITY_ORDER: Record<ActionPriority, number> = {
  high: 0,
  medium: 1,
  low: 2,
};

const PRIORITY_TONE = { high: 'danger', medium: 'warning', low: 'neutral' } as const;

const STAGE_TONE = {
  completed: 'success',
  partial: 'warning',
  failed: 'danger',
  skipped: 'neutral',
} as const;

function byPriority(a: VerificationAction, b: VerificationAction) {
  return PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority];
}

function findingLabels(dossier: IncidentDossier): Map<string, string> {
  return new Map(dossier.findings.map((f) => [f.finding_id, f.label]));
}

// Truncated evidence id with full id on hover and click-to-copy.
export function EvidenceId({ id }: { id: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(id);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };
  return (
    <span className="inline-flex items-center gap-1">
      <code title={id} className="rounded bg-slate-100 px-1 text-sm">
        {shortId(id)}
      </code>
      <button
        type="button"
        onClick={copy}
        title={`Copy full id: ${id}`}
        className="no-print text-sm text-teal-800 underline"
      >
        {copied ? 'Copied' : 'Copy'}
      </button>
    </span>
  );
}

function Header({ dossier }: { dossier: IncidentDossier }) {
  const total = dossier.findings.length;
  const pending = dossier.findings.filter((f) => f.review_status === 'pending').length;
  const analysisDone = dossier.incident_status === 'completed';
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={analysisDone ? 'success' : 'warning'}>
          Assessment {assessmentStatusLabel(dossier.incident_status)}
        </Badge>
        <Badge>
          Image Analysis {workflowStatusLabel(dossier.vision_workflow_status)}
        </Badge>
        <Badge tone="warning">Human Verification Required</Badge>
      </div>
      <h3 className="mt-2 text-xl font-semibold tracking-tight">
        {dossier.situation_summary.headline}
      </h3>
      <p className="mt-1">
        <strong>Observed:</strong> {dossier.situation_summary.observed}
      </p>
      <p className="mt-1 text-slate-700">
        <strong>Unknown:</strong> {dossier.situation_summary.unknowns}
      </p>
      <p className="mt-1 text-sm text-slate-600">
        {dossier.incident_id} — {plural(total, 'visual observation')},{' '}
        {plural(dossier.exposure_concerns.length, 'conditional concern')},{' '}
        {plural(dossier.verification_actions.length, 'verification action')}.{' '}
        {total > 0 ? `${pending} of ${total} awaiting human review. ` : ''}
        Results require human verification before action.
      </p>
      {dossier.warnings.length > 0 && (
        <ul className="mt-2 grid gap-1">
          {dossier.warnings.map((w) => (
            <li key={w} className="text-amber-800">
              Warning: {w}
            </li>
          ))}
        </ul>
      )}
      {dossier.degraded_sections && dossier.degraded_sections.length > 0 && (
        <p
          role="alert"
          className="mt-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-amber-900"
        >
          Partial coverage: {dossier.degraded_sections.join(', ')} had
          content loss in this report — read those sections with extra
          care.
        </p>
      )}
    </Card>
  );
}

// Split a compound task into short sequential steps. Splitting is
// presentational only: wording is never altered, and single tasks
// render as one plain paragraph.
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

// Finding links for "Supporting evidence" sections: numbered
// observation names up front ("Visual Observation 2 — label"), the
// full internal id on hover for traceability.
function FindingBasis({
  ids,
  labels,
  names,
  empty,
}: {
  ids: string[];
  labels?: Map<string, string>;
  names?: Map<string, string>;
  empty: string;
}) {
  if (ids.length === 0) return <p>Supporting observations: {empty}.</p>;
  return (
    <div>
      <p>Supporting observations:</p>
      <ul className="list-disc pl-5">
        {ids.map((id) => {
          const name = names?.get(id);
          return (
            <li key={id} title={id}>
              {name ? (
                <>
                  {name} — {labels?.get(id) ?? 'observation'}
                </>
              ) : (
                <>
                  {labels?.get(id) ?? 'observation'} (<code>{shortId(id)}</code>)
                </>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// Verification card hierarchy: short title plus priority, what to
// check (compound tasks as sequential steps), why it matters,
// unknowns, suggested method — then supporting evidence behind one
// expander instead of a wall of text.
export function ActionCard({
  action,
  compact,
  anchorId,
  labels,
  names,
}: {
  action: VerificationAction;
  compact?: boolean;
  anchorId?: string;
  labels?: Map<string, string>;
  names?: Map<string, string>;
}) {
  const resolve = (text: string) =>
    names ? resolveFindingReferences(text, names) : text;
  const task = resolve(action.what || action.action);
  const title = actionTitle(action);
  const steps = splitSteps(task);
  const why = resolve(action.why_operational || action.reason);
  const unknown = action.unknown ? resolve(action.unknown) : '';
  const method = action.method ? resolve(action.method) : '';
  return (
    <li id={anchorId} className="rounded-lg border border-slate-200 bg-white p-3 shadow-card">
      <p>
        <Badge tone={PRIORITY_TONE[action.priority]}>{titleWord(action.priority)} Priority</Badge>{' '}
        <strong>{title}</strong>
      </p>
      {compact && (
        <p className="mt-1 text-sm">
          <a className="text-teal-800 underline" href={`#${action.action_id}`}>
            Full instructions, unknowns, and evidence in the checklist below.
          </a>
        </p>
      )}
      {!compact && (
        <div className="mt-1 grid gap-1 text-slate-700">
          {steps.length > 1 ? (
            <div>
              <strong>What to check:</strong>
              <ol className="list-decimal pl-5">
                {steps.map((step, i) => (
                  <li key={`${i}-${step.slice(0, 24)}`}>{step}</li>
                ))}
              </ol>
            </div>
          ) : (
            title !== task.trim() && (
              <p>
                <strong>What to check:</strong> {task}
              </p>
            )
          )}
          <p>
            <strong>Why it matters:</strong> {why}
          </p>
          {unknown && (
            <p>
              <strong>Unknown:</strong> {unknown}
            </p>
          )}
          {method && (
            <p>
              <strong>Suggested method</strong> (requires local judgment): {method}
            </p>
          )}
          <details className="print-expand">
            <summary className="cursor-pointer text-sm text-teal-800 underline">
              Supporting evidence
            </summary>
            <div className="mt-1 grid gap-1 text-sm text-slate-600">
              <FindingBasis
                ids={action.related_finding_ids}
                labels={labels}
                names={names}
                empty="General review"
              />
              <p>{resolve(action.priority_reason)}</p>
            </div>
          </details>
        </div>
      )}
    </li>
  );
}

const DAMAGE_LABEL: Record<DamageCategory, string> = {
  no_visible_damage: 'No visible damage',
  possible_damage: 'Possible damage',
  apparent_major_damage: 'Apparent major damage',
  cannot_assess: 'Cannot assess',
};

const DAMAGE_TONE = {
  no_visible_damage: 'neutral',
  possible_damage: 'warning',
  apparent_major_damage: 'danger',
  cannot_assess: 'neutral',
} as const;

function DamageCard({
  assessment,
  labels,
  names,
}: {
  assessment: DamageAssessment;
  labels?: Map<string, string>;
  names?: Map<string, string>;
}) {
  return (
    <li className="rounded-lg border border-slate-200 bg-white p-3 shadow-card">
      <p>
        <Badge>{assessment.target_label || assessment.feature}</Badge>{' '}
        <Badge tone={DAMAGE_TONE[assessment.category]}>
          {DAMAGE_LABEL[assessment.category]}
        </Badge>
      </p>
      {damageNarrativeRows(assessment).map((row) => (
        <p key={row.label} className="mt-1 text-slate-700">
          <strong>{`${row.label}:`}</strong> {row.text}
        </p>
      ))}
      <details className="print-expand mt-1">
        <summary className="cursor-pointer text-sm text-teal-800 underline">
          Supporting evidence
        </summary>
        <div className="mt-1 text-sm text-slate-600">
          <FindingBasis
            ids={assessment.basis_finding_ids}
            labels={labels}
            names={names}
            empty="None listed"
          />
        </div>
      </details>
    </li>
  );
}

const RESCUE_TONE = {
  high: 'danger',
  medium: 'warning',
  low: 'neutral',
  undetermined: 'neutral',
} as const;

function RescueCard({
  attention,
  labels,
  names,
}: {
  attention: RescueAttention;
  labels?: Map<string, string>;
  names?: Map<string, string>;
}) {
  const priority: RescuePriority = attention.priority;
  const rationale = names
    ? resolveFindingReferences(attention.rationale, names)
    : attention.rationale;
  return (
    <li className="rounded-lg border border-slate-200 bg-white p-3 shadow-card">
      <p>
        <Badge tone={RESCUE_TONE[priority]}>{titleWord(priority)} Review Priority</Badge>
      </p>
      <p className="mt-1">{rationale}</p>
      <details className="print-expand mt-1">
        <summary className="cursor-pointer text-sm text-teal-800 underline">
          Supporting evidence
        </summary>
        <div className="mt-1 text-sm text-slate-600">
          <FindingBasis
            ids={attention.basis_finding_ids}
            labels={labels}
            names={names}
            empty="No observations available"
          />
        </div>
      </details>
    </li>
  );
}

function ConcernCard({
  concern,
  labels,
  names,
  linkedTask,
}: {
  concern: ExposureConcern;
  labels?: Map<string, string>;
  names?: Map<string, string>;
  linkedTask?: string;
}) {
  const condition = names
    ? resolveFindingReferences(concern.condition, names)
    : concern.condition;
  const consequence = names
    ? resolveFindingReferences(concern.concern, names)
    : concern.concern;
  return (
    <li className="rounded-lg border border-amber-200 bg-amber-50 p-3">
      <p>
        <Badge>{concern.feature}</Badge>
      </p>
      <p className="mt-1">
        <strong>Unconfirmed premise:</strong> {ensurePeriod(condition)}
      </p>
      <p>
        <strong>Possible consequence:</strong> {ensurePeriod(consequence)}
      </p>
      <details className="print-expand mt-1">
        <summary className="cursor-pointer text-sm text-teal-800 underline">
          Supporting evidence
        </summary>
        <div className="mt-1 grid gap-1 text-sm text-slate-600">
          <FindingBasis
            ids={concern.basis_finding_ids}
            labels={labels}
            names={names}
            empty="None listed"
          />
          <p>
            Linked verification task:{' '}
            <a
              className="text-teal-800 underline"
              href={`#${concern.verification_action_id}`}
              title={concern.verification_action_id}
            >
              {linkedTask ?? shortId(concern.verification_action_id)}
            </a>
          </p>
          <p title={concern.concern_id}>
            Concern reference: <code>{shortId(concern.concern_id)}</code>
          </p>
        </div>
      </details>
    </li>
  );
}

function summaryStatusLabel(status: string, count: number): string {
  if (status === 'ok') return plural(count, 'region');
  if (status === 'zero_matches') return 'No matching regions identified';
  if (status === 'failed') return 'Unavailable';
  return 'Not analyzed';
}

function ObservedEvidence({ dossier }: { dossier: IncidentDossier }) {
  const byId = new Map<string, Finding>(dossier.findings.map((f) => [f.finding_id, f]));
  // Global sequence in dossier order, so grouped cards keep the same
  // numbers used everywhere else in the report.
  const sequence = new Map<string, number>(
    dossier.findings.map((f, i) => [f.finding_id, i + 1]),
  );
  return (
    <div className="grid gap-3">
      <p className="text-slate-600">
        Directly observed in the image. Region counts describe outlined
        areas only and never confirm an observation.
      </p>
      <ConfidenceNote />
      {dossier.finding_groups.length > 0 ? (
        dossier.finding_groups.map((g) => (
          <div key={g.group_id}>
            <h4 className="mb-1 font-medium">{g.title}</h4>
            <div className="grid gap-2 xl:grid-cols-2">
              {g.finding_ids.map(
                (fid) =>
                  byId.has(fid) && (
                    <FindingCard
                      key={fid}
                      finding={byId.get(fid)!}
                      sequence={sequence.get(fid)}
                    />
                  ),
              )}
            </div>
          </div>
        ))
      ) : dossier.findings.length > 0 ? (
        <div className="grid gap-2 xl:grid-cols-2">
          {dossier.findings.map((f, i) => (
            <FindingCard key={f.finding_id} finding={f} sequence={i + 1} />
          ))}
        </div>
      ) : (
        <p>No visual observations identified in this image.</p>
      )}
      {dossier.segmentation_summary.length > 0 && (
        <ul>
          {dossier.segmentation_summary.map((s) => (
            <li key={s.prompt}>
              “{s.prompt}”: {summaryStatusLabel(s.status, s.detection_count)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// Session-only review checklist: every item starts unchecked, and checks
// are never sent, saved, or presented as completed verification.
function HumanReview({ actions }: { actions: VerificationAction[] }) {
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const toggle = (id: string) =>
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  return (
    <div>
      <p className="text-slate-600">
        {checked.size} of {actions.length} marked reviewed by you, in this
        browser session only. Marks are a personal aid — they are not saved
        and never count as verified evidence.
      </p>
      <ul className="mt-2 grid gap-1">
        {actions.map((a) => (
          <li key={a.action_id}>
            <label className="flex items-start gap-2">
              <input
                type="checkbox"
                className="mt-1"
                checked={checked.has(a.action_id)}
                onChange={() => toggle(a.action_id)}
                aria-label={`Mark reviewed: ${a.what || a.action}`}
              />
              <span>
                <Badge tone={PRIORITY_TONE[a.priority]}>{titleWord(a.priority)}</Badge>{' '}
                {actionTitle(a)}
              </span>
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
}

// Incident-command dashboard: header summary, annotated viewer beside the
// top actions, damage and review priorities, evidence vs inference,
// timeline, geo, technical details.
export default function DossierView({
  dossier,
  imageUrl,
}: {
  dossier: IncidentDossier;
  imageUrl: string | null;
}) {
  const ranked = [...dossier.verification_actions].sort(byPriority);
  const labels = findingLabels(dossier);
  const names = findingDisplayNames(dossier.findings);
  const taskById = new Map(
    dossier.verification_actions.map((a) => [a.action_id, actionTitle(a)]),
  );
  return (
    <div className="report-body grid gap-4">
      {/* Print/PDF renders the linear brief, not the dashboard. */}
      <div className="print-only">
        <PrintBrief dossier={dossier} imageUrl={imageUrl} />
      </div>
      <div className="screen-only grid gap-4">
      <ExportBar dossier={dossier} />
      <section aria-label="Incident overview">
        <Header dossier={dossier} />
      </section>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="min-w-0 xl:col-span-2">
          <section aria-label="Incident imagery">
            <SectionTitle>Incident Imagery</SectionTitle>
            {imageUrl ? (
              <IncidentViewer imageUrl={imageUrl} dossier={dossier} />
            ) : (
              <p>No image preview available.</p>
            )}
          </section>
        </Card>
        <Card className="min-w-0">
          <section aria-label="Priority actions">
            <SectionTitle>Priority Actions</SectionTitle>
            <ol className="grid gap-2">
              {ranked.slice(0, 3).map((a) => (
                <ActionCard key={a.action_id} action={a} compact labels={labels} names={names} />
              ))}
            </ol>
            {ranked.length > 3 && (
              <p className="mt-2 text-slate-600">
                {ranked.length - 3} additional actions listed below.
              </p>
            )}
          </section>
        </Card>
      </div>

      <Card>
        <section aria-label="Provisional damage assessments">
          <SectionTitle>Provisional Damage Assessments</SectionTitle>
          <p className="text-slate-600">
            Provisional observations linked to evidence, not engineering
            findings. “No visible damage” does not confirm safety.
          </p>
          {dossier.damage_assessments.length > 0 ? (
            <ul className="mt-2 grid gap-2 xl:grid-cols-2">
              {dossier.damage_assessments.map((d) => (
                <DamageCard key={d.assessment_id} assessment={d} labels={labels} names={names} />
              ))}
            </ul>
          ) : (
            <p className="mt-2">
              No damage observations available (no identifiable features, or
              assessment incomplete).
            </p>
          )}
        </section>
      </Card>

      <Card>
        <section aria-label="Review priorities">
          <SectionTitle>Human-Verification Priorities</SectionTitle>
          <p className="text-slate-600">
            Urgency of human review — never rescue orders. High priority
            requires explicit evidence of possible immediate danger.
            {((dossier.access_priorities?.length ?? 0) > 0 ||
              (dossier.review_priorities?.length ?? 0) > 0) && (
              <>
                {' '}
                Separately,{' '}
                {plural(dossier.access_priorities?.length ?? 0, 'route-access item')}{' '}
                and{' '}
                {plural(dossier.review_priorities?.length ?? 0, 'routine observation')}{' '}
                also await human review; full records are in the JSON export.
              </>
            )}
          </p>
          {dossier.rescue_priorities.length > 0 ? (
            <ul className="mt-2 grid gap-2 xl:grid-cols-2">
              {dossier.rescue_priorities.map((r) => (
                <RescueCard key={r.attention_id} attention={r} labels={labels} names={names} />
              ))}
            </ul>
          ) : (
            <p className="mt-2">
              No review priorities available (assessment incomplete).
            </p>
          )}
        </section>
      </Card>

      <Card>
        <section aria-label="Observed visual evidence">
          <SectionTitle>Observed Visual Evidence</SectionTitle>
          <ObservedEvidence dossier={dossier} />
        </section>
      </Card>

      <Card>
        <section aria-label="Conditional exposure concerns">
          <SectionTitle>Conditional Exposure Concerns</SectionTitle>
          <p className="text-slate-600">
            Unverified inference, not observed facts: each concern states an
            unconfirmed “if” premise and must be verified before any action.
          </p>
          {dossier.exposure_concerns.length > 0 ? (
            <ul className="mt-2 grid gap-2 xl:grid-cols-2">
              {dossier.exposure_concerns.map((c) => (
                <ConcernCard
                  key={c.concern_id}
                  concern={c}
                  labels={labels}
                  names={names}
                  linkedTask={taskById.get(c.verification_action_id)}
                />
              ))}
            </ul>
          ) : (
            <p className="mt-2">
              No exposure concerns identified (none indicated, or assessment
              incomplete).
            </p>
          )}
        </section>
      </Card>

      <Card>
        <section aria-label="Verification checklist">
          <SectionTitle>Verification Checklist (by Priority)</SectionTitle>
          <p className="text-slate-600">
            Complete each item manually. Nothing is marked complete
            automatically. Suggested methods require local judgment.
          </p>
          <ol className="mt-2 grid gap-2">
            {ranked.map((a) => (
              <ActionCard key={a.action_id} action={a} anchorId={a.action_id} labels={labels} names={names} />
            ))}
          </ol>
        </section>
      </Card>

      <Card>
        <section aria-label="Human review record">
          <SectionTitle>Human Review Record</SectionTitle>
          <HumanReview actions={dossier.verification_actions} />
        </section>
      </Card>

      <Card>
        <section aria-label="Analysis summary">
          <SectionTitle>Analysis Summary</SectionTitle>
          <ol className="grid gap-1">
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
                <span className="font-medium">{s.stage}</span>{' '}
                <Badge tone={STAGE_TONE[s.status]}>{titleWord(s.status)}</Badge>{' '}
                <span className="text-slate-600">{s.summary}</span>
              </li>
            ))}
          </ol>
          <details className="print-expand mt-2">
            <summary className="cursor-pointer text-sm text-teal-800 underline">
              Technical Details
            </summary>
            <ul className="mt-1 grid gap-1 text-sm text-slate-600">
              {analysisTechnicalDetails({
                agent_trail: dossier.agent_trail,
                vision_source: dossier.vision_source,
                analysis_ref: dossier.analysis_ref,
                vision_workflow_status: dossier.vision_workflow_status,
                incident_status: dossier.incident_status,
              }).map((line, i) => (
                <li key={`${i}-${line.slice(0, 24)}`}>{line}</li>
              ))}
            </ul>
          </details>
        </section>
      </Card>

      <Card>
        <section aria-label="Location and unverified information">
          <SectionTitle>Location & Unverified Information</SectionTitle>
          <h4 className="font-medium">Location</h4>
          <p className="mt-1">
            {dossier.geo_context.status === 'provided' ? (
              <>
                <Badge>Operator-Provided, Unverified</Badge>{' '}
                {dossier.geo_context.location_label && (
                  <strong>{dossier.geo_context.location_label} </strong>
                )}
                {dossier.geo_context.latitude != null &&
                  `(${dossier.geo_context.latitude}, ${dossier.geo_context.longitude}) `}
                {dossier.geo_context.geojson_feature_count != null &&
                  `${plural(dossier.geo_context.geojson_feature_count, 'GeoJSON feature')}. `}
                {dossier.geo_context.note}
              </>
            ) : (
              <>
                <Badge tone="neutral">Unavailable</Badge> {dossier.geo_context.note}{' '}
                The image is not placed on a map.
              </>
            )}
          </p>
          <p className="mt-1 text-sm text-slate-600">
            Observation locations refer to positions within the image, not
            map coordinates — they never place the image geographically.
          </p>
          {groupInformationGaps(dossier.information_gaps).length > 0 && (
            <div className="mt-3 grid gap-2">
              <h4 className="font-medium">Still needs verification</h4>
              {groupInformationGaps(dossier.information_gaps).map((group) => (
                <div key={group.heading}>
                  <p className="text-sm font-medium text-slate-700">{group.heading}</p>
                  <ul className="mt-1 grid gap-1">
                    {group.items.map((g) => (
                      <li key={g.topic}>
                        <Badge>{titleWord(g.status)}</Badge>{' '}
                        <strong>{gapTopicLabel(g.topic)}:</strong> {g.detail}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
              <p className="text-sm text-slate-600">
                Confirm each item during verification; the checklist above
                holds the corresponding checks.
              </p>
            </div>
          )}
        </section>
      </Card>

      <Card>
        <details className="print-expand">
          <summary className="no-print cursor-pointer text-lg font-semibold tracking-tight">
            Technical Evidence and Uncertainty
          </summary>
          <h3 className="print-only print-section-title">
            Technical Evidence and Uncertainty
          </h3>
          <div className="grid gap-2 pt-2">
            <ul className="grid gap-1">
              {dossier.uncertainty_notes.map((n, i) => (
                <li key={`${i}-${n.slice(0, 24)}`}>{n}</li>
              ))}
            </ul>
            <ul className="grid gap-1">
              {dossier.evidence_ledger.map((e) => (
                <li key={e.evidence_id}>
                  <EvidenceId id={e.evidence_id} /> — {e.modality} ({e.source})
                </li>
              ))}
            </ul>
          </div>
        </details>
      </Card>
      </div>
    </div>
  );
}
