import { useSimulatedProgress, type ProgressStage } from '../hooks/useSimulatedProgress';

export const UNIFIED_STAGES: ProgressStage[] = [
  { upTo: 8, label: 'Uploading image' },
  { upTo: 55, label: 'Detecting visual findings' },
  { upTo: 65, label: 'Planning segmentation prompts' },
  { upTo: 93, label: 'Segmenting regions' },
  { upTo: 100, label: 'Finalizing results' },
];

export const FINDINGS_STAGES: ProgressStage[] = [
  { upTo: 10, label: 'Uploading image' },
  { upTo: 88, label: 'Detecting visual findings' },
  { upTo: 100, label: 'Finalizing results' },
];

export const SEGMENT_STAGES: ProgressStage[] = [
  { upTo: 10, label: 'Uploading image' },
  { upTo: 90, label: 'Segmenting regions' },
  { upTo: 100, label: 'Finalizing results' },
];

export const DOSSIER_STAGES: ProgressStage[] = [
  { upTo: 10, label: 'Uploading image' },
  { upTo: 60, label: 'Analyzing visual evidence' },
  { upTo: 88, label: 'Assessing impact' },
  { upTo: 100, label: 'Preparing report' },
];

export function ProgressBar({ value, label }: { value: number; label: string }) {
  const clamped = Math.min(100, Math.max(0, Math.round(value)));
  return (
    <div className="grid gap-1" role="status" aria-live="polite">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-slate-700">{label}</p>
        <p className="text-slate-700 tabular-nums" aria-hidden="true">
          {clamped}%
        </p>
      </div>
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={clamped}
        aria-label={label}
        className="h-2.5 overflow-hidden rounded-full bg-slate-200"
      >
        <div
          className="h-full rounded-full bg-teal-700 transition-[width] duration-200 ease-out"
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  );
}

// Live progress readout for one blocking analysis call. The percentage is
// an estimate that always advances, proving the tool is still working
// rather than stuck.
export function AnalysisProgress({ stages }: { stages: ProgressStage[] }) {
  const { percent, stageLabel } = useSimulatedProgress(true, stages);
  return <ProgressBar value={percent} label={stageLabel} />;
}
