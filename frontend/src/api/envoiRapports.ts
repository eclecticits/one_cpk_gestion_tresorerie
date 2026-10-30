import { apiRequest } from '../lib/apiClient'

export type CanalEnvoi = 'email' | 'whatsapp'

/** Une personne, toutes ses fiches de service réunies. */
export interface DestinataireRapport {
  id: number
  member_ids: number[]
  nom: string
  fonction: string
  services: string[]
  email: string | null
  /** Numéro exploitable et notifications WhatsApp acceptées. */
  whatsapp: boolean
  /** Siège dans un service intitulé « Bureau ». */
  bureau: boolean
}

/** E-mail : les adresses fixes du Bureau, comme pour les réquisitions. WhatsApp : les membres à choisir. */
export interface DestinatairesRapport {
  /** Le Président (Paramètres › Notifications). */
  email_to: string[]
  /** Les adresses du Bureau en copie. */
  email_cc: string[]
  membres: DestinataireRapport[]
}

export interface ResultatEnvoiRapport {
  emails_envoyes: number
  whatsapp_envoyes: number
  echecs: { nom: string; canal: CanalEnvoi; raison: string }[]
}

export interface EnvoiRapport {
  titre: string
  periode: string
  /** Chiffres clés, une ligne chacun : « Entrées : 1 200,00 USD ». */
  resume: string[]
  message: string
  /** Membres choisis pour WhatsApp. */
  memberIds: number[]
  canaux: CanalEnvoi[]
  pdf?: { blob: Blob; nom: string }
}

export function listDestinatairesRapport(): Promise<DestinatairesRapport> {
  return apiRequest<DestinatairesRapport>('GET', '/rapports-envoi/destinataires')
}

export function envoyerRapport(envoi: EnvoiRapport): Promise<ResultatEnvoiRapport> {
  const form = new FormData()
  form.append('titre', envoi.titre)
  form.append('periode', envoi.periode)
  form.append('resume', JSON.stringify(envoi.resume))
  form.append('message', envoi.message)
  form.append('member_ids', JSON.stringify(envoi.memberIds))
  form.append('canaux', JSON.stringify(envoi.canaux))
  if (envoi.pdf) form.append('fichier', envoi.pdf.blob, envoi.pdf.nom)
  return apiRequest<ResultatEnvoiRapport>('POST', '/rapports-envoi', form)
}
