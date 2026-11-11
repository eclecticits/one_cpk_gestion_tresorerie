import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, AlertTriangle, Landmark, ReceiptText, Save, Users } from 'lucide-react'
import {
  enregistrerComptaCreancesParametres,
  getComptaCreancesParametres,
  reprendreComptaCreances,
} from '../../api/comptabilite'
import type { ComptaCompte, ComptaRepriseCreances } from '../../types/comptabilite'
import { toNumber } from '../../utils/amount'
import { useToast } from '../../hooks/useToast'
import CompteSelect from './CompteSelect'
import styles from './CreancesSection.module.css'

interface Props {
  comptes: ComptaCompte[]
  canParametrer: boolean
}

function montant(value: string | number): string {
  return new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(
    toNumber(value)
  )
}

/**
 * Créances.
 *
 * Éteint, une cotisation n'entre en comptabilité qu'à son encaissement.
 * Allumé, elle y entre à l'émission de la note de débit, au débit du compte
 * du tiers, et le règlement vient solder ce compte. Chaque tiers reçoit son
 * propre compte, ouvert sous le compte choisi ici.
 */
export default function CreancesSection({ comptes, canParametrer }: Props) {
  const queryClient = useQueryClient()
  const { notifyError, notifySuccess } = useToast()
  const [actif, setActif] = useState(false)
  const [racineId, setRacineId] = useState<number | null>(null)
  const [racineClientsId, setRacineClientsId] = useState<number | null>(null)
  const [libelleTiers, setLibelleTiers] = useState('membre')
  const [libelleJournal, setLibelleJournal] = useState('Adhérents')
  const [enCours, setEnCours] = useState(false)
  const [apercu, setApercu] = useState<ComptaRepriseCreances | null>(null)

  const parametresQuery = useQuery({
    queryKey: ['compta-creances-parametres'],
    queryFn: getComptaCreancesParametres,
  })
  const parametres = parametresQuery.data

  useEffect(() => {
    if (!parametres) return
    setActif(parametres.actif)
    setRacineId(parametres.compte_racine_id)
    setRacineClientsId(parametres.compte_racine_clients_id)
    setLibelleTiers(parametres.libelle_tiers)
    setLibelleJournal(parametres.libelle_journal)
  }, [parametres])

  // Le mot de l'organisation pour ses tiers : « membre », « adhérent », « client »…
  const tiers = (libelleTiers.trim() || parametres?.libelle_tiers || 'membre').toLowerCase()
  const tiersPluriel = /[sxz]$/.test(tiers) ? tiers : `${tiers}s`

  // Les comptes individuels des tiers s'ouvrent sous ce compte.
  const comptesTiers = comptes.filter(c => c.numero.startsWith('4') && c.actif)
  const modifie = parametres
    ? actif !== parametres.actif ||
      racineId !== parametres.compte_racine_id ||
      racineClientsId !== parametres.compte_racine_clients_id ||
      libelleTiers.trim() !== parametres.libelle_tiers ||
      libelleJournal.trim() !== parametres.libelle_journal
    : false
  const configurationValide = !actif || racineId !== null

  const invalider = async () => {
    await queryClient.invalidateQueries({ queryKey: ['compta-creances-parametres'] })
    await queryClient.invalidateQueries({ queryKey: ['compta-referentiel'] })
  }

  const enregistrer = async () => {
    setEnCours(true)
    try {
      await enregistrerComptaCreancesParametres({
        actif,
        compte_racine_id: racineId,
        compte_racine_clients_id: racineClientsId,
        libelle_tiers: libelleTiers,
        libelle_journal: libelleJournal,
      })
      notifySuccess(
        'Créances',
        actif
          ? 'Les prochaines notes de débit constateront la créance.'
          : 'Les prochaines notes ne seront comptabilisées qu’à leur encaissement.'
      )
      setApercu(null)
      await invalider()
    } catch (error) {
      notifyError('Réglage refusé', error instanceof Error ? error.message : 'Impossible d’enregistrer.')
    } finally {
      setEnCours(false)
    }
  }

  const reprendre = async (simulation: boolean) => {
    setEnCours(true)
    try {
      const rapport = await reprendreComptaCreances(simulation)
      if (simulation) {
        setApercu(rapport)
      } else {
        setApercu(null)
        notifySuccess(
          'Créances constatées',
          `${rapport.constatees} notes, ${montant(rapport.montant)} au débit des comptes individuels.`
        )
        await invalider()
      }
    } catch (error) {
      notifyError('Reprise refusée', error instanceof Error ? error.message : 'La reprise a échoué.')
    } finally {
      setEnCours(false)
    }
  }

  return (
    <section className={styles.section}>
      <header className={styles.sectionHeader}>
        <div className={styles.sectionTitle}>
          <span className={styles.sectionIcon}><ReceiptText size={18} /></span>
          <div>
            <span className={styles.eyebrow}>Comptabilité d’engagement</span>
            <h3>Créances des tiers</h3>
            <p>
              Constater le produit dès la note de débit, puis solder le compte du tiers au règlement.
            </p>
          </div>
        </div>
        {parametres && (
          <span className={`${styles.statusBadge} ${parametres.actif ? styles.statusActive : styles.statusInactive}`}>
            {parametres.actif ? 'Activé' : 'À l’encaissement'}
          </span>
        )}
      </header>

      {parametres && (
        <div className={styles.stats}>
          <div>
            <Users size={17} />
            <span>Comptes individuels</span>
            <strong>{parametres.comptes_tiers}</strong>
          </div>
          <div>
            <ReceiptText size={17} />
            <span>Notes sans écriture</span>
            <strong>{parametres.notes_sans_creance}</strong>
          </div>
          <div>
            <Landmark size={17} />
            <span>Journal</span>
            <strong>{parametres.libelle_journal}</strong>
          </div>
        </div>
      )}

      <div className={`${styles.banner} ${styles.bannerInfo}`}>
        <Users size={18} className={styles.bannerIcon} />
        <div>
          <strong>Un compte par tiers</strong>
          <p>
            Le journal {parametres?.libelle_journal || 'Adhérents'} débite le compte du tiers et crédite les
            produits. Les comptes s’ouvrent automatiquement sous la racine choisie ; les anciennes notes restent
            comptabilisées à l’encaissement tant qu’aucune reprise n’est lancée.
          </p>
        </div>
      </div>

      {parametres && actif && !parametres.mode_automatique && (
        <div className={`${styles.banner} ${styles.bannerWarning}`}>
          <AlertTriangle size={18} className={styles.bannerIcon} />
          <div>
            <strong>Sans effet pour l’instant</strong>
            <p>
              La comptabilité n’est pas en génération automatique : aucune écriture de créance ne
              sera produite tant que ce mode n’est pas choisi dans les réglages.
            </p>
          </div>
        </div>
      )}

      {parametresQuery.isLoading ? (
        <div className={styles.loadingState}>Chargement…</div>
      ) : parametresQuery.isError ? (
        <div className={styles.errorState} role="alert">
          <AlertCircle size={18} />
          <span>Le paramétrage des créances n’a pas pu être chargé.</span>
          <button type="button" onClick={() => parametresQuery.refetch()}>Réessayer</button>
        </div>
      ) : (
        <form
          className={styles.formTaux}
          onSubmit={e => {
            e.preventDefault()
            void enregistrer()
          }}
        >
          <div className={styles.champTaux}>
            <label htmlFor="creances-actif">Constater les créances</label>
            <select
              id="creances-actif"
              value={actif ? 'oui' : 'non'}
              disabled={!canParametrer}
              onChange={e => setActif(e.target.value === 'oui')}
            >
              <option value="non">Non — à l’encaissement</option>
              <option value="oui">Oui — à l’émission de la note</option>
            </select>
            <small>Ce choix modifie la date d’entrée du produit en comptabilité.</small>
          </div>
          <div className={styles.champTaux}>
            <label htmlFor="creances-racine">Compte racine des {tiersPluriel}</label>
            <CompteSelect
              id="creances-racine"
              comptes={comptesTiers}
              value={racineId}
              disabled={!canParametrer}
              allowCollectif
              onChange={setRacineId}
            />
            {actif && racineId === null && <small className={styles.fieldError}>Obligatoire lorsque le mode est activé.</small>}
          </div>
          <div className={styles.champTaux}>
            <label htmlFor="creances-racine-clients">Compte racine des autres clients (vide : le même)</label>
            <select
              id="creances-racine-clients"
              value={racineClientsId ?? ''}
              disabled={!canParametrer}
              onChange={e => setRacineClientsId(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">Le même compte racine</option>
              {comptesTiers.map(c => (
                <option key={c.id} value={c.id}>
                  {c.numero} — {c.libelle}
                </option>
              ))}
            </select>
          </div>
          <div className={styles.champTaux}>
            <label htmlFor="creances-libelle-tiers">Nom donné aux membres de l’organisation</label>
            <input
              id="creances-libelle-tiers"
              type="text"
              maxLength={40}
              placeholder="membre, adhérent, client, tiers…"
              value={libelleTiers}
              disabled={!canParametrer}
              onChange={e => setLibelleTiers(e.target.value)}
            />
          </div>
          <div className={styles.champTaux}>
            <label htmlFor="creances-libelle-journal">Nom du journal</label>
            <input
              id="creances-libelle-journal"
              type="text"
              maxLength={100}
              placeholder="Adhérents, Créances, Ventes…"
              value={libelleJournal}
              disabled={!canParametrer}
              onChange={e => setLibelleJournal(e.target.value)}
            />
          </div>
          {canParametrer && (
            <button
              type="submit"
              className={styles.bannerAction}
              disabled={enCours || !modifie || !configurationValide}
            >
              <Save size={15} />
              Enregistrer
            </button>
          )}
        </form>
      )}

      {canParametrer && parametres?.actif && parametres.mode_automatique && parametres.notes_sans_creance > 0 && (
        <div className={`${styles.banner} ${styles.bannerWarning} ${styles.recoveryBanner}`}>
          <AlertTriangle size={18} className={styles.bannerIcon} />
          <div>
            <strong>Notes émises avant l’activation</strong>
            <p>
              Leur créance peut être constatée maintenant, à la date de chaque note. Une note déjà
              réglée en partie est laissée telle quelle : son règlement est déjà passé en produit.
            </p>
            {apercu && (
              <p>
                <strong>{apercu.constatees}</strong> notes seraient constatées pour{' '}
                <strong>{montant(apercu.montant)}</strong> ; {apercu.deja_reglees_en_partie} déjà réglées en
                partie sont laissées ; {apercu.echecs.length} refusées
                {apercu.echecs.length > 0 && ` (${apercu.echecs[0].numero} : ${apercu.echecs[0].motif})`}.
              </p>
            )}
          </div>
          {apercu && apercu.constatees > 0 ? (
            <button type="button" className={styles.bannerAction} disabled={enCours} onClick={() => reprendre(false)}>
              Constater ces {apercu.constatees} créances
            </button>
          ) : (
            <button type="button" className={styles.bannerAction} disabled={enCours} onClick={() => reprendre(true)}>
              Voir ce qui serait constaté
            </button>
          )}
        </div>
      )}
    </section>
  )
}
