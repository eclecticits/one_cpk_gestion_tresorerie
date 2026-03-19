# 🚀 ONEC-Mind : Financial SaaS Infrastructure

**ONEC-Mind** est une plateforme de gestion de trésorerie et de gouvernance financière en mode SaaS (Software as a Service), conçue pour les organisations structurées et les institutions professionnelles en RDC.

**Status**: SaaS Production Ready

---

## 🌟 Vision du projet
Passer d'une gestion manuelle et fragmentée à une **transparence financière totale**. L'architecture multi-tenant permet au Conseil National et aux Conseils Provinciaux de cohabiter sur la même infrastructure tout en garantissant une étanchéité stricte des données.

---

## 🛠 Architecture & fonctionnalités SaaS

### 1) 🏢 Multi‑Tenancy & Isolation
- **Sous‑domaines dynamiques** : chaque organisation accède à son propre espace (ex: `cpk.onecmind.cd`).
- **Isolation stricte** : filtrage par `organisation_id` depuis le JWT, appliqué au niveau ORM.
- **White‑labeling** : personnalisation de l'interface (logos, devises, identités visuelles) par organisation.

### 2) 💳 Fintech & Paiements intégrés
- **Agrégateur ePaieLink** : encaissements Mobile Money + cartes.
- **Réconciliation automatique** : webhooks sécurisés (signature) pour mise à jour de la trésorerie.

### 3) 🎙️ Interface multimodale (AI Ready)
- **Web Speech API** : commandes vocales et lecture des rapports (accessibilité renforcée).
- **Transcription avancée** : intégration possible avec Whisper pour les motifs de dépenses.

### 4) 📊 Monitoring & Gouvernance (Super Admin)
- **Console SaaS** : supervision globale des tenants (statuts, volumétrie, abonnements).
- **Vue matérialisée SQL** : suivi rapide de la santé plateforme.
- **Reporting PDF** : rapports consolidés mensuels pour le Bureau National.
- **Audit logs** : traçabilité complète (qui, quoi, quand, organisation).

👉 Voir `docs/ARCHITECTURE.md` pour le schéma d’architecture.
👉 Voir `docs/ARCHITECTURE_DETAILED.md` pour le schéma détaillé.

---

## 🚀 Stack technique
- **Backend** : Python 3.10+ | FastAPI | SQLAlchemy | Alembic | PostgreSQL
- **Frontend** : React 18 | Vite | CSS Modules
- **Infra** : Docker & Docker Compose | Nginx (wildcard subdomains)
- **IA locale** : Ollama + Gemma 2 (2b)

---

## ⚙️ Installation rapide (Dev)

```bash
# 1. Cloner le projet
git clone https://github.com/eclecticits/one_cpk_gestion_tresorerie.git

# 2. Configurer les variables d'environnement
cp .env.example .env

# 2bis. (Optionnel) Démarrer Ollama + télécharger Gemma 2 (2b)
ollama run gemma2:2b

# 3. Lancer l'infrastructure
docker compose up --build -d

# 4. Appliquer les migrations
docker compose exec api alembic upgrade head
```

Variables IA locales (dans `.env`)
```bash
OLLAMA_URL=http://localhost:11434/api/generate
OLLAMA_MODEL=gemma2:2b
```

---

## 🔒 Sécurité & conformité
- **Authentification** : JWT + rôles (Super Admin, Admin, Comptable, Auditeur).
- **Intégrité** : validation de signature pour paiements entrants.
- **Isolation** : stockage des documents par UUID d'organisation.

---

## 🖼️ Captures d’écran
Place tes screenshots dans `docs/assets/` et référence-les ici. Exemples suggérés :
- Console Super Admin (KPIs & monitoring)
- Paramètres Organisation (logo/devise/plan)
- Rapport mensuel PDF
- Login white‑label (logo dynamique)

## 👨‍💻 Auteur
Christian KIDIKALA NGABA — Architecte Solution & Lead Developer

> “Transformer la finance institutionnelle par le code.”
