import { Button } from '../ui/Button';
import type { IncidentDossier } from '../types/incident';
import { downloadDossierJson, printReport } from './reportExport';

// Screen-only export controls. Hidden in print via .no-print. The PDF
// itself is the print-only PrintBrief, not this dashboard.
export function ExportBar({ dossier }: { dossier: IncidentDossier }) {
  return (
    <div className="no-print flex flex-wrap items-center gap-2">
      <Button
        type="button"
        onClick={() => printReport(`sentinel-${dossier.incident_id}-brief`)}
      >
        Export PDF
      </Button>
      <Button type="button" variant="secondary" onClick={() => downloadDossierJson(dossier)}>
        Export JSON
      </Button>
      <span className="text-sm text-slate-600">
        Exports reflect the current report without re-analysis.
      </span>
    </div>
  );
}
