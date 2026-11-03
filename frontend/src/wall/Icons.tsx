import type { ItemStatus } from '../api/wall'

/** Einfache Linien-Icons für den Status einer Fälligkeit. */
export function StatusIcon({ status, size }: { status: ItemStatus; size: number }) {
  const common = {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 2,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
  }
  if (status === 'paid') {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="10" />
        <path d="m7.5 12.5 3 3 6-6.5" />
      </svg>
    )
  }
  if (status === 'overdue') {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="10" />
        <path d="M12 7v6" />
        <path d="M12 16.8v.2" />
      </svg>
    )
  }
  return (
    <svg {...common}>
      <circle cx="12" cy="12" r="10" />
      <path d="M12 7v5l3 2" />
    </svg>
  )
}
