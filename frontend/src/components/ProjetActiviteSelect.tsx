import { useEffect, useState } from 'react'
import { listProjetsActivites, type ProjetActivite } from '../api/projetsActivites'

type Props = {
  id: string
  /** Identifiant du projet, ou chaîne vide pour « aucun ». */
  value: string
  onChange: (value: string) => void
  className?: string
  hintClassName?: string
}

/**
 * Choix facultatif du projet ou de l'activité qu'une dépense finance.
 * Rien ne s'affiche tant que l'organisation n'a configuré aucun projet actif :
 * ceux qui ne s'en servent pas ne voient pas de champ en plus.
 */
export default function ProjetActiviteSelect({ id, value, onChange, className, hintClassName }: Props) {
  const [projets, setProjets] = useState<ProjetActivite[]>([])

  useEffect(() => {
    let annule = false
    listProjetsActivites(true)
      .then((items) => { if (!annule) setProjets(items) })
      .catch(() => { if (!annule) setProjets([]) })
    return () => { annule = true }
  }, [])

  if (projets.length === 0 && !value) return null

  return (
    <div className={className}>
      <label htmlFor={id}>Projet / activité (facultatif)</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Aucun</option>
        {projets.map((p) => (
          <option key={p.id} value={String(p.id)}>
            {p.code} — {p.libelle}
          </option>
        ))}
      </select>
      <small className={hintClassName}>Permet de retrouver cette dépense dans le rapport du projet.</small>
    </div>
  )
}
