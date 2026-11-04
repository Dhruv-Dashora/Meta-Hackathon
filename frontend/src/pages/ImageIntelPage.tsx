import { useState } from 'react';
import { api } from '../api/client';
import { useSession, type FindingsResult } from '../state/session';
import FindingCard from '../components/FindingCard';
import SegmentationOverlay from '../components/SegmentationOverlay';
import { Badge } from '../ui/Badge';
import { Banner, Field, inputClass } from '../ui/Banner';
import { Button } from '../ui/Button';
import { Card, PageTitle } from '../ui/Card';
import { ConfidenceNote } from '../ui/ConfidenceHelp';
import { friendlyErrorMessage, plural } from '../ui/format';
import { EmptyState, ErrorState } from '../ui/States';
import {
  AnalysisProgress,
  FINDINGS_STAGES,
  SEGMENT_STAGES,
  UNIFIED_STAGES,
} from '../ui/ProgressBar';
import { Tabs } from '../ui/Tabs';
import type { SegmentImageResponse } from '../types/segmentation';
import type { UnifiedAnalysisResponse } from '../types/unified';

const PROMPT_EXAMPLES = ['road', 'river', 'building', 'vehicle'];

type TabId = 'findings' | 'segment' | 'unified';

const TABS = [
  { id: 'findings', label: 'Image findings' },
  { id: 'segment', label: 'SAM segmentation' },
  { id: 'unified', label: 'Unified analysis' },
];

