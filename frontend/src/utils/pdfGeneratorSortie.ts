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
  const examinateurName = formatUserName(requisition?.examinateur, requisition?.examen_par)
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
  // L'examen ouvre le circuit (avant les validations). Complément pour les
  // réquisitions dont le snapshot a été figé avant la capture de l'examinateur :
  // on l'insère à partir des données vives, juste avant la 1re validation.
  if (examinateurName !== '—' && !circuitSteps.some((s) => s.label === 'Examen')) {
    const idx = circuitSteps.findIndex((s) => s.label === 'Validation 1' || s.label === 'Visa (validation 2)')
    const examStep = { label: 'Examen', name: examinateurName }
    if (idx >= 0) circuitSteps.splice(idx, 0, examStep)
    else circuitSteps.push(examStep)
  }
  if (autorisateurTrancheName) circuitSteps.push({ label: 'Autorisation progressive', name: autorisateurTrancheName })
  if (etablisseurName !== '—') circuitSteps.push({ label: 'Exécuté (caisse)', name: etablisseurName })

  // Signature 3 = signataire PARAMÉTRABLE (ex. Secrétaire Exécutif / Comptable) :
  // libellé et nom viennent des réglages d'impression. L'autorisateur de la tranche
  // figure dans le « Circuit de validation » ci-dessus, pas dans ce bloc.
  const signataireFinalName =
    String(settings?.sortie_nom_signataire || settings?.recu_nom_signataire || '').trim() || '—'
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

  // ============================================================
  //  PALETTE & OUTILS DE SÉCURITÉ (dessin vectoriel jsPDF pur)
  // ============================================================
  const GREEN: [number, number, number] = [6, 95, 70]
  const GREEN_SOFT: [number, number, number] = [22, 122, 92]
  const INK: [number, number, number] = [15, 23, 42]
  const MUTED: [number, number, number] = [100, 116, 139]
  const HAIR: [number, number, number] = [205, 214, 226]
  const CARD_BG: [number, number, number] = [248, 250, 252]
  const GUILLOCHE: [number, number, number] = [224, 236, 230]

  const setFill = (c: [number, number, number]) => doc.setFillColor(c[0], c[1], c[2])
  const setDraw = (c: [number, number, number]) => doc.setDrawColor(c[0], c[1], c[2])
  const setText = (c: [number, number, number]) => doc.setTextColor(c[0], c[1], c[2])

  // Jeton déterministe dérivé de la référence (purement cosmétique — style
  // « micro-empreinte », sans aucune valeur ni prétention cryptographique).
  const securityToken = (() => {
    const src = `${ref}#${systemId}`
    let h = 0x811c9dc5
    for (let i = 0; i < src.length; i += 1) {
      h ^= src.charCodeAt(i)
      h = Math.imul(h, 0x01000193)
    }
    return (h >>> 0).toString(16).toUpperCase().padStart(8, '0')
  })()

  // --- FOND GUILLOCHÉ : fines lignes ondulées, teinte très claire.
  // Reste lisible sous le texte (les cartes opaques le recouvrent) et
  // survit à une impression noir & blanc en trame légère.
  const drawGuilloche = (spacing: number, amp: number, wl: number, phase: number) => {
    setDraw(GUILLOCHE)
    doc.setLineWidth(0.12)
    const x0 = 8
    const x1 = pageWidth - 8
    for (let y = 12; y <= pageHeight - 9; y += spacing) {
      let px = x0
      let py = y + Math.sin(phase) * amp
      for (let x = x0 + 2.5; x <= x1; x += 2.5) {
        const cy = y + Math.sin(((x - x0) / wl) * Math.PI * 2 + phase) * amp
        doc.line(px, py, x, cy)
        px = x
        py = cy
      }
    }
  }
  drawGuilloche(4.6, 1.1, 16, 0)
  drawGuilloche(4.6, 1.1, 16, Math.PI)

  // --- FILIGRANE DE SÉCURITÉ (diagonal, faible opacité) ---
  if (settings?.show_sortie_watermark !== false) {
    const watermarkText = String(settings?.sortie_watermark_text || 'PAYÉ').trim()
    if (watermarkText) {
      const opacityRaw = Number(settings?.sortie_watermark_opacity ?? 0.14)
      const opacity = Math.min(0.6, Math.max(0.05, Number.isFinite(opacityRaw) ? opacityRaw : 0.14))
      doc.setTextColor(210, 222, 216)
      doc.setFont('helvetica', 'bold')
      doc.setFontSize(74)
      try {
        doc.saveGraphicsState()
        const GState = (doc as any).GState
        if (GState && (doc as any).setGState) {
          const gs = new GState({ opacity })
          ;(doc as any).setGState(gs)
        }
        doc.text(watermarkText, pageWidth / 2, pageHeight / 2 + 8, { align: 'center', angle: 28 })
        doc.setFontSize(11)
        doc.text('ORIGINAL', pageWidth / 2, pageHeight / 2 + 26, { align: 'center', angle: 28 })
      } finally {
        doc.restoreGraphicsState()
      }
    }
  }

  // --- CADRE DE SÉCURITÉ (double filet + coins ornementaux) ---
  setDraw(GREEN)
  doc.setLineWidth(0.9)
  doc.rect(5, 5, pageWidth - 10, pageHeight - 10)
  doc.setLineWidth(0.3)
  doc.rect(7.5, 7.5, pageWidth - 15, pageHeight - 15)
  const corner = (cx: number, cy: number, dx: number, dy: number) => {
    doc.line(cx, cy, cx + dx, cy)
    doc.line(cx, cy, cx, cy + dy)
  }
  setDraw(GREEN_SOFT)
  doc.setLineWidth(1.1)
  corner(7.5, 7.5, 6, 6)
  corner(pageWidth - 7.5, 7.5, -6, 6)
  corner(7.5, pageHeight - 7.5, 6, -6)
  corner(pageWidth - 7.5, pageHeight - 7.5, -6, -6)

  // --- EN-TÊTE ---
  if (logoDataUrl) {
    doc.addImage(logoDataUrl, 'PNG', margin + 1, 10, 18, 18)
  }
  const headTextX = logoDataUrl ? margin + 22 : margin
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(13)
  setText(GREEN)
  doc.text(orgName.toUpperCase(), headTextX, 15)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8)
  setText(MUTED)
  if (subtitle) doc.text(String(subtitle).slice(0, 78), headTextX, 20)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(6.5)
  setText(GREEN_SOFT)
  doc.text('• PIÈCE DE TRÉSORERIE SÉCURISÉE • CASH DISBURSEMENT VOUCHER •', headTextX, 24.5)

  // Panneau série (N° BON) — style « serial » monospace
  const metaW = 84
  const metaH = 21
  const metaX = pageWidth - margin - metaW
  const metaY = 9
  setFill(GREEN)
  doc.roundedRect(metaX, metaY, metaW, metaH, 2.5, 2.5, 'F')
  setFill(GREEN_SOFT)
  doc.rect(metaX, metaY, 3, metaH, 'F')
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(6.8)
  doc.setTextColor(200, 224, 214)
  doc.text('N° BON / RÉFÉRENCE', metaX + 7, metaY + 6)
  doc.setFont('courier', 'bold')
  doc.setFontSize(12)
  doc.setTextColor(255, 255, 255)
  doc.text(String(ref).slice(0, 20), metaX + 7, metaY + 13)
  doc.setFont('courier', 'normal')
  doc.setFontSize(6.6)
  doc.setTextColor(200, 224, 214)
  doc.text(`${format(datePaiement, 'dd/MM/yyyy')}  ·  CLE ${securityToken}`, metaX + 7, metaY + 18)

  // --- FILET SÉPARATEUR (double) ---
  setDraw(GREEN)
  doc.setLineWidth(0.5)
  doc.line(margin, 32, pageWidth - margin, 32)
  setDraw(GREEN_SOFT)
  doc.setLineWidth(0.2)
  doc.line(margin, 33, pageWidth - margin, 33)

  // --- TITRE + STATUT ---
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(15)
  setText(INK)
  doc.text('BON DE SORTIE DE CAISSE', margin, 41)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  setText(MUTED)
  doc.text(
    `Document source : ${String(sourceNumero).slice(0, 26) || 'N/A'}${systemId ? `   ·   ID système : ${systemId.slice(0, 22)}` : ''}`,
    margin,
    46
  )

  const statusRaw = String(sortie?.statut || sortie?.status || '').toUpperCase()
  const statusLabel =
    statusRaw === 'VALIDE' || statusRaw === 'APPROUVEE' ? 'APPROUVÉ' :
    statusRaw === 'ANNULEE' ? 'ANNULÉ' :
    statusRaw === 'PAYEE' ? 'PAYÉ' : 'EN ATTENTE'
  const statusColor: [number, number, number] =
    statusLabel === 'APPROUVÉ' || statusLabel === 'PAYÉ' ? [22, 163, 74] :
    statusLabel === 'ANNULÉ' ? [220, 38, 38] :
    [245, 158, 11]
  const badgeW = 42
  const badgeH = 8
  const badgeX = pageWidth - margin - badgeW
  const badgeY = 37
  setFill(statusColor)
  doc.roundedRect(badgeX, badgeY, badgeW, badgeH, 2, 2, 'F')
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(8)
  doc.setTextColor(255, 255, 255)
  doc.text(statusLabel, badgeX + badgeW / 2, badgeY + 5.4, { align: 'center' })

  // --- CARTE D'INFORMATIONS ---
  const infoY = 49
  const infoH = 41
  setFill(CARD_BG)
  doc.roundedRect(margin, infoY, pageWidth - margin * 2, infoH, 2.5, 2.5, 'F')
  setDraw(HAIR)
  doc.setLineWidth(0.3)
  doc.roundedRect(margin, infoY, pageWidth - margin * 2, infoH, 2.5, 2.5, 'S')
  const splitX = margin + 150
  doc.setLineWidth(0.2)
  setDraw(HAIR)
  doc.line(splitX, infoY + 5, splitX, infoY + infoH - 5)

  const leftX = margin + 6
  const rightX = splitX + 8
  const drawLabel = (t: string, x: number, y: number) => {
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(6.8)
    setText(MUTED)
    doc.text(t.toUpperCase(), x, y)
  }

  // Colonne gauche : bénéficiaire + motif
  drawLabel('Bénéficiaire', leftX, infoY + 7)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(12)
  setText(INK)
  doc.text(String(sortie?.beneficiaire || '-').toUpperCase().slice(0, 42), leftX, infoY + 14)
  drawLabel('Motif', leftX, infoY + 22)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  setText(INK)
  const motifLines = doc.splitTextToSize(String(sortie?.motif || '-'), splitX - leftX - 6)
  doc.text(motifLines.slice(0, 2), leftX, infoY + 28)

  // Colonne droite : date, mode, source, poste
  drawLabel('Date', rightX, infoY + 7)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  setText(INK)
  doc.text(format(datePaiement, 'dd/MM/yyyy'), rightX, infoY + 12)

  const modeX = rightX + 60
  drawLabel('Mode de paiement', modeX, infoY + 7)
  const modeLabel =
    sortie?.mode_paiement === 'mobile_money'
      ? 'Mobile Money'
      : sortie?.mode_paiement === 'virement'
      ? 'Virement'
      : sortie?.mode_paiement === 'card'
      ? 'Carte (Visa)'
      : 'Cash'
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  setText(INK)
  doc.text(modeLabel, modeX, infoY + 12)

  drawLabel('Document source', rightX, infoY + 20)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(9)
  setText(INK)
  doc.text(String(sourceNumero).slice(0, 30), rightX, infoY + 25)

  drawLabel('Poste budgétaire', rightX, infoY + 33)
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(8.5)
  setText(INK)
  const maxPosteWidth = pageWidth - margin - rightX
  let posteValue = String(budgetLabel || '-')
  if (doc.getTextWidth(posteValue) > maxPosteWidth) {
    const ellipsis = '...'
    let trimmed = posteValue
    while (trimmed.length > 0 && doc.getTextWidth(`${trimmed}${ellipsis}`) > maxPosteWidth) {
      trimmed = trimmed.slice(0, -1)
    }
    posteValue = `${trimmed}${ellipsis}`
  }
  doc.text(posteValue, rightX, infoY + 38)

  let contentY = infoY + infoH + 7
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

  // --- BLOC MONTANT ---
  const montant = toNumber(sortie?.montant_paye || 0)
  const montantLettres = numberToWords(montant)
  const tauxSnapshot = sortie?.exchange_rate_snapshot
  const tauxLabel =
    tauxSnapshot && Number(tauxSnapshot) > 0 ? `Taux appliqué : 1 USD = ${formatAmount(tauxSnapshot)} CDF` : ''

  const amountY = contentY
  const amountH = 20
  setFill([241, 245, 249])
  doc.roundedRect(margin, amountY, pageWidth - margin * 2, amountH, 2.5, 2.5, 'F')
  setFill(GREEN)
  doc.rect(margin, amountY, 4, amountH, 'F')
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(7)
  setText(MUTED)
  doc.text('MONTANT TOTAL', margin + 9, amountY + 7)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(20)
  setText(INK)
  doc.text(`${formatAmount(montant)} ${String(sortie?.devise || 'USD').toUpperCase()}`, margin + 9, amountY + 16)

  const wordsX = margin + 122
  setDraw(HAIR)
  doc.setLineWidth(0.2)
  doc.line(wordsX - 8, amountY + 3, wordsX - 8, amountY + amountH - 3)
  doc.setFont('helvetica', 'italic')
  doc.setFontSize(8)
  setText(MUTED)
  doc.text('Arrêté à la somme de :', wordsX, amountY + 7)
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(8.5)
  setText(INK)
  const lettresLines = doc.splitTextToSize(montantLettres, pageWidth - margin - wordsX - 4)
  doc.text(lettresLines.slice(0, 2), wordsX, amountY + 12)
  if (tauxLabel) {
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7.5)
    setText(MUTED)
    doc.text(tauxLabel, wordsX, amountY + amountH - 2.5)
  }

  // --- CIRCUIT DE VALIDATION & EXÉCUTION ---
  const validationY = amountY + amountH + 12
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
  const colCount = 3
  const rows = Math.ceil(steps.length / colCount)
  const lineH = 5
  const boxTop = validationY - 6
  const boxH = 11 + rows * lineH
  setFill([250, 251, 252])
  doc.roundedRect(margin, boxTop, pageWidth - margin * 2, boxH, 2, 2, 'F')
  setDraw(HAIR)
  doc.setLineWidth(0.3)
  doc.roundedRect(margin, boxTop, pageWidth - margin * 2, boxH, 2, 2, 'S')
  doc.setFont('helvetica', 'bold')
  doc.setFontSize(8.5)
  setText(GREEN)
  doc.text('Circuit de validation & exécution', margin + 4, validationY)
  const colW = (pageWidth - margin * 2 - 8) / colCount
  steps.forEach((s, i) => {
    const col = i % colCount
    const row = Math.floor(i / colCount)
    const x = margin + 4 + col * colW
    const y = validationY + 6 + row * lineH
    setFill(GREEN_SOFT)
    doc.circle(x + 0.8, y - 1.1, 0.7, 'F')
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(7)
    setText(MUTED)
    doc.text(`${s.label} :`, x + 3, y)
    const lblW = doc.getTextWidth(`${s.label} : `)
    doc.setFont('helvetica', 'normal')
    setText(INK)
    doc.text(String(s.name).slice(0, 26), x + 3 + lblW, y)
  })

  // --- BANDEAU VÉRIFICATION & CACHET ---
  const verifY = 152
  const verifH = 22
  setFill([250, 251, 252])
  doc.roundedRect(margin, verifY, pageWidth - margin * 2, verifH, 2.5, 2.5, 'F')
  setDraw(HAIR)
  doc.setLineWidth(0.3)
  doc.roundedRect(margin, verifY, pageWidth - margin * 2, verifH, 2.5, 2.5, 'S')

  // QR de vérification (ancre d'authentification)
  if (settings?.show_sortie_qr !== false) {
    try {
      const qrCodeDataUrl = await QRCode.toDataURL(buildQrValue(), { margin: 0, width: 120 })
      const qrSize = 16
      const qrX = margin + 5
      const qrY = verifY + 3
      setFill([255, 255, 255])
      setDraw(HAIR)
      doc.setLineWidth(0.3)
      doc.roundedRect(qrX - 1.5, qrY - 1.5, qrSize + 3, qrSize + 3, 1.5, 1.5, 'FD')
      doc.addImage(qrCodeDataUrl, 'PNG', qrX, qrY, qrSize, qrSize)
      const capX = qrX + qrSize + 5
      doc.setFont('helvetica', 'bold')
      doc.setFontSize(8.5)
      setText(GREEN)
      doc.text('VÉRIFICATION', capX, verifY + 7)
      doc.setFont('helvetica', 'normal')
      doc.setFontSize(6.8)
      setText(MUTED)
      doc.text('Scannez le code pour authentifier ce bon.', capX, verifY + 11.5)
      doc.setFont('courier', 'normal')
      doc.setFontSize(6.5)
      setText(INK)
      doc.text(`REF ${String(ref).slice(0, 22)}`, capX, verifY + 16)
      doc.text(`CLE ${securityToken}`, capX, verifY + 19.5)
    } catch {
      // QR code optionnel : on continue sans échouer.
    }
  }

  // Zone « Cachet & signature »
  if (settings?.show_footer_signature !== false) {
    const sortieLabel = settings?.sortie_label_signature || settings?.recu_label_signature || 'Cachet & signature'
    const sortieNom = settings?.sortie_nom_signataire || settings?.recu_nom_signataire || ''
    const shouldRenderFooterName =
      String(sortieNom || '').trim() &&
      String(sortieNom || '').trim().toLowerCase() !== String(signataireFinalName || '').trim().toLowerCase()
    const signX = pageWidth - margin - 66
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(8)
    setText(GREEN)
    doc.text(sortieLabel, signX, verifY + 7)
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7)
    setText(MUTED)
    if (shouldRenderFooterName) doc.text(String(sortieNom).slice(0, 30), signX, verifY + 12)
    doc.setFontSize(6.3)
    setText(MUTED)
    doc.text('Apposer le cachet humide dans le cadre.', signX, verifY + 17)
    setDraw(HAIR)
    doc.setLineWidth(0.3)
    doc.roundedRect(pageWidth - margin - 24, verifY + 2, 20, verifH - 4, 2, 2, 'S')
    if (stampDataUrl) {
      doc.addImage(stampDataUrl, 'PNG', pageWidth - margin - 23, verifY + 2.5, 17, 17)
    }
  }

  // --- BLOCS DE SIGNATURE ---
  const sigGap = 6
  const sigW = (pageWidth - margin * 2 - sigGap * 2) / 3
  const sigH = 17
  const sigY = 177
  // Bloc 1 = Bénéficiaire (nom auto) · Bloc 2 = Caissier / exécutant (nom auto) ·
  // Bloc 3 = signataire paramétrable (libellé + nom depuis les réglages).
  const sigLabels = [
    settings?.sortie_sig_label_1 || 'BÉNÉFICIAIRE',
    settings?.sortie_sig_label_2 || 'CAISSIER',
    settings?.sortie_sig_label_3 || 'AUTORITÉ',
  ]
  const sigNames = [
    beneficiaireSignatureName,
    etablisseurName,
    signataireFinalName,
  ]
  const sigHint = settings?.sortie_sig_hint || 'Signature & date'
  for (let i = 0; i < 3; i += 1) {
    const x = margin + i * (sigW + sigGap)
    setFill([255, 255, 255])
    doc.rect(x, sigY, sigW, sigH, 'F')
    setDraw(HAIR)
    doc.setLineWidth(0.3)
    doc.rect(x, sigY, sigW, sigH, 'S')
    setFill(GREEN)
    doc.rect(x, sigY, sigW, 6, 'F')
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(7.5)
    doc.setTextColor(255, 255, 255)
    doc.text(sigLabels[i], x + sigW / 2, sigY + 4.2, { align: 'center' })
    doc.setFont('helvetica', 'bold')
    doc.setFontSize(8)
    setText(INK)
    doc.text(String(sigNames[i]).slice(0, 36), x + sigW / 2, sigY + 11, { align: 'center' })
    setDraw(HAIR)
    doc.setLineWidth(0.2)
    doc.line(x + 8, sigY + 13.5, x + sigW - 8, sigY + 13.5)
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(6)
    setText(MUTED)
    doc.text(sigHint, x + sigW / 2, sigY + 16, { align: 'center' })
  }

  // --- MICROTEXTE DE SÉCURITÉ (ligne fine répétée : réf + clé) ---
  const microUnit = ` ONEC-RDC · CONSEIL PROVINCIAL DE KINSHASA · BON ${ref} · CLE ${securityToken} ·`
  doc.setFont('helvetica', 'normal')
  doc.setFontSize(4)
  setText([168, 184, 176])
  let micro = ''
  const microMax = pageWidth - margin * 2 - 2
  while (micro.length < 1400 && doc.getTextWidth(micro + microUnit) < microMax) {
    micro += microUnit
  }
  if (micro) doc.text(micro, margin, 199)

  // --- PIED DE PAGE ---
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
