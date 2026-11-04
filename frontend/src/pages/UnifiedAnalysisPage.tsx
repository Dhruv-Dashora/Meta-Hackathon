import { useState } from 'react';
import { api } from '../api/client';
import { useSession } from '../state/session';
import FindingCard from '../components/FindingCard';
import SegmentationOverlay from '../components/SegmentationOverlay';
import { Badge } from '../ui/Badge';
import { Banner, Field, inputClass } from '../ui/Banner';
import { Button } from '../ui/Button';
import { Card, PageTitle } from '../ui/Card';
import { ConfidenceNote } from '../ui/ConfidenceHelp';
import { friendlyErrorMessage, plural } from '../ui/format';
import { EmptyState, ErrorState } from '../ui/States';
import { AnalysisProgress, UNIFIED_STAGES } from '../ui/ProgressBar';
import type { PromptProvenance, PromptStatus, UnifiedAnalysisResponse } from '../types/unified';

// Hazard & Impact Analysis: one upload, one Analyze button, image
// analysis panel plus control panel. Requested regions render first.
const PROVENANCE_LABEL: Record<PromptProvenance, string> = {
  user_requested: 'Requested',
  automatic: 'Automatic',
  exploratory: 'Exploratory',
};

function RegionState({
  status,
  count,
  error,
}: {
  status: PromptStatus;
  count: number;
  error?: string | null;
}) {
  if (status === 'ok') {
    return <span className="text-sm text-slate-600">{plural(count, 'region')}</span>;
  }
  if (status === 'zero_matches') {
    return (
      <span className="grid gap-0.5">
        <span className="text-sm text-slate-600">
          No matching regions identified for this category.
        </span>
        <span className="text-sm text-slate-500">
          No match does not establish absence.
        </span>
      </span>
    );
  }
  return (
    <span className="grid gap-0.5">
      <span className="text-sm text-slate-600">
        {status === 'failed' ? 'Unavailable' : 'Not analyzed'}
      </span>
      {error && <span className="text-sm text-slate-500">{error}</span>}
    </span>
  );
}

