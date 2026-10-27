import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Download, FileSpreadsheet, RefreshCw } from 'lucide-react'
import { listComptesBancaires } from '../../api/banques'
import {
  downloadComptaExport,
  getComptaExportApercu,
  getComptaExportHistorique,
} from '../../api/comptabilite'
import type {
  ComptaExportAnomalie,
  ComptaExportFiltres,
  ComptaFormatExport,
  ComptaJournalExport,
} from '../../types/comptabilite'
import { toNumber } from '../../utils/amount'
import { useToast } from '../../hooks/useToast'
import styles from './ComptaExportsPanel.module.css'


function isoDate(value: Date): string {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function montant(value: string | number, devise: string): string {
  return `${new Intl.NumberFormat('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(toNumber(value))} ${devise}`
}

function jour(value: string): string {
  const [annee, mois, j] = value.slice(0, 10).split('-')
  return annee && mois && j ? `${j}/${mois}/${annee}` : value
}

interface GroupeAnomalies {
  code: string
  bloquante: boolean
  message: string
  nombre: number
  numeros: string[]
}

// Une même anomalie (compte inactif, écriture déjà exportée…) se répète sur
// des centaines d'écritures : on la montre une fois, avec les pièces visées.
function regrouper(anomalies: ComptaExportAnomalie[]): GroupeAnomalies[] {
  const groupes = new Map<string, GroupeAnomalies>()
  for (const anomalie of anomalies) {
    const cle = `${anomalie.bloquante ? 1 : 0}|${anomalie.code}`
    const groupe = groupes.get(cle) ?? {
      code: anomalie.code,
      bloquante: anomalie.bloquante,
      message: anomalie.message,
      nombre: 0,
      numeros: [],
    }
    groupe.nombre += 1
    if (anomalie.numero && !groupe.numeros.includes(anomalie.numero)) groupe.numeros.push(anomalie.numero)
    groupes.set(cle, groupe)
  }
  return [...groupes.values()].sort((a, b) => Number(b.bloquante) - Number(a.bloquante) || b.nombre - a.nombre)
}

const NUMEROS_AFFICHES = 8

interface Props {
  canExport: boolean
}

export default function ComptaExportsPanel({ canExport }: Props) {
  const now = new Date()
  const [dateDebut, setDateDebut] = useState(isoDate(new Date(now.getFullYear(), now.getMonth(), 1)))
  const [dateFin, setDateFin] = useState(isoDate(now))
  const [journal, setJournal] = useState<ComptaJournalExport>('TOUS')
  const [devise, setDevise] = useState<'USD' | 'CDF'>('USD')
  const [compteId, setCompteId] = useState<number | ''>('')
  const [formatControle, setFormatControle] = useState<ComptaFormatExport>('XLSX')
  const [autoriserReexport, setAutoriserReexport] = useState(false)
  const [downloading, setDownloading] = useState<string | null>(null)
  const { notifyError, notifySuccess } = useToast()
  const queryClient = useQueryClient()

  const comptesQuery = useQuery({
    queryKey: ['compta-export-comptes-bancaires'],
    queryFn: () => listComptesBancaires({ active: true, account_type: 'BANK' }),
    staleTime: 5 * 60_000,
  })
  const comptes = comptesQuery.data ?? []
  const comptesDevise = useMemo(() => comptes.filter(c => c.devise === devise), [comptes, devise])

  const filtres = useMemo<ComptaExportFiltres>(() => ({
    date_debut: dateDebut,
    date_fin: dateFin,
    journal,
    compte_bancaire_id: journal === 'BANQUE' && compteId !== '' ? Number(compteId) : null,
    devise,
    format: 'XLSX',
    autoriser_reexport: autoriserReexport,
  }), [autoriserReexport, compteId, dateDebut, dateFin, devise, journal])

  const apercuQuery = useQuery({
    queryKey: ['compta-export-apercu', filtres],
    queryFn: () => getComptaExportApercu(filtres),
    enabled: canExport && Boolean(dateDebut && dateFin),
  })
  const historiqueQuery = useQuery({
    queryKey: ['compta-export-historique'],
    queryFn: getComptaExportHistorique,
    enabled: canExport,
  })
  const apercu = apercuQuery.data
  const groupes = useMemo(() => regrouper(apercu?.anomalies ?? []), [apercu])

  const exporter = async (type: 'logiciel-comptable' | 'controle-bancaire') => {
    if (type === 'controle-bancaire' && (journal !== 'BANQUE' || compteId === '')) {
      notifyError('Compte requis', 'Sélectionnez le journal Banque et un compte bancaire précis.')
      return
    }
    setDownloading(type)
    try {
      const payload: ComptaExportFiltres = {
        ...filtres,
        journal: type === 'controle-bancaire' ? 'BANQUE' : filtres.journal,
        compte_bancaire_id: type === 'controle-bancaire' ? Number(compteId) : filtres.compte_bancaire_id,
        format: type === 'controle-bancaire' ? formatControle : 'XLSX',
      }
      const filename = await downloadComptaExport(type, payload)
      notifySuccess('Export généré', filename)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['compta-export-apercu'] }),
        queryClient.invalidateQueries({ queryKey: ['compta-export-historique'] }),
      ])
    } catch (error: any) {
      notifyError('Export impossible', error?.message || 'Une erreur est survenue.')
    } finally {
      setDownloading(null)
    }
  }

  if (!canExport) {
    return <div className={styles.empty}>La permission « Export comptable » est requise.</div>
  }

  return (
    <div className={styles.stack}>
      <section className={styles.panel}>
        <div className={styles.heading}>
          <div>
            <span className={styles.eyebrow}>Contrat logiciel validé</span>
            <h3>Préparer un export comptable</h3>
            <p><code>Date&gt;</code> · Pièce · Compte · Libellé · Débit · Crédit</p>
          </div>
          <button type="button" className={styles.refresh} onClick={() => apercuQuery.refetch()} disabled={apercuQuery.isFetching}>
            <RefreshCw size={15} /> Actualiser
          </button>
        </div>

        <div className={styles.filters}>
          <label>Du<input type="date" value={dateDebut} onChange={e => setDateDebut(e.target.value)} /></label>
          <label>Au<input type="date" value={dateFin} onChange={e => setDateFin(e.target.value)} /></label>
          <label>Journal<select value={journal} onChange={e => {
            const next = e.target.value as ComptaJournalExport
            setJournal(next)
            if (next !== 'BANQUE') setCompteId('')
          }}>
            <option value="TOUS">Caisse + Banque</option>
            <option value="CAISSE">Caisse</option>
            <option value="BANQUE">Banque</option>
          </select></label>
          {journal === 'BANQUE' && (
            <label>Compte bancaire<select value={compteId} onChange={e => setCompteId(e.target.value ? Number(e.target.value) : '')}>
              <option value="">Tous les comptes {devise}</option>
              {comptesDevise.map(compte => (
                <option key={compte.id} value={compte.id}>{compte.banque?.nom || 'Banque'} — {compte.intitule}</option>
              ))}
            </select></label>
          )}
          <label>Devise<select value={devise} onChange={e => {
            setDevise(e.target.value as 'USD' | 'CDF')
            setCompteId('')
          }}><option value="USD">USD</option><option value="CDF">CDF</option></select></label>
          <label>Format contrôle<select value={formatControle} onChange={e => setFormatControle(e.target.value as ComptaFormatExport)}>
            <option value="XLSX">Excel (.xlsx)</option>
            <option value="CSV">CSV UTF-8 (.csv)</option>
          </select></label>
        </div>

        {apercuQuery.isLoading ? <div className={styles.empty}>Contrôle des écritures…</div> : apercu ? (
          <>
            <div className={styles.metrics}>
              <div><span>Écritures</span><strong>{apercu.nombre_ecritures}</strong></div>
              <div><span>Lignes</span><strong>{apercu.nombre_lignes}</strong></div>
              <div><span>Total débit</span><strong>{montant(apercu.total_debit, devise)}</strong></div>
              <div><span>Total crédit</span><strong>{montant(apercu.total_credit, devise)}</strong></div>
              <div className={apercu.equilibre ? styles.metricOk : styles.metricDanger}>
                <span>Écart</span><strong>{montant(apercu.ecart, devise)}</strong>
              </div>
            </div>

            <div className={`${styles.status} ${apercu.exportable ? styles.statusOk : styles.statusBlocked}`}>
              {apercu.exportable ? <CheckCircle2 size={19} /> : <AlertTriangle size={19} />}
              <div><strong>{apercu.exportable ? 'Sélection exportable' : 'Export bloqué'}</strong>
                <span>{apercu.exportable ? 'Toutes les écritures sont complètes et équilibrées.' : 'Corrigez les anomalies bloquantes avant génération.'}</span>
              </div>
            </div>

            {groupes.length > 0 && (
              <div className={styles.anomalies}>
                {groupes.map(groupe => (
                  <div key={`${groupe.bloquante}-${groupe.code}`}>
                    <span className={groupe.bloquante ? styles.blocking : styles.warning}>
                      {groupe.bloquante ? 'Bloquant' : 'Avertissement'}
                    </span>
                    <strong>{groupe.nombre > 1 ? `${groupe.nombre} écritures` : groupe.numeros[0] || groupe.code}</strong>
                    <p>
                      {groupe.nombre > 1 ? `Premier cas : ${groupe.message}` : groupe.message}
                      {groupe.nombre > 1 && groupe.numeros.length > 0 && (
                        <small>
                          {groupe.numeros.slice(0, NUMEROS_AFFICHES).join(', ')}
                          {groupe.numeros.length > NUMEROS_AFFICHES && ` et ${groupe.numeros.length - NUMEROS_AFFICHES} autre(s)`}
                        </small>
                      )}
                    </p>
                  </div>
                ))}
              </div>
            )}

            {apercu.nombre_deja_exportees > 0 && (
              <label className={styles.reexport}>
                <input type="checkbox" checked={autoriserReexport} onChange={e => setAutoriserReexport(e.target.checked)} />
                Réexportation confirmée par le comptable ({apercu.nombre_deja_exportees} écriture(s) déjà incluse(s))
              </label>
            )}

            <div className={styles.actions}>
              <button type="button" className={styles.primary} disabled={!apercu.exportable || downloading !== null} onClick={() => exporter('logiciel-comptable')}>
                <FileSpreadsheet size={16} /> {downloading === 'logiciel-comptable' ? 'Génération…' : 'Exporter pour le logiciel comptable'}
              </button>
              <button type="button" className={styles.secondary} disabled={journal !== 'BANQUE' || compteId === '' || downloading !== null} onClick={() => exporter('controle-bancaire')}>
                <Download size={16} /> {downloading === 'controle-bancaire' ? 'Génération…' : 'Exporter le journal de contrôle'}
              </button>
            </div>
          </>
        ) : (
          <div className={styles.empty}>
            {(apercuQuery.error as Error | null)?.message || 'Impossible de charger l’aperçu.'}
          </div>
        )}
      </section>

      {apercu && apercu.lignes.length > 0 && (
        <section className={styles.panel}>
          <div className={styles.heading}><div><span className={styles.eyebrow}>Aperçu</span><h3>Écritures retenues</h3></div></div>
          <div className={styles.tableWrap}><table><thead><tr><th>Date</th><th>Pièce</th><th>Compte</th><th>Libellé</th><th>Débit</th><th>Crédit</th></tr></thead>
            <tbody>{apercu.lignes.slice(0, 100).map((ligne, index) => <tr key={`${ligne.ecriture_id}-${index}`}>
              <td>{jour(ligne.date)}</td><td>{ligne.piece}</td><td className={styles.mono}>{ligne.compte}</td><td>{ligne.libelle}</td>
              <td className={styles.amount}>{toNumber(ligne.debit) ? montant(ligne.debit, '') : '—'}</td>
              <td className={styles.amount}>{toNumber(ligne.credit) ? montant(ligne.credit, '') : '—'}</td>
            </tr>)}</tbody></table></div>
          {apercu.lignes.length > 100 && <p className={styles.caption}>100 premières lignes affichées sur {apercu.nombre_lignes}.</p>}
        </section>
      )}

      <section className={styles.panel}>
        <div className={styles.heading}><div><span className={styles.eyebrow}>Traçabilité</span><h3>Historique des exports</h3></div></div>
        <div className={styles.tableWrap}><table><thead><tr><th>Généré le</th><th>Type</th><th>Période</th><th>Journal</th><th>Devise</th><th>Écritures</th><th>Fichier</th></tr></thead>
          <tbody>{(historiqueQuery.data ?? []).map(item => <tr key={item.id}>
            <td>{new Date(item.created_at).toLocaleString('fr-FR')}</td><td>{item.type_export === 'LOGICIEL_COMPTABLE' ? 'Logiciel' : 'Contrôle bancaire'}</td>
            <td>{jour(item.date_debut)} → {jour(item.date_fin)}</td><td>{item.journal}</td><td>{item.devise}</td><td>{item.nombre_ecritures}</td><td className={styles.mono}>{item.nom_fichier}</td>
          </tr>)}</tbody></table>
          {!historiqueQuery.isLoading && (historiqueQuery.data?.length ?? 0) === 0 && <div className={styles.empty}>Aucun export généré.</div>}
        </div>
      </section>
    </div>
  )
}

