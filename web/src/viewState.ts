/**
 * URL state: /view?target=&band=&epoch=&mode=&plane=&cmap=
 *
 * Phase 4 spec names ra/dec/band/epoch/fov. For the committed-file build the
 * target slug is what identifies a sequence, so `target` replaces `ra`/`dec`
 * until Phase 5 serves arbitrary coordinates. `epoch` is a date, not an index,
 * so a pasted URL keeps its meaning even if the frame list changes.
 *
 * Phase 6 adds a second mode. `plane` is the cube's wavelength-plane index and `cmap` the palette
 * id, so a shared link reproduces the exact view someone was looking at.
 */

export type Mode = 'time' | 'cube'

export type ViewState = {
  target: string
  band: string
  epoch: string | null
  mode: Mode
  plane: number | null
  cmap: string | null
}

const DEFAULT_TARGET = 'r_dra'

export function readViewState(): ViewState {
  const params = new URLSearchParams(window.location.search)
  const plane = params.get('plane')
  return {
    target: params.get('target') ?? DEFAULT_TARGET,
    band: params.get('band') ?? '',
    epoch: params.get('epoch'),
    mode: params.get('mode') === 'cube' ? 'cube' : 'time',
    plane: plane == null || plane === '' ? null : Number(plane),
    cmap: params.get('cmap'),
  }
}

export function writeViewState(state: ViewState): void {
  const params = new URLSearchParams()
  params.set('target', state.target)
  if (state.band) params.set('band', state.band)
  if (state.epoch) params.set('epoch', state.epoch)
  if (state.mode === 'cube') {
    params.set('mode', 'cube')
    if (state.plane != null) params.set('plane', String(state.plane))
    if (state.cmap) params.set('cmap', state.cmap)
  }

  const next = `${window.location.pathname}?${params.toString()}`
  window.history.replaceState(null, '', next)
}

export function shareUrl(): string {
  return window.location.href
}
