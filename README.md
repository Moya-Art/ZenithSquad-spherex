# SPHEREx Sky-Time Viewer

NASA's SPHEREx mission maps the entire sky every six months in 102 near-infrared bands. This tool
shows one small patch of sky across its observation dates as a blinking sequence, so motion is easy
to spot, and lets you scrub the 102 wavelength planes to read a spectrum — with the archive's real
gaps in coverage left visible rather than smoothed away.

## Targets

| slug | name | RA (deg) | Dec (deg) |
|---|---|---|---|
| `r_dra` | R Draconis | 248.16775 | +66.75497 |
| `wise0855` | WISE 0855 | 133.795129 | -7.245147 |
| `barnard` | Barnard's Star | 269.45402 | +4.69336 |
| `eps_ind` | Epsilon Indi B | 330.84025 | -56.78597 |
| `rw_aur` | RW Aurigae | 76.956 | +30.401 |

## Run the Python half

Requires Python 3.14 (the pinned interpreter; `requirements.txt` was frozen from 3.14.7).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Check the stack imports:

```bash
python -c "import numpy, astropy, astroquery, reproject, photutils, PIL, hpgeom; from google.cloud import storage; import fastapi, uvicorn, pytest; print('python ok')"
```

## Run the API

```bash
source .venv/bin/activate
python -m uvicorn api.app.main:app --port 8000
```

`/frames?ra=&dec=&band=` builds that coordinate's sequence from IRSA on first request and caches it;
`/preview` serves one frame as WebP. The dev frontend proxies `/api` here, so running both halves
needs no configuration. A production frontend sets `VITE_API_URL`, and the API reads `CORS_ORIGINS`.

## Run the web half

```bash
cd web
npm install
npm run dev
```

Vite serves on <http://localhost:5173>. `npm run build` produces a production build in `web/dist`.

## References

Data products:

- SPHEREx Data Release 1 (DR1) Spectral Images — DOI [10.26131/IRSA678](https://doi.org/10.26131/IRSA678), SPHEREx Team, IPAC, 2026.
- SPHEREx Data Release 1 (DR1) Spectral All-Sky Cube — DOI [10.26131/IRSA679](https://doi.org/10.26131/IRSA679), SPHEREx Team, IPAC, 2026.

Documentation and services:

- SPHEREx at IRSA — <https://irsa.ipac.caltech.edu/Missions/spherex.html>
- IRSA SPHEREx tutorial notebooks — <https://caltech-ipac.github.io/irsa-tutorials/spherex/>

Data are made available by the Infrared Science Archive (IRSA) at IPAC, which is operated by the
California Institute of Technology under contract with the National Aeronautics and Space
Administration.

The objects shown are candidates for inspection, not discoveries.
