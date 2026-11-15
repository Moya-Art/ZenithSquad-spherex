/**
 * Flux against wavelength for the 102 planes.
 *
 * Hand-rolled SVG for the same reason `Timeline` is: one user unit is one CSS pixel (measured with
 * `ResizeObserver`), so labels are not distorted and the playhead sits exactly on its channel.
 *
 * Nulls break the line instead of being drawn through: a blank dichroic channel is a hole in the
 * spectrum, and joining across it would invent data.
 */

import { useEffect, useMemo, useRef, useState } from 'react'

import type { CubePlane, CubeSpectrumPoint } from './data'

type Props = {
  planes: CubePlane[]
  points: CubeSpectrumPoint[]
  active: number
  onSelect: (index: number) => void
}

const H_CURVE = 96
const H_AXIS = 26
const HEIGHT = H_CURVE + H_AXIS
const PAD_L = 46
const PAD_R = 14
const PAD_T = 10

/** The markers the notebook plots over its own spectra (`spherex_hipscube` §6.3). */
const LINES: Array<[number, string]> = [
  [1.282, 'Paβ'],
  [1.6, 'H⁻'],
  [1.875, 'Paα'],
  [2.166, 'Brγ'],
  [2.626, 'Brβ'],
  [3.3, 'PAH'],
  [4.052, 'Brα'],
  [4.67, 'CO'],
]

