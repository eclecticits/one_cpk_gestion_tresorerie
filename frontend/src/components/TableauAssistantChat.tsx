import { tableauAssistantChat } from '../api/tableau'
import AgentChatWidget, { type AgentChatConfig } from './AgentChatWidget'

// L'assistant du module ne modifie rien : il lit la base, les anomalies et les
// règles. Corriger, décider ou générer un document reste un acte humain, gardé
// par son propre droit.
const CONFIG: AgentChatConfig = {
  titre: 'Assistant Tableau',
  sousTitre: 'Tableau de l\'Ordre · IA',
  accroche:
    'Je réponds sur la base consolidée, les anomalies et les règles de délibération. '
    + 'Je ne modifie rien : posez-moi une question ou choisissez une suggestion :',
  questionsSuggerees: [
    'Où en est le Tableau de cet exercice ?',
    'Quelles sont les anomalies critiques ?',
    'Combien de membres sont à délibérer ?',
    'Quelles règles de délibération s\'appliquent ?',
    'Quelle est la situation de EC/18.00062 ?',
  ],
  libellesOutils: {
    etat_du_tableau: 'État du Tableau',
    consulter_base: 'Base consolidée',
    situation_membre: 'Situation d\'un membre',
    lister_anomalies: 'Anomalies',
    regles_de_deliberation: 'Règles de délibération',
  },
  envoyer: tableauAssistantChat,
}

export default function TableauAssistantChat() {
  return <AgentChatWidget config={CONFIG} />
}
