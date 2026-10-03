// The design's repo glyph (a book); lucide's BookMarked is close but heavier.
export function RepoIcon({ size = 16, className, strokeWidth = 1.8 }: { size?: number; className?: string; strokeWidth?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true" className={className}>
      <path
        d="M5.5 18.5V5A1.5 1.5 0 0 1 7 3.5h11.5v13H7a1.5 1.5 0 0 0-1.5 1.5 1.5 1.5 0 0 0 1.5 1.5h11.5"
        stroke="currentColor"
        strokeWidth={strokeWidth}
        strokeLinejoin="round"
      />
    </svg>
  )
}
