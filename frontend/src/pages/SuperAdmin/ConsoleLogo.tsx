/**
 * Logo de l'éditeur dans l'en-tête de la console.
 *
 * Rien ne s'affiche tant qu'aucun logo n'est enregistré : l'en-tête garde
 * alors son icône d'origine. `version` est incrémenté par l'écran de réglages
 * après un dépôt ou un retrait, pour relire sans recharger la page.
 */

import { useEffect, useState } from 'react'
import { getEditorLogo } from '../../api/superAdmin'
import { fetchAuthenticatedObjectUrl } from '../../utils/download'

export default function ConsoleLogo({ version = 0 }: { version?: number }) {
  const [url, setUrl] = useState('')

  useEffect(() => {
    let actif = true
    let cree = ''
    const charger = async () => {
      try {
        const descripteur = await getEditorLogo()
        if (!actif) return
        if (!descripteur.present) {
          setUrl('')
          return
        }
        // Une <img> ne porte pas d'en-tête Authorization : passage par un blob.
        cree = await fetchAuthenticatedObjectUrl('/super-admin/branding/logo/file')
        if (actif) setUrl(cree)
        else URL.revokeObjectURL(cree)
      } catch {
        // Un logo illisible ne doit pas empêcher la console de s'afficher.
        if (actif) setUrl('')
      }
    }
    charger()
    return () => {
      actif = false
      if (cree) URL.revokeObjectURL(cree)
    }
  }, [version])

  if (!url) return null

  return (
    <img
      src={url}
      alt="Logo de l’éditeur"
      style={{ height: 30, maxWidth: 132, objectFit: 'contain' }}
    />
  )
}
