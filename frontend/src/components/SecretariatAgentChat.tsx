import { managerAgentChat } from '../api/secretariat'
import AgentChatWidget, { type AgentChatConfig } from './AgentChatWidget'

const CONFIG: AgentChatConfig = {
  titre: 'Agent Manager',
  sousTitre: 'Secrétariat · IA',
  accroche:
    'Je coordonne les agents Agenda, Réunions, Documents et Approbations. '
    + 'Posez-moi une question ou choisissez une suggestion :',
  questionsSuggerees: [
    'Montre-moi le tableau de bord du secrétariat',
    'Quelles sont les actions prioritaires ?',
    'Liste les réunions prévues',
    'Quelles approbations sont en attente ?',
    'Liste les échéances urgentes',
  ],
  libellesOutils: {
    get_tableau_de_bord: 'Vue d\'ensemble',
    get_actions_recommandees: 'Actions recommandées',
    lister_echeances_agenda: 'Agenda — liste',
    creer_echeance_agenda: 'Agenda — création',
    lister_reunions: 'Réunions — liste',
    creer_reunion: 'Réunion — création',
    generer_ordre_du_jour: 'Ordre du jour',
    generer_pv_reunion: 'Procès-verbal',
    lister_documents: 'Documents — liste',
    generer_synthese_document: 'Synthèse document',
    lister_approbations_en_attente: 'Approbations en attente',
  },
  envoyer: managerAgentChat,
}

export default function SecretariatAgentChat() {
  return <AgentChatWidget config={CONFIG} />
}
