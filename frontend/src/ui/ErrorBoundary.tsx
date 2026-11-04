import { Component, type ReactNode } from 'react';
import { Button } from './Button';
import { Card } from './Card';

// Application-level error boundary: a rendering failure in any view
// shows this recoverable state instead of a blank application. It never
// fabricates results — it offers a retry and a full reload.
export class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error): { error: Error } {
    return { error };
  }

  componentDidCatch(error: Error): void {
    console.error('Himalayan Sentinel render error:', error);
  }

  private retry = (): void => {
    this.setState({ error: null });
  };

  private reload = (): void => {
    window.location.reload();
  };

  render(): ReactNode {
    const { error } = this.state;
    if (error) {
      return (
        <div className="mx-auto w-full max-w-2xl p-4 md:p-6">
          <Card>
            <h2 className="text-xl font-semibold tracking-tight">
              Something went wrong
            </h2>
            <p className="mt-1 text-slate-600">
              The application encountered an unexpected display error. No
              results have been changed — try again, or reload to restart
              from a clean state.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button type="button" onClick={this.retry}>
                Try Again
              </Button>
              <Button type="button" variant="secondary" onClick={this.reload}>
                Reload Application
              </Button>
            </div>
            <details className="mt-3 text-sm text-slate-600">
              <summary className="cursor-pointer text-teal-800 underline">
                Technical details
              </summary>
              <p className="mt-1 break-words">{error.message}</p>
            </details>
          </Card>
        </div>
      );
    }
    return this.props.children;
  }
}
