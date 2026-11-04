import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { api } from '../api/client';
import type { IncidentDossier } from '../types/incident';
import type { SegmentImageResponse } from '../types/segmentation';
import type { Finding } from '../types/sentinel';
import type { UnifiedAnalysisResponse } from '../types/unified';

export interface FindingsResult {
  incident_id: string;
  findings: Finding[];
}

export interface BackendHealth {
  status: string;
  service: string;
}

export interface SessionStats {
  analyses: number;
  findings: number;
  regions: number;
}

interface StagedFile {
  file: File | null;
  previewUrl: string | null;
}

export interface SharedEvidence {
  file: File | null;
  previewUrl: string | null;
  unifiedResult: UnifiedAnalysisResponse | null;
  dossier: IncidentDossier | null;
}

interface SessionValue {
  health: BackendHealth | null;
  healthError: string | null;
  setHealth: (h: BackendHealth | null, error: string | null) => void;
  /** Shared evidence flow: one upload serves Unified Analysis + Reports. */
  evidence: SharedEvidence;
  setEvidenceFile: (f: File | null) => void;
  setEvidenceUnified: (r: UnifiedAnalysisResponse | null) => void;
  setEvidenceDossier: (d: IncidentDossier | null) => void;
  /** Backend browser-session id for cached-analysis reuse (lazy). */
  sessionId: string | null;
  ensureSessionId: () => Promise<string | null>;
  resetSessionId: () => void;
  intel: StagedFile & {
    findingsResult: FindingsResult | null;
    segResult: SegmentImageResponse | null;
    unifiedResult: UnifiedAnalysisResponse | null;
  };
  setIntelFile: (f: File | null) => void;
  setIntelFindings: (r: FindingsResult | null) => void;
  setIntelSeg: (r: SegmentImageResponse | null) => void;
  setIntelUnified: (r: UnifiedAnalysisResponse | null) => void;
  incident: StagedFile & { dossier: IncidentDossier | null };
  setIncidentFile: (f: File | null) => void;
  setIncidentDossier: (d: IncidentDossier | null) => void;
  stats: SessionStats;
  registerAnalysis: (counts: { findings: number; regions: number }) => void;
}

const SessionContext = createContext<SessionValue | null>(null);

function revoke(url: string | null) {
  if (url) URL.revokeObjectURL(url);
}

const SESSION_STORAGE_KEY = 'sentinel-session-id';

