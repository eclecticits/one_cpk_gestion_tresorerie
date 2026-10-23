import { useEffect, useRef, useState, type MouseEvent, type ReactNode } from 'react'
import { Check } from 'lucide-react'
import styles from './FormSections.module.css'

export type FormSectionItem = {
  id: string
  label: string
  complete?: boolean
  /** Section facultative : son absence ne retient pas l'enregistrement. */
  optional?: boolean
}

/**
 * Sommaire des sections d'un long formulaire de création.
 *
 * Il reste collé en haut pendant le défilement, signale la section visible et
 * compte les sections obligatoires déjà remplies. Les sections facultatives
 * vides ne portent ni coche ni alerte : rien n'y manque.
 */
export function FormSectionNav({ items, label }: { items: FormSectionItem[]; label: string }) {
  const [activeId, setActiveId] = useState<string | null>(items[0]?.id ?? null)
  const navRef = useRef<HTMLElement>(null)
  const idsKey = items.map((item) => item.id).join('|')

  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') return
    const sections = idsKey
      .split('|')
      .map((id) => document.getElementById(id))
      .filter((el): el is HTMLElement => Boolean(el))
    if (sections.length === 0) return

    const visibles = new Map<string, number>()
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) visibles.set(entry.target.id, entry.boundingClientRect.top)
          else visibles.delete(entry.target.id)
        }
        // La plus haute des sections présentes dans la bande de lecture.
        const first = [...visibles.entries()].sort((a, b) => a[1] - b[1])[0]
        if (first) setActiveId(first[0])
      },
      { rootMargin: '-96px 0px -50% 0px' },
    )
    sections.forEach((section) => observer.observe(section))
    return () => observer.disconnect()
  }, [idsKey])

  // Sur mobile, le sommaire défile horizontalement : l'étape active reste en vue.
  useEffect(() => {
    if (!activeId) return
    const link = navRef.current?.querySelector<HTMLElement>(`[data-section="${activeId}"]`)
    const nav = navRef.current
    if (!link || !nav || nav.scrollWidth <= nav.clientWidth) return
    nav.scrollTo({ left: link.offsetLeft - 12, behavior: 'smooth' })
  }, [activeId])

  const goTo = (event: MouseEvent<HTMLAnchorElement>, id: string) => {
    const target = document.getElementById(id)
    if (!target) return
    // Pas de fragment dans l'URL : il survivrait au retour sur la liste.
    event.preventDefault()
    target.scrollIntoView({ behavior: 'smooth', block: 'start' })
    setActiveId(id)
  }

  const required = items.filter((item) => !item.optional)
  const done = required.filter((item) => item.complete).length
  const progress = required.length > 0 ? (done / required.length) * 100 : 0

  return (
    <nav ref={navRef} className={styles.sectionNav} aria-label={label}>
      <div className={styles.navItems}>
        {items.map((item, index) => {
          const state = item.complete ? 'complete' : item.optional ? 'optional' : 'pending'
          return (
            <a
              key={item.id}
              href={`#${item.id}`}
              data-section={item.id}
              data-state={state}
              aria-current={activeId === item.id ? 'step' : undefined}
              onClick={(event) => goTo(event, item.id)}
            >
              <span className={styles.navNumber} aria-hidden="true">
                {item.complete ? <Check size={13} /> : index + 1}
              </span>
              <span className={styles.navText}>
                <span className={styles.navLabel}>{item.label}</span>
                <small className={styles.navState}>
                  {item.complete ? 'Renseigné' : item.optional ? 'Facultatif' : 'À compléter'}
                </small>
              </span>
            </a>
          )
        })}
      </div>
      <div
        className={styles.navProgress}
        role="progressbar"
        aria-label="Sections obligatoires renseignées"
        aria-valuemin={0}
        aria-valuemax={required.length}
        aria-valuenow={done}
        aria-valuetext={`${done} sur ${required.length}`}
      >
        <span style={{ width: `${progress}%` }} />
      </div>
    </nav>
  )
}

type FormSectionProps = {
  id: string
  number: number
  title: string
  description?: string
  optional?: boolean
  action?: ReactNode
  children: ReactNode
  className?: string
}

export function FormSection({
  id,
  number,
  title,
  description,
  optional,
  action,
  children,
  className,
}: FormSectionProps) {
  return (
    <section className={`${styles.sectionCard} ${className || ''}`} aria-labelledby={`${id}-title`} id={id}>
      <header className={styles.sectionHeader}>
        <div className={styles.sectionHeading}>
          <span className={styles.sectionNumber} aria-hidden="true">{number}</span>
          <div className={styles.sectionTitleGroup}>
            <div className={styles.sectionTitleLine}>
              <h3 id={`${id}-title`}>{title}</h3>
              {optional && <span className={styles.optionalBadge}>Facultatif</span>}
            </div>
            {description && <p className={styles.sectionDescription}>{description}</p>}
          </div>
        </div>
        {action}
      </header>
      <div className={styles.sectionBody}>{children}</div>
    </section>
  )
}
