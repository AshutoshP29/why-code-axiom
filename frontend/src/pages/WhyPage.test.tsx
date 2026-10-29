import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { createMockApi } from '../api/mock'
import { E } from '../api/sample'
import { whyPath } from '../lib/routes'
import { currentLocation, renderApp } from '../test/render'

describe('Why Workspace', () => {
  it('answers with the decision, the overridden rule and four linked sources', async () => {
    renderApp(whyPath(E.rebuildAuth.id, 'strips the Authorization header on redirect?'))

    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: 'Why does Session.rebuild_auth strip the Authorization header on redirect?',
      }),
    ).toBeInTheDocument()
    expect(screen.getByText('Active decision')).toBeInTheDocument()
    expect(screen.getByText('Supersedes 1 earlier')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Confidence' })).toHaveAttribute('aria-valuenow', '87')

    const banner = screen.getByRole('note')
    expect(banner).toHaveTextContent('An earlier decision was overridden')
    expect(banner).toHaveTextContent('forward the header on every redirect (Issue #812, Nov 2012)')

    const chain = screen.getByRole('list', { name: 'Evidence, from the report to the code' })
    expect(within(chain).getAllByRole('listitem')).toHaveLength(4)
    expect(screen.getByText('4 sources. Every claim above is linked to one of them.')).toBeInTheDocument()
    expect(screen.getByText('Why 87%?')).toBeInTheDocument()

    // The compact bar in the top bar keeps the question being asked.
    expect(await screen.findByRole('textbox', { name: 'Your question' })).toHaveValue(
      'strips the Authorization header on redirect?',
    )
  })

  it('shows both thresholds from the response, and leaves the verdict to the API', async () => {
    const api = createMockApi({ delayMs: 0 })
    const ask = api.ask
    api.ask = async (...args) => ({ ...(await ask(...args)), thresholds: { answer: 0.9, refuse: 0.25 } })
    renderApp(whyPath(E.rebuildAuth.id, 'q'), { api })

    expect(await screen.findByText('Refuses below 25% · warns below 90%')).toBeInTheDocument()
    expect(screen.queryByText('Refuses below 40% · warns below 70%')).not.toBeInTheDocument()
    // 87% is under this response's 90% line, but the API said "answered", so it is shown as an answer.
    expect(screen.getByText('Active decision')).toBeInTheDocument()
    expect(screen.queryByText('Low confidence')).not.toBeInTheDocument()
  })

  it('marks who is still around', async () => {
    renderApp(whyPath(E.rebuildAuth.id, 'q'))
    const a = await screen.findByRole('button', { name: /^Ask\s*@maintainer_a/ })
    const b = screen.getByRole('button', { name: /^Ask\s*@maintainer_b/ })
    expect(a).toHaveTextContent('Active')
    expect(b).toHaveTextContent('Inactive')
    expect(b).toHaveTextContent('Reviewed it, last seen 2021')
  })

  it('writes a message for the maintainer', async () => {
    const user = userEvent.setup()
    renderApp(whyPath(E.rebuildAuth.id, 'q'))
    await user.click(await screen.findByRole('button', { name: /^Ask\s*@maintainer_a/ }))

    const dialog = screen.getByRole('dialog', { name: 'Ask @maintainer_a' })
    const message = within(dialog).getByRole<HTMLTextAreaElement>('textbox', { name: 'Message' })
    expect(message.value).toContain("I'm looking at Session.rebuild_auth in psf/requests")
    expect(message.value).toContain('Strip the Authorization header when a redirect changes host')
    await user.click(within(dialog).getByRole('button', { name: 'Copy message' }))
    expect(within(dialog).getByRole('button', { name: 'Copied' })).toBeInTheDocument()

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('re-asks about a neighbouring entity from the graph', async () => {
    const user = userEvent.setup()
    renderApp(whyPath(E.rebuildAuth.id, 'q'))
    await user.click(await screen.findByRole('button', { name: 'Ask about Session.resolve_redirects' }))

    expect(currentLocation()).toBe(`/why?entity=${E.resolveRedirects.id}&q=Why is Session.resolve_redirects like this?`)
    expect(await screen.findByText('No recorded decision')).toBeInTheDocument()
  })

  it('lists the options that were considered and not chosen', async () => {
    renderApp(whyPath(E.rebuildAuth.id, 'q'))
    const options = await screen.findByRole('list', { name: 'Also considered' })
    expect(within(options).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Strip the header on every redirect, even to the same host',
      'Keep the header and leave it to the caller',
    ])
  })

  it('leaves out "Also considered" when no other option was recorded', async () => {
    renderApp(whyPath(E.timeout.id, 'q'))
    expect(await screen.findByText('Low confidence')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Also considered' })).not.toBeInTheDocument()
  })
})

