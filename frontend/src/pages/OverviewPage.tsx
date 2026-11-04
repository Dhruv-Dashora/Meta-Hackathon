import { useSession } from '../state/session';
import { Badge } from '../ui/Badge';
import { Card, PageTitle, SectionTitle } from '../ui/Card';
import { plural } from '../ui/format';
import { EmptyState } from '../ui/States';

const WORKFLOWS = [
  {
    hash: '#image',
    title: 'Image Intelligence',
    body: 'Findings, SAM segmentation, and unified analysis on one upload.',
    status: 'live' as const,
  },
  {
    hash: '#reports',
    title: 'Incident Reports',
    body: 'Full dossiers with concerns and verification checklists.',
    status: 'live' as const,
  },
  {
    hash: '#geo',
    title: 'Geospatial Intelligence',
    body: 'Corridor map with operator location context.',
    status: 'live' as const,
  },
  {
    hash: '#verification',
    title: 'Verification',
    body: 'Session review queue. Persistent assignment is not implemented.',
    status: 'limited' as const,
  },
  {
    hash: '#early-warning',
    title: 'Early Warning',
    body: 'Historical comparison and anomaly flags — planned.',
    status: 'planned' as const,
  },
];

const STATUS_TONE = { live: 'success', limited: 'warning', planned: 'neutral' } as const;

// Product landing: real backend status, real session stats, and entry
// points into the working analysis views. Nothing is fabricated.
export default function OverviewPage() {
  const { health, healthError, stats, incident, intel } = useSession();
  const online = health?.status === 'ok';

  return (
    <section>
      <PageTitle
        title="Overview"
        subtitle="Himalayan Sentinel disaster-intelligence workspace for the Gyirong–Rasuwa corridor."
      />
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <SectionTitle>Backend</SectionTitle>
          <p>
            <Badge tone={online ? 'success' : 'warning'}>
              {online ? `Online — ${health?.service}` : 'Unreachable'}
            </Badge>
          </p>
          {healthError && <p className="mt-1 text-sm text-slate-600">{healthError}</p>}
        </Card>
        <Card>
          <SectionTitle>This session</SectionTitle>
          <p className="text-lg">
            {stats.analyses} analyses · {stats.findings} findings · {stats.regions}{' '}
            regions measured
          </p>
          <p className="mt-1 text-sm text-slate-600">
            Counts reset when the page reloads. No data leaves this browser except
            backend API calls.
          </p>
        </Card>
        <Card>
          <SectionTitle>Latest results</SectionTitle>
          {incident.dossier ? (
            <p>
              Incident {incident.dossier.incident_id} — {incident.dossier.incident_status},{' '}
              {plural(incident.dossier.verification_actions.length, 'verification action')}.
            </p>
          ) : intel.unifiedResult || intel.segResult || intel.findingsResult ? (
            <p>
              Image Intelligence:{' '}
              {intel.unifiedResult
                ? `${intel.unifiedResult.findings.length} findings, ${intel.unifiedResult.segmentations.length} prompts`
                : intel.segResult
                  ? `${intel.segResult.detections.length} segmented regions`
                  : `${intel.findingsResult?.findings.length ?? 0} findings`}
              .
            </p>
          ) : (
            <EmptyState title="No analyses yet" body="Run an analysis to see it here." />
          )}
        </Card>
      </div>
      <h3 className="mb-2 mt-6 text-lg font-semibold">Workflows</h3>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {WORKFLOWS.map((w) => (
          <a key={w.hash} href={w.hash} className="block rounded-lg">
            <Card className="h-full transition-colors hover:border-teal-600">
              <div className="flex items-center justify-between gap-2">
                <h4 className="text-lg font-semibold">{w.title}</h4>
                <Badge tone={STATUS_TONE[w.status]}>{w.status}</Badge>
              </div>
              <p className="mt-1 text-slate-600">{w.body}</p>
            </Card>
          </a>
        ))}
      </div>
    </section>
  );
}
