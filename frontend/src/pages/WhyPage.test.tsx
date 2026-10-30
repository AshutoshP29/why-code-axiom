import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { createMockApi } from '../api/mock'
import { E } from '../api/sample'
import { whyPath } from '../lib/routes'
import { currentLocation, renderApp } from '../test/render'

describe('Why Workspace', () => {
  it('answers apparent_encoding from PR #5797, linking the real sources', async () => {
    renderApp(whyPath(E.apparentEncoding.id, 'why charset_normalizer?'))

    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: 'Why does Response.apparent_encoding use charset_normalizer instead of chardet?',
      }),
    ).toBeInTheDocument()
    expect(screen.getByText('Active decision')).toBeInTheDocument()
    expect(screen.queryByRole('note')).not.toBeInTheDocument() // nothing was overridden
    const chain = screen.getByRole('list', { name: 'Evidence, from the report to the code' })
    expect(within(chain).getAllByRole('listitem')).toHaveLength(4)
    expect(within(chain).getByRole('link', { name: /^PR #5797: Switch LGPL'd chardet/ })).toHaveAttribute(
      'href',
      'https://github.com/psf/requests/pull/5797',
    )
    expect(within(chain).getByRole('link', { name: /^PR #5797: comment by @Ousret/ })).toHaveAttribute(
      'href',
      'https://github.com/psf/requests/pull/5797#issuecomment-842306896',
    )
    expect(within(chain).getByRole('link', { name: /^3e798b9:/ })).toHaveAttribute(
      'href',
      'https://github.com/psf/requests/commit/3e798b94717918ea48a38cdc315bf47a1067cb39',
    )
    expect(
      screen.getByText('Approved by @sigmavirus24, @Ousret, @mik-laj, @kaxil, @sethmlarson, @nateprewitt'),
    ).toBeInTheDocument()
    expect(screen.queryByText(/^Reviewed by/)).not.toBeInTheDocument() // sigmavirus24 is named once
    expect(screen.getByRole('button', { name: /^Ask\s*@ashb/ })).toHaveTextContent('Inactive')
    expect(screen.getByRole('button', { name: /^Ask\s*@nateprewitt/ })).toHaveTextContent('Active')
  })

  it('answers with the decision, the overridden rule and four linked sources', async () => {
    renderApp(whyPath(E.rebuildAuth.id, 'strips the Authorization header on redirect?'))

    expect(
      await screen.findByRole('heading', {
        level: 1,
        name: 'Why does rebuild_auth strip the Authorization header on redirect?',
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
    expect(message.value).toContain("I'm looking at SessionRedirectMixin.rebuild_auth in psf/requests")
    expect(message.value).toContain('Strip the Authorization header when a redirect changes host')
    await user.click(within(dialog).getByRole('button', { name: 'Copy message' }))
    expect(within(dialog).getByRole('button', { name: 'Copied' })).toBeInTheDocument()

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('re-asks about a neighbouring entity from the graph', async () => {
    const user = userEvent.setup()
    renderApp(whyPath(E.rebuildAuth.id, 'q'))
    await user.click(await screen.findByRole('button', { name: 'Ask about SessionRedirectMixin.resolve_redirects' }))

    expect(currentLocation()).toBe(`/why?entity=${E.resolveRedirects.id}&q=Why is SessionRedirectMixin.resolve_redirects like this?`)
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

  it('names everyone who approved the decision next to who proposed it', async () => {
    renderApp(whyPath(E.rebuildAuth.id, 'q'))
    expect(await screen.findByText('Proposed by @maintainer_a')).toBeInTheDocument()
    expect(screen.getByText('Approved by @maintainer_b, @maintainer_c')).toBeInTheDocument()
    // maintainer_b also reviewed it, and is named once, as an approver.
    expect(screen.queryByText('Reviewed by @maintainer_b')).not.toBeInTheDocument()
  })

  it('still names a reviewer who did not approve', async () => {
    const api = createMockApi({ delayMs: 0 })
    const ask = api.ask
    api.ask = async (...args) => {
      const answer = await ask(...args)
      if (answer.verdict === 'refused') return answer
      return { ...answer, decision: { ...answer.decision, reviewed_by: 'reviewer_x', approved_by: [] } }
    }
    renderApp(whyPath(E.rebuildAuth.id, 'q'), { api })
    expect(await screen.findByText('Reviewed by @reviewer_x')).toBeInTheDocument()
    expect(screen.queryByText(/^Approved by/)).not.toBeInTheDocument()
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
    expect(screen.getByText(/^Matched to/)).toHaveTextContent('Matched to SessionRedirectMixin.rebuild_auth (score 0.90) from your question.')
    expect(screen.getByRole('navigation', { name: 'Breadcrumb' })).toHaveTextContent('SessionRedirectMixin.rebuild_auth()')
  })

  it('asks the same question about a different entity when the match is wrong', async () => {
    const user = userEvent.setup()
    renderApp(whyPath(null, asked))
    await user.click(await screen.findByRole('button', { name: 'Pick a different entity' }))
    await user.type(screen.getByRole('combobox'), 'resolve')
    await user.click(await screen.findByRole('option', { name: /SessionRedirectMixin\.resolve_redirects/ }))

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
    renderApp(whyPath(null, 'why did requests drop python 2 support?'))
    await user.click(await screen.findByRole('button', { name: 'Pick an item to ask about' }))
    await user.type(screen.getByRole('combobox'), 'max_r')
    await user.click(await screen.findByRole('option', { name: /max_retries/ }))
    expect(currentLocation()).toBe(`/why?entity=${E.maxRetries.id}&q=why did requests drop python 2 support?`)
  })
})

describe('Refusal', () => {
  it('refuses below the threshold and keeps facts apart from reasons', async () => {
    renderApp(whyPath(E.checkCompatibility.id, 'why the version cap?'))

    expect(await screen.findByText('No recorded decision')).toBeInTheDocument()
    expect(screen.getByText('Refuses below 40% · warns below 70%')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'What the graph does know' })).toBeInTheDocument()
    // The one fact the graph has: the commit that changed it, with no reason attached.
    expect(screen.getByText("Commit 3e798b9: Switch LGPL'd chardet for MIT licensed charset_normalizer")).toBeInTheDocument()
    expect(screen.getByText('changed it: +14 / -6 lines')).toBeInTheDocument()
    expect(screen.getByText('36% match')).toBeInTheDocument()
    expect(screen.getByText('Why only 12%?')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open commit history' })).toHaveAttribute(
      'href',
      'https://github.com/psf/requests/commits/main/src/requests/__init__.py',
    )
    expect(screen.queryByText('Active decision')).not.toBeInTheDocument()
  })

  it('still explains itself when a question matched no item', async () => {
    renderApp(`/why?${new URLSearchParams({ q: 'why did requests drop python 2 support?' })}`)

    expect(await screen.findByText('No matching item')).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: 'why did requests drop python 2 support?' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Breadcrumb' })).not.toBeInTheDocument()
    expect(screen.getByText(/No function, file or config key in the graph matches this question/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'PR #1565: only strip auth when the host changes' })).toBeInTheDocument()
    expect(screen.getByText('9% match')).toBeInTheDocument()
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