export function SessionProvider({ children }: { children: ReactNode }) {
  const [health, setHealthState] = useState<BackendHealth | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [evidenceFile, setEvidenceFileState] = useState<File | null>(null);
  const [evidencePreview, setEvidencePreview] = useState<string | null>(null);
  const [evidenceUnified, setEvidenceUnifiedState] = useState<UnifiedAnalysisResponse | null>(null);
  const [evidenceDossier, setEvidenceDossierState] = useState<IncidentDossier | null>(null);
  const [sessionId, setSessionIdState] = useState<string | null>(() => {
    try {
      return window.sessionStorage.getItem(SESSION_STORAGE_KEY);
    } catch {
      return null;
    }
  });
  const [intelFile, setIntelFileState] = useState<File | null>(null);
  const [intelPreview, setIntelPreview] = useState<string | null>(null);
  const [findingsResult, setFindingsResult] = useState<FindingsResult | null>(null);
  const [segResult, setSegResult] = useState<SegmentImageResponse | null>(null);
  const [unifiedResult, setUnifiedResult] = useState<UnifiedAnalysisResponse | null>(null);
  const [incidentFile, setIncidentFileState] = useState<File | null>(null);
  const [incidentPreview, setIncidentPreview] = useState<string | null>(null);
  const [dossier, setDossier] = useState<IncidentDossier | null>(null);
  const [stats, setStats] = useState<SessionStats>({ analyses: 0, findings: 0, regions: 0 });

  const setHealth = useCallback((h: BackendHealth | null, error: string | null) => {
    setHealthState(h);
    setHealthError(error);
  }, []);

  const setIntelFile = useCallback((f: File | null) => {
    setIntelFileState(f);
    setIntelPreview((prev) => {
      revoke(prev);
      return f ? URL.createObjectURL(f) : null;
    });
    setFindingsResult(null);
    setSegResult(null);
    setUnifiedResult(null);
  }, []);

  const setIntelFindings = useCallback((r: FindingsResult | null) => setFindingsResult(r), []);
  const setIntelSeg = useCallback((r: SegmentImageResponse | null) => setSegResult(r), []);
  const setIntelUnified = useCallback((r: UnifiedAnalysisResponse | null) => setUnifiedResult(r), []);

  const setIncidentFile = useCallback((f: File | null) => {
    setIncidentFileState(f);
    setIncidentPreview((prev) => {
      revoke(prev);
      return f ? URL.createObjectURL(f) : null;
    });
    setDossier(null);
  }, []);

  const setIncidentDossier = useCallback((d: IncidentDossier | null) => setDossier(d), []);

  const setEvidenceFile = useCallback((f: File | null) => {
    setEvidenceFileState(f);
    setEvidencePreview((prev) => {
      revoke(prev);
      return f ? URL.createObjectURL(f) : null;
    });
    setEvidenceUnifiedState(null);
    setEvidenceDossierState(null);
  }, []);

  const setEvidenceUnified = useCallback((r: UnifiedAnalysisResponse | null) => {
    setEvidenceUnifiedState(r);
    if (r === null) setEvidenceDossierState(null);
  }, []);

  const setEvidenceDossier = useCallback(
    (d: IncidentDossier | null) => setEvidenceDossierState(d),
    [],
  );

  const ensureSessionId = useCallback(async (): Promise<string | null> => {
    if (sessionId) return sessionId;
    try {
      const data = (await api.createSession()) as { session_id: string };
      setSessionIdState(data.session_id);
      try {
        window.sessionStorage.setItem(SESSION_STORAGE_KEY, data.session_id);
      } catch {
        /* storage unavailable — session id still works in memory */
      }
      return data.session_id;
    } catch {
      return null;
    }
  }, [sessionId]);

  const resetSessionId = useCallback(() => {
    setSessionIdState(null);
    try {
      window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
    } catch {
      /* ignore */
    }
  }, []);

  const registerAnalysis = useCallback((counts: { findings: number; regions: number }) => {
    setStats((s) => ({
      analyses: s.analyses + 1,
      findings: s.findings + counts.findings,
      regions: s.regions + counts.regions,
    }));
  }, []);

  const value = useMemo<SessionValue>(
    () => ({
      health,
      healthError,
      setHealth,
      evidence: {
        file: evidenceFile,
        previewUrl: evidencePreview,
        unifiedResult: evidenceUnified,
        dossier: evidenceDossier,
      },
      setEvidenceFile,
      setEvidenceUnified,
      setEvidenceDossier,
      sessionId,
      ensureSessionId,
      resetSessionId,
      intel: { file: intelFile, previewUrl: intelPreview, findingsResult, segResult, unifiedResult },
      setIntelFile,
      setIntelFindings,
      setIntelSeg,
      setIntelUnified,
      incident: { file: incidentFile, previewUrl: incidentPreview, dossier },
      setIncidentFile,
      setIncidentDossier,
      stats,
      registerAnalysis,
    }),
    [
      health,
      healthError,
      setHealth,
      evidenceFile,
      evidencePreview,
      evidenceUnified,
      evidenceDossier,
      setEvidenceFile,
      setEvidenceUnified,
      setEvidenceDossier,
      sessionId,
      ensureSessionId,
      resetSessionId,
      intelFile,
      intelPreview,
      findingsResult,
      segResult,
      unifiedResult,
      setIntelFile,
      setIntelFindings,
      setIntelSeg,
      setIntelUnified,
      incidentFile,
      incidentPreview,
      dossier,
      setIncidentFile,
      setIncidentDossier,
      stats,
      registerAnalysis,
    ],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error('useSession must be used inside SessionProvider');
  return ctx;
}
