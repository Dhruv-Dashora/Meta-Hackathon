import { useState } from 'react';
import { api } from '../api/client';
import { useSession } from '../state/session';
import DossierView from '../components/DossierView';
import { Banner, Field, inputClass } from '../ui/Banner';
import { Button } from '../ui/Button';
import { Card, PageTitle } from '../ui/Card';
import { EmptyState, ErrorState } from '../ui/States';
import { AnalysisProgress, DOSSIER_STAGES } from '../ui/ProgressBar';
import { friendlyErrorMessage } from '../ui/format';
import type { IncidentDossier } from '../types/incident';

// Incident Reports: builds the dossier from shared evidence. When the
// image was analyzed on the Unified tab, the report reuses that analysis
// with zero model calls; otherwise it runs one fresh analysis.
export default function IncidentReportsPage() {
  const {
    evidence,
    setEvidenceDossier,
    sessionId,
    ensureSessionId,
    resetSessionId,
    registerAnalysis,
  } = useSession();
  const [locationLabel, setLocationLabel] = useState('');
  const [latitude, setLatitude] = useState('');
  const [longitude, setLongitude] = useState('');
  const [geojson, setGeojson] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expired, setExpired] = useState(false);
  const [loading, setLoading] = useState(false);

  const { file, previewUrl, unifiedResult, dossier } = evidence;
  const reusableRef = unifiedResult?.analysis_ref ?? null;
  const canReuse = Boolean(reusableRef && (sessionId || unifiedResult));

  const parseNumber = (raw: string): number | null => {
    const text = raw.trim();
    if (!text) return null;
    const value = Number(text);
    return Number.isFinite(value) ? value : null;
  };

  const readGeojson = async (f: File | null): Promise<Record<string, unknown> | undefined> => {
    if (!f) return undefined;
    const text = await f.text();
    return JSON.parse(text) as Record<string, unknown>;
  };

  const buildFromAnalysis = async () => {
    if (!reusableRef || loading) return;
    setLoading(true);
    setError(null);
    setExpired(false);
    setEvidenceDossier(null);
    try {
      let sid = sessionId ?? (await ensureSessionId());
      if (!sid) throw new Error('No service session available. The report will require a new analysis.');
      let geojsonBody: Record<string, unknown> | undefined;
      try {
        geojsonBody = await readGeojson(geojson);
      } catch {
        throw new Error('GeoJSON file is not valid JSON.');
      }
      const buildArgs = {
        locationLabel: locationLabel.trim(),
        latitude: parseNumber(latitude),
        longitude: parseNumber(longitude),
        ...(geojsonBody === undefined ? {} : { geojson: geojsonBody }),
      };
      let data: IncidentDossier;
      try {
        data = (await api.assessIncidentFromAnalysis(
          reusableRef,
          sid,
          buildArgs,
        )) as IncidentDossier;
      } catch (e) {
        // One retry with a fresh session: the stored id may predate a restart.
        if (e instanceof Error && e.message.includes('invalid_session')) {
          resetSessionId();
          sid = await ensureSessionId();
          if (!sid) throw new Error('No service session available. The report will require a new analysis.');
          data = (await api.assessIncidentFromAnalysis(
            reusableRef,
            sid,
            buildArgs,
          )) as IncidentDossier;
        } else {
          throw e;
        }
      }
      setEvidenceDossier(data);
      registerAnalysis({
        findings: data.findings.length,
        regions: data.segmentation_summary.reduce((n, s) => n + s.detection_count, 0),
      });
    } catch (e) {
      // Machine-readable code stays on the raw message; the display
      // text is user-friendly.
      const raw = e instanceof Error ? e.message : 'Report build failed.';
      if (raw.includes('analysis_not_found')) setExpired(true);
      setError(friendlyErrorMessage(e, raw));
    } finally {
      setLoading(false);
    }
  };

  const buildFresh = async () => {
    if (!file || loading) return;
    setLoading(true);
    setError(null);
    setExpired(false);
    setEvidenceDossier(null);
    try {
      const data = (await api.assessIncident(file, {
        locationLabel: locationLabel.trim(),
        latitude: latitude.trim(),
        longitude: longitude.trim(),
        geojson,
      })) as IncidentDossier;
      setEvidenceDossier(data);
      registerAnalysis({
        findings: data.findings.length,
        regions: data.segmentation_summary.reduce((n, s) => n + s.detection_count, 0),
      });
    } catch (e) {
      setError(friendlyErrorMessage(e, 'Incident assessment failed.'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <section>
      <PageTitle
        title="Incident Reports"
        subtitle="Evidence-grounded incident assessments with verification checklists."
      />
      {!file && !dossier && (
        <Card>
          <EmptyState
            title="No Image Selected"
            body="Analyze an image in Hazard & Impact Analysis first, then return here to prepare the report."
          />
          <div className="mt-3">
            <Button
              type="button"
              onClick={() => {
                window.location.hash = '#unified';
              }}
            >
              Go to Hazard & Impact Analysis
            </Button>
          </div>
        </Card>
      )}

      {(file || dossier) && (
        <Card className="no-print mb-4">
          {dossier ? (
            <details>
              <summary className="cursor-pointer font-medium">
                New report — {file?.name ?? 'image'}
              </summary>
              <div className="pt-3">
                <BuildForm
                  fileName={file?.name ?? null}
                  canReuse={canReuse}
                  hasAnalysis={Boolean(unifiedResult)}
                  locationLabel={locationLabel}
                  setLocationLabel={setLocationLabel}
                  latitude={latitude}
                  setLatitude={setLatitude}
                  longitude={longitude}
                  setLongitude={setLongitude}
                  setGeojson={setGeojson}
                  disabled={loading}
                  loading={loading}
                  onReuse={buildFromAnalysis}
                  onFresh={buildFresh}
                />
              </div>
            </details>
          ) : (
            <BuildForm
              fileName={file?.name ?? null}
              canReuse={canReuse}
              hasAnalysis={Boolean(unifiedResult)}
              locationLabel={locationLabel}
              setLocationLabel={setLocationLabel}
              latitude={latitude}
              setLatitude={setLatitude}
              longitude={longitude}
              setLongitude={setLongitude}
              setGeojson={setGeojson}
              disabled={loading}
              loading={loading}
              onReuse={buildFromAnalysis}
              onFresh={buildFresh}
            />
          )}
          <div className="mt-3 grid gap-2">
            {loading && <AnalysisProgress stages={DOSSIER_STAGES} />}
            {error && <ErrorState message={error} />}
            {expired && file && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-slate-700">
                  The previous analysis has expired. Prepare a new analysis
                  from the image?
                </span>
                <Button type="button" variant="secondary" disabled={loading} onClick={buildFresh}>
                  Prepare New Analysis
                </Button>
              </div>
            )}
          </div>
        </Card>
      )}

      {dossier && <DossierView dossier={dossier} imageUrl={previewUrl} />}
    </section>
  );
}

function BuildForm(props: {
  fileName: string | null;
  canReuse: boolean;
  hasAnalysis: boolean;
  locationLabel: string;
  setLocationLabel: (v: string) => void;
  latitude: string;
  setLatitude: (v: string) => void;
  longitude: string;
  setLongitude: (v: string) => void;
  setGeojson: (f: File | null) => void;
  disabled: boolean;
  loading: boolean;
  onReuse: () => void;
  onFresh: () => void;
}) {
  return (
    <div className="grid gap-3">
      <p className="text-slate-700">
        Image: <strong>{props.fileName ?? 'None selected'}</strong>
      </p>
      {props.canReuse ? (
        <Banner>
          This image has already been analyzed. The report will reuse those
          results.
        </Banner>
      ) : props.hasAnalysis ? (
        <Banner>
          Previous results are unavailable for this analysis. Preparing the
          report will run a new analysis.
        </Banner>
      ) : (
        <Banner>Preparing a report analyzes the image once.</Banner>
      )}
      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Location label (optional)">
          <input
            type="text"
            value={props.locationLabel}
            maxLength={200}
            placeholder="e.g. Rasuwa corridor"
            onChange={(e) => props.setLocationLabel(e.target.value)}
            className={inputClass}
          />
        </Field>
        <Field label="Latitude (optional)">
          <input
            type="text"
            value={props.latitude}
            inputMode="decimal"
            placeholder="e.g. 28.2"
            onChange={(e) => props.setLatitude(e.target.value)}
            className={inputClass}
          />
        </Field>
        <Field label="Longitude (optional)">
          <input
            type="text"
            value={props.longitude}
            inputMode="decimal"
            placeholder="e.g. 85.6"
            onChange={(e) => props.setLongitude(e.target.value)}
            className={inputClass}
          />
        </Field>
        <Field label="GeoJSON context (optional)">
          <input
            type="file"
            accept=".geojson,.json,application/json"
            onChange={(e) => props.setGeojson(e.target.files?.[0] ?? null)}
            className="text-base"
          />
        </Field>
      </div>
      <p className="text-sm text-slate-600">
        Location details are provided by the operator and remain unverified.
      </p>
      <div className="flex flex-wrap items-end gap-2">
        {props.canReuse ? (
          <Button disabled={props.disabled} onClick={props.onReuse}>
            {props.loading ? 'Preparing Report…' : 'Prepare Report from Current Analysis'}
          </Button>
        ) : (
          <Button disabled={props.disabled || !props.fileName} onClick={props.onFresh}>
            {props.loading ? 'Preparing Report…' : 'Prepare Incident Report'}
          </Button>
        )}
      </div>
    </div>
  );
}
