import { useState } from 'react';
import type { Finding } from '../types/sentinel';
import { Badge } from '../ui/Badge';
import { Card } from '../ui/Card';
import { ConfidenceScore } from '../ui/ConfidenceHelp';
import { shortId } from '../ui/format';
import EvidenceViewer from './EvidenceViewer';

// Vision descriptions carry structured lines ("Observed:",
// "Affected feature:", "Location in image:"). Parse them so the card
// can show a concise observation plus the image-relative location —
// verbatim, never reworded. Plain-text descriptions fall back to the
// first line as the observation with no location line.
export function parseDescription(description: string): {
  observed: string;
  feature: string;
  location: string;
} {
  let observed = '';
  let feature = '';
  let location = '';
  for (const line of description.split('\n')) {
    const stripped = line.trim();
    if (stripped.startsWith('Observed:')) {
      observed = stripped.slice('Observed:'.length).trim();
    } else if (stripped.startsWith('Affected feature:')) {
      feature = stripped.slice('Affected feature:'.length).trim();
    } else if (stripped.startsWith('Location in image:')) {
      location = stripped.slice('Location in image:'.length).trim();
    }
  }
  if (!observed && !feature && !location) {
    observed = description.split('\n')[0]?.trim() ?? '';
  }
  return { observed, feature, location };
}

const REVIEW_TONE = {
  pending: 'warning',
  confirmed: 'success',
  rejected: 'danger',
  needs_more_evidence: 'warning',
} as const;

const REVIEW_LABEL: Record<string, string> = {
  pending: 'Pending Review',
  confirmed: 'Confirmed',
  rejected: 'Rejected',
  needs_more_evidence: 'Needs More Evidence',
};

// Observation card hierarchy: sequence badge, title, concise
// observation, affected feature and image-relative location when
// available, score, review status — then uncertainty and evidence
// details behind one expander.
export default function FindingCard({
  finding,
  sequence,
}: {
  finding: Finding;
  sequence?: number;
}) {
  const { observed, feature, location } = parseDescription(
    finding.description ?? '',
  );
  const [copied, setCopied] = useState(false);
  const copyId = async () => {
    try {
      await navigator.clipboard.writeText(finding.finding_id);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2">
        {sequence != null && <Badge>Visual Observation {sequence}</Badge>}
        <h4 className="text-lg font-semibold">{finding.label}</h4>
        <Badge tone={REVIEW_TONE[finding.review_status]}>
          {REVIEW_LABEL[finding.review_status] ?? finding.review_status}
        </Badge>
      </div>
      {observed && <p className="mt-1 text-slate-700">{observed}</p>}
      {feature && (
        <p className="mt-1 text-slate-700">
          <strong>Affected feature:</strong> {feature}
        </p>
      )}
      {location && (
        <p className="mt-1 text-slate-700">
          <strong>Location in image:</strong> {location}
        </p>
      )}
      <p className="mt-1 text-slate-700">
        <ConfidenceScore value={finding.confidence.value} />
      </p>
      <details className="print-expand mt-2 text-sm">
        <summary className="cursor-pointer text-teal-800 underline">
          Uncertainty and Evidence Details
        </summary>
        <div className="mt-1 grid gap-1 text-slate-600">
          {finding.uncertainty_notes && (
            <p>
              <strong>Uncertainty:</strong> {finding.uncertainty_notes}
            </p>
          )}
          <div>
            <p>
              <strong>Evidence Details:</strong>
            </p>
            <EvidenceViewer refs={finding.evidence_refs} />
          </div>
          <p title={finding.finding_id}>
            Observation reference:{' '}
            {sequence != null ? (
              <>Visual Observation {sequence}</>
            ) : (
              <code>{shortId(finding.finding_id)}</code>
            )}{' '}
            <button
              type="button"
              onClick={copyId}
              title={`Copy full reference: ${finding.finding_id}`}
              className="no-print text-teal-800 underline"
            >
              {copied ? 'Copied' : 'Copy'}
            </button>
          </p>
          {(finding.observed_at || finding.analyzed_at) && (
            <p>
              {[finding.observed_at, finding.analyzed_at]
                .filter(Boolean)
                .join(' · ')}
            </p>
          )}
        </div>
      </details>
    </Card>
  );
}
