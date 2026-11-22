import type { Ward } from './api/service'

export const scoreBands = [
  { id: 'lower', label: 'Lower priority', range: '0–<34', min: 0, color: '#8dc5e4' },
  { id: 'elevated', label: 'Elevated priority', range: '34–<67', min: 34, color: '#e6b34e' },
  { id: 'higher', label: 'Higher priority', range: '67–100', min: 67, color: '#a54b88' },
] as const

export const insufficientBand = { id: 'insufficient', label: 'Insufficient data', color: '#8796a5' } as const
export const unavailableBand = { id: 'unavailable', label: 'Score unavailable', color: '#c7ced7' } as const
export type ScoreBand = typeof scoreBands[number] | typeof insufficientBand | typeof unavailableBand

export function scoreBand(status: string | undefined, score: number | null | undefined): ScoreBand {
  if (status === 'insufficient_data') return insufficientBand
  if (status !== 'ranked' || score == null || !Number.isFinite(score)) return unavailableBand
  return score >= scoreBands[2].min ? scoreBands[2] : score >= scoreBands[1].min ? scoreBands[1] : scoreBands[0]
}

const formatter = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 1 })
export const formatNumber = (value: number) => formatter.format(value)
export const showNumber = (value: number | null | undefined) => value == null ? '—' : formatNumber(value)

export function rankRange(ward: Ward) {
  const { rank_p05: low, rank_p95: high } = ward
  return low != null && high != null && low <= high ? { low, high, label: low === high ? String(low) : `${low}–${high}` } : null
}

export const flagLabels: Record<Ward['flags'][number], string> = {
  sparse_points: 'Sparse radar points',
  groundwater_missing: 'Groundwater data missing',
  small_ward: 'Small ward sample',
  low_coverage: 'Low coverage',
  boundary_vintage: 'Boundary vintage flagged',
}
