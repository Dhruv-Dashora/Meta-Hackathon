import { SessionProvider } from './state/session';
import { useHealthOnce } from './hooks/useHealth';
import { AppShell } from './shell/AppShell';
import type { ViewId } from './shell/nav';
import { ErrorBoundary } from './ui/ErrorBoundary';
import HomePage from './pages/HomePage';
import UnifiedAnalysisPage from './pages/UnifiedAnalysisPage';
import IncidentReportsPage from './pages/IncidentReportsPage';

function Shell() {
  useHealthOnce();
  const views: Record<ViewId, React.ReactNode> = {
    home: <HomePage />,
    unified: <UnifiedAnalysisPage />,
    reports: <IncidentReportsPage />,
  };
  return <AppShell views={views} />;
}

export default function App() {
  return (
    <ErrorBoundary>
      <SessionProvider>
        <Shell />
      </SessionProvider>
    </ErrorBoundary>
  );
}