// Image Intelligence: one shared upload, three analysis modes.
// Viewer (~62%) + compact control panel; results persist in session.
export default function ImageIntelPage() {
  const {
    intel,
    setIntelFile,
    setIntelFindings,
    setIntelSeg,
    setIntelUnified,
    registerAnalysis,
  } = useSession();
  const [tab, setTab] = useState<TabId>('findings');
  const [prompt, setPrompt] = useState('road');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hiddenPrompts, setHiddenPrompts] = useState<Set<string>>(new Set());

  const runFindings = async () => {
    if (!intel.file || loading) return;
    setLoading(true);
    setError(null);
    try {
      const data = (await api.analyzeImage(intel.file)) as FindingsResult;
      setIntelFindings(data);
      registerAnalysis({ findings: data.findings.length, regions: 0 });
    } catch (e) {
      setError(friendlyErrorMessage(e, 'Analysis failed.'));
    } finally {
      setLoading(false);
    }
  };

  const runSegment = async () => {
    if (!intel.file || !prompt.trim() || loading) return;
    setLoading(true);
    setError(null);
    try {
      const data = (await api.segmentImage(intel.file, prompt.trim())) as SegmentImageResponse;
      setIntelSeg(data);
      registerAnalysis({ findings: 0, regions: data.detections.length });
    } catch (e) {
      setError(friendlyErrorMessage(e, 'Segmentation failed.'));
    } finally {
      setLoading(false);
    }
  };

  const runUnified = async () => {
    if (!intel.file || loading) return;
    setLoading(true);
    setError(null);
    setHiddenPrompts(new Set());
    try {
      const data = (await api.analyzeAndSegment(intel.file)) as UnifiedAnalysisResponse;
      setIntelUnified(data);
      registerAnalysis({
        findings: data.findings.length,
        regions: data.segmentations.reduce((n, s) => n + s.detections.length, 0),
      });
    } catch (e) {
      setError(friendlyErrorMessage(e, 'Unified analysis failed.'));
    } finally {
      setLoading(false);
    }
  };

  const togglePrompt = (name: string) =>
    setHiddenPrompts((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });

  const { previewUrl, findingsResult, segResult, unifiedResult } = intel;

  return (
    <section>
      <PageTitle
        title="Image Intelligence"
        subtitle="Muse Spark findings and SAM 3.1 segmentation on one uploaded image."
      />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <Card className="min-w-0">
          <h3 className="mb-2 text-lg font-semibold">Viewer</h3>
          {!previewUrl && (
            <EmptyState
              title="No image yet"
              body="Upload a JPEG, PNG, or WebP image in the control panel to begin."
            />
          )}
          {previewUrl && tab === 'findings' && (
            <img src={previewUrl} alt="Uploaded evidence" className="block max-w-full rounded border" />
          )}
          {previewUrl && tab === 'segment' && segResult && (
            <SegmentationOverlay imageUrl={previewUrl} result={segResult} />
          )}
          {previewUrl && tab === 'segment' && !segResult && (
            <img src={previewUrl} alt="Uploaded evidence" className="block max-w-full rounded border" />
          )}
          {previewUrl && tab === 'unified' && unifiedResult && (
            <div className="grid gap-3">
              {unifiedResult.segmentations
                .filter((s) => !hiddenPrompts.has(s.prompt))
                .map((seg) => (
                  <div key={seg.prompt}>
                    {(seg.status === 'failed' || seg.status === 'skipped') && (
                      <p className="text-slate-600">
                        Layer “{seg.prompt}” unavailable: {seg.error ?? seg.status}
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
                  </div>
                ))}
            </div>
          )}
          {previewUrl && tab === 'unified' && !unifiedResult && (
            <img src={previewUrl} alt="Uploaded evidence" className="block max-w-full rounded border" />
          )}
          <p className="mt-2 text-sm text-slate-600">
            Segmentation shows geometry only (unverified). Damage, blockage, and
            people findings require agent assessment plus human review.
          </p>
        </Card>

        <div className="grid min-w-0 content-start gap-4">
          <Card>
            <Field label="Image">
              <input
                type="file"
                accept="image/jpeg,image/png,image/webp"
                onChange={(e) => {
                  setIntelFile(e.target.files?.[0] ?? null);
                  setError(null);
                }}
                className="text-base"
              />
            </Field>
            <div className="mt-3">
              <Tabs tabs={TABS} activeId={tab} onChange={(id) => setTab(id as TabId)} label="Analysis mode" />
            </div>

            {tab === 'findings' && (
              <div className="mt-3 grid gap-3">
                <p className="text-slate-600">
                  Muse Spark visual findings for this image (no segmentation).
                </p>
                <Button disabled={!intel.file || loading} onClick={runFindings}>
                  {loading ? 'Analyzing…' : 'Analyze image'}
                </Button>
                {findingsResult && (
                  <div className="grid gap-2">
                    <p>
                      <Badge tone="success">
                        {plural(findingsResult.findings.length, 'finding')}
                      </Badge>
                    </p>
                    <ConfidenceNote />
                    {findingsResult.findings.map((f, i) => (
                      <FindingCard key={f.finding_id} finding={f} sequence={i + 1} />
                    ))}
                  </div>
                )}
              </div>
            )}

            {tab === 'segment' && (
              <div className="mt-3 grid gap-3">
                <Field label="Prompt (one concrete object)">
                  <input
                    type="text"
                    value={prompt}
                    maxLength={120}
                    list="sam-prompt-examples"
                    onChange={(e) => setPrompt(e.target.value)}
                    className={inputClass}
                  />
                  <datalist id="sam-prompt-examples">
                    {PROMPT_EXAMPLES.map((p) => (
                      <option key={p} value={p} />
                    ))}
                  </datalist>
                </Field>
                <Button disabled={!intel.file || !prompt.trim() || loading} onClick={runSegment}>
                  {loading ? 'Segmenting…' : 'Segment image'}
                </Button>
                {segResult && (
                  <div className="grid gap-2">
                    <p>
                      Prompt “{segResult.prompt}” — {plural(segResult.detections.length, 'object')}
                      in a {segResult.image.width}×{segResult.image.height} image.
                    </p>
                    {segResult.warnings.map((w) => (
                      <p key={w} className="text-amber-800">
                        Warning: {w}
                      </p>
                    ))}
                  </div>
                )}
              </div>
            )}

            {tab === 'unified' && (
              <div className="mt-3 grid gap-3">
                <p className="text-slate-600">
                  Findings first, then targeted SAM segmentation of road, river,
                  building, and vehicle. Links are prompt-derived and unverified.
                </p>
                <Button disabled={!intel.file || loading} onClick={runUnified}>
                  {loading ? 'Analyzing…' : 'Analyze + segment'}
                </Button>
                {unifiedResult && (
                  <div className="grid gap-2">
                    <p>
                      Status: <Badge>{unifiedResult.workflow_status}</Badge>{' '}
                      {plural(unifiedResult.findings.length, 'finding')},{' '}
                      {plural(unifiedResult.segmentations.length, 'SAM prompt')}.
                    </p>
                    <ConfidenceNote />
                    {unifiedResult.warnings.map((w) => (
                      <p key={w} className="text-amber-800">
                        Warning: {w}
                      </p>
                    ))}
                    {unifiedResult.findings.map((f, i) => (
                      <FindingCard key={f.finding_id} finding={f} sequence={i + 1} />
                    ))}
                    <div className="flex flex-wrap gap-3">
                      {unifiedResult.segmentations.map((seg) => (
                        <label key={seg.prompt} className="flex items-center gap-1 text-base">
                          <input
                            type="checkbox"
                            checked={!hiddenPrompts.has(seg.prompt)}
                            onChange={() => togglePrompt(seg.prompt)}
                            aria-label={`Toggle ${seg.prompt} layer`}
                          />
                          {seg.prompt} ({seg.status})
                        </label>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {loading && (
              <AnalysisProgress
                key={tab}
                stages={
                  tab === 'segment'
                    ? SEGMENT_STAGES
                    : tab === 'unified'
                      ? UNIFIED_STAGES
                      : FINDINGS_STAGES
                }
              />
            )}
            {error && <ErrorState message={error} />}
          </Card>
          <Banner>
            Each button runs one backend analysis on the uploaded image. Switching
            tabs or pages never re-runs analysis.
          </Banner>
        </div>
      </div>
    </section>
  );
}
