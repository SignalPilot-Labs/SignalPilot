/**
 * Minimal MD5 implementation (RFC 1321) over the UTF-8 encoding of a string.
 *
 * The Python side computes cell `code_hash` as
 * `hashlib.md5(code.encode("utf-8")).hexdigest()` (see
 * signalpilot/_utils/code.py in the notebook-server). This mirrors that
 * exactly so hashes computed in the browser match hashes computed by the
 * kernel. Correctness is verified against Python-generated fixtures in
 * parse.test.ts.
 */

// Per-round left-rotate amounts.
// oxlint-disable-next-line no-magic-numbers
const S = [
  7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 5, 9, 14, 20, 5,
  9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11,
  16, 23, 4, 11, 16, 23, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10,
  15, 21,
];

// K[i] = floor(|sin(i + 1)| * 2^32)
const K = new Uint32Array(64);
for (let i = 0; i < 64; i++) {
  K[i] = Math.floor(Math.abs(Math.sin(i + 1)) * 0x1_0000_0000);
}

function wordToHexLE(word: number): string {
  let out = "";
  for (let i = 0; i < 4; i++) {
    out += ((word >>> (i * 8)) & 0xff).toString(16).padStart(2, "0");
  }
  return out;
}

export function md5Hex(input: string): string {
  const bytes = new TextEncoder().encode(input);

  // Pad: 0x80, zeros, then 64-bit little-endian bit length.
  const paddedLen = (((bytes.length + 8) >> 6) + 1) << 6;
  const buf = new Uint8Array(paddedLen);
  buf.set(bytes);
  buf[bytes.length] = 0x80;
  const view = new DataView(buf.buffer);
  view.setUint32(paddedLen - 8, (bytes.length * 8) >>> 0, true);
  view.setUint32(paddedLen - 4, Math.floor(bytes.length / 0x2000_0000), true);

  let a0 = 0x67452301;
  let b0 = 0xefcdab89;
  let c0 = 0x98badcfe;
  let d0 = 0x10325476;

  const M = new Uint32Array(16);
  for (let offset = 0; offset < paddedLen; offset += 64) {
    for (let j = 0; j < 16; j++) {
      M[j] = view.getUint32(offset + j * 4, true);
    }
    let A = a0;
    let B = b0;
    let C = c0;
    let D = d0;
    for (let j = 0; j < 64; j++) {
      let F: number;
      let g: number;
      if (j < 16) {
        F = (B & C) | (~B & D);
        g = j;
      } else if (j < 32) {
        F = (D & B) | (~D & C);
        g = (5 * j + 1) % 16;
      } else if (j < 48) {
        F = B ^ C ^ D;
        g = (3 * j + 5) % 16;
      } else {
        F = C ^ (B | ~D);
        g = (7 * j) % 16;
      }
      const tmp = D;
      D = C;
      C = B;
      const sum = (A + F + K[j] + M[g]) | 0;
      B = (B + ((sum << S[j]) | (sum >>> (32 - S[j])))) | 0;
      A = tmp;
    }
    a0 = (a0 + A) | 0;
    b0 = (b0 + B) | 0;
    c0 = (c0 + C) | 0;
    d0 = (d0 + D) | 0;
  }

  return (
    wordToHexLE(a0) + wordToHexLE(b0) + wordToHexLE(c0) + wordToHexLE(d0)
  );
}

/**
 * Hash a cell's code the way the Python session serializer does:
 * `None` (null) for empty/absent code, otherwise the md5 hex digest.
 */
export function hashCellCode(code: string | null | undefined): string | null {
  if (code == null || code === "") {
    return null;
  }
  return md5Hex(code);
}
