import { useEffect, useRef, useState } from 'react'
import { Calendar } from 'lucide-react'
import styles from './DateSaisie.module.css'

type Props = {
  id?: string
  /** Date au format ISO (aaaa-mm-jj), ou chaîne vide. */
  value: string
  onChange: (value: string) => void
  min?: string
  max?: string
  'aria-label'?: string
}

const versAffichage = (iso: string): string => {
  const [a, m, j] = iso.split('-')
  return a && m && j ? `${j}/${m}/${a}` : ''
}

// Les chiffres tapés, barres posées au fil de la saisie : 14102026 → 14/10/2026.
const masquer = (saisie: string): string => {
  const chiffres = saisie.replace(/\D/g, '').slice(0, 8)
  if (chiffres.length <= 2) return chiffres
  if (chiffres.length <= 4) return `${chiffres.slice(0, 2)}/${chiffres.slice(2)}`
  return `${chiffres.slice(0, 2)}/${chiffres.slice(2, 4)}/${chiffres.slice(4)}`
}

// jj/mm/aaaa → aaaa-mm-jj, ou null si la date n'existe pas (31/02, 00/10…).
const versIso = (texte: string): string | null => {
  const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(texte)
  if (!m) return null
  const [, j, mo, a] = m
  const d = new Date(Number(a), Number(mo) - 1, Number(j))
  if (d.getFullYear() !== Number(a) || d.getMonth() !== Number(mo) - 1 || d.getDate() !== Number(j)) return null
  return `${a}-${mo}-${j}`
}

/**
 * Champ date qui se tape au clavier (jj/mm/aaaa) ou se choisit au calendrier.
 * La valeur n'est transmise qu'une fois la date complète et valide : une
 * saisie en cours ne relance pas la recherche à chaque chiffre.
 */
export default function DateSaisie({ id, value, onChange, min, max, 'aria-label': ariaLabel }: Props) {
  const [texte, setTexte] = useState(() => versAffichage(value))
  const natifRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setTexte(versAffichage(value))
  }, [value])

  const complet = texte.length === 10
  const invalide = complet && versIso(texte) === null

  const saisir = (brut: string) => {
    const masque = masquer(brut)
    setTexte(masque)
    const iso = versIso(masque)
    if (iso && iso !== value) onChange(iso)
  }

  // Saisie abandonnée en route : on revient à la dernière date retenue.
  const quitter = () => {
    if (!versIso(texte)) setTexte(versAffichage(value))
  }

  const ouvrirCalendrier = () => {
    const natif = natifRef.current
    if (!natif) return
    try {
      natif.showPicker()
    } catch {
      natif.focus()
      natif.click()
    }
  }

  return (
    <span className={styles.root}>
      <input
        id={id}
        type="text"
        inputMode="numeric"
        autoComplete="off"
        placeholder="jj/mm/aaaa"
        maxLength={10}
        className={styles.input}
        aria-label={ariaLabel}
        aria-invalid={invalide || undefined}
        value={texte}
        onChange={(e) => saisir(e.target.value)}
        onBlur={quitter}
      />
      <button
        type="button"
        className={styles.bouton}
        onClick={ouvrirCalendrier}
        aria-label={ariaLabel ? `${ariaLabel} : ouvrir le calendrier` : 'Ouvrir le calendrier'}
      >
        <Calendar size={14} aria-hidden="true" />
      </button>
      <input
        ref={natifRef}
        type="date"
        tabIndex={-1}
        aria-hidden="true"
        className={styles.natif}
        value={value}
        min={min}
        max={max}
        onChange={(e) => e.target.value && onChange(e.target.value)}
      />
    </span>
  )
}
