import { describe, it, expect, vi, beforeEach } from "vitest";
import { createHash } from "crypto";

// Mock auth
const authMock = vi.fn();
vi.mock("@/lib/auth", () => ({
  auth: () => authMock(),
}));

// Mock prisma
const deleteManyCliMock = vi.fn().mockResolvedValue({ count: 0 });
const findManyCliMock = vi.fn().mockResolvedValue([]);
const createCliMock = vi.fn().mockResolvedValue({});

vi.mock("@/lib/prisma", () => ({
  prisma: {
    cliToken: {
      deleteMany: (...args: unknown[]) => deleteManyCliMock(...args),
      findMany: (...args: unknown[]) => findManyCliMock(...args),
      create: (...args: unknown[]) => createCliMock(...args),
    },
  },
}));

import { POST, GET } from "@/app/api/auth/cli-token/route";

const AUTHED_SESSION = {
  user: {
    id: "user-1",
    name: "Test User",
    email: "test@example.com",
    image: "https://avatar.url",
  },
};

beforeEach(() => {
  authMock.mockReset();
  deleteManyCliMock.mockReset();
  deleteManyCliMock.mockResolvedValue({ count: 0 });
  findManyCliMock.mockReset();
  findManyCliMock.mockResolvedValue([]);
  createCliMock.mockReset();
  createCliMock.mockResolvedValue({});
});

describe("POST /api/auth/cli-token", () => {
  // 1. Unauthenticated request returns 401 with UNAUTHORIZED
  it("returns 401 with UNAUTHORIZED when not authenticated", async () => {
    authMock.mockResolvedValue(null);

    const response = await POST();
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body).toEqual({ error: "UNAUTHORIZED" });
  });

  // 2. Authenticated request returns a token string and expiresAt ISO string
  it("returns token and expiresAt for an authenticated user", async () => {
    authMock.mockResolvedValue(AUTHED_SESSION);

    const response = await POST();
    const body = await response.json();

    expect(response.status).toBe(200);
    // Raw token is 32 random bytes encoded as hex — 64 hex characters
    expect(typeof body.token).toBe("string");
    expect(body.token).toHaveLength(64);
    expect(/^[0-9a-f]{64}$/.test(body.token)).toBe(true);
    // expiresAt must be a valid ISO string
    expect(typeof body.expiresAt).toBe("string");
    expect(() => new Date(body.expiresAt)).not.toThrow();
    expect(new Date(body.expiresAt).toISOString()).toBe(body.expiresAt);
  });

  // 3. Stores the SHA-256 hash of the raw token, not the raw token itself
  it("stores the hashed token in the database, not the raw token", async () => {
    authMock.mockResolvedValue(AUTHED_SESSION);

    const response = await POST();
    const body = await response.json();
    const rawToken = body.token;

    expect(createCliMock).toHaveBeenCalledOnce();
    const callArg = createCliMock.mock.calls[0][0] as {
      data: { token: string; userId: string; expiresAt: Date };
    };

    // Stored token must NOT equal the raw token returned to the client
    expect(callArg.data.token).not.toBe(rawToken);
    // Stored token must equal SHA-256(rawToken)
    const expectedHash = createHash("sha256").update(rawToken).digest("hex");
    expect(callArg.data.token).toBe(expectedHash);
  });

  // 4. Cleans up expired tokens on every POST
  it("deletes expired tokens before creating a new one", async () => {
    authMock.mockResolvedValue(AUTHED_SESSION);

    await POST();

    expect(deleteManyCliMock).toHaveBeenCalledWith(
      expect.objectContaining({
        where: { expiresAt: { lt: expect.any(Date) } },
      })
    );
  });

  // 5. Enforces 5-token cap — oldest tokens are removed when at or over limit
  it("deletes oldest tokens when user already has 5 active tokens", async () => {
    authMock.mockResolvedValue(AUTHED_SESSION);

    const existingTokens = [
      { id: "tok-1", createdAt: new Date("2026-01-01") },
      { id: "tok-2", createdAt: new Date("2026-01-02") },
      { id: "tok-3", createdAt: new Date("2026-01-03") },
      { id: "tok-4", createdAt: new Date("2026-01-04") },
      { id: "tok-5", createdAt: new Date("2026-01-05") },
    ];
    findManyCliMock.mockResolvedValue(existingTokens);

    await POST();

    // With 5 existing tokens, slice(0, 5 - 4) = slice(0, 1) → only the oldest is deleted
    expect(deleteManyCliMock).toHaveBeenCalledWith(
      expect.objectContaining({
        where: { id: { in: ["tok-1"] } },
      })
    );
  });

  // 6. Does NOT enforce cap when user has fewer than 5 tokens
  it("does not delete any cap-related tokens when user has 3 active tokens", async () => {
    authMock.mockResolvedValue(AUTHED_SESSION);

    const existingTokens = [
      { id: "tok-1", createdAt: new Date("2026-01-01") },
      { id: "tok-2", createdAt: new Date("2026-01-02") },
      { id: "tok-3", createdAt: new Date("2026-01-03") },
    ];
    findManyCliMock.mockResolvedValue(existingTokens);

    await POST();

    // The only deleteMany call should be the expired-token cleanup, not a cap-enforcement one.
    // Cap-enforcement deleteMany uses { where: { id: { in: [...] } } }
    const capDeletion = deleteManyCliMock.mock.calls.find((call) => {
      const arg = call[0] as { where?: { id?: unknown } };
      return arg?.where?.id !== undefined;
    });
    expect(capDeletion).toBeUndefined();
  });
});

describe("GET /api/auth/cli-token", () => {
  // 7. Unauthenticated request returns { authenticated: false }
  it("returns { authenticated: false } when not authenticated", async () => {
    authMock.mockResolvedValue(null);

    const response = await GET();
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual({ authenticated: false });
  });

  // 8. Authenticated request returns user name and email but not image
  it("returns authenticated true with name and email but no image field", async () => {
    authMock.mockResolvedValue(AUTHED_SESSION);

    const response = await GET();
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual({
      authenticated: true,
      user: {
        name: "Test User",
        email: "test@example.com",
      },
    });
    // image must not be present
    expect(body.user).not.toHaveProperty("image");
  });
});
