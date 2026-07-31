import { useState } from 'react'
import { Calculator } from 'lucide-react'
import type { TypeReferentiel } from '../../types/comptabilite'
import styles from './ComptaSetupScreen.module.css'

const REFERENTIELS: { value: TypeReferentiel; label: string; description: string }[] = [
  {
    value: 'SYSCEBNL',
    label: 'SYSCEBNL',
    description:
      "Référentiel dédié aux entités à but non lucratif (ordres professionnels, associations, ONG). Recommandé pour l'ONEC.",
  },
  {
    value: 'SYSCOHADA',
    label: 'SYSCOHADA révisé',
    description:
      'Plan comptable général des entreprises de l’espace OHADA. À privilégier pour une activité commerciale classique.',
  },
]

function defaultDates() {
  const year = new Date().getFullYear()
  return {
    debut: `${year}-01-01`,
    fin: `${year}-12-31`,
  }
}

export default function ComptaSetupScreen({
  canConfigure,
  submitting,
  errorMessage,
  onSubmit,
}: {
  canConfigure: boolean
  submitting: boolean
  errorMessage: string | null
  onSubmit: (input: { type_referentiel: TypeReferentiel; exercice_date_debut: string; exercice_date_fin: string }) => void
}) {
  const defaults = defaultDates()
  const [referentiel, setReferentiel] = useState<TypeReferentiel>('SYSCEBNL')
  const [dateDebut, setDateDebut] = useState(defaults.debut)
  const [dateFin, setDateFin] = useState(defaults.fin)

  const isValid = Boolean(dateDebut && dateFin && dateDebut < dateFin)

  return (
    <div className={styles.wrapper}>
      <div className={styles.card}>
        <div className={styles.icon}>
          <Calculator size={26} />
        </div>
        <h1 className={styles.title}>Activer la comptabilité</h1>
        <p className={styles.lead}>
          Le module Comptabilité n'est pas encore configuré pour votre organisation. Choisissez le
          référentiel comptable et l'exercice à ouvrir : le plan de comptes et les journaux de base
          seront créés automatiquement.
        </p>

        {!canConfigure ? (
          <p className={styles.noAccess}>
            Vous n'avez pas la permission nécessaire (« Paramétrage comptable ») pour activer ce
            module. Contactez un administrateur.
          </p>
        ) : (
          <>
            <div className={styles.sectionLabel}>Référentiel comptable</div>
            <div className={styles.referentielGrid}>
              {REFERENTIELS.map(ref => {
                const active = referentiel === ref.value
                return (
                  <button
                    key={ref.value}
                    type="button"
                    className={`${styles.referentielOption} ${active ? styles.referentielOptionActive : ''}`}
                    onClick={() => setReferentiel(ref.value)}
                    aria-pressed={active}
                  >
                    <div className={styles.referentielOptionTitle}>
                      <span>{ref.label}</span>
                      <span className={`${styles.checkDot} ${active ? styles.checkDotActive : ''}`} />
                    </div>
                    <div className={styles.referentielOptionDesc}>{ref.description}</div>
                  </button>
                )
              })}
            </div>

            <div className={styles.sectionLabel}>Exercice à ouvrir</div>
            <div className={styles.dateRow}>
              <div className={styles.field}>
                <label htmlFor="compta-setup-date-debut">Date de début</label>
                <input
                  id="compta-setup-date-debut"
                  type="date"
                  value={dateDebut}
                  onChange={e => setDateDebut(e.target.value)}
                />
              </div>
              <div className={styles.field}>
                <label htmlFor="compta-setup-date-fin">Date de fin</label>
                <input
                  id="compta-setup-date-fin"
                  type="date"
                  value={dateFin}
                  onChange={e => setDateFin(e.target.value)}
                />
              </div>
            </div>

            {errorMessage && <div className={styles.errorBox}>{errorMessage}</div>}

            <button
              type="button"
              className={styles.submitBtn}
              disabled={!isValid || submitting}
              onClick={() =>
                onSubmit({
                  type_referentiel: referentiel,
                  exercice_date_debut: dateDebut,
                  exercice_date_fin: dateFin,
                })
              }
            >
              {submitting ? 'Activation en cours…' : 'Activer la comptabilité'}
            </button>
          </>
        )}
      </div>
    </div>
  )
}
