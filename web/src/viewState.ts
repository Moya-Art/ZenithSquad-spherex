/**
 * URL state: /view?target=&band=&epoch=
 *
 * Phase 4 spec names ra/dec/band/epoch/fov. For the committed-file build the
 * target slug is what identifies a sequence, so `target` replaces `ra`/`dec`
 * until Phase 5 serves arbitrary coordinates. `epoch` is a date, not an index,
 * so a pasted URL keeps its meaning even if the frame list changes.
 */

export type ViewState = {
  target: string
  band: string
  epoch: string | null
}

const DEFAULT_TARGET = 'r_dra'

export function readViewState(): ViewState {
  const params = new URLSearchParams(window.location.search)
  return {
    target: params.get('target') ?? DEFAULT_TARGET,
    band: params.get('band') ?? '',
    epoch: params.get('epoch'),
  }
}

export function writeViewState(state: ViewState): void {
  const params = new URLSearchParams()
  params.set('target', state.target)
  if (state.band) params.set('band', state.band)
  if (state.epoch) params.set('epoch', state.epoch)

  const next = `${window.location.pathname}?${params.toString()}`
  window.history.replaceState(null, '', next)
}

export function shareUrl(): string {
  return window.location.href
}
