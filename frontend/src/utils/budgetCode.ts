/** Normalisation d'un code de poste budgétaire.
 *
 *  Partagée entre l'écran Budget et les générateurs de documents : c'est cette
 *  clé qui relie un commentaire à sa ligne. Deux normalisations légèrement
 *  différentes de part et d'autre (une casse, un point de trop) ne provoquent
 *  aucune erreur — elles font simplement disparaître tous les commentaires du
 *  document exporté, en silence. D'où l'unique implémentation.
 *
 *  Mêmes règles que `_normalize_budget_code` côté API, plus la casse repliée :
 *  « I.7.1 » et « i.7.1 » désignent le même poste.
 */
export const normalizeBudgetCode = (value?: string | null): string => {
  if (!value) return ''
  return value
    .trim()
    .replace(/\s+/g, '')
    .replace(/\.+/g, '.')
    .replace(/^\.+|\.+$/g, '')
    .toLowerCase()
}
