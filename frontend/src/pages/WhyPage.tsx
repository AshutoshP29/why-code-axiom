import { Navigate, useSearchParams } from 'react-router'
import { useAnswer } from '../api/queries'
import { ErrorNotice, Loading } from '../components/ui'
import { useTitle } from '../lib/hooks'
import { useRepo } from '../state/repo-context'
import { AnsweredView } from './AnsweredView'
import { RefusalView } from './RefusalView'

/**
 * /why?entity=<id>&q=<question>, or /why?q=<question> to let the API find the entity.
 * The API decides between an answer, a hedged answer and a refusal.
 */
export function WhyPage() {
  const [params] = useSearchParams()
  const entityId = params.get('entity')
  const question = params.get('q') ?? ''
  const { repo } = useRepo()
  const { data, error, refetch } = useAnswer(repo?.id ?? null, entityId, question)
  useTitle(data?.question ?? 'Tracing')

  if (!entityId && !question.trim()) return <Navigate to="/" replace />
  if (!repo) return null
  if (error) return <ErrorNotice error={error} onRetry={() => refetch()} />
  if (!data) return <Loading label="Tracing the history" />
  // Keyed so dialogs and flags start fresh for each item and question.
  const key = `${data.entity?.id ?? ''}|${data.question}`
  return data.verdict === 'refused' ? (
    <RefusalView key={key} answer={data} repoId={repo.id} asked={question} />
  ) : (
    <AnsweredView key={key} answer={data} repoId={repo.id} asked={question} />
  )
}
