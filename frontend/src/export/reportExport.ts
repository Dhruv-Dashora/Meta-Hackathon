// Report export: JSON download + print-to-PDF. Both operate on the
// in-hand dossier only — neither makes any network or model request.
import type { IncidentDossier } from '../types/incident';

export const REPORT_SCHEMA_VERSION = '1.0';

export interface ExportedReport {
  schema_version: string;
  exported_at: string;
  dossier: IncidentDossier;
}

export function buildExportPayload(dossier: IncidentDossier): ExportedReport {
  return {
    schema_version: REPORT_SCHEMA_VERSION,
    exported_at: new Date().toISOString(),
    dossier,
  };
}

export function downloadDossierJson(dossier: IncidentDossier): void {
  const payload = buildExportPayload(dossier);
  const text = JSON.stringify(payload, null, 2);
  const url = URL.createObjectURL(
    new Blob([text], { type: 'application/json' }),
  );
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `sentinel-${dossier.incident_id}.json`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function printReport(title?: string): void {
  // Closed <details> content does not print; expand print-marked ones and
  // restore them after the print dialog closes.
  const collapsed = Array.from(
    document.querySelectorAll<HTMLDetailsElement>('details.print-expand:not([open])'),
  );
  collapsed.forEach((d) => {
    d.setAttribute('open', '');
  });
  // A readable document title becomes the default PDF filename.
  const previousTitle = document.title;
  if (title) document.title = title;
  const restore = () => {
    collapsed.forEach((d) => {
      d.removeAttribute('open');
    });
    document.title = previousTitle;
    window.removeEventListener('afterprint', restore);
  };
  window.addEventListener('afterprint', restore);
  window.print();
}
