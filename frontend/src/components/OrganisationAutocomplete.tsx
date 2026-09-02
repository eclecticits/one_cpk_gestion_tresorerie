import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { ChevronDown, Search } from 'lucide-react'
import { listOrganisationOptions, type OrganisationOption } from '../api/organisation'
import { useAuth } from '../contexts/AuthContext'
import styles from './OrganisationAutocomplete.module.css'

export const ORGANISATION_OTHER_VALUE = '__OTHER__'

export type OrganisationAutocompleteValue = number | typeof ORGANISATION_OTHER_VALUE | null

/** Entrée du menu : une organisation du référentiel, ou l'échappatoire « autre ». */
type Entry =
  | { kind: 'org'; org: OrganisationOption }
  | { kind: 'other' }

type Props = {
  value: OrganisationAutocompleteValue
  onChange: (value: OrganisationAutocompleteValue, organisation?: OrganisationOption | null) => void
  excludeCurrentOrganisation?: boolean
  allowOther?: boolean
  otherLabel?: string
  disabled?: boolean
  placeholder?: string
  inputId?: string
}

/**
 * Désignation d'une organisation du référentiel — le tiers d'un fonds détenu,
 * l'instance qui doit rembourser une avance.
 *
 * Le champ affiché n'est pas la valeur : celle-ci est un identifiant tenu par le
 * parent. Il ne porte donc pas `required`, qui ne validerait que du texte ; c'est
 * au formulaire de refuser une valeur absente.
 */
