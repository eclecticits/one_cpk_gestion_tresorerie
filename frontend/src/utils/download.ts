import { API_BASE_URL, apiRequest, getAuthHeaders } from '../lib/apiClient'

type Params = Record<string, string | number | boolean | undefined | null>

const MIME_XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

// Etat d'un export genere en tache de fond, tel que le rend
// GET /exports/jobs/{id} (backend/app/services/export_jobs.py:serialiser_job).
export type ExportJob = {
  id: string
  type: string
  status: 'QUEUED' | 'RUNNING' | 'DONE' | 'FAILED' | 'EXPIRED' | 'CANCELLED'
  progress: number | null
  row_count: number | null
  file_name: string | null
  file_size: number | null
  error_code: string | null
  error_message: string | null
  status_path: string
  // Absent tant que le job n'est pas DONE : le serveur ne publie le lien que
  // quand il y a quelque chose a telecharger.
  download_path?: string
}

export type OptionsExport = {
  // Appele UNE fois, au moment ou le serveur repond 202 au lieu du fichier.
  // C'est le seul instant ou la page peut savoir que l'attente ne sera pas
  // instantanee. Sans ce signal, un bouton reste muet pendant deux minutes et
  // l'utilisateur reclique — motif observe tel quel dans les tirs de charge du
  // 28/08, et qui coute cinq fois le prix (d'ou la deduplication cote serveur).
  onMiseEnFile?: (job: ExportJob) => void
}

// Interrogation : on commence court pour que les petits exports paraissent
// immediats, et on s'espace pour ne pas marteler le serveur pendant qu'un gros
// classeur se construit. Le plafond de 10 minutes est superieur au plus long
// export mesure (112 s pour un exercice complet) avec une marge large : au-dela,
// mieux vaut rendre la main a l'utilisateur que de le laisser devant une page
// qui tourne indefiniment. Le job, lui, continue cote serveur.
const ATTENTE_INITIALE_MS = 800
const ATTENTE_MAX_MS = 5000
const DELAI_TOTAL_MS = 10 * 60 * 1000

// Le serveur ne remplit `error_message` que sur les echecs qu'il sait
// expliquer. Pour les autres etats terminaux, un repli FRANCAIS est
// indispensable : `Export ${status.toLowerCase()}` rendait « Export failed. » a
// l'utilisateur — le nom d'une constante d'enum SQL, dans une autre langue que
// celle de l'application.
const MESSAGE_PAR_STATUT: Record<string, string> = {
  FAILED: "La génération de l'export a échoué. Réessayez ; si le problème persiste, prévenez l'administrateur.",
  EXPIRED: "Cet export a expiré avant d'avoir pu être récupéré. Relancez-le.",
  CANCELLED: "Cet export a été annulé.",
  // DONE sans lien de telechargement : le job a abouti mais son fichier a ete
  // purge (retention) ou perdu. Le cas existe, il merite mieux que « Export done. ».
  DONE: "Le fichier de cet export n'est plus disponible. Relancez-le.",
}

const pause = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

function declencherTelechargement(blob: Blob, filename: string): void {
  const downloadUrl = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = downloadUrl
  link.setAttribute('download', filename)
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(downloadUrl)
}

async function messageErreur(resp: Response, defaut: string): Promise<string> {
  try {
    const data = await resp.json()
    if (typeof data?.detail === 'string') return data.detail
  } catch {
    // Corps non JSON : 504 de nginx, page d'erreur HTML, reponse vide.
  }
  return defaut
}

