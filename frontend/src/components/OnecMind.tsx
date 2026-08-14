import { useEffect, useMemo, useRef, useState } from 'react'
import { Eraser, Mic, Send, Sparkles, Volume2, VolumeX, X } from 'lucide-react'
import { chatWithMind } from '../api/ai'
import AiContentBanner from './AiContentBanner'
import { useAuth } from '../contexts/AuthContext'
import styles from './OnecMind.module.css'

type Message = {
  id: string
  role: 'user' | 'mind'
  content: string
  widget?: {
    label: string
    value: string
    tone?: 'ok' | 'warn' | 'critical'
    type?: 'impact'
    solid?: number
    ghost?: number
    limit?: number
    details?: { solid: string; ghost: string; limit: string }
  }
}

const QUICK_SUGGESTIONS = [
  'Fais-moi un résumé de la semaine',
  'Quelles sont les réquisitions urgentes ?',
  'Qui a le plus gros budget restant ?',
]

export default function OnecMind() {
  const { user } = useAuth()
  const [open, setOpen] = useState(false)
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [thinking, setThinking] = useState(false)
  const [isListening, setIsListening] = useState(false)
  const [speechAvailable, setSpeechAvailable] = useState(false)
  const [isMuted, setIsMuted] = useState(false)
  const [lastResponse, setLastResponse] = useState('')
  const listRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const messagesRef = useRef<Message[]>([])
  const recognitionRef = useRef<any>(null)
  const panelRef = useRef<HTMLDivElement | null>(null)

  // Le prénom était écrit en dur dans l'accueil : tout le monde était salué
  // « Christian ».
  const prenom = useMemo(() => (user?.prenom || '').trim(), [user])

  useEffect(() => {
    if (open && inputRef.current) {
      inputRef.current.focus()
    }
  }, [open])

  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight
    }
  }, [messages, thinking])

  useEffect(() => {
    messagesRef.current = messages
  }, [messages])

  useEffect(() => {
    const speechCtor =
      typeof window !== 'undefined'
        ? (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
        : null
    setSpeechAvailable(!!speechCtor)
  }, [])

  useEffect(() => {
    if (!open && isListening && recognitionRef.current) {
      recognitionRef.current.stop()
      setIsListening(false)
    }
  }, [open, isListening])

  const sendMessage = async (text: string) => {
    const trimmed = text.trim()
    // Sans ce garde, un double-clic lance deux requêtes concurrentes dont les
    // réponses s'entremêlent dans le fil.
    if (!trimmed || thinking) return
    const userMsg: Message = { id: `u-${Date.now()}`, role: 'user', content: trimmed }
    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setThinking(true)

    try {
      const history: Array<{ role: 'user' | 'assistant'; content: string }> = messagesRef.current.map((msg) => ({
        role: msg.role === 'mind' ? 'assistant' : 'user',
        content: msg.content,
      }))
      const res = await chatWithMind({ message: trimmed, history })
      const reply: Message = {
        id: `m-${Date.now()}`,
        role: 'mind',
        content: res.answer || 'Je n’ai pas pu générer de réponse pour l’instant.',
        widget: res.widget,
      }
      setMessages((prev) => [...prev, reply])
      setLastResponse(reply.content)
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          id: `m-${Date.now()}`,
          role: 'mind',
          content: "Le service IA n'est pas disponible pour le moment.",
        },
      ])
      setLastResponse("Le service IA n'est pas disponible pour le moment.")
    } finally {
      setThinking(false)
    }
  }

  // La lecture vocale ne survit pas à la fermeture : sinon le navigateur
  // énonce des montants alors que l'assistant est fermé.
  useEffect(() => {
    if (!open && typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel()
    }
  }, [open])

  useEffect(() => {
    if (!open || !lastResponse || isMuted || typeof window === 'undefined') return
    if (!('speechSynthesis' in window)) return
    window.speechSynthesis.cancel()
    const utterance = new SpeechSynthesisUtterance(lastResponse)
    utterance.lang = 'fr-FR'
    utterance.rate = 1
    window.speechSynthesis.speak(utterance)
  }, [open, lastResponse, isMuted])

  const toggleListening = () => {
    const SpeechRecognition =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SpeechRecognition) {
      setSpeechAvailable(false)
      return
    }

    if (isListening && recognitionRef.current) {
      recognitionRef.current.stop()
      setIsListening(false)
      return
    }

    const recognition = recognitionRef.current ?? new SpeechRecognition()
    recognition.lang = 'fr-FR'
    recognition.interimResults = false
    recognition.maxAlternatives = 1

    recognition.onresult = (event: any) => {
      const transcript = event?.results?.[0]?.[0]?.transcript || ''
      if (transcript) {
        setInput(transcript)
        sendMessage(transcript)
      }
    }

    recognition.onerror = () => {
      setIsListening(false)
    }

    recognition.onend = () => {
      setIsListening(false)
    }

    recognitionRef.current = recognition
    setIsListening(true)
    recognition.start()
  }

  const effacerConversation = () => {
    setMessages([])
    setLastResponse('')
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel()
    }
  }

  return (
    <div className={styles.wrapper}>
      {open && (
        <div
          className={styles.panel}
          role="dialog"
          aria-label="Assistant ONEC Smart"
          ref={panelRef}
          onKeyDown={(e) => {
            if (e.key === 'Escape') setOpen(false)
          }}
        >
          <div className={styles.panelHeader}>
            <div className={styles.headerIdentity}>
              <span className={styles.headerAvatar} aria-hidden="true">
                <Sparkles size={16} />
              </span>
              <div className={styles.headerText}>
                <div className={styles.title}>Assistant ONEC Smart</div>
                <div className={styles.localAiBadge}>
                  <span className={styles.localAiDot} />
                  <span>Modèle local · données non transmises</span>
                </div>
              </div>
            </div>
            <div className={styles.headerActions}>
              <button
                className={styles.iconBtn}
                onClick={() => setIsMuted((prev) => !prev)}
                aria-label={isMuted ? 'Activer la lecture vocale' : 'Couper la lecture vocale'}
                title={isMuted ? 'Activer la lecture vocale' : 'Couper la lecture vocale'}
              >
                {isMuted ? <VolumeX size={15} /> : <Volume2 size={15} />}
              </button>
              {messages.length > 0 && (
                <button
                  className={styles.iconBtn}
                  onClick={effacerConversation}
                  aria-label="Effacer la conversation"
                  title="Effacer la conversation"
                >
                  <Eraser size={15} />
                </button>
              )}
              <button
                className={styles.iconBtn}
                onClick={() => setOpen(false)}
                aria-label="Fermer l'assistant"
                title="Fermer"
              >
                <X size={16} />
              </button>
            </div>
          </div>

          {/* Transparence IA : obligatoire sur toute vue produisant du contenu
              généré, et c'est ici que les chiffres les plus sensibles passent. */}
          <AiContentBanner
            compact
            message="Réponses générées par IA — vérifiez les chiffres avant toute décision."
          />

          {/* La région live ne couvre que le fil : posée sur tout le panneau,
              elle faisait relire l'en-tête et les suggestions à chaque frappe. */}
          <div
            className={styles.messages}
            ref={listRef}
            aria-live="polite"
            aria-atomic="false"
          >
            {messages.length === 0 && (
              <div className={styles.emptyState}>
                <span className={styles.emptyIcon} aria-hidden="true">
                  <Sparkles size={22} />
                </span>
                <div className={styles.emptyTitle}>
                  {prenom ? `Bonjour ${prenom}` : 'Bonjour'} 👋
                </div>
                <div className={styles.emptySub}>
                  Posez une question sur vos données, ou partez d'une suggestion.
                  Les réponses se limitent aux modules auxquels vous avez accès.
                </div>
              </div>
            )}

            {messages.map((msg) => (
              <div
                key={msg.id}
                className={`${styles.message} ${msg.role === 'user' ? styles.messageUser : styles.messageMind}`}
              >
                <div className={styles.bubble}>{msg.content}</div>
                {msg.widget && (
                  <details className={`${styles.widget} ${styles[`widget${msg.widget.tone || 'ok'}`]}`}>
                    <summary className={styles.widgetSummary}>
                      <span>{msg.widget.label}</span>
                      <span className={styles.widgetRight}>
                        <span className={styles.statusBadge}>
                          {msg.widget.tone === 'critical' ? '🔴' : msg.widget.tone === 'warn' ? '🟠' : '🟢'}
                        </span>
                        <strong>{msg.widget.value}</strong>
                      </span>
                    </summary>
                    {msg.widget.type === 'impact' && typeof msg.widget.limit === 'number' && (
                      <>
                        <div className={styles.impactBar}>
                          <div
                            className={styles.impactSolid}
                            style={{
                              width: `${Math.min(100, ((msg.widget.solid || 0) / msg.widget.limit) * 100)}%`,
                            }}
                          />
                          <div
                            className={styles.impactGhost}
                            style={{
                              width: `${Math.min(100, ((msg.widget.ghost || 0) / msg.widget.limit) * 100)}%`,
                            }}
                          />
                          <div className={styles.impactLimit} />
                        </div>
                        {msg.widget.details && (
                          <div className={styles.impactDetails}>
                            <span>Payé : {msg.widget.details.solid}</span>
                            <span>En attente : {msg.widget.details.ghost}</span>
                            <span>Budget : {msg.widget.details.limit}</span>
                          </div>
                        )}
                      </>
                    )}
                  </details>
                )}
              </div>
            ))}

            {thinking && (
              <div className={`${styles.message} ${styles.messageMind}`}>
                <div className={styles.thinking} aria-label="L'assistant rédige une réponse">
                  <span />
                  <span />
                  <span />
                </div>
              </div>
            )}
          </div>

          {messages.length === 0 && (
            <div className={styles.suggestions}>
              {QUICK_SUGGESTIONS.map((label) => (
                <button
                  key={label}
                  type="button"
                  className={styles.suggestion}
                  onClick={() => sendMessage(label)}
                  disabled={thinking}
                >
                  {label}
                </button>
              ))}
            </div>
          )}

          <div className={styles.inputRow}>
            <button
              type="button"
              className={`${styles.micBtn} ${isListening ? styles.micActive : ''}`}
              onClick={toggleListening}
              disabled={!speechAvailable || thinking}
              aria-label={isListening ? 'Arrêter la dictée' : 'Dicter la question'}
              title={speechAvailable ? 'Dicter la question' : 'Micro non disponible'}
            >
              <Mic size={16} />
            </button>
            <input
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  sendMessage(input)
                }
              }}
              placeholder={thinking ? 'Réponse en cours…' : 'Posez votre question…'}
              className={styles.input}
              disabled={thinking}
            />
            <button
              type="button"
              className={styles.sendBtn}
              onClick={() => sendMessage(input)}
              disabled={thinking || !input.trim()}
              aria-label="Envoyer la question"
              title="Envoyer"
            >
              <Send size={16} />
            </button>
          </div>
        </div>
      )}

      <button
        className={styles.orb}
        onClick={() => setOpen((prev) => !prev)}
        aria-label={open ? "Fermer l'assistant ONEC Smart" : "Ouvrir l'assistant ONEC Smart"}
        aria-expanded={open}
      >
        <Sparkles size={22} />
      </button>
    </div>
  )
}
