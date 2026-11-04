import { useEffect, useState } from 'react';

export type ProgressStage = { upTo: number; label: string };

// Time-based estimate: the backend runs analysis as one blocking call,
// so the bar eases toward 95% and only hits 100% when the response lands.
// Deterministic in elapsed time so it always moves forward, never backward.
export function useSimulatedProgress(running: boolean, stages: ProgressStage[]) {
  const [elapsedMs, setElapsedMs] = useState(0);

  useEffect(() => {
    if (!running) return;
    setElapsedMs(0);
    const started = Date.now();
    const timer = window.setInterval(() => {
      setElapsedMs(Date.now() - started);
    }, 200);
    return () => window.clearInterval(timer);
  }, [running]);

  const eased = 95 * (1 - Math.exp(-elapsedMs / 18000));
  const percent = Math.min(95, Math.max(2, Math.round(eased)));
  const stage =
    stages.find((s) => percent <= s.upTo) ?? stages[stages.length - 1];

  return { percent, stageLabel: stage?.label ?? '', elapsedSec: Math.floor(elapsedMs / 1000) };
}
