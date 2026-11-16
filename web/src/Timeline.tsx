import { useEffect, useMemo, useRef, useState } from 'react'

import type { Frame } from './data'
import { formatFlux } from './data'

/**
 * Timeline: two tracks, one time axis.
 *
 * Track 1 (top) is WHEN we observed: one mark per epoch at its real t_min, so the
 * nine-month hole between the 2025 and 2026 seasons is a hole and not a smooth run.
 * Track 2 (bottom) is WHAT we measured: flux against the same x, so a brightening
 * star reads as a shape rather than a number in a panel.
 *
 * The two tracks share one x mapping. That alignment is the argument of the whole
 * product: the gaps in the science are the gaps in the coverage.
 *
 * 1 user unit = 1 CSS pixel (measured via ResizeObserver), so date labels keep their
 * proportions and a mark's screen position matches its time exactly.
 */

type Props = {
  frames: Frame[]
  index: number
  onSelect: (index: number) => void
  accent: string
}

// Vertical budget: epochs band, then the curve, then the month axis.
// The axis needs room for two rows of labels (month, then year on the change), so
// H_AXIS must be deeper than the year baseline: curveEnd + 24 must stay under HEIGHT.
const H_EPOCH_TOP = 18
const H_EPOCH = 9
const H_CURVE_TOP = 40
const H_CURVE = 74
const H_AXIS = 30
const HEIGHT = H_CURVE_TOP + H_CURVE + H_AXIS

const PAD_L = 58
const PAD_R = 22

