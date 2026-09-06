/**
 * Grille tarifaire de l'application.
 *
 * `Organisation.plan_type` portait jusqu'ici une chaîne libre : deux
 * organisations sur le même plan pouvaient l'écrire différemment, et le prix
 * affiché n'avait aucun lien avec le plan. Le catalogue édité ici devient la
 * référence — dès qu'il contient au moins un plan, le serveur n'accepte plus
 * que ses codes pour une organisation.
 *
 * Le catalogue s'enregistre en bloc : on édite un tableau, on l'enregistre.
 */

import { useEffect, useMemo, useState } from 'react'
import { Loader2, Plus, Save, Trash2 } from 'lucide-react'
import {
  listBillingPlans,
  updateBillingPlans,
  type BillingPlan,
} from '../../api/superAdmin'
import { useNotification } from '../../contexts/NotificationContext'
import styles from './Reglages.module.css'

// Le serveur retombe silencieusement sur ces valeurs pour tout ce qu'il ne
// reconnaît pas : les proposer ici évite de découvrir la correction après coup.
const DEVISES = ['USD', 'CDF'] as const
const PERIODICITES = [
  { value: 'monthly', label: 'Mensuel' },
  { value: 'quarterly', label: 'Trimestriel' },
  { value: 'semiannual', label: 'Semestriel' },
  { value: 'yearly', label: 'Annuel' },
] as const

const PLAN_VIDE: BillingPlan = {
  code: '',
  name: '',
  description: '',
  price: '0.00',
  currency: 'USD',
  interval: 'monthly',
  active: true,
}

/** Même normalisation que le serveur, pour que l'aperçu ne mente pas. */
const normaliserCode = (valeur: string) =>
  valeur
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9_-]/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 50)

/** `onChange` : la console rattache les organisations aux codes de la grille.
 *  Elle doit la relire après un enregistrement, sinon ses listes déroulantes
 *  proposent encore les plans d'avant. */
