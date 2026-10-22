// Mirrors backend/app/api/serializers.py. The browser never computes scores itself.

export type Person = { id: string; display_name: string };

export type Bundle = {
  id: string;
  project_key: string;
  content_hash: string;
  source_inventory: Record<string, string>;
  coverage_start: string | null;
  coverage_end: string | null;
  import_complete: boolean;
  item_count: number;
  people: Person[];
};

export type Handoff = {
  id: string;
  project_key: string;
  bundle_id: string;
  expert_id: string;
  successor_id: string;
  status?: string;
  created_at?: string;
};

export type HandoffRole = "admin" | "expert" | "successor";

export type HandoffSummary = Handoff & { viewer_role: HandoffRole };

export type HandoffDetail = HandoffSummary & {
  // Absent for the successor, who works from released exercises only.
  analyses?: { id: string; selected_engineer_id: string; created_at: string }[];
};

export type Signal = number | null;
export type SignalKey = "A" | "D" | "O" | "M" | "B";
export type EvidenceRef = { chunk_id: string; quote: string; event?: string; document?: string };

export type PriorKnowledge = { finding_id: string; version_id: string; version_no: number };

export type Finding = {
  id: string;
  area_key: string;
  title: string;
  summary: string;
  question: string | null;
  signals: Record<SignalKey, Signal>;
  counts: Record<string, number | null>;
  raw_score: number | null;
  // Score breakdown computed by the backend; the browser only draws it.
  weights: Record<SignalKey, number>;
  contributions: Record<SignalKey, number | null>;
  cap: number;
  reasons: string[];
  missing_facets: string[];
  top_candidate: boolean;
  review_priority: number | null;
  evidence_confidence: "high" | "medium" | "low";
  eligibility_status:
    | "ranked"
    | "adequately_covered"
    | "not_prioritized"
    | "insufficient"
    | "review_required";
  status: "candidate" | "confirmed" | "rejected" | "obsolete";
  status_reason: string | null;
  revision: number;
  evidence_refs: EvidenceRef[];
  // Approved knowledge for the same area from an earlier analysis of this handoff.
  prior_knowledge: PriorKnowledge | null;
};

export type Analysis = {
  id: string;
  selected_engineer_id: string;
  model_id: string;
  prompt_version: string;
  scoring_version: string;
  bundle_hash: string;
  rejected_areas: { area_key: string; problems: string[] }[];
  reused_extraction_from: string | null;
  findings: Finding[];
};

export type Chunk = {
  chunk_id: string;
  line_start: number | null;
  line_end: number | null;
  text: string;
  item: {
    source: string;
    source_type: string;
    external_id: string;
    author_display_name: string | null;
    occurred_at: string | null;
    title: string | null;
    url: string | null;
  };
};

export type KnowledgeContent = {
  applicability: string;
  prerequisites: string[];
  steps: string[];
  stop_and_escalate: string[];
  success_checks: string[];
  limitations: string[];
  unresolved: string[];
};

export type Draft = { id: string; revision: number; content: KnowledgeContent };

export type KnowledgeVersion = {
  id: string;
  finding_id: string;
  version_no: number;
  draft_revision: number;
  approved_content: KnowledgeContent;
  approved_by: string;
  approved_at: string;
  content_hash: string;
  supersedes_version_id: string | null;
};

export type FindingDetail = Finding & {
  handoff: Handoff;
  draft: Draft | null;
  versions: KnowledgeVersion[];
};

// ---------- Verify ----------
// The successor's view never contains criteria; `results` appears only after assessment.

export type Criterion = { id: string; text: string; critical: boolean; source_path: string };

export type Verdict = "met" | "partial" | "unmet" | "uncertain";
export type AggregateResult = "demonstrated" | "partial" | "not_yet" | "review_required";

export type CriterionResult = {
  criterion_id: string;
  text: string;
  verdict: Verdict;
  evidence_quote: string;
  critical?: boolean; // expert view only
  source_path?: string; // expert view only
};

export type Attempt = {
  id: string;
  exercise_id: string;
  knowledge_version_id: string;
  knowledge_version_no: number;
  successor_id: string;
  answer: string;
  assessment_status: "pending" | "succeeded" | "failed";
  assessment_error: string | null;
  aggregate_result: AggregateResult | null;
  results: CriterionResult[] | null;
  created_at: string;
  assessed_at: string | null;
};

export type Exercise = {
  id: string;
  knowledge_version_id: string;
  knowledge_version_no: number;
  status: "draft" | "ready" | "obsolete";
  scenario: string;
  approved_at: string | null;
  viewer_role: HandoffRole;
  attempts: Attempt[];
  // expert and admin view only
  revision?: number;
  approved_by?: string | null;
  generator_id?: string | null;
  criteria?: Criterion[];
};

// ---------- Accounts ----------

export type Role = "admin" | "member";

export type User = {
  id: string;
  username: string;
  display_name: string | null;
  role: Role;
  person_id: string | null;
};

export type AdminUser = User & { is_active: boolean; created_at: string; last_login_at: string | null };

export type Page<T> = { items: T[]; total: number; page: number; size: number };

export type AuditEvent = {
  id: number;
  handoff_id: string | null;
  actor_id: string;
  action: string;
  target_type: string;
  target_id: string;
  target_revision: number | null;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type MyExercise = {
  id: string;
  status: Exercise["status"];
  viewer_role: HandoffRole;
  handoff_id: string;
  project_key: string;
  finding_id: string;
  area_key: string;
  title: string;
  knowledge_version_id: string;
  knowledge_version_no: number;
  approved_at: string | null;
  latest_attempt: {
    id: string;
    assessment_status: Attempt["assessment_status"];
    aggregate_result: AggregateResult | null;
    created_at: string;
  } | null;
};

export type LibraryEntry = {
  version_id: string;
  version_no: number;
  finding_id: string;
  area_key: string;
  title: string;
  project_key: string;
  handoff_id: string;
  approved_by: string;
  approved_at: string;
};
