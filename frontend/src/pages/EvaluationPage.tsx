import { Link, useSearchParams } from 'react-router'
import { useEvaluation } from '../api/queries'
import type { EvalResult, ExpectedOutcome } from '../api/types'
import { EvalTable } from '../components/EvalTable'
import { SegmentedControl } from '../components/SegmentedControl'
import { Badge, Card, ErrorNotice, Loading } from '../components/ui'
import { OUTCOME_LABEL, SYSTEMS } from '../lib/eval'
import { useTitle } from '../lib/hooks'
import { whyPath } from '../lib/routes'
import { cx } from '../lib/tones'
import { useRepo } from '../state/repo-context'

const FILTERS: (ExpectedOutcome | 'all')[] = ['all', 'answered', 'superseded', 'refused']

const SCORING: { metric: string; rule: string }[] = [
  { metric: 'Citation accuracy', rule: 'every claim in the answer points to a real commit, PR or issue that says it' },
  { metric: 'Supersession detected correctly', rule: 'the current rule is given, and older rules are named as replaced' },
  { metric: 'Correct refusals', rule: 'when the history has no reason, the system says so instead of guessing' },
  { metric: 'Answers with evidence links', rule: 'the answer links to at least one source' },
]

function ResultCell({ result }: { result: EvalResult | null }) {
  if (!result) return <span className="text-xs text-faint">Not run</span>
  return (
    <span className="flex flex-col gap-0.5 text-xs">
      <span className={result.correct ? 'font-semibold text-green' : 'font-semibold text-red'}>
        {result.correct ? '✓ Correct' : '✗ Wrong'}
      </span>
      <span className="text-faint">
        {OUTCOME_LABEL[result.outcome].label}
        {result.cited_source ? ', cited a source' : ', no source'}
      </span>
    </span>
  )
}

/** The proof page: every labelled question, what the right response is, and how each system did. */
export function EvaluationPage() {
  const { repo } = useRepo()
  const [params, setParams] = useSearchParams()
  const { data, error, refetch } = useEvaluation(repo?.id ?? null)
  useTitle('Evaluation')

  const raw = params.get('expected')
  const filter = FILTERS.find((f) => f === raw) ?? 'all'

  if (!repo) return null
  if (error) return <ErrorNotice error={error} onRetry={() => refetch()} />
  if (!data) return <Loading label="Loading the evaluation" />

  const shown = data.questions.filter((q) => filter === 'all' || q.expected === filter)
  const count = (f: ExpectedOutcome | 'all') =>
    f === 'all' ? data.questions.length : data.questions.filter((q) => q.expected === f).length

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Evaluation</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            {data.question_count} labelled questions about {repo.id}, each with a known right answer, run through
            a plain LLM, an LLM with vector search, and WhyCode. Some questions have no recorded reason, so the
            right response is to refuse.
          </p>
        </div>
        {!data.measured && <Badge tone="amber">Placeholder values</Badge>}
      </div>

      {!data.measured && (
        <p className="mt-4 rounded-lg border border-amber/30 bg-amber/10 px-3 py-2 text-sm text-muted">
          The evaluation has not been run yet. The scores below are placeholders and no question has a result.
        </p>
      )}

      <div className="mt-6 grid grid-cols-1 items-start gap-4 lg:grid-cols-[1.45fr_1fr]">
        <Card className="p-5">
          <h2 className="font-semibold">Scores</h2>
          <div className="mt-4">
            <EvalTable rows={data.rows} />
          </div>
        </Card>
        <Card className="p-5">
          <h2 className="font-semibold">How a response is scored</h2>
          <dl className="mt-3 space-y-3 text-sm">
            {SCORING.map((s) => (
              <div key={s.metric}>
                <dt className="font-semibold">{s.metric}</dt>
                <dd className="text-muted">{s.rule}</dd>
              </div>
            ))}
          </dl>
        </Card>
      </div>

      <section className="mt-8" aria-labelledby="questions-heading">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 id="questions-heading" className="font-semibold">
              Questions
            </h2>
            <p className="text-xs text-faint">
              {data.questions.length < data.question_count
                ? `${data.questions.length} of ${data.question_count} written so far.`
                : `All ${data.question_count} questions.`}
            </p>
          </div>
          <SegmentedControl
            label="Right response"
            options={FILTERS.map((f) => ({
              value: f,
              label: `${f === 'all' ? 'All' : OUTCOME_LABEL[f].label} (${count(f)})`,
            }))}
            value={filter}
            onChange={(f) => setParams(f === 'all' ? {} : { expected: f }, { replace: true })}
          />
        </div>

        <div className="mt-3 overflow-x-auto rounded-xl border border-line bg-surface">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-[11px] tracking-wider text-faint uppercase">
                <th scope="col" className="px-4 py-3 font-semibold">
                  #
                </th>
                <th scope="col" className="px-2 py-3 font-semibold">
                  Question
                </th>
                <th scope="col" className="px-2 py-3 font-semibold">
                  Right response
                </th>
                {SYSTEMS.map((s) => (
                  <th
                    key={s.key}
                    scope="col"
                    className={cx('px-2 py-3 font-semibold whitespace-nowrap', s.key === 'whycode' && 'text-teal')}
                  >
                    {s.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((q) => (
                <tr key={q.id} className="border-b border-line align-top last:border-0">
                  <td className="px-4 py-3 font-mono text-xs text-faint">{q.id}</td>
                  <th scope="row" className="min-w-64 px-2 py-3 text-left font-normal">
                    {q.entity ? (
                      <Link to={whyPath(q.entity.id, q.question)} className="hover:underline">
                        {q.question}
                      </Link>
                    ) : (
                      q.question
                    )}
                  </th>
                  <td className="px-2 py-3">
                    <Badge tone={OUTCOME_LABEL[q.expected].tone}>{OUTCOME_LABEL[q.expected].label}</Badge>
                  </td>
                  {SYSTEMS.map((s) => (
                    <td key={s.key} className="px-2 py-3">
                      <ResultCell result={q.results[s.key]} />
                    </td>
                  ))}
                </tr>
              ))}
              {shown.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-sm text-faint">
                    {data.questions.length === 0 ? 'No questions have been written yet.' : 'No question matches this filter.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
