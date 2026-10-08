import { useMutation } from '@tanstack/react-query'
import { api } from '@/api'
import { ApiError, messageOf } from '@/api/errors'
import { DEMO_BOOKING_URL } from '@/utils/links'

export const WORKERS_OFFLINE = "Otto's workers are offline right now. Plain chat still works."

/** The composer's note while the workers are offline: ask Taufik to bring them up (an email to
 *  him, POST /wake-requests), or book a live demo. */
export function WorkersOffline({ bookingUrl = DEMO_BOOKING_URL }: { bookingUrl?: string | null }) {
  const ask = useMutation({ mutationFn: () => api.wakeRequest() })
  // asked within the hour already (429): he has been told
  const notified = ask.isSuccess || (ask.error instanceof ApiError && ask.error.status === 429)
  return (
    <div className="mb-2.5 rounded-[14px] border border-solid border-hair bg-bg2 px-3.5 py-[11px] text-sm leading-[1.45] text-muted">
      <div className="flex items-start gap-2.5">
        <span aria-hidden="true" className="mt-1.5 size-2 shrink-0 rounded-full border-[1.5px] border-solid border-ter" />
        <span>{WORKERS_OFFLINE}</span>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5 pl-[18px]">
        {notified ? (
          <span role="status" className="text-text">Taufik has been notified.</span>
        ) : (
          <button
            type="button"
            disabled={ask.isPending}
            onClick={() => ask.mutate()}
            className="border-0 bg-transparent p-0 text-sm text-accent hover:text-accent-h disabled:text-muted"
          >
            {ask.isPending ? 'Asking…' : 'Ask Taufik to bring it up'}
          </button>
        )}
        {bookingUrl && (
          <a href={bookingUrl} target="_blank" rel="noopener noreferrer" className="text-sm">
            Book a live demo
          </a>
        )}
        {ask.isError && !notified && <span role="alert" className="text-bad">{messageOf(ask.error)}</span>}
      </div>
    </div>
  )
}
