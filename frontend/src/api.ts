import type {
  Analysis,
  Bundle,
  Chunk,
  Draft,
  FindingDetail,
  Handoff,
  KnowledgeContent,
  KnowledgeVersion,
  Finding,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

async function call<T>(method: string, path: string, body?: unknown, idempotent = false): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (idempotent) headers["Idempotency-Key"] = crypto.randomUUID();
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "network", "Cannot reach the SiloBreaker API. Is the backend running?");
  }
  const text = await res.text();
  if (!res.ok) {
    let code = "http_error";
    let detail = text || res.statusText;
    try {
      const j = JSON.parse(text);
      if (j.error) ({ code, detail } = j.error);
      else if (j.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, code, detail);
  }
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("json") ? JSON.parse(text) : text) as T;
}

export const api = {
  reset: () => call<Bundle>("POST", "/demo/reset"),
  importBundle: () => call<Bundle>("POST", "/bundles/import"),
  createHandoff: (b: { bundle_id: string; expert_id: string; successor_id: string }) =>
    call<Handoff>("POST", "/handoffs", b),
  analyze: (handoffId: string, selected: string) =>
    call<Analysis>("POST", `/handoffs/${handoffId}/analyses`, { selected_engineer_id: selected }, true),
  getAnalysis: (id: string) => call<Analysis>("GET", `/analyses/${id}`),
  chunk: (id: string) => call<Chunk>("GET", `/chunks/${id}`),
  finding: (id: string) => call<FindingDetail>("GET", `/findings/${id}`),
  review: (id: string, b: { action: string; reason: string; expected_revision: number; actor_id: string; corrected_summary?: string }) =>
    call<Finding>("POST", `/findings/${id}/review`, b),
  structure: (id: string, answer: string) =>
    call<KnowledgeContent>("POST", `/findings/${id}/structure`, { answer }),
  saveDraft: (id: string, b: { content: KnowledgeContent; expected_revision: number | null; author_id: string }) =>
    call<Draft>("PUT", `/findings/${id}/draft`, b),
  publish: (id: string, b: { expected_finding_revision: number; draft_revision: number; approver_id: string }) =>
    call<KnowledgeVersion>("POST", `/findings/${id}/publish`, b, true),
  okf: (versionId: string) => call<string>("GET", `/knowledge/${versionId}/okf`),
};
