// API client (scaffold). No secrets in frontend — backend base URL only.
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '';

async function request(path: string, init?: RequestInit) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
  return res.json();
}

async function upload(path: string, form: FormData, headers?: Record<string, string>) {
  // No explicit Content-Type: fetch sets the multipart boundary itself.
  const res = await fetch(`${BASE_URL}${path}`, { method: 'POST', body: form, headers });
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`API ${res.status}: ${path}${detail ? ` — ${detail}` : ''}`);
  }
  return res.json();
}

export const SESSION_HEADER = 'x-session-id';

export const api = {
  health: () => request('/api/health'),
  createSession: () => request('/api/session', { method: 'POST' }),
  analyzeImage: (image: File) => {
    const form = new FormData();
    form.append('image', image);
    return upload('/api/disaster-response/analyze-image', form);
  },
  segmentImage: (image: File, prompt: string) => {
    const form = new FormData();
    form.append('image', image);
    form.append('prompt', prompt);
    return upload('/api/disaster-response/segment-image', form);
  },
  analyzeAndSegment: (image: File, targets?: string, sessionId?: string | null) => {
    const form = new FormData();
    form.append('image', image);
    if (targets?.trim()) form.append('targets', targets.trim());
    const headers = sessionId ? { [SESSION_HEADER]: sessionId } : undefined;
    return upload('/api/disaster-response/analyze-and-segment', form, headers);
  },
  assessIncidentFromAnalysis: (
    analysisRef: string,
    sessionId: string,
    opts: {
      locationLabel?: string;
      latitude?: number | null;
      longitude?: number | null;
      geojson?: Record<string, unknown> | null;
    } = {},
  ) =>
    request('/api/disaster-response/assess-incident-from-analysis', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', [SESSION_HEADER]: sessionId },
      body: JSON.stringify({
        analysis_ref: analysisRef,
        location_label: opts.locationLabel ?? '',
        latitude: opts.latitude ?? null,
        longitude: opts.longitude ?? null,
        geojson: opts.geojson ?? null,
      }),
    }),
  assessIncident: (
    image: File,
    opts: {
      locationLabel?: string;
      latitude?: string;
      longitude?: string;
      geojson?: File | null;
    } = {},
  ) => {
    const form = new FormData();
    form.append('image', image);
    if (opts.locationLabel) form.append('location_label', opts.locationLabel);
    if (opts.latitude) form.append('latitude', opts.latitude);
    if (opts.longitude) form.append('longitude', opts.longitude);
    if (opts.geojson) form.append('geojson', opts.geojson);
    return upload('/api/disaster-response/assess-incident', form);
  },
  earlyWarning: (body: Record<string, unknown>) =>
    request('/api/early-warning/analyze', { method: 'POST', body: JSON.stringify(body) }),
  disasterAssess: (body: Record<string, unknown>) =>
    request('/api/disaster-response/assess', { method: 'POST', body: JSON.stringify(body) }),
  verificationQueue: () => request('/api/verification/queue'),
  report: (incidentId: string) => request(`/api/reports/${incidentId}`),
};
