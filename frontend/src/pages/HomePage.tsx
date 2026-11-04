import { useSession } from '../state/session';
import { Banner } from '../ui/Banner';
import { Button } from '../ui/Button';
import { Card, PageTitle } from '../ui/Card';
import { assessmentStatusLabel, plural, workflowStatusLabel } from '../ui/format';

const STEPS = [
  'Upload a disaster image.',
  'Visual analysis identifies potential hazards and affected features.',
  'Detected regions outline relevant areas such as roads, water, buildings, vehicles, and people.',
  'The assessment adds provisional damage observations and review priorities.',
  'An incident report is assembled with supporting evidence and identified gaps.',
  'Export the report as PDF or JSON. Exports use the current results without re-analysis.',
];

export default function HomePage() {
  const { evidence, stats, health } = useSession();
  const { file, unifiedResult, dossier } = evidence;
  const online = health?.status === 'ok';

  return (
    <section>
      <PageTitle
        title="Himalayan Sentinel"
        subtitle="Disaster imagery assessment with evidence-grounded incident reporting."
      />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <div className="grid content-start gap-4">
          <Card>
            <h3 className="text-lg font-semibold">Start</h3>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button type="button" onClick={() => { window.location.hash = '#unified'; }}>
                Analyze Image
              </Button>
              <Button
                type="button"
                variant="secondary"
                disabled={!dossier}
                title={dossier ? 'Open the current report' : 'No report yet — analyze an image first'}
                onClick={() => { window.location.hash = '#reports'; }}
              >
                Open Current Report
              </Button>
            </div>
            <p className="mt-3 text-slate-600">
              {file
                ? `Current image: ${file.name}. The incident report will use this analysis.`
                : 'No image selected. Begin in Hazard & Impact Analysis.'}
            </p>
          </Card>

          <Card>
            <h3 className="text-lg font-semibold">How a Report Is Prepared</h3>
            <ol className="mt-2 grid list-decimal gap-1 pl-5 text-slate-700">
              {STEPS.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          </Card>
        </div>

        <div className="grid content-start gap-4">
          <Card>
            <h3 className="text-lg font-semibold">This Session</h3>
            <dl className="mt-2 grid gap-1 text-slate-700">
              <div className="flex justify-between gap-2">
                <dt>Service</dt>
                <dd>{online ? 'Available' : 'Unavailable'}</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt>Current Image</dt>
                <dd>{file ? file.name : 'None selected'}</dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt>Analysis</dt>
                <dd>
                  {unifiedResult
                    ? `${plural(unifiedResult.findings.length, 'visual observation')}, ${workflowStatusLabel(unifiedResult.workflow_status)}`
                    : 'Not started'}
                </dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt>Report</dt>
                <dd>
                  {dossier
                    ? `${dossier.incident_id} (${assessmentStatusLabel(dossier.incident_status)})`
                    : 'Not prepared'}
                </dd>
              </div>
              <div className="flex justify-between gap-2">
                <dt>Analyses Completed</dt>
                <dd>{stats.analyses}</dd>
              </div>
            </dl>
          </Card>

          <Banner>
            Preliminary results. Damage observations are provisional, detected
            regions do not confirm exposure, and nothing is verified until
            reviewed.
          </Banner>
        </div>
      </div>
    </section>
  );
}
