import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Plus, Trash2 } from 'lucide-react'
import {
  enregistrerComptaTauxChange,
  getComptaTauxChange,
  supprimerComptaTauxChange,
} from '../../api/comptabilite'
import { useToast } from '../../hooks/useToast'
import styles from './ComptaMappingsPanel.module.css'

interface Props {
  canParametrer: boolean
}

function aujourdhui(): string {
  return new Date().toISOString().slice(0, 10)
}

/**
 * Taux de change COMPTABLES.
 *
 * À ne pas confondre avec les taux de trésorerie des réglages d'impression :
 * la trésorerie applique le taux du jour pour encaisser ou décaisser, la
 * comptabilité retient le taux de la période (taux moyen, de clôture, taux
 * officiel). Le moteur de génération n'utilise que ces taux-ci — celui de la
 * trésorerie n'est jamais repris automatiquement, il est seulement proposé
 * comme point de départ.
 */
export default function TauxChangeSection({ canParametrer }: Props) {
  const queryClient = useQueryClient()
  const { notifyError, notifySuccess } = useToast()

  const [deviseSource, setDeviseSource] = useState('CDF')
  const [taux, setTaux] = useState('')
  const [dateTaux, setDateTaux] = useState(aujourdhui())
  const [libelleSource, setLibelleSource] = useState('')

  const tauxQuery = useQuery({
    queryKey: ['compta-taux-change'],
    queryFn: getComptaTauxChange,
  })

  const invalider = () => queryClient.invalidateQueries({ queryKey: ['compta-taux-change'] })

  const enregistrer = useMutation({
    mutationFn: enregistrerComptaTauxChange,
    onSuccess: () => {
      invalider()
      setTaux('')
      setLibelleSource('')
      notifySuccess('Taux enregistré', 'Les prochaines écritures l’utiliseront.')
    },
    onError: (err: any) =>
      notifyError('Taux refusé', err?.message || 'Impossible d’enregistrer ce taux.'),
  })

  const supprimer = useMutation({
    mutationFn: supprimerComptaTauxChange,
    onSuccess: () => {
      invalider()
      notifySuccess('Taux supprimé', 'Les écritures déjà générées gardent leur taux figé.')
    },
    onError: (err: any) => notifyError('Suppression impossible', err?.message || 'Erreur.'),
  })

  const donnees = tauxQuery.data
  const deviseTenue = donnees?.devise_tenue ?? 'USD'

  return (
    <section className={styles.section}>
      <header className={styles.sectionHeader}>
        <h3>Taux de change comptables</h3>
        <p>
          Devise de tenue : <strong>{deviseTenue}</strong>. Toute écriture dans une autre devise y
          est convertie à ces taux.
        </p>
      </header>

      <div className={`${styles.banner} ${styles.bannerInfo} ${styles.sectionNote}`}>
        <AlertTriangle size={18} className={styles.bannerIcon} />
        <div>
          <strong>Le taux comptable n’est pas le taux de trésorerie</strong>
          <p>
            La trésorerie applique le taux du jour pour encaisser ou décaisser. La comptabilité
            retient le taux de la période — taux moyen, taux de clôture, taux officiel. Le taux de
            trésorerie n’est donc <strong>jamais repris automatiquement</strong> : il vous est
            proposé comme point de départ, à vous de retenir celui qui fait foi.
          </p>
        </div>
      </div>

      {donnees && donnees.manquants.length > 0 && (
        <div className={`${styles.banner} ${styles.bannerWarning} ${styles.sectionNote}`}>
          <AlertTriangle size={18} className={styles.bannerIcon} />
          <div>
            <strong>
              {donnees.manquants.length} devise{donnees.manquants.length > 1 ? 's' : ''} sans taux
              comptable
            </strong>
            <p>
              Toute écriture dans{' '}
              {donnees.manquants.map(m => m.devise).join(', ')} sera <strong>refusée</strong> tant
              qu’un taux n’est pas saisi.
            </p>
            {canParametrer && (
              <div className={styles.propositions}>
                {donnees.manquants
                  .filter(m => m.taux_tresorerie_propose)
                  .map(m => (
                    <button
                      key={m.devise}
                      type="button"
                      className={styles.bannerAction}
                      disabled={enregistrer.isPending}
                      onClick={() =>
                        enregistrer.mutate({
                          devise_source: m.devise,
                          devise_cible: m.devise_tenue,
                          taux: m.taux_tresorerie_propose as string,
                          date_taux: aujourdhui(),
                          source: 'Repris du taux de trésorerie',
                        })
                      }
                    >
                      Reprendre le taux de trésorerie pour {m.devise}
                    </button>
                  ))}
              </div>
            )}
          </div>
        </div>
      )}

      {canParametrer && (
        <form
          className={styles.formTaux}
          onSubmit={e => {
            e.preventDefault()
            if (!taux) return
            enregistrer.mutate({
              devise_source: deviseSource.toUpperCase(),
              devise_cible: deviseTenue,
              taux,
              date_taux: dateTaux,
              source: libelleSource || null,
            })
          }}
        >
          <div className={styles.champTaux}>
            <label htmlFor="taux-devise">Devise</label>
            <input
              id="taux-devise"
              type="text"
              maxLength={3}
              value={deviseSource}
              onChange={e => setDeviseSource(e.target.value.toUpperCase())}
            />
          </div>
          <div className={styles.champTaux}>
            <label htmlFor="taux-valeur">1 {deviseSource || '???'} = ? {deviseTenue}</label>
            <input
              id="taux-valeur"
              type="text"
              inputMode="decimal"
              placeholder="0.00035714"
              value={taux}
              onChange={e => setTaux(e.target.value)}
            />
          </div>
          <div className={styles.champTaux}>
            <label htmlFor="taux-date">Applicable à partir du</label>
            <input
              id="taux-date"
              type="date"
              value={dateTaux}
              onChange={e => setDateTaux(e.target.value)}
            />
          </div>
          <div className={styles.champTaux}>
            <label htmlFor="taux-source">Source (facultatif)</label>
            <input
              id="taux-source"
              type="text"
              placeholder="Taux moyen BCC"
              value={libelleSource}
              onChange={e => setLibelleSource(e.target.value)}
            />
          </div>
          <button type="submit" className={styles.bannerAction} disabled={enregistrer.isPending}>
            <Plus size={15} />
            {enregistrer.isPending ? 'Enregistrement…' : 'Enregistrer'}
          </button>
        </form>
      )}

      {tauxQuery.isLoading ? (
        <div className={styles.loadingState}>Chargement des taux…</div>
      ) : !donnees || donnees.taux.length === 0 ? (
        <div className={styles.emptyState}>Aucun taux comptable saisi.</div>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>À partir du</th>
              <th>Conversion</th>
              <th>Taux</th>
              <th>Équivaut à</th>
              <th>Source</th>
              {canParametrer && <th />}
            </tr>
          </thead>
          <tbody>
            {donnees.taux.map(t => (
              <tr key={t.id}>
                <td className={styles.codeCell}>{t.date_taux}</td>
                <td>
                  {t.devise_source} → {t.devise_cible}
                </td>
                <td className={styles.codeCell}>{t.taux}</td>
                <td className={styles.typeCell}>
                  {t.taux_inverse} {t.devise_source} pour 1 {t.devise_cible}
                </td>
                <td className={styles.typeCell}>{t.source || '—'}</td>
                {canParametrer && (
                  <td>
                    <button
                      type="button"
                      className={styles.supprimerBtn}
                      aria-label={`Supprimer le taux du ${t.date_taux}`}
                      disabled={supprimer.isPending}
                      onClick={() => supprimer.mutate(t.id)}
                    >
                      <Trash2 size={15} />
                    </button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