export default function UnifiedAnalysisPage() {
  const {
    evidence,
    setEvidenceFile,
    setEvidenceUnified,
    ensureSessionId,
    resetSessionId,
    registerAnalysis,
  } = useSession();
  const [targets, setTargets] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sessionNote, setSessionNote] = useState<string | null>(null);
  const [hiddenPrompts, setHiddenPrompts] = useState<Set<string>>(new Set());

  const { file, previewUrl, unifiedResult } = evidence;

  const runAnalyze = async () => {
    if (!file || loading) return;
    // Match the backend targets contract (max 3, 40 chars each) so an
    // over-long focus area fails here with a clear message, not a 400.
    const terms = targets
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean);
    if (terms.length > 3) {
      setError('Enter at most 3 focus areas.');
      return;
    }
    if (terms.some((t) => t.length > 40)) {
      setError('Each focus area must be 40 characters or fewer.');
      return;
    }
    setLoading(true);
    setError(null);
    setSessionNote(null);
    setHiddenPrompts(new Set());
    try {
      const data = (await analyzeWithSession(file, targets)) as UnifiedAnalysisResponse;
      setEvidenceUnified(data);
      registerAnalysis({
        findings: data.findings.length,
        regions: data.segmentations.reduce((n, s) => n + s.detections.length, 0),
      });
    } catch (e) {
      // The image and focus areas stay in state, so retry needs no re-upload.
      setError(friendlyErrorMessage(e, 'Analysis failed.'));
    } finally {
      setLoading(false);
    }
  };

  const analyzeWithSession = async (image: File, rawTargets: string) => {
    let sessionId = await ensureSessionId();
    if (!sessionId) {
      setSessionNote(
        'Report reuse is unavailable. Analysis will continue; the incident report will require a new analysis.',
      );
    }
    try {
      return await api.analyzeAndSegment(image, rawTargets, sessionId);
    } catch (e) {
      // One retry with a fresh session: the stored id may predate a restart.
      if (sessionId && e instanceof Error && e.message.includes('invalid_session')) {
        resetSessionId();
        sessionId = await ensureSessionId();
        return await api.analyzeAndSegment(image, rawTargets, sessionId);
      }
      throw e;
    }
  };

  const togglePrompt = (name: string) =>
    setHiddenPrompts((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });

  const ordered = unifiedResult
    ? [...unifiedResult.segmentations].sort(
        (a, b) =>
          Number(b.provenance === 'user_requested') -
          Number(a.provenance === 'user_requested'),
      )
    : [];

  return (
    <section>
      <PageTitle
        title="Hazard & Impact Analysis"
        subtitle="Analyze disaster imagery to identify potential hazards, affected infrastructure, and areas requiring further assessment."
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <Card className="min-w-0">
          <h3 className="mb-2 text-lg font-semibold">Image Analysis</h3>
          {!previewUrl && (
            <EmptyState
              title="No image selected"
              body="Upload a JPEG, PNG, or WebP image in the control panel, then select Analyze Image."
            />
          )}
          {previewUrl && !unifiedResult && (
            <figure>
              <figcaption className="mb-1 text-sm font-medium text-slate-700">
                Original Image
              </figcaption>
              <img
                src={previewUrl}
                alt="Uploaded photograph"
                className="block max-w-full rounded border"
              />
            </figure>
          )}
          {previewUrl && unifiedResult && (
            <div className="grid gap-4">
              <figure>
                <figcaption className="mb-1 text-sm font-medium text-slate-700">
                  Original Image
                </figcaption>
                <img
                  src={previewUrl}
                  alt="Uploaded photograph"
                  className="block max-w-full rounded border"
                />
              </figure>
              {ordered
                .filter((s) => !hiddenPrompts.has(s.prompt))
                .map((seg) => (
                  <figure key={seg.prompt}>
                    <figcaption className="mb-1 text-sm font-medium text-slate-700">
                      Annotated Image — {seg.prompt}
                    </figcaption>
                    {(seg.status === 'failed' || seg.status === 'skipped') && (
                      <p className="text-slate-600">
                        Category “{seg.prompt}” unavailable
                        {seg.error ? `: ${seg.error}` : ''}
                      </p>
                    )}
                    {(seg.status === 'ok' || seg.status === 'zero_matches') && (
                      <SegmentationOverlay
                        imageUrl={previewUrl}
                        result={{
                          image: unifiedResult.image,
                          prompt: seg.prompt,
                          model: '',
                          detections: seg.detections,
                          warnings: [],
                        }}
                      />
                    )}
                  </figure>
                ))}
            </div>
          )}
          <p className="mt-2 text-sm text-slate-600">
            Outlined regions show visible areas only. They do not confirm
            damage, blockage, or exposure. Assessment and human review are
            required.
          </p>
        </Card>

        <div className="grid min-w-0 content-start gap-4">
          <Card>
            <Field label="Image (JPEG, PNG, WebP)">
              <input
                type="file"
                accept="image/jpeg,image/png,image/webp"
                onChange={(e) => {
                  setEvidenceFile(e.target.files?.[0] ?? null);
                  setError(null);
                  setSessionNote(null);
                }}
                className="text-base"
              />
            </Field>
            <div className="mt-3">
              <Field
                label="Focus Areas (Optional)"
                hint="Comma-separated, up to 3 (40 characters each)"
              >
                <input
                  type="text"
                  value={targets}
                  maxLength={130}
                  placeholder="e.g. house, debris"
                  onChange={(e) => setTargets(e.target.value)}
                  className={inputClass}
                />
              </Field>
              <p className="mt-1 text-sm text-slate-600">
                Leave blank for automatic detection. Your focus areas are
                analyzed first.
              </p>
            </div>
            <div className="mt-3">
              <Button type="button" disabled={!file || loading} onClick={runAnalyze}>
                {loading ? 'Analyzing Image…' : 'Analyze Image'}
              </Button>
            </div>
            <div className="mt-3 grid gap-2">
              {loading && <AnalysisProgress stages={UNIFIED_STAGES} />}
              {error && <ErrorState message={error} />}
              {sessionNote && <Banner>{sessionNote}</Banner>}
            </div>
          </Card>

          {unifiedResult && (
            <>
              <Card>
                <h3 className="text-lg font-semibold">
                  {plural(unifiedResult.findings.length, 'Visual Observation')}
                </h3>
                <div className="mt-1">
                  <ConfidenceNote />
                </div>
                {unifiedResult.findings.length > 0 ? (
                  <div className="mt-2 grid gap-2">
                    {unifiedResult.findings.map((f, i) => (
                      <FindingCard key={f.finding_id} finding={f} sequence={i + 1} />
                    ))}
                  </div>
                ) : (
                  <p className="mt-2 text-slate-600">
                    No visual observations identified in this image.
                  </p>
                )}
              </Card>

              <Card>
                <h3 className="text-lg font-semibold">Detected Regions</h3>
                {ordered.length > 0 ? (
                  <ul className="mt-2 grid gap-2">
                    {ordered.map((seg) => (
                      <li key={seg.prompt} className="grid gap-1">
                        <span className="flex flex-wrap items-center gap-2">
                          <label className="flex items-center gap-2">
                            <input
                              type="checkbox"
                              checked={!hiddenPrompts.has(seg.prompt)}
                              onChange={() => togglePrompt(seg.prompt)}
                              aria-label={`Toggle ${seg.prompt} regions`}
                            />
                            <strong>{seg.prompt}</strong>
                          </label>
                          <Badge tone={seg.provenance === 'user_requested' ? 'accent' : 'neutral'}>
                            {PROVENANCE_LABEL[seg.provenance]}
                          </Badge>
                        </span>
                        <RegionState
                          status={seg.status}
                          count={seg.detections.length}
                          error={seg.error}
                        />
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-2 text-slate-600">
                    No detectable categories identified in the visual observations.
                  </p>
                )}
                {unifiedResult.warnings.length > 0 && (
                  <ul className="mt-2 grid gap-1">
                    {unifiedResult.warnings.map((w) => (
                      <li key={w} className="text-sm text-amber-800">
                        {w}
                      </li>
                    ))}
                  </ul>
                )}
              </Card>

              <Card>
                <h3 className="text-lg font-semibold">Generate Incident Assessment</h3>
                <p className="mt-1 text-slate-600">
                  Prepare an incident report from this analysis. No re-upload
                  is required.
                </p>
                <div className="mt-2">
                  <Button
                    type="button"
                    onClick={() => {
                      window.location.hash = '#reports';
                    }}
                  >
                    Prepare Incident Report
                  </Button>
                </div>
              </Card>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
