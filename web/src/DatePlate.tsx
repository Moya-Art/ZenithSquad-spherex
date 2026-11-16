import { BlinkStage } from './BlinkStage'
import { LoadingNotice } from './LoadingNotice'
import type { Tint } from './colorAdjust'
import type { Colormap } from './colormaps'
import type { Frame, Sequence } from './data'
import type { SequenceState } from './useSequence'

/**
 * The date plate: the challenge's required objective, on the left.
 *
 * It owns nothing but presentation. Loading, transport and playback live in `useSequence`, so the
 * wavelength plate's state can never blank this one. Its caption is its own — the field and scale
 * here are different facts from the wavelength plate's.
 */

type Props = {
  label: string
  sequence: Sequence | null
  state: SequenceState
  error: string | null
  retry: () => void
  index: number
  setIndex: (index: number) => void
  step: (delta: number) => void
  playing: boolean
  setPlaying: (playing: boolean) => void
  ready: boolean
  setReady: (ready: boolean) => void
  frame: Frame | null
  sources: string[]
  labels: string[]
  palette: Colormap
  tint?: Tint
  band: string
  disabled: boolean
}

function captionForSequence(sequence: Sequence | null, band: string, loading: boolean): string {
  if (sequence) {
    return `${sequence.band} · ${sequence.size_deg}° · ${sequence.pixscale_arcsec.toFixed(
      2,
    )}″/px · ${sequence.frames.length} epochs`
  }
  if (loading) return band ? `${band} · loading…` : 'resolving the band…'
  return 'no sequence yet'
}

export function DatePlate({
  label,
  sequence,
  state,
  error,
  retry,
  index,
  setIndex,
  step,
  playing,
  setPlaying,
  ready,
  setReady,
  frame,
  sources,
  labels,
  palette,
  tint,
  band,
  disabled,
}: Props) {
  return (
    <section className="plate plate--date">
      <div className="plate-head">
        <span className="plate-title">The date</span>
        <span className="plate-caption mono tnum">
          {captionForSequence(sequence, band, state === 'loading')}
        </span>
      </div>

      {disabled && (
        <div className="notice">
          <div className="notice-title">Enter a coordinate</div>
          <div className="notice-body">
            The patch of sky loads from Right Ascension and Declination.
          </div>
        </div>
      )}

      {!disabled && state === 'loading' && <LoadingNotice kind="sequence" targetName={label} />}

      {!disabled && state === 'missing' && (
        <div className="notice">
          <div className="notice-title">No data was found</div>
          <div className="notice-body">Try another coordinate.</div>
        </div>
      )}

      {!disabled && state === 'error' && (
        <div className="notice notice--bad">
          <div className="notice-title">The archive did not answer</div>
          <div className="notice-body mono">{error}</div>
          <div className="notice-body">
            A first visit has to build the sequence from the archive, and IRSA drops requests often
            enough that this does sometimes fail.
          </div>
          <button type="button" className="notice-action" onClick={retry}>
            Try again
          </button>
        </div>
      )}

      {!disabled && sequence && frame && (
        <>
          <div className="plate-stage">
            <BlinkStage
              sources={sources}
              labels={labels}
              index={index}
              onIndexChange={setIndex}
              playing={playing}
              onPlayingChange={setPlaying}
              onReadyChange={setReady}
              palette={palette}
              tint={tint}
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
                disabled={!ready}
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

          {sequence.stale && (
            <p className="plate-note">
              Committed copy of this target, not a live build. It replaces itself if the archive
              answers.
            </p>
          )}

          {sequence.position_note && (
            <p className="plate-note">{sequence.position_note}</p>
          )}
        </>
      )}
    </section>
  )
}
