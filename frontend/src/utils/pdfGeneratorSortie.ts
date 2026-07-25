import jsPDF from 'jspdf'
import QRCode from 'qrcode'
import { format } from 'date-fns'
import { API_BASE_URL, getAuthHeaders } from '../lib/apiClient'
import { numberToWords } from './numberToWords'
import { formatAmount, toNumber } from './amount'
import { buildUploadUrl } from './uploads'

let cachedSettings: any | null = null
let cachedLogoDataUrl: string | null = null
let cachedLogoUrl: string | null = null
let cachedStampDataUrl: string | null = null
let cachedStampUrl: string | null = null

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
    const settings = await getPrintSettingsData()
    cachedLogoUrl = settings?.logo_url || null
    const logoPath = cachedLogoUrl ? buildUploadUrl(cachedLogoUrl) : '/imge_onec.png'
    const res = await fetch(logoPath, { 
      headers: getAuthHeaders(),
      credentials: 'include' 
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

const getStampDataUrl = async () => {
  if (cachedStampDataUrl) return cachedStampDataUrl
  try {
    if (!cachedStampUrl) {
      const settings = await getPrintSettingsData()
      cachedStampUrl = settings?.stamp_url || null
    }
    if (!cachedStampUrl) return null
    const res = await fetch(buildUploadUrl(cachedStampUrl), { 
      headers: getAuthHeaders(),
      credentials: 'include' 
    })
    if (!res.ok) return null
    const blob = await res.blob()
    const dataUrl = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onloadend = () => resolve(String(reader.result || ''))
      reader.onerror = reject
      reader.readAsDataURL(blob)
    })
    cachedStampDataUrl = dataUrl
    return cachedStampDataUrl
  } catch {
    return null
  }
}

