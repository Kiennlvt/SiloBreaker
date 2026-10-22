import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, describeError } from "./api";

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

describe("api requests", () => {
  it("sends the session cookie, and the CSRF header only on writes", async () => {
    const fetch = vi.fn(async () => new Response("{}", { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetch);
    await api.handoffs();
    await api.review("f1", { action: "confirm", reason: "", expected_revision: 1 });
    const [[, read], [, write]] = fetch.mock.calls as unknown as [string, RequestInit][];
    expect(read.credentials).toBe("include");
    expect(write.credentials).toBe("include");
    expect((read.headers as Record<string, string>)["X-Requested-With"]).toBeUndefined();
    expect((write.headers as Record<string, string>)["X-Requested-With"]).toBe("silobreaker");
    expect(JSON.parse(write.body as string)).not.toHaveProperty("actor_id");
  });
});

describe("describeError", () => {
  it("separates stale data, provider failures and other errors", () => {
    expect(describeError(new ApiError(409, "stale_revision", "x")).kind).toBe("stale");
    expect(describeError(new ApiError(409, "invalid_transition", "x")).kind).toBe("other");
    const provider = describeError(new ApiError(502, "provider_error", "x"));
    expect(provider.kind).toBe("provider");
    expect(provider.message).toMatch(/system error/);
    expect(describeError(new ApiError(504, "provider_timeout", "x")).message).toMatch(/in time/);
    expect(describeError(new ApiError(503, "provider_not_configured", "x")).kind).toBe("provider");
    expect(describeError(new ApiError(500, "http_error", "x")).kind).toBe("other");
  });
});
