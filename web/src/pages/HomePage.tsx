import { X } from 'lucide-react'
import { useMemo } from 'react'
import { useSearchParams } from 'react-router'
import { useRepos } from '@/api/queries'
import { githubErrorMessage, useMe } from '@/auth/auth'
import { Mark } from '@/components/brand'
import { Composer, type Suggestion } from '@/composer/Composer'
import { useShell } from '@/shell/AppShell'
import { TopBar } from '@/shell/TopBar'
import { firstName } from '@/utils/format'

/** A new chat: the greeting, the big composer and a few suggestions. */
export function HomePage() {
  const me = useMe()
  const { mobile } = useShell()
  const repos = useRepos()
  const [params, setParams] = useSearchParams()
  const ghError = githubErrorMessage(params.get('github_error'))

  const suggestions = useMemo<Suggestion[]>(() => {
    const repo = repos.data?.[0] ?? null
    const plain: Suggestion = { text: 'What can you do?', repo: null }
    if (!repo) return [plain]
    return [
      { text: 'fix the failing tests', repo },
      { text: 'add tests for Order', repo },
      { text: 'Explain how the pricing works', repo, mentionAtEnd: true },
      plain,
    ]
  }, [repos.data])

  const name = firstName(me.name)
  const greeting = `What should we build today${name ? `, ${name}` : ''}?`

  return (
    <>
      <TopBar bordered={false} newChat />
      <div className="flex min-h-0 flex-col overflow-y-auto pt-[52px]" style={{ flex: mobile ? '1 1 auto' : '1 1 0' }}>
        {mobile && (
          <div className="flex flex-1 flex-col items-center justify-center px-7 py-6 text-center animate-rise">
            <Mark size={40} className="mb-[18px]" />
            <h1 className="m-0 text-[28px] font-semibold leading-[1.15] tracking-[-0.022em] text-balance">{greeting}</h1>
          </div>
        )}
      </div>
      {!mobile && (
        <div className="flex flex-col items-center px-8 pb-7 text-center animate-rise">
          <Mark size={44} className="mb-5" />
          <h1 className="m-0 text-[40px] font-semibold leading-[1.1] tracking-[-0.025em] text-balance">{greeting}</h1>
        </div>
      )}
      {ghError && (
        <div className="mx-auto mb-3 flex w-[calc(100%-24px)] max-w-[720px] items-center gap-3 rounded-[14px] border border-solid border-line px-4 py-2.5 text-sm">
          <span className="flex-1 text-muted">{ghError.replace('or use your email', 'from Settings')}</span>
          <button
            type="button"
            aria-label="Dismiss"
            onClick={() => setParams({}, { replace: true })}
            className="flex size-7 items-center justify-center rounded-lg border-0 bg-transparent text-muted hover:bg-hover"
          >
            <X size={14} />
          </button>
        </div>
      )}
      <Composer mobile={mobile} hero suggestions={suggestions} />
      <div style={{ flex: mobile ? '0 0 0px' : '1.35 1 0' }} />
    </>
  )
}