// Attend qu'un export asynchrone soit pret, puis le telecharge.
//
// Le serveur decide du regime (200 avec le fichier, ou 202 avec un job) et le
// client s'adapte : c'est ce qui rend la bascule reversible type par type sans
// redeployer le frontend. Aucune page appelante ne change.
async function suivreEtTelecharger(
  job: ExportJob,
  baseUrl: string,
  filenameParDefaut: string,
): Promise<void> {
  const echeance = Date.now() + DELAI_TOTAL_MS
  let attente = ATTENTE_INITIALE_MS
  let courant = job

  while (courant.status === 'QUEUED' || courant.status === 'RUNNING') {
    if (Date.now() >= echeance) {
      // Le job continue cote serveur : le plafond ne l'annule pas, il rend la
      // main. Relancer le meme export pendant la fenetre de deduplication
      // (EXPORT_DEDUP_WINDOW_MINUTES) rend l'artefact deja produit sans le
      // regenerer — c'est pour cela que le message invite a relancer plutot
      // qu'a renvoyer vers un ecran « Mes exports » qui n'existe pas encore.
      throw new Error(
        "L'export est toujours en cours de génération côté serveur. Relancez-le dans quelques minutes : s'il est terminé, le fichier déjà produit sera rendu immédiatement.",
      )
    }
    await pause(attente)
    attente = Math.min(attente * 2, ATTENTE_MAX_MS)

    // apiRequest et NON un fetch brut. Le jeton d'acces vit en RAM et il est
    // court (apiClient.ts) ; une attente de plusieurs minutes le voit expirer.
    // Un fetch brut rendrait alors « HTTP 401 » sur un export qui, lui, s'est
    // parfaitement termine. apiRequest rejoue la requete apres refresh
    // silencieux, reessaie les 502/503/504 d'un backend qui redemarre, et
    // envoie `Accept: application/json` — ce que cette route attend, la
    // negociation xlsx n'ayant aucun sens sur un etat de job.
    courant = await apiRequest<ExportJob>('GET', courant.status_path)
  }

  if (courant.status !== 'DONE' || !courant.download_path) {
    // `error_message` est ecrit par le worker pour etre lu par un humain : il
    // ne porte aucune trace technique. A defaut, un message francais par etat.
    throw new Error(
      courant.error_message ||
        MESSAGE_PAR_STATUT[courant.status] ||
        "L'export ne peut pas être téléchargé.",
    )
  }

  const fichier = await fetch(`${baseUrl}${courant.download_path}`, {
    // En-tetes relus MAINTENANT et non au premier appel : entre les deux,
    // l'attente a pu durer dix minutes et le suivi ci-dessus a pu renouveler
    // le jeton. Reutiliser les en-tetes capturees a la soumission ferait
    // echouer le telechargement en 401 juste apres une attente reussie.
    headers: { ...getAuthHeaders(), Accept: MIME_XLSX },
    credentials: 'include',
    mode: 'cors',
    cache: 'no-store',
  })
  if (!fichier.ok) {
    // 409 : le job n'est plus DONE (purge concurrente). 410 : l'artefact a
    // disparu. Les deux portent un `detail` explicite cote serveur.
    throw new Error(await messageErreur(fichier, `Téléchargement impossible (HTTP ${fichier.status})`))
  }

  const contenu = await fichier.blob()
  if (contenu.size === 0) {
    // Corps VIDE : le backend confie le fichier a nginx par X-Accel-Redirect et
    // ne renvoie aucun octet lui-meme (export_jobs.py). Si la reponse n'a pas
    // traverse le reverse-proxy — appel direct au port 8000, ou `location
    // internal /_protected_uploads/` absente de la configuration deployee —
    // l'en-tete est ignoree et le navigateur enregistre zero octet sous un nom
    // en .xlsx. Une erreur lisible vaut mieux qu'un classeur vide que
    // l'utilisateur imputera a Excel.
    throw new Error(
      "Le fichier de l'export est arrivé vide : la livraison des fichiers protégés n'est pas configurée sur ce serveur. Prévenez l'administrateur.",
    )
  }
  declencherTelechargement(contenu, courant.file_name || filenameParDefaut)
}

