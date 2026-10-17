import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../api";
import type { FindingDetail } from "../types";
import CapturePanel from "./CapturePanel";

const detail = {
  id: "f1",
  area_key: "settlement",
  title: "Settlement recovery",
  summary: "3 distinct events",
  question: null,
  status: "candidate",
  status_reason: null,
  revision: 1,
  prior_knowledge: null,
  handoff: { id: "h1", project_key: "p", bundle_id: "b", expert_id: "alice", successor_id: "bob" },
  draft: null,
  versions: [],
} as unknown as FindingDetail;

afterEach(() => vi.restoreAllMocks());

describe("CapturePanel", () => {
  it("shows a stale-data message with a reload button on 409 stale_revision", async () => {
    const finding = vi.spyOn(api, "finding").mockResolvedValue(detail);
    vi.spyOn(api, "review").mockRejectedValue(new ApiError(409, "stale_revision", "finding is at revision 2, not 1"));
    render(<CapturePanel findingId="f1" onChanged={() => undefined} />);
    await userEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/this data has changed\. reload/i);
    expect(alert).not.toHaveTextContent("stale_revision");
    const calls = finding.mock.calls.length;
    await userEvent.click(screen.getByRole("button", { name: "Reload" }));
    expect(finding.mock.calls.length).toBe(calls + 1);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps other conflicts distinct from stale data", async () => {
    vi.spyOn(api, "finding").mockResolvedValue(detail);
    vi.spyOn(api, "review").mockRejectedValue(new ApiError(409, "invalid_transition", "finding is already rejected"));
    render(<CapturePanel findingId="f1" onChanged={() => undefined} />);
    await userEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("invalid_transition");
    expect(screen.queryByRole("button", { name: "Reload" })).not.toBeInTheDocument();
  });

  it("tells the expert when knowledge was already approved in an earlier analysis", async () => {
    vi.spyOn(api, "finding").mockResolvedValue({
      ...detail,
      prior_knowledge: { finding_id: "f0", version_id: "v1", version_no: 1 },
    });
    const target = vi.fn();
    render(<CapturePanel findingId="f1" onChanged={() => undefined} onVerifyTarget={target} />);
    expect(await screen.findByText(/Version v1 was already approved/)).toBeInTheDocument();
    expect(target).toHaveBeenCalledWith({ id: "v1", version_no: 1 });
  });
});