export function Timeline({ frames, index, onSelect, accent }: Props) {
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const [width, setWidth] = useState(0)
  const [hover, setHover] = useState<number | null>(null)

  useEffect(() => {
    const element = wrapRef.current
    if (!element) return
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) setWidth(entry.contentRect.width)
    })
    observer.observe(element)
    setWidth(element.getBoundingClientRect().width)
    return () => observer.disconnect()
  }, [])

  const layout = useMemo(() => {
    if (frames.length === 0 || width <= 0) {
      return { marks: [], ticks: [], curve: '', points: [], usable: 0, fluxLo: 0, fluxHi: 1, hasFlux: false }
    }

    const times = frames.map((frame) => frame.t_min)
    const t0 = Math.min(...times)
    const t1 = Math.max(...times)
    const span = Math.max(t1 - t0, 1e-6)
    const usable = Math.max(width - PAD_L - PAD_R, 10)
    const x = (t: number) => PAD_L + ((t - t0) / span) * usable

    const fluxes = frames.map((frame) => frame.measure?.flux ?? null)
    const finite = fluxes.filter((value): value is number => value !== null && Number.isFinite(value))
    // No photometry at all is a real outcome (a saturated core), not a scale of 0–1.
    // Drawing an empty 0–1 axis would read as "we measured no light" instead.
    const hasFlux = finite.length > 0
    const fluxLo = hasFlux ? Math.min(...finite) : 0
    const fluxHi = hasFlux ? Math.max(...finite) : 1
    // A flat sequence must not divide by zero, and a 16% headroom keeps peaks off the edge.
    const pad = Math.max((fluxHi - fluxLo) * 0.16, fluxHi * 0.02, 1e-9)
    const y = (flux: number) =>
      H_CURVE_TOP + H_CURVE - ((flux - (fluxLo - pad)) / (fluxHi + pad - (fluxLo - pad))) * H_CURVE

    const points = frames.map((frame, i) => ({
      i,
      x: x(frame.t_min),
      y: frame.measure && Number.isFinite(frame.measure.flux) ? y(frame.measure.flux) : null,
      date: frame.date,
      flux: frame.measure?.flux ?? null,
      snr: frame.measure?.snr ?? null,
      bad: frame.bad_fraction > 0.5,
    }))

    // One continuous path through the measured points; nulls break the line rather
    // than being interpolated across, because a missing measurement is not a value.
    let curve = ''
    points.forEach((point) => {
      if (point.y === null) return
      curve += `${curve ? 'L' : 'M'}${point.x.toFixed(1)},${point.y.toFixed(1)}`
    })

    // Monthly ticks, labelled only where they fit.
    const months: Array<{ t: number; label: string; year: number }> = []
    const first = new Date(`${frames[0].date}T00:00:00Z`)
    const last = new Date(`${frames[frames.length - 1].date}T00:00:00Z`)
    const cursor = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth(), 1))
    while (cursor <= last) {
      months.push({
        t: 40587 + cursor.getTime() / 86400000,
        label: cursor.toLocaleDateString('en-GB', { month: 'short', timeZone: 'UTC' }),
        year: cursor.getUTCFullYear(),
      })
      cursor.setUTCMonth(cursor.getUTCMonth() + 1)
    }
    const stride = Math.max(1, Math.ceil(months.length / Math.max(2, Math.floor(usable / 52))))
    const ticks = months
      .map((month, i) => ({ ...month, i, x: x(month.t) }))
      .filter((month) => month.i % stride === 0 && month.t >= t0 && month.t <= t1)

    return { marks: points, ticks, curve, points, usable, fluxLo, fluxHi, span, hasFlux }
  }, [frames, width])

  if (frames.length === 0) {
    return <div className="timeline timeline--empty">no epochs</div>
  }

  const active = layout.points[index]
  const hovered = hover !== null ? layout.points[hover] : null
  const years = (frames[frames.length - 1].t_min - frames[0].t_min) / 365.25

  const handleClick = (event: React.MouseEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    const px = event.clientX - rect.left
    let best = 0
    let bestDistance = Infinity
    layout.points.forEach((point) => {
      const distance = Math.abs(point.x - px)
      if (distance < bestDistance) {
        bestDistance = distance
        best = point.i
      }
    })
    onSelect(best)
  }

  const curveStart = H_CURVE_TOP
  const curveEnd = H_CURVE_TOP + H_CURVE

  return (
    <div className="timeline track track--date" ref={wrapRef}>
      <div className="timeline-head">
        <span className="timeline-title">Dates</span>
        <span className="timeline-sub mono tnum">
          {layout.hasFlux
            ? `flux ${formatFlux(layout.fluxLo)}–${formatFlux(layout.fluxHi)} mJy · `
            : ''}
          {frames.length} epochs · {years.toFixed(2)} yr
        </span>
      </div>

      <svg
        width={width || 1}
        height={HEIGHT}
        viewBox={`0 0 ${width || 1} ${HEIGHT}`}
        className="timeline-svg"
        onClick={handleClick}
        onMouseMove={(event) => {
          const rect = event.currentTarget.getBoundingClientRect()
          const px = event.clientX - rect.left
          let best = 0
          let bestDistance = Infinity
          layout.points.forEach((point) => {
            const distance = Math.abs(point.x - px)
            if (distance < bestDistance) {
              bestDistance = distance
              best = point.i
            }
          })
          setHover(bestDistance < 26 ? best : null)
        }}
        onMouseLeave={() => setHover(null)}
        role="slider"
        aria-label="observation epochs"
        aria-valuemin={0}
        aria-valuemax={frames.length - 1}
        aria-valuenow={index}
        aria-valuetext={frames[index]?.date}
        tabIndex={0}
        onKeyDown={(event) => {
          if (event.key === 'ArrowRight') onSelect(Math.min(index + 1, frames.length - 1))
          if (event.key === 'ArrowLeft') onSelect(Math.max(index - 1, 0))
        }}
      >
        {/* ---- track 1: coverage ---- */}
        <text x={PAD_L - 8} y={H_EPOCH_TOP + H_EPOCH - 2} className="timeline-track-label" textAnchor="end">
          SEEN
        </text>
        <rect
          x={PAD_L}
          y={H_EPOCH_TOP}
          width={Math.max(layout.usable, 1)}
          height={H_EPOCH}
          fill="#15151a"
        />
        {layout.marks.map((mark) => (
          <rect
            key={`cov-${mark.i}`}
            x={mark.x - 1.6}
            y={H_EPOCH_TOP}
            width={mark.i === index ? 5 : 3.2}
            height={H_EPOCH}
            rx={1}
            fill={mark.bad ? '#c15f3c' : mark.i === index ? accent : '#4e4e5c'}
          />
        ))}

        {/* ---- track 2: the measured light curve ---- */}
        <text x={PAD_L - 8} y={curveStart + 9} className="timeline-track-label" textAnchor="end">
          FLUX
        </text>

        {layout.hasFlux ? (
          <>
            <text x={PAD_L - 8} y={curveStart + 9 + 18} className="timeline-value-label" textAnchor="end">
              {formatFlux(layout.fluxHi)}
            </text>
            <text x={PAD_L - 8} y={curveEnd + 2} className="timeline-value-label" textAnchor="end">
              {formatFlux(layout.fluxLo)}
            </text>

            {[0, 0.5, 1].map((frac) => (
              <line
                key={`grid-${frac}`}
                x1={PAD_L}
                x2={width - PAD_R}
                y1={curveStart + frac * H_CURVE}
                y2={curveStart + frac * H_CURVE}
                stroke="#1e1e25"
                strokeWidth={1}
              />
            ))}
          </>
        ) : (
          // An empty 0–1 axis would read as "we measured no light". The truth is that
          // every core saturated, so only a lower bound exists and nothing can be plotted.
          <text
            x={PAD_L + 4}
            y={curveStart + H_CURVE / 2 + 3}
            className="timeline-nophotom"
            textAnchor="start"
          >
            no photometry — target core saturated in all {frames.length} epochs
          </text>
        )}

        {layout.curve && (
          <path
            d={layout.curve}
            fill="none"
            stroke={accent}
            strokeWidth={1.6}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        )}

        {layout.points.map((point) =>
          point.y === null ? null : (
            <circle
              key={`pt-${point.i}`}
              cx={point.x}
              cy={point.y}
              r={point.i === index ? 3.4 : 1.9}
              fill={point.i === index ? accent : '#0a0a0c'}
              stroke={accent}
              strokeWidth={point.i === index ? 0 : 1.1}
            />
          ),
        )}

        {/* ---- shared axis ---- */}
        {layout.ticks.map((tick, i) => (
          <g key={`tick-${tick.label}-${tick.x.toFixed(0)}`}>
            <line
              x1={tick.x}
              y1={curveEnd + 1}
              x2={tick.x}
              y2={curveEnd + 5}
              stroke="#2a2a31"
              strokeWidth={1}
            />
            <text x={tick.x} y={curveEnd + 15} fill="#5f5e5c" fontSize={9} textAnchor="middle" className="tnum">
              {tick.label}
            </text>
            {i > 0 && tick.year !== layout.ticks[i - 1].year && (
              <text x={tick.x} y={curveEnd + 24} fill="#3f3f49" fontSize={8} textAnchor="middle" className="tnum">
                {tick.year}
              </text>
            )}
          </g>
        ))}

        {/* ---- playhead: one line through both tracks ---- */}
        {active && (
          <g>
            <line
              x1={active.x}
              y1={H_EPOCH_TOP - 4}
              x2={active.x}
              y2={curveEnd + 1}
              stroke={accent}
              strokeOpacity={0.35}
              strokeWidth={1}
            />
            {active.y !== null && (
              <circle cx={active.x} cy={active.y} r={6} fill="none" stroke={accent} strokeWidth={1.2} />
            )}
          </g>
        )}

        {/* ---- hover readout ---- */}
        {hovered && hovered.i !== index && (
          <g>
            <line
              x1={hovered.x}
              y1={H_EPOCH_TOP - 4}
              x2={hovered.x}
              y2={curveEnd + 1}
              stroke="#5f5e5c"
              strokeWidth={1}
              strokeDasharray="2 3"
            />
            {hovered.y !== null && <circle cx={hovered.x} cy={hovered.y} r={2.6} fill="#8b8a87" />}
          </g>
        )}
      </svg>

      <div className="timeline-foot mono tnum">
        <span>{frames[0]?.date}</span>
        <span className="timeline-readout">
          {hovered && hovered.i !== index
            ? `${hovered.date} · ${hovered.flux !== null ? formatFlux(hovered.flux) : '—'}`
            : active?.flux != null
              ? `${active.date} · ${formatFlux(active.flux, frames[index]?.measure?.flux_err)}`
              : `${active?.date ?? ''}`}
        </span>
        <span>{frames[frames.length - 1]?.date}</span>
      </div>
    </div>
  )
}