export default function OrganisationAutocomplete({
  value,
  onChange,
  excludeCurrentOrganisation = false,
  allowOther = false,
  otherLabel = 'Autres',
  disabled = false,
  placeholder = 'Rechercher une organisation',
  inputId,
}: Props) {
  const { user } = useAuth()
  const rootRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const generatedId = useId()
  const listboxId = `${inputId || generatedId}-listbox`
  const [organisations, setOrganisations] = useState<OrganisationOption[]>([])
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    listOrganisationOptions({ limit: 500 })
      .then((items) => {
        if (!cancelled) setOrganisations(Array.isArray(items) ? items : [])
      })
      .catch((err) => {
        if (!cancelled) {
          setOrganisations([])
          setError(err?.message || 'Chargement impossible')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const close = useCallback(() => {
    setOpen(false)
    setQuery('')
  }, [])

  // `focusout` plutôt qu'un `mousedown` global : sortir au clavier (Tab) doit
  // refermer le menu comme un clic ailleurs, sans quoi le champ reste ouvert et
  // vide alors qu'une valeur est bien sélectionnée.
  useEffect(() => {
    const root = rootRef.current
    if (!root) return
    const handleFocusOut = (event: FocusEvent) => {
      const next = event.relatedTarget as Node | null
      if (next && root.contains(next)) return
      close()
    }
    const handlePointerDown = (event: MouseEvent) => {
      if (!root.contains(event.target as Node)) close()
    }
    root.addEventListener('focusout', handleFocusOut)
    document.addEventListener('mousedown', handlePointerDown)
    return () => {
      root.removeEventListener('focusout', handleFocusOut)
      document.removeEventListener('mousedown', handlePointerDown)
    }
  }, [close])

  const currentOrganisationId = user?.organisation_id == null ? null : Number(user.organisation_id)
  const visibleOrganisations = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    return organisations
      .filter((org) => !excludeCurrentOrganisation || currentOrganisationId == null || org.id !== currentOrganisationId)
      .filter((org) => {
        if (!normalized) return true
        return `${org.nom} ${org.slug}`.toLowerCase().includes(normalized)
      })
      .slice(0, 50)
  }, [currentOrganisationId, excludeCurrentOrganisation, organisations, query])

  const entries = useMemo<Entry[]>(() => {
    const items: Entry[] = visibleOrganisations.map((org) => ({ kind: 'org', org }))
    if (allowOther) items.push({ kind: 'other' })
    return items
  }, [allowOther, visibleOrganisations])

  // Une frappe qui réduit la liste ne doit pas laisser le curseur au-delà.
  useEffect(() => {
    setActiveIndex((prev) => (prev < entries.length ? prev : 0))
  }, [entries.length])

  const selectedOrganisation = useMemo(
    () => organisations.find((org) => org.id === value) || null,
    [organisations, value],
  )

  const select = useCallback(
    (entry: Entry) => {
      if (entry.kind === 'other') onChange(ORGANISATION_OTHER_VALUE, null)
      else onChange(entry.org.id, entry.org)
      close()
    },
    [close, onChange],
  )

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Escape') {
      close()
      return
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      if (!open) {
        setOpen(true)
        return
      }
      if (entries.length === 0) return
      const step = event.key === 'ArrowDown' ? 1 : -1
      setActiveIndex((prev) => (prev + step + entries.length) % entries.length)
      return
    }
    if (event.key === 'Enter' && open) {
      const entry = entries[activeIndex]
      if (entry) {
        // Ne pas laisser l'Entrée soumettre le formulaire qui contient le champ.
        event.preventDefault()
        select(entry)
      }
    }
  }

  const displayValue = open ? query : value === ORGANISATION_OTHER_VALUE ? otherLabel : selectedOrganisation?.nom || ''

  return (
    <div className={styles.root} ref={rootRef}>
      <div className={styles.inputWrap} data-disabled={disabled ? 'true' : 'false'}>
        <Search size={16} className={styles.searchIcon} aria-hidden="true" />
        <input
          id={inputId}
          ref={inputRef}
          type="text"
          role="combobox"
          autoComplete="off"
          aria-expanded={open}
          aria-controls={open ? listboxId : undefined}
          aria-activedescendant={open && entries[activeIndex] ? `${listboxId}-${activeIndex}` : undefined}
          value={displayValue}
          disabled={disabled}
          placeholder={loading ? 'Chargement...' : placeholder}
          onFocus={() => {
            setQuery('')
            setActiveIndex(0)
            setOpen(true)
          }}
          onChange={(event) => {
            setQuery(event.target.value)
            setActiveIndex(0)
            setOpen(true)
          }}
          onKeyDown={handleKeyDown}
        />
        <button
          type="button"
          className={styles.toggle}
          disabled={disabled}
          tabIndex={-1}
          onClick={() => {
            setQuery('')
            setActiveIndex(0)
            setOpen((prev) => !prev)
            inputRef.current?.focus()
          }}
          aria-label="Afficher les organisations"
        >
          <ChevronDown size={16} />
        </button>
      </div>
      {open && !disabled && (
        <div className={styles.menu} role="listbox" id={listboxId}>
          {error ? (
            <div className={styles.empty}>{error}</div>
          ) : loading ? (
            <div className={styles.empty}>Chargement...</div>
          ) : entries.length === 0 ? (
            <div className={styles.empty}>Aucune organisation trouvée</div>
          ) : (
            entries.map((entry, index) => {
              const isOther = entry.kind === 'other'
              const selected = isOther ? value === ORGANISATION_OTHER_VALUE : entry.org.id === value
              return (
                <button
                  type="button"
                  key={isOther ? '__other__' : entry.org.id}
                  id={`${listboxId}-${index}`}
                  role="option"
                  aria-selected={selected}
                  className={styles.item}
                  data-selected={selected ? 'true' : 'false'}
                  data-active={index === activeIndex ? 'true' : 'false'}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => select(entry)}
                >
                  <span className={styles.icon}>{isOther ? '+' : entry.org.icon || 'ORG'}</span>
                  <span>
                    <strong>{isOther ? otherLabel : entry.org.nom}</strong>
                    <small>{isOther ? 'Tiers externe' : entry.org.slug}</small>
                  </span>
                </button>
              )
            })
          )}
        </div>
      )}
    </div>
  )
}