export const generateSortieFondsPDF = async (
  sortie: any,
  budgetLabel?: string,
  output: 'download' | 'blob' = 'download'
) => {
  const settings = await getPrintSettingsData()
  const logoDataUrl = await getLogoDataUrl()
  const stampDataUrl = settings?.show_footer_signature === false ? null : await getStampDataUrl()
  const doc = new jsPDF({ orientation: 'l', unit: 'mm', format: 'a4' })

  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  const margin = 10

  const orgName = settings?.organization_name || 'ONEC'
  const subtitle = settings?.organization_subtitle || "Plateforme intelligente de gestion intégrée de l'ONEC-RDC"
  
  const formatUserName = (user: any, fallbackId?: string) => {
    const first = String(user?.prenom || '').trim()
    const last = String(user?.nom || '').trim()
    const full = `${first} ${last}`.trim()
    if (full) return full
    if (requisition?.req_nom_gauche_hist && fallbackId === requisition?.validee_par) return requisition.req_nom_gauche_hist
    if (requisition?.req_nom_droite_hist && fallbackId === requisition?.approuvee_par) return requisition.req_nom_droite_hist
    if (fallbackId) return `ID ${String(fallbackId).slice(0, 8)}`
    return '—'
  }

  const resolveSourceNumero = (item: any) => {
    if (String(item?.type_sortie || '').toLowerCase() === 'sortie_directe') {
      return item?.ordre_numero || '-'
    }
    const requisition = item?.requisition || {}
    const transport =
      requisition?.remboursement_transport ||
      item?.remboursement_transport ||
      null
    const transportNumero =
      transport?.numero_remboursement ||
      transport?.reference_numero ||
      null
    const isTransportSource =
      String(requisition?.type_requisition || '').toLowerCase() === 'remboursement_transport' ||
      String(item?.type_sortie || '').toLowerCase() === 'remboursement' ||
      Boolean(transportNumero)

    if (isTransportSource) {
      return transportNumero || requisition?.numero_requisition || item?.requisition_id || '-'
    }
    return requisition?.numero_requisition || item?.requisition_id || '-'
  }

  const sourceNumero = resolveSourceNumero(sortie)

  // Le numéro de référence du bon doit être le numéro du document source (REQ ou REMB)
  const ref = sourceNumero !== '-' ? sourceNumero : (sortie?.reference_numero || sortie?.reference || sortie?.id || 'N/A')
  
  const systemId = sortie?.id ? String(sortie.id) : ''
  const datePaiement = sortie?.date_paiement ? new Date(sortie.date_paiement) : new Date()
  
  const requisition = sortie?.requisition || {}
  const autorisateurName = formatUserName(requisition?.validateur, requisition?.validee_par)
  const viseurName = formatUserName(requisition?.approbateur, requisition?.approuvee_par)
  const beneficiaireSignatureName = String(sortie?.beneficiaire || '-').trim() || '-'
  const etablisseurName = formatUserName(sortie?.created_by_user, sortie?.created_by)
  const cancellationAuthor = formatUserName(sortie?.annulee_par_user, sortie?.annulee_par_id)
  // Auto depuis les vrais utilisateurs : pour une tranche liée à un ordre de
  // décaissement, le signataire « autorité » est la personne qui a autorisé CETTE
  // tranche (à défaut, le nom statique des réglages).
  const autorisateurTrancheUser = sortie?.ordre?.autorise_par_user
  const autorisateurTrancheName = String(
    sortie?.autorisateur_tranche ||
      (autorisateurTrancheUser ? formatUserName(autorisateurTrancheUser) : '') ||
      ''
  ).trim()

  // Circuit complet (compact) : toutes les étapes de validation de la réquisition,
  // puis l'autorisation progressive et l'exécution en caisse. Source privilégiée :
  // le snapshot des signataires (figé à la finalisation), sinon les champs présents.
  const roleLabelsCircuit: Record<string, string> = {
    demandeur: 'Demandeur',
    signataire_service: 'Signataire service',
    examen: 'Examen',
    validation_1: 'Validation 1',
    validation_2: 'Visa (validation 2)',
  }
  const snapItems: any[] = Array.isArray((requisition as any)?.signatories_snapshot?.items)
    ? (requisition as any).signatories_snapshot.items
    : []
  const circuitSteps: { label: string; name: string }[] = []
  if (snapItems.length) {
    for (const it of [...snapItems].sort((a, b) => (a?.display_order || 0) - (b?.display_order || 0))) {
      const label = roleLabelsCircuit[String(it?.role || '')]
      const name = String(it?.full_name || '').trim()
      if (label && name) circuitSteps.push({ label, name })
    }
  } else {
    if (autorisateurName !== '—') circuitSteps.push({ label: 'Validation 1', name: autorisateurName })
    if (viseurName !== '—') circuitSteps.push({ label: 'Visa (validation 2)', name: viseurName })
  }
  if (autorisateurTrancheName) circuitSteps.push({ label: 'Autorisation progressive', name: autorisateurTrancheName })
  if (etablisseurName !== '—') circuitSteps.push({ label: 'Exécuté (caisse)', name: etablisseurName })

  const signataireFinalName =
    autorisateurTrancheName ||
    String(settings?.sortie_nom_signataire || settings?.recu_nom_signataire || '').trim() ||
    '—'
  const buildQrValue = () => {
    const base = String(settings?.sortie_qr_base_url || '').trim()
    if (base) {
      if (base.includes('{ref}')) return base.replace('{ref}', encodeURIComponent(String(ref)))
      if (base.includes('{id}')) return base.replace('{id}', encodeURIComponent(String(systemId || '')))
      const sep = base.includes('?') ? '&' : '?'
      return `${base}${sep}ref=${encodeURIComponent(String(ref))}`
    }
    return [
      `REF:${ref}`,
      `AMT:${toNumber(sortie?.montant_paye || 0)}`,
      `DATE:${format(datePaiement, 'yyyy-MM-dd')}`,
      systemId ? `ID:${systemId}` : null,
    ]
      .filter(Boolean)
      .join('|')
  }

  // --- FILIGRANE DE SÉCURITÉ ---
  if (settings?.show_sortie_watermark !== false) {
    const watermarkText = String(settings?.sortie_watermark_text || 'PAYÉ').trim()
    if (watermarkText) {
      const opacityRaw = Number(settings?.sortie_watermark_opacity ?? 0.15)
      const opacity = Math.min(0.6, Math.max(0.05, Number.isFinite(opacityRaw) ? opacityRaw : 0.15))
      doc.setTextColor(240, 240, 240)
      doc.setFont('helvetica', 'bold')
      doc.setFontSize(60)
      try {
        doc.saveGraphicsState()
        const GState = (doc as any).GState
        if (GState && (doc as any).setGState) {
          const gs = new GState({ opacity })
          ;(doc as any).setGState(gs)
        }
        doc.text(watermarkText, pageWidth / 2, pageHeight / 2 + 8, { align: 'center', angle: 45 })
      } finally {
        doc.restoreGraphicsState()
      }
    }
  }

  // --- CADRE EXTÉRIEUR ---
  doc.setLineWidth(0.6)
  doc.setDrawColor(226, 232, 240)
  doc.rect(5, 5, pageWidth - 10, pageHeight - 10)

  // --- EN-TÊTE ---
  if (logoDataUrl) {
    doc.addImage(logoDataUrl, 'PNG', margin, 8, 18, 18)
  }

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(12)
  doc.setTextColor(15, 23, 42)
  doc.text(orgName.toUpperCase(), logoDataUrl ? margin + 22 : margin, 14)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8.5)
  doc.setTextColor(71, 85, 105)
  if (subtitle) doc.text(subtitle, logoDataUrl ? margin + 22 : margin, 19)

  const metaW = 70
  const metaH = 22
  const metaX = pageWidth - margin - metaW
  const metaY = 8
  doc.setFillColor(15, 23, 42)
  doc.roundedRect(metaX, metaY, metaW, metaH, 3, 3, 'F')
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  doc.setTextColor(226, 232, 240)
  doc.text('N° BON', metaX + 6, metaY + 6)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(11)
  doc.text(String(ref).slice(0, 22), metaX + 6, metaY + 14)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  doc.text(`Date: ${format(datePaiement, 'dd/MM/yyyy')}`, metaX + 6, metaY + 19)

  doc.setDrawColor(226, 232, 240)
  doc.setLineWidth(0.6)
  doc.line(margin, 28, pageWidth - margin, 28)

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(15)
  doc.setTextColor(15, 23, 42)
  doc.text('BON DE SORTIE DE CAISSE', pageWidth / 2, 33, { align: 'center' })

  const statusRaw = String(sortie?.statut || sortie?.status || '').toUpperCase()
  const statusLabel =
    statusRaw === 'VALIDE' || statusRaw === 'APPROUVEE' ? 'APPROUVÉ' :
    statusRaw === 'ANNULEE' ? 'ANNULÉ' :
    statusRaw === 'PAYEE' ? 'PAYÉ' : 'EN ATTENTE'
  const statusColor =
    statusLabel === 'APPROUVÉ' || statusLabel === 'PAYÉ' ? [22, 163, 74] :
    statusLabel === 'ANNULÉ' ? [220, 38, 38] :
    [245, 158, 11]
  const badgeW = 36
  const badgeH = 7
  const badgeX = pageWidth - margin - badgeW
  const badgeY = 31
  doc.setFillColor(statusColor[0], statusColor[1], statusColor[2])
  doc.roundedRect(badgeX, badgeY, badgeW, badgeH, 2, 2, 'F')
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(7.5)
  doc.setTextColor(255, 255, 255)
  doc.text(statusLabel, badgeX + badgeW / 2, badgeY + 5, { align: 'center' })

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8)
  doc.setTextColor(71, 85, 105)
  doc.text(`Document source : ${String(sourceNumero).slice(0, 26) || 'N/A'}`, margin, 36)
  if (systemId) {
    doc.text(`ID système: ${systemId.slice(0, 24)}`, margin, 40)
  }

  // --- CORPS DU DOCUMENT ---
  const infoY = 42
  const infoH = 44
  doc.setFillColor(248, 250, 252)
  doc.roundedRect(margin, infoY, pageWidth - margin * 2, infoH, 3, 3, 'F')

  const colGap = 6
  const leftX = margin + 6
  const rightX = pageWidth / 2 + colGap
  const labelColor = [100, 116, 139]
  const valueColor = [15, 23, 42]

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  doc.setTextColor(labelColor[0], labelColor[1], labelColor[2])
  doc.text('Bénéficiaire', leftX, infoY + 7)
  doc.setTextColor(valueColor[0], valueColor[1], valueColor[2])
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(10)
  doc.text(String(sortie?.beneficiaire || '-').toUpperCase(), leftX, infoY + 13)

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  doc.setTextColor(labelColor[0], labelColor[1], labelColor[2])
  doc.text('Motif', leftX, infoY + 20)
  doc.setTextColor(valueColor[0], valueColor[1], valueColor[2])
  doc.setFontSize(9)
  const motifLines = doc.splitTextToSize(String(sortie?.motif || '-'), pageWidth / 2 - margin - 12)
  doc.text(motifLines.slice(0, 2), leftX, infoY + 26)

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  doc.setTextColor(labelColor[0], labelColor[1], labelColor[2])
  doc.text('Date', rightX, infoY + 7)
  doc.setTextColor(valueColor[0], valueColor[1], valueColor[2])
  doc.setFontSize(9)
  doc.text(format(datePaiement, 'dd/MM/yyyy'), rightX, infoY + 12)

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  doc.setTextColor(labelColor[0], labelColor[1], labelColor[2])
  doc.text('Mode de paiement', rightX, infoY + 19)
  doc.setTextColor(valueColor[0], valueColor[1], valueColor[2])
  doc.setFontSize(9)
  const modeLabel =
    sortie?.mode_paiement === 'mobile_money'
      ? 'Mobile Money'
      : sortie?.mode_paiement === 'virement'
      ? 'Virement'
      : sortie?.mode_paiement === 'card'
      ? 'Carte (Visa)'
      : 'Cash'
  doc.text(modeLabel, rightX, infoY + 24)

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  doc.setTextColor(labelColor[0], labelColor[1], labelColor[2])
  doc.text('Document source', rightX, infoY + 30)
  doc.setTextColor(valueColor[0], valueColor[1], valueColor[2])
  doc.setFontSize(9)
  doc.text(String(sourceNumero).slice(0, 20), rightX + 24, infoY + 30)

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  doc.setTextColor(labelColor[0], labelColor[1], labelColor[2])
  const posteLabel = 'Poste budgétaire'
  const posteY = infoY + 34
  doc.text(posteLabel, rightX, posteY)
  const labelWidth = doc.getTextWidth(posteLabel)
  const valueX = rightX + labelWidth + 4
  const maxValueWidth = pageWidth - margin - valueX
  doc.setTextColor(valueColor[0], valueColor[1], valueColor[2])
  doc.setFontSize(8.5)
  const rawPoste = String(budgetLabel || '-')
  let posteValue = rawPoste
  if (doc.getTextWidth(posteValue) > maxValueWidth) {
    const ellipsis = '...'
    let trimmed = posteValue
    while (trimmed.length > 0 && doc.getTextWidth(`${trimmed}${ellipsis}`) > maxValueWidth) {
      trimmed = trimmed.slice(0, -1)
    }
    posteValue = `${trimmed}${ellipsis}`
  }
  doc.text(posteValue, valueX, posteY)

  let contentY = infoY + infoH + 6
  if (statusRaw === 'ANNULEE') {
    const cancellationHeight = 22
    doc.setFillColor(254, 226, 226)
    doc.setDrawColor(220, 38, 38)
    doc.roundedRect(margin, contentY, pageWidth - margin * 2, cancellationHeight, 3, 3, 'FD')
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(11)
    doc.setTextColor(185, 28, 28)
    doc.text('OPÉRATION ANNULÉE', margin + 6, contentY + 7)
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(8)
    const cancelledAt = sortie?.annulee_le ? format(new Date(sortie.annulee_le), 'dd/MM/yyyy HH:mm') : '—'
    const cancellationMotif = String(sortie?.motif_annulation || '-').trim() || '-'
    doc.text(`Date d'annulation : ${cancelledAt}`, margin + 6, contentY + 13)
    doc.text(`Annulée par : ${cancellationAuthor}`, margin + 74, contentY + 13)
    doc.text(`Motif : ${cancellationMotif}`, margin + 6, contentY + 18)
    contentY += cancellationHeight + 6
  }

  const montant = toNumber(sortie?.montant_paye || 0)
  const montantLettres = numberToWords(montant)
  const tauxSnapshot = sortie?.exchange_rate_snapshot
  const tauxLabel =
    tauxSnapshot && Number(tauxSnapshot) > 0 ? `Taux appliqué : 1 USD = ${formatAmount(tauxSnapshot)} CDF` : ''

  // Bloc montant
  const amountY = contentY
  const amountH = 18
  doc.setFillColor(241, 245, 249)
  doc.roundedRect(margin, amountY, pageWidth - margin * 2, amountH, 3, 3, 'F')
  doc.setFillColor(34, 197, 94)
  doc.rect(margin, amountY, 4, amountH, 'F')
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  doc.setTextColor(71, 85, 105)
  doc.text('Montant total', margin + 8, amountY + 7)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(18)
  doc.setTextColor(15, 23, 42)
  doc.text(`${formatAmount(montant)} ${String(sortie?.devise || 'USD').toUpperCase()}`, margin + 8, amountY + 15)

  doc.setFont('helvetica', 'italic')
  doc.setFontSize(8.5)
  doc.setTextColor(71, 85, 105)
  doc.text(`Soit en lettres : ${montantLettres}`, margin, amountY + amountH + 7)
  if (tauxLabel) {
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(8)
    doc.text(tauxLabel, margin, amountY + amountH + 12)
  }

  // --- VALIDATION CROISÉE ---
  const validationY = amountY + amountH + 18
  const isSortieDirecteDoc = String(sortie?.type_sortie || '').toLowerCase() === 'sortie_directe'
  let steps = circuitSteps
  if (isSortieDirecteDoc) {
    const programmeurName = formatUserName(sortie?.programme_par_user, sortie?.programme_par_id)
    steps = [
      ...(programmeurName !== '—' ? [{ label: 'Programmé par', name: programmeurName }] : []),
      ...circuitSteps.filter((s) => s.label !== 'Autorisation progressive'),
    ]
  }
  if (steps.length === 0) steps = [{ label: 'Circuit', name: 'Non renseigné' }]
  const colCount = 2
  const rows = Math.ceil(steps.length / colCount)
  const lineH = 4
  const boxTop = validationY - 5
  const boxH = 8 + rows * lineH
  doc.setFillColor(250, 250, 250)
  doc.roundedRect(margin, boxTop, pageWidth - margin * 2, boxH, 2, 2, 'F')
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(8.5)
  doc.setTextColor(15, 23, 42)
  doc.text('Circuit de validation & exécution', margin + 4, validationY)
  const colW = (pageWidth - margin * 2 - 8) / colCount
  steps.forEach((s, i) => {
    const col = i % colCount
    const row = Math.floor(i / colCount)
    const x = margin + 4 + col * colW
    const y = validationY + 5 + row * lineH
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(7)
    doc.setTextColor(71, 85, 105)
    doc.text(`${s.label} :`, x, y)
    const lblW = doc.getTextWidth(`${s.label} : `)
    doc.setFont('helvetica', 'normal')
    doc.setTextColor(30, 41, 59)
    doc.text(String(s.name).slice(0, 28), x + lblW, y)
  })

  const ySign = pageHeight - 30
  const sigGap = 5
  const sigW = (pageWidth - margin * 2 - sigGap * 2) / 3
  const sigH = 16
  const sigY = ySign - sigH
  const sigLabels = [
    settings?.sortie_sig_label_1 || 'BÉNÉFICIAIRE',
    settings?.sortie_sig_label_2 || 'ÉTABLI PAR',
    // Quand l'autorisation vient d'un ordre (tranche progressive / sortie directe),
    // on nomme explicitement « AUTORISÉ PAR » avec le vrai autorisateur.
    autorisateurTrancheName ? 'AUTORISÉ PAR' : (settings?.sortie_sig_label_3 || 'AUTORITÉ (TRÉSORERIE)'),
  ]
  const sigNames = [
    beneficiaireSignatureName,
    etablisseurName,
    signataireFinalName,
  ]
  const sigHint = settings?.sortie_sig_hint || 'Signature & date'
  for (let i = 0; i < 3; i += 1) {
    const x = margin + i * (sigW + sigGap)
    doc.setDrawColor(226, 232, 240)
    doc.rect(x, sigY, sigW, sigH)
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(8)
    doc.setTextColor(15, 23, 42)
    doc.text(sigLabels[i], x + sigW / 2, sigY + 6, { align: 'center' })
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7)
    doc.setTextColor(100, 116, 139)
    doc.text(String(sigNames[i]).slice(0, 34), x + sigW / 2, sigY + 10.5, { align: 'center' })
    doc.setFontSize(6.5)
    doc.text(sigHint, x + sigW / 2, sigY + 14, { align: 'center' })
  }

  if (settings?.show_footer_signature !== false) {
    const sortieLabel = settings?.sortie_label_signature || settings?.recu_label_signature || 'Cachet & signature'
    const sortieNom = settings?.sortie_nom_signataire || settings?.recu_nom_signataire || ''
    const shouldRenderFooterName =
      String(sortieNom || '').trim() &&
      String(sortieNom || '').trim().toLowerCase() !== String(signataireFinalName || '').trim().toLowerCase()
    const signX = pageWidth - margin - 50
    const signY = sigY - 4
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(8)
    doc.setTextColor(15, 23, 42)
    doc.text(sortieLabel, signX, signY)
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7)
    doc.setTextColor(71, 85, 105)
    if (shouldRenderFooterName) {
      doc.text(sortieNom, signX, signY + 4)
    }
    if (stampDataUrl) {
      const stampSize = 18
      doc.addImage(stampDataUrl, 'PNG', signX, signY + 6, stampSize, stampSize)
    }
  }

  // --- QR CODE ---
  if (settings?.show_sortie_qr !== false) {
    try {
      const qrCodeDataUrl = await QRCode.toDataURL(buildQrValue(), { margin: 0, width: 100 })
      const qrSize = 16
      const qrX = pageWidth - margin - qrSize
      const qrY = pageHeight - 26 - qrSize
      doc.setFont('helvetica', 'normal')
      doc.setFontSize(6.5)
      doc.setTextColor(100, 116, 139)
      doc.text('Scanner pour vérifier', qrX + qrSize / 2, qrY - 2, { align: 'center' })
      doc.addImage(qrCodeDataUrl, 'PNG', qrX, qrY, qrSize, qrSize)
    } catch {
      // QR code is optional; continue without failing the PDF
    }
  }

  doc.setFont('times', 'normal')
  doc.setFontSize(7.5)
  doc.setTextColor(90)
  doc.text(format(new Date(), 'dd/MM/yyyy HH:mm'), margin, pageHeight - 6)
  doc.text(orgName ? `Sortie de caisse - ${orgName}` : 'Sortie de caisse', pageWidth / 2, pageHeight - 6, { align: 'center' })
  doc.text('Page 1/1', pageWidth - margin, pageHeight - 6, { align: 'right' })

  if (output === 'blob') {
    return doc.output('blob')
  }
  doc.save(`Sortie_Fonds_${String(ref).slice(0, 16)}.pdf`)
  return null
}
