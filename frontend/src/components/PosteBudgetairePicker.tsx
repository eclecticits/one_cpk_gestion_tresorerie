import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { ChevronRight, Search, X } from 'lucide-react'
import type { BudgetPosteSummary } from '../types/budget'
import { compareBudgetCodes } from '../utils/budgetCode'
import { toNumber } from '../utils/amount'
import styles from './PosteBudgetairePicker.module.css'

interface Noeud extends BudgetPosteSummary {
  enfants: Noeud[]
}

interface Ligne {
  noeud: Noeud
  profondeur: number
  parent: boolean
  ouvert: boolean
}

interface Props {
  id: string
  postes: BudgetPosteSummary[]
  value: number | null
  onChange: (posteId: number | null) => void
  disabled?: boolean
  loading?: boolean
  invalid?: boolean
  describedBy?: string
}

const usd = (valeur: unknown) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(toNumber(valeur as any))

/** Comparaison sans casse ni accents : « frais » trouve « Frais d'hébergement ». */
const plier = (texte: string) =>
  texte.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()

function surligner(texte: string, requete: string): ReactNode {
  const q = plier(requete.trim())
  if (!q) return texte
  const debut = plier(texte).indexOf(q)
  if (debut < 0) return texte
  return (
    <>
      {texte.slice(0, debut)}
      <mark className={styles.surligne}>{texte.slice(debut, debut + q.length)}</mark>
      {texte.slice(debut + q.length)}
    </>
  )
}

/**
 * Choix d'un poste budgétaire, sur le modèle de la réquisition : recherche par
 * code ou libellé, arborescence des postes (un parent se déplie, seule une
 * feuille s'impute), disponible affiché en regard de chaque poste.
 *
 * Au clavier : ↓/↑ parcourent la liste, → / ← déplient ou replient un parent,
 * Entrée choisit, Échap referme.
 */
