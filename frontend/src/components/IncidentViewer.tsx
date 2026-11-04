import { useState } from 'react';
import SegmentationOverlay from './SegmentationOverlay';
import { plural } from '../ui/format';
import type { IncidentDossier } from '../types/incident';

// Annotated viewer for the uploaded photograph with its already-produced
// region layers. Reuses SegmentationOverlay, so box-local mask placement
// is identical to the proven overlay. Toggling layers never calls any API.
function layerStateLabel(
  status: string,
  count: number,
  error?: string | null,
): string {
  if (status === 'ok') return plural(count, 'region');
  if (status === 'zero_matches') return 'No matching regions';
  if (status === 'failed') return `Unavailable${error ? `: ${error}` : ''}`;
  return `Not analyzed${error ? `: ${error}` : ''}`;
}

export default function IncidentViewer({
  imageUrl,
  dossier,
}: {
  imageUrl: string;
  dossier: IncidentDossier;
}) {
  const [hiddenPrompts, setHiddenPrompts] = useState<Set<string>>(new Set());

  const toggle = (prompt: string) =>
    setHiddenPrompts((prev) => {
      const next = new Set(prev);
      if (next.has(prompt)) next.delete(prompt);
      else next.add(prompt);
      return next;
    });

  if (dossier.segmentations.length === 0) {
    return (
      <div>
        <figure>
          <figcaption className="mb-1 text-sm font-medium text-slate-700">
            Original Image
          </figcaption>
          <img
            src={imageUrl}
            alt="Uploaded incident photograph"
            className="print-image block max-w-full border"
          />
        </figure>
        <p className="mt-1 text-sm text-slate-600">
          No detected regions were produced for this image (visual
          observations only).
        </p>
      </div>
    );
  }

  // Print shows the base photograph with a layer-status caption instead
  // of the interactive toggles: toggling is impossible on paper, and the
  // visible layers are whatever is checked at print time.
  const layerCaption = dossier.segmentations
    .map((seg) => `“${seg.prompt}” (${layerStateLabel(seg.status, seg.detections.length, seg.error)})`)
    .join('; ');

  return (
    <div className="grid gap-2">
      <div className="no-print flex flex-wrap gap-3">
        {dossier.segmentations.map((seg) => (
          <label key={seg.prompt} className="flex items-center gap-1 text-sm">
            <input
              type="checkbox"
              checked={!hiddenPrompts.has(seg.prompt)}
              onChange={() => toggle(seg.prompt)}
              aria-label={`Toggle ${seg.prompt} regions`}
            />
            <span>
              {seg.prompt} ({seg.status === 'ok' ? String(seg.detections.length) : layerStateLabel(seg.status, 0)})
            </span>
          </label>
        ))}
      </div>
      <p className="print-only text-sm">
        Detected regions at print time: {layerCaption}.
      </p>
      <figure>
        <figcaption className="mb-1 text-sm font-medium text-slate-700">
          Original Image
        </figcaption>
        <img
          src={imageUrl}
          alt="Uploaded incident photograph"
          className="print-image block max-w-full border"
        />
      </figure>
      {dossier.segmentations.map(
        (seg) =>
          !hiddenPrompts.has(seg.prompt) && (
            <figure key={seg.prompt} className="print-figure">
              <figcaption className="mb-1 text-sm font-medium text-slate-700">
                Annotated Image — {seg.prompt}
              </figcaption>
              {(seg.status === 'failed' || seg.status === 'skipped') && (
                <p className="text-sm text-slate-600">
                  Category “{seg.prompt}” unavailable
                  {seg.error ? `: ${seg.error}` : ''}
                </p>
              )}
              {(seg.status === 'ok' || seg.status === 'zero_matches') && (
                <SegmentationOverlay
                  imageUrl={imageUrl}
                  result={{
                    image: dossier.image,
                    prompt: seg.prompt,
                    model: '',
                    detections: seg.detections,
                    warnings: [],
                  }}
                />
              )}
            </figure>
          ),
      )}
      <p className="text-sm text-slate-600">
        Outlined regions are visual guides only and never confirm an
        observation. Toggling regions does not run new analysis.
      </p>
    </div>
  );
}
