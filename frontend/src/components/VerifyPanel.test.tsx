import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../api";
import type { Attempt, Exercise } from "../types";
import VerifyPanel from "./VerifyPanel";

const SCENARIO = "You are on call for settlement recovery. Describe what you do.";
const CRITERIA = [
  { id: "C1", text: "Do not create a new settlement when ACCEPTED", critical: true, source_path: "stop_and_escalate[0]" },
  { id: "C2", text: "Check the provider transaction state", critical: false, source_path: "steps[0]" },
  { id: "C3", text: "Ledger shows exactly one settlement", critical: false, source_path: "success_checks[0]" },
];

const base = {
  id: "ex1",
  knowledge_version_id: "v1",
  knowledge_version_no: 1,
  status: "ready" as const,
  scenario: SCENARIO,
  approved_at: "2026-10-13T00:00:00Z",
  attempts: [] as Attempt[],
};
// What the backend returns to each role: the successor payload has no criteria at all.
const expertView: Exercise = { ...base, viewer_role: "expert", revision: 2, criteria: CRITERIA, generator_id: "offline" };
const successorView: Exercise = { ...base, viewer_role: "successor" };

const graded: Attempt = {
  id: "a1",
  exercise_id: "ex1",
  knowledge_version_id: "v1",
  knowledge_version_no: 1,
  successor_id: "bob",
  answer: "I would retry it.",
  assessment_status: "succeeded",
  assessment_error: null,
  aggregate_result: "not_yet",
  results: [{ criterion_id: "C1", text: CRITERIA[0].text, verdict: "unmet", evidence_quote: "" }],
  created_at: "2026-10-13T00:00:00Z",
  assessed_at: "2026-10-13T00:00:01Z",
};

afterEach(() => vi.restoreAllMocks());

function renderPanel(role: "expert" | "successor") {
  return render(<VerifyPanel versionId="v1" versionNo={1} expertId="alice" successorId="bob" initialRole={role} />);
}

describe("VerifyPanel", () => {
  it("never renders the rubric in the successor view", async () => {
    const list = vi.spyOn(api, "listExercises").mockResolvedValue([successorView]);
    const { container } = renderPanel("successor");
    expect(await screen.findByText(SCENARIO)).toBeInTheDocument();
    expect(list).toHaveBeenCalledWith("v1", "bob");
    expect(screen.getByLabelText("Your answer")).toBeInTheDocument();
    const html = container.innerHTML.toLowerCase();
    expect(html).not.toContain("rubric");
    expect(html).not.toContain("critical");
    for (const c of CRITERIA) expect(container.textContent).not.toContain(c.text);
  });

  it("shows the rubric to the expert and switches viewer by role", async () => {
    const list = vi
      .spyOn(api, "listExercises")
      .mockImplementation(async (_v, viewer) => (viewer === "alice" ? [expertView] : [successorView]));
    renderPanel("expert");
    expect(await screen.findByText(/Private rubric/)).toBeInTheDocument();
    expect(screen.getByDisplayValue(CRITERIA[0].text)).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Successor (bob)"));
    await screen.findByLabelText("Your answer");
    expect(list).toHaveBeenLastCalledWith("v1", "bob");
    expect(screen.queryByText(/Private rubric/)).not.toBeInTheDocument();
  });

  it("shows criterion-level results from the backend and lets the successor retry", async () => {
    vi.spyOn(api, "listExercises")
      .mockResolvedValueOnce([successorView])
      .mockResolvedValue([{ ...successorView, attempts: [graded] }]);
    const submit = vi.spyOn(api, "submitAttempt").mockResolvedValue(graded);
    renderPanel("successor");
    await userEvent.type(await screen.findByLabelText("Your answer"), "I would retry it.");
    await userEvent.click(screen.getByRole("button", { name: "Submit answer" }));
    expect(submit).toHaveBeenCalledWith("ex1", { actor_id: "bob", answer: "I would retry it." });
    expect(await screen.findByText("Not yet demonstrated")).toBeInTheDocument();
    expect(screen.getByText(CRITERIA[0].text, { exact: false })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Thử lại" }));
    expect(screen.getByLabelText("Your answer")).toHaveValue("");
  });

  it("reports a provider failure as a system error, not a result", async () => {
    const failed: Attempt = {
      ...graded,
      assessment_status: "failed",
      assessment_error: "provider_error",
      aggregate_result: null,
      results: null,
    };
    vi.spyOn(api, "listExercises")
      .mockResolvedValueOnce([successorView])
      .mockResolvedValue([{ ...successorView, attempts: [failed] }]);
    vi.spyOn(api, "submitAttempt").mockRejectedValue(
      new ApiError(502, "provider_error", "down", { attempt_id: "a1" }),
    );
    renderPanel("successor");
    await userEvent.type(await screen.findByLabelText("Your answer"), "answer");
    await userEvent.click(screen.getByRole("button", { name: "Submit answer" }));
    await waitFor(() => expect(screen.getAllByRole("alert")[0]).toHaveTextContent(/system error/));
    expect(screen.queryByText("Not yet demonstrated")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Chấm lại/ })).toBeInTheDocument();
  });

  it("offers to generate when no exercise exists", async () => {
    vi.spyOn(api, "listExercises").mockResolvedValue([]);
    renderPanel("expert");
    expect(await screen.findByRole("button", { name: "Generate exercise" })).toBeInTheDocument();
  });
});
