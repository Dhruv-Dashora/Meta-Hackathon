import { useCallback, useEffect, useState } from 'react';

export type ViewId = 'home' | 'unified' | 'reports';

export type ViewStatus = 'live' | 'limited' | 'planned';

export interface NavItem {
  id: ViewId;
  label: string;
  hash: string;
  status: ViewStatus;
  blurb: string;
}

export const NAV_ITEMS: NavItem[] = [
  { id: 'home', label: 'Home', hash: '#home', status: 'live', blurb: 'Start here' },
  { id: 'unified', label: 'Hazard & Impact Analysis', hash: '#unified', status: 'live', blurb: 'Image assessment' },
  { id: 'reports', label: 'Incident Reports', hash: '#reports', status: 'live', blurb: 'Assessments and checklists' },
];

function hashToView(hash: string): ViewId | null {
  const found = NAV_ITEMS.find((n) => n.hash === hash);
  return found ? found.id : null;
}

// Hash-synced view state: deep-linkable, back-button friendly, zero deps.
// Unknown hashes (e.g. in-page anchors like #verify-exp-1) are ignored so
// anchor links never switch views.
export function useHashRoute(): [ViewId, (id: ViewId) => void] {
  const [view, setView] = useState<ViewId>(() => {
    if (typeof window === 'undefined') return 'home';
    return hashToView(window.location.hash) ?? 'home';
  });

  useEffect(() => {
    const onChange = () => {
      const next = hashToView(window.location.hash);
      if (next) setView(next);
    };
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);

  const navigate = useCallback((id: ViewId) => {
    const item = NAV_ITEMS.find((n) => n.id === id);
    if (!item) return;
    if (window.location.hash !== item.hash) window.location.hash = item.hash;
    else setView(id);
  }, []);

  return [view, navigate];
}
