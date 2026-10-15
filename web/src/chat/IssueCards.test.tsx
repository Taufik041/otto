import { screen, within } from '@testing-library/react'
import { renderSignedIn } from '@/test/render'
import { PrCard } from './PrCard'
import { ProposalCard } from './ProposalCard'
import type { IssueRef, PrCard as Pr, Proposal } from './reduce'
import { IssueCard } from './Thread'

const URL = 'https://github.com/Taufik041/otto_test/issues/12'
const ISSUE: IssueRef = { number: 12, title: 'Login button does nothing', state: 'open', labels: ['bug', 'ui'], url: URL, repo: 'Taufik041/otto_test' }

it('the issue card: number, title, state, labels and a link', () => {
  renderSignedIn(<IssueCard issue={ISSUE} />)
  const card = screen.getByRole('region', { name: 'Issue #12' })
  expect(within(card).getByRole('link', { name: '#12 Login button does nothing' })).toHaveAttribute('href', URL)
  expect(within(card).getByText('Open')).toBeInTheDocument()
  expect(within(card).getByText('bug')).toBeInTheDocument()
  expect(within(card).getByText('ui')).toBeInTheDocument()
  expect(within(card).queryByText(/closed on GitHub/)).not.toBeInTheDocument()
})

it('a closed issue: a soft warning, and Otto works on it anyway', () => {
  renderSignedIn(<IssueCard issue={{ ...ISSUE, state: 'closed', labels: [] }} />)
  expect(screen.getByText('Closed')).toBeInTheDocument()
  expect(screen.getByText('This issue is closed on GitHub. Otto works on it anyway.')).toBeInTheDocument()
})

const issues = [{ number: 12, url: URL }]

it('the proposal says "Closes #12", linking to the issue', () => {
  const proposal: Proposal = {
    title: 'Fix the login button', body: 'Done.\n\nFixes #12', head: 'otto/s1', base: 'main', additions: 1, deletions: 0,
    files: 1, tests: null, repo: 'Taufik041/otto_test', issues,
  }
  renderSignedIn(<ProposalCard sessionId="s1" proposal={proposal} state="proposed" live={false} />)
  expect(screen.getByRole('link', { name: 'Closes #12' })).toHaveAttribute('href', URL)
})

it('the PR card says "Closes #12" too, and nothing without issues', () => {
  const pr: Pr = {
    id: 't1', updated: false, number: 3, url: 'https://github.com/Taufik041/otto_test/pull/3', title: 'Fix the login button',
    repo: 'Taufik041/otto_test', branch: 'otto/s1', base: 'main', additions: 1, deletions: 0, files: 1, tests: null,
    firstFile: null, issues,
  }
  const { unmount } = renderSignedIn(<PrCard pr={pr} onSeeChanges={() => {}} />)
  expect(screen.getByRole('link', { name: 'Closes #12' })).toHaveAttribute('href', URL)
  unmount()
  renderSignedIn(<PrCard pr={{ ...pr, issues: [] }} onSeeChanges={() => {}} />)
  expect(screen.queryByText(/Closes/)).not.toBeInTheDocument()
})
