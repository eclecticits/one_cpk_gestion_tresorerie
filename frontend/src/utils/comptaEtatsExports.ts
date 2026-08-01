/**
 * Exports des états financiers (Bilan, Résultat, SIG, Flux).
 *
 * Le bilan actif est le seul état à trois colonnes (brut, amortissement,
 * net) ; les autres n'affichent que le net. Les exports le reflètent pour ne
 * pas imprimer deux colonnes vides.
 */

import * as XLSX from 'xlsx'
import { buildListReport } from './pdfGeneratorReports'
import { toNumber } from './amount'
import type { ComptaEtat } from '../types/comptabilite'

const TITRES: Record<string, string> = {
  BILAN_ACTIF: 'Bilan — Actif',
  BILAN_PASSIF: 'Bilan — Passif',
  RESULTAT: 'Compte de résultat',
  SIG: 'Soldes intermédiaires de gestion',
  FLUX: 'Tableau de variation de trésorerie',
}

export function titreEtat(typeEtat: string): string {
  return TITRES[typeEtat] || typeEtat
}

function montant(value: string | number): string {
  const n = toNumber(value)
  if (n === 0) return ''
  return new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n)
}

/** Indentation du libellé selon le niveau, pour rendre la hiérarchie lisible
 *  dans un PDF ou un tableur, où l'on ne peut pas styler par CSS. */
function libelleIndente(libelle: string, niveau: number): string {
  return `${'    '.repeat(Math.max(0, niveau - 1))}${libelle}`
}

export async function exportEtatPDF(etat: ComptaEtat): Promise<void> {
  const avecAmortissement = etat.type_etat === 'BILAN_ACTIF'

  await buildListReport({
    title: `${titreEtat(etat.type_etat)} — exercice ${etat.exercice_code}`,
    footerLabel: titreEtat(etat.type_etat),
    columns: avecAmortissement
      ? [
          { header: 'Poste', width: 120 },
          { header: 'Brut', width: 45, halign: 'right' },
          { header: 'Amort./Dépréc.', width: 45, halign: 'right' },
          { header: 'Net', width: 45, halign: 'right' },
        ]
      : [
          { header: 'Poste', width: 180 },
          { header: 'Montant', width: 55, halign: 'right' },
        ],
    rows: etat.lignes.map(l =>
      avecAmortissement
        ? [
            libelleIndente(l.libelle, l.niveau),
            montant(l.brut),
            montant(l.amortissement),
            montant(l.net),
          ]
        : [libelleIndente(l.libelle, l.niveau), montant(l.net)]
    ),
    summary: [
      { label: 'Exercice', value: etat.exercice_code },
      { label: 'Arrêté au', value: etat.date_arrete },
      { label: 'Total', value: `${montant(etat.total)} ${etat.devise_tenue}` },
    ],
    options: {
      dateFin: etat.date_arrete,
      filters: [
        etat.inclure_brouillons
          ? { label: 'Nature', value: 'SIMULATION — brouillons inclus' }
          : null,
        etat.comptes_non_couverts.length > 0
          ? {
              label: 'Alerte',
              value: `${etat.comptes_non_couverts.length} compte(s) hors de tout poste`,
            }
          : null,
      ],
    },
    fileNameBase: etat.type_etat.toLowerCase(),
  })
}

export function exportEtatExcel(etat: ComptaEtat): void {
  const avecAmortissement = etat.type_etat === 'BILAN_ACTIF'

  const data: (string | number)[][] = [
    [`${titreEtat(etat.type_etat)} — exercice ${etat.exercice_code}`],
    ['Devise de tenue', etat.devise_tenue],
    ['Arrêté au', etat.date_arrete],
    ...(etat.inclure_brouillons ? [['SIMULATION — brouillons inclus']] : []),
    ...(etat.comptes_non_couverts.length > 0
      ? [
          ['ATTENTION — comptes mouvementés hors de tout poste :'],
          ...etat.comptes_non_couverts.map(c => ['', c]),
        ]
      : []),
    [],
    avecAmortissement
      ? ['Code', 'Poste', 'Brut', 'Amort./Dépréc.', 'Net']
      : ['Code', 'Poste', 'Montant'],
    ...etat.lignes.map(l =>
      avecAmortissement
        ? [
            l.code,
            libelleIndente(l.libelle, l.niveau),
            toNumber(l.brut),
            toNumber(l.amortissement),
            toNumber(l.net),
          ]
        : [l.code, libelleIndente(l.libelle, l.niveau), toNumber(l.net)]
    ),
  ]

  const sheet = XLSX.utils.aoa_to_sheet(data)
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, sheet, titreEtat(etat.type_etat).slice(0, 31))
  XLSX.writeFile(wb, `${etat.type_etat.toLowerCase()}_${etat.exercice_code}.xlsx`)
}
