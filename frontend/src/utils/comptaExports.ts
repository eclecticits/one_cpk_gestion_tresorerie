/**
 * Exports des restitutions comptables (Balance, Grand Livre).
 *
 * Le PDF réutilise `buildListReport` — le même moteur que les rapports de
 * trésorerie — pour que les états comptables sortent avec l'en-tête, le logo
 * et la mise en page déjà validés par l'organisation. L'Excel suit le format
 * de la page Rapports (`XLSX.utils.aoa_to_sheet`).
 */

import * as XLSX from 'xlsx'
import { buildListReport } from './pdfGeneratorReports'
import { toNumber } from './amount'
import type { ComptaBalance, ComptaGrandLivre } from '../types/comptabilite'

function formatMontant(value: string | number): string {
  const n = toNumber(value)
  if (n === 0) return ''
  return new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n)
}

function periodeFiltre(balance: { date_debut: string | null; date_fin: string | null }) {
  if (!balance.date_debut && !balance.date_fin) return null
  return {
    label: 'Période',
    value: `${balance.date_debut || '…'} → ${balance.date_fin || '…'}`,
  }
}

/** Signale sur l'état lui-même qu'il inclut des brouillons : imprimé, il ne
 *  porterait plus l'avertissement affiché à l'écran. */
function simulationFiltre(inclureBrouillons: boolean) {
  return inclureBrouillons
    ? { label: 'Nature', value: 'SIMULATION — brouillons inclus' }
    : null
}

export async function exportBalancePDF(balance: ComptaBalance): Promise<void> {
  await buildListReport({
    title: 'Balance générale',
    footerLabel: 'Balance générale',
    columns: [
      { header: 'Compte', width: 24 },
      { header: 'Libellé', width: 90 },
      { header: 'Débit', width: 34, halign: 'right' },
      { header: 'Crédit', width: 34, halign: 'right' },
      { header: 'Solde débiteur', width: 34, halign: 'right' },
      { header: 'Solde créditeur', width: 34, halign: 'right' },
    ],
    rows: balance.lignes.map(l => [
      l.compte_numero,
      l.compte_libelle,
      formatMontant(l.total_debit),
      formatMontant(l.total_credit),
      formatMontant(l.solde_debiteur),
      formatMontant(l.solde_crediteur),
    ]),
    footRow: [
      'TOTAL',
      '',
      formatMontant(balance.total_debit),
      formatMontant(balance.total_credit),
      formatMontant(balance.total_solde_debiteur),
      formatMontant(balance.total_solde_crediteur),
    ],
    summary: [
      { label: 'Comptes mouvementés', value: String(balance.lignes.length) },
      { label: 'Total débit', value: `${formatMontant(balance.total_debit)} ${balance.devise_tenue}` },
      { label: 'Total crédit', value: `${formatMontant(balance.total_credit)} ${balance.devise_tenue}` },
      { label: 'Équilibre', value: balance.equilibree ? 'Oui' : 'NON — à vérifier' },
    ],
    options: {
      dateDebut: balance.date_debut,
      dateFin: balance.date_fin,
      filters: [periodeFiltre(balance), simulationFiltre(balance.inclure_brouillons)],
    },
    fileNameBase: 'balance_generale',
  })
}

export function exportBalanceExcel(balance: ComptaBalance): void {
  const data: (string | number)[][] = [
    ['Balance générale'],
    ['Devise de tenue', balance.devise_tenue],
    ['Période', `${balance.date_debut || 'début'} → ${balance.date_fin || 'fin'}`],
    ...(balance.inclure_brouillons ? [['SIMULATION — brouillons inclus']] : []),
    [],
    ['Compte', 'Libellé', 'Nature', 'Débit', 'Crédit', 'Solde débiteur', 'Solde créditeur'],
    ...balance.lignes.map(l => [
      l.compte_numero,
      l.compte_libelle,
      l.nature,
      toNumber(l.total_debit),
      toNumber(l.total_credit),
      toNumber(l.solde_debiteur),
      toNumber(l.solde_crediteur),
    ]),
    [],
    [
      'TOTAL',
      '',
      '',
      toNumber(balance.total_debit),
      toNumber(balance.total_credit),
      toNumber(balance.total_solde_debiteur),
      toNumber(balance.total_solde_crediteur),
    ],
  ]

  const sheet = XLSX.utils.aoa_to_sheet(data)
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, sheet, 'Balance')
  XLSX.writeFile(wb, `balance_generale_${balance.date_fin || 'exercice'}.xlsx`)
}

