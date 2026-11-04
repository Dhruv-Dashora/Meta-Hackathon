import type { ReactNode } from 'react';

type Tone = 'info' | 'warning';

const TONES: Record<Tone, string> = {
  info: 'border-sky-200 bg-sky-50 text-sky-900',
  warning: 'border-amber-200 bg-amber-50 text-amber-900',
};

export function Banner({
  tone = 'info',
  children,
}: {
  tone?: Tone;
  children: ReactNode;
}) {
  return (
    <div role="note" className={`rounded-lg border p-3 ${TONES[tone]}`}>
      {children}
    </div>
  );
}

export function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label className="grid gap-1 text-base">
      <span className="font-medium">{label}</span>
      {children}
      {hint && <span className="text-sm text-slate-600">{hint}</span>}
    </label>
  );
}

export const inputClass =
  'rounded-md border border-slate-300 bg-white px-3 py-2 text-base text-slate-900 placeholder:text-slate-400';
