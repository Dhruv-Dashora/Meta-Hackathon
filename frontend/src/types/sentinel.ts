// Shared types mirroring backend/app/schemas/common.py (scaffold).
// Confidence is an UNCALIBRATED model signal — NOT a probability.

export type ReviewStatus = 'pending' | 'confirmed' | 'rejected' | 'needs_more_evidence';

export interface Confidence {
  value: number;
  scale: '0-1';
  calibrated: false;
}

export interface EvidenceRef {
  evidence_id: string;
  modality: 'image' | 'video_frame' | 'geojson' | 'hydromet' | 'report';
  uri_or_hash: string;
  captured_at?: string | null;
}

export interface Finding {
  finding_id: string;
  label: string;
  description?: string;
  confidence: Confidence;
  uncertainty_notes?: string;
  evidence_refs: EvidenceRef[];
  observed_at?: string | null;
  analyzed_at?: string | null;
  review_status: ReviewStatus;
}
