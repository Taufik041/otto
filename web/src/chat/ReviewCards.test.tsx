import { screen, within } from '@testing-library/react'
import { renderSignedIn } from '@/test/render'
import type { Review, ReviewPr } from './reduce'
import { ReviewCard, ReviewPrCard } from './ReviewCards'

const PR: ReviewPr = {
  repo: 'Taufik041/otto_test', number: 7, title: 'Add a widget', url: 'https://github.com/Taufik041/otto_test/pull/7',
  head: 'feature', base: 'main', additions: 2, deletions: 1, totalFiles: 3, reviewedFiles: 2, requestedBy: 'taufik',
}
const REVIEW: Review = {
  summary: 'Adds a widget.', postedUrl: null, failed: null,
  comments: [{ path: 'app/widget.py', line: 3, body: 'This can be None.', excerpt: [
    { line: 2, text: 'w = get()', added: false }, { line: 3, text: 'return w.size', added: true }] }],
}

it('the PR header: who asked, repo, #number, title, branches and a link', () => {
  renderSignedIn(<ReviewPrCard pr={PR} state="reviewing" />)
  const card = screen.getByRole('region', { name: 'Pull request #7' })
  expect(within(card).getByText('Review requested by @taufik')).toBeInTheDocument()
  expect(within(card).getByText('Reviewing')).toBeInTheDocument()
  expect(within(card).getByText('Add a widget')).toBeInTheDocument()
  expect(within(card).getByText('#7', { exact: false })).toBeInTheDocument()
  expect(within(card).getByText('Taufik041/otto_test · feature → main')).toBeInTheDocument()
  expect(within(card).getByText('2 of 3 files reviewed')).toBeInTheDocument()
  expect(within(card).queryByText(/tokens/)).not.toBeInTheDocument() // none until the review is written
  expect(within(card).getByRole('link', { name: /Open pull request/ })).toHaveAttribute('href', PR.url)
})

it('auto-review and a posted review read so', () => {
  renderSignedIn(<ReviewPrCard pr={{ ...PR, requestedBy: null, reviewedFiles: 3 }} state="posted" />)
  expect(screen.getByText('Automatic review')).toBeInTheDocument()
  expect(screen.getByText('Posted on GitHub')).toBeInTheDocument()
  expect(screen.queryByText(/files reviewed/)).not.toBeInTheDocument()
})

it('the review written: its tokens, small and muted, beside the files', () => {
  renderSignedIn(<ReviewPrCard pr={PR} state="reviewed" tokens={2060} />)
  const line = screen.getByText('2 of 3 files reviewed · 2,060 tokens')
  expect(line).toHaveClass('text-muted', 'text-[12.5px]')
})

it('the review: the summary, then each comment with path:line, its code and its words', () => {
  renderSignedIn(<ReviewCard review={REVIEW} />)
  const card = screen.getByRole('region', { name: 'Review' })
  expect(within(card).getByText('Adds a widget.')).toBeInTheDocument()
  expect(within(card).getByText('1 inline comment')).toBeInTheDocument()
  const comment = within(card).getByRole('listitem', { name: 'app/widget.py:3' })
  expect(within(comment).getByText('app/widget.py:3')).toBeInTheDocument()
  expect(within(comment).getByText('w = get()')).toBeInTheDocument()
  expect(within(comment).getByText('return w.size')).toBeInTheDocument()
  expect(within(comment).getByText('This can be None.')).toBeInTheDocument()
  expect(within(card).queryByRole('link')).not.toBeInTheDocument()
})

it('posted: a link to it on GitHub; refused: why', () => {
  const { unmount } = renderSignedIn(<ReviewCard review={{ ...REVIEW, comments: [], postedUrl: 'https://github.com/x/y/pull/7#r' }} />)
  expect(screen.getByText('No inline comments')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'See it on GitHub ›' })).toHaveAttribute('href', 'https://github.com/x/y/pull/7#r')
  unmount()
  renderSignedIn(<ReviewCard review={{ ...REVIEW, failed: "GitHub didn't take the review." }} />)
  expect(screen.getByRole('alert')).toHaveTextContent("GitHub didn't take the review.")
})
