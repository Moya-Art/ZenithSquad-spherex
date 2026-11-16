import type { ReactNode } from 'react'

/**
 * The page's last line.
 *
 * The credit is the only place the data provenance lives now that the cube note left the screen, and
 * the legal line is deliberately blunt: a candidate for inspection is not a discovery.
 */

function Item({ children }: { children: ReactNode }) {
  return <span className="footer-item">{children}</span>
}

export function Footer() {
  return (
    <footer className="footer">
      <Item>NASA Space Apps Challenge</Item>
      <Item>Planet X and SPHEREx</Item>
      <Item>
        Data: NASA/IPAC IRSA · SPHEREx DR1{' '}
        <span className="mono">10.26131/IRSA678</span> / <span className="mono">10.26131/IRSA679</span>
      </Item>
      <Item>
        Not affiliated with or endorsed by NASA; what is shown are candidates for inspection, not
        discoveries.
      </Item>
      <Item>Arturo Moya / Matias Molina — ZenithSquad</Item>
    </footer>
  )
}
