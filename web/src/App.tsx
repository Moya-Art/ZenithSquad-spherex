import { useEffect, useMemo, useState } from 'react'

import './tokens.css'
import './App.css'

import { DatePlate } from './DatePlate'
import { Footer } from './Footer'
import { Navbar } from './Navbar'
import { Sidebar } from './Sidebar'
import { TrackStack } from './TrackStack'
import { WavelengthPlate } from './WavelengthPlate'
import { PALETTES, isComposite, type Colormap, type PaletteEntry } from './colormaps'
import {
  cubeCompositeUrl,
  cubePlaneUrl,
  loadTargets,
  type Target,
} from './data'
import { useCoordinate } from './useCoordinate'
import { useCube } from './useCube'
import { useGreyFrames } from './useGreyFrames'
import { useSequence } from './useSequence'

/**
 * The page: one coordinate, two plates, one palette.
 *
 * There is no mode and no slug: a coordinate is the only state, and it is in the URL. Everything that
 * is not layout lives in a hook (`useCoordinate`, `useSequence`, `useCube`) or a component, so this
 * file stays a composition and the two sources can never blank each other.
 */

export default function App() {
  const [targets, setTargets] = useState<Target[]>([])
  const [targetsError, setTargetsError] = useState<string | null>(null)
  const [band, setBand] = useState('')

  const [palette, setPalette] = useState<PaletteEntry>(PALETTES[0])
  // The date plate keeps whatever ramp was last chosen: the composite has no per-date meaning.
  const [datePalette, setDatePalette] = useState<Colormap>(PALETTES[0] as Colormap)

  const coords = useCoordinate(targets)
  const ra = coords.position?.ra ?? null
  const dec = coords.position?.dec ?? null

  const fallback = coords.target
    ? { slug: coords.target.slug, band: band || coords.target.band }
    : null

  // A coordinate cannot be matched to a committed artifact before the target list arrives, so the
  // date plate waits for that answer instead of firing a request that has no fallback.
  const targetsSettled = targets.length > 0 || targetsError !== null

  const dateLoad = useSequence(ra, dec, band || undefined, fallback, targetsSettled)
  const cubeLoad = useCube(ra, dec, coords.target?.slug ?? null)

  useEffect(() => {
    loadTargets()
      .then(setTargets)
      .catch((error: Error) => setTargetsError(error.message))
  }, [])

  const choosePalette = (entry: PaletteEntry) => {
    setPalette(entry)
    if (!isComposite(entry)) setDatePalette(entry)
  }

  // Swatch previews use whichever plate is decoded: a wavelength plane when the cube is loaded,
  // otherwise the frame on the date plate. Same greyscale source, so both swatch sets are honest.
  const thumbnailUrl = useMemo(() => {
    const planes = cubeLoad.cube?.planes ?? []
    if (planes.length > 0) {
      const selected = planes.find((plane) => plane.index === cubeLoad.plane) ?? planes[0]
      return cubePlaneUrl(selected)
    }
    return dateLoad.sources[dateLoad.index] ?? null
  }, [cubeLoad.cube, cubeLoad.plane, dateLoad.sources, dateLoad.index])

  const thumbnail = useGreyFrames(thumbnailUrl ? [thumbnailUrl] : []).frames[0] ?? null
  const compositeUrl = cubeLoad.cube ? cubeCompositeUrl(cubeLoad.cube) : null

  // Transport keys. Space is play/pause; arrows step one epoch. Ignored while typing a coordinate.
  useEffect(() => {
    if (!dateLoad.sequence) return
    const step = dateLoad.step
    const setPlaying = dateLoad.setPlaying
    const playing = dateLoad.playing

    const onKey = (event: KeyboardEvent) => {
      const tag = (event.target as HTMLElement | null)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return

      if (event.code === 'Space') {
        event.preventDefault()
        setPlaying(!playing)
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
  }, [dateLoad.sequence, dateLoad.step, dateLoad.setPlaying, dateLoad.playing])

  const disabled = coords.position === null
  const subject = coords.label

  return (
    <div className="app">
      <Navbar
        targets={targets}
        targetsError={targetsError}
        current={coords.target}
        ra={coords.raInput}
        dec={coords.decInput}
        errors={coords.errors}
        busy={dateLoad.state === 'loading'}
        onRaChange={coords.setRaInput}
        onDecChange={coords.setDecInput}
        onSubmit={coords.submit}
        onPick={(target) => coords.goTo({ ra: target.ra, dec: target.dec })}
      />

      <div className="workspace">
        <div className="stage">
          <DatePlate
            label={subject}
            sequence={dateLoad.sequence}
            state={dateLoad.state}
            error={dateLoad.error}
            retry={dateLoad.retry}
            index={dateLoad.index}
            setIndex={dateLoad.setIndex}
            step={dateLoad.step}
            playing={dateLoad.playing}
            setPlaying={dateLoad.setPlaying}
            ready={dateLoad.ready}
            setReady={dateLoad.setReady}
            frame={dateLoad.frame}
            sources={dateLoad.sources}
            labels={dateLoad.labels}
            palette={datePalette}
            band={band}
            disabled={disabled}
          />

          <WavelengthPlate
            label={subject}
            cube={cubeLoad.cube}
            loading={cubeLoad.loading}
            error={cubeLoad.error}
            requested={cubeLoad.requested}
            request={cubeLoad.request}
            retry={cubeLoad.retry}
            plane={cubeLoad.plane}
            setPlane={cubeLoad.setPlane}
            palette={palette}
            disabled={disabled}
          />
        </div>

        <Sidebar
          sequence={dateLoad.sequence}
          frame={dateLoad.frame}
          palette={palette}
          onPalette={choosePalette}
          grey={thumbnail}
          compositeUrl={compositeUrl}
        />
      </div>

      <TrackStack
        band={band}
        onBand={setBand}
        resolvedBand={dateLoad.sequence?.band ?? null}
        loading={dateLoad.state === 'loading'}
        sequence={dateLoad.sequence}
        index={dateLoad.index}
        onSelect={(next) => {
          dateLoad.setPlaying(false)
          dateLoad.setIndex(next)
        }}
        cube={cubeLoad.cube}
        plane={cubeLoad.plane}
        onPlane={cubeLoad.setPlane}
      />

      <Footer />
    </div>
  )
}