export async function exportGrandLivrePDF(livre: ComptaGrandLivre): Promise<void> {
  await buildListReport({
    title: `Grand Livre — ${livre.compte_numero} ${livre.compte_libelle}`,
    footerLabel: 'Grand Livre',
    columns: [
      { header: 'Date', width: 22 },
      { header: 'Pièce', width: 30 },
      { header: 'Jrn', width: 14 },
      { header: 'Libellé', width: 88 },
      { header: 'Débit', width: 30, halign: 'right' },
      { header: 'Crédit', width: 30, halign: 'right' },
      { header: 'Solde', width: 32, halign: 'right' },
    ],
    rows: [
      ['', '', '', 'Solde antérieur', '', '', formatMontant(livre.solde_anterieur)],
      ...livre.mouvements.map(m => [
        m.date_ecriture,
        m.numero || '(brouillon)',
        m.journal_code,
        m.libelle || '',
        formatMontant(m.debit),
        formatMontant(m.credit),
        formatMontant(m.solde_cumule),
      ]),
    ],
    footRow: [
      'TOTAL',
      '',
      '',
      '',
      formatMontant(livre.total_debit_page),
      formatMontant(livre.total_credit_page),
      formatMontant(livre.solde_final_page),
    ],
    summary: [
      { label: 'Compte', value: `${livre.compte_numero} — ${livre.compte_libelle}` },
      { label: 'Mouvements', value: String(livre.mouvements.length) },
      { label: 'Solde final', value: `${formatMontant(livre.solde_final_page)} ${livre.devise_tenue}` },
    ],
    options: {
      dateDebut: livre.date_debut,
      dateFin: livre.date_fin,
      filters: [periodeFiltre(livre), simulationFiltre(livre.inclure_brouillons)],
    },
    fileNameBase: `grand_livre_${livre.compte_numero}`,
  })
}

export function exportGrandLivreExcel(livre: ComptaGrandLivre): void {
  const data: (string | number)[][] = [
    [`Grand Livre — ${livre.compte_numero} ${livre.compte_libelle}`],
    ['Devise de tenue', livre.devise_tenue],
    ['Période', `${livre.date_debut || 'début'} → ${livre.date_fin || 'fin'}`],
    ...(livre.inclure_brouillons ? [['SIMULATION — brouillons inclus']] : []),
    [],
    ['Date', 'Pièce', 'Journal', 'Libellé', 'Débit', 'Crédit', 'Solde cumulé'],
    ['', '', '', 'Solde antérieur', '', '', toNumber(livre.solde_anterieur)],
    ...livre.mouvements.map(m => [
      m.date_ecriture,
      m.numero || '(brouillon)',
      m.journal_code,
      m.libelle || '',
      toNumber(m.debit),
      toNumber(m.credit),
      toNumber(m.solde_cumule),
    ]),
    [],
    [
      'TOTAL',
      '',
      '',
      '',
      toNumber(livre.total_debit_page),
      toNumber(livre.total_credit_page),
      toNumber(livre.solde_final_page),
    ],
  ]

  const sheet = XLSX.utils.aoa_to_sheet(data)
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, sheet, 'Grand Livre')
  XLSX.writeFile(wb, `grand_livre_${livre.compte_numero}.xlsx`)
}
