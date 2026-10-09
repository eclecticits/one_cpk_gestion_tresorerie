import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { FileSpreadsheet, FileText, RefreshCw } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import {
  FONDS_TIERS_STATUT_LABELS,
  fondsTiersDisponible,
  listFondsTiers,
  type FondsTiersOperation,
} from '../api/mouvementsHorsBudget'
import { toNumber } from '../utils/amount'
import {
  createReportListSheet,
  jourExcel,
  telechargerClasseur,
} from '../utils/reportExcelStyles'
import { useAuth } from '../contexts/AuthContext'
import { usePermissions } from '../hooks/usePermissions'
import styles from './FondsTiers.module.css'

type XlsxModule = typeof import('xlsx')
let xlsxModulePromise: Promise<XlsxModule> | null = null
async function loadXlsxModule(): Promise<XlsxModule> {
  if (!xlsxModulePromise) {
    xlsxModulePromise = import('xlsx').then((importedModule) => {
      const compatibleModule = importedModule as XlsxModule & { default?: XlsxModule }
      return compatibleModule.utils ? compatibleModule : compatibleModule.default || compatibleModule
    })
  }
  return xlsxModulePromise
}

type PdfGeneratorReportsModule = typeof import('../utils/pdfGeneratorReports')
let pdfGeneratorReportsModulePromise: Promise<PdfGeneratorReportsModule> | null = null
function loadPdfGeneratorReportsModule(): Promise<PdfGeneratorReportsModule> {
  if (!pdfGeneratorReportsModulePromise) {
    pdfGeneratorReportsModulePromise = import('../utils/pdfGeneratorReports')
  }
  return pdfGeneratorReportsModulePromise
}

/**
 * Argent détenu pour le compte d'autrui.
 *
 * Ces fonds sont entrés en trésorerie sans jamais appartenir à l'organisation :
 * ils n'ont alimenté aucun poste budgétaire et doivent repartir. L'écran répond
 * donc à une seule question — combien reste-t-il à reverser, et à qui.
 */

const formatMontant = (valeur: unknown, devise: string) =>
  new Intl.NumberFormat('fr-FR', {
    style: 'currency',
    currency: devise === 'CDF' ? 'CDF' : 'USD',
  }).format(toNumber(valeur as any) || 0)

type FiltreStatut = 'A_REVERSER' | 'TOUS' | FondsTiersOperation['statut']

const FILTRES: [FiltreStatut, string][] = [
  ['A_REVERSER', 'À reverser'],
  ['REGULARISE', 'Soldés'],
  ['ANNULE', 'Annulés'],
  ['TOUS', 'Tous'],
]

const typeTiersLabel = (type: FondsTiersOperation['tiers_type']) =>
  type === 'ORGANISATION' ? 'Tenant ONEC' : type === 'EXTERNE' ? 'Tiers externe' : 'Historique'