export async function downloadExcel(
  path: string,
  params: Params,
  filename: string,
  options: OptionsExport = {},
): Promise<void> {
  const origin = typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8000'
  let baseUrl = API_BASE_URL.replace(/\/+$/, '')
  if (baseUrl.startsWith('/')) {
    baseUrl = `${origin}${baseUrl}`
  } else if (!/^https?:\/\//i.test(baseUrl)) {
    baseUrl = `${origin}/${baseUrl.replace(/^\/+/, '')}`
  }
  const url = new URL(`${baseUrl}${path.startsWith('/') ? path : `/${path}`}`)
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    url.searchParams.set(key, String(value))
  })

  const headers = {
    ...getAuthHeaders(),
    Accept: MIME_XLSX,
  }

  const resp = await fetch(url.toString(), {
    headers,
    credentials: 'include',
    mode: 'cors',
    cache: 'no-store',
  })
  if (!resp.ok) {
    // Le backend refuse explicitement un export trop volumineux (413) avec un
    // message qui dit quoi faire : restreindre la période ou les filtres. Sans
    // cette lecture du corps, l'utilisateur ne lisait que « Export failed (HTTP
    // 413) » — un code, aucune action possible, et le réflexe naturel est de
    // recliquer à l'identique. Le corps est du JSON FastAPI ({ detail }).
    throw new Error(await messageErreur(resp, `Export failed (HTTP ${resp.status})`))
  }

  // 202 : l'export est trop lourd pour le chemin direct, le serveur l'a mis en
  // file. ATTENTION, 202 est un statut « ok » : sans cette branche, le JSON du
  // job serait telecharge tel quel sous un nom en .xlsx, et l'utilisateur
  // ouvrirait un fichier illisible en croyant a un bug d'Excel.
  if (resp.status === 202) {
    const job = (await resp.json()) as ExportJob
    // Prevenir la page AVANT la premiere attente : c'est le seul moment ou elle
    // peut afficher « preparation en cours » plutot que de laisser un bouton
    // muet. Une exception levee par la page ne doit pas faire echouer l'export.
    try {
      options.onMiseEnFile?.(job)
    } catch {
      /* l'affichage n'est pas une raison d'abandonner le telechargement */
    }
    return await suivreEtTelecharger(job, baseUrl, filename)
  }

  declencherTelechargement(await resp.blob(), filename)
}

/** Résout un chemin d'API en URL absolue, quelle que soit la forme de
 *  API_BASE_URL (absolue, racine, ou relative). */
function resolveApiUrl(path: string): string {
  const origin = typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8000'
  let baseUrl = API_BASE_URL.replace(/\/+$/, '')
  if (baseUrl.startsWith('/')) {
    baseUrl = `${origin}${baseUrl}`
  } else if (!/^https?:\/\//i.test(baseUrl)) {
    baseUrl = `${origin}/${baseUrl.replace(/^\/+/, '')}`
  }
  return `${baseUrl}${path.startsWith('/') ? path : `/${path}`}`
}

/** Récupère un fichier protégé en object URL, utilisable dans un <img>.
 *
 *  Une balise <img> ne peut pas porter d'en-tête Authorization : afficher une
 *  image servie derrière un jeton passe forcément par un fetch puis un blob.
 *  L'appelant doit révoquer l'URL rendue quand il ne s'en sert plus.
 */
export async function fetchAuthenticatedObjectUrl(path: string): Promise<string> {
  const response = await fetch(resolveApiUrl(path), {
    method: 'GET',
    headers: getAuthHeaders(),
    credentials: 'include',
    mode: 'cors',
    cache: 'no-store',
  })
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }
  return URL.createObjectURL(await response.blob())
}

export async function openAuthenticatedFile(path: string): Promise<void> {
  const origin = typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8000'
  let baseUrl = API_BASE_URL.replace(/\/+$/, '')
  if (baseUrl.startsWith('/')) {
    baseUrl = `${origin}${baseUrl}`
  } else if (!/^https?:\/\//i.test(baseUrl)) {
    baseUrl = `${origin}/${baseUrl.replace(/^\/+/, '')}`
  }

  const url = `${baseUrl}${path.startsWith('/') ? path : `/${path}`}`
  const response = await fetch(url, {
    method: 'GET',
    headers: getAuthHeaders(),
    credentials: 'include',
    mode: 'cors',
    cache: 'no-store',
  })

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }

  const blob = await response.blob()
  const objectUrl = URL.createObjectURL(blob)
  window.open(objectUrl, '_blank', 'noopener,noreferrer')
  setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000)
}

export async function downloadAuthenticatedFile(path: string, filename: string): Promise<void> {
  const origin = typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8000'
  let baseUrl = API_BASE_URL.replace(/\/+$/, '')
  if (baseUrl.startsWith('/')) {
    baseUrl = `${origin}${baseUrl}`
  } else if (!/^https?:\/\//i.test(baseUrl)) {
    baseUrl = `${origin}/${baseUrl.replace(/^\/+/, '')}`
  }

  const url = `${baseUrl}${path.startsWith('/') ? path : `/${path}`}`
  const response = await fetch(url, {
    method: 'GET',
    headers: getAuthHeaders(),
    credentials: 'include',
    mode: 'cors',
    cache: 'no-store',
  })

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }

  const blob = await response.blob()
  const objectUrl = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = objectUrl
  link.setAttribute('download', filename)
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(objectUrl)
}
