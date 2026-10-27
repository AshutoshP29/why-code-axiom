import type { EvalRow } from '../api/types'
import { SYSTEMS } from '../lib/eval'
import { formatPct } from '../lib/format'
import { ProgressBar } from './ui'

/** Metric by system: plain LLM, LLM with vector search, WhyCode. */
export function EvalTable({ rows }: { rows: EvalRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[11px] tracking-wider uppercase">
            <th scope="col" className="pb-2 font-semibold text-faint">
              Metric
            </th>
            {SYSTEMS.map((s) => (
              <th
                key={s.key}
                scope="col"
                className={`pb-2 pl-4 font-semibold ${s.key === 'whycode' ? 'text-teal' : 'text-faint'}`}
              >
                {s.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.metric}>
              <th scope="row" className="py-2.5 pr-2 text-left font-normal text-muted">
                {row.metric}
              </th>
              {SYSTEMS.map((s) => {
                const v = row[s.key]
                return (
                  <td key={s.key} className="min-w-28 py-2.5 pl-4">
                    <span className={`text-xs ${s.key === 'whycode' ? 'font-semibold' : 'text-muted'}`}>
                      {v === null ? '—' : formatPct(v)}
                    </span>
                    <ProgressBar value={v ?? 0} tone={s.tone} className="mt-1" />
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
