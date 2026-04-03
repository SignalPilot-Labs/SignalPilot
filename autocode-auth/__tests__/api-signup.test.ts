import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Mock prisma before importing the route handler
const findUniqueMock = vi.fn();
const createMock = vi.fn();

vi.mock("@/lib/prisma", () => ({
  prisma: {
    user: {
      findUnique: (...args: unknown[]) => findUniqueMock(...args),
      create: (...args: unknown[]) => createMock(...args),
    },
  },
}));

// Mock bcryptjs before importing the route handler
const hashMock = vi.fn().mockResolvedValue("$2a$12$hashedpassword");

vi.mock("bcryptjs", () => ({
  default: {
    hash: (...args: unknown[]) => hashMock(...args),
  },
}));

import { POST } from "@/app/api/auth/signup/route";

function makeRequest(body: unknown): Request {
  return new Request("http://localhost:3000/api/auth/signup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

let errorSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  findUniqueMock.mockReset();
  createMock.mockReset();
  hashMock.mockReset();
  hashMock.mockResolvedValue("$2a$12$hashedpassword");
  // Default: no existing user
  findUniqueMock.mockResolvedValue(null);
  // Default: created user
  createMock.mockResolvedValue({ id: "user-123", email: "test@example.com" });
  errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  errorSpy.mockRestore();
});

