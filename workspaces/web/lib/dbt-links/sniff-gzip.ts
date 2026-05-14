import "server-only";

/**
 * Returns true if the first two bytes match the gzip magic-byte signature
 * (0x1f 0x8b). Callers should read `file.slice(0, 2).arrayBuffer()` and pass
 * the result as a Uint8Array; does NOT consume the stream used for extraction.
 */
export function isGzipMagic(head: Uint8Array): boolean {
  return head.length >= 2 && head[0] === 0x1f && head[1] === 0x8b;
}
