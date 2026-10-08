import jsPDF from 'jspdf'
import autoTable, { type UserOptions } from 'jspdf-autotable'
import { format } from 'date-fns'
import { numberToWords } from './numberToWords'
import { formatAmount, toNumber } from './amount'
import { API_BASE_URL, getAuthHeaders } from '../lib/apiClient'
import { buildUploadUrl } from './uploads'
import { makeTenantScopedCacheGuard } from './pdfTenantIdentity'

let cachedLogoDataUrl: string | null = null
let cachedLogoUrl: string | null = null
let cachedStampDataUrl: string | null = null
let cachedStampUrl: string | null = null
let cachedSettings: any | null = null

// Purge du cache d'identité dès que l'organisation courante change :
// sans cela un document émis après une bascule de tenant porterait le nom
// et le logo du tenant précédent.
const ensureTenantScopedPrintCache = makeTenantScopedCacheGuard(() => {
  cachedLogoDataUrl = null
  cachedLogoUrl = null
  cachedStampDataUrl = null
  cachedStampUrl = null
  cachedSettings = null
})

const getPrintSettingsData = async () => {
  ensureTenantScopedPrintCache()
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
  ensureTenantScopedPrintCache()
  if (cachedLogoDataUrl) return cachedLogoDataUrl
  try {
    if (!cachedLogoUrl) {
      const settings = await getPrintSettingsData()
      cachedLogoUrl = settings?.logo_url || null
    }
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
  ensureTenantScopedPrintCache()
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

/**
 * Place le logo dans une boîte fixe sans jamais le déformer.
 *
 * Les logos institutionnels sont souvent horizontaux. Les forcer dans un
 * carré rendait le texte et l'emblème visiblement écrasés sur l'état de frais.
 */
const addProportionalLogo = (
  doc: jsPDF,
  dataUrl: string,
  x: number,
  y: number,
  maxWidth: number,
  maxHeight: number
) => {
  try {
    const props = doc.getImageProperties(dataUrl)
    const ratio = props.width / props.height
    let width = maxWidth
    let height = width / ratio
    if (height > maxHeight) {
      height = maxHeight
      width = height * ratio
    }
    const format = String((props as any).fileType || 'PNG').toUpperCase()
    doc.addImage(
      dataUrl,
      format,
      x + (maxWidth - width) / 2,
      y + (maxHeight - height) / 2,
      width,
      height
    )
  } catch {
    // Mieux vaut omettre une image illisible que déformer l'identité visuelle.
  }
}

const normalizeHeaderLine = (value: unknown) =>
  String(value || '')
    .trim()
    .toLowerCase()
    .replace(/\s+/g, ' ')

const formatCommissionBeneficiaire = (remboursement: any) => {
  const serviceCode = String(
    remboursement?.service_code ||
    remboursement?.commission_code ||
    remboursement?.requisition?.service_code ||
    ''
  ).trim()
  const serviceLibelle = String(
    remboursement?.service_libelle ||
    remboursement?.commission_libelle ||
    remboursement?.requisition?.service_libelle ||
    ''
  ).trim()

  if (serviceCode && serviceLibelle) {
    return serviceLibelle.toLowerCase().includes(serviceCode.toLowerCase())
      ? serviceLibelle
      : `${serviceCode} - ${serviceLibelle}`
  }
  if (serviceCode) return serviceCode
  if (serviceLibelle) return serviceLibelle

  const instance = String(remboursement?.instance || '').trim()
  return instance || 'N/A'
}

const getTypeReunionLabel = (value: unknown) => {
  switch (String(value || '')) {
    case 'bureau':
      return 'Réunion du Bureau'
    case 'commission':
      return 'Réunion de la Commission permanente'
    case 'commission_ad_hoc':
      return 'Réunion de la Commission ad hoc'
    case 'conseil':
      return 'Réunion du Conseil'
    case 'atelier':
      return 'Atelier / Séminaire / Formation'
    default:
      return String(value || 'N/A')
  }
}

const formatFonctionParticipant = (p: any) => {
  const fonction = String(p?.titre_fonction || '').trim()
  if (p?.type_participant !== 'assistant') return fonction || '—'
  if (!fonction) return 'Assistant(e)'
  return /assistant/i.test(fonction) ? fonction : `${fonction}\nAssistant(e)`
}

const formatPersonName = (personne: any) =>
  personne ? `${personne.prenom || ''} ${personne.nom || ''}`.trim() : ''

const normalizeHour = (value: unknown) => {
  const hour = String(value || '').trim()
  const match = hour.match(/^(\d{1,2}):(\d{2})/)
  return match ? `${match[1].padStart(2, '0')}:${match[2]}` : hour
}

const getMeetingSchedule = (startValue: unknown, endValue: unknown) => {
  const start = normalizeHour(startValue)
  const end = normalizeHour(endValue)
  if (!start && !end) return 'Non renseigné'
  if (start && !end) return `Début : ${start}`
  if (!start && end) return `Fin : ${end}`

  const startMatch = start.match(/^(\d{2}):(\d{2})$/)
  const endMatch = end.match(/^(\d{2}):(\d{2})$/)
  let duration = ''
  if (startMatch && endMatch) {
    const startMinutes = Number(startMatch[1]) * 60 + Number(startMatch[2])
    const endMinutes = Number(endMatch[1]) * 60 + Number(endMatch[2])
    if (endMinutes >= startMinutes) {
      const durationMinutes = endMinutes - startMinutes
      const hours = Math.floor(durationMinutes / 60)
      const minutes = durationMinutes % 60
      const parts = [hours ? `${hours} h` : '', minutes ? `${minutes} min` : ''].filter(Boolean)
      duration = parts.length > 0 ? ` · durée ${parts.join(' ')}` : ''
    }
  }
  return `${start} – ${end}${duration}`
}

const openPdfInNewTab = (doc: jsPDF) => {
  const blob = doc.output('blob')
  const url = URL.createObjectURL(blob)
  window.open(url, '_blank', 'noopener,noreferrer')
  setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

const addFooter = (doc: jsPDF, pageNumber: number, pageCount: number, margin: number) => {
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  doc.setFontSize(8)
  doc.setFont('times', 'normal')
  doc.setTextColor(100)
  doc.text(`${format(new Date(), 'dd/MM/yyyy HH:mm')}`, margin, pageHeight - 6)
  const tenantLabel = cachedSettings?.organization_name?.trim()
  doc.text(tenantLabel ? `État de frais de déplacement - ${tenantLabel}` : 'État de frais de déplacement', pageWidth / 2, pageHeight - 6, { align: 'center' })
  doc.text(`Page ${pageNumber}/${pageCount}`, pageWidth - margin, pageHeight - 6, { align: 'right' })
}

export const generateRemboursementTransportPDF = async (
  remboursement: any,
  participants: any[],
  action: 'print' | 'download' | 'blob' = 'download',
  _userName?: string,
  paperFormat: 'a4' | 'a5' = 'a4',
  onBlob?: (blob: Blob, filename: string) => Promise<void>
) => {
  const settings = await getPrintSettingsData()
  const logoDataUrl = settings?.show_header_logo === false ? null : await getLogoDataUrl()
  const stampDataUrl = await getStampDataUrl()
  const isA5 = paperFormat === 'a5'
  const doc = new jsPDF({ orientation: 'p', unit: 'mm', format: paperFormat })
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  const margin = isA5 ? 10 : 15

  const beneficiaire = formatCommissionBeneficiaire(remboursement)

  const montantTotal = toNumber(remboursement.montant_total)
  const montantEnLettres = numberToWords(montantTotal)
  const lieu = String(remboursement.lieu || '').trim() || 'N/A'
  const objetReunion = String(remboursement.nature_reunion || '').trim() || 'N/A'
  const travaux: string[] = Array.isArray(remboursement.nature_travail)
    ? remboursement.nature_travail.map((item: unknown) => String(item || '').trim()).filter(Boolean)
    : []
  const horaires = getMeetingSchedule(remboursement.heure_debut, remboursement.heure_fin)
  const requisitionLiee = remboursement.requisition || {}
  // Jamais l'utilisateur connecté : c'est souvent un validateur ou la
  // trésorerie qui imprime, et son nom finirait sous « Le demandeur » d'une
  // pièce archivée. Demandeur inconnu = ligne vierge, signée à la main.
  const nomDemandeurBrut = formatPersonName(requisitionLiee.demandeur || remboursement.demandeur)
  const nomDemandeur = nomDemandeurBrut || 'Non renseigné'

  const dateReunion = remboursement.date_reunion ? new Date(remboursement.date_reunion) : new Date()
  const formattedDate = Number.isNaN(dateReunion.getTime()) ? 'N/A' : format(dateReunion, 'dd/MM/yyyy')

  // Échelle typographique unique du document : une seule table de tailles, dont
  // l'A5 est la réduction homothétique. Auparavant chaque bloc portait sa propre
  // paire de valeurs, si bien que le nom de l'organisation, le titre et le
  // numéro se disputaient le même poids visuel.
  const echelle = isA5
    ? { organisation: 10.5, sousTitre: 7.5, titre: 11.5, numero: 8.5, identification: 7.5, tableau: 8, lettres: 8, signature: 8.5 }
    : { organisation: 12.5, sousTitre: 9, titre: 14, numero: 10, identification: 9, tableau: 9.5, lettres: 9.5, signature: 10 }

  // Couleur d'accent unique. Le document mêlait un vert (46,125,50) pour
  // l'identification et un bleu (41,128,185) pour les participants : deux
  // familles sans rapport sur une même feuille, que rien ne hiérarchisait.
  const ACCENT: [number, number, number] = [46, 125, 50]
  const ACCENT_CLAIR: [number, number, number] = [237, 244, 237]
  const FILET: [number, number, number] = [205, 210, 205]

  // Le bandeau d'en-tête réservait 34 mm de haut quel que soit son contenu. Sa
  // hauteur découle désormais de celle du logo, ce qui rend une dizaine de
  // millimètres au tableau dès la première page.
  const hautBandeau = isA5 ? 8 : 9
  const largeurLogo = isA5 ? 21 : 27
  const hauteurLogo = isA5 ? 15 : 19
  if (logoDataUrl) {
    addProportionalLogo(doc, logoDataUrl, margin, hautBandeau, largeurLogo, hauteurLogo)
  }
  // Sans logo (paramétrage incomplet ou image indisponible), le texte reprend la
  // marge : décalé de la largeur d'un logo absent, il ouvrait à gauche une
  // encoche vide que rien ne justifiait.
  const headerX = logoDataUrl ? margin + largeurLogo + 4 : margin

  const organizationName = settings?.organization_name?.trim() || 'ONEC'
  const organizationKey = normalizeHeaderLine(organizationName)
  const seenHeaderLines = new Set([organizationKey])
  const subtitleLines = [
    settings?.organization_subtitle,
    settings?.header_text,
  ].filter((line): line is string => {
    const normalized = normalizeHeaderLine(line)
    if (!normalized || seenHeaderLines.has(normalized)) return false
    seenHeaderLines.add(normalized)
    return true
  }).slice(0, 3)

  doc.setFont('times', 'bold')
  doc.setFontSize(echelle.organisation)
  doc.setTextColor(0)
  doc.text(organizationName.toUpperCase(), headerX, hautBandeau + (isA5 ? 5 : 6))
  doc.setFont('times', 'normal')
  doc.setFontSize(echelle.sousTitre)
  // Les mentions légales sont un rappel, pas une information à lire : en gris
  // elles cessent de concurrencer le nom de l'organisation.
  doc.setTextColor(95)
  const interligneSousTitre = isA5 ? 3.2 : 3.8
  const premierSousTitre = isA5 ? 9.5 : 11.5
  subtitleLines.forEach((line, index) => {
    doc.text(line, headerX, hautBandeau + premierSousTitre + index * interligneSousTitre)
  })
  doc.setTextColor(0)

  // Le filet ferme le bandeau au plus près de ce qu'il contient : avec logo il
  // suit le bas de l'image, sans logo il suit la dernière mention imprimée.
  // Fixé à 34 mm quel que soit le contenu, il ouvrait jusqu'à 16 mm de blanc
  // au-dessus du titre lorsque le tenant n'avait ni logo ni sous-titre.
  const hauteurTexteEntete = premierSousTitre + Math.max(0, subtitleLines.length - 1) * interligneSousTitre + 2
  const hauteurBandeau = logoDataUrl ? Math.max(hauteurLogo, hauteurTexteEntete) : hauteurTexteEntete
  const yLigne = hautBandeau + hauteurBandeau + (isA5 ? 2 : 2.5)
  doc.setDrawColor(ACCENT[0], ACCENT[1], ACCENT[2])
  doc.setLineWidth(0.8)
  doc.line(margin, yLigne, pageWidth - margin, yLigne)

  // Titre puis numéro, tous deux en Times : le numéro passait au-dessus du
  // titre et en Helvetica, ce qui inversait la hiérarchie et mêlait deux
  // familles de caractères sur trois lignes.
  const transTitre = remboursement.trans_titre_officiel_hist || settings?.trans_titre_officiel || 'ÉTAT DE FRAIS DE DÉPLACEMENT'
  doc.setFont('times', 'bold')
  doc.setFontSize(echelle.titre)
  doc.setTextColor(0)
  const yTitre = yLigne + (isA5 ? 7 : 8)
  // Léger interlettrage : sur un titre court et capitalisé, il donne l'allure
  // d'un intitulé officiel sans exiger un corps plus gros. jsPDF en tient
  // compte dans le calcul du centrage, l'axe reste juste.
  doc.setCharSpace(isA5 ? 0.3 : 0.5)
  const lignesTitre = doc.splitTextToSize(
    String(transTitre).toUpperCase(),
    pageWidth - margin * 2 - (isA5 ? 4 : 12)
  ) as string[]
  const interligneTitre = isA5 ? 4.5 : 5.5
  lignesTitre.forEach((line, index) => {
    doc.text(line, pageWidth / 2, yTitre + index * interligneTitre, { align: 'center' })
  })
  doc.setCharSpace(0)

  let yApresTitre = yTitre + Math.max(0, lignesTitre.length - 1) * interligneTitre
  if (remboursement.reference_numero) {
    // Le numéro est une référence de classement, pas un second titre : maigre et
    // gris, il se lit sans disputer la vedette à l'intitulé.
    doc.setFont('times', 'normal')
    doc.setFontSize(echelle.numero)
    doc.setTextColor(85)
    const yReference = yApresTitre + (isA5 ? 4.5 : 5.5)
    doc.text(`N° ${remboursement.reference_numero}`, pageWidth / 2, yReference, { align: 'center' })
    yApresTitre = yReference
  }
  doc.setFont('times', 'normal')
  doc.setTextColor(0)

  // Identification appariée sur deux colonnes : les six lignes empilées
  // occupaient une cinquantaine de millimètres, soit le tiers haut de la page,
  // pour six valeurs souvent tenant en trois mots. Deux par deux, elles se
  // lisent en trois lignes et rendent une vingtaine de millimètres à la liste
  // des participants — l'équivalent de trois émargements de plus en page 1.
  // Colonnes dissymétriques : les valeurs de gauche (bénéficiaire, motif, type
  // de réunion) sont des phrases, celles de droite des données courtes (une
  // instance, une date, un lieu). Un partage à parts égales faisait retourner à
  // la ligne le seul nom du bénéficiaire alors qu'il restait 25 mm de vide en
  // face. Les largeurs sont calées sur les chaînes mesurées à 9 pt.
  const largeurLabel = isA5 ? 24 : 28
  const largeurValeurGauche = isA5 ? 52 : 74
  const largeurValeurDroite = pageWidth - margin * 2 - largeurLabel * 2 - largeurValeurGauche
  autoTable(doc, {
    startY: yApresTitre + (isA5 ? 3.5 : 4.5),
    theme: 'grid',
    // Pas de ligne d'en-tête : « Élément / Détail » n'apprenait rien que les
    // libellés de gauche ne disent déjà, pour une bande pleine de plus.
    body: [
      ['Bénéficiaire', beneficiaire.toUpperCase(), 'Instance', remboursement.instance || 'N/A'],
      ['Type de réunion', getTypeReunionLabel(remboursement.type_reunion), 'Date', formattedDate],
      ['Lieu', lieu, 'Horaires', horaires],
      ['Demandeur', nomDemandeur, 'Effectif', `${participants.length} participant${participants.length === 1 ? '' : 's'}`],
    ],
    styles: {
      // Un demi-point de moins que la liste : l'identification est le contexte,
      // les émargements sont l'objet du document. La hiérarchie passe par le
      // corps plutôt que par une bande de couleur supplémentaire.
      font: 'times',
      fontSize: echelle.identification,
      cellPadding: { top: isA5 ? 1.4 : 1.6, bottom: isA5 ? 1.4 : 1.6, left: 2.2, right: 2.2 },
      lineColor: FILET,
      lineWidth: 0.1,
      textColor: 25,
      valign: 'middle',
    },
    columnStyles: {
      0: { cellWidth: largeurLabel, fillColor: [246, 247, 246], fontStyle: 'bold', textColor: 70 },
      1: { cellWidth: largeurValeurGauche },
      2: { cellWidth: largeurLabel, fillColor: [246, 247, 246], fontStyle: 'bold', textColor: 70 },
      3: { cellWidth: largeurValeurDroite },
    },
    margin: { left: margin, right: margin },
  })

  let yPos = (doc as any).lastAutoTable.finalY + (isA5 ? 3 : 4)

  // Le lecteur doit comprendre la réunion avant de lire les montants. L'objet
  // et les travaux saisis sont donc réunis dans un bloc dédié au lieu de se
  // remplacer mutuellement dans une seule cellule « Motif ».
  const contexteReunion = [
    { content: objetReunion, styles: { fontStyle: 'bold' as const, textColor: 20 } },
    ...travaux.map((travail: string, index: number) => ({
      content: `${index + 1}. ${travail}`,
      styles: { textColor: 45 },
    })),
  ]
  autoTable(doc, {
    startY: yPos,
    theme: 'grid',
    head: [[travaux.length > 0 ? 'OBJET ET TRAVAUX DE LA RÉUNION' : 'OBJET DE LA RÉUNION']],
    body: contexteReunion.map((entry) => [entry]),
    styles: {
      font: 'times',
      fontSize: echelle.identification,
      cellPadding: { top: isA5 ? 1.2 : 1.4, bottom: isA5 ? 1.2 : 1.4, left: 2.2, right: 2.2 },
      lineColor: FILET,
      lineWidth: 0.1,
      overflow: 'linebreak',
    },
    headStyles: {
      fillColor: ACCENT_CLAIR,
      textColor: ACCENT,
      fontStyle: 'bold',
      lineColor: FILET,
    },
    margin: { left: margin, right: margin },
  })
  yPos = (doc as any).lastAutoTable.finalY + (isA5 ? 4 : 5)

  const totalParticipants = participants.reduce((somme, p: any) => somme + (toNumber(p.montant) || 0), 0)

  // Somme en lettres et bloc de signature sont mesurés avant la pagination du
  // tableau : leur hauteur est réservée en marge basse pour que la coupure tombe
  // à l'intérieur de la liste. Sans cette réserve, une liste qui remplit la page
  // rejetait les signatures seules sur une feuille vierge — on faisait signer un
  // feuillet ne portant ni nom ni montant.
  doc.setFont('times', 'italic')
  doc.setFontSize(echelle.lettres)
  const lignesLettres = doc.splitTextToSize(
    `Arrêté le présent état à la somme de : ${montantEnLettres} ($ ${formatAmount(montantTotal)}).`,
    pageWidth - margin * 2
  ) as string[]
  doc.setFont('times', 'normal')
  const hauteurLettres = lignesLettres.length * (isA5 ? 3.6 : 4.4)

  // Hauteur réelle du bloc de signature : deux lignes de texte, un trait
  // d'apposition, et le cachet seulement s'il existe. L'ancienne valeur
  // forfaitaire réservait la place d'un cachet même absent.
  const hauteurCachet = stampDataUrl ? (isA5 ? 22 : 28) : 0
  const afficheQr = settings?.afficher_qr_code !== false
  const qrSize = isA5 ? 14 : 18
  // Deux rangées : le demandeur et le Secrétaire exécutif attestent l'état de
  // frais, les signataires statutaires l'autorisent. La réserve de bas de page
  // compte donc un pas de rangée de plus, sinon la seconde tombe sous le filet
  // de pied de page.
  // Pas large : trop serré, le libellé statutaire venait toucher le trait du
  // demandeur et les deux rangées n'en formaient plus qu'une.
  const pasRangeeSignature = isA5 ? 25 : 30
  const hauteurSignatures = (isA5 ? 20 : 22) + pasRangeeSignature + hauteurCachet
  // Respiration avant les signatures : à 7 mm le bloc « Vu par… » touchait la
  // somme en lettres et se lisait comme la suite du tableau. Un blanc franc
  // sépare ce qui est déclaré de ce qui est signé.
  const espaceAvantSignatures = isA5 ? 12 : 15
  const hauteurPied = isA5 ? 12 : 14
  const hauteurQueue = hauteurLettres + espaceAvantSignatures + hauteurSignatures

  if (participants.length > 0) {
    const participantsData = participants.map((p: any, index: number) => [
      index + 1,
      String(p.nom || '').toUpperCase(),
      // Sans repli, un participant sans fonction laissait une cellule vide au
      // milieu du tableau, qu'on ne distingue pas d'un oubli d'impression.
      // La fonction d'un assistant vaut déjà souvent « Assistant(e) » : la
      // mention ne s'ajoute que si elle n'y figure pas, sinon elle s'imprimait
      // deux fois dans la cellule.
      formatFonctionParticipant(p),
      `${formatAmount(p.montant)} $`,
      // Cellule laissée nue : la bordure de la grille fait déjà l'espace de
      // signature, la ligne de pointillés le mangeait.
      '',
    ])
    const optionsTableau = (body: any[][], startY: number, avecTotal: boolean): UserOptions => ({
      startY,
      theme: 'grid' as const,
      head: [['N°', 'Nom & Postnom', 'Fonction', 'Montant', 'Émargement']],
      body,
      // Le total en pied donne au signataire de quoi recouper la somme
      // déclarée sans additionner à la main. Il est fusionné sur les trois
      // premières colonnes et calé à droite pour venir toucher le montant :
      // isolé dans la colonne des noms, il s'en trouvait à deux colonnes.
      foot: avecTotal ? [[
        { content: 'TOTAL GÉNÉRAL', colSpan: 3, styles: { halign: 'right' as const } },
        `${formatAmount(totalParticipants)} $`,
        '',
      ]] : [],
      styles: {
        font: 'times',
        fontSize: echelle.tableau,
        cellPadding: { top: isA5 ? 1.6 : 1.7, bottom: isA5 ? 1.6 : 1.7, left: 2.2, right: 2.2 },
        lineColor: FILET,
        lineWidth: 0.1,
        textColor: 25,
        valign: 'middle',
      },
      // La colonne Émargement reçoit une signature manuscrite : à la hauteur
      // d'une ligne de texte, le paraphe débordait sur la ligne voisine et on
      // ne savait plus qui avait signé quoi. Chaque ligne du corps réserve donc
      // la hauteur d'un paraphe — minCellHeight plutôt que du rembourrage seul,
      // qui laissait retomber les lignes d'un seul mot. L'en-tête et le total
      // gardent leur hauteur : ils ne se signent pas.
      bodyStyles: {
        cellPadding: { top: isA5 ? 2.4 : 3, bottom: isA5 ? 2.4 : 3, left: 2.2, right: 2.2 },
        minCellHeight: isA5 ? 10 : 13,
      },
      // Pas de halign dans headStyles : sans cela l'en-tête forçait tout à
      // gauche et « Montant » se retrouvait décalé de la colonne de chiffres
      // qu'il annonce. Chaque intitulé suit désormais l'alignement de sa colonne.
      headStyles: { fillColor: ACCENT, textColor: 255, fontStyle: 'bold', lineColor: ACCENT },
      footStyles: { fillColor: ACCENT_CLAIR, textColor: 20, fontStyle: 'bold' },
      // Une trame très claire une ligne sur deux : sur vingt émargements, elle
      // évite de suivre la ligne du doigt pour rattacher un nom à son montant.
      alternateRowStyles: { fillColor: [248, 250, 248] },
      // Le tableau descend jusqu'au pied de page. Il réservait auparavant, en
      // bas de chaque page, la hauteur de la somme en lettres et des
      // signatures : un bloc qui ne s'imprime qu'une fois, à la fin, laissait
      // ainsi une dizaine de centimètres vides au bas de la première page.
      margin: { left: margin, right: margin, top: margin, bottom: hauteurPied },
      // En-tête répété : sur une liste qui déborde, la page suivante n'affichait
      // que des colonnes de chiffres sans intitulé.
      showHead: 'everyPage' as const,
      showFoot: 'lastPage' as const,
      columnStyles: {
        0: { cellWidth: isA5 ? 8 : 10, halign: 'center' as const, textColor: 110 },
        1: { cellWidth: isA5 ? 42 : 52 },
        2: { cellWidth: isA5 ? 34 : 46 },
        3: { cellWidth: isA5 ? 20 : 24, halign: 'right' as const },
        4: { cellWidth: 'auto' as const, halign: 'center' as const },
      },
    })
    const ecartApresTableau = isA5 ? 7 : 9
    const queueTient = (finalY: number) => finalY + ecartApresTableau + hauteurQueue <= pageHeight - hauteurPied

    // Mesure à blanc sur un document jetable : la queue (somme en lettres,
    // signatures) tient-elle sous la dernière ligne ?
    const essai = new jsPDF({ orientation: 'p', unit: 'mm', format: paperFormat })
    autoTable(essai, optionsTableau(participantsData, yPos, true))
    if (queueTient((essai as any).lastAutoTable.finalY)) {
      autoTable(doc, optionsTableau(participantsData, yPos, true))
    } else {
      // Sinon la dernière ligne passe avec le total et les signatures sur la
      // page suivante : des signatures seules sur une page ne se
      // rattacheraient à aucun participant. Une seule ligne suffit ; en
      // reporter davantage creusait un blanc au bas de la page précédente.
      const lignesReportees = 1
      const coupure = participantsData.length - lignesReportees
      if (coupure > 0) {
        autoTable(doc, optionsTableau(participantsData.slice(0, coupure), yPos, false))
        doc.addPage()
      }
      autoTable(doc, optionsTableau(participantsData.slice(coupure), coupure > 0 ? margin : yPos, true))
    }
    yPos = (doc as any).lastAutoTable.finalY + ecartApresTableau
  }

  // Pas d'encadré pour le montant : le tableau porte déjà sa ligne TOTAL, un
  // second bloc répétait la même somme en mangeant une vingtaine de
  // millimètres — de la place en moins pour les participants. Reste la somme
  // en lettres, qui elle ne figure nulle part ailleurs, sur une seule ligne.
  if (yPos + hauteurQueue > pageHeight - hauteurPied) {
    doc.addPage()
    yPos = margin
  }
  doc.setFont('times', 'italic')
  doc.setFontSize(echelle.lettres)
  doc.setTextColor(0)
  doc.text(lignesLettres, margin, yPos)
  doc.setFont('times', 'normal')
  yPos += hauteurLettres + espaceAvantSignatures

  const labelGauche =
    remboursement.signataire_g_label ||
    remboursement.trans_label_gauche_hist ||
    settings?.trans_label_gauche ||
    'Vu par la Trésorière'
  const labelDroite =
    remboursement.signataire_d_label ||
    remboursement.trans_label_droite_hist ||
    settings?.trans_label_droite ||
    'Approuvé par :'
  const nomGauche =
    remboursement.signataire_g_nom ||
    remboursement.trans_nom_gauche_hist ||
    settings?.trans_nom_gauche ||
    'Esther BIMPE'
  const nomDroite =
    remboursement.signataire_d_nom ||
    remboursement.trans_nom_droite_hist ||
    settings?.trans_nom_droite ||
    '................................'

  // Le demandeur signe ce qu'il sollicite, le Secrétaire exécutif ce qu'il a
  // examiné. Le Secrétaire exécutif est un poste : son libellé et son nom
  // viennent des paramètres d'impression, et à défaut de l'examinateur de la
  // réquisition rattachée — c'est le plus souvent la même personne. Sans l'un
  // ni l'autre la ligne reste vierge : un état tiré avant l'examen se signe à
  // la main.
  const labelSecretaire = settings?.secretaire_executif_label || 'Le Secrétaire exécutif'
  const nomSecretaire = settings?.secretaire_executif_nom || formatPersonName(requisitionLiee.examinateur)

  const colonneDroiteX = pageWidth / 2 + (isA5 ? 4 : 6)
  // Largeur des traits calée pour laisser au QR sa colonne à l'extrême droite :
  // le second trait s'arrêtait auparavant à quelques millimètres du bord et ne
  // laissait aucune place ailleurs qu'en dessous.
  const largeurTrait = isA5 ? 42 : 58
  // Un nom réduit à des pointillés faisait doublon avec le trait d'apposition
  // tracé juste dessous : on ne pose que les noms réellement renseignés.
  const nomImprimable = (valeur: string) => (/^[\s.·_-]*$/.test(valeur) ? '' : valeur)

  const dessinerSignature = (x: number, y: number, label: string, nom: string) => {
    doc.setFontSize(echelle.signature)
    doc.setFont('times', 'bold')
    doc.setTextColor(0)
    doc.text(label, x, y)

    doc.setFont('times', 'normal')
    doc.text(nomImprimable(nom), x, y + (isA5 ? 4.5 : 5.5))

    // Trait d'apposition : sans lui, la signature manuscrite n'a pas de repère
    // et vient se poser sur le nom imprimé.
    doc.setDrawColor(150)
    doc.setLineWidth(0.2)
    const yTraitRangee = y + (isA5 ? 12 : 15)
    doc.line(x, yTraitRangee, x + largeurTrait, yTraitRangee)
  }

  const yRangeeStatutaire = yPos + pasRangeeSignature
  dessinerSignature(margin, yPos, 'Le demandeur', nomDemandeurBrut)
  dessinerSignature(colonneDroiteX, yPos, labelSecretaire, nomSecretaire)
  dessinerSignature(margin, yRangeeStatutaire, labelGauche, nomGauche)
  dessinerSignature(colonneDroiteX, yRangeeStatutaire, labelDroite, nomDroite)

  // Le cachet accompagne la signature statutaire, pas celle du demandeur.
  const yTrait = yRangeeStatutaire + (isA5 ? 12 : 15)

  if (stampDataUrl) {
    const stampSize = isA5 ? 22 : 28
    doc.addImage(stampDataUrl, 'PNG', colonneDroiteX + largeurTrait - stampSize, yTrait + 2, stampSize, stampSize)
  }

  if (afficheQr) {
    try {
      const { default: QRCode } = await import('qrcode')
      const qrDate = !Number.isNaN(dateReunion.getTime()) ? format(dateReunion, 'yyyyMMdd') : '00000000'
      const qrData = `TRANS-${remboursement.id}-${formatAmount(montantTotal)}USD-${qrDate}`
      const qrCodeUrl = await QRCode.toDataURL(qrData, { margin: 1, width: 120 })
      // Le QR occupe la colonne restée libre à droite des signatures, à leur
      // hauteur : posé sous le bloc, il ajoutait près de 30 mm de queue et
      // suffisait à rejeter les signatures sur une page supplémentaire.
      const qrX = pageWidth - margin - qrSize
      const qrY = yPos - (isA5 ? 3 : 3.5)
      doc.addImage(qrCodeUrl, 'PNG', qrX, qrY, qrSize, qrSize)
      doc.setFontSize(6)
      doc.setTextColor(120)
      doc.text('Vérification', qrX + qrSize / 2, qrY + qrSize + 2.6, { align: 'center' })
      doc.setTextColor(0)
    } catch {
      // ignore QR code failures
    }
  }

  doc.setProperties({
    title: `État de frais ${remboursement.reference_numero || remboursement.numero_remboursement || ''}`.trim(),
    subject: 'Remboursement de frais de transport',
    author: cachedSettings?.organization_name?.trim() || 'ONEC',
    creator: 'ONEC Smart',
  })

  const pageCount = doc.getNumberOfPages()
  for (let pageNumber = 1; pageNumber <= pageCount; pageNumber += 1) {
    doc.setPage(pageNumber)
    addFooter(doc, pageNumber, pageCount, margin)
  }

  const rawNumber = remboursement.reference_numero || remboursement.numero_remboursement || 'remboursement_transport'
  const safeNumber = String(rawNumber).trim().replace(/[\\/:*?"<>|]+/g, '-')
  const filename = `${safeNumber}.pdf`
  const blob = doc.output('blob')
  if (onBlob) {
    await onBlob(blob, filename)
  }
  if (action === 'print') {
    openPdfInNewTab(doc)
  } else if (action === 'blob') {
    return blob
  } else {
    doc.save(filename)
  }
}

export type ListePresenceReunion = {
  service_code?: string | null
  service_libelle?: string | null
  instance?: string | null
  type_reunion?: string | null
  nature_reunion?: string | null
  nature_travail?: string[]
  lieu?: string | null
  date_reunion?: string | null
  heure_debut?: string | null
  heure_fin?: string | null
}

export type ListePresencePersonne = {
  nom: string
  titre_fonction?: string | null
  type_participant: 'principal' | 'assistant'
}

/**
 * Liste de présence à faire remplir en séance, imprimée depuis le brouillon du
 * remboursement de transport. Les lignes sont vierges : chaque présent y écrit
 * lui-même son nom, son post-nom, son prénom et sa qualité, puis signe. Il y a
 * une ligne par participant prévu, plus des lignes de réserve. La liste se
 * clôt par le décompte et la signature du secrétaire et du président de séance.
 * Une fois signée, elle sert à cocher les présences dans le brouillon : seuls
 * les présents seront remboursés.
 */
export const generateListePresencePDF = async (
  reunion: ListePresenceReunion,
  personnes: ListePresencePersonne[],
  lignesVierges = 5,
) => {
  const settings = await getPrintSettingsData()
  const logoDataUrl = settings?.show_header_logo === false ? null : await getLogoDataUrl()
  const doc = new jsPDF({ orientation: 'p', unit: 'mm', format: 'a4' })
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  const margin = 15
  const ACCENT: [number, number, number] = [46, 125, 50]
  const FILET: [number, number, number] = [205, 210, 205]

  // En-tête : même identité que l'état de frais.
  const largeurLogo = 27
  const hauteurLogo = 19
  if (logoDataUrl) addProportionalLogo(doc, logoDataUrl, margin, 9, largeurLogo, hauteurLogo)
  const headerX = logoDataUrl ? margin + largeurLogo + 4 : margin
  const organizationName = settings?.organization_name?.trim() || 'ONEC'
  const seen = new Set([normalizeHeaderLine(organizationName)])
  const subtitleLines = [settings?.organization_subtitle, settings?.header_text]
    .filter((line): line is string => {
      const n = normalizeHeaderLine(line)
      if (!n || seen.has(n)) return false
      seen.add(n)
      return true
    })
    .slice(0, 3)
  doc.setFont('times', 'bold')
  doc.setFontSize(12.5)
  doc.setTextColor(0)
  doc.text(organizationName.toUpperCase(), headerX, 15)
  doc.setFont('times', 'normal')
  doc.setFontSize(9)
  doc.setTextColor(95)
  subtitleLines.forEach((line, i) => doc.text(line, headerX, 20.5 + i * 3.8))
  const hauteurTexte = 11.5 + Math.max(0, subtitleLines.length - 1) * 3.8 + 2
  const yLigne = 9 + (logoDataUrl ? Math.max(hauteurLogo, hauteurTexte) : hauteurTexte) + 2.5
  doc.setDrawColor(ACCENT[0], ACCENT[1], ACCENT[2])
  doc.setLineWidth(0.8)
  doc.line(margin, yLigne, pageWidth - margin, yLigne)

  doc.setFont('times', 'bold')
  doc.setFontSize(15)
  doc.setTextColor(0)
  doc.setCharSpace(0.6)
  doc.text('LISTE DE PRÉSENCE', pageWidth / 2, yLigne + 9, { align: 'center' })
  doc.setCharSpace(0)

  const commission = formatCommissionBeneficiaire(reunion)
  const dateReunion = reunion.date_reunion ? new Date(reunion.date_reunion) : null
  const dateLabel = dateReunion && !Number.isNaN(dateReunion.getTime()) ? format(dateReunion, 'dd/MM/yyyy') : '....../....../..........'
  const travaux = (reunion.nature_travail || []).map((t) => String(t || '').trim()).filter(Boolean)
  const objet = [String(reunion.nature_reunion || '').trim(), ...travaux.map((t, i) => `${i + 1}. ${t}`)]
    .filter(Boolean)
    .join('\n')

  autoTable(doc, {
    startY: yLigne + 14,
    theme: 'grid',
    body: [
      ['Commission / Service', commission.toUpperCase(), 'Date', dateLabel],
      ['Type de réunion', getTypeReunionLabel(reunion.type_reunion), 'Horaires', getMeetingSchedule(reunion.heure_debut, reunion.heure_fin)],
      ['Lieu', String(reunion.lieu || '').trim() || '................................', 'Prévus', `${personnes.length}`],
      ...(objet ? [[{ content: 'Objet', styles: { fillColor: [246, 247, 246] as [number, number, number], fontStyle: 'bold' as const, textColor: 70 } }, { content: objet, colSpan: 3 }]] : []),
    ],
    styles: { font: 'times', fontSize: 9, cellPadding: 1.6, lineColor: FILET, lineWidth: 0.1, textColor: 25, valign: 'middle' },
    columnStyles: {
      0: { cellWidth: 34, fillColor: [246, 247, 246], fontStyle: 'bold', textColor: 70 },
      1: { cellWidth: 74 },
      2: { cellWidth: 22, fillColor: [246, 247, 246], fontStyle: 'bold', textColor: 70 },
    },
    margin: { left: margin, right: margin },
  })

  // Tableau d'émargement vierge : une ligne haute par présent, la place
  // d'écrire à la main et de signer. Au moins 15 lignes, pour remplir la page.
  const nbLignes = Math.max(personnes.length + lignesVierges, 15)
  const body = Array.from({ length: nbLignes }, (_, i) => [String(i + 1), '', '', '', '', ''])

  autoTable(doc, {
    startY: (doc as any).lastAutoTable.finalY + 5,
    theme: 'grid',
    head: [['N°', 'Nom', 'Post-nom', 'Prénom', 'Qualité / Fonction', 'Signature']],
    body,
    styles: { font: 'times', fontSize: 9.5, cellPadding: 1.8, lineColor: [150, 155, 150], lineWidth: 0.2, textColor: 20, valign: 'middle', minCellHeight: 10 },
    headStyles: { fillColor: ACCENT, textColor: 255, fontStyle: 'bold', fontSize: 9.5, minCellHeight: 8, halign: 'center' },
    columnStyles: {
      0: { cellWidth: 9, halign: 'center', textColor: 90 },
      1: { cellWidth: 33 },
      2: { cellWidth: 33 },
      3: { cellWidth: 30 },
      4: { cellWidth: 34 },
      5: { cellWidth: 'auto' },
    },
    margin: { left: margin, right: margin, bottom: 16 },
  })

  // Clôture : décompte et signatures de séance.
  let y = (doc as any).lastAutoTable.finalY + 8
  if (y > pageHeight - 42) {
    doc.addPage()
    y = 25
  }
  doc.setFont('times', 'normal')
  doc.setFontSize(10)
  doc.setTextColor(0)
  doc.text(
    'Arrêtée la présente liste à ........ personnes présentes.',
    margin,
    y,
  )
  y += 12
  doc.setFont('times', 'bold')
  doc.text('Le Secrétaire de séance', margin + 30, y, { align: 'center' })
  doc.text('Le Président de séance', pageWidth - margin - 30, y, { align: 'center' })
  doc.setDrawColor(150)
  doc.setLineWidth(0.2)
  doc.line(margin + 5, y + 16, margin + 55, y + 16)
  doc.line(pageWidth - margin - 55, y + 16, pageWidth - margin - 5, y + 16)

  const pageCount = doc.getNumberOfPages()
  for (let i = 1; i <= pageCount; i += 1) {
    doc.setPage(i)
    doc.setFont('times', 'normal')
    doc.setFontSize(8)
    doc.setTextColor(100)
    doc.text(format(new Date(), 'dd/MM/yyyy HH:mm'), margin, pageHeight - 6)
    doc.text(`Liste de présence - ${organizationName}`, pageWidth / 2, pageHeight - 6, { align: 'center' })
    doc.text(`Page ${i}/${pageCount}`, pageWidth - margin, pageHeight - 6, { align: 'right' })
  }

  openPdfInNewTab(doc)
}

export type RecapitulatifTransportDossier = {
  reference?: string | null
  description?: string | null
}

const cleRecapitulatif = (p: any) => {
  if (p?.expert_comptable_id) return `expert:${p.expert_comptable_id}`
  const nom = String(p?.nom || '')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, ' ')
    .trim()
  return `nom:${nom}`
}

/**
 * État récapitulatif d'un dossier qui regroupe plusieurs remboursements de
 * transport, en paysage. Chaque état de frais reste la pièce source, intacte ;
 * ce document les condense : une ligne par personne, une colonne par réunion.
 * Une personne présente à la première réunion et absente aux suivantes n'a de
 * montant que dans la première colonne, « — » ailleurs : on ne rembourse que
 * les présences portées sur les états sources.
 */
export const generateRecapitulatifTransportPDF = async (
  dossier: RecapitulatifTransportDossier,
  remboursements: any[],
  action: 'print' | 'download' = 'print',
) => {
  const reunions = [...remboursements].sort((a, b) => {
    const da = new Date(a?.date_reunion || 0).getTime()
    const db = new Date(b?.date_reunion || 0).getTime()
    return (Number.isNaN(da) ? 0 : da) - (Number.isNaN(db) ? 0 : db)
  })

  type Ligne = { nom: string; fonction: string; assistant: boolean; montants: (number | null)[] }
  const lignes = new Map<string, Ligne>()
  reunions.forEach((reunion, index) => {
    const participants: any[] = Array.isArray(reunion?.participants) ? reunion.participants : []
    participants.forEach((p) => {
      if (!String(p?.nom || '').trim()) return
      const cle = cleRecapitulatif(p)
      let ligne = lignes.get(cle)
      if (!ligne) {
        ligne = {
          nom: String(p.nom).trim(),
          fonction: formatFonctionParticipant(p),
          assistant: p.type_participant === 'assistant',
          montants: reunions.map(() => null),
        }
        lignes.set(cle, ligne)
      }
      ligne.montants[index] = (ligne.montants[index] ?? 0) + toNumber(p.montant)
    })
  })
  // Les membres d'abord, les assistants ensuite, comme sur les états sources.
  const personnes = [...lignes.values()].sort((a, b) => Number(a.assistant) - Number(b.assistant))

  const totauxReunions = reunions.map((_, i) =>
    personnes.reduce((s, p) => s + (p.montants[i] ?? 0), 0),
  )
  const totalGeneral = totauxReunions.reduce((s, v) => s + v, 0)

  const settings = await getPrintSettingsData()
  const logoDataUrl = settings?.show_header_logo === false ? null : await getLogoDataUrl()
  const doc = new jsPDF({ orientation: 'l', unit: 'mm', format: 'a4' })
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  const margin = 12
  const ACCENT: [number, number, number] = [46, 125, 50]
  const ACCENT_CLAIR: [number, number, number] = [237, 244, 237]
  const FILET: [number, number, number] = [205, 210, 205]

  // En-tête : même identité que l'état de frais.
  const largeurLogo = 24
  const hauteurLogo = 17
  if (logoDataUrl) addProportionalLogo(doc, logoDataUrl, margin, 8, largeurLogo, hauteurLogo)
  const headerX = logoDataUrl ? margin + largeurLogo + 4 : margin
  const organizationName = settings?.organization_name?.trim() || 'ONEC'
  const seen = new Set([normalizeHeaderLine(organizationName)])
  const subtitleLines = [settings?.organization_subtitle, settings?.header_text]
    .filter((line): line is string => {
      const n = normalizeHeaderLine(line)
      if (!n || seen.has(n)) return false
      seen.add(n)
      return true
    })
    .slice(0, 3)
  doc.setFont('times', 'bold')
  doc.setFontSize(12.5)
  doc.setTextColor(0)
  doc.text(organizationName.toUpperCase(), headerX, 14)
  doc.setFont('times', 'normal')
  doc.setFontSize(9)
  doc.setTextColor(95)
  subtitleLines.forEach((line, i) => doc.text(line, headerX, 19.5 + i * 3.8))
  const hauteurTexte = 11.5 + Math.max(0, subtitleLines.length - 1) * 3.8 + 2
  const yLigne = 8 + (logoDataUrl ? Math.max(hauteurLogo, hauteurTexte) : hauteurTexte) + 2.5
  doc.setDrawColor(ACCENT[0], ACCENT[1], ACCENT[2])
  doc.setLineWidth(0.8)
  doc.line(margin, yLigne, pageWidth - margin, yLigne)

  doc.setFont('times', 'bold')
  doc.setFontSize(14)
  doc.setTextColor(0)
  doc.setCharSpace(0.5)
  doc.text('ÉTAT RÉCAPITULATIF DES FRAIS DE DÉPLACEMENT', pageWidth / 2, yLigne + 8, { align: 'center' })
  doc.setCharSpace(0)
  doc.setFont('times', 'normal')
  doc.setFontSize(10)
  doc.text(
    `Dossier ${String(dossier?.reference || '').trim() || 'N/A'} · ${reunions.length} réunion${reunions.length > 1 ? 's' : ''}`,
    pageWidth / 2,
    yLigne + 13.5,
    { align: 'center' },
  )

  // Les réunions du dossier, chacune renvoyant à son état de frais source.
  const formatDateReunion = (value: unknown) => {
    const d = value ? new Date(String(value)) : null
    return d && !Number.isNaN(d.getTime()) ? format(d, 'dd/MM/yyyy') : 'N/A'
  }
  autoTable(doc, {
    startY: yLigne + 17,
    theme: 'grid',
    head: [['Réunion', 'Date', 'État de frais', 'Commission / Service', 'Objet', 'Lieu', 'Présents', 'Montant']],
    body: reunions.map((r, i) => [
      `R${i + 1}`,
      formatDateReunion(r?.date_reunion),
      String(r?.reference_numero || r?.numero_remboursement || '—'),
      formatCommissionBeneficiaire(r),
      String(r?.nature_reunion || '').trim() || 'N/A',
      String(r?.lieu || '').trim() || 'N/A',
      String(Array.isArray(r?.participants) ? r.participants.length : 0),
      `${formatAmount(totauxReunions[i])} $`,
    ]),
    styles: { font: 'times', fontSize: 8.5, cellPadding: 1.3, lineColor: FILET, lineWidth: 0.1, textColor: 25, valign: 'middle' },
    headStyles: { fillColor: ACCENT_CLAIR, textColor: 40, fontStyle: 'bold' },
    columnStyles: {
      0: { cellWidth: 16, halign: 'center', fontStyle: 'bold' },
      1: { cellWidth: 22, halign: 'center' },
      2: { cellWidth: 32 },
      3: { cellWidth: 50 },
      5: { cellWidth: 36 },
      6: { cellWidth: 18, halign: 'center' },
      7: { cellWidth: 26, halign: 'right' },
    },
    margin: { left: margin, right: margin },
  })

  autoTable(doc, {
    startY: (doc as any).lastAutoTable.finalY + 5,
    theme: 'grid',
    head: [[
      'N°',
      'Nom & Postnom',
      'Fonction',
      ...reunions.map((r, i) => `R${i + 1}\n${formatDateReunion(r?.date_reunion)}`),
      'Séances',
      'Total',
      'Émargement',
    ]],
    body: personnes.map((p, index) => [
      index + 1,
      p.nom.toUpperCase(),
      p.fonction,
      ...p.montants.map((m) => (m == null ? '—' : `${formatAmount(m)} $`)),
      String(p.montants.filter((m) => m != null).length),
      `${formatAmount(p.montants.reduce<number>((s, m) => s + (m ?? 0), 0))} $`,
      '',
    ]),
    foot: [[
      { content: 'TOTAL GÉNÉRAL', colSpan: 3, styles: { halign: 'right' as const } },
      ...totauxReunions.map((t) => `${formatAmount(t)} $`),
      '',
      `${formatAmount(totalGeneral)} $`,
      '',
    ]],
    styles: { font: 'times', fontSize: 9, cellPadding: 1.5, lineColor: FILET, lineWidth: 0.1, textColor: 20, valign: 'middle', minCellHeight: 7 },
    headStyles: { fillColor: ACCENT, textColor: 255, fontStyle: 'bold', halign: 'center' },
    footStyles: { fillColor: ACCENT_CLAIR, textColor: 20, fontStyle: 'bold', halign: 'right' },
    columnStyles: {
      0: { cellWidth: 9, halign: 'center', textColor: 90 },
      1: { cellWidth: 52 },
      2: { cellWidth: 36 },
      ...Object.fromEntries(reunions.map((_, i) => [3 + i, { halign: 'right' as const }])),
      [3 + reunions.length]: { cellWidth: 16, halign: 'center' },
      [4 + reunions.length]: { cellWidth: 24, halign: 'right', fontStyle: 'bold' },
      [5 + reunions.length]: { cellWidth: 30 },
    },
    didParseCell: (data) => {
      if (data.section !== 'body') return
      const col = data.column.index
      if (col >= 3 && col < 3 + reunions.length && data.cell.raw === '—') {
        data.cell.styles.halign = 'center'
        data.cell.styles.textColor = 150
      }
    },
    margin: { left: margin, right: margin, bottom: 14 },
  })

  let y = (doc as any).lastAutoTable.finalY + 6
  if (y > pageHeight - 30) {
    doc.addPage()
    y = 20
  }
  doc.setFont('times', 'italic')
  doc.setFontSize(8.5)
  doc.setTextColor(90)
  doc.text(
    '« — » : absent à la réunion, non remboursé. Les montants proviennent des états de frais de chaque réunion, qui restent les pièces sources.',
    margin,
    y,
  )
  y += 6
  doc.setFont('times', 'normal')
  doc.setFontSize(10)
  doc.setTextColor(0)
  const lettres = doc.splitTextToSize(
    `Arrêté le présent état récapitulatif à la somme de ${numberToWords(totalGeneral)} (${formatAmount(totalGeneral)} $).`,
    pageWidth - 2 * margin,
  )
  doc.text(lettres, margin, y)

  const pageCount = doc.getNumberOfPages()
  for (let i = 1; i <= pageCount; i += 1) {
    doc.setPage(i)
    doc.setFont('times', 'normal')
    doc.setFontSize(8)
    doc.setTextColor(100)
    doc.text(format(new Date(), 'dd/MM/yyyy HH:mm'), margin, pageHeight - 6)
    doc.text(`État récapitulatif des frais de déplacement - ${organizationName}`, pageWidth / 2, pageHeight - 6, { align: 'center' })
    doc.text(`Page ${i}/${pageCount}`, pageWidth - margin, pageHeight - 6, { align: 'right' })
  }

  if (action === 'print') {
    openPdfInNewTab(doc)
  } else {
    const ref = String(dossier?.reference || 'dossier').replace(/[^A-Za-z0-9_-]+/g, '_')
    doc.save(`Etat_recapitulatif_transport_${ref}.pdf`)
  }
}
