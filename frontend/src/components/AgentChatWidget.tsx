import { FormEvent, useEffect, useRef, useState } from 'react'
import { Bot, ChevronDown, Loader2, RotateCw, Send, Wrench, X } from 'lucide-react'
import AiContentBanner from './AiContentBanner'
import { ApiError } from '../lib/apiClient'
import styles from './AgentChatWidget.module.css'

// Widget de conversation partagé : chaque module y branche son propre assistant,
// sans dépendre de celui d'un autre.

export interface AgentChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface AgentChatResponse {
  response: string
  actions_taken: string[]
  tool_results: Array<Record<string, unknown>>
}

export interface AgentChatConfig {
  /** Nom affiché dans l'en-tête et l'écran d'accueil. */
  titre: string
  /** Ligne secondaire de l'en-tête, ex. « Secrétariat · IA ». */
  sousTitre: string
  /** Phrase d'accueil, qui dit ce que l'assistant sait faire. */
  accroche: string
  questionsSuggerees: string[]
  /** Libellés lisibles des outils, pour les étiquettes sous les réponses. */
  libellesOutils: Record<string, string>
  envoyer: (input: { message: string; conversation_history?: AgentChatMessage[] }) => Promise<AgentChatResponse>
}

// ── Types internes ────────────────────────────────────────────────────────────

interface ChatEntry {
  id: string
  role: 'user' | 'assistant'
  content: string
  actions?: string[]
  error?: boolean
  loading?: boolean
}

function uid() {
  return Math.random().toString(36).slice(2)
}

// ── Composant principal ───────────────────────────────────────────────────────

export default function AgentChatWidget({ config }: { config: AgentChatConfig }) {
  const [open, setOpen] = useState(false)
  const [input, setInput] = useState('')
  const [entries, setEntries] = useState<ChatEntry[]>([])
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // Historique pour le contexte multi-tour
  const historyRef = useRef<AgentChatMessage[]>([])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [entries])

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 150)
    }
  }, [open])

  const send = async (text?: string) => {
    const message = (text ?? input).trim()
    if (!message || loading) return

    setInput('')
    const userEntry: ChatEntry = { id: uid(), role: 'user', content: message }
    const placeholderId = uid()
    const placeholderEntry: ChatEntry = { id: placeholderId, role: 'assistant', content: '', loading: true }

    setEntries((prev) => [...prev, userEntry, placeholderEntry])
    setLoading(true)

    // Construire l'historique pour le backend (sans les placeholders)
    const history: AgentChatMessage[] = historyRef.current.slice(-10)

    try {
      const result: AgentChatResponse = await config.envoyer({
        message,
        conversation_history: history,
      })

      // Ajouter user + assistant à l'historique
      historyRef.current = [
        ...historyRef.current,
        { role: 'user' as const, content: message },
        { role: 'assistant' as const, content: result.response },
      ].slice(-20)

      setEntries((prev) =>
        prev.map((e) =>
          e.id === placeholderId
            ? {
                id: placeholderId,
                role: 'assistant',
                content: result.response,
                actions: result.actions_taken,
              }
            : e,
        ),
      )
    } catch (err: any) {
      // Message métier plutôt que le détail brut du serveur : err.message peut
      // contenir une erreur de validation FastAPI en anglais, affichée jusqu'ici
      // dans une bulle qui a l'apparence d'une réponse de l'assistant.
      const statut = err instanceof ApiError ? err.status : 0
      const msg =
        statut === 401
          ? 'Votre session a expiré. Reconnectez-vous pour continuer.'
          : statut >= 500
            ? 'Le service est temporairement indisponible. Réessayez dans un instant.'
            : "Impossible de contacter l'assistant pour le moment."
      setEntries((prev) =>
        prev.map((e) =>
          e.id === placeholderId
            ? { id: placeholderId, role: 'assistant', content: msg, error: true }
            : e,
        ),
      )
    } finally {
      setLoading(false)
    }
  }

  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    void send()
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void send()
    }
  }

  const reset = () => {
    setEntries([])
    historyRef.current = []
  }

  return (
    <>
      {/* ── Bouton flottant ── */}
      <button
        className={`${styles.fab} ${open ? styles.fabOpen : ''}`}
        onClick={() => setOpen((v) => !v)}
        title={config.titre}
        aria-label={`Ouvrir ${config.titre}`}
      >
        {open ? <ChevronDown size={22} /> : <Bot size={22} />}
      </button>

      {/* ── Panneau de chat ── */}
      {open && (
        <div className={styles.panel}>
          {/* En-tête */}
          <div className={styles.header}>
            <div className={styles.headerLeft}>
              <div className={styles.agentAvatar}>
                <Bot size={16} />
              </div>
              <div>
                <div className={styles.agentName}>{config.titre}</div>
                <div className={styles.agentSub}>{config.sousTitre}</div>
              </div>
            </div>
            <div className={styles.headerActions}>
              {entries.length > 0 && (
                <button className={styles.iconBtn} onClick={reset} title="Réinitialiser la conversation">
                  <RotateCw size={15} />
                </button>
              )}
              <button className={styles.iconBtn} onClick={() => setOpen(false)} title="Fermer">
                <X size={16} />
              </button>
            </div>
          </div>

          {/* Corps */}
          <div className={styles.body}>
            <AiContentBanner compact message="Réponses générées par IA — à vérifier. Aucune action sensible n'est exécutée sans votre validation." />
            {entries.length === 0 ? (
              <WelcomeScreen config={config} onPrompt={(p) => void send(p)} />
            ) : (
              entries.map((entry) => (
                <MessageBubble key={entry.id} entry={entry} libelles={config.libellesOutils} />
              ))
            )}
            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <form className={styles.inputArea} onSubmit={onSubmit}>
            <textarea
              ref={inputRef}
              className={styles.textarea}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder="Posez une question ou donnez une instruction..."
              rows={2}
              disabled={loading}
            />
            <button
              type="submit"
              className={styles.sendBtn}
              disabled={!input.trim() || loading}
              title="Envoyer (Entrée)"
            >
              {loading ? <Loader2 size={18} className={styles.spin} /> : <Send size={18} />}
            </button>
          </form>
        </div>
      )}
    </>
  )
}

