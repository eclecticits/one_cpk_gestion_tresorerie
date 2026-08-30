import { useEffect, useRef, useState } from 'react'
import { apiRequest } from '../lib/apiClient'
import { jouer } from '../lib/sons'

export interface ResumeAValider {
  nb: number
  dont_transport: number
  dernier: string | null
  peut_valider: boolean
}

const INTERVALLE_MS = 60_000
const CLE_DERNIER_VU = 'onec_dernier_dossier_vu'

/**
 * Prévient un validateur quand un dossier arrive, où qu'il soit dans l'app.
 *
 * Le son ne se déclenche pas sur « il y a du travail » — sinon il sonnerait à
 * chaque tour d'horloge tant qu'une pile n'est pas vidée — mais sur « il vient
 * d'en arriver », c'est-à-dire quand l'horodatage du plus récent dépasse celui
 * retenu au dernier passage.
 *
 * Ce repère est conservé dans le navigateur : sans lui, un simple rechargement
 * de page rejouerait le signal pour des dossiers déjà vus, et l'alerte
 * deviendrait un bruit qu'on apprend à ignorer.
 *
 * Le tout premier passage ne sonne jamais : il ne fait qu'établir le repère.
 * Découvrir l'application au son de trois notes pour du travail vieux d'une
 * semaine n'apprendrait rien à personne.
 */
export function useAlerteAValider(actif: boolean): ResumeAValider | null {
  const [resume, setResume] = useState<ResumeAValider | null>(null)
  const repereEtabli = useRef(false)

  useEffect(() => {
    if (!actif) return
    let annule = false

    const verifier = async () => {
      try {
        const res = await apiRequest<ResumeAValider>('GET', '/alertes/a-valider')
        if (annule || !res?.peut_valider) return
        setResume(res)

        if (!res.dernier) return
        const dernierVu = (() => {
          try { return localStorage.getItem(CLE_DERNIER_VU) } catch { return null }
        })()

        // Premier passage : on note le repère sans sonner.
        if (!repereEtabli.current && !dernierVu) {
          repereEtabli.current = true
          try { localStorage.setItem(CLE_DERNIER_VU, res.dernier) } catch { /* stockage bloqué */ }
          return
        }
        repereEtabli.current = true

        if (!dernierVu || res.dernier > dernierVu) {
          try { localStorage.setItem(CLE_DERNIER_VU, res.dernier) } catch { /* stockage bloqué */ }
          if (dernierVu) jouer('aValider')
        }
      } catch {
        // Une alerte qui échoue reste silencieuse : elle n'a pas à interrompre
        // le travail en cours pour dire qu'elle n'a pas pu regarder.
      }
    }

    verifier()
    const minuteur = window.setInterval(verifier, INTERVALLE_MS)
    return () => { annule = true; window.clearInterval(minuteur) }
  }, [actif])

  return resume
}
