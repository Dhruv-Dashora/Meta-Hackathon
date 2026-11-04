import { useState } from 'react';
import type { SegmentImageResponse } from '../types/segmentation';

const PALETTE = ['#22c55e', '#f59e0b', '#3b82f6', '#ef4444', '#a855f7', '#14b8a6'];

// Image + SVG overlay: masks (semi-transparent paths in mask-raster coords)
// and half-open boxes (source-image pixels), with per-object visibility toggles.
export default function SegmentationOverlay({
  imageUrl,
  result,
}: {
  imageUrl: string;
  result: SegmentImageResponse;
}) {
  const [hiddenIds, setHiddenIds] = useState<Set<string>>(new Set());
  const { width: imgW, height: imgH } = result.image;

  const toggle = (id: string) =>
    setHiddenIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const labelSize = Math.max(10, Math.round(imgW / 45));

  return (
    <div className="grid gap-3">
      <div className="relative inline-block justify-self-start border">
        <img src={imageUrl} alt="Annotated image" className="block max-w-full" />
        <svg
          className="pointer-events-none absolute inset-0 h-full w-full"
          viewBox={`0 0 ${imgW} ${imgH}`}
          preserveAspectRatio="none"
        >
          {result.detections.map((d, i) => {
            if (hiddenIds.has(d.object_id)) return null;
            const color = PALETTE[i % PALETTE.length];
            const w = d.box.x2 - d.box.x1;
            const h = d.box.y2 - d.box.y1;
            return (
              <g key={d.object_id}>
                {d.mask.svg_path && (
                  <svg
                    // Mask rasters are box-sized and box-local (W,H == box
                    // w,h): place at the box origin, 1:1. Path coords trace
                    // pixel corners in [-0.5, W-0.5], so the -0.5 viewBox
                    // origin lands mask edges exactly on the box rect.
                    x={d.box.x1}
                    y={d.box.y1}
                    width={w}
                    height={h}
                    viewBox={`-0.5 -0.5 ${d.mask.width} ${d.mask.height}`}
                    preserveAspectRatio="none"
                  >
                    <path
                      d={d.mask.svg_path}
                      fill={color}
                      fillOpacity={0.35}
                      stroke={color}
                      strokeOpacity={0.8}
                      strokeWidth={1}
                      vectorEffect="non-scaling-stroke"
                    />
                  </svg>
                )}
                <rect
                  x={d.box.x1}
                  y={d.box.y1}
                  width={w}
                  height={h}
                  fill="none"
                  stroke={color}
                  strokeWidth={2}
                  vectorEffect="non-scaling-stroke"
                />
                <text
                  x={d.box.x1}
                  y={Math.max(d.box.y1 - 2, labelSize)}
                  fontSize={labelSize}
                  fill={color}
                  stroke="white"
                  strokeWidth={0.5}
                >
                  {d.object_id}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      {result.detections.length > 0 ? (
        <ul className="grid gap-1 text-sm">
          {result.detections.map((d, i) => (
            <li key={d.object_id} className="flex items-center gap-2">
              <input
                type="checkbox"
                className="no-print"
                checked={!hiddenIds.has(d.object_id)}
                onChange={() => toggle(d.object_id)}
                aria-label={`Toggle region ${d.object_id}`}
              />
              <span
                className="inline-block h-3 w-3"
                style={{ backgroundColor: PALETTE[i % PALETTE.length] }}
              />
              <span>
                Region {d.object_id} — [{d.box.x1}, {d.box.y1}, {d.box.x2},{' '}
                {d.box.y2}] px
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <div className="grid gap-1">
          <p className="text-sm text-slate-600">
            No matching regions identified for this category.
          </p>
          <p className="text-sm text-slate-500">
            A lack of matching regions does not establish absence.
          </p>
        </div>
      )}
    </div>
  );
}
