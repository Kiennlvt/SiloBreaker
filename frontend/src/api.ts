import type {
  Analysis,
  Attempt,
  Criterion,
  Exercise,
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
    // Safe identifiers the backend adds to recover, e.g. attempt_id after a provider failure.
    public extra: Record<string, string> = {},
  ) {
    super(message);
  }
}

const PROVIDER_CODES = new Set(["provider_error", "provider_timeout", "provider_not_configured"]);

export type ErrorKind = "stale" | "provider" | "network" | "other";

/** Classifies an error so stale data and provider failures get their own message. */
export function describeError(e: unknown): { kind: ErrorKind; message: string } {
  if (!(e instanceof ApiError)) return { kind: "other", message: String(e) };
  if (e.status === 409 && e.code === "stale_revision")
    return { kind: "stale", message: "This data has changed. Reload to see the latest version." };
  if (e.status >= 500 && PROVIDER_CODES.has(e.code)) {
    const what =
      e.code === "provider_timeout"
        ? "The AI provider did not answer in time"
        : e.code === "provider_not_configured"
          ? "The AI provider is not configured"
          : "The AI provider failed";
    return {
      kind: "provider",
      message: `${what}. This is a system error, not a result about anyone's knowledge. (${e.code})`,
    };
  }
  if (e.code === "network") return { kind: "network", message: e.message };
  return { kind: "other", message: `${e.message} (${e.code})` };
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
    let extra: Record<string, string> = {};
    try {
      const j = JSON.parse(text);
      if (j.error) ({ code, detail, ...extra } = j.error);
      else if (j.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, code, detail, extra);
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

  // Verify. Reads pass viewer_id; the backend decides what that viewer may see.
  createExercise: (versionId: string, actor: string) =>
    call<Exercise>("POST", `/knowledge/${versionId}/exercises`, { actor_id: actor }, true),
  listExercises: (versionId: string, viewer: string) =>
    call<Exercise[]>("GET", `/knowledge/${versionId}/exercises?viewer_id=${encodeURIComponent(viewer)}`),
  getExercise: (id: string, viewer: string) =>
    call<Exercise>("GET", `/exercises/${id}?viewer_id=${encodeURIComponent(viewer)}`),
  saveExerciseDraft: (
    id: string,
    b: { scenario: string; criteria: Criterion[]; expected_revision: number; actor_id: string },
  ) => call<Exercise>("PUT", `/exercises/${id}/draft`, b),
  approveExercise: (id: string, b: { expected_revision: number; actor_id: string }) =>
    call<Exercise>("POST", `/exercises/${id}/approve`, b),
  submitAttempt: (exerciseId: string, b: { actor_id: string; answer: string }) =>
    call<Attempt>("POST", `/exercises/${exerciseId}/attempts`, b, true),
  getAttempt: (id: string, viewer: string) =>
    call<Attempt>("GET", `/attempts/${id}?viewer_id=${encodeURIComponent(viewer)}`),
  reassess: (id: string, actor: string) => call<Attempt>("POST", `/attempts/${id}/reassess`, { actor_id: actor }),
};
