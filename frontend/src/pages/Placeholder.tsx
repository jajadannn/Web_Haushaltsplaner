import { EmptyState, PageHeader } from '../ui/blocks'

/** Bereiche, die in einem späteren Paket gebaut werden. */
export function Placeholder({ title, paket }: { title: string; paket: number }) {
  return (
    <div className="page">
      <PageHeader title={title} />
      <div className="tile">
        <EmptyState icon="clock" title="Kommt bald">
          Dieser Bereich wird in Paket {paket} gebaut.
        </EmptyState>
      </div>
    </div>
  )
}
