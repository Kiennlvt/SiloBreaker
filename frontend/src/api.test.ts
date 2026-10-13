import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";

function mockFetch(status: number, body: unknown) {
  const text = typeof body === "string" ? body : JSON.stringify(body);
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(text, { status, headers: { "content-type": "application/json" } })),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("api error parsing", () => {
  it("surfaces the backend error code and detail", async () => {
    mockFetch(409, { error: { code: "stale_revision", detail: "finding is at revision 2, not 1" } });
    const err = await api.finding("x").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(409);
    expect(err.code).toBe("stale_revision");
    expect(err.message).toContain("revision 2");
  });

  it("reports an unreachable API as a network error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("failed"))));
    const err = await api.finding("x").catch((e) => e);
    expect(err.code).toBe("network");
  });
});
