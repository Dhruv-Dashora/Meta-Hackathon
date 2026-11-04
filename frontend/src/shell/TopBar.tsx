import { useSession } from '../state/session';
import { assessmentStatusLabel } from '../ui/format';
import { NAV_ITEMS, type ViewId } from './nav';
import { Icons } from './icons';

export function TopBar({
  active,
  sidebarCollapsed,
  onToggleSidebar,
  onOpenDrawer,
}: {
  active: ViewId;
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
  onOpenDrawer: () => void;
}) {
  const { health, healthError, evidence } = useSession();
  const item = NAV_ITEMS.find((n) => n.id === active);
  const online = health?.status === 'ok';

  return (
    <header className="no-print flex h-16 shrink-0 items-center gap-3 border-b border-slate-200 bg-white px-4">
      <button
        id="nav-open"
        type="button"
        onClick={onOpenDrawer}
        aria-label="Open navigation"
        className="rounded-md p-2 text-slate-700 hover:bg-slate-100 lg:hidden"
      >
        <Icons.menu />
      </button>
      <button
        type="button"
        onClick={onToggleSidebar}
        aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        aria-expanded={!sidebarCollapsed}
        className="hidden rounded-md p-2 text-slate-700 hover:bg-slate-100 lg:block"
      >
        {sidebarCollapsed ? <Icons.expand /> : <Icons.collapse />}
      </button>
      <div className="min-w-0 flex-1">
        <h1 className="truncate text-xl font-semibold tracking-tight">
          {item?.label ?? 'Himalayan Sentinel'}
        </h1>
        {evidence.dossier && (
          <p className="truncate text-sm text-slate-600">
            Incident {evidence.dossier.incident_id} — {assessmentStatusLabel(evidence.dossier.incident_status)}
          </p>
        )}
      </div>
      <span
        role="status"
        title={healthError ? `Service: ${healthError}` : 'Service: available'}
        className={`inline-flex shrink-0 items-center gap-2 rounded-full px-3 py-1 text-sm font-medium ${
          online ? 'bg-green-100 text-green-800' : 'bg-amber-100 text-amber-800'
        }`}
      >
        <span
          aria-hidden
          className={`h-2 w-2 rounded-full ${online ? 'bg-green-600' : 'bg-amber-500'}`}
        />
        {online ? 'Service Available' : 'Service Unavailable'}
      </span>
    </header>
  );
}