export default function PosteBudgetairePicker({
  id,
  postes,
  value,
  onChange,
  disabled = false,
  loading = false,
  invalid = false,
  describedBy,
}: Props) {
  const listeId = useId()
  const inputRef = useRef<HTMLInputElement>(null)
  const listeRef = useRef<HTMLDivElement>(null)
  const [ouvert, setOuvert] = useState(false)
  const [requete, setRequete] = useState('')
  const [deplies, setDeplies] = useState<Set<number>>(new Set())
  const [actif, setActif] = useState(0)
  const [position, setPosition] = useState<{ top: number; left: number; width: number; hauteur: number; versLeHaut: boolean } | null>(null)

  /**
   * La liste vit dans un portail, en position fixe, calée sur le champ. Dans
   * le formulaire, la section des lignes est en `overflow: hidden` et chaque
   * ligne empile son propre contexte : rendue sur place, la liste était coupée
   * ou passait sous la ligne suivante. Elle s'ouvre vers le haut quand la place
   * manque en bas, et suit le champ au défilement.
   */
  const placer = useCallback(() => {
    const champ = inputRef.current?.getBoundingClientRect()
    if (!champ) return
    const marge = 8
    const dessous = window.innerHeight - champ.bottom - marge
    const dessus = champ.top - marge
    const versLeHaut = dessous < 220 && dessus > dessous
    const hauteur = Math.max(160, Math.min(320, versLeHaut ? dessus : dessous))
    const largeur = Math.min(Math.max(champ.width, 420), window.innerWidth - 2 * marge)
    const left = Math.min(Math.max(marge, champ.left), window.innerWidth - largeur - marge)
    setPosition({
      top: versLeHaut ? champ.top - 4 : champ.bottom + 4,
      left,
      width: largeur,
      hauteur,
      versLeHaut,
    })
  }, [])

  useLayoutEffect(() => {
    if (ouvert) placer()
  }, [ouvert, placer])

  useEffect(() => {
    if (!ouvert) return
    // `capture` : le défilement d'un conteneur intérieur (la page, une modale)
    // ne remonte pas jusqu'à window sans elle.
    window.addEventListener('scroll', placer, true)
    window.addEventListener('resize', placer)
    return () => {
      window.removeEventListener('scroll', placer, true)
      window.removeEventListener('resize', placer)
    }
  }, [ouvert, placer])

  const selection = useMemo(() => postes.find((p) => p.id === value) ?? null, [postes, value])

  const racines = useMemo(() => {
    const noeuds = new Map<number, Noeud>()
    postes.forEach((p) => noeuds.set(p.id, { ...p, enfants: [] }))
    const resultat: Noeud[] = []
    noeuds.forEach((noeud) => {
      const parent = noeud.parent_id ? noeuds.get(noeud.parent_id) : undefined
      if (parent) parent.enfants.push(noeud)
      else resultat.push(noeud)
    })
    const trier = (liste: Noeud[]) => {
      liste.sort((a, b) => compareBudgetCodes(a.code, b.code))
      liste.forEach((n) => trier(n.enfants))
    }
    trier(resultat)
    return resultat
  }, [postes])

  // Une recherche déplie tout ce qu'elle trouve ; sans recherche, l'arbre
  // s'ouvre sur la branche du poste déjà choisi.
  const lignes = useMemo<Ligne[]>(() => {
    const q = plier(requete.trim())
    const correspond = (n: Noeud) => !q || plier(`${n.code} ${n.libelle}`).includes(q)
    const garder = (n: Noeud): boolean => correspond(n) || n.enfants.some(garder)
    const sortie: Ligne[] = []
    const parcourir = (liste: Noeud[], profondeur: number) => {
      liste.forEach((n) => {
        if (!garder(n)) return
        const parent = n.enfants.length > 0
        const estOuvert = parent && (Boolean(q) || deplies.has(n.id))
        sortie.push({ noeud: n, profondeur, parent, ouvert: estOuvert })
        if (estOuvert) parcourir(n.enfants, profondeur + 1)
      })
    }
    parcourir(racines, 0)
    return sortie
  }, [racines, requete, deplies])

  const ouvrir = () => {
    if (disabled) return
    // Déplie la branche du poste choisi pour le montrer en contexte.
    if (selection) {
      const parents = new Set(deplies)
      let courant = selection.parent_id ? postes.find((p) => p.id === selection.parent_id) : undefined
      while (courant) {
        parents.add(courant.id)
        const parentId: number | null | undefined = courant.parent_id
        courant = parentId ? postes.find((p) => p.id === parentId) : undefined
      }
      setDeplies(parents)
    }
    setRequete('')
    setActif(0)
    setOuvert(true)
  }

  const fermer = () => {
    setOuvert(false)
    setRequete('')
  }

  const basculer = (posteId: number) =>
    setDeplies((prev) => {
      const next = new Set(prev)
      if (next.has(posteId)) next.delete(posteId)
      else next.add(posteId)
      return next
    })

  const choisir = (ligne: Ligne) => {
    if (ligne.parent) {
      basculer(ligne.noeud.id)
      return
    }
    onChange(ligne.noeud.id)
    fermer()
    inputRef.current?.blur()
  }

  const deplacer = (pas: number) => {
    if (!lignes.length) return
    const suivant = Math.max(0, Math.min(lignes.length - 1, actif + pas))
    setActif(suivant)
    listeRef.current
      ?.querySelector<HTMLElement>(`[data-index="${suivant}"]`)
      ?.scrollIntoView({ block: 'nearest' })
  }

  const auClavier = (event: KeyboardEvent<HTMLInputElement>) => {
    if (!ouvert && (event.key === 'ArrowDown' || event.key === 'Enter')) {
      event.preventDefault()
      ouvrir()
      return
    }
    if (!ouvert) return
    const courante = lignes[actif]
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault()
        deplacer(1)
        break
      case 'ArrowUp':
        event.preventDefault()
        deplacer(-1)
        break
      case 'ArrowRight':
        if (courante?.parent && !courante.ouvert) {
          event.preventDefault()
          basculer(courante.noeud.id)
        }
        break
      case 'ArrowLeft':
        if (courante?.parent && courante.ouvert && !requete) {
          event.preventDefault()
          basculer(courante.noeud.id)
        }
        break
      case 'Enter':
        event.preventDefault()
        if (courante) choisir(courante)
        break
      case 'Escape':
        event.preventDefault()
        fermer()
        break
    }
  }

  const affichage = ouvert ? requete : selection ? `${selection.code} — ${selection.libelle}` : ''

  return (
    <div className={`${styles.picker} ${invalid ? styles.invalide : ''}`}>
      <div className={styles.champ}>
        <Search size={15} aria-hidden="true" className={styles.loupe} />
        <input
          ref={inputRef}
          id={id}
          type="text"
          role="combobox"
          aria-expanded={ouvert}
          aria-controls={listeId}
          aria-autocomplete="list"
          aria-activedescendant={ouvert && lignes[actif] ? `${listeId}-${lignes[actif].noeud.id}` : undefined}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
          aria-required="true"
          autoComplete="off"
          value={affichage}
          placeholder={loading ? 'Chargement des postes…' : 'Rechercher par code ou libellé'}
          disabled={disabled}
          title={selection ? `${selection.code} — ${selection.libelle}` : undefined}
          onFocus={ouvrir}
          onClick={() => { if (!ouvert) ouvrir() }}
          onBlur={() => window.setTimeout(fermer, 120)}
          onChange={(e) => {
            setRequete(e.target.value)
            setActif(0)
            if (!ouvert) setOuvert(true)
          }}
          onKeyDown={auClavier}
        />
        {selection && !disabled && (
          <button
            type="button"
            className={styles.effacer}
            aria-label="Retirer le poste choisi"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => { onChange(null); inputRef.current?.focus() }}
          >
            <X size={14} aria-hidden="true" />
          </button>
        )}
      </div>

      {ouvert && position && createPortal(
        <div
          ref={listeRef}
          id={listeId}
          role="listbox"
          className={styles.liste}
          style={{
            top: position.versLeHaut ? undefined : position.top,
            bottom: position.versLeHaut ? window.innerHeight - position.top : undefined,
            left: position.left,
            width: position.width,
            maxHeight: position.hauteur,
          }}
          onMouseDown={(e) => e.preventDefault()}
        >
          {lignes.length === 0 ? (
            <div className={styles.vide}>
              {postes.length === 0 ? 'Aucun poste de dépense disponible.' : 'Aucun poste ne correspond.'}
            </div>
          ) : (
            lignes.map((ligne, index) => {
              const { noeud } = ligne
              const disponible = toNumber(noeud.montant_disponible)
              return (
                <div
                  key={noeud.id}
                  id={`${listeId}-${noeud.id}`}
                  data-index={index}
                  role="option"
                  aria-selected={noeud.id === value}
                  aria-expanded={ligne.parent ? ligne.ouvert : undefined}
                  className={[
                    styles.option,
                    ligne.parent ? styles.optionParent : '',
                    index === actif ? styles.optionActive : '',
                    noeud.id === value ? styles.optionChoisie : '',
                  ].join(' ')}
                  style={{ paddingLeft: 10 + ligne.profondeur * 16 }}
                  onMouseEnter={() => setActif(index)}
                  onClick={() => choisir(ligne)}
                >
                  {ligne.parent ? (
                    <ChevronRight
                      size={14}
                      aria-hidden="true"
                      className={`${styles.chevron} ${ligne.ouvert ? styles.chevronOuvert : ''}`}
                    />
                  ) : (
                    <span className={styles.puce} aria-hidden="true" />
                  )}
                  <span className={styles.intitule}>
                    <strong>{surligner(noeud.code, requete)}</strong> — {surligner(noeud.libelle, requete)}
                  </span>
                  {ligne.parent ? (
                    <span className={styles.badgeParent}>Parent</span>
                  ) : (
                    <span className={`${styles.disponible} ${disponible <= 0 ? styles.disponibleEpuise : ''}`}>
                      {usd(disponible)}
                    </span>
                  )}
                </div>
              )
            })
          )}
        </div>,
        document.body,
      )}
    </div>
  )
}

