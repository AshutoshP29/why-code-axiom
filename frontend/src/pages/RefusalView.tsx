import { useRef, useState } from 'react'
import { Link } from 'react-router'
import { useFlagGap } from '../api/queries'
import type { EntityKind, Person, RefusedAnswer } from '../api/types'
import { Breadcrumb, ConfidenceMeter, PartialHistoryNote } from '../components/answer-parts'
import { AskMaintainerDialog } from '../components/AskMaintainerDialog'
import { ConfidenceFactors } from '../components/ConfidenceFactors'
import { PersonCard } from '../components/PersonCard'
import { Badge, Button, Card, ExternalButton, Meta, SectionLabel, SourceLink } from '../components/ui'
import { entityCrumbs } from '../lib/entity'
import { formatPct } from '../lib/format'

const RELATED_CAPTION: Record<EntityKind, string> = {
  config: 'Mention the setting, but do not justify its value',
  function: 'Mention the function, but do not explain it',
  file: 'Mention the file, but do not explain it',
  module: 'Mention the module, but do not explain it',
}

/** When the history does not say: facts only, kept apart from reasons, plus who to ask. */
export function RefusalView({ answer, repoId }: { answer: RefusedAnswer; repoId: string }) {
  const [asking, setAsking] = useState<Person | null>(null)
  const flag = useFlagGap(repoId)
  const owner = answer.who_to_ask[0] ?? null
  // A double-click lands before the button re-renders as disabled; this stops the second flag.
  const flagSent = useRef(false)

  function sendFlag() {
    if (flagSent.current) return
    flagSent.current = true
    flag.mutate(
      { entityId: answer.entity.id, question: answer.question },
      { onError: () => (flagSent.current = false) },
    )
  }

  return (
    <div className="grid flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_300px]">
      <article className="min-w-0 px-4 py-6 sm:px-8 lg:px-12">
        <Breadcrumb parts={entityCrumbs(answer.entity)} />
        <h1 className="mt-2 text-2xl leading-snug font-semibold">{answer.question}</h1>
        {answer.partial_history && <PartialHistoryNote />}

        <Card className="mt-5 border-red/40 p-5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="red">No recorded decision</Badge>
            <div className="ml-auto">
              <ConfidenceMeter
                value={answer.confidence}
                tone="red"
                note={`below the ${formatPct(answer.threshold)} answer threshold`}
              />
            </div>
          </div>
          <p className="mt-3 leading-relaxed">{answer.reason}</p>
        </Card>

        <section className="mt-7" aria-labelledby="facts-heading">
          <div className="flex flex-wrap items-baseline gap-2">
            <h2 id="facts-heading" className="font-semibold">
              What the graph does know
            </h2>
            <span className="text-xs text-faint">Facts, not reasons</span>
          </div>
          {answer.known_facts.length === 0 ? (
            <p className="mt-3 text-sm text-faint">No facts are recorded for this item.</p>
          ) : (
            <ul className="mt-3 space-y-3">
              {answer.known_facts.map((fact) => (
                <li key={fact.title} className="rounded-xl border border-line bg-surface p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone="blue">Fact</Badge>
                    <span className="text-sm font-semibold">{fact.title}</span>
                  </div>
                  <p className="mt-1.5 text-sm text-muted">{fact.detail}</p>
                  <Meta className="mt-2">
                    {[...fact.meta.map((m) => <span key={m}>{m}</span>), <SourceLink key="src" href={fact.source.url} />]}
                  </Meta>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="mt-7" aria-labelledby="related-heading">
          <div className="flex flex-wrap items-baseline gap-2">
            <h2 id="related-heading" className="font-semibold">
              Closest related items
            </h2>
            <span className="text-xs text-faint">{RELATED_CAPTION[answer.entity.kind]}</span>
          </div>
          {answer.related.length === 0 ? (
            <p className="mt-3 text-sm text-faint">Nothing else mentions it.</p>
          ) : (
            <ul className="mt-3 space-y-2">
              {answer.related.map((item) => (
                <li key={item.source.id} className="flex items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3">
                  <Badge>Related only</Badge>
                  <a
                    href={item.source.url}
                    target="_blank"
                    rel="noreferrer"
                    className="min-w-0 flex-1 truncate text-sm hover:underline"
                  >
                    {item.title}
                  </a>
                  <span className="text-xs whitespace-nowrap text-faint">{formatPct(item.match_score)} match</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <div className="mt-6 flex flex-wrap items-center gap-2">
          {owner && (
            <Button variant="primary" onClick={() => setAsking(owner)}>
              Ask @{owner.login}
            </Button>
          )}
          <ExternalButton href={answer.history_url}>Open commit history</ExternalButton>
          <Button disabled={flag.isPending || flag.isSuccess} onClick={sendFlag}>
            {flag.isSuccess ? 'Flagged' : flag.isPending ? 'Flagging…' : 'Flag as missing context'}
          </Button>
        </div>
        <div aria-live="polite" className="mt-2 text-xs">
          {flag.isSuccess && (
            <span className="text-muted">
              Added to the gap queue on{' '}
              <Link to="/health" className="text-blue underline underline-offset-2">
                Graph health
              </Link>
              .
            </span>
          )}
          {flag.error && <span className="text-red">{flag.error.message}</span>}
        </div>
      </article>

      <aside className="space-y-7 border-t border-line bg-chrome p-4 lg:border-t-0 lg:border-l">
        <section>
          <SectionLabel>Last owner of this code</SectionLabel>
          <div className="mt-3">
            {owner ? (
              <PersonCard person={owner} onAsk={setAsking} />
            ) : (
              <p className="text-xs text-faint">No owner recorded.</p>
            )}
          </div>
        </section>
        <ConfidenceFactors confidence={answer.confidence} factors={answer.confidence_factors} refused />
      </aside>

      {asking && (
        <AskMaintainerDialog
          person={asking}
          repo={repoId}
          entity={answer.entity}
          question={answer.question}
          finding="WhyCode found no recorded decision, discussion or incident that explains it."
          onClose={() => setAsking(null)}
        />
      )}
    </div>
  )
}
