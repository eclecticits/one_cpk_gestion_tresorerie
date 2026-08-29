import { useEffect, useMemo, useRef, useState } from 'react'
import type { BudgetPosteSummary } from '../types/budget'
import { useTreeBranchReveal } from '../hooks/useTreeBranchReveal'
import { toNumber } from '../utils/amount'
import { compareBudgetCodes } from '../utils/budgetCode'
import styles from './BudgetPosteSelect.module.css'

/**
 * Recherche de poste budgétaire : champ texte + arborescence dépliable.
 *
 * Une liste déroulante native impose de connaître le code par coeur et noie les
 * feuilles dans les parents ; ici on filtre au fil de la frappe, sur le code
 * comme sur le libellé, et la recherche déplie d'office les branches qui
 * contiennent un résultat. Seules les feuilles sont sélectionnables — un poste
 * parent est un agrégat, on n'impute rien dessus — et chacune affiche son
 * disponible, l'information qui décide du choix.
 *
 * Le motif vient des lignes de réquisition ; il est isolé ici pour que les
 * écrans qui l'adoptent partagent le même comportement au lieu d'en recopier
 * une variante de plus.
 */

type Noeud = BudgetPosteSummary & { children: Noeud[] }

interface Props {
  postes: BudgetPosteSummary[]
  value: number | string | null | undefined
  onChange: (posteId: number | null) => void
  id?: string
  placeholder?: string
  required?: boolean
  disabled?: boolean
  /** Message affiché sous le champ quand aucun poste n'est disponible. */
  emptyHint?: string
  ariaLabel?: string
}

const formatDisponible = (valeur: unknown) =>
  new Intl.NumberFormat('fr-FR', { style: 'currency', currency: 'USD' }).format(
    toNumber(valeur as any) || 0
  )

function construireArbre(postes: BudgetPosteSummary[]): Noeud[] {
  const noeuds = new Map<number, Noeud>()
  const racines: Noeud[] = []

  postes.forEach((poste) => {
    noeuds.set(poste.id, { ...poste, children: [] })
  })
  postes.forEach((poste) => {
    const noeud = noeuds.get(poste.id)!
    const parent = poste.parent_id != null ? noeuds.get(poste.parent_id) : undefined
    if (parent) parent.children.push(noeud)
    else racines.push(noeud)
  })

  const trier = (liste: Noeud[]) => {
    liste.sort((a, b) => compareBudgetCodes(a.code, b.code))
    liste.forEach((n) => trier(n.children))
  }
  trier(racines)
  return racines
}

function filtrerArbre(arbre: Noeud[], requete: string): Noeud[] {
  const terme = requete.trim().toLowerCase()
  if (!terme) return arbre

  const correspond = (n: Noeud) =>
    String(n.code || '').toLowerCase().includes(terme) ||
    String(n.libelle || '').toLowerCase().includes(terme)

  const filtrer = (noeuds: Noeud[]): Noeud[] =>
    noeuds
      .map((n) => {
        const children = filtrer(n.children)
        // Un parent est conservé s'il correspond lui-même ou s'il mène à un
        // résultat : sinon la feuille trouvée apparaîtrait sans son contexte.
        if (correspond(n) || children.length > 0) return { ...n, children }
        return null
      })
      .filter((n): n is Noeud => n !== null)

  return filtrer(arbre)
}

interface NoeudProps {
  noeud: Noeud
  profondeur: number
  ouverts: Set<number>
  onBasculer: (id: number, ligne?: HTMLElement | null) => void
  onSelectionner: (poste: Noeud) => void
  toutDeplie: boolean
}

function LigneArbre({
  noeud,
  profondeur,
  ouverts,
  onBasculer,
  onSelectionner,
  toutDeplie,
}: NoeudProps) {
  const aDesEnfants = noeud.children.length > 0
  const estOuvert = toutDeplie || ouverts.has(noeud.id)
  return (
    <>
      <div
        className={`${styles.item} ${aDesEnfants ? styles.itemParent : ''}`}
        style={{ paddingLeft: `${10 + profondeur * 16}px` }}
        data-tree-node={aDesEnfants ? noeud.id : undefined}
        role="option"
        aria-selected={false}
        onClick={(event) => {
          if (aDesEnfants) onBasculer(noeud.id, event.currentTarget)
          else onSelectionner(noeud)
        }}
      >
        {aDesEnfants && (
          <span className={`${styles.chevron} ${estOuvert ? styles.chevronOuvert : ''}`} />
        )}
        <span className={styles.itemText}>
          <strong>{noeud.code}</strong> - {noeud.libelle}
        </span>
        {aDesEnfants ? (
          <span className={styles.badgeParent}>Parent</span>
        ) : (
          <span className={styles.itemMeta}>{formatDisponible(noeud.montant_disponible)}</span>
        )}
      </div>
      {aDesEnfants && estOuvert && (
        <div className={styles.branche} data-tree-branch={noeud.id}>
          {noeud.children.map((enfant) => (
            <LigneArbre
              key={enfant.id}
              noeud={enfant}
              profondeur={profondeur + 1}
              ouverts={ouverts}
              onBasculer={onBasculer}
              onSelectionner={onSelectionner}
              toutDeplie={toutDeplie}
            />
          ))}
        </div>
      )}
    </>
  )
}

