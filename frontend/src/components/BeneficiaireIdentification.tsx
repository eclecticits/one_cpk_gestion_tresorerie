import { Check } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useDebouncedValue } from '../hooks/useDebouncedValue'
import {
  rechercherBeneficiaires,
  TYPE_BENEFICIAIRE_LABELS,
  type BeneficiaireSuggestion,
  type TypeBeneficiaire,
} from '../api/justificatifs'
import styles from './Justificatif.module.css'

/** Ce que l'on retient du bénéficiaire, en plus de son nom. */
export interface BeneficiaireSaisie {
  type: TypeBeneficiaire | null
  refId: string | null
  detail: string | null
  /** Nom de la fiche choisie : retaper un autre nom détache la fiche. */
  nomFiche: string | null
  email: string
  telephone: string
}

export const BENEFICIAIRE_VIDE: BeneficiaireSaisie = {
  type: null,
  refId: null,
  detail: null,
  nomFiche: null,
  email: '',
  telephone: '',
}

/** Champs envoyés avec la pièce (réquisition, ordre ou sortie). */
export function payloadBeneficiaire(saisie: BeneficiaireSaisie): Record<string, string | null> {
  const email = saisie.email.trim()
  const telephone = saisie.telephone.trim()
  // Sans fiche mais avec un contact : la personne est enregistrée comme externe,
  // seul moyen de la prévenir.
  const type = saisie.type ?? (email || telephone ? 'EXTERNE' : null)
  return {
    beneficiaire_type: type,
    beneficiaire_ref_id: saisie.refId,
    beneficiaire_email: email || null,
    beneficiaire_telephone: telephone || null,
  }
}

/** Identification déjà portée par une pièce, pour la reprendre dans un formulaire. */
export function saisieDepuis(source: any, nom?: string | null): BeneficiaireSaisie {
  if (!source?.beneficiaire_type) return { ...BENEFICIAIRE_VIDE }
  return {
    type: source.beneficiaire_type,
    refId: source.beneficiaire_ref_id || null,
    detail: null,
    nomFiche: source.beneficiaire_ref_id ? (nom ?? source.beneficiaire ?? null) : null,
    email: source.beneficiaire_email || '',
    telephone: source.beneficiaire_telephone || '',
  }
}

interface Props {
  id: string
  label?: ReactNode
  nom: string
  onNomChange: (nom: string) => void
  value: BeneficiaireSaisie
  onChange: (value: BeneficiaireSaisie) => void
  required?: boolean
  placeholder?: string
  disabled?: boolean
  /** Nom et contacts arrêtés en amont (réquisition, ordre) : on les montre, on n'y touche pas. */
  lectureSeule?: boolean
  inputClassName?: string
  aide?: ReactNode
  /** En saisie facultative, masque les contacts tant qu'aucun nom n'est saisi. */
  compactEmpty?: boolean
}

/**
 * Champ Bénéficiaire : on tape le nom, l'application propose les fiches — les
 * experts-comptables d'abord, puis le personnel, puis les personnes externes —
 * comme la recherche d'experts de l'encaissement. Le téléphone et l'e-mail
 * servent à prévenir la personne quand les fonds lui sont remis.
 */
