/**
 * Les signaux sonores de l'application, et leur interrupteur.
 *
 * Trois contraintes gouvernent ce module.
 *
 * **Le navigateur refuse le son tant que personne n'a cliqué.** C'est une règle
 * d'autoplay, pas un réglage : un son déclenché au chargement d'une page
 * rouverte avec une session valide est bloqué en silence. On ne peut donc pas
 * « saluer à l'ouverture » de façon fiable ; on salue après la connexion, où le
 * clic sur « Se connecter » vaut geste. `jouer` avale ce refus sans bruit —
 * échouer à faire un bruit n'est pas une erreur digne d'une trace rouge.
 *
 * **Un son sans interrupteur est un défaut.** Le réglage vit dans le
 * navigateur de chacun : il n'a pas à être partagé entre collègues qui
 * n'occupent pas le même bureau.
 *
 * **Un son répété est pire que pas de son.** L'appelant est responsable de ne
 * demander qu'aux vraies nouveautés ; ce module ne fait que jouer.
 */

export type Signal = 'ouverture' | 'aValider'

const FICHIERS: Record<Signal, string> = {
  ouverture: '/sons/ouverture.wav',
  aValider: '/sons/a-valider.wav',
}

const CLE_PREFERENCE = 'onec_sons_actifs'

export function sonsActifs(): boolean {
  try {
    // Absent = actif : la fonctionnalité s'installe allumée, et se coupe d'un clic.
    return localStorage.getItem(CLE_PREFERENCE) !== 'false'
  } catch {
    // Navigation privée, stockage bloqué : on ne prive personne du signal pour
    // un réglage illisible.
    return true
  }
}

export function reglerSons(actifs: boolean): void {
  try {
    localStorage.setItem(CLE_PREFERENCE, actifs ? 'true' : 'false')
  } catch {
    /* Le réglage ne survivra pas à la session : ce n'est pas une raison d'échouer. */
  }
}

/** Joue un signal, ou ne fait rien. Ne lève jamais. */
export function jouer(signal: Signal): void {
  if (!sonsActifs()) return
  try {
    const audio = new Audio(FICHIERS[signal])
    audio.volume = 0.5
    // `play()` rend une promesse rejetée quand l'autoplay est refusé : sans ce
    // `catch`, elle remonterait en « unhandled rejection » dans la console.
    void audio.play().catch(() => {})
  } catch {
    /* Format non supporté, fichier absent : le silence est acceptable. */
  }
}
