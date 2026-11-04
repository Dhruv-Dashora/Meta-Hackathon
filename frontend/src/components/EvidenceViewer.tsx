import { useState } from 'react';
import type { EvidenceRef } from '../types/sentinel';
import { shortId } from '../ui/format';

// Compact evidence refs: modality plus a short hash with copy. Full
// hashes stay available on hover, via copy, and in JSON exports.
// NOTE: the data prop is named `evidence` — never `ref`, which React
// reserves and strips before props reach the component.
function EvidenceItem({ evidence }: { evidence: EvidenceRef }) {
  const [copied, setCopied] = useState(false);
  const evidenceId = evidence.evidence_id ?? '';
  const target = evidence.uri_or_hash ?? evidenceId;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(evidenceId);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };
  return (
    <li
      title={evidenceId && target ? `${evidenceId} — ${target}` : evidenceId || target}
      className="flex flex-wrap items-center gap-1"
    >
      <span className="min-w-0 break-anywhere">
        {evidence.modality ?? 'reference'}:{' '}
        {target ? <code>{shortId(target)}</code> : 'unavailable'}
      </span>
      {evidenceId && (
        <button
          type="button"
          onClick={copy}
          title={`Copy full reference: ${evidenceId}`}
          className="no-print text-teal-800 underline"
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
      )}
    </li>
  );
}

export default function EvidenceViewer({ refs }: { refs: EvidenceRef[] }) {
  const items = Array.isArray(refs) ? refs.filter((r) => r != null) : [];
  if (items.length === 0)
    return <p className="text-slate-600">No evidence references available.</p>;
  return (
    <ul className="grid gap-1 text-sm text-slate-600">
      {items.map((r, index) => (
        <EvidenceItem key={r.evidence_id ?? `evidence-${index}`} evidence={r} />
      ))}
    </ul>
  );
}