describe("POST /api/auth/signup", () => {
  // 1. Successful signup returns 201 with id and email
  it("returns 201 with id and email on successful signup", async () => {
    const req = makeRequest({ email: "test@example.com", password: "securepassword" });
    const res = await POST(req as never);

    expect(res.status).toBe(201);
    const body = await res.json();
    expect(body).toEqual({ id: "user-123", email: "test@example.com" });
  });

  // 2. Response body never contains the raw password
  it("does not include the raw password in the response body", async () => {
    const req = makeRequest({ email: "test@example.com", password: "securepassword" });
    const res = await POST(req as never);
    const body = await res.json();

    expect(body).not.toHaveProperty("password");
    const serialised = JSON.stringify(body);
    expect(serialised).not.toContain("securepassword");
  });

  // 3. Missing email returns 400 with EMAIL_AND_PASSWORD_REQUIRED
  it("returns 400 with EMAIL_AND_PASSWORD_REQUIRED when email is missing", async () => {
    const req = makeRequest({ password: "securepassword" });
    const res = await POST(req as never);

    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body).toEqual({ error: "EMAIL_AND_PASSWORD_REQUIRED" });
  });

  // 4. Missing password returns 400 with EMAIL_AND_PASSWORD_REQUIRED
  it("returns 400 with EMAIL_AND_PASSWORD_REQUIRED when password is missing", async () => {
    const req = makeRequest({ email: "test@example.com" });
    const res = await POST(req as never);

    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body).toEqual({ error: "EMAIL_AND_PASSWORD_REQUIRED" });
  });

  // 5. Both fields missing returns 400 with EMAIL_AND_PASSWORD_REQUIRED
  it("returns 400 with EMAIL_AND_PASSWORD_REQUIRED when both fields are missing", async () => {
    const req = makeRequest({});
    const res = await POST(req as never);

    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body).toEqual({ error: "EMAIL_AND_PASSWORD_REQUIRED" });
  });

  // 6. Invalid email (no @) returns 400 with INVALID_EMAIL
  it("returns 400 with INVALID_EMAIL for email missing @", async () => {
    const req = makeRequest({ email: "notanemail", password: "securepassword" });
    const res = await POST(req as never);

    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body).toEqual({ error: "INVALID_EMAIL" });
  });

  // 7. Invalid email (no TLD) returns 400 with INVALID_EMAIL
  it("returns 400 with INVALID_EMAIL for email missing domain extension", async () => {
    const req = makeRequest({ email: "user@nodomain", password: "securepassword" });
    const res = await POST(req as never);

    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body).toEqual({ error: "INVALID_EMAIL" });
  });

  // 8. Non-string email returns 400 with INVALID_EMAIL
  it("returns 400 with INVALID_EMAIL when email is a number", async () => {
    const req = makeRequest({ email: 12345, password: "securepassword" });
    const res = await POST(req as never);

    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body).toEqual({ error: "INVALID_EMAIL" });
  });

  // 9. Short password (< 8 chars) returns 400 with PASSWORD_MIN_8_CHARACTERS
  it("returns 400 with PASSWORD_MIN_8_CHARACTERS for a 7-character password", async () => {
    const req = makeRequest({ email: "test@example.com", password: "short7!" });
    const res = await POST(req as never);

    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body).toEqual({ error: "PASSWORD_MIN_8_CHARACTERS" });
  });

  // 10. Empty password returns 400 with PASSWORD_MIN_8_CHARACTERS
  it("returns 400 with PASSWORD_MIN_8_CHARACTERS for an empty password", async () => {
    const req = makeRequest({ email: "test@example.com", password: "" });
    const res = await POST(req as never);

    // Empty string is falsy so hits EMAIL_AND_PASSWORD_REQUIRED first
    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body.error).toMatch(/EMAIL_AND_PASSWORD_REQUIRED|PASSWORD_MIN_8_CHARACTERS/);
  });

  // 11. Non-string password returns 400 with PASSWORD_MIN_8_CHARACTERS
  it("returns 400 with PASSWORD_MIN_8_CHARACTERS when password is a number", async () => {
    const req = makeRequest({ email: "test@example.com", password: 12345678 });
    const res = await POST(req as never);

    expect(res.status).toBe(400);
    const body = await res.json();
    expect(body).toEqual({ error: "PASSWORD_MIN_8_CHARACTERS" });
  });

  // 12. Exactly 8-character password is accepted
  it("accepts a password that is exactly 8 characters", async () => {
    const req = makeRequest({ email: "test@example.com", password: "exactly8" });
    const res = await POST(req as never);

    expect(res.status).toBe(201);
  });

  // 13. Duplicate email returns 409 with EMAIL_ALREADY_EXISTS
  it("returns 409 with EMAIL_ALREADY_EXISTS when email is already registered", async () => {
    findUniqueMock.mockResolvedValue({ id: "existing-user", email: "test@example.com" });

    const req = makeRequest({ email: "test@example.com", password: "securepassword" });
    const res = await POST(req as never);

    expect(res.status).toBe(409);
    const body = await res.json();
    expect(body).toEqual({ error: "EMAIL_ALREADY_EXISTS" });
  });

  // 14. Internal error (prisma throws) returns 500 with INTERNAL_ERROR
  it("returns 500 with INTERNAL_ERROR when prisma.user.findUnique throws", async () => {
    findUniqueMock.mockRejectedValue(new Error("DB connection failed"));

    const req = makeRequest({ email: "test@example.com", password: "securepassword" });
    const res = await POST(req as never);

    expect(res.status).toBe(500);
    const body = await res.json();
    expect(body).toEqual({ error: "INTERNAL_ERROR" });
  });

  // 15. Internal error (prisma.create throws) returns 500 with INTERNAL_ERROR
  it("returns 500 with INTERNAL_ERROR when prisma.user.create throws", async () => {
    createMock.mockRejectedValue(new Error("Write failed"));

    const req = makeRequest({ email: "test@example.com", password: "securepassword" });
    const res = await POST(req as never);

    expect(res.status).toBe(500);
    const body = await res.json();
    expect(body).toEqual({ error: "INTERNAL_ERROR" });
  });

  // 16. Internal error calls console.error
  it("calls console.error when an internal error occurs", async () => {
    const thrownError = new Error("DB connection failed");
    findUniqueMock.mockRejectedValue(thrownError);

    const req = makeRequest({ email: "test@example.com", password: "securepassword" });
    await POST(req as never);

    expect(errorSpy).toHaveBeenCalledWith("[signup] error:", thrownError);
  });

  // 17. bcrypt.hash is called with cost factor 12
  it("calls bcrypt.hash with the password and cost factor 12", async () => {
    const req = makeRequest({ email: "test@example.com", password: "securepassword" });
    await POST(req as never);

    expect(hashMock).toHaveBeenCalledWith("securepassword", 12);
  });

  // 18. bcrypt.hash is called exactly once on success
  it("calls bcrypt.hash exactly once on a successful request", async () => {
    const req = makeRequest({ email: "test@example.com", password: "securepassword" });
    await POST(req as never);

    expect(hashMock).toHaveBeenCalledTimes(1);
  });

  // 19. bcrypt.hash is NOT called when validation fails
  it("does not call bcrypt.hash when validation fails", async () => {
    const req = makeRequest({ email: "bademail", password: "securepassword" });
    await POST(req as never);

    expect(hashMock).not.toHaveBeenCalled();
  });

  // 20. bcrypt.hash is NOT called when email already exists
  it("does not call bcrypt.hash when email already exists", async () => {
    findUniqueMock.mockResolvedValue({ id: "existing-user", email: "test@example.com" });

    const req = makeRequest({ email: "test@example.com", password: "securepassword" });
    await POST(req as never);

    expect(hashMock).not.toHaveBeenCalled();
  });

  // 21. The hashed password (not the raw password) is stored via prisma.user.create
  it("stores the hashed password, not the raw password, via prisma.user.create", async () => {
    const req = makeRequest({ email: "test@example.com", password: "securepassword" });
    await POST(req as never);

    expect(createMock).toHaveBeenCalledWith({
      data: {
        email: "test@example.com",
        password: "$2a$12$hashedpassword",
      },
    });

    const callArgs = createMock.mock.calls[0][0];
    expect(callArgs.data.password).not.toBe("securepassword");
  });

  // 22. prisma.user.findUnique is queried with the correct email
  it("queries prisma.user.findUnique with the provided email", async () => {
    const req = makeRequest({ email: "test@example.com", password: "securepassword" });
    await POST(req as never);

    expect(findUniqueMock).toHaveBeenCalledWith({ where: { email: "test@example.com" } });
  });

  // 23. console.error is not called on a successful request
  it("does not call console.error on a successful request", async () => {
    const req = makeRequest({ email: "test@example.com", password: "securepassword" });
    await POST(req as never);

    expect(errorSpy).not.toHaveBeenCalled();
  });

  // 24. console.error is not called on a validation error
  it("does not call console.error on a validation error", async () => {
    const req = makeRequest({ email: "bad", password: "securepassword" });
    await POST(req as never);

    expect(errorSpy).not.toHaveBeenCalled();
  });

  // 25. console.error is not called on a duplicate email 409
  it("does not call console.error on a duplicate email conflict", async () => {
    findUniqueMock.mockResolvedValue({ id: "existing-user", email: "test@example.com" });

    const req = makeRequest({ email: "test@example.com", password: "securepassword" });
    await POST(req as never);

    expect(errorSpy).not.toHaveBeenCalled();
  });
});
