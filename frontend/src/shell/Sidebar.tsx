import { NAV_ITEMS, type ViewId, type ViewStatus } from './nav';
import { Icons, type IconName } from './icons';

const STATUS_DOT: Record<ViewStatus, string> = {
  live: 'bg-teal-400',
  limited: 'bg-amber-400',
  planned: 'bg-slate-500',
};

const ICONS: Record<ViewId, IconName> = {
  home: 'overview',
  unified: 'image',
  reports: 'reports',
};

export function Sidebar({
  active,
  collapsed,
  onNavigate,
}: {
  active: ViewId;
  collapsed: boolean;
  onNavigate: (id: ViewId) => void;
}) {
  return (
    <nav aria-label="Primary" className="flex h-full flex-col gap-1 p-3">
      {NAV_ITEMS.map((item) => {
        const Icon = Icons[ICONS[item.id]];
        const isActive = item.id === active;
        return (
          <button
            key={item.id}
            type="button"
            onClick={() => onNavigate(item.id)}
            aria-current={isActive ? 'page' : undefined}
            title={collapsed ? `${item.label} — ${item.blurb}` : undefined}
            className={`flex items-center gap-3 rounded-md px-3 py-2.5 text-left text-base transition-colors ${
              isActive
                ? 'bg-slate-700 font-medium text-white'
                : 'text-slate-300 hover:bg-slate-800 hover:text-white'
            } ${collapsed ? 'justify-center px-0' : ''}`}
          >
            <Icon />
            {!collapsed && (
              <>
                <span className="flex-1">{item.label}</span>
                <span
                  aria-label={item.status}
                  title={item.status}
                  className={`h-2 w-2 rounded-full ${STATUS_DOT[item.status]}`}
                />
              </>
            )}
          </button>
        );
      })}
    </nav>
  );
}