export default function PlanCatalogueEditor({ onChange }: { onChange?: () => void }) {
  const { showSuccess, showError } = useNotification()
  const [plans, setPlans] = useState<BillingPlan[]>([])
  const [chargement, setChargement] = useState(true)
  const [enregistrement, setEnregistrement] = useState(false)
  const [modifie, setModifie] = useState(false)

  useEffect(() => {
    let actif = true
    const charger = async () => {
      try {
        const res = await listBillingPlans()
        if (actif) {
          setPlans(res)
          setModifie(false)
        }
      } catch (err: any) {
        if (actif) showError('Chargement impossible', err?.message || 'Grille tarifaire illisible.')
      } finally {
        if (actif) setChargement(false)
      }
    }
    charger()
    return () => { actif = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const modifier = (index: number, champ: keyof BillingPlan, valeur: string | boolean) => {
    setPlans((precedent) =>
      precedent.map((plan, i) => (i === index ? { ...plan, [champ]: valeur } : plan))
    )
    setModifie(true)
  }

  const ajouter = () => {
    setPlans((precedent) => [...precedent, { ...PLAN_VIDE }])
    setModifie(true)
  }

  const retirer = (index: number) => {
    setPlans((precedent) => precedent.filter((_, i) => i !== index))
    setModifie(true)
  }

  // Deux plans de même code s'écraseraient à l'enregistrement : le serveur
  // garde le dernier. Mieux vaut le dire avant.
  const doublons = useMemo(() => {
    const vus = new Set<string>()
    const repetes = new Set<string>()
    for (const plan of plans) {
      const code = normaliserCode(plan.code)
      if (!code) continue
      if (vus.has(code)) repetes.add(code)
      vus.add(code)
    }
    return repetes
  }, [plans])

  const sansCode = plans.some((plan) => !normaliserCode(plan.code))

  const enregistrer = async () => {
    if (sansCode) {
      showError('Code manquant', 'Chaque plan doit porter un code : c’est sa clé.')
      return
    }
    if (doublons.size > 0) {
      showError('Codes en double', `Un même code ne peut pas désigner deux plans : ${[...doublons].join(', ')}.`)
      return
    }
    setEnregistrement(true)
    try {
      const res = await updateBillingPlans(plans)
      setPlans(res)
      setModifie(false)
      onChange?.()
      showSuccess('Grille enregistrée', `${res.length} plan${res.length > 1 ? 's' : ''} au catalogue.`)
    } catch (err: any) {
      showError('Enregistrement impossible', err?.message || 'La grille n’a pas été modifiée.')
    } finally {
      setEnregistrement(false)
    }
  }

  if (chargement) {
    return <div className={styles.state}>Chargement de la grille tarifaire…</div>
  }

  return (
    <section className={styles.panel}>
      <div className={styles.panelHead}>
        <div>
          <h3 className={styles.panelTitle}>Grille tarifaire</h3>
          <p className={styles.panelHint}>
            Le code est la clé du plan : c’est lui que porte une organisation. Tant que cette
            grille est vide, le plan d’une organisation reste une saisie libre ; dès qu’elle
            contient un plan, seuls ces codes sont acceptés. Retirer un plan de la grille ne
            change rien aux organisations qui y sont déjà rattachées.
          </p>
        </div>
        <div className={styles.actions}>
          <button type="button" className={styles.ghostBtn} onClick={ajouter} disabled={enregistrement}>
            <Plus size={15} />
            Ajouter un plan
          </button>
          <button
            type="button"
            className={styles.primaryBtn}
            onClick={enregistrer}
            disabled={enregistrement || !modifie}
          >
            {enregistrement ? <Loader2 size={15} className="spin" /> : <Save size={15} />}
            Enregistrer
          </button>
        </div>
      </div>

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th className={styles.colCode}>Code</th>
              <th>Nom</th>
              <th>Description</th>
              <th className={styles.colPrice}>Prix</th>
              <th className={styles.colCurrency}>Devise</th>
              <th className={styles.colInterval}>Périodicité</th>
              <th className={styles.colActive}>Actif</th>
              <th className={styles.colRemove} aria-label="Retirer" />
            </tr>
          </thead>
          <tbody>
            {plans.length === 0 ? (
              <tr>
                <td colSpan={8} className={styles.empty}>
                  Aucun plan. Ajoutez-en un pour décrire vos tarifs.
                </td>
              </tr>
            ) : (
              plans.map((plan, index) => {
                const code = normaliserCode(plan.code)
                const enDouble = code !== '' && doublons.has(code)
                return (
                  <tr key={index}>
                    <td>
                      <input
                        type="text"
                        className={`${styles.cellInput} ${styles.codeInput}`}
                        value={plan.code}
                        onChange={(e) => modifier(index, 'code', e.target.value)}
                        placeholder="SOCLE"
                        aria-label={`Code du plan ${index + 1}`}
                        title={
                          enDouble
                            ? 'Ce code désigne déjà un autre plan.'
                            : code && code !== plan.code.trim()
                            ? `Enregistré sous : ${code}`
                            : undefined
                        }
                        style={enDouble ? { borderColor: '#dc2626' } : undefined}
                      />
                    </td>
                    <td>
                      <input
                        type="text"
                        className={styles.cellInput}
                        value={plan.name}
                        onChange={(e) => modifier(index, 'name', e.target.value)}
                        placeholder="Socle"
                        aria-label={`Nom du plan ${index + 1}`}
                      />
                    </td>
                    <td>
                      <input
                        type="text"
                        className={styles.cellInput}
                        value={plan.description}
                        onChange={(e) => modifier(index, 'description', e.target.value)}
                        placeholder="Ce que comprend le plan"
                        aria-label={`Description du plan ${index + 1}`}
                      />
                    </td>
                    <td>
                      <input
                        type="text"
                        inputMode="decimal"
                        className={`${styles.cellInput} ${styles.priceInput}`}
                        value={plan.price}
                        onChange={(e) => modifier(index, 'price', e.target.value)}
                        aria-label={`Prix du plan ${index + 1}`}
                      />
                    </td>
                    <td>
                      <select
                        className={styles.cellSelect}
                        value={plan.currency}
                        onChange={(e) => modifier(index, 'currency', e.target.value)}
                        aria-label={`Devise du plan ${index + 1}`}
                      >
                        {DEVISES.map((devise) => (
                          <option key={devise} value={devise}>{devise}</option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <select
                        className={styles.cellSelect}
                        value={plan.interval}
                        onChange={(e) => modifier(index, 'interval', e.target.value)}
                        aria-label={`Périodicité du plan ${index + 1}`}
                      >
                        {PERIODICITES.map((periode) => (
                          <option key={periode.value} value={periode.value}>{periode.label}</option>
                        ))}
                      </select>
                    </td>
                    <td className={styles.colActive}>
                      <input
                        type="checkbox"
                        checked={plan.active}
                        onChange={(e) => modifier(index, 'active', e.target.checked)}
                        aria-label={`Plan ${index + 1} actif`}
                      />
                    </td>
                    <td>
                      <button
                        type="button"
                        className={styles.rowRemove}
                        onClick={() => retirer(index)}
                        title="Retirer ce plan"
                        aria-label={`Retirer le plan ${plan.name || plan.code || index + 1}`}
                      >
                        <Trash2 size={15} />
                      </button>
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}
