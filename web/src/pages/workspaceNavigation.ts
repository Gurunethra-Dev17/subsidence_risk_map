import { useSyncExternalStore } from 'react'

const fragments = {
  map: '#overview-map',
  inspector: '#ward-inspector',
  brief: '#inspection-brief',
  methods: '#methods',
  validation: '#validation',
  limitations: '#limitations',
} as const

type View = keyof typeof fragments

function currentView(): View {
  const hash = window.location.hash
  if (hash === '#inspector') return 'inspector'
  return (Object.keys(fragments) as View[]).find((view) => fragments[view] === hash) ?? 'map'
}

function subscribe(onChange: () => void) {
  window.addEventListener('hashchange', onChange)
  return () => window.removeEventListener('hashchange', onChange)
}

export function useWorkspaceView() {
  return useSyncExternalStore(subscribe, currentView)
}

export const viewHref = (view: View) => fragments[view]
