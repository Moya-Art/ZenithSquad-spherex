import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import './tokens.css'
import './App.css'

import { BlinkStage } from './BlinkStage'
import { CubeView } from './CubeView'
import { Inspector } from './Inspector'
import { LoadingNotice } from './LoadingNotice'
import { PlateContext } from './PlateContext'
import { Timeline } from './Timeline'
import { COLORMAPS, type Colormap } from './colormaps'
import {
  frameUrl,
  loadCube,
  loadSequence,
  loadTargets,
  type Cube,
  type Sequence,
  type Target,
} from './data'
import { readViewState, writeViewState } from './viewState'

const BANDS = ['D1', 'D2', 'D3', 'D4', 'D5', 'D6']
const CUBE_POLL_MS = 2000

export default function App() {
  const initial = useMemo(() => readViewState(), [])

  const [targets, setTargets] = useState<Target[]>([])
  const [targetsError, setTargetsError] = useState<string | null>(null)
  const [slug, setSlug] = useState(initial.target)
  const [band, setBand] = useState(initial.band)
  const [sequence, setSequence] = useState<Sequence | null>(null)
  const [sequenceState, setSequenceState] = useState<'idle' | 'loading' | 'missing' | 'error'>('idle')
  const [sequenceError, setSequenceError] = useState<string | null>(null)
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [framesReady, setFramesReady] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const epochPending = useRef(true)

  const [mode, setMode] = useState<'time' | 'cube'>(initial.mode)
  const [plane, setPlane] = useState(initial.plane ?? 0)
  const [colormap, setColormap] = useState<Colormap>(
    () => COLORMAPS.find((entry) => entry.id === initial.cmap) ?? COLORMAPS[0],
  )
  const [cube, setCube] = useState<Cube | null>(null)
  const [cubeState, setCubeState] = useState<'idle' | 'loading' | 'error'>('idle')
  const [cubeError, setCubeError] = useState<string | null>(null)
  const [cubeAttempt, setCubeAttempt] = useState(0)


  useEffect(() => {
    loadTargets()
      .then(setTargets)
      .catch((error: Error) => setTargetsError(error.message))
  }, [])

  const target = targets.find((t) => t.slug === slug) ?? null
  const effectiveBand = band || target?.band || 'D6'

  useEffect(() => {
    if (!slug) return
    let cancelled = false
    setSequenceState('loading')
    setSequence(null)
    setSequenceError(null)

    loadSequence(slug, effectiveBand)
      .then((loaded) => {
        if (cancelled) return
        if (!loaded) {
          setSequenceState('missing')
          return
        }
        setSequence(loaded)
        setSequenceState('idle')

        // The URL's epoch only means something for the sequence it was captured from.
        // Apply it once, on first load; later band/target switches start at the first frame.
        const wanted = epochPending.current ? initial.epoch : null
        epochPending.current = false
        const found = wanted ? loaded.frames.findIndex((f) => f.date === wanted) : -1
        setIndex(found >= 0 ? found : 0)
      })
      .catch((error: Error) => {
        if (cancelled) return
        setSequenceState('error')
        setSequenceError(error.message)
      })

    return () => {
      cancelled = true
    }
  }, [slug, effectiveBand, initial.epoch, attempt])

  const frame = sequence?.frames[index] ?? null

  // Spectrum mode. A cold coordinate answers 202 with progress, so this polls the same URL until the
  // cube is ready; no job id is needed because the coordinate is the job.
  useEffect(() => {
    if (mode !== 'cube' || !slug) return
    let cancelled = false
    let timer: number | undefined
    setCube(null)
    setCubeState('loading')
    setCubeError(null)

    const fetchOnce = async () => {
      try {
        const loaded = await loadCube({ target: slug, refresh: cubeAttempt > 0 })
        if (cancelled) return
        setCube(loaded)
        setCubeState('idle')
        if (loaded && (loaded.state === 'building' || loaded.state === 'queued')) {
          timer = window.setTimeout(() => void fetchOnce(), CUBE_POLL_MS)
        }
      } catch (error) {
        if (cancelled) return
        setCubeState('error')
        setCubeError(error instanceof Error ? error.message : String(error))
      }
    }

    void fetchOnce()
    return () => {
      cancelled = true
      if (timer) window.clearTimeout(timer)
    }
  }, [mode, slug, cubeAttempt])

  // Keep the URL in step with the view.
  useEffect(() => {
    if (mode === 'cube') {
      const shareable = colormap.stops.length > 0 && !colormap.id.startsWith('random-')
      writeViewState({
        target: slug,
        band: '',
        epoch: null,
        mode: 'cube',
        plane,
        cmap: shareable ? colormap.id : null,
      })
      return
    }
    if (!frame) return
    writeViewState({
      target: slug,
      band: effectiveBand,
      epoch: frame.date,
      mode: 'time',
      plane: null,
      cmap: null,
    })
  }, [slug, effectiveBand, frame, mode, plane, colormap])

  const sources = useMemo(
    () => (sequence ? sequence.frames.map((f) => frameUrl(f)) : []),
    [sequence],
  )
  const labels = useMemo(
    () => (sequence ? sequence.frames.map((f) => f.date) : []),
    [sequence],
  )

  const step = useCallback(
    (delta: number) => {
      if (!sequence) return
      setPlaying(false)
      setIndex((current) => Math.min(Math.max(current + delta, 0), sequence.frames.length - 1))
    },
    [sequence],
  )

  // Transport keys. Space is play/pause; arrows step one epoch. In spectrum mode the plane scrubber
  // owns the arrows, so this map stands down rather than stepping a timeline nobody can see.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (mode !== 'time') return
      const tag = (event.target as HTMLElement | null)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA') return

      if (event.code === 'Space') {
        event.preventDefault()
        setPlaying((p) => !p)
      } else if (event.key === 'ArrowRight') {
        event.preventDefault()
        step(1)
      } else if (event.key === 'ArrowLeft') {
        event.preventDefault()
        step(-1)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [step, mode])

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <img
            className="brand-logo"
            src="/space-apps-logo.png"
            alt="NASA Space Apps Challenge"
          />
          <span className="brand-divider" aria-hidden="true" />
          <span className="brand-name">SPHEREx Sky-Time</span>
        </div>

        {target && (
          <div className="topbar-target mono tnum">
            RA {target.ra.toFixed(4)}° Dec {target.dec >= 0 ? '+' : ''}
            {target.dec.toFixed(4)}°
          </div>
        )}

        <div className="modes" role="group" aria-label="view mode">
          {(['time', 'cube'] as const).map((value) => (
            <button
              key={value}
              type="button"
              className={`mode ${mode === value ? 'is-active' : ''}`}
              onClick={() => setMode(value)}
              aria-pressed={mode === value}
            >
              {value === 'time' ? 'Time' : 'Spectrum'}
            </button>
          ))}
        </div>

        {mode === 'time' && (
          <div className="bands" role="group" aria-label="infrared band">
            {BANDS.map((b) => (
              <button
                key={b}
                type="button"
                className={`band ${b === effectiveBand ? 'is-active' : ''}`}
                onClick={() => {
                  setBand(b)
                  setIndex(0)
                  setPlaying(false)
                }}
                aria-pressed={b === effectiveBand}
              >
                {b}
              </button>
            ))}
          </div>
        )}
      </header>

      <div className="body">
        <nav className="rail" aria-label="targets">
          <div className="rail-title">Targets</div>
          {targetsError && <div className="rail-error">{targetsError}</div>}
          {targets.map((t) => (
            <button
              key={t.slug}
              type="button"
              className={`rail-item ${t.slug === slug ? 'is-active' : ''}`}
              onClick={() => {
                setSlug(t.slug)
                setBand('')
                setIndex(0)
                setPlaying(false)
              }}
              aria-current={t.slug === slug}
            >
              <span className="rail-name">{t.name}</span>
              <span className="rail-band mono">{t.band}</span>
            </button>
          ))}
        </nav>

        <main className="main">
          {mode === 'cube' && (
            <div className="cube-wrap">
              {cubeState === 'loading' && !cube && (
                <LoadingNotice targetName={target?.name ?? null} />
              )}

              {cubeState === 'error' && (
                <div className="notice notice--bad">
                  <div className="notice-title">Could not load this cube</div>
                  <div className="notice-body mono">{cubeError}</div>
                  <button
                    type="button"
                    className="notice-action"
                    onClick={() => setCubeAttempt((current) => current + 1)}
                  >
                    Try again
                  </button>
                </div>
              )}

              {cube && (
                <CubeView
                  cube={cube}
                  plane={plane}
                  onPlane={setPlane}
                  colormap={colormap}
                  onColormap={setColormap}
                  onRetry={() => setCubeAttempt((current) => current + 1)}
                />
              )}
            </div>
          )}

          {mode === 'time' && sequenceState === 'missing' && target && (
            <div className="notice">
              <div className="notice-title">
                No {effectiveBand} frames for {target.name}.
              </div>
              <div className="notice-body">
                The archive has nothing at this coordinate in that band, and there is no committed
                copy. Try another band, or another target.
              </div>
            </div>
          )}

          {mode === 'time' && sequenceState === 'error' && (
            <div className="notice notice--bad">
              <div className="notice-title">Could not load this patch of sky</div>
              <div className="notice-body mono">{sequenceError}</div>
              <div className="notice-body">
                A first visit has to build the sequence from the archive, and IRSA drops requests
                often enough that this does sometimes fail.
              </div>
              <button
                type="button"
                className="notice-action"
                onClick={() => setAttempt((current) => current + 1)}
              >
                Try again
              </button>
            </div>
          )}

          {mode === 'time' && sequenceState === 'loading' && (
            <LoadingNotice targetName={target?.name ?? null} />
          )}

          {mode === 'time' && sequence && frame && target && (
            <div className="workbench">
              <div className="plate">
                <div className="plate-head">
                  <span className="plate-name">{target.name}</span>
                  <span className="plate-meta mono">
                    {sequence.band} · {sequence.size_deg}° field · {sequence.frames.length} epochs
                  </span>
                </div>

                <div className="plate-body">
                  <div className="plate-stage">
                    <BlinkStage
                      sources={sources}
                      labels={labels}
                      index={index}
                      onIndexChange={setIndex}
                      playing={playing}
                      onPlayingChange={setPlaying}
                      onReadyChange={setFramesReady}
                    />

                    <div className="transport">
                      <button
                        type="button"
                        className="transport-btn"
                        onClick={() => step(-1)}
                        aria-label="previous epoch"
                      >
                        ‹
                      </button>
                      <button
                        type="button"
                        className="transport-btn transport-btn--play"
                        onClick={() => setPlaying(!playing)}
                        disabled={!framesReady}
                        aria-label={playing ? 'pause' : 'play'}
                      >
                        {playing ? '❙❙' : '▶'}
                      </button>
                      <button
                        type="button"
                        className="transport-btn"
                        onClick={() => step(1)}
                        aria-label="next epoch"
                      >
                        ›
                      </button>
                      <span className="transport-counter mono tnum">
                        {String(index + 1).padStart(2, '0')}
                        <span className="transport-total">
                          /{String(sequence.frames.length).padStart(2, '0')}
                        </span>
                      </span>
                      <span className="hint mono">space · ← →</span>
                    </div>
                  </div>

                  <PlateContext target={target} sequence={sequence} motion={sequence.motion} />
                </div>
              </div>

              <Inspector sequence={sequence} frame={frame} />
            </div>
          )}
        </main>
      </div>

      {mode === 'time' && sequence && (
        <Timeline
          frames={sequence.frames}
          index={index}
          onSelect={(i) => {
            setPlaying(false)
            setIndex(i)
          }}
          accent="var(--accent)"
        />
      )}
    </div>
  )
}
