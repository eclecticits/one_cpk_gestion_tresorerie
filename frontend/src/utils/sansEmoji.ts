// Mêmes plages que `strip_emoji` côté serveur : pour le texte qui ne passe pas
// par un gabarit (saisie avant envoi, réponses de l'assistant, données anciennes).
const EMOJI = /[\p{Extended_Pictographic}\u{1F1E6}-\u{1F1FF}\u{FE0F}\u{200D}\u{20E3}]/gu

export const sansEmoji = (texte: string) => texte.replace(EMOJI, '')
