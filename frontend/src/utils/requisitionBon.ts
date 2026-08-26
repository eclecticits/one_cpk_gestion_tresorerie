import { apiRequest } from '../lib/apiClient'

// pdfGenerator importe jspdf (135 ko gz) et la police greatVibes (27 ko gz).
// Importe statiquement, ce module les tirait dans le chunk de toute page qui
// l'importe — DossiersExamen et ExamenDossier, qui n'en ont besoin qu'au
// moment de valider un examen. On charge donc a la demande, une seule fois.
type PdfGeneratorModule = typeof import('./pdfGenerator')
let _pdfGeneratorModulePromise: Promise<PdfGeneratorModule> | null = null
function loadPdfGeneratorModule(): Promise<PdfGeneratorModule> {
  if (!_pdfGeneratorModulePromise) _pdfGeneratorModulePromise = import('./pdfGenerator')
  return _pdfGeneratorModulePromise
}

/**
 * Le bon officiel est un PDF généré côté navigateur puis stocké sur la
 * réquisition (`pdf_path`). Il est produit une seule fois, à la création, donc
 * il fige l'état d'alors : au moment de l'examen il porte encore « Examinateur :
 * N/A ». Or c'est ce fichier-là que le backend joint au mail envoyé au Bureau
 * après la validation d'examen — le corps du mail annonçait un examinateur que
 * la pièce jointe ne montrait pas.
 *
 * On régénère donc le bon juste avant de valider l'examen, avec l'examinateur
 * renseigné, et on le réenregistre sans déclencher de notification : c'est la
 * validation qui suit qui enverra le mail, avec le bon à jour.
 *
 * Un échec ici ne doit jamais empêcher la validation : on renvoie `false` et
 * l'appelant poursuit avec l'ancien bon plutôt que de bloquer l'examen.
 */
export const refreshRequisitionBonBeforeExamen = async (
  requisition: any,
  examinateur: { prenom?: string | null; nom?: string | null } | null | undefined,
): Promise<boolean> => {
  try {
    if (!requisition?.id) return false

    const lignesRes: any = await apiRequest('GET', '/lignes-requisition', {
      params: { requisition_id: requisition.id },
    })
    const lignes = Array.isArray(lignesRes) ? lignesRes : (lignesRes?.items ?? lignesRes?.data ?? [])
    if (!lignes.length) return false

    // L'examinateur est l'utilisateur qui déclenche la validation : on l'injecte
    // dans la copie servant au rendu, la base ne le connaîtra qu'après l'appel
    // à validate-examen.
    const snapshot = {
      ...requisition,
      examinateur: examinateur || requisition.examinateur,
      examen_le: requisition.examen_le || new Date().toISOString(),
    }

    const { generateSingleRequisitionPDF } = await loadPdfGeneratorModule()
    const blob = await generateSingleRequisitionPDF(snapshot, lignes, 'blob', '')
    if (!blob) return false

    const form = new FormData()
    form.append('file', blob, `requisition_${requisition.numero_requisition || requisition.id}.pdf`)
    await apiRequest('POST', `/requisitions/${requisition.id}/pdf`, {
      params: { notify: false },
      body: form,
    })
    return true
  } catch (error) {
    console.error('Impossible de régénérer le bon avant validation d’examen:', error)
    return false
  }
}
