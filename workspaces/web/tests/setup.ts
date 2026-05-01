import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// Stub all required server env vars so tests start from a known baseline.
// Individual tests can override or delete stubs with vi.stubEnv / vi.unstubAllEnvs.
vi.stubEnv("WORKSPACES_MODE", "local");
vi.stubEnv("WORKSPACES_API_URL", "http://localhost:3400");
vi.stubEnv("SP_LOCAL_API_KEY", "test-api-key");
