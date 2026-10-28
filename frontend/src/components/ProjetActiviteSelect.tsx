import { useEffect, useState } from 'react'
import { listProjetsActivites, type ProjetActivite } from '../api/projetsActivites'

type Props = {
  id: string
  /** Identifiant du projet, ou chaîne vide pour « aucun ». */
  value: string
  onChange: (value: string) => void
  className?: string
  hintClassName?: string
  label?: string
  hint?: string
}

/**
 * Choix facultatif du projet ou de l'activité qu'une dépense finance.
 * Rien ne s'affiche tant que l'organisation n'a configuré aucun projet actif :
 * ceux qui ne s'en servent pas ne voient pas de champ en plus.
 */
export default function ProjetActiviteSelect({ id, value, onChange, className, hintClassName, label, hint }: Props) {
  const [projets, setProjets] = useState<ProjetActivite[]>([])

  useEffect(() => {
    let annule = false
    // Charger aussi les éléments désactivés : une opération ancienne peut
    // encore y être rattachée. Ils ne sont jamais proposés pour un nouveau
    // choix, mais la valeur courante doit rester visible et compréhensible.
    listProjetsActivites()
      .then((items) => { if (!annule) setProjets(items) })
      .catch(() => { if (!annule) setProjets([]) })
    return () => { annule = true }
  }, [])

  const actifs = projets.filter((projet) => projet.is_active)
  const courant = value ? projets.find((projet) => String(projet.id) === value) : undefined

  if (actifs.length === 0 && !value) return null

  return (
    <div className={className}>
      <label htmlFor={id}>{label || 'Projet / activité (facultatif)'}</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Aucun</option>
        {value && !courant && (
          <option value={value}>Projet #{value} — référence indisponible</option>
        )}
        {courant && !courant.is_active && (
          <option value={String(courant.id)}>
            {courant.code} — {courant.libelle} (désactivé, valeur conservée)
          </option>
        )}
        {actifs.map((p) => (
          <option key={p.id} value={String(p.id)}>
            {p.code} — {p.libelle}
          </option>
        ))}
      </select>
      <small className={hintClassName}>
        {value && !courant
          ? 'La référence enregistrée ne peut pas être relue. Elle reste conservée tant que vous ne la changez pas.'
          : courant && !courant.is_active
          ? 'Ce projet a été désactivé depuis la programmation. Il reste conservé tant que vous ne le changez pas.'
          : hint || 'Permet de retrouver cette dépense dans le rapport du projet.'}
      </small>
    </div>
  )
}
