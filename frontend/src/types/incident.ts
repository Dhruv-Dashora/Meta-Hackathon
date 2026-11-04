// Types mirroring backend/app/schemas/incident.py.
// Exposure concerns are always conditional and unverified; geo context is
// always operator-provided and unverified.

import type { Finding } from './sentinel';
import type { SegmentImageInfo } from './segmentation';
import type {
  PromptSegmentation,
  PromptStatus,
  WorkflowStatus,
} from './unified';

export type IncidentStatus = 'completed' | 'partial';
export type GeoStatus = 'provided' | 'unavailable';
export type AgentStepStatus = 'ok' | 'failed' | 'skipped';
export type ActionPriority = 'high' | 'medium' | 'low';

export interface GeoContext {
  status: GeoStatus;
  location_label: string;
  latitude?: number | null;
  longitude?: number | null;
  geojson_feature_count?: number | null;
  provenance: 'operator-provided, unverified';
  note: string;
}

export type HazardCategory =
  | 'observed_feature'
  | 'mechanism'
  | 'visible_damage'
  | 'exposed_infrastructure'
  | 'human_exposure'
  | 'unknown'
  | 'unclassified';

export interface ObservedHazard {
  hazard_id: string;
  finding_ids: string[];
  evidence_ids: string[];
  summary: string;
  category?: HazardCategory;
}

export interface ExposureConcern {
  concern_id: string;
  condition: string;
  concern: string;
  basis_finding_ids: string[];
  basis_evidence_ids: string[];
  status: 'unverified';
  verification_action_id: string;
  feature: string;
}

export type DamageCategory =
  | 'no_visible_damage'
  | 'possible_damage'
  | 'apparent_major_damage'
  | 'cannot_assess';

export interface DamageAssessment {
  assessment_id: string;
  feature: string;
  target_label: string;
  basis_finding_ids: string[];
  basis_evidence_ids: string[];
  category: DamageCategory;
  rationale: string;
  provisional: true;
  uncertainty_note: string;
  // Structured narrative fields from refined damage reads. Optional
  // for forward compatibility with older cached payloads.
  observed_condition?: string;
  condition_class?: string;
  recommended_verification?: string;
}

export type RescuePriority = 'high' | 'medium' | 'low' | 'undetermined';

export interface RescueAttention {
  attention_id: string;
  priority: RescuePriority;
  basis_finding_ids: string[];
  basis_evidence_ids: string[];
  rationale: string;
  unknowns?: string;
  requires_human_review: true;
}

export interface AccessAttention {
  attention_id: string;
  priority: RescuePriority;
  basis_finding_ids: string[];
  basis_evidence_ids: string[];
  rationale: string;
  unknowns?: string;
  requires_human_review: true;
}

export interface ReviewAttention {
  review_id: string;
  priority: RescuePriority;
  basis_finding_ids: string[];
  basis_evidence_ids: string[];
  rationale: string;
  unknowns?: string;
  requires_human_review: true;
}

export interface VerificationAction {
  action_id: string;
  action: string;
  reason: string;
  // Concise structured heading from the backend (derived from the task
  // type). Optional for forward compatibility with older payloads.
  title?: string;
  priority: ActionPriority;
  related_finding_ids: string[];
  what: string;
  why_operational: string;
  unknown: string;
  method: string;
  priority_reason: string;
  kind?:
    | 'concern_review'
    | 'finding_review'
    | 'people_safety'
    | 'segmentation_review'
    | 'geo_context'
    | 'routine';
  concern_id?: string | null;
  prompt?: string | null;
}

export interface SituationSummary {
  headline: string;
  observed: string;
  unknowns: string;
}

export interface FindingGroup {
  group_id: string;
  title: string;
  finding_ids: string[];
  evidence_ids: string[];
}

export interface InformationGap {
  topic: string;
  detail: string;
  why_matters: string;
  status: 'unknown' | 'unverified' | 'verified';
}

export interface AgentTrailEntry {
  agent: string;
  status: AgentStepStatus;
  duration_s: number;
  notes: string;
}

export interface SegmentationSummary {
  prompt: string;
  status: PromptStatus;
  detection_count: number;
  linked_finding_ids: string[];
  provenance?: string;
}

export interface EvidenceLedgerEntry {
  evidence_id: string;
  modality: string;
  source: string;
}

export interface IncidentDossier {
  incident_id: string;
  image: SegmentImageInfo;
  analysis_ref?: string | null;
  vision_source: 'fresh_analysis' | 'cached_reuse';
  vision_workflow_status: WorkflowStatus;
  incident_status: IncidentStatus;
  situation_summary: SituationSummary;
  findings: Finding[];
  finding_groups: FindingGroup[];
  information_gaps: InformationGap[];
  segmentation_summary: SegmentationSummary[];
  segmentations: PromptSegmentation[];
  observed_hazards: ObservedHazard[];
  exposure_concerns: ExposureConcern[];
  damage_assessments: DamageAssessment[];
  rescue_priorities: RescueAttention[];
  access_priorities?: AccessAttention[];
  review_priorities?: ReviewAttention[];
  // Dossier sections with partial content loss: when non-empty, read
  // those sections with extra care (backend contract).
  degraded_sections?: string[];
  geo_context: GeoContext;
  uncertainty_notes: string[];
  verification_actions: VerificationAction[];
  evidence_ledger: EvidenceLedgerEntry[];
  agent_trail: AgentTrailEntry[];
  warnings: string[];
}
