import type { Frame, Sequence } from './data'

/**
 * Per-frame inspection.
 *
 * This panel answers one question: what did THIS epoch measure, and should I believe
 * it? Target-level statements (what the star is, what the whole sequence says about
 * motion) live in PlateContext, so a single epoch's noise never reads as a finding.
 *
 * SNR is the dominant number because it is the one that decides whether the frame is
 * worth looking at at all — flux is the raw quantity, SNR is the permission to trust it.
 */

type Props = {
  sequence: Sequence
  frame: Frame
}

export function Inspector({ sequence, frame }: Props) {
  const measure = frame.measure
  const outlier = frame.outlier
  const epoch = sequence.frames.findIndex((f) => f.obs_id === frame.obs_id) + 1

  const snr = measure?.snr ?? null
  const snrState = snr === null ? 'none' : snr < 3 ? 'weak' : snr < 10 ? 'faint' : 'solid'
  const snrNote =
    snrState === 'solid'
      ? 'well detected'
      : snrState === 'faint'
        ? 'detected, low confidence'
        : snrState === 'weak'
          ? 'below detection threshold'
          : 'no photometry in this frame'

  return (
    <aside className="inspector">
      <div className="inspect-block">
        <div className="inspect-key">Epoch</div>
        <div className="inspect-epoch mono tnum">
          {frame.date}
          <span className="inspect-epoch-index">
            {epoch}/{sequence.frames.length}
          </span>
        </div>
      </div>

      <div className="inspect-hero">
        <div className="inspect-key">Signal-to-noise</div>
        <div className={`inspect-hero-value mono tnum is-${snrState}`}>
          {snr === null ? '—' : snr.toFixed(1)}
        </div>
        <div className="inspect-hero-note">{snrNote}</div>
      </div>

      <div className="inspect-table">
        <div className="inspect-row">
          <span>flux</span>
          <span className="mono tnum">
            {measure ? `${measure.flux.toFixed(0)} ± ${measure.flux_err.toFixed(0)}` : '—'}
          </span>
        </div>
        <div className="inspect-row">
          <span>good pixels</span>
          <span className="mono tnum">{(100 * (1 - frame.bad_fraction)).toFixed(1)}%</span>
        </div>
        <div className="inspect-row">
          <span>Δ vs median</span>
          <span className="mono tnum">{outlier?.median?.toFixed(2) ?? '—'}</span>
        </div>
        <div className="inspect-row">
          <span>max |Δ|</span>
          <span className="mono tnum">{outlier?.max_abs?.toFixed(0) ?? '—'}</span>
        </div>
        <div className="inspect-row">
          <span>MJD</span>
          <span className="mono tnum">{frame.t_min.toFixed(2)}</span>
        </div>
        <div className="inspect-row">
          <span>exposure</span>
          <span className="mono inspect-truncate" title={frame.obs_id}>
            {frame.obs_id}
          </span>
        </div>
      </div>

      <div className="inspect-foot">
        Candidate for inspection, not a discovery.
      </div>
    </aside>
  )
}
