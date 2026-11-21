import type { WardGeometry } from '../api/service'
import { scoreBand } from '../wardMetrics'

function planPoint(longitude: number, latitude: number) {
  return [longitude * Math.PI / 180, -Math.log(Math.tan(Math.PI / 4 + latitude * Math.PI / 360))]
}

export default function WardPlan({ geometry, activeId, onSelect }: {
  geometry: WardGeometry
  activeId?: string
  onSelect: (id: string) => void
}) {
  const shapes = geometry.features.map(({ geometry, properties }) => ({
    properties,
    rings: (geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates)
      .flatMap((polygon) => polygon.map((ring) => ring.map(([lon, lat]) => planPoint(lon, lat)))),
  }))
  const points = shapes.flatMap((shape) => shape.rings.flat())
  if (!points.length) return null
  const [minX, maxX, minY, maxY] = points.reduce(
    ([left, right, top, bottom], [x, y]) => [Math.min(left, x), Math.max(right, x), Math.min(top, y), Math.max(bottom, y)],
    [Infinity, -Infinity, Infinity, -Infinity],
  )
  const scale = 630 / Math.max(maxX - minX, maxY - minY, Number.EPSILON)
  const path = (rings: number[][][]) => rings.map((ring) =>
    ring.map(([x, y], index) => `${index === 0 ? 'M' : 'L'} ${35 + (x - minX) * scale} ${35 + (y - minY) * scale}`).join(' ') + ' Z',
  ).join(' ')

  return (
    <svg className="ward-plan" viewBox={`0 0 ${70 + (maxX - minX) * scale} ${70 + (maxY - minY) * scale}`}
      aria-label="2D synthetic ward boundaries">
      <defs><pattern id="ward-plan-hatching" width="9" height="9" patternUnits="userSpaceOnUse" patternTransform="rotate(35)">
        <rect width="9" height="9" fill="#aebccd" /><line x1="0" y1="0" x2="0" y2="9" stroke="#56697c" strokeWidth="3" />
      </pattern></defs>
      {shapes.map(({ properties, rings }) => {
        const band = scoreBand('status' in properties && typeof properties.status === 'string' ? properties.status : undefined,
          'score' in properties && typeof properties.score === 'number' ? properties.score : undefined)
        const selected = activeId === properties.ward_id
        const label = properties.ward_name + ' · ' + band.label
        return <path key={properties.ward_id} d={path(rings)} fillRule="evenodd"
          fill={band.id === 'insufficient' ? 'url(#ward-plan-hatching)' : band.color}
          stroke="#213e59" strokeWidth={selected ? 5 : 1.5} role="button" tabIndex={0} aria-label={label} aria-pressed={selected}
          onClick={() => onSelect(properties.ward_id)} onKeyDown={(event) => {
            if (event.key !== 'Enter' && event.key !== ' ') return
            event.preventDefault()
            onSelect(properties.ward_id)
          }}><title>{label}</title></path>
      })}
    </svg>
  )
}
