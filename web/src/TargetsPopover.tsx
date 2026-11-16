import { targetPreviewUrl, type Target } from './data'
import { TargetCard } from './TargetCard'

/**
 * The five named targets, behind one button.
 *
 * Each row carries its committed preview, its name, one plain-language sentence and the catalogue
 * facts. Picking a row writes the target's coordinates — not its slug — so choosing a target and
 * pasting its coordinates produce the same link and the same request.
 */

type Props = {
  targets: Target[]
  error: string | null
  current: Target | null
  onPick: (target: Target) => void
}

export function TargetsPopover({ targets, error, current, onPick }: Props) {
  return (
    <div className="popover-body">
      <div className="popover-title">Targets</div>

      {error && <div className="popover-error">{error}</div>}

      {targets.map((target) => {
        const active = current?.slug === target.slug
        return (
          <button
            key={target.slug}
            type="button"
            className={`target-row ${active ? 'is-active' : ''}`}
            onClick={() => onPick(target)}
            aria-current={active}
          >
            <img
              className="target-thumb"
              src={targetPreviewUrl(target)}
              alt={`${target.name} preview`}
              loading="lazy"
            />
            <span className="target-main">
              <span className="target-name">
                {target.name}
                <span className="target-band mono">{target.band}</span>
              </span>
              <TargetCard target={target} />
            </span>
          </button>
        )
      })}

      {!error && targets.length === 0 && <div className="popover-note">No targets loaded.</div>}
    </div>
  )
}
