import type { ReactNode } from 'react'

/** The composer's menus: on desktop a card above or below the composer, on phones a bottom sheet
 *  over a scrim. A click outside closes it. */
export function ComposerPopover({
  mobile,
  below,
  width,
  onClose,
  label,
  children,
}: {
  mobile: boolean
  below: boolean
  width: number
  onClose: () => void
  label: string
  children: ReactNode
}) {
  return (
    <>
      <div
        aria-hidden="true"
        onMouseDown={(e) => {
          e.preventDefault() // keep the textarea's focus
          onClose()
        }}
        className="fixed inset-0 z-40 animate-fade"
        style={{ background: mobile ? 'var(--scrim)' : 'transparent' }}
      />
      <div
        role="dialog"
        aria-label={label}
        onMouseDown={(e) => e.preventDefault()}
        className="z-[41] border border-solid border-line bg-card shadow-pop"
        style={
          mobile
            ? { position: 'fixed', left: 0, right: 0, bottom: 0, borderRadius: '22px 22px 0 0', padding: '8px 10px 30px', animation: 'otto-sheet .32s cubic-bezier(.2,.8,.2,1) both', maxHeight: '70dvh', overflowY: 'auto' }
            : {
                position: 'absolute',
                left: 0,
                width,
                borderRadius: 16,
                padding: 6,
                animation: 'otto-pop .18s ease-out both',
                ...(below ? { top: 'calc(100% + 10px)' } : { bottom: 'calc(100% + 10px)' }),
              }
        }
      >
        {mobile && <div className="mx-auto mb-2.5 mt-0.5 h-[5px] w-9 rounded-full bg-line" />}
        {children}
      </div>
    </>
  )
}