interface ResumeProps {
  poste: BudgetPosteSummary
  /** Ce que la pièce impute sur ce poste, toutes lignes confondues, en USD.
   *  `null` : pas de taux pour convertir — le contrôle se fera à la transmission. */
  montantUsd: number | null
  /** Seuil d'alerte de consommation, en %. */
  seuil?: number
  /** Le paramétrage bloque-t-il un dépassement ? */
  bloque?: boolean
}

/**
 * Situation du poste choisi, comme sous un groupe de réquisition : prévu,
 * engagé, disponible, et ce qu'il resterait après cette dépense.
 */
export function PosteBudgetaireResume({ poste, montantUsd, seuil = 80, bloque = false }: ResumeProps) {
  const prevu = toNumber(poste.montant_prevu)
  const engage = toNumber(poste.montant_engage)
  const disponible = toNumber(poste.montant_disponible)
  const montant = montantUsd ?? 0
  const soldeApres = disponible - montant
  const depasse = montantUsd !== null && montant > disponible + 0.005
  const consomme = prevu > 0 ? ((engage + montant) / prevu) * 100 : 0
  const enAlerte = !depasse && consomme >= seuil

  return (
    <div className={`${styles.resume} ${depasse ? styles.resumeDepasse : enAlerte ? styles.resumeAlerte : ''}`}>
      <div className={styles.chiffres}>
        <span>Prévu <strong>{usd(prevu)}</strong></span>
        <span>Engagé <strong>{usd(engage)}</strong></span>
        <span>Disponible <strong>{usd(disponible)}</strong></span>
        <span>
          Cette sortie <strong>{montantUsd === null ? '—' : usd(montant)}</strong>
        </span>
        <span className={soldeApres < 0 ? styles.negatif : styles.positif}>
          Solde après <strong>{montantUsd === null ? '—' : usd(soldeApres)}</strong>
        </span>
      </div>
      {prevu > 0 && (
        <div
          className={styles.jauge}
          role="meter"
          aria-label="Consommation du poste après cette sortie"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(Math.min(consomme, 100))}
        >
          <span style={{ width: `${Math.min(consomme, 100)}%` }} />
        </div>
      )}
      {depasse && (
        <p className={styles.message}>
          {bloque ? 'Blocage' : 'Dépassement'} : cette sortie ({usd(montant)}) dépasse le disponible du poste ({usd(disponible)}).
        </p>
      )}
      {enAlerte && (
        <p className={styles.message}>Seuil de {seuil} % atteint : le poste sera consommé à {Math.round(consomme)} %.</p>
      )}
      {montantUsd === null && (
        <p className={styles.note}>Montant en CDF : le disponible sera contrôlé au taux actif lors de la transmission.</p>
      )}
    </div>
  )
}
