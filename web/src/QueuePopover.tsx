import type { QueueJob } from './data'

/**
 * Builds in flight.
 *
 * Only cubes are queued: a date sequence is one blocking request, shown inside its own plate, and it
 * cannot outlive navigation. The note says so rather than letting the panel imply both sources behave
 * the same.
 */

type Props = {
  jobs: QueueJob[] | null
  error: string | null
}

function progressLine(job: QueueJob): string {
  if (job.state === 'failed') return 'failed'
  if (job.bytes_total && job.bytes_done != null) {
    return `${(job.bytes_done / 1e6).toFixed(0)} / ${(job.bytes_total / 1e6).toFixed(0)} MB`
  }
  if (job.planes_total) return `planes ${job.planes_done}/${job.planes_total}`
  return job.stage ?? job.state
}

export function QueuePopover({ jobs, error }: Props) {
  return (
    <div className="popover-body">
      <div className="popover-title">Queued builds</div>

      {error && <div className="popover-error">{error}</div>}
      {!error && jobs === null && <div className="popover-note">Reading the queue…</div>}
      {!error && jobs !== null && jobs.length === 0 && (
        <div className="popover-note">No queued builds.</div>
      )}

      {jobs?.map((job) => (
        <div key={job.key} className={`queue-row is-${job.state}`}>
          <div className="queue-head">
            <span className="queue-name">{job.name}</span>
            <span className="queue-state mono">{job.state}</span>
          </div>
          <div className="queue-meta mono tnum">
            {progressLine(job)}
            {job.eta_seconds != null && job.state !== 'failed' ? ` · about ${job.eta_seconds}s left` : ''}
          </div>
          <div className="queue-coords mono tnum">
            RA {job.ra.toFixed(4)} · Dec {job.dec >= 0 ? '+' : ''}
            {job.dec.toFixed(4)}
          </div>
        </div>
      ))}

      <div className="popover-foot">
        Cubes only. A date sequence is a single request and cannot outlive navigation.
      </div>
    </div>
  )
}
