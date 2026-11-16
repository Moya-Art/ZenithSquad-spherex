/**
 * Two independent fields, never one.
 *
 * A combined `"12.5, -30"` string makes `12.5` ambiguous between two axes, and a single error message
 * cannot say which side is wrong. Each field keeps its own value, its own placeholder and its own
 * message, and a bad value is rejected here — the component never fetches anything.
 */

type Props = {
  ra: string
  dec: string
  onRaChange: (value: string) => void
  onDecChange: (value: string) => void
  onSubmit: () => void
  errors?: { ra?: string; dec?: string } | null
  busy?: boolean
}

export function CoordinateInput({
  ra,
  dec,
  onRaChange,
  onDecChange,
  onSubmit,
  errors,
  busy,
}: Props) {
  return (
    <form
      className="nav-coords"
      onSubmit={(event) => {
        event.preventDefault()
        onSubmit()
      }}
    >
      <label className="coord-field">
        <span className="coord-label">RA</span>
        <input
          className="coord-input mono tnum"
          type="text"
          inputMode="decimal"
          value={ra}
          placeholder="0 – 360°"
          spellCheck={false}
          autoComplete="off"
          aria-invalid={Boolean(errors?.ra)}
          aria-describedby={errors?.ra ? 'coord-error-ra' : undefined}
          onChange={(event) => onRaChange(event.target.value)}
        />
        {errors?.ra && (
          <span className="coord-error" id="coord-error-ra" role="alert">
            {errors.ra}
          </span>
        )}
      </label>

      <label className="coord-field">
        <span className="coord-label">Dec</span>
        <input
          className="coord-input mono tnum"
          type="text"
          inputMode="decimal"
          value={dec}
          placeholder="−90 – 90°"
          spellCheck={false}
          autoComplete="off"
          aria-invalid={Boolean(errors?.dec)}
          aria-describedby={errors?.dec ? 'coord-error-dec' : undefined}
          onChange={(event) => onDecChange(event.target.value)}
        />
        {errors?.dec && (
          <span className="coord-error" id="coord-error-dec" role="alert">
            {errors.dec}
          </span>
        )}
      </label>

      <button type="submit" className="coord-go" disabled={busy}>
        {busy ? '…' : 'Go'}
      </button>
    </form>
  )
}
