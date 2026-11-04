import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';
import { Icons } from './icons';
import { NAV_ITEMS, useHashRoute, type ViewId } from './nav';

export function AppShell({ views }: { views: Record<ViewId, ReactNode> }) {
  const [active, navigate] = useHashRoute();
  const [collapsed, setCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);

  const wasOpen = useRef(false);
  useEffect(() => {
    if (drawerOpen) {
      closeRef.current?.focus();
    } else if (wasOpen.current) {
      document.getElementById('nav-open')?.focus();
    }
    wasOpen.current = drawerOpen;
  }, [drawerOpen]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setDrawerOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [setDrawerOpen]);

  const go = (id: ViewId) => {
    navigate(id);
    setDrawerOpen(false);
  };

  return (
    <div className="flex min-h-screen bg-slate-100 text-slate-900">
      <a
        href="#main-content"
        className="no-print sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      {/* Desktop sidebar */}
      <aside
        aria-label="Application"
        className={`no-print sticky top-0 hidden h-screen shrink-0 flex-col bg-slate-900 transition-[width] lg:flex ${
          collapsed ? 'w-16' : 'w-60'
        }`}
      >
        <div className="flex h-16 shrink-0 items-center gap-2 overflow-hidden px-4">
          <span aria-hidden className="flex h-8 w-8 shrink-0 items-center justify-center rounded bg-teal-600 text-lg font-bold text-white">
            H
          </span>
          {!collapsed && (
            <span className="truncate text-base font-semibold text-white">
              Himalayan Sentinel
            </span>
          )}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          <Sidebar active={active} collapsed={collapsed} onNavigate={go} />
        </div>
      </aside>

      {/* Mobile drawer */}
      {drawerOpen && (
        <div className="no-print fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <div
            aria-hidden
            className="absolute inset-0 bg-slate-900/50"
            onClick={() => setDrawerOpen(false)}
          />
          <aside className="absolute inset-y-0 left-0 flex w-72 flex-col bg-slate-900">
            <div className="flex h-16 shrink-0 items-center justify-between px-4">
              <span className="text-base font-semibold text-white">Himalayan Sentinel</span>
              <button
                ref={closeRef}
                type="button"
                onClick={() => setDrawerOpen(false)}
                aria-label="Close navigation"
                className="rounded-md p-2 text-slate-300 hover:bg-slate-800 hover:text-white"
              >
                <Icons.close />
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto">
              <Sidebar active={active} collapsed={false} onNavigate={go} />
            </div>
          </aside>
        </div>
      )}

      <div className="flex min-h-screen min-w-0 flex-1 flex-col">
        <TopBar
          active={active}
          sidebarCollapsed={collapsed}
          onToggleSidebar={() => setCollapsed(!collapsed)}
          onOpenDrawer={() => setDrawerOpen(true)}
        />
        <main id="main-content" className="mx-auto w-full max-w-7xl flex-1 p-4 md:p-6">
          {NAV_ITEMS.map((item) => (
            <div key={item.id} hidden={item.id !== active}>
              {views[item.id]}
            </div>
          ))}
        </main>
      </div>
    </div>
  );
}
