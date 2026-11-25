import { useLayoutEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

type Dimensions = { width: number; height: number }

export default function ChartFrame({ className, children }: {
  className: string
  children: (dimensions: Dimensions) => ReactNode
}) {
  const element = useRef<HTMLDivElement>(null)
  const [dimensions, setDimensions] = useState<Dimensions | null>(null)

  useLayoutEffect(() => {
    const frame = element.current
    if (!frame) return
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      const w = Math.floor(width)
      const h = Math.floor(height)
      setDimensions((previous) => {
        if (w <= 0 || h <= 0) return null
        return previous?.width === w && previous.height === h ? previous : { width: w, height: h }
      })
    })
    observer.observe(frame)
    return () => observer.disconnect()
  }, [])

  return <div className={className} ref={element}>{dimensions && children(dimensions)}</div>
}
