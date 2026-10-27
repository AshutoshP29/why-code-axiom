import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
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
})

describe('Refusal', () => {
  it('refuses below the threshold and keeps facts apart from reasons', async () => {
    renderApp(whyPath(E.poolMaxsize.id, 'why is the default 10?'))

    expect(await screen.findByText('No recorded decision')).toBeInTheDocument()
    expect(screen.getByText('below the 40% answer threshold')).toBeInTheDocument()
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
