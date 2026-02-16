import { useEffect, useRef, useState } from 'react'
import { chatWithMind } from '../api/ai'
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
  const [open, setOpen] = useState(false)
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [thinking, setThinking] = useState(false)
  const listRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const messagesRef = useRef<Message[]>([])

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

  const sendMessage = async (text: string) => {
    const trimmed = text.trim()
    if (!trimmed) return
    const userMsg: Message = { id: `u-${Date.now()}`, role: 'user', content: trimmed }
    setMessages((prev) => [...prev, userMsg])
    setInput('')
    setThinking(true)

    try {
      const history = messagesRef.current.map((msg) => ({
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
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          id: `m-${Date.now()}`,
          role: 'mind',
          content: "Le service IA n'est pas disponible pour le moment.",
        },
      ])
    } finally {
      setThinking(false)
    }
  }

  return (
    <div className={styles.wrapper} aria-live="polite">
      {open && (
        <div className={styles.panel} role="dialog" aria-label="ONEC-Mind">
          <div className={styles.panelHeader}>
            <div>
              <div className={styles.title}>ONEC‑Mind</div>
              <div className={styles.subtitle}>Assistant financier interne</div>
            </div>
            <button className={styles.closeBtn} onClick={() => setOpen(false)} aria-label="Fermer">
              ×
            </button>
          </div>

          <div className={styles.messages} ref={listRef}>
            {messages.length === 0 && (
              <div className={styles.emptyState}>
                <div className={styles.emptyTitle}>Bonjour Christian 👋</div>
                <div className={styles.emptySub}>
                  Posez une question ou choisissez une suggestion rapide.
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
                            <span>Payé: {msg.widget.details.solid}</span>
                            <span>En attente: {msg.widget.details.ghost}</span>
                            <span>Budget: {msg.widget.details.limit}</span>
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
                <div className={styles.thinking}>
                  <span />
                  <span />
                  <span />
                </div>
              </div>
            )}
          </div>

          <div className={styles.suggestions}>
            {QUICK_SUGGESTIONS.map((label) => (
              <button key={label} type="button" className={styles.suggestion} onClick={() => sendMessage(label)}>
                {label}
              </button>
            ))}
          </div>

          <div className={styles.inputRow}>
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
              placeholder="Posez votre question…"
              className={styles.input}
            />
            <button className={styles.sendBtn} onClick={() => sendMessage(input)}>
              Envoyer
            </button>
          </div>
        </div>
      )}

      <button
        className={styles.orb}
        onClick={() => setOpen((prev) => !prev)}
        aria-label="Ouvrir ONEC‑Mind"
      >
        ✦
      </button>
    </div>
  )
}
