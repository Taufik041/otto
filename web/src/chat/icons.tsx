// The design's own glyphs (docs/design/otto-data.js), for the chat's steps and cards.
import type { CSSProperties } from 'react'
export const IC = {
  run: 'M4.5 17l5-5-5-5M11.5 18h8',
  search: 'M10.5 4a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13zM15.5 15.5 20 20',
  file: 'M14 3H7a1.5 1.5 0 0 0-1.5 1.5v15A1.5 1.5 0 0 0 7 21h10a1.5 1.5 0 0 0 1.5-1.5V7.5zM14 3v4.5h4.5',
  edit: 'M4 20h4L19.5 8.5a2.1 2.1 0 0 0-4-4L4 16zM13.5 6.5l4 4',
  push: 'M12 16V4M7 9l5-5 5 5M5 20h14',
  pr: 'M6 8.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM6 8.5v7M6 20.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM18 20.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM18 15.5V9a3 3 0 0 0-3-3h-3M14 3.5 11.5 6 14 8.5',
  spin: 'M12 3.5a8.5 8.5 0 1 0 8.5 8.5',
  x: 'M6.5 6.5l11 11M17.5 6.5l-11 11',
  check: 'M5 12.5l4.5 4.5L19 7.5',
  checkCircle: 'M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17zM8 12.3l2.8 2.8L16.2 9.5',
  alert: 'M12 4 21 19.5H3zM12 10v4M12 17h.01',
  chevDown: 'M6 9.5l6 6 6-6',
  panel: 'M4 5.5h16v13H4zM13.5 5.5v13',
  ext: 'M14 4h6v6M20 4l-9 9M18 14v5.5H4.5V6H10',
  retry: 'M4.5 12a7.5 7.5 0 1 0 2.2-5.3M4.5 4.5v4h4',
  at: 'M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0zM16 12v1.5a2.5 2.5 0 0 0 5 0V12a9 9 0 1 0-3.5 7.1',
  box: 'M12 3l8 4.5v9L12 21l-8-4.5v-9zM4 7.5l8 4.5 8-4.5M12 12v9',
  stop: 'M7 7h10v10H7z',
  more: 'M5.5 12h.01M12 12h.01M18.5 12h.01',
} as const

export function Glyph({
  d,
  size = 16,
  width = 1.7,
  className,
  style,
  fill = false,
}: {
  d: string
  size?: number
  width?: number
  className?: string
  style?: CSSProperties
  fill?: boolean
}) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden="true" className={className} style={style}>
      <path
        d={d}
        fill={fill ? 'currentColor' : 'none'}
        stroke={fill ? 'none' : 'currentColor'}
        strokeWidth={width}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
