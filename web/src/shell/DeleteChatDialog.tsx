import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router'
import { api } from '@/api'
import { messageOf } from '@/api/errors'
import { keys } from '@/api/queries'
import type { SessionSummary } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogTitle } from '@/components/ui/dialog'

/** "Delete this chat?" DELETE /sessions/{id} stops its sandbox and deletes its history. */
export function DeleteChatDialog({
  chat,
  onOpenChange,
}: {
  chat: Pick<SessionSummary, 'id' | 'title'> | null
  onOpenChange: (open: boolean) => void
}) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const loc = useLocation()
  const del = useMutation({
    mutationFn: (id: string) => api.deleteSession(id),
    onSuccess: (_, id) => {
      qc.setQueryData<SessionSummary[]>(keys.sessions, (list) => list?.filter((s) => s.id !== id))
      qc.removeQueries({ queryKey: keys.session(id) })
      qc.invalidateQueries({ queryKey: keys.sessions })
      onOpenChange(false)
      if (loc.pathname === `/c/${id}`) navigate('/', { replace: true })
    },
  })

  return (
    <Dialog
      open={chat !== null}
      onOpenChange={(open) => {
        if (!open) del.reset()
        onOpenChange(open)
      }}
    >
      {chat && (
        <DialogContent aria-describedby="delete-chat-desc">
          <DialogTitle>Delete this chat?</DialogTitle>
          <DialogDescription id="delete-chat-desc">
            “{chat.title}” and its history will be deleted, and its sandbox stopped. This can't be undone.
          </DialogDescription>
          {del.isError && (
            <p role="alert" className="mb-0 mt-3 text-sm text-bad">
              {messageOf(del.error)}
            </p>
          )}
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline" size="sm">
                Cancel
              </Button>
            </DialogClose>
            <Button variant="dangerSolid" size="sm" disabled={del.isPending} onClick={() => del.mutate(chat.id)}>
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      )}
    </Dialog>
  )
}
