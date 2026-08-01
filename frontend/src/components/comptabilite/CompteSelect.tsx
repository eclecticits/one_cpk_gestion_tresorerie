import { useMemo, useState } from 'react'
import type { ComptaCompte } from '../../types/comptabilite'
import styles from './ComptaMappingsPanel.module.css'

interface Props {
  id: string
  comptes: ComptaCompte[]
  value: number | null
  disabled?: boolean
  onChange: (compteId: number) => void
}

/**
 * Sélecteur de compte comptable avec filtre au clavier.
 *
 * Un plan de démarrage compte déjà ~60 lignes et un plan réel plusieurs
 * centaines : un `<select>` nu devient inutilisable. Le champ de recherche
 * filtre sur le numéro ET le libellé, un comptable connaissant souvent l'un
 * ou l'autre. Les comptes collectifs sont exclus — le backend les refuse
 * (ils exigent un auxiliaire par écriture), autant ne pas les proposer.
 */
export default function CompteSelect({ id, comptes, value, disabled, onChange }: Props) {
  const [recherche, setRecherche] = useState('')

  const selectionnables = useMemo(
    () => comptes.filter(c => c.actif && !c.is_collectif),
    [comptes]
  )

  const filtres = useMemo(() => {
    const terme = recherche.trim().toLowerCase()
    if (!terme) return selectionnables
    const resultats = selectionnables.filter(
      c => c.numero.toLowerCase().includes(terme) || c.libelle.toLowerCase().includes(terme)
    )
    // Le compte actuellement mappé reste listé même s'il ne correspond pas au
    // filtre, sinon le `<select>` afficherait une valeur absente de ses options.
    const selectionne = selectionnables.find(c => c.id === value)
    if (selectionne && !resultats.some(c => c.id === selectionne.id)) {
      return [selectionne, ...resultats]
    }
    return resultats
  }, [recherche, selectionnables, value])

  return (
    <div className={styles.compteSelect}>
      <input
        type="text"
        className={styles.compteSearch}
        placeholder="Filtrer…"
        value={recherche}
        onChange={e => setRecherche(e.target.value)}
        disabled={disabled}
        aria-label="Filtrer les comptes"
      />
      <select
        id={id}
        className={styles.compteDropdown}
        value={value ?? ''}
        disabled={disabled}
        onChange={e => {
          if (e.target.value) onChange(Number(e.target.value))
        }}
      >
        <option value="">— Non mappé —</option>
        {filtres.map(compte => (
          <option key={compte.id} value={compte.id}>
            {compte.numero} — {compte.libelle}
          </option>
        ))}
      </select>
    </div>
  )
}
