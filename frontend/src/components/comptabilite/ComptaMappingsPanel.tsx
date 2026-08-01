import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Info, Wand2 } from 'lucide-react'
import {
  appliquerComptaMappingsDefaut,
  getComptaMappings,
  setComptaCaisseDefaut,
  setComptaMappingCompteBancaire,
  setComptaMappingPoste,
  setComptaMappingRubrique,
} from '../../api/comptabilite'
import { useToast } from '../../hooks/useToast'
import type { ComptaCompte } from '../../types/comptabilite'
import CompteSelect from './CompteSelect'
import styles from './ComptaMappingsPanel.module.css'

interface Props {
  comptes: ComptaCompte[]
  canParametrer: boolean
}

/**
 * Paramétrage des mappings comptables.
 *
 * Le moteur de génération ne contient aucun numéro de compte : il résout tout
 * via ces mappings, et une résolution manquante BLOQUE l'opération métier
 * (sortie de fonds, encaissement, paie). Cet écran est donc le point de
 * contrôle avant mise en service — d'où le bandeau d'alerte permanent tant
 * qu'il reste des lignes non mappées.
 */
export default function ComptaMappingsPanel({ comptes, canParametrer }: Props) {
  const queryClient = useQueryClient()
  const { notifyError, notifySuccess } = useToast()
  const [ligneEnCours, setLigneEnCours] = useState<string | null>(null)

  const mappingsQuery = useQuery({
    queryKey: ['compta-mappings'],
    queryFn: () => getComptaMappings(),
  })

  const mappings = mappingsQuery.data

  const invalider = () => queryClient.invalidateQueries({ queryKey: ['compta-mappings'] })

  const enregistrer = async (cle: string, action: () => Promise<unknown>) => {
    setLigneEnCours(cle)
    try {
      await action()
      await invalider()
      notifySuccess('Mapping enregistré', 'Les prochaines écritures utiliseront ce compte.')
    } catch (err: any) {
      notifyError('Mapping refusé', err?.message || 'Impossible d’enregistrer ce mapping.')
    } finally {
      setLigneEnCours(null)
    }
  }

  const defautMutation = useMutation({
    mutationFn: appliquerComptaMappingsDefaut,
    onSuccess: async result => {
      await invalider()
      const total =
        result.postes_mappes + result.comptes_bancaires_mappes + result.rubriques_mappees
      notifySuccess(
        total > 0 ? `${total} mapping(s) complété(s)` : 'Rien à compléter',
        total > 0
          ? 'Comptes génériques appliqués aux lignes qui n’étaient pas encore mappées — affinez-les ci-dessous.'
          : 'Toutes les lignes étaient déjà mappées.'
      )
    },
    onError: (err: any) =>
      notifyError('Échec', err?.message || 'Impossible d’appliquer les mappings par défaut.'),
  })

  if (mappingsQuery.isLoading) {
    return <div className={styles.loadingState}>Chargement du paramétrage…</div>
  }

  if (mappingsQuery.isError || !mappings) {
    return (
      <div className={styles.errorState}>
        Impossible de charger le paramétrage comptable.
      </div>
    )
  }

  const disabled = !canParametrer

  return (
    <div className={styles.panel}>
      {mappings.nb_non_mappes > 0 ? (
        <div className={`${styles.banner} ${styles.bannerWarning}`}>
          <AlertTriangle size={18} className={styles.bannerIcon} />
          <div>
            <strong>
              {mappings.nb_non_mappes} élément{mappings.nb_non_mappes > 1 ? 's' : ''} non mappé
              {mappings.nb_non_mappes > 1 ? 's' : ''}
            </strong>
            <p>
              Toute opération qui utilise l’un d’eux sera <strong>refusée</strong> : la sortie de
              fonds, l’encaissement ou le run de paie concerné échouera tant que le compte n’est pas
              renseigné.
            </p>
          </div>
          {canParametrer && (
            <button
              type="button"
              className={styles.bannerAction}
              onClick={() => defautMutation.mutate()}
              disabled={defautMutation.isPending}
            >
              <Wand2 size={15} />
              {defautMutation.isPending ? 'Application…' : 'Compléter par défaut'}
            </button>
          )}
        </div>
      ) : (
        <div className={`${styles.banner} ${styles.bannerOk}`}>
          <CheckCircle2 size={18} className={styles.bannerIcon} />
          <div>
            <strong>Paramétrage complet</strong>
            <p>Toutes les opérations peuvent être comptabilisées automatiquement.</p>
          </div>
        </div>
      )}

      {!canParametrer && (
        <div className={`${styles.banner} ${styles.bannerInfo}`}>
          <Info size={18} className={styles.bannerIcon} />
          <div>
            <strong>Lecture seule</strong>
            <p>La permission « compta.parametrage » est requise pour modifier ces mappings.</p>
          </div>
        </div>
      )}

      {/* ── Postes budgétaires ─────────────────────────────────────────── */}
      <section className={styles.section}>
        <header className={styles.sectionHeader}>
          <h3>
            Postes budgétaires
            {mappings.budget_exercice_annee ? ` — exercice ${mappings.budget_exercice_annee}` : ''}
          </h3>
          <p>
            Compte de charge ou de produit utilisé lorsqu’une opération est imputée sur ce poste.
          </p>
        </header>

        <div className={`${styles.banner} ${styles.bannerInfo} ${styles.sectionNote}`}>
          <Info size={18} className={styles.bannerIcon} />
          <div>
            <strong>Poste « salaires » : mappez-le sur la dette envers le personnel (42x)</strong>
            <p>
              La validation d’un run de paie constate déjà la charge (66x). Si le poste utilisé pour
              verser les salaires pointe sur un compte de charge, celle-ci serait comptabilisée{' '}
              <strong>deux fois</strong>. Sur un compte 42x, le versement solde la dette.
            </p>
          </div>
        </div>

        {mappings.postes.length === 0 ? (
          <div className={styles.emptyState}>
            Aucun poste budgétaire actif sur cet exercice.
          </div>
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Code</th>
                <th>Libellé</th>
                <th>Type</th>
                <th>Compte comptable</th>
              </tr>
            </thead>
            <tbody>
              {mappings.postes.map(poste => {
                const cle = `poste-${poste.budget_poste_id}`
                return (
                  <tr
                    key={cle}
                    className={poste.compte_id === null ? styles.rowManquant : undefined}
                  >
                    <td className={styles.codeCell}>{poste.code}</td>
                    <td>{poste.libelle}</td>
                    <td className={styles.typeCell}>{poste.type || '—'}</td>
                    <td>
                      <CompteSelect
                        id={`compte-${cle}`}
                        comptes={comptes}
                        value={poste.compte_id}
                        disabled={disabled || ligneEnCours === cle}
                        onChange={compteId =>
                          enregistrer(cle, () =>
                            setComptaMappingPoste(poste.budget_poste_id, compteId)
                          )
                        }
                      />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </section>

      {/* ── Trésorerie ─────────────────────────────────────────────────── */}
      <section className={styles.section}>
        <header className={styles.sectionHeader}>
          <h3>Trésorerie</h3>
          <p>Compte 512x / 571 mouvementé par les encaissements, décaissements et transferts.</p>
        </header>

        <table className={styles.table}>
          <thead>
            <tr>
              <th>Compte</th>
              <th>Numéro</th>
              <th>Devise</th>
              <th>Compte comptable</th>
            </tr>
          </thead>
          <tbody>
            <tr className={mappings.caisse_defaut_compte_id === null ? styles.rowManquant : undefined}>
              <td className={styles.codeCell}>Caisse centrale</td>
              <td className={styles.typeCell}>caisse unique de l’organisation</td>
              <td className={styles.typeCell}>—</td>
              <td>
                <CompteSelect
                  id="compte-caisse-defaut"
                  comptes={comptes}
                  value={mappings.caisse_defaut_compte_id}
                  disabled={disabled || ligneEnCours === 'caisse-defaut'}
                  onChange={compteId =>
                    enregistrer('caisse-defaut', () => setComptaCaisseDefaut(compteId))
                  }
                />
              </td>
            </tr>
            {mappings.comptes_bancaires.map(banque => {
              const cle = `banque-${banque.compte_bancaire_id}`
              return (
                <tr
                  key={cle}
                  className={banque.compte_id === null ? styles.rowManquant : undefined}
                >
                  <td className={styles.codeCell}>{banque.intitule}</td>
                  <td className={styles.typeCell}>{banque.numero_compte || '—'}</td>
                  <td className={styles.typeCell}>{banque.devise || '—'}</td>
                  <td>
                    <CompteSelect
                      id={`compte-${cle}`}
                      comptes={comptes}
                      value={banque.compte_id}
                      disabled={disabled || ligneEnCours === cle}
                      onChange={compteId =>
                        enregistrer(cle, () =>
                          setComptaMappingCompteBancaire(banque.compte_bancaire_id, compteId)
                        )
                      }
                    />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </section>

      {/* ── Rubriques techniques ───────────────────────────────────────── */}
      <section className={styles.section}>
        <header className={styles.sectionHeader}>
          <h3>Rubriques techniques</h3>
          <p>
            Opérations qui n’ont ni poste budgétaire ni compte de trésorerie à mapper : paie et
            encaissements par paiement en ligne.
          </p>
        </header>

        <table className={styles.table}>
          <thead>
            <tr>
              <th>Rubrique</th>
              <th>Rôle</th>
              <th>Compte comptable</th>
            </tr>
          </thead>
          <tbody>
            {mappings.rubriques.map(rubrique => {
              const cle = `rubrique-${rubrique.code_rubrique}`
              return (
                <tr
                  key={cle}
                  className={rubrique.compte_id === null ? styles.rowManquant : undefined}
                >
                  <td className={styles.codeCell}>{rubrique.libelle}</td>
                  <td className={styles.descriptionCell}>{rubrique.description}</td>
                  <td>
                    <CompteSelect
                      id={`compte-${cle}`}
                      comptes={comptes}
                      value={rubrique.compte_id}
                      disabled={disabled || ligneEnCours === cle}
                      onChange={compteId =>
                        enregistrer(cle, () =>
                          setComptaMappingRubrique(rubrique.code_rubrique, compteId)
                        )
                      }
                    />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </section>
    </div>
  )
}