describe('Hedged answer', () => {
  it('gives the full answer under an amber warning', async () => {
    renderApp(whyPath(E.timeout.id, 'why no default?'))

    expect(await screen.findByRole('heading', { level: 1, name: 'Why is there no default timeout?' })).toBeInTheDocument()
    const warning = screen.getByRole('region', { name: 'Low confidence: check before relying on this' })
    expect(warning).toHaveTextContent(/Only one source supports this, and the reason is inferred/)
    expect(within(warning).getByRole('list', { name: 'What held confidence back' })).toHaveTextContent(
      'Evidence directness: 45%, inferredIndependent sources: 1 of 2 needed',
    )

    // Everything a confident answer has is still there.
    expect(screen.getByText('Active decision')).toBeInTheDocument()
    expect(screen.getByText('Low confidence')).toBeInTheDocument()
    const chain = screen.getByRole('list', { name: 'Evidence, from the report to the code' })
    expect(within(chain).getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByRole('button', { name: 'Ask about HTTPAdapter.send' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Ask\s*@maintainer_b/ })).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Confidence' })).toHaveAttribute('aria-valuenow', '55')
    expect(screen.getByText('Refuses below 40% · warns below 70%')).toBeInTheDocument()
  })

  it('lists the weak confidence factors first', async () => {
    renderApp(whyPath(E.timeout.id, 'q'))
    expect(await screen.findByText('Why only 55%?')).toBeInTheDocument()
    const factors = within(screen.getByRole('list', { name: 'Confidence factors' })).getAllByRole('listitem')
    expect(factors.map((li) => li.firstElementChild?.firstElementChild?.textContent)).toEqual([
      'Evidence directness',
      'Independent sources',
      'Entity match',
      'Supersession resolved',
    ])
  })

  it('never looks like a confident answer', async () => {
    const confident = renderApp(whyPath(E.rebuildAuth.id, 'q'))
    expect(await screen.findByText('Why 87%?')).toBeInTheDocument()
    expect(screen.queryByText('Low confidence')).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: /Low confidence/ })).not.toBeInTheDocument()
    confident.unmount()

    renderApp(whyPath(E.timeout.id, 'q'))
    expect(await screen.findByText('Low confidence')).toBeInTheDocument()
    expect(screen.queryByText(/^Why 55%/)).not.toBeInTheDocument()
  })

  it('writes the maintainer message with the caveat', async () => {
    const user = userEvent.setup()
    renderApp(whyPath(E.timeout.id, 'q'))
    await user.click(await screen.findByRole('button', { name: /^Ask\s*@maintainer_a/ }))
    const message = within(screen.getByRole('dialog')).getByRole<HTMLTextAreaElement>('textbox', { name: 'Message' })
    expect(message.value).toContain('WhyCode found this decision, but with low confidence: "Leave timeouts to the caller"')
  })
})

