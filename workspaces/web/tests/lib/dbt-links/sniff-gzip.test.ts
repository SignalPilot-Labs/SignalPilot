import { describe, it, expect } from "vitest";
import { isGzipMagic } from "@/lib/dbt-links/sniff-gzip";

describe("isGzipMagic", () => {
  it("returns true for a valid gzip magic header [0x1f, 0x8b, ...]", () => {
    const head = new Uint8Array([0x1f, 0x8b, 0x08, 0x00]);
    expect(isGzipMagic(head)).toBe(true);
  });

  it("returns true for exactly two bytes [0x1f, 0x8b]", () => {
    const head = new Uint8Array([0x1f, 0x8b]);
    expect(isGzipMagic(head)).toBe(true);
  });

  it("returns false for an empty Uint8Array (length 0)", () => {
    const head = new Uint8Array([]);
    expect(isGzipMagic(head)).toBe(false);
  });

  it("returns false for a single-byte array (length 1)", () => {
    const head = new Uint8Array([0x1f]);
    expect(isGzipMagic(head)).toBe(false);
  });

  it("returns false for wrong first byte", () => {
    const head = new Uint8Array([0x00, 0x8b]);
    expect(isGzipMagic(head)).toBe(false);
  });

  it("returns false for wrong second byte", () => {
    const head = new Uint8Array([0x1f, 0x00]);
    expect(isGzipMagic(head)).toBe(false);
  });

  it("returns false for both bytes wrong", () => {
    const head = new Uint8Array([0x00, 0x00]);
    expect(isGzipMagic(head)).toBe(false);
  });
});
