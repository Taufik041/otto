import { useSyncExternalStore } from 'react'

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const mql = window.matchMedia(query)
      mql.addEventListener('change', onChange)
      return () => mql.removeEventListener('change', onChange)
    },
    () => window.matchMedia(query).matches,
  )
}

/** Phones: the sidebar becomes a drawer and popovers become bottom sheets. */
export const MOBILE_QUERY = '(max-width: 767px)'
export const useIsMobile = () => useMediaQuery(MOBILE_QUERY)
