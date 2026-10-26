import { Navigate, useSearchParams } from 'react-router'
import { useAnswer } from '../api/queries'
import { ErrorNotice, Loading } from '../components/ui'
import { useTitle } from '../lib/hooks'
import { useRepo } from '../state/repo-context'
import { AnsweredView } from './AnsweredView'
import { RefusalView } from './RefusalView'

/** /why?entity=<id>&q=<question>: the API decides between an answer and a refusal. */
export function WhyPage() {
  const [params] = useSearchParams()
  const entityId = params.get('entity')
  const question = params.get('q') ?? ''
  const { repo } = useRepo()
  const { data, error, refetch } = useAnswer(repo?.id ?? null, entityId, question)
  useTitle(data?.question ?? 'Tracing')

  if (!entityId) return <Navigate to="/" replace />
  if (!repo) return null
  if (error) return <ErrorNotice error={error} onRetry={() => refetch()} />
  if (!data) return <Loading label="Tracing the history" />
  return data.verdict === 'answered' ? (
    <AnsweredView key={data.entity.id} answer={data} repoId={repo.id} />
  ) : (
    <RefusalView key={data.entity.id} answer={data} repoId={repo.id} />
  )
}
