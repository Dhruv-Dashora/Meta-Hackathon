import { useCallback, useRef } from 'react';

export interface TabDef {
  id: string;
  label: string;
}

// Segmented control with button semantics and arrow-key navigation.
export function Tabs({
  tabs,
  activeId,
  onChange,
  label,
}: {
  tabs: TabDef[];
  activeId: string;
  onChange: (id: string) => void;
  label: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent, index: number) => {
      let next: number | null = null;
      if (e.key === 'ArrowRight') next = (index + 1) % tabs.length;
      else if (e.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
      else if (e.key === 'Home') next = 0;
      else if (e.key === 'End') next = tabs.length - 1;
      if (next !== null) {
        e.preventDefault();
        onChange(tabs[next].id);
        refs.current[next]?.focus();
      }
    },
    [onChange, tabs],
  );

  return (
    <div
      role="tablist"
      aria-label={label}
      className="inline-flex gap-1 rounded-lg border border-slate-200 bg-white p-1 shadow-card"
    >
      {tabs.map((t, i) => (
        <button
          key={t.id}
          ref={(el) => {
            refs.current[i] = el;
          }}
          type="button"
          role="tab"
          aria-selected={t.id === activeId}
          tabIndex={t.id === activeId ? 0 : -1}
          onClick={() => onChange(t.id)}
          onKeyDown={(e) => onKeyDown(e, i)}
          className={`rounded-md px-4 py-2 text-base font-medium transition-colors ${
            t.id === activeId
              ? 'bg-slate-900 text-white'
              : 'text-slate-600 hover:bg-slate-100'
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
