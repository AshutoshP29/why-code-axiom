import { useState } from 'react'
import { Link } from 'react-router'
import type { AnsweredAnswer, Person } from '../api/types'
import {
  Breadcrumb,
  ConfidenceMeter,
  PartialHistoryNote,
  SupersededBanner,
} from '../components/answer-parts'
import { AskMaintainerDialog } from '../components/AskMaintainerDialog'
import { ConfidenceFactors } from '../components/ConfidenceFactors'
import { EvidenceChain } from '../components/EvidenceChain'
import { ExplorerPanel } from '../components/ExplorerPanel'
import { GraphNeighbourhood } from '../components/GraphNeighbourhood'
import { PersonCard } from '../components/PersonCard'
import { Badge, Card, SectionLabel } from '../components/ui'
import { entityCrumbs } from '../lib/entity'
import { plural } from '../lib/format'
import { lineagePath } from '../lib/routes'

/** Why Workspace: the whole idea on one screen. Every claim has a source. */
export function AnsweredView({ answer, repoId }: { answer: AnsweredAnswer; repoId: string }) {
  const [asking, setAsking] = useState<Person | null>(null)
  const d = answer.decision
  const decidedOn = d.decided_at.slice(0, 10)

  return (
    <div className="grid flex-1 grid-cols-1 lg:grid-cols-[232px_minmax(0,1fr)_300px]">
      <aside className="hidden border-r border-line bg-chrome lg:block">
        <ExplorerPanel activeEntity={answer.entity} />
      </aside>

      <article className="min-w-0 px-4 py-6 sm:px-8">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Breadcrumb parts={entityCrumbs(answer.entity)} />
          <Link to={lineagePath(answer.entity.id)} className="text-xs text-blue hover:underline">
            Decision history →
          </Link>
        </div>
        <h1 className="mt-2 text-2xl leading-snug font-semibold">{answer.question}</h1>
        {answer.partial_history && <PartialHistoryNote />}

        <Card className="mt-5 border-teal/40 p-5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={d.status === 'ACTIVE' ? 'teal' : 'blue'}>
              {d.status === 'ACTIVE' ? 'Active decision' : 'Partly in force'}
            </Badge>
            {answer.superseded.length > 0 && (
              <Badge tone="amber">Supersedes {answer.superseded.length} earlier</Badge>
            )}
            <div className="ml-auto">
              <ConfidenceMeter value={answer.confidence} tone="teal" />
            </div>
          </div>
          <p className="mt-3 leading-relaxed">{answer.answer_text}</p>
          <p className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-faint">
            <span>Decided {decidedOn}</span>
            {d.proposed_by && <span>Proposed by @{d.proposed_by}</span>}
            {d.reviewed_by && <span>Reviewed by @{d.reviewed_by}</span>}
            <a href={d.source.url} target="_blank" rel="noreferrer" className="text-blue hover:underline">
              {d.source.label}
            </a>
          </p>
        </Card>

        {answer.superseded.map((note) => (
          <SupersededBanner key={note.decision.id} note={note} entityId={answer.entity.id} />
        ))}

        <section className="mt-7" aria-labelledby="chain-heading">
          <div className="flex flex-wrap items-baseline gap-2">
            <h2 id="chain-heading" className="font-semibold">
              Chain of evidence
            </h2>
            <span className="text-xs text-faint">
              {plural(answer.evidence_chain.length, 'source')}. Every claim above is linked to one of them.
            </span>
          </div>
          <div className="mt-3">
            <EvidenceChain steps={answer.evidence_chain} />
          </div>
        </section>
      </article>

      <aside className="space-y-7 border-t border-line bg-chrome p-4 lg:border-t-0 lg:border-l">
        <GraphNeighbourhood nodes={answer.graph.nodes} edges={answer.graph.edges} current={answer.entity} />
        <section>
          <SectionLabel>Who to ask</SectionLabel>
          <div className="mt-3 space-y-2">
            {answer.who_to_ask.map((p) => (
              <PersonCard key={p.login} person={p} onAsk={setAsking} />
            ))}
            {answer.who_to_ask.length === 0 && <p className="text-xs text-faint">No people linked to this decision.</p>}
          </div>
        </section>
        <ConfidenceFactors confidence={answer.confidence} factors={answer.confidence_factors} refused={false} />
      </aside>

      {asking && (
        <AskMaintainerDialog
          person={asking}
          repo={repoId}
          entity={answer.entity}
          question={answer.question}
          finding={`WhyCode found this decision: "${d.summary}" (${d.source.label}, ${decidedOn}). I'd like to confirm it still holds.`}
          onClose={() => setAsking(null)}
        />
      )}
    </div>
  )
}
