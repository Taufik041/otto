import type { SessionEvent } from '@/chat/reduce'

/** Events built in order, like the backend writes them. */
export function log() {
  const events: SessionEvent[] = []
  let seq = 0
  let t = Date.parse('2026-10-02T14:02:00Z')
  const add = (type: string, payload: Record<string, unknown> = {}) => {
    seq += 1
    t += 1000
    events.push({ seq, ts: new Date(t).toISOString(), type, payload })
    return api
  }
  let actionN = 0
  const api = {
    events,
    add,
    created: (task: string, repo: string | null = 'Taufik041/otto_test') =>
      add('session.created', { task, repo, model: 'openrouter:openrouter/free' }),
    status: (status: string) => add('session.status', { status }),
    msg: (role: string, content: string | null, tool_calls?: unknown[]) =>
      add('llm.message', { message: { role, content, ...(tool_calls ? { tool_calls } : {}) } }),
    /** an action and (unless result is null) its result */
    act: (kind: string, args: Record<string, unknown>, result: Record<string, unknown> | null = { exit_code: 0, stdout: '', stderr: '' }) => {
      const id = `a${++actionN}`
      add('bus.action', { action_id: id, kind, payload: args })
      if (result) add('bus.result', { action_id: id, ok: true, payload: result })
      return api
    },
  }
  return api
}

export const call = { id: 'c', type: 'function', function: { name: 'x', arguments: '{}' } }

export const PYTEST_FAIL = '...F..F..\nFAILED tests/test_pricing.py::test_bulk\n2 failed, 7 passed in 0.12s\n'
export const PYTEST_OK = '.........                                [100%]\n9 passed in 0.09s\n'
export const DIFF = '--- a/src/inventory/pricing.py\n+++ b/src/inventory/pricing.py\n@@ -22,3 +22,3 @@\n def q(quantity):\n-    return quantity > 10\n+    return quantity >= 10\n'

/** The design's main run: tests fail, search, read, edit, tests pass, commit+push, PR. */
export function mainRun() {
  return log()
    .created('two tests are failing, find out why and fix the source, not the tests')
    .status('provisioning')
    .status('queued')
    .status('running')
    .msg('system', 'You are Otto...')
    .msg('user', 'two tests are failing, find out why and fix the source, not the tests')
    .msg('assistant', "On it. I'll reproduce the failures first.", [call])
    .act('shell.exec', { cmd: 'python -m pytest -q' }, { exit_code: 1, stdout: PYTEST_FAIL, stderr: '' })
    .msg('tool', '{...}')
    .act('code.search', { pattern: 'qualifies_for_bulk' }, {
      exit_code: 0,
      stdout: 'src/inventory/pricing.py:22:def qualifies_for_bulk(q):\nsrc/inventory/legacy_pricing.py:15:def qualifies_for_bulk(qty):',
      stderr: '',
    })
    .act('fs.read', { path: '/workspace/docs/PRICING.md', start_line: 1, end_line: 12 }, { exit_code: 0, stdout: '# Pricing\n', stderr: '' })
    .act('fs.replace', { path: 'src/inventory/pricing.py', old_str: '>', new_str: '>=' }, {
      exit_code: 0, stdout: 'replaced 1 occurrence', stderr: '', diff: DIFF, added: 1, removed: 1,
    })
    .act('shell.exec', { cmd: 'python -m pytest -q' }, { exit_code: 0, stdout: PYTEST_OK, stderr: '' })
    .act('git.commit', { message: 'Fix bulk discount threshold' })
    .act('git.push', {}, {
      exit_code: 0, stdout: '', stderr: '', branch: 'otto/4299fa2c3f', base: 'main',
      diffstat: { files: 1, additions: 1, deletions: 1 },
    })
    .act('git.open_pr', { title: 'Fix bulk discount threshold', body: 'b' }, {
      exit_code: 0, stdout: 'u', stderr: '', number: 3, html_url: 'https://github.com/Taufik041/otto_test/pull/3',
      title: 'Fix bulk discount threshold', base: 'main',
    })
    .add('pr.opened', { number: 3, html_url: 'https://github.com/Taufik041/otto_test/pull/3' })
    .msg('assistant', 'Found it. `qualifies_for_bulk` used `>` instead of `>=`.')
    .status('done')
}


export const REVIEW_PR = {
  repo: 'Taufik041/otto_test', number: 7, title: 'Add a widget', url: 'https://github.com/Taufik041/otto_test/pull/7',
  author: 'contributor', head: 'feature', base: 'main', head_sha: 'c0ffee', trigger: 'mention', requested_by: 'taufik',
  additions: 2, deletions: 1, total_files: 2, truncated: false, skipped: [{ path: 'package-lock.json', reason: 'lockfile' }],
  files: [{ path: 'app/widget.py', status: 'modified', additions: 2, deletions: 1, patch: '@@ -1,3 +1,4 @@' }],
}
export const REVIEW = {
  summary: 'Adds a widget. **One problem.**',
  comments: [{
    path: 'app/widget.py', line: 3, body: 'This can be `None`.',
    excerpt: [{ line: 2, text: 'w = get()', added: true }, { line: 3, text: 'return w.size', added: true }],
  }],
  dropped: 1,
  usage: { prompt_tokens: 1900, completion_tokens: 160 },
}

/** A review chat: "@ottoci review" on GitHub, the brain's review, and (posted) it on GitHub. */
export function reviewRun(posted = true) {
  const l = log()
    .add('session.created', { task: 'Review Taufik041/otto_test#7: Add a widget', repo: null, model: 'openrouter:openrouter/free', kind: 'review' })
    .status('provisioning')
    .add('review.requested', REVIEW_PR)
    .status('queued')
    .status('running')
    .msg('system', 'You are Otto...')
    .add('llm.message', { message: { role: 'user', content: '<untrusted kind="pull-request">…</untrusted>' }, review_request: true, display: 'Review #7' })
    .add('review.drafted', REVIEW)
    .add('llm.message', { message: { role: 'assistant', content: 'Adds a widget.\n\n**app/widget.py:3**: This can be `None`.' }, review: true })
    .status('done')
  if (posted) l.add('review.posted', { review_id: 9001, url: 'https://github.com/Taufik041/otto_test/pull/7#pullrequestreview-9001', comments: 1 })
  return l
}
