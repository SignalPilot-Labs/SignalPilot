"use client";

/**
 * Tiny deterministic monogram avatar.
 * If imageUrl provided: renders an img.
 * Else: picks bg from PALETTE keyed by first char code, renders initial.
 */

const PALETTE = [
  "var(--color-bg-card)",
  "var(--color-border)",
  "var(--color-bg-subtle)",
] as const;

export interface InitialsAvatarProps {
  name: string;
  imageUrl?: string;
  size?: number;
}

export function InitialsAvatar({ name, imageUrl, size = 28 }: InitialsAvatarProps) {
  if (imageUrl) {
    return (
      /* eslint-disable-next-line @next/next/no-img-element */
      <img
        src={imageUrl}
        alt={name}
        loading="lazy"
        width={size}
        height={size}
        style={{ width: size, height: size }}
        className="object-cover flex-shrink-0"
      />
    );
  }

  const bg = PALETTE[name.charCodeAt(0) % PALETTE.length];
  const initial = name.charAt(0).toUpperCase();

  return (
    <span
      aria-hidden="true"
      style={{
        width: size,
        height: size,
        backgroundColor: bg,
        border: "1px solid var(--color-border)",
        color: "var(--color-text)",
        fontSize: Math.round(size * 0.45),
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "monospace",
        flexShrink: 0,
      }}
    >
      {initial}
    </span>
  );
}