describe('Asking without an entity', () => {
  const asked = 'why does rebuild_auth strip the header?'

  it('says which item the question was matched to', async () => {
    renderApp(whyPath(null, asked))
    expect(await screen.findByText('Active decision')).toBeInTheDocument()
    expect(screen.getByText(/^Matched to/)).toHaveTextContent('Matched to Session.rebuild_auth (score 0.90) from your question.')
    expect(screen.getByRole('navigation', { name: 'Breadcrumb' })).toHaveTextContent('Session.rebuild_auth()')
  })

  it('asks the same question about a different entity when the match is wrong', async () => {
    const user = userEvent.setup()
    renderApp(whyPath(null, asked))
    await user.click(await screen.findByRole('button', { name: 'Pick a different entity' }))
    await user.type(screen.getByRole('combobox'), 'resolve')
    await user.click(await screen.findByRole('option', { name: /Session\.resolve_redirects/ }))

    expect(currentLocation()).toBe(`/why?entity=${E.resolveRedirects.id}&q=${asked}`)
    expect(await screen.findByText('No recorded decision')).toBeInTheDocument()
    expect(screen.queryByText(/^Matched to/)).not.toBeInTheDocument() // picked, not matched
  })

  it('shows no match line for a picked entity', async () => {
    renderApp(whyPath(E.rebuildAuth.id, 'q'))
    expect(await screen.findByText('Active decision')).toBeInTheDocument()
    expect(screen.queryByText(/^Matched to/)).not.toBeInTheDocument()
  })

  it('shows the match on a refusal too', async () => {
    renderApp(whyPath(null, 'why is the pool size 10?'))
    expect(await screen.findByText('No recorded decision')).toBeInTheDocument()
    expect(screen.getByText(/^Matched to/)).toHaveTextContent('Matched to HTTPAdapter.pool_maxsize (score 0.38)')
  })

  it('offers to pick an item when nothing matched', async () => {
    const user = userEvent.setup()
    renderApp(whyPath(null, 'why did requests drop chardet?'))
    await user.click(await screen.findByRole('button', { name: 'Pick an item to ask about' }))
    await user.type(screen.getByRole('combobox'), 'max_r')
    await user.click(await screen.findByRole('option', { name: /max_retries/ }))
    expect(currentLocation()).toBe(`/why?entity=${E.maxRetries.id}&q=why did requests drop chardet?`)
  })
})

describe('Refusal', () => {
  it('refuses below the threshold and keeps facts apart from reasons', async () => {
    renderApp(whyPath(E.poolMaxsize.id, 'why is the default 10?'))

    expect(await screen.findByText('No recorded decision')).toBeInTheDocument()
    expect(screen.getByText('Refuses below 40% · warns below 70%')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'What the graph does know' })).toBeInTheDocument()
    expect(screen.getByText('Introduced in commit e4f5a6b, 2012-05-02')).toBeInTheDocument()
    expect(screen.getByText('31% match')).toBeInTheDocument()
    expect(screen.getByText('Why only 18%?')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open commit history' })).toHaveAttribute(
      'href',
      'https://github.com/psf/requests/commits/main/src/requests/adapters.py',
    )
    expect(screen.queryByText('Active decision')).not.toBeInTheDocument()
  })

  it('still explains itself when a question matched no item', async () => {
    renderApp(`/why?${new URLSearchParams({ q: 'why did requests drop chardet?' })}`)

    expect(await screen.findByText('No matching item')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'why did requests drop chardet?' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Breadcrumb' })).not.toBeInTheDocument()
    expect(screen.getByText(/No function, file or config key in the graph matches this question/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'PR #1565: only strip auth when the host changes' })).toBeInTheDocument()
    expect(screen.getByText('18% match')).toBeInTheDocument()
    // There is no item to flag or to name an owner for.
    expect(screen.queryByRole('button', { name: 'Flag as missing context' })).not.toBeInTheDocument()
    expect(screen.queryByText('Last owner of this code')).not.toBeInTheDocument()
  })

  it('flags missing context into the gap queue on Graph health', async () => {
    const user = userEvent.setup()
    renderApp(whyPath(E.poolMaxsize.id, 'why is the default 10?'))

    await user.click(await screen.findByRole('button', { name: 'Flag as missing context' }))
    expect(await screen.findByRole('button', { name: 'Flagged' })).toBeDisabled()

    await user.click(screen.getByRole('link', { name: 'Graph health' }))
    const gap = await screen.findByRole('link', { name: /HTTPAdapter\.pool_maxsize/ })
    expect(gap).toHaveTextContent('3 flags') // the sample queue starts with 2
  })
})