const dateFichier = () => {
  const date = new Date()
  const mois = String(date.getMonth() + 1).padStart(2, '0')
  const jour = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${mois}-${jour}`
}

const estAReverser = (op: FondsTiersOperation) =>
  (op.statut === 'OUVERT' || op.statut === 'PARTIELLEMENT_REMBOURSE') && fondsTiersDisponible(op) > 0

export default function FondsTiers() {
  const [operations, setOperations] = useState<FondsTiersOperation[]>([])
  const [chargement, setChargement] = useState(true)
  const [erreur, setErreur] = useState<string | null>(null)
  const [exportErreur, setExportErreur] = useState<string | null>(null)
  const [exportEnCours, setExportEnCours] = useState<'pdf' | 'excel' | null>(null)
  const [filtre, setFiltre] = useState<FiltreStatut>('A_REVERSER')
  // Fonds cochés pour un versement groupé. Le versement passe par une
  // réquisition « Fonds de tiers » qui les nomme ; c'est elle qui désigne
  // l'instance destinataire, pas forcément celle pour qui l'argent a été reçu.
  const [selection, setSelection] = useState<Set<string>>(() => new Set())
  const navigate = useNavigate()
  const { user } = useAuth()
  const { hasPermission } = usePermissions()
  const peutVerser = hasPermission('requisitions') || hasPermission('services')

  const charger = useCallback(async () => {
    setChargement(true)
    setErreur(null)
    try {
      setOperations(await listFondsTiers())
    } catch (e: any) {
      setErreur(e?.message || 'Impossible de charger les fonds de tiers.')
      setOperations([])
    } finally {
      setChargement(false)
    }
  }, [])

  useEffect(() => {
    charger()
  }, [charger])

  // Un fonds soldé ou disparu au rechargement ne reste pas coché en silence.
  useEffect(() => {
    setSelection((prev) => {
      const valides = new Set(operations.filter(estAReverser).map((op) => String(op.id)))
      const next = new Set([...prev].filter((id) => valides.has(id)))
      return next.size === prev.size ? prev : next
    })
  }, [operations])

  const selectionnes = useMemo(
    () => operations.filter((op) => selection.has(String(op.id))),
    [operations, selection],
  )
  // Un versement ne mélange pas les devises : la première cochée l'impose.
  const deviseSelection = selectionnes[0]?.devise ?? null
  const totalSelection = useMemo(
    () => selectionnes.reduce((sum, op) => sum + fondsTiersDisponible(op), 0),
    [selectionnes],
  )

  const basculer = (op: FondsTiersOperation) => {
    const id = String(op.id)
    setSelection((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const verserSelection = () => {
    if (selectionnes.length === 0) return
    const ids = selectionnes.map((op) => op.id).join(',')
    navigate(`/requisitions/nouvelle?fonds_tiers=${encodeURIComponent(ids)}`)
  }

  const visibles = useMemo(() => {
    if (filtre === 'TOUS') return operations
    if (filtre === 'A_REVERSER') {
      return operations.filter((op) => op.statut === 'OUVERT' || op.statut === 'PARTIELLEMENT_REMBOURSE')
    }
    return operations.filter((op) => op.statut === filtre)
  }, [operations, filtre])

  // Un total par devise : additionner des dollars et des francs ne dirait rien.
  const soldesParDevise = useMemo(() => {
    const cumul = new Map<string, number>()
    operations
      .filter((op) => op.statut === 'OUVERT' || op.statut === 'PARTIELLEMENT_REMBOURSE')
      .forEach((op) => {
        cumul.set(op.devise, (cumul.get(op.devise) || 0) + (toNumber(op.solde_restant) || 0))
      })
    return Array.from(cumul.entries())
  }, [operations])

  const filtreLabel = FILTRES.find(([valeur]) => valeur === filtre)?.[1] || filtre
  const suffixeExport = `${filtre.toLowerCase()}_${dateFichier()}`

  const exporterExcel = async () => {
    if (exportEnCours || visibles.length === 0) return
    setExportEnCours('excel')
    setExportErreur(null)
    try {
      const XLSX = await loadXlsxModule()
      const organisation = user?.organisation_name || user?.organisation_slug || 'ONEC'
      const genereLe = new Intl.DateTimeFormat('fr-FR', {
        dateStyle: 'short',
        timeStyle: 'short',
      }).format(new Date())
      const rows = visibles.map((op) => [
        op.tiers_display_name,
        typeTiersLabel(op.tiers_type),
        op.beneficiaire_reel || '—',
        op.payeur_origine || '—',
        op.motif || '—',
        op.reference || '—',
        toNumber(op.montant_recu),
        op.devise,
        toNumber(op.montant_rembourse),
        toNumber(op.montant_reserve),
        toNumber(op.solde_restant),
        FONDS_TIERS_STATUT_LABELS[op.statut],
        jourExcel(op.created_at),
      ])
      // Comme le bandeau de l'écran : seuls les dossiers ouverts restent à
      // reverser (un dossier annulé garde un solde égal au montant reçu).
      const soldesExportes = new Map<string, number>()
      visibles
        .filter((op) => op.statut === 'OUVERT' || op.statut === 'PARTIELLEMENT_REMBOURSE')
        .forEach((op) => {
          soldesExportes.set(
            op.devise,
            (soldesExportes.get(op.devise) || 0) + toNumber(op.solde_restant),
          )
        })
      const sheet = createReportListSheet(XLSX, {
        title: 'ÉTAT DES FONDS DE TIERS',
        organisation,
        subtitle: `Filtre : ${filtreLabel} | Généré le ${genereLe}`,
        headers: [
          'Tiers',
          'Type de tiers',
          'Bénéficiaire réel',
          "Payeur d'origine",
          'Motif',
          'Référence',
          'Reçu',
          'Devise',
          'Reversé',
          'Réservé',
          'Reste',
          'Statut',
          'Reçu le',
        ],
        rows,
        widths: [30, 18, 28, 28, 34, 20, 16, 10, 16, 16, 16, 24, 14],
        moneyColumns: [6, 8, 9, 10],
        wrapColumns: [0, 2, 3, 4],
        centerColumns: [1, 7, 11],
        dateColumns: [12],
        summaryCards: [
          { label: 'Dossiers exportés', value: visibles.length, format: 'integer', tone: 'accent' },
          ...Array.from(soldesExportes.entries()).map(([devise, total]) => ({
            label: `Reste à reverser (${devise})`,
            value: total,
            format: 'money' as const,
            tone: total > 0 ? ('warning' as const) : ('positive' as const),
          })),
        ],
      })
      const workbook = XLSX.utils.book_new()
      workbook.Props = {
        Title: 'État des fonds de tiers',
        Subject: `Filtre : ${filtreLabel}`,
        Author: organisation,
        Company: organisation,
      }
      XLSX.utils.book_append_sheet(workbook, sheet, 'Fonds de tiers')
      telechargerClasseur(XLSX, workbook, `fonds_tiers_${suffixeExport}.xlsx`)
    } catch (error) {
      console.error("Erreur lors de l'export Excel des fonds de tiers :", error)
      setExportErreur("Impossible de générer l'export Excel des fonds de tiers.")
    } finally {
      setExportEnCours(null)
    }
  }

  const exporterPDF = async () => {
    if (exportEnCours || visibles.length === 0) return
    setExportEnCours('pdf')
    setExportErreur(null)
    try {
      const { generateFondsTiersReportPDF } = await loadPdfGeneratorReportsModule()
      await generateFondsTiersReportPDF(visibles, {
        filters: [{ label: 'Statut', value: filtreLabel }],
        fileName: `fonds_tiers_${suffixeExport}.pdf`,
      })
    } catch (error) {
      console.error("Erreur lors de l'export PDF des fonds de tiers :", error)
      setExportErreur("Impossible de générer l'export PDF des fonds de tiers.")
    } finally {
      setExportEnCours(null)
    }
  }

  return (
    <div className={styles.page}>
      <PageHeader
        title="Fonds de tiers"
        subtitle="Argent encaissé pour le compte d'un tiers : présent en trésorerie, absent du budget, à reverser."
        actions={
          <div className={styles.headerActions}>
            <Link to="/sorties-fonds/nouvelle" className={styles.primaryLink}>
              Reverser des fonds
            </Link>
            <button
              type="button"
              className={styles.exportBtn}
              onClick={exporterPDF}
              disabled={chargement || visibles.length === 0 || exportEnCours !== null}
              title="Exporter la liste affichée au format PDF"
            >
              <FileText size={16} aria-hidden="true" />
              {exportEnCours === 'pdf' ? 'PDF…' : 'PDF'}
            </button>
            <button
              type="button"
              className={styles.exportBtn}
              onClick={exporterExcel}
              disabled={chargement || visibles.length === 0 || exportEnCours !== null}
              title="Exporter la liste affichée au format Excel"
            >
              <FileSpreadsheet size={16} aria-hidden="true" />
              {exportEnCours === 'excel' ? 'Excel…' : 'Excel'}
            </button>
            <button
              type="button"
              className={styles.iconBtn}
              onClick={charger}
              disabled={chargement}
              aria-label={chargement ? 'Actualisation en cours' : 'Rafraîchir les fonds de tiers'}
              title="Rafraîchir"
            >
              <RefreshCw size={16} aria-hidden="true" />
            </button>
          </div>
        }
      />

      <section className={styles.summary} aria-label="Synthèse des fonds de tiers" aria-live="polite">
        {soldesParDevise.length === 0 ? (
          <div className={styles.summaryCard}>
            <span className={styles.summaryLabel}>Reste à reverser</span>
            <strong className={styles.summaryValue}>Aucun</strong>
          </div>
        ) : (
          soldesParDevise.map(([devise, total]) => (
            <div key={devise} className={styles.summaryCard}>
              <span className={styles.summaryLabel}>Reste à reverser ({devise})</span>
              <strong className={styles.summaryValue}>{formatMontant(total, devise)}</strong>
            </div>
          ))
        )}
        <div className={styles.summaryCard}>
          <span className={styles.summaryLabel}>Dossiers ouverts</span>
          <strong className={styles.summaryValue}>
            {operations.filter((op) => op.statut === 'OUVERT' || op.statut === 'PARTIELLEMENT_REMBOURSE').length}
          </strong>
        </div>
      </section>

      <div className={styles.filters} role="group" aria-label="Filtrer les fonds de tiers par statut">
        {FILTRES.map(([valeur, label]) => (
          <button
            key={valeur}
            type="button"
            aria-pressed={filtre === valeur}
            className={`${styles.filterBtn} ${filtre === valeur ? styles.filterBtnActive : ''}`}
            onClick={() => setFiltre(valeur)}
          >
            {label}
          </button>
        ))}
      </div>

      {erreur && <div className={styles.error} role="alert">{erreur}</div>}
      {exportErreur && <div className={styles.error} role="alert">{exportErreur}</div>}

      {peutVerser && (
        <div className={styles.selectionBar} aria-live="polite">
          <span className={styles.selectionInfo}>
            {selectionnes.length === 0
              ? 'Cochez un ou plusieurs fonds pour les verser en une fois à une instance.'
              : `${selectionnes.length} fonds sélectionné${selectionnes.length > 1 ? 's' : ''} · ${formatMontant(totalSelection, deviseSelection || 'USD')}`}
          </span>
          {selectionnes.length > 0 && (
            <button type="button" className={styles.secondaryBtn} onClick={() => setSelection(new Set())}>
              Effacer
            </button>
          )}
          <button
            type="button"
            className={styles.primaryBtn}
            onClick={verserSelection}
            disabled={selectionnes.length === 0}
          >
            Verser la sélection
          </button>
        </div>
      )}

      <div className={styles.tableWrap} aria-busy={chargement}>
        <table className={styles.table}>
          <caption className={styles.srOnly}>Opérations de fonds détenus pour le compte de tiers</caption>
          <thead>
            <tr>
              <th>Tiers</th>
              <th>Bénéficiaire réel</th>
              <th>Payeur d'origine</th>
              <th>Reçu</th>
              <th>Reversé</th>
              <th>Reste</th>
              <th>Statut</th>
              <th>Reçu le</th>
              <th><span className={styles.srOnly}>Action</span></th>
            </tr>
          </thead>
          <tbody>
            {chargement ? (
              <tr>
                <td colSpan={9} className={styles.empty}>Chargement…</td>
              </tr>
            ) : visibles.length === 0 ? (
              <tr>
                <td colSpan={9} className={styles.empty}>
                  {filtre === 'A_REVERSER'
                    ? 'Aucun fonds de tiers en attente de reversement.'
                    : 'Aucun fonds de tiers pour ce filtre.'}
                </td>
              </tr>
            ) : (
              visibles.map((op) => (
                <tr key={op.id}>
                  <td data-label="Tiers">
                    <div className={styles.tiersCell}>
                    {peutVerser && estAReverser(op) && (
                      <input
                        type="checkbox"
                        className={styles.rowCheck}
                        checked={selection.has(String(op.id))}
                        disabled={!!deviseSelection && op.devise !== deviseSelection && !selection.has(String(op.id))}
                        onChange={() => basculer(op)}
                        aria-label={`Sélectionner les fonds de ${op.tiers_display_name} pour un versement`}
                        title={
                          deviseSelection && op.devise !== deviseSelection
                            ? `Fonds en ${op.devise} : versement séparé`
                            : undefined
                        }
                      />
                    )}
                    <div>
                    <strong>{op.tiers_display_name}</strong>
                    <div className={styles.sub}>
                      {typeTiersLabel(op.tiers_type)}
                    </div>
                    {op.motif && <div className={styles.sub}>{op.motif}</div>}
                    {toNumber(op.montant_reserve) > 0 && (
                      <div className={styles.reserve}>
                        Réservé {formatMontant(op.montant_reserve, op.devise)}
                        {op.requisitions_en_cours?.length ? ` · ${op.requisitions_en_cours.join(', ')}` : ''}
                      </div>
                    )}
                    </div>
                    </div>
                  </td>
                  <td data-label="Bénéficiaire réel">{op.beneficiaire_reel || '—'}</td>
                  <td data-label="Payeur d'origine">{op.payeur_origine || '—'}</td>
                  <td data-label="Reçu">{formatMontant(op.montant_recu, op.devise)}</td>
                  <td data-label="Reversé">{formatMontant(op.montant_rembourse, op.devise)}</td>
                  <td data-label="Reste">
                    <strong className={toNumber(op.solde_restant) > 0 ? styles.soldeDu : styles.soldeNul}>
                      {formatMontant(op.solde_restant, op.devise)}
                    </strong>
                  </td>
                  <td data-label="Statut">
                    <span className={styles.statut} data-statut={op.statut}>
                      {FONDS_TIERS_STATUT_LABELS[op.statut]}
                    </span>
                  </td>
                  <td data-label="Reçu le">{new Date(op.created_at).toLocaleDateString('fr-FR')}</td>
                  <td data-label="Action">
                    {(op.statut === 'OUVERT' || op.statut === 'PARTIELLEMENT_REMBOURSE') && (
                      <Link
                        to={`/sorties-fonds/nouvelle?type_sortie=remboursement_fonds_tiers&fonds_tiers_operation_id=${op.id}`}
                        className={styles.primaryLink}
                      >
                        Rembourser
                      </Link>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