// ── Écran d'accueil ────────────────────────────────────────────────────────

function WelcomeScreen({ config, onPrompt }: { config: AgentChatConfig; onPrompt: (p: string) => void }) {
  return (
    <div className={styles.welcome}>
      <div className={styles.welcomeIcon}>
        <Bot size={32} />
      </div>
      <h3>{config.titre}</h3>
      <p>{config.accroche}</p>
      <div className={styles.quickPrompts}>
        {config.questionsSuggerees.map((p) => (
          <button key={p} className={styles.quickPrompt} onClick={() => onPrompt(p)}>
            {p}
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Bulle de message ──────────────────────────────────────────────────────────

function MessageBubble({ entry, libelles }: { entry: ChatEntry; libelles: Record<string, string> }) {
  const isUser = entry.role === 'user'

  return (
    <div className={`${styles.bubbleRow} ${isUser ? styles.userRow : styles.assistantRow}`}>
      {!isUser && (
        <div className={styles.botAvatar}>
          <Bot size={13} />
        </div>
      )}
      <div className={`${styles.bubble} ${isUser ? styles.userBubble : styles.assistantBubble} ${entry.error ? styles.errorBubble : ''}`}>
        {entry.loading ? (
          <span className={styles.typing}>
            <span /><span /><span />
          </span>
        ) : (
          <>
            <p className={styles.bubbleText}>{entry.content}</p>
            {entry.actions && entry.actions.length > 0 && (
              <div className={styles.actionTags}>
                <Wrench size={11} />
                {entry.actions.map((a) => (
                  <span key={a} className={styles.actionTag}>{libelles[a] || a}</span>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
