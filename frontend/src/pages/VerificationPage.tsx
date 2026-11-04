import { useSession } from '../state/session';
import { ActionCard } from '../components/DossierView';
import { Badge } from '../ui/Badge';
import { Banner } from '../ui/Banner';
import { Card, PageTitle } from '../ui/Card';
import { EmptyState } from '../ui/States';
import { findingDisplayNames } from '../ui/format';

const ORDER = { high: 0, medium: 1, low: 2 } as const;

// Session review queue from the latest incident dossier. Review state is
// not persisted and assignment does not exist — stated, not implied.
export default function VerificationPage() {
  const { incident } = useSession();
  const dossier = incident.dossier;
  const actions = dossier ? [...dossier.verification_actions].sort(
    (a, b) => ORDER[a.priority] - ORDER[b.priority],
  ) : [];
  const labels = new Map(
    (dossier?.findings ?? []).map((f) => [f.finding_id, f.label]),
  );
  const names = findingDisplayNames(dossier?.findings ?? []);

  return (
    <section>
      <PageTitle
        title="Verification"
        subtitle="Human review of this session's incident analysis."
      />
      <div className="grid gap-4">
        <Banner tone="warning">
          Persistent verification and task assignment are not implemented. Actions
          below come from the current session only and clear on reload; completing
          them requires a person — nothing is marked done automatically.
        </Banner>
        {!dossier && (
          <EmptyState
            title="No incident in this session"
            body="Build an incident report first; its verification actions will appear here."
          />
        )}
        {dossier && (
          <Card>
            <p>
              Incident {dossier.incident_id} — report {dossier.incident_status},{' '}
              vision {dossier.vision_workflow_status}.{' '}
              <Badge tone="warning">Human verification: pending/manual</Badge>
            </p>
          </Card>
        )}
        {dossier && (
          <ol className="grid gap-2">
            {actions.map((a) => (
              <ActionCard key={a.action_id} action={a} labels={labels} names={names} />
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}
