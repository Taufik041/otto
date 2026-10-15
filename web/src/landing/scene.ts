// The landing page's sample work, all made up: a shop's repo (acme/shop), three of its open issues,
// and what Otto does with one of them: the fix, the pull request, a failing CI check and its fix.
// The replay (./replay.ts) plays it; the sections below the hero show pieces of it.
import type { Issue, Repo } from '@/api/types'

export const REPO = 'acme/shop'
export const BRANCH = 'otto/7d1f0c2a9e'
export const PR_NUMBER = 15
export const PR_TITLE = 'Apply the bulk discount at exactly 10 units'
export const PR_URL = `https://github.com/${REPO}/pull/${PR_NUMBER}`
const issueUrl = (n: number) => `https://github.com/${REPO}/issues/${n}`
const RUN_URL = `https://github.com/${REPO}/actions/runs/4182`

/** The # picker's open issues, most recently updated first */
export const ISSUES: Issue[] = [
  { number: 14, title: 'Show discount codes on the receipt', labels: ['enhancement'], updated_at: '2026-10-14T09:00:00Z' },
  { number: 12, title: 'Bulk discount not applied at exactly 10 units', labels: ['bug'], updated_at: '2026-10-13T16:20:00Z' },
  { number: 11, title: "Cart badge doesn't update after removing an item", labels: ['ui'], updated_at: '2026-10-12T11:05:00Z' },
]
export const ISSUE = ISSUES[1]!
/** what the thread's issue card shows (the gateway's issues.card) */
export const ISSUE_CARD = { number: ISSUE.number, title: ISSUE.title, state: 'open', labels: ISSUE.labels, url: issueUrl(ISSUE.number), repo: REPO }
export const CLOSES = [{ number: ISSUE.number, url: issueUrl(ISSUE.number) }]

/** The @ picker's repos */
export const REPOS: Repo[] = [
  { full_name: REPO, private: true, updated_at: '2026-10-14T10:00:00Z', default_branch: 'main', installation_id: 1 },
  { full_name: 'acme/storefront', private: false, updated_at: '2026-10-11T10:00:00Z', default_branch: 'main', installation_id: 1 },
]

// what the user types: the repo, then # and a few letters of the issue
export const TYPED_REPO = `@${REPO} `
export const TYPED_QUERY = 'disc'
/** the message a picked issue sends with no words of the user's own (the composer's "Fix #12") */
export const TASK = `Fix #${ISSUE.number}`

// --- the fix ---------------------------------------------------------------------------------

export const INTRO = 'On it. The issue says an order of exactly 10 units misses the bulk discount. Let me find the check.'
export const SEARCH_OUT = 'src/shop/pricing.py:22:def qualifies_for_bulk(quantity: int) -> bool:'
export const FIX_DIFF = [
  '--- a/src/shop/pricing.py',
  '+++ b/src/shop/pricing.py',
  '@@ -20,7 +20,7 @@ CENT = Decimal("0.01")',
  ' ',
  ' ',
  ' def qualifies_for_bulk(quantity: int) -> bool:',
  '     """Orders at or above the threshold get the bulk rate."""',
  '-    return quantity > BULK_THRESHOLD',
  '+    return quantity >= BULK_THRESHOLD',
  ' ',
  ' ',
  ' def order_total(order: Order) -> Decimal:',
  '',
].join('\n')
export const PASSING = '.........                                [100%]\n9 passed in 0.08s'
export const COMMIT_OUT = `[${BRANCH} 3e8b1d4] ${PR_TITLE}\n 1 file changed, 1 insertion(+), 1 deletion(-)`
export const PUSH_OUT = `To github.com:${REPO}.git\n * [new branch]      ${BRANCH} -> ${BRANCH}`
export const REPLY =
  'Found it. `qualifies_for_bulk` used `>` instead of `>=`, so exactly 10 units missed the discount. I fixed the comparison and all 9 tests pass.'
export const PR_BODY = `${REPLY}\n\nFixes #${ISSUE.number}`

// --- CI, and its fix -------------------------------------------------------------------------

export const SHA = '3e8b1d4c0a9f2b7e6d5c4b3a2f1e0d9c8b7a6f5e'
export const FIX_SHA = '9a2c7e1b5d3f4a6c8e0b2d4f6a8c0e2b4d6f8a0c'
const check = (name: string, status: string, conclusion: string | null, duration: number | null, job: number) => ({
  name, status, conclusion, duration, html_url: `${RUN_URL}/job/${job}`,
})
/** ci.updated payloads, as the gateway records GitHub's checks */
export const ci = {
  waiting: (sha: string) => ({ sha, state: 'queued', checks: [], url: null }),
  running: (sha: string) => ({
    sha, state: 'running', url: RUN_URL,
    checks: [check('lint', 'in_progress', null, null, 1), check('tests', 'in_progress', null, null, 2)],
  }),
  failed: (sha: string) => ({
    sha, state: 'failed', url: `${RUN_URL}/job/2`,
    checks: [check('lint', 'completed', 'success', 14, 1), check('tests', 'completed', 'failure', 48, 2)],
  }),
  passed: (sha: string) => ({
    sha, state: 'passed', url: RUN_URL,
    checks: [check('lint', 'completed', 'success', 13, 1), check('tests', 'completed', 'success', 52, 2)],
  }),
}

export const FIX_CI_DISPLAY = 'Fix CI: tests'
export const FIX_INTRO = 'CI runs the integration tests too. `test_checkout_flow` still expects no discount at 10 units, so I\'ll update it to the rule in #12.'
export const CI_DIFF = [
  '--- a/tests/integration/test_checkout.py',
  '+++ b/tests/integration/test_checkout.py',
  '@@ -31,4 +31,4 @@ def test_checkout_flow(client):',
  '     cart = client.add("WIDGET", quantity=10)',
  '     receipt = client.checkout(cart)',
  '-    assert receipt.total == Decimal("100.00")',
  '+    assert receipt.total == Decimal("90.00")',
  '',
].join('\n')
export const ALL_PASSING = '............                             [100%]\n12 passed in 0.41s'
export const FIX_COMMIT = 'Update the checkout test for the bulk discount at 10 units'
export const FIX_COMMIT_OUT = `[${BRANCH} 9a2c7e1] ${FIX_COMMIT}\n 1 file changed, 1 insertion(+), 1 deletion(-)`
export const FIX_PUSH_OUT = `To github.com:${REPO}.git\n   3e8b1d4..9a2c7e1  ${BRANCH} -> ${BRANCH}`
export const FIX_REPLY = 'The checkout test expected the old rule. I updated it, all 12 tests pass, and I pushed to the pull request.'
