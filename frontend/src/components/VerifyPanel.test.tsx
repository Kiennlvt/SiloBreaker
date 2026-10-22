import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../api";
import type { Attempt, Exercise, HandoffRole } from "../types";
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

// The page only says which view it expects; once an exercise exists, its viewer_role
// (decided by the backend from the signed-in account) wins.
function renderPanel(expectedRole: HandoffRole) {
  return render(<VerifyPanel versionId="v1" versionNo={1} expectedRole={expectedRole} />);
}

describe("VerifyPanel", () => {
  it("never renders the rubric in the successor view", async () => {
    const list = vi.spyOn(api, "listExercises").mockResolvedValue([successorView]);
    const { container } = renderPanel("successor");
    expect(await screen.findByText(SCENARIO)).toBeInTheDocument();
    expect(list).toHaveBeenCalledWith("v1");
    expect(screen.getByLabelText("Your answer")).toBeInTheDocument();
    const html = container.innerHTML.toLowerCase();
    expect(html).not.toContain("rubric");
    expect(html).not.toContain("critical");
    for (const c of CRITERIA) expect(container.textContent).not.toContain(c.text);
  });

  it("shows the rubric to the expert and offers no viewer switch", async () => {
    vi.spyOn(api, "listExercises").mockResolvedValue([expertView]);
    renderPanel("expert");
    expect(await screen.findByText(/Private rubric/)).toBeInTheDocument();
    expect(screen.getByDisplayValue(CRITERIA[0].text)).toBeInTheDocument();
    expect(screen.getByText("You are the experienced engineer")).toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
  });

  it("follows the backend's viewer_role, not the page's expectation", async () => {
    // A successor who opens the expert URL still gets the successor payload and view.
    vi.spyOn(api, "listExercises").mockResolvedValue([successorView]);
    const { container } = renderPanel("expert");
    expect(await screen.findByLabelText("Your answer")).toBeInTheDocument();
    expect(container.innerHTML.toLowerCase()).not.toContain("rubric");
  });

  it("gives an admin a read-only view with no authoring or answering", async () => {
    vi.spyOn(api, "listExercises").mockResolvedValue([
      { ...expertView, viewer_role: "admin", status: "draft" },
    ]);
    renderPanel("admin");
    expect(await screen.findByText(/Private rubric/)).toBeInTheDocument();
    expect(screen.getByText("Administrator view (read only)")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Save exercise draft|Approve and release/ })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Your answer")).not.toBeInTheDocument();
  });

  it("shows criterion-level results from the backend and lets the successor retry", async () => {
    vi.spyOn(api, "listExercises")
      .mockResolvedValueOnce([successorView])
      .mockResolvedValue([{ ...successorView, attempts: [graded] }]);
    const submit = vi.spyOn(api, "submitAttempt").mockResolvedValue(graded);
    renderPanel("successor");
    await userEvent.type(await screen.findByLabelText("Your answer"), "I would retry it.");
    await userEvent.click(screen.getByRole("button", { name: "Submit answer" }));
    expect(submit).toHaveBeenCalledWith("ex1", { answer: "I would retry it." });
    expect(await screen.findByText("Not yet demonstrated")).toBeInTheDocument();
    expect(screen.getByText(CRITERIA[0].text, { exact: false })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
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
    expect(screen.getByRole("button", { name: "Assess again" })).toBeInTheDocument();
  });

  it("offers to generate when no exercise exists, without naming an actor", async () => {
    vi.spyOn(api, "listExercises").mockResolvedValue([]);
    const create = vi.spyOn(api, "createExercise").mockResolvedValue(expertView);
    renderPanel("expert");
    await userEvent.click(await screen.findByRole("button", { name: "Generate exercise" }));
    expect(create).toHaveBeenCalledWith("v1");
  });

  it("tells the successor when nothing has been released yet", async () => {
    vi.spyOn(api, "listExercises").mockResolvedValue([]);
    renderPanel("successor");
    expect(await screen.findByText(/has not released an exercise/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Generate exercise" })).not.toBeInTheDocument();
  });
});
