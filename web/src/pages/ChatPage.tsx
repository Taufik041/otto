import { Ellipsis, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useParams } from 'react-router'
import { messageOf } from '@/api/errors'
import { useModels, useSession } from '@/api/queries'
import { Mark } from '@/components/brand'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { DeleteChatDialog } from '@/shell/DeleteChatDialog'
import { useShell } from '@/shell/AppShell'
import { TopBar } from '@/shell/TopBar'
import { shortName } from '@/utils/mention'

/** A chat. Part 1 shows its first message; the live conversation arrives in Part 2. */
export function ChatPage() {
  const { id = '' } = useParams()
  const { mobile } = useShell()
  const session = useSession(id)
  const models = useModels()
  const [deleting, setDeleting] = useState(false)
  const s = session.data
  const modelLabel = models.data?.models.find((m) => m.id === s?.model)?.label ?? s?.model

  return (
    <>
      <TopBar title={s?.title} repo={s?.repo} model={modelLabel}>
        {s && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                title="More"
                aria-label="More"
                className="flex size-9 shrink-0 items-center justify-center rounded-[10px] border-0 bg-transparent text-text hover:bg-sel data-[state=open]:bg-sel"
              >
                <Ellipsis size={20} strokeWidth={2.2} />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-[200px]">
              <DropdownMenuItem variant="danger" onSelect={() => setDeleting(true)}>
                <Trash2 />
                Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </TopBar>
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto pt-[52px]">
        <div
          className="mx-auto flex w-full flex-col"
          style={{ maxWidth: mobile ? '100%' : 760, padding: mobile ? '20px 16px 12px' : '36px 32px 24px' }}
        >
          {session.isError && <p className="text-center text-sm text-muted">{messageOf(session.error)}</p>}
          {s && (
            <>
              <div className="flex justify-end pb-6 animate-rise">
                <div className="max-w-[82%] rounded-[20px] bg-bg2 px-4 py-2.5 text-base leading-[1.55] text-pretty whitespace-pre-wrap">
                  {s.repo && (
                    <span className="mr-1 inline-flex items-center rounded-[7px] bg-accent-bg px-[7px] font-medium text-accent">
                      @{shortName(s.repo)}
                    </span>
                  )}
                  {s.task}
                </div>
              </div>
              <div className="flex gap-3.5 pb-4 animate-rise">
                <div className="shrink-0 pt-[3px]">
                  <Mark size={22} />
                </div>
                <p className="m-0 text-base leading-[1.65] text-muted">
                  The live conversation view is coming soon. This chat is {s.status}.
                </p>
              </div>
            </>
          )}
        </div>
      </div>
      <DeleteChatDialog chat={deleting && s ? s : null} onOpenChange={setDeleting} />
    </>
  )
}