export function SpectrumChart({ planes, points, active, onSelect }: Props) {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const [width, setWidth] = useState(640)

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    const observer = new ResizeObserver((entries) => {
      const measured = entries[0]?.contentRect.width ?? 0
      if (measured > 0) setWidth(Math.round(measured))
    })
    observer.observe(host)
    return () => observer.disconnect()
  }, [])

  const layout = useMemo(() => {
    const byIndex = new Map(points.map((point) => [point.index, point]))
    const rows = planes
      .map((plane) => ({ plane, point: byIndex.get(plane.index) ?? null }))
      .filter((row) => row.point != null)
    if (!rows.length) return null

    const waves = rows.map((row) => row.plane.wavelength_um)
    const xMin = Math.min(...waves)
    const xMax = Math.max(...waves)
    const peak = Math.max(
      ...rows.map((row) => {
        const flux = row.point?.flux_mjy ?? 0
        const noise = row.point?.noise_mjy ?? 0
        return flux + noise
      }),
      1e-6,
    )

    const plotW = Math.max(width - PAD_L - PAD_R, 40)
    const x = (wave: number) => PAD_L + ((wave - xMin) / (xMax - xMin || 1)) * plotW
    const y = (flux: number) => PAD_T + H_CURVE - (flux / peak) * (H_CURVE - PAD_T)

    const plotted = rows.map((row) => ({
      index: row.plane.index,
      wavelength: row.plane.wavelength_um,
      flux: row.point?.flux_mjy ?? null,
      noise: row.point?.noise_mjy ?? null,
      cx: x(row.plane.wavelength_um),
    }))

    let path = ''
    let open = false
    for (const item of plotted) {
      if (item.flux == null) {
        open = false
        continue
      }
      path += `${open ? 'L' : 'M'}${item.cx.toFixed(2)},${y(item.flux).toFixed(2)} `
      open = true
    }

    return { plotted, path, x, y, xMin, xMax, peak }
  }, [planes, points, width])

  const current = layout?.plotted.find((item) => item.index === active) ?? null

  const handlePointer = (event: React.PointerEvent<SVGSVGElement>) => {
    if (!layout) return
    const box = event.currentTarget.getBoundingClientRect()
    const px = event.clientX - box.left
    let best = layout.plotted[0]
    for (const item of layout.plotted) {
      if (Math.abs(item.cx - px) < Math.abs(best.cx - px)) best = item
    }
    onSelect(best.index)
  }

  return (
    <div className="spectrum" ref={hostRef}>
      <div className="spectrum-head">
        <span className="spectrum-title">Spectrum</span>
        <span className="spectrum-meta mono tnum">
          {current
            ? `${current.wavelength.toFixed(3)} µm · ${
                current.flux == null ? 'no data' : `${current.flux.toFixed(0)} mJy`
              }`
            : '—'}
        </span>
      </div>

      {layout && (
        <svg
          width={width}
          height={HEIGHT}
          viewBox={`0 0 ${width} ${HEIGHT}`}
          role="slider"
          tabIndex={0}
          aria-label="spectrum by wavelength"
          aria-valuemin={0}
          aria-valuemax={Math.max(layout.plotted.length - 1, 0)}
          aria-valuenow={active}
          aria-valuetext={current ? `${current.wavelength.toFixed(3)} micrometres` : 'no plane'}
          onPointerDown={handlePointer}
          onKeyDown={(event) => {
            if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
              event.preventDefault()
              const step = event.key === 'ArrowRight' ? 1 : -1
              const position = layout.plotted.findIndex((item) => item.index === active)
              const next = layout.plotted[position + step]
              if (next) onSelect(next.index)
            }
          }}
        >
          <line
            x1={PAD_L}
            x2={width - PAD_R}
            y1={PAD_T + H_CURVE}
            y2={PAD_T + H_CURVE}
            stroke="#2a2a31"
          />
          <text x={2} y={PAD_T + 4} fontSize={8} fill="#5f5e5c" className="tnum">
            {layout.peak.toFixed(0)} mJy
          </text>
          <text x={2} y={PAD_T + H_CURVE} fontSize={8} fill="#5f5e5c" className="tnum">
            0
          </text>

          {LINES.filter(([wave]) => wave > layout.xMin && wave < layout.xMax).map(([wave, name]) => (
            <g key={name}>
              <line
                x1={layout.x(wave)}
                x2={layout.x(wave)}
                y1={PAD_T}
                y2={PAD_T + H_CURVE}
                stroke="#c15f3c"
                strokeWidth={0.7}
                strokeDasharray="2 3"
                opacity={0.5}
              />
              <text
                x={layout.x(wave)}
                y={PAD_T + 7}
                fontSize={8}
                fill="#c15f3c"
                textAnchor="middle"
                opacity={0.85}
              >
                {name}
              </text>
            </g>
          ))}

          <path d={layout.path} fill="none" stroke="#8b8a87" strokeWidth={0.8} opacity={0.5} />

          {layout.plotted.map((item) => {
            const isActive = item.index === active
            if (item.flux == null) return null
            const bar = item.noise ?? 0
            return (
              <g key={item.index}>
                <line
                  x1={item.cx}
                  x2={item.cx}
                  y1={layout.y(Math.max(item.flux - bar, 0))}
                  y2={layout.y(item.flux + bar)}
                  stroke={isActive ? 'var(--accent)' : '#4e4e5c'}
                  strokeWidth={0.8}
                  opacity={isActive ? 1 : 0.7}
                />
                <circle
                  cx={item.cx}
                  cy={layout.y(item.flux)}
                  r={isActive ? 2.6 : 1.5}
                  fill={isActive ? 'var(--accent)' : '#8b8a87'}
                />
              </g>
            )
          })}

          {current && current.flux != null && (
            <line
              x1={current.cx}
              x2={current.cx}
              y1={PAD_T}
              y2={PAD_T + H_CURVE}
              stroke="var(--accent)"
              strokeWidth={0.8}
              opacity={0.45}
            />
          )}

          <text x={PAD_L} y={HEIGHT - 6} fontSize={8} fill="#5f5e5c" className="tnum">
            {layout.xMin.toFixed(2)} µm
          </text>
          <text
            x={width - PAD_R}
            y={HEIGHT - 6}
            fontSize={8}
            fill="#5f5e5c"
            textAnchor="end"
            className="tnum"
          >
            {layout.xMax.toFixed(2)} µm
          </text>
        </svg>
      )}

      <div className="spectrum-foot">
        Aperture photometry per plane, background from an annulus. Visualization grade — for
        science numbers use the IRSA SPHEREx Spectrophotometry tool.
      </div>
    </div>
  )
}
