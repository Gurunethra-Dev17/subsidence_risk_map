import { Bar, BarChart, CartesianGrid, Tooltip, XAxis, YAxis } from 'recharts'
import type { Ward } from '../api/service'
import ChartFrame from './ChartFrame'

const decimal = new Intl.NumberFormat('en-IN', { maximumSignificantDigits: 8 })

export default function DistortionHistogram({ histogram }: { histogram: Ward['histogram'] }) {
  const edges = histogram?.bin_edges
  const counts = histogram?.counts
  const bins = edges && counts?.length && edges.length === counts.length + 1 &&
    edges.every((edge, i) => Number.isFinite(edge) && (i === 0 || edge > edges[i - 1])) &&
    counts.every((count) => Number.isInteger(count) && count >= 0)
    ? counts.map((count, i) => ({
      count, lower: decimal.format(edges[i]), range: `${decimal.format(edges[i])}–${decimal.format(edges[i + 1])}`,
    }))
    : []

  if (!bins.length) return <p className="muted-copy">No distortion histogram is available for this ward.</p>

  return (
    <figure className="histogram" aria-label="Distribution of building distortion">
      <ChartFrame className="chart-canvas">
        {(size) => (
          <BarChart {...size} accessibilityLayer data={bins} margin={{ top: 8, right: 12, bottom: 0, left: -20 }}>
            <CartesianGrid vertical={false} stroke="#dce2eb" strokeDasharray="3 4" />
            <XAxis dataKey="lower" axisLine={false} tickLine={false} tick={{ fill: '#53647b', fontSize: 12 }} minTickGap={18} />
            <YAxis allowDecimals={false} axisLine={false} tickLine={false} tick={{ fill: '#53647b', fontSize: 12 }} />
            <Tooltip cursor={{ fill: '#e9eef6' }} labelFormatter={(_label, payload) => payload[0]?.payload.range ?? ''}
              formatter={(value) => [value, 'Buildings']} />
            <Bar dataKey="count" name="Buildings" fill="#315f93" radius={[4, 4, 0, 0]} maxBarSize={40} isAnimationActive={false} />
          </BarChart>
        )}
      </ChartFrame>
      <figcaption>Building count per angular distortion interval (dimensionless). Axis labels show bin starts.</figcaption>
      <details className="chart-data">
        <summary>View bin counts</summary>
        <table><thead><tr><th scope="col">Distortion interval</th><th scope="col">Buildings</th></tr></thead>
          <tbody>{bins.map(({ range, count }) => <tr key={range}><th scope="row">{range}</th><td>{count.toLocaleString('en-IN')}</td></tr>)}</tbody>
        </table>
      </details>
    </figure>
  )
}
