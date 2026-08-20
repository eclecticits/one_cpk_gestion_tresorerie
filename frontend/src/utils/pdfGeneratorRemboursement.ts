import jsPDF from 'jspdf'
import autoTable from 'jspdf-autotable'
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

const addLogo = (doc: jsPDF, x: number, y: number, size: number, dataUrl?: string | null) => {
  if (!dataUrl) return
  doc.addImage(dataUrl, 'PNG', x, y, size, size)
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
  doc.text(tenantLabel ? `Remboursement frais de transport - ${tenantLabel}` : 'Remboursement frais de transport', pageWidth / 2, pageHeight - 6, { align: 'center' })
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
  const logoDataUrl = await getLogoDataUrl()
  const stampDataUrl = await getStampDataUrl()
  const isA5 = paperFormat === 'a5'
  const doc = new jsPDF({ orientation: 'p', unit: 'mm', format: paperFormat })
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  const margin = isA5 ? 10 : 15

  const beneficiaire = formatCommissionBeneficiaire(remboursement)

  const montantTotal = toNumber(remboursement.montant_total)
  const montantEnLettres = numberToWords(montantTotal)
  const itineraire = remboursement.lieu || 'N/A'
  const motif =
    remboursement.nature_reunion ||
    (Array.isArray(remboursement.nature_travail) ? remboursement.nature_travail.join(' / ') : '') ||
    'N/A'

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
  const tailleLogo = isA5 ? 16 : 20
  if (logoDataUrl) {
    addLogo(doc, margin, hautBandeau, tailleLogo, logoDataUrl)
  }
  // Sans logo (paramétrage incomplet ou image indisponible), le texte reprend la
  // marge : décalé de la largeur d'un logo absent, il ouvrait à gauche une
  // encoche vide que rien ne justifiait.
  const headerX = logoDataUrl ? margin + tailleLogo + 4 : margin

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
  const hauteurBandeau = logoDataUrl ? Math.max(tailleLogo, hauteurTexteEntete) : hauteurTexteEntete
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
  doc.text(String(transTitre).toUpperCase(), pageWidth / 2, yTitre, { align: 'center' })
  doc.setCharSpace(0)

  let yApresTitre = yTitre
  if (remboursement.reference_numero) {
    // Le numéro est une référence de classement, pas un second titre : maigre et
    // gris, il se lit sans disputer la vedette à l'intitulé.
    doc.setFont('times', 'normal')
    doc.setFontSize(echelle.numero)
    doc.setTextColor(85)
    doc.text(`N° ${remboursement.reference_numero}`, pageWidth / 2, yTitre + (isA5 ? 4.5 : 5.5), { align: 'center' })
    yApresTitre = yTitre + (isA5 ? 4.5 : 5.5)
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
      ['Motif / Mission', motif, 'Itinéraire', itineraire],
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

  let yPos = (doc as any).lastAutoTable.finalY + (isA5 ? 4 : 5)

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
      String(p.titre_fonction || '—'),
      `${formatAmount(p.montant)} $`,
      // Cellule laissée nue : la bordure de la grille fait déjà l'espace de
      // signature, la ligne de pointillés le mangeait.
      '',
    ])
    autoTable(doc, {
      startY: yPos,
      theme: 'grid',
      head: [['N°', 'Nom & Postnom', 'Fonction', 'Montant', 'Émargement']],
      body: participantsData,
      // Le total en pied donne au signataire de quoi recouper la somme
      // déclarée sans additionner à la main. Il est fusionné sur les trois
      // premières colonnes et calé à droite pour venir toucher le montant :
      // isolé dans la colonne des noms, il s'en trouvait à deux colonnes.
      foot: [[
        { content: 'TOTAL GÉNÉRAL', colSpan: 3, styles: { halign: 'right' as const } },
        `${formatAmount(totalParticipants)} $`,
        '',
      ]],
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
      margin: { left: margin, right: margin, bottom: hauteurQueue + hauteurPied },
      // En-tête répété : sur une liste qui déborde, la page suivante n'affichait
      // que des colonnes de chiffres sans intitulé.
      showHead: 'everyPage',
      showFoot: 'lastPage',
      columnStyles: {
        0: { cellWidth: isA5 ? 8 : 10, halign: 'center', textColor: 110 },
        1: { cellWidth: isA5 ? 42 : 52 },
        2: { cellWidth: isA5 ? 34 : 46 },
        3: { cellWidth: isA5 ? 20 : 24, halign: 'right' },
        4: { cellWidth: 'auto', halign: 'center' },
      },
    })
    yPos = (doc as any).lastAutoTable.finalY + (isA5 ? 7 : 9)
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
  const requisitionLiee = remboursement.requisition || {}
  const nomComplet = (personne: any) =>
    personne ? `${personne.prenom || ''} ${personne.nom || ''}`.trim() : ''
  const labelSecretaire = settings?.secretaire_executif_label || 'Le Secrétaire exécutif'
  const nomDemandeur = nomComplet(requisitionLiee.demandeur || remboursement.demandeur)
  const nomSecretaire = settings?.secretaire_executif_nom || nomComplet(requisitionLiee.examinateur)

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
  dessinerSignature(margin, yPos, 'Le demandeur', nomDemandeur)
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
