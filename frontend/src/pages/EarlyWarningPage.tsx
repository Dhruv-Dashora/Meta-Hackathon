import { Badge } from '../ui/Badge';
import { Card, PageTitle } from '../ui/Card';

// Honest planned state: describes intent, fabricates no feeds or alerts.
export default function EarlyWarningPage() {
  return (
    <section>
      <PageTitle
        title="Early Warning"
        subtitle="Historical comparison and anomaly flags for the corridor."
      />
      <Card>
        <p>
          <Badge>Planned</Badge>
        </p>
        <p className="mt-2">
          Early warning will pair historical and recent views of the same location,
          flag visual and environmental changes, and attach hydromet context where
          available — always for human verification, never as autonomous prediction.
        </p>
        <p className="mt-2 text-slate-600">
          There are no monitoring feeds, historical trends, or alerts in this build.
          The working image and incident workflows are available in the sidebar.
        </p>
      </Card>
    </section>
  );
}
