// Types mirroring backend/app/schemas/unified_analysis.py.
// Linkage is prompt_trigger_only: a SAM detection NEVER confirms a finding.

import type { Finding } from './sentinel';
import type { SegmentDetection, SegmentImageInfo } from './segmentation';

export type PromptStatus = 'ok' | 'zero_matches' | 'failed' | 'skipped';
export type WorkflowStatus = 'completed' | 'partial' | 'vision_only';
export type PromptProvenance = 'user_requested' | 'automatic' | 'exploratory';

export interface PromptDecision {
  prompt: string;
  triggered_by: string[];
  matched_keywords: string[];
  provenance: PromptProvenance;
  requested_as?: string | null;
}

export interface PromptSegmentation {
  prompt: string;
  linked_finding_ids: string[];
  association: 'prompt_trigger_only';
  status: PromptStatus;
  error?: string | null;
  detections: SegmentDetection[];
  provenance: PromptProvenance;
}

export interface UnifiedAnalysisResponse {
  incident_id: string;
  image: SegmentImageInfo;
  findings: Finding[];
  prompt_plan: PromptDecision[];
  segmentations: PromptSegmentation[];
  workflow_status: WorkflowStatus;
  warnings: string[];
  user_targets: string[];
  analysis_ref?: string | null;
}
