import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Finding } from "../types";
import FindingCard from "./FindingCard";
import ScoreChart from "./ScoreChart";

// Shapes copied from the API response; the chart must draw these numbers, not compute them.
const WEIGHTS = { A: 25, D: 25, O: 20, M: 15, B: 15 };

function finding(over: Partial<Finding>): Finding {
  return {
    id: "f",
    area_key: "x",
    title: "Area",
    summary: "One sentence. A second sentence with detail.",
    question: null,
    signals: { A: 1, D: 1, O: 1, M: 1, B: 1 },
    counts: {
      distinct_events: 3,
      manual_events: 3,
      attributable_events: 3,
      events_by_selected: 3,
      events_by_others: 0,
      participation_share: 1,
      linked_records: 10,
      relevant_documents: 1,
    },
    raw_score: 100,
    weights: WEIGHTS,
    contributions: { A: 25, D: 25, O: 20, M: 15, B: 15 },
    cap: 60,
    reasons: [],
    missing_facets: [],
    top_candidate: true,
    review_priority: 100,
    evidence_confidence: "high",
    eligibility_status: "ranked",
    status: "candidate",
    status_reason: null,
    revision: 1,
    evidence_refs: [],
    prior_knowledge: null,
    ...over,
  };
}

const settlement = finding({
  title: "Settlement Recovery",
  signals: { A: 1, D: 0.5, O: 1, M: 1, B: 1 },
  contributions: { A: 25, D: 12.5, O: 20, M: 15, B: 15 },
  raw_score: 87.5,
  review_priority: 88,
  missing_facets: ["stop_and_escalate", "success_checks"],
});

const webhooks = finding({
  title: "Webhook Replay",
  signals: { A: 1, D: 1, O: 0.5, M: 1, B: 0 },
  contributions: { A: 25, D: 25, O: 10, M: 15, B: 0 },
  raw_score: 75,
  review_priority: 60,
  reasons: [
    "Capped: selected engineer handled only part of the attributable events.",
    "Capped: two or more recoveries by other engineers were found.",
  ],
});

const fx = finding({
  title: "FX Rates",
  signals: { A: 0.5, D: null, O: null, M: 0, B: null },
  contributions: { A: 12.5, D: null, O: null, M: 0, B: null },
  raw_score: null,
  review_priority: null,
  eligibility_status: "insufficient",
  evidence_confidence: "low",
  reasons: ["Unknown signal(s): D, O, B; no number is shown."],
});

const signalBars = () => screen.getAllByRole("img", { name: /points$/ });

describe("ScoreChart", () => {
  it("draws the stacked total and all five signal bars for Settlement", () => {
    const { container } = render(<ScoreChart finding={settlement} />);
    expect(screen.getByRole("img", { name: "Raw score 87.5 of 100, review priority 88" })).toBeInTheDocument();
    const bars = signalBars();
    expect(bars).toHaveLength(5);
    expect(bars.map((b) => b.getAttribute("aria-label"))).toEqual([
      "A Operational repetition: 25 of 25 points",
      "D Documentation gap: 12.5 of 25 points",
      "O Selected engineer participation: 20 of 20 points",
      "M Manual intervention: 15 of 15 points",
      "B Limited alternate recovery: 15 of 15 points",
    ]);
    // Grey track = maximum weight, filled part = backend contribution.
    const d = bars[1];
    expect(d.querySelector(".track")).toHaveAttribute("width", "25");
    expect(d.querySelector(".seg-D")).toHaveAttribute("width", "12.5");
    expect(screen.getByText(/missing: stop and escalate, success checks/)).toBeInTheDocument();
    expect(container.querySelector('[data-testid="cap-line"]')).toBeNull();
    expect(screen.queryByText(/Capped at/)).not.toBeInTheDocument();
  });

  it("draws a dashed cap line at 60 with the reasons for Webhooks", () => {
    render(<ScoreChart finding={webhooks} />);
    const total = screen.getByRole("img", { name: /capped at 60/ });
    const line = within(total).getByTestId("cap-line");
    expect(line).toHaveAttribute("x1", "60");
    expect(screen.getByText("Capped at 60")).toBeInTheDocument();
    expect(screen.getByText("two or more recoveries by other engineers were found.")).toBeInTheDocument();
    expect(signalBars()).toHaveLength(5);
  });

  it("shows no number for an unranked area and outlines unknown signals", () => {
    render(<ScoreChart finding={fx} />);
    expect(screen.getByText("No priority shown")).toBeInTheDocument();
    expect(screen.getByText(/Unknown signal\(s\)/)).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /Raw score/ })).not.toBeInTheDocument();
    const unknown = signalBars().filter((b) => b.querySelector(".track-unknown"));
    expect(unknown.map((b) => b.getAttribute("aria-label"))).toEqual([
      "D Documentation gap: unknown, up to 25 points",
      "O Selected engineer participation: unknown, up to 20 points",
      "B Limited alternate recovery: unknown, up to 15 points",
    ]);
  });
});

describe("FindingCard", () => {
  it("shows one sentence of interpretation and hides the table behind Show calculation", async () => {
    render(<FindingCard finding={settlement} selected={false} onEvidence={() => undefined} />);
    expect(screen.getByText("One sentence.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show calculation" }));
    const table = screen.getByRole("table");
    expect(within(table).getByText("87.5 → review priority 88")).toBeInTheDocument();
    expect(screen.getByText(settlement.summary)).toBeInTheDocument();
  });
});
