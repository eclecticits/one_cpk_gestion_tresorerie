import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { MoreHorizontal } from 'lucide-react'
import styles from './RowActionsMenu.module.css'

export type ActionLigne = {
  cle: string
  libelle: string
  icone: ReactNode
  onSelect: () => void
  /** Grise l'entree sans la retirer du menu ni du parcours clavier. */
  disabled?: boolean
  /** Ligne secondaire : etape du circuit, ou motif d'indisponibilite. */
  description?: string
  /** Action destructrice : signalee en rouge et separee des autres. */
  destructive?: boolean
}

/**
 * Menu « … » des actions d'une ligne de tableau.
 *
 * Meme patron que MenuActionsLigne de pages/Requisitions.tsx : le panneau est
 * rendu dans un portail sur <body> et positionne en `position: fixed` a partir
 * du rectangle du declencheur. Pose en `position: absolute` dans la ligne, il
 * serait rogne par l'`overflow` et le `max-height: 520px` de .tableContainer ;
 * le portail neutralise en plus les `transform` du chassis, qui piegeraient un
 * `fixed` en creant un bloc conteneur.
 *
 * Deux ajouts par rapport a la version de Requisitions, imposes par cet ecran :
 * des entrees desactivables (une action en cours, ou le visa interdit a celui
 * qui a deja valide) et une ligne de description, qui recueille les reperes de
 * circuit auparavant affiches en clair dans la cellule.
 */
export default function RowActionsMenu({ items, libelle }: { items: ActionLigne[]; libelle: string }) {
  const [ouvert, setOuvert] = useState(false)
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null)
  const [indexActif, setIndexActif] = useState(0)
  const declencheurRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const itemsRef = useRef<(HTMLButtonElement | null)[]>([])

  const fermer = useCallback((rendreLeFocus: boolean) => {
    setOuvert(false)
    if (rendreLeFocus) declencheurRef.current?.focus()
  }, [])

  const ouvrir = () => {
    const rect = declencheurRef.current?.getBoundingClientRect()
    if (!rect) return
    const largeur = 268
    const separateurs = items.some((item) => item.destructive) ? 9 : 0
    // Une entree a description occupe deux lignes : la bascule doit le savoir,
    // sinon un menu de six entrees commentees sortirait de l'ecran.
    const hauteur = items.reduce((total, item) => total + (item.description ? 50 : 34), 8) + separateurs
    const placeEnDessous = window.innerHeight - rect.bottom > hauteur + 8
    setPosition({
      top: placeEnDessous ? rect.bottom + 4 : Math.max(8, rect.top - hauteur - 4),
      left: Math.max(8, Math.min(rect.right - largeur, window.innerWidth - largeur - 8)),
    })
    setIndexActif(0)
    setOuvert(true)
  }

  // Le panneau est en `fixed` : il ne suit pas le defilement. On le referme
  // plutot que de le laisser flotter loin de sa ligne. `capture` intercepte
  // aussi le defilement interne de .tableContainer.
  useEffect(() => {
    if (!ouvert) return
    const surClicExterieur = (event: MouseEvent) => {
      const cible = event.target as Node
      if (menuRef.current?.contains(cible) || declencheurRef.current?.contains(cible)) return
      fermer(false)
    }
    const surDefilement = () => fermer(false)
    document.addEventListener('mousedown', surClicExterieur)
    window.addEventListener('scroll', surDefilement, true)
    window.addEventListener('resize', surDefilement)
    return () => {
      document.removeEventListener('mousedown', surClicExterieur)
      window.removeEventListener('scroll', surDefilement, true)
      window.removeEventListener('resize', surDefilement)
    }
  }, [ouvert, fermer])

  // Focus reellement deplace sur l'entree active : c'est ce qu'attend un
  // lecteur d'ecran d'un role="menu". Les entrees indisponibles portent
  // aria-disabled et non l'attribut disabled, pour rester atteignables au
  // clavier — c'est la seule facon de leur faire lire leur motif.
  useEffect(() => {
    if (ouvert) itemsRef.current[indexActif]?.focus()
  }, [ouvert, indexActif])

  const surToucheMenu = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      fermer(true)
    } else if (event.key === 'ArrowDown') {
      event.preventDefault()
      setIndexActif((i) => (i + 1) % items.length)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setIndexActif((i) => (i - 1 + items.length) % items.length)
    } else if (event.key === 'Home') {
      event.preventDefault()
      setIndexActif(0)
    } else if (event.key === 'End') {
      event.preventDefault()
      setIndexActif(items.length - 1)
    } else if (event.key === 'Tab') {
      // On rend la main au declencheur plutot que de laisser le focus filer
      // vers un panneau sur le point d'etre demonte.
      event.preventDefault()
      fermer(true)
    }
  }

  const surToucheDeclencheur = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp' || event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      if (!ouvert) ouvrir()
    }
  }

  if (items.length === 0) return null

  return (
    <>
      <button
        type="button"
        ref={declencheurRef}
        className={`${styles.actionIconBtn} ${styles.actionMenuBtn}`}
        onClick={() => (ouvert ? fermer(true) : ouvrir())}
        onKeyDown={surToucheDeclencheur}
        aria-haspopup="menu"
        aria-expanded={ouvert}
        title="Autres actions"
        aria-label={libelle}
      >
        <MoreHorizontal size={16} aria-hidden="true" />
      </button>
      {ouvert && position && createPortal(
        <div
          ref={menuRef}
          className={styles.rowMenu}
          role="menu"
          aria-label={libelle}
          style={{ top: position.top, left: position.left }}
          onKeyDown={surToucheMenu}
        >
          {items.map((item, index) => (
            <Fragment key={item.cle}>
              {item.destructive && index > 0 && (
                <div className={styles.rowMenuSeparator} role="separator" />
              )}
              <button
                type="button"
                role="menuitem"
                tabIndex={index === indexActif ? 0 : -1}
                aria-disabled={item.disabled || undefined}
                ref={(element) => { itemsRef.current[index] = element }}
                className={`${styles.rowMenuItem} ${item.destructive ? styles.rowMenuDanger : ''} ${item.disabled ? styles.rowMenuItemDisabled : ''}`}
                title={item.description}
                onClick={() => {
                  if (item.disabled) return
                  fermer(true)
                  item.onSelect()
                }}
                onMouseEnter={() => setIndexActif(index)}
              >
                <span className={styles.rowMenuIcone} aria-hidden="true">{item.icone}</span>
                <span className={styles.rowMenuTexte}>
                  {item.libelle}
                  {item.description && <small className={styles.rowMenuHint}>{item.description}</small>}
                </span>
              </button>
            </Fragment>
          ))}
        </div>,
        document.body
      )}
    </>
  )
}
