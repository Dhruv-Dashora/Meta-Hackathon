import { useEffect } from 'react';
import { api } from '../api/client';
import { useSession } from '../state/session';

// One cheap health check per session (no model cost). Never refetches models.
export function useHealthOnce() {
  const { health, healthError, setHealth } = useSession();

  useEffect(() => {
    let cancelled = false;
    if (health || healthError) return;
    api
      .health()
      .then((h) => {
        if (!cancelled) setHealth(h as { status: string; service: string }, null);
      })
      .catch((e: unknown) => {
        if (!cancelled) setHealth(null, e instanceof Error ? e.message : 'Unreachable');
      });
    return () => {
      cancelled = true;
    };
  }, [health, healthError, setHealth]);
}
