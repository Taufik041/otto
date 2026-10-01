import { useEffect, useState } from 'react'
import { Outlet, useLocation, useOutletContext } from 'react-router'
import { useIsMobile } from '@/hooks/useMediaQuery'
import { Sidebar } from './Sidebar'

type ShellContext = { mobile: boolean; openDrawer: () => void }

export const useShell = () => useOutletContext<ShellContext>()

const COLLAPSED_KEY = 'otto.sidebar.collapsed'

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === '1'
  } catch {
    return false
  }
}

/** The sidebar and the page: collapsible on desktop, a drawer over a scrim on phones. */
export function AppShell() {
  const mobile = useIsMobile()
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const [drawer, setDrawer] = useState(false)
  const loc = useLocation()

  useEffect(() => setDrawer(false), [loc.pathname])
  useEffect(() => {
    if (!drawer) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setDrawer(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [drawer])

  const toggle = () => {
    if (mobile) return setDrawer(false)
    setCollapsed((c) => {
      try {
        localStorage.setItem(COLLAPSED_KEY, c ? '0' : '1')
      } catch {
        // fine
      }
      return !c
    })
  }

  const width = mobile ? 300 : collapsed ? 64 : 272
  return (
    <div className="flex h-full overflow-hidden">
      {mobile && drawer && (
        <div aria-hidden="true" onClick={() => setDrawer(false)} className="fixed inset-0 z-[79] bg-scrim animate-fade" />
      )}
      <aside
        aria-label="Sidebar"
        inert={mobile && !drawer ? true : undefined}
        className="top-0 bottom-0 left-0 z-[80] flex min-h-0 shrink-0 flex-col border-0 border-r border-solid border-line bg-bg2 transition-[transform,width] duration-300 ease-in-out"
        style={{
          position: mobile ? 'fixed' : 'relative',
          width,
          transform: mobile && !drawer ? 'translateX(-105%)' : 'none',
        }}
      >
        <Sidebar
          mobile={mobile}
          collapsed={collapsed}
          onToggle={toggle}
          onNavigate={() => setDrawer(false)}
        />
      </aside>
      <div className="relative flex min-w-0 flex-1 flex-col bg-bg">
        <Outlet context={{ mobile, openDrawer: () => setDrawer(true) } satisfies ShellContext} />
      </div>
    </div>
  )
}
