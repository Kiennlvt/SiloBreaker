// Mirrors backend/app/api/serializers.py. The browser never computes scores itself.

export type Person = { id: string; display_name: string };

export type Bundle = {
  id: string;
  project_key: string;
  content_hash: string;
  source_inventory: Record<string, string>;
  coverage_start: string | null;
  coverage_end: string | null;
  item_count: number;
  people: Person[];
};

export type Handoff = {
  id: string;
  project_key: string;
  bundle_id: string;
  expert_id: string;
  successor_id: string;
};

export type Signal = number | null;
export type EvidenceRef = { chunk_id: string; quote: string; event?: string; document?: string };

export type Finding = {
  id: string;
  area_key: string;
  title: string;
  summary: string;
  question: string | null;
  signals: Record<"A" | "D" | "O" | "M" | "B", Signal>;
  counts: Record<string, number | null>;
  raw_score: number | null;
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
