/**
 * Identité du tenant pour les documents PDF.
 *
 * Règle : aucun document ne doit sortir de l'application sans identifier
 * l'organisation qui l'émet. Ce module centralise la récupération des
 * paramètres d'impression et du logo, ainsi que le tracé de l'en-tête et du
 * pied de page, pour que cette règle soit tenue à un seul endroit.
 *
 * Le cache est SCOPÉ AU TENANT : après un changement d'organisation dans le
 * même onglet, il est purgé. Sans cela un document pourrait porter le nom et
 * le logo du tenant précédent — pire qu'un document non identifié.
 */

import type jsPDF from 'jspdf'
import { format } from 'date-fns'

import { API_BASE_URL, getAuthHeaders } from '../lib/apiClient'
import { getTenantRequestHint } from './tenant'
import { buildUploadUrl } from './uploads'

export const ONEC_GREEN = '#065f46'
export const ONEC_LIGHT_BG = '#f0fdf4'
const DEFAULT_ORG_NAME = 'ONEC-RDC'
const ONEC_TITLE = 'ORDRE NATIONAL DES EXPERTS-COMPTABLES'

let cachedSettings: any | null = null
let cachedLogoDataUrl: string | null = null
let cachedTenantHint: string | null = null

const ensureTenantScopedCache = () => {
  const hint = getTenantRequestHint()
  if (hint !== cachedTenantHint) {
    cachedTenantHint = hint
    cachedSettings = null
    cachedLogoDataUrl = null
  }
}

/**
 * Fabrique une garde de cache scopée au tenant.
 *
 * Les générateurs PDF mettent en cache les paramètres d'impression et le logo
 * pour éviter de les recharger à chaque document. Ce cache DOIT être purgé
 * quand l'organisation courante change, sinon un document émis après une
 * bascule de tenant porterait le nom et le logo du tenant précédent.
 *
 * Chaque générateur garde ses propres variables de cache et fournit ici sa
 * fonction de purge ; seule la détection du changement est mutualisée.
 */
export const makeTenantScopedCacheGuard = (reset: () => void): (() => void) => {
  let knownHint: string | null | undefined
  let initialised = false
  return () => {
    const hint = getTenantRequestHint()
    if (!initialised || hint !== knownHint) {
      initialised = true
      knownHint = hint
      reset()
    }
  }
}

export const getTenantPrintSettings = async (): Promise<any | null> => {
  ensureTenantScopedCache()
  if (cachedSettings) return cachedSettings
  try {
    const res = await fetch(`${API_BASE_URL}/print-settings`, {
      headers: getAuthHeaders(),
      credentials: 'include',
    })
    if (!res.ok) return null
    cachedSettings = await res.json()
    return cachedSettings
  } catch {
    return null
  }
}

export const getTenantLogoDataUrl = async (): Promise<string | null> => {
  ensureTenantScopedCache()
  if (cachedLogoDataUrl) return cachedLogoDataUrl
  try {
    const settings = await getTenantPrintSettings()
    const logoPath = settings?.logo_url ? buildUploadUrl(settings.logo_url) : '/imge_onec.png'
    const res = await fetch(logoPath, { headers: getAuthHeaders(), credentials: 'include' })
    if (!res.ok) return null
    const blob = await res.blob()
    cachedLogoDataUrl = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onloadend = () => resolve(String(reader.result || ''))
      reader.onerror = reject
      reader.readAsDataURL(blob)
    })
    return cachedLogoDataUrl
  } catch {
    return null
  }
}

export type TenantIdentity = {
  settings: any | null
  logoDataUrl: string | null
  orgName: string
}

export const loadTenantIdentity = async (): Promise<TenantIdentity> => {
  const settings = await getTenantPrintSettings()
  const logoDataUrl =
    settings?.show_header_logo === false ? null : await getTenantLogoDataUrl()
  return {
    settings,
    logoDataUrl,
    orgName: settings?.organization_name || DEFAULT_ORG_NAME,
  }
}

/**
 * En-tête identifiant l'organisation émettrice. Retourne l'ordonnée à laquelle
 * le contenu du document peut commencer.
 */
export const drawTenantHeader = (
  doc: jsPDF,
  identity: TenantIdentity,
  options: { title: string; subtitle?: string | null },
): number => {
  const pageWidth = doc.internal.pageSize.getWidth()
  const margin = 12
  const bandHeight = 26

  doc.setFillColor(ONEC_LIGHT_BG)
  doc.roundedRect(margin, 8, pageWidth - margin * 2, bandHeight, 2.5, 2.5, 'F')

  if (identity.logoDataUrl) {
    try {
      doc.addImage(identity.logoDataUrl, 'PNG', margin + 3, 10.5, 21, 21)
    } catch {
      // Un logo illisible ne doit jamais empêcher l'émission du document.
    }
  }

  const textLeft = margin + (identity.logoDataUrl ? 28 : 5)

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(11)
  doc.setTextColor(6, 95, 70)
  doc.text(ONEC_TITLE, textLeft, 16)

  doc.setFont('times', 'bolditalic')
  doc.setFontSize(11)
  doc.setTextColor(15, 23, 42)
  doc.text(identity.orgName, textLeft, 22.5)

  const contact = [
    identity.settings?.address,
    identity.settings?.phone,
    identity.settings?.email,
  ]
    .filter(Boolean)
    .join('  •  ')
  if (contact) {
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(7.5)
    doc.setTextColor(90, 100, 115)
    doc.text(doc.splitTextToSize(contact, pageWidth - textLeft - margin - 4)[0], textLeft, 28)
  }

  doc.setDrawColor(6, 95, 70)
  doc.setLineWidth(1.2)
  doc.line(margin, 8 + bandHeight + 1.5, pageWidth - margin, 8 + bandHeight + 1.5)

  doc.setFont('helvetica', 'bold')
  doc.setFontSize(13)
  doc.setTextColor(15, 23, 42)
  doc.text(options.title.toUpperCase(), margin, 44)

  if (options.subtitle) {
    doc.setFont('helvetica', 'normal')
    doc.setFontSize(9)
    doc.setTextColor(90, 100, 115)
    doc.text(options.subtitle, margin, 50)
    return 56
  }
  return 50
}

/**
 * Pied de page : rappelle l'organisation sur CHAQUE page, de sorte qu'une page
 * isolée reste rattachable à son émetteur.
 */
export const drawTenantFooter = (
  doc: jsPDF,
  identity: TenantIdentity,
  options: { pageNumber: number; pageCount: number; generatedBy?: string | null },
): void => {
  const pageWidth = doc.internal.pageSize.getWidth()
  const pageHeight = doc.internal.pageSize.getHeight()
  const margin = 12

  doc.setDrawColor(226, 232, 240)
  doc.setLineWidth(0.3)
  doc.line(margin, pageHeight - 14, pageWidth - margin, pageHeight - 14)

  doc.setFont('helvetica', 'normal')
  doc.setFontSize(7.5)
  doc.setTextColor(110, 120, 135)
  doc.text(identity.orgName, margin, pageHeight - 9.5)

  const emitted = `Émis le ${format(new Date(), 'dd/MM/yyyy à HH:mm')}${
    options.generatedBy ? ` par ${options.generatedBy}` : ''
  }`
  doc.text(emitted, pageWidth / 2, pageHeight - 9.5, { align: 'center' })

  doc.text(
    `Page ${options.pageNumber} / ${options.pageCount}`,
    pageWidth - margin,
    pageHeight - 9.5,
    { align: 'right' },
  )
}
