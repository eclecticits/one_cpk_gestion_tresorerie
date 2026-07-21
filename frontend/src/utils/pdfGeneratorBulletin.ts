import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'
import { format } from 'date-fns'
import { numberToWords } from './numberToWords'
import { formatAmount, toNumber } from './amount'
import { API_BASE_URL, getAuthHeaders } from '../lib/apiClient'
import { buildUploadUrl } from './uploads'
import type { HRSalarySlip, HREmployee } from '../api/hr'

let cachedLogoDataUrl: string | null = null
let cachedLogoUrl: string | null = null
let cachedSettings: any | null = null

const getPrintSettingsData = async () => {
  if (cachedSettings) return cachedSettings
  try {
    const settingsRes = await fetch(`${API_BASE_URL}/print-settings`, {
      headers: getAuthHeaders(),
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
    if (!cachedLogoUrl) {
      const settings = await getPrintSettingsData()
      cachedLogoUrl = settings?.logo_url || null
    }
    const logoPath = cachedLogoUrl ? buildUploadUrl(cachedLogoUrl) : '/imge_onec.png'
    const res = await fetch(logoPath, {
      headers: getAuthHeaders(),
      credentials: 'include',
    })
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

const openPdfInNewTab = (doc: jsPDF) => {
  const blob = doc.output('blob')
  const url = URL.createObjectURL(blob)
  window.open(url, '_blank', 'noopener,noreferrer')
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

const fullEmployeeName = (employee?: HREmployee) => {
  if (!employee) return 'N/A'
  return [employee.nom, employee.post_nom, employee.prenom].filter(Boolean).join(' ')
}

export const generateBulletinPaiePDF = async (
  slip: HRSalarySlip,
  employee: HREmployee | undefined,
  periodeLabel: string,
  action: 'print' | 'download' = 'download'
) => {
  const settings = await getPrintSettingsData()
  const logoDataUrl = await getLogoDataUrl()
  const doc = new jsPDF({ orientation: 'p', unit: 'mm', format: 'a4' })
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  const margin = 15

  if (logoDataUrl) {
    doc.addImage(logoDataUrl, 'PNG', margin, 10, 24, 24)
  }

  doc.setFont('times', 'bold')
  doc.setFontSize(14)
  doc.setTextColor(0)
  const organizationName = settings?.organization_name?.trim() || 'ONEC'
  const headerX = margin + 28
  doc.text(organizationName.toUpperCase(), headerX, 16)
  doc.setFont('times', 'normal')
  doc.setFontSize(10)
  const subtitleLines = [settings?.organization_subtitle, settings?.header_text].filter(
    (line): line is string => Boolean(line && String(line).trim())
  )
  subtitleLines.slice(0, 2).forEach((line, index) => doc.text(line, headerX, 21 + index * 4))

  doc.setDrawColor(113, 75, 103)
  doc.setLineWidth(0.8)
  doc.line(margin, 38, pageWidth - margin, 38)

  doc.setFont('times', 'bold')
  doc.setFontSize(14)
  doc.setTextColor(0)
  doc.text('BULLETIN DE PAIE', pageWidth / 2, 48, { align: 'center' })
  doc.setFont('times', 'normal')
  doc.setFontSize(10)
  doc.text(`Période : ${periodeLabel}`, pageWidth / 2, 54, { align: 'center' })
  doc.text(`Bulletin N° ${slip.id}`, pageWidth / 2, 59, { align: 'center' })

  autoTable(doc, {
    startY: 66,
    theme: 'grid',
    head: [["Identité de l'agent", '']],
    body: [
      ['Nom complet', fullEmployeeName(employee).toUpperCase()],
      ['Matricule', employee?.matricule || 'N/A'],
      ['Fonction', employee?.fonction?.libelle || '—'],
      ['Service', employee?.service?.libelle || '—'],
    ],
    styles: { font: 'times', fontSize: 10, cellPadding: 3 },
    headStyles: { fillColor: [113, 75, 103], textColor: 255, fontStyle: 'bold' },
    columnStyles: { 0: { cellWidth: 60, fillColor: [245, 245, 245], fontStyle: 'bold' } },
    margin: { left: margin, right: margin },
  })

  let y = (doc as any).lastAutoTable.finalY + 8

  const salaireBase = toNumber(slip.salaire_base)
  const primes = toNumber(slip.total_primes)
  const brut = salaireBase + primes
  const ipr = toNumber(slip.ipr)
  const cnss = toNumber(slip.cnss_salarie)
  const retenues = toNumber(slip.total_retenues)
  const net = toNumber(slip.net_a_payer)
  const devise = slip.devise

  const rows: any[] = []
  if (slip.jours_travailles != null) rows.push(['Jours travaillés', String(slip.jours_travailles)])
  if (slip.jours_absences != null) rows.push(["Jours d'absence", String(slip.jours_absences)])
  rows.push(
    ['Salaire de base', `${formatAmount(salaireBase)} ${devise}`],
    ['Primes', `+ ${formatAmount(primes)} ${devise}`],
    ['Total brut', { content: `${formatAmount(brut)} ${devise}`, styles: { fontStyle: 'bold' } }],
    ['IPR', `- ${formatAmount(ipr)} ${devise}`],
    ['CNSS salarié', `- ${formatAmount(cnss)} ${devise}`],
    ['Total retenues', { content: `- ${formatAmount(retenues)} ${devise}`, styles: { fontStyle: 'bold' } }],
    ['NET À PAYER', { content: `${formatAmount(net)} ${devise}`, styles: { fontStyle: 'bold', fontSize: 12, fillColor: [253, 248, 252] } }]
  )

  autoTable(doc, {
    startY: y,
    theme: 'grid',
    head: [['Détail de la paie', 'Montant']],
    body: rows,
    styles: { font: 'times', fontSize: 10, cellPadding: 3 },
    headStyles: { fillColor: [113, 75, 103], textColor: 255, fontStyle: 'bold' },
    columnStyles: { 0: { cellWidth: 90, fillColor: [245, 245, 245] }, 1: { halign: 'right' } },
    margin: { left: margin, right: margin },
  })

  y = (doc as any).lastAutoTable.finalY + 8

  // numberToWords suppose des dollars américains — on n'affiche la ligne "en lettres"
  // que pour les bulletins en USD afin de ne pas produire un texte incorrect en CDF.
  if (devise === 'USD') {
    const netEnLettres = numberToWords(Math.round(net))
    doc.setFont('times', 'italic')
    doc.setFontSize(9)
    doc.text(`Arrêté le présent bulletin à la somme de : ${netEnLettres}`, margin, y, { maxWidth: pageWidth - margin * 2 })
    y += 12
  }

  const signatureY = Math.max(y + 6, pageHeight - 50)
  doc.setFont('times', 'bold')
  doc.setFontSize(10)
  doc.setTextColor(0)
  doc.text("L'Employeur", margin, signatureY)
  doc.text("L'Employé(e)", pageWidth - margin - 50, signatureY)
  doc.setFont('times', 'normal')
  doc.text('................................', margin, signatureY + 15)
  doc.text('................................', pageWidth - margin - 50, signatureY + 15)

  doc.setFontSize(8)
  doc.setFont('times', 'normal')
  doc.setTextColor(100)
  doc.text(`Généré le ${format(new Date(), 'dd/MM/yyyy HH:mm')}`, margin, pageHeight - 6)
  const tenantLabel = settings?.organization_name?.trim()
  doc.text(tenantLabel ? `Bulletin de paie - ${tenantLabel}` : 'Bulletin de paie', pageWidth / 2, pageHeight - 6, { align: 'center' })

  const safeName = fullEmployeeName(employee).replace(/[\\/:*?"<>|]+/g, '-').trim() || 'agent'
  const safePeriode = periodeLabel.replace(/\s+/g, '_')
  const filename = `bulletin_paie_${safeName}_${safePeriode}.pdf`

  if (action === 'print') {
    openPdfInNewTab(doc)
  } else {
    doc.save(filename)
  }
}