export default function BudgetPosteSelect({
  postes,
  value,
  onChange,
  id,
  placeholder = 'Rechercher par code ou libellé',
  required,
  disabled,
  emptyHint,
  ariaLabel,
}: Props) {
  const [requete, setRequete] = useState('')
  const [ouvert, setOuvert] = useState(false)
  const [ouverts, setOuverts] = useState<Set<number>>(new Set())
  const fermetureRef = useRef<number | undefined>(undefined)
  const revelerBranche = useTreeBranchReveal()

  const arbre = useMemo(() => construireArbre(postes), [postes])
  const arbreFiltre = useMemo(() => filtrerArbre(arbre, requete), [arbre, requete])
  const toutDeplie = requete.trim().length > 0

  const posteSelectionne = useMemo(
    () => (value == null || value === '' ? null : postes.find((p) => String(p.id) === String(value)) ?? null),
    [postes, value]
  )

  // Le champ affiche le poste retenu, y compris quand la sélection est effacée
  // depuis l'extérieur (changement de service, réinitialisation du formulaire).
  useEffect(() => {
    if (posteSelectionne) setRequete(`${posteSelectionne.code} - ${posteSelectionne.libelle}`)
    else if (value == null || value === '') setRequete('')
  }, [posteSelectionne, value])

  useEffect(() => () => window.clearTimeout(fermetureRef.current), [])

  const basculer = (idNoeud: number, ligne?: HTMLElement | null) => {
    const etaitOuvert = ouverts.has(idNoeud)
    setOuverts((prev) => {
      const suivant = new Set(prev)
      if (suivant.has(idNoeud)) suivant.delete(idNoeud)
      else suivant.add(idNoeud)
      return suivant
    })
    // Recentrage seulement à l'ouverture : replier n'a rien à montrer.
    if (!etaitOuvert) revelerBranche(ligne ?? null)
  }

  const selectionner = (poste: Noeud) => {
    onChange(poste.id)
    setRequete(`${poste.code} - ${poste.libelle}`)
    setOuvert(false)
  }

  return (
    <div className={styles.wrapper}>
      <input
        id={id}
        type="text"
        role="combobox"
        aria-expanded={ouvert}
        aria-label={ariaLabel}
        autoComplete="off"
        className={styles.input}
        value={requete}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(e) => {
          setRequete(e.target.value)
          // Toute frappe invalide la sélection : le champ ne doit jamais
          // afficher un libellé alors qu'un autre poste reste enregistré.
          if (value != null && value !== '') onChange(null)
          setOuvert(true)
        }}
        onFocus={() => setOuvert(true)}
        onBlur={() => {
          // Laisse le clic sur un élément de la liste se produire avant la
          // fermeture.
          fermetureRef.current = window.setTimeout(() => setOuvert(false), 120)
        }}
        onKeyDown={(e) => {
          if (e.key === 'Escape' && ouvert) {
            e.stopPropagation()
            setOuvert(false)
          }
        }}
      />
      {/* Porte la contrainte HTML sans exposer un second champ saisissable :
          le texte visible est une recherche, la valeur soumise est l'id. */}
      <input
        type="text"
        tabIndex={-1}
        aria-hidden="true"
        className={styles.champValeur}
        value={value == null ? '' : String(value)}
        required={required}
        onChange={() => {}}
      />
      {ouvert && (
        <div className={styles.dropdown} data-tree-scroll role="listbox" onMouseDown={(e) => e.preventDefault()}>
          {arbreFiltre.length > 0 ? (
            arbreFiltre.map((noeud) => (
              <LigneArbre
                key={noeud.id}
                noeud={noeud}
                profondeur={0}
                ouverts={ouverts}
                onBasculer={basculer}
                onSelectionner={selectionner}
                toutDeplie={toutDeplie}
              />
            ))
          ) : (
            <div className={styles.itemVide}>Aucun poste trouvé.</div>
          )}
        </div>
      )}
      {postes.length === 0 && emptyHint && <small className={styles.hint}>{emptyHint}</small>}
    </div>
  )
}
