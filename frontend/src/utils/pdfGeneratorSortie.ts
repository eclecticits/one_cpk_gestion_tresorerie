import jsPDF from 'jspdf'
import { format } from 'date-fns'
import { API_BASE_URL } from '../lib/apiClient'
import { numberToWords } from './numberToWords'
import { formatAmount, toNumber } from './amount'

let cachedSettings: any | null = null
let cachedLogoDataUrl: string | null = null
let cachedLogoUrl: string | null = null

const getPrintSettingsData = async () => {
  if (cachedSettings) return cachedSettings
  try {
    const token =
      (typeof window !== 'undefined' &&
        (window.localStorage.getItem('access_token') ||
          window.localStorage.getItem('token') ||
          window.localStorage.getItem('onec_cpk_access_token'))) ||
      null
    const settingsRes = await fetch(`${API_BASE_URL}/print-settings`, {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      credentials: 'include',
    })
    if (!settingsRes.ok) return null
    cachedSettings = await settingsRes.json()
    return cachedSettings
  } catch {
    return null
  }
}

const getLogoDataUrl = async () => {
  if (cachedLogoDataUrl) return cachedLogoDataUrl
  try {
    const settings = await getPrintSettingsData()
    cachedLogoUrl = settings?.logo_url || null
    const logoPath = cachedLogoUrl || '/imge_onec.png'
    const res = await fetch(logoPath, { credentials: 'include' })
    if (!res.ok) return null
    const blob = await res.blob()
    const dataUrl = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onloadend = () => resolve(String(reader.result || ''))
      reader.onerror = reject
      reader.readAsDataURL(blob)
    })
    cachedLogoDataUrl = dataUrl
    return cachedLogoDataUrl
  } catch {
    return null
  }
}

export const generateSortieFondsPDF = async (sortie: any, budgetLabel?: string) => {
  const settings = await getPrintSettingsData()
  const logoDataUrl = await getLogoDataUrl()
  const doc = new jsPDF({ orientation: 'p', unit: 'mm', format: 'a4' })

  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  const margin = 15

  const orgName = settings?.organization_name || 'ONEC / CPK'
  const subtitle = settings?.organization_subtitle || ''
  const ref = sortie?.reference_numero || sortie?.reference || sortie?.id || 'N/A'
  const datePaiement = sortie?.date_paiement ? new Date(sortie.date_paiement) : new Date()
  const sourceNumero = sortie?.requisition?.numero_requisition || sortie?.requisition_id || '-'
  const sourceLabel = sortie?.type_sortie === 'remboursement' ? 'Remboursement transport' : 'Réquisition'

  if (logoDataUrl) {
    doc.addImage(logoDataUrl, 'PNG', margin, 10, 18, 18)
  }

  doc.setFont('times', 'bold')
  doc.setFontSize(14)
  doc.text(orgName.toUpperCase(), logoDataUrl ? margin + 24 : margin, 16)
  doc.setFont('times', 'normal')
  doc.setFontSize(9)
  if (subtitle) doc.text(subtitle, logoDataUrl ? margin + 24 : margin, 21)

  doc.setFont('times', 'bold')
  doc.setFontSize(16)
  doc.text('BON DE SORTIE DE CAISSE', pageWidth / 2, 30, { align: 'center' })
  doc.setFontSize(10)
  doc.setFont('helvetica', 'bold')
  doc.text(String(ref), pageWidth / 2, 36, { align: 'center' })
  doc.setFont('helvetica', 'italic')
  doc.setFontSize(8)
  doc.text(`Lié à la Réquisition : ${String(sourceNumero).slice(0, 20) || 'N/A'}`, margin, 42)
  doc.setFont('times', 'normal')

  doc.setFont('times', 'normal')
  doc.setFontSize(10)
  doc.text(`N° Transaction : ${ref}`, margin, 40)
  doc.text(`Date : ${format(datePaiement, 'dd/MM/yyyy')}`, margin, 46)
  doc.text(`Source : ${sourceLabel} N° ${String(sourceNumero).slice(0, 20)}`, margin, 52)

  const montant = toNumber(sortie?.montant_paye || 0)
  const montantLettres = numberToWords(montant)

  doc.setDrawColor(0)
  doc.rect(margin, 60, pageWidth - margin * 2, 46)

  doc.setFont('times', 'bold')
  doc.text('Bénéficiaire :', margin + 4, 70)
  doc.setFont('times', 'normal')
  doc.text(String(sortie?.beneficiaire || '-'), margin + 35, 70)

  doc.setFont('times', 'bold')
  doc.text('Montant :', margin + 4, 78)
  doc.setFont('times', 'normal')
  doc.text(`${formatAmount(montant)} USD`, margin + 35, 78)

  doc.setFont('times', 'bold')
  doc.text('Montant en lettres :', margin + 4, 86)
  doc.setFont('times', 'italic')
  const lignes = doc.splitTextToSize(montantLettres, pageWidth - margin * 2 - 50)
  doc.text(lignes, margin + 35, 86)

  doc.setFont('times', 'bold')
  doc.text('Motif :', margin + 4, 96)
  doc.setFont('times', 'normal')
  const motifLines = doc.splitTextToSize(String(sortie?.motif || '-'), pageWidth - margin * 2 - 35)
  doc.text(motifLines, margin + 35, 96)

  doc.setFont('times', 'bold')
  doc.text('Rubrique budgétaire :', margin + 4, 106)
  doc.setFont('times', 'normal')
  doc.text(String(budgetLabel || '-'), margin + 50, 106)

  if (sortie?.requisition?.annexe?.filename) {
    doc.setFont('times', 'normal')
    doc.setFontSize(8)
    doc.text(`Justificatif : ${sortie.requisition.annexe.filename}`, margin, 114)
    doc.setFontSize(10)
  }

  const ySign = Math.min(pageHeight - 40, 130)
  const colWidth = (pageWidth - margin * 2) / 3
  const colCenters = [
    margin + colWidth / 2,
    margin + colWidth * 1.5,
    margin + colWidth * 2.5,
  ]

  doc.setFont('times', 'bold')
  doc.text('Le Caissier', colCenters[0], ySign, { align: 'center' })
  doc.text('Le Bénéficiaire', colCenters[1], ySign, { align: 'center' })
  doc.text('Le Comptable', colCenters[2], ySign, { align: 'center' })

  doc.setFont('times', 'normal')
  doc.text('....................', colCenters[0], ySign + 18, { align: 'center' })
  doc.text('....................', colCenters[1], ySign + 18, { align: 'center' })
  doc.text('....................', colCenters[2], ySign + 18, { align: 'center' })

  doc.setFontSize(7.5)
  doc.setTextColor(90)
  const montantLettreAcquit = numberToWords(montant)
  const dateAcquit = format(datePaiement, 'dd/MM/yyyy')
  const acquitLine = `Reçu la somme de ${formatAmount(montant)} USD (${montantLettreAcquit}) le ${dateAcquit}`
  const acquitLines = doc.splitTextToSize(acquitLine, colWidth - 6)
  doc.text(acquitLines, colCenters[1], ySign + 26, { align: 'center' })

  doc.setFontSize(8)
  doc.setTextColor(100)
  doc.text(format(new Date(), 'dd/MM/yyyy HH:mm'), margin, pageHeight - 8)
  doc.text(settings?.pied_de_page_legal || 'Sortie de caisse - ONEC/CPK', pageWidth / 2, pageHeight - 8, { align: 'center' })
  doc.text('Page 1/1', pageWidth - margin, pageHeight - 8, { align: 'right' })

  doc.save(`Sortie_Fonds_${String(ref).slice(0, 16)}.pdf`)
}