export default function BeneficiaireIdentification({
  id,
  label = 'Bénéficiaire',
  nom,
  onNomChange,
  value,
  onChange,
  required,
  placeholder = 'Rechercher : nom, n° d’ordre, matricule… ou saisir un nom',
  disabled,
  lectureSeule,
  inputClassName,
  aide,
  compactEmpty,
}: Props) {
  const [suggestions, setSuggestions] = useState<BeneficiaireSuggestion[]>([])
  const [chargement, setChargement] = useState(false)
  const [ouvert, setOuvert] = useState(false)
  // Téléphone et e-mail ne s'affichent pas d'emblée : un clic sur le
  // bénéficiaire les déplie.
  const [contactsVisibles, setContactsVisibles] = useState(false)
  const conteneur = useRef<HTMLDivElement>(null)
  const terme = useDebouncedValue(nom.trim(), 300)

  useEffect(() => {
    if (lectureSeule || disabled || value.refId || !ouvert || terme.length < 2) {
      setSuggestions([])
      return
    }
    let actif = true
    setChargement(true)
    rechercherBeneficiaires(terme)
      .then((items) => {
        if (actif) setSuggestions(items)
      })
      .catch(() => {
        if (actif) setSuggestions([])
      })
      .finally(() => {
        if (actif) setChargement(false)
      })
    return () => {
      actif = false
    }
  }, [terme, value.refId, ouvert, lectureSeule, disabled])

  // Un clic ailleurs referme la liste, comme un menu.
  useEffect(() => {
    const fermer = (e: MouseEvent) => {
      if (conteneur.current && !conteneur.current.contains(e.target as Node)) setOuvert(false)
    }
    document.addEventListener('mousedown', fermer)
    return () => document.removeEventListener('mousedown', fermer)
  }, [])

  const taper = (texte: string) => {
    onNomChange(texte)
    setOuvert(true)
    // Le nom ne correspond plus à la fiche choisie : elle est détachée, ses
    // contacts avec elle.
    if (value.refId && texte.trim() !== (value.nomFiche || '').trim()) {
      onChange({ ...BENEFICIAIRE_VIDE })
    }
  }

  const choisir = (s: BeneficiaireSuggestion) => {
    onNomChange(s.nom)
    onChange({
      type: s.type,
      refId: s.id,
      detail: s.detail || null,
      nomFiche: s.nom,
      email: s.email || '',
      telephone: s.telephone || '',
    })
    setSuggestions([])
    setOuvert(false)
  }

  const sansContact = !value.email.trim() && !value.telephone.trim()

  const boutonContacts = (
    <button
      type="button"
      className={styles.lienBtn}
      onClick={() => setContactsVisibles((v) => !v)}
      aria-expanded={contactsVisibles}
    >
      {contactsVisibles ? '▾' : '▸'} {nom.trim() || 'Bénéficiaire'} — téléphone et e-mail
      {!contactsVisibles && (sansContact ? ' (non renseignés)' : ' (renseignés)')}
    </button>
  )

  if (lectureSeule) {
    return (
      <div className={styles.identification}>
        <label htmlFor={id}>{label}</label>
        <input id={id} type="text" value={nom} disabled className={inputClassName} />
        {aide}
        <div className={styles.ficheChoisie}>
          {value.type && <span className={styles.typeChip}>{TYPE_BENEFICIAIRE_LABELS[value.type]}</span>}
          {sansContact ? (
            <span className={styles.ficheDetail}>
              Aucun téléphone ni e-mail enregistré en amont : le bénéficiaire ne sera pas prévenu.
            </span>
          ) : (
            boutonContacts
          )}
        </div>
        {contactsVisibles && !sansContact && (
          <div className={styles.contactsLecture}>
            {value.telephone && <span>WhatsApp : {value.telephone}</span>}
            {value.email && <span>E-mail : {value.email}</span>}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className={styles.identification} ref={conteneur}>
      <label htmlFor={id}>
        {label}
        {required ? ' *' : ''}
      </label>
      <div className={styles.champRecherche}>
        <input
          id={id}
          type="text"
          value={nom}
          onChange={(e) => taper(e.target.value)}
          onFocus={() => setOuvert(true)}
          placeholder={placeholder}
          disabled={disabled}
          required={required}
          autoComplete="off"
          className={`${inputClassName || ''} ${value.refId ? styles.champIdentifie : ''}`}
          aria-autocomplete="list"
          aria-expanded={suggestions.length > 0}
        />
        {value.refId && <span className={styles.coche} aria-hidden="true"><Check size="1em" aria-hidden="true" /></span>}
        {ouvert && suggestions.length > 0 && (
          <ul className={styles.dropdown} role="listbox" aria-label="Fiches correspondantes">
            {suggestions.map((s) => (
              <li key={`${s.type}-${s.id}`}>
                <button
                  type="button"
                  className={styles.dropdownItem}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => choisir(s)}
                >
                  <span className={styles.typeChip}>{TYPE_BENEFICIAIRE_LABELS[s.type]}</span>
                  <strong>{s.nom}</strong>
                  {s.detail && <small className={styles.ficheDetail}>{s.detail}</small>}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      {chargement && ouvert && <small className={styles.aide}>Recherche en cours…</small>}
      {aide}
      {value.refId && value.type && (
        <div className={styles.ficheChoisie}>
          <span className={styles.typeChip}>{TYPE_BENEFICIAIRE_LABELS[value.type]}</span>
          {value.detail && <span className={styles.ficheDetail}>{value.detail}</span>}
        </div>
      )}

      {(!compactEmpty || nom.trim() || contactsVisibles) && boutonContacts}
      {contactsVisibles && (
      <div className={styles.contacts}>
        <label className={styles.contactField}>
          <span>Téléphone (WhatsApp)</span>
          <input
            type="tel"
            value={value.telephone}
            onChange={(e) => onChange({ ...value, telephone: e.target.value })}
            placeholder="+243 8xx xxx xxx"
            disabled={disabled}
          />
        </label>
        <label className={styles.contactField}>
          <span>E-mail</span>
          <input
            type="email"
            value={value.email}
            onChange={(e) => onChange({ ...value, email: e.target.value })}
            placeholder="adresse@exemple.org"
            disabled={disabled}
          />
        </label>
      </div>
      )}
      <small className={styles.aide}>
        {compactEmpty && !nom.trim()
          ? 'Facultatif : il pourra être ajouté après validation, et devra l’être avant le paiement.'
          : sansContact
          ? 'Sans téléphone ni e-mail, le bénéficiaire ne sera pas prévenu de la remise des fonds.'
          : !value.refId && nom.trim()
            ? 'Aucune fiche choisie : une fiche « personne externe » sera créée à ce nom.'
            : 'Le bénéficiaire sera prévenu de la remise des fonds.'}
      </small>
    </div>
  )
}
