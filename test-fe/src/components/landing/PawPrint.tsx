export function PawPrint({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 64 64"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden="true"
    >
      <ellipse cx="20" cy="14" rx="5" ry="7" />
      <ellipse cx="44" cy="14" rx="5" ry="7" />
      <ellipse cx="10" cy="30" rx="4" ry="6" />
      <ellipse cx="54" cy="30" rx="4" ry="6" />
      <path d="M32 22c-10 0-18 8-14 20 2 6 6 10 10 12 2 1 4 1 8 0 4-2 8-6 10-12 4-12-4-20-14-20z" />
    </svg>
  );
}
