# ONEC Smart

**ONEC Smart** est une plateforme intelligente de gestion intégrée de l'ONEC-RDC en mode SaaS (Software as a Service), conçue pour les organisations structurées et les institutions professionnelles en RDC.

**Status**: SaaS Production Ready

---

## Vision du projet
Passer d'une gestion manuelle et fragmentée à une **plateforme intégrée** couvrant la trésorerie, les ressources humaines, le secrétariat intelligent, les documents, les réunions, les rapports et l'administration. L'architecture multi-tenant permet au Conseil National et aux Conseils Provinciaux de cohabiter sur la même infrastructure tout en garantissant une étanchéité stricte des données.

---

## 🛠 Architecture & fonctionnalités SaaS

### 1) 🏢 Multi‑Tenancy & Isolation
- **Sous‑domaines dynamiques** : chaque organisation accède à son propre espace (ex: `cpk.onec-smart.cd`).
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

## 📄 Stockage des PDFs (Dev & Production)

### Dev local (uvicorn)
- Les fichiers sont stockés dans `backend/app/uploads/` si `UPLOAD_DIR` n’est pas défini.
- Tu peux forcer le chemin avec `UPLOAD_DIR=./app/uploads`.

### Docker (local)
- `docker-compose.yml` monte `./backend/app/uploads` pour garder les fichiers sur disque.

### Production (AWS/EC2)
1) Utiliser `docker-compose.prod.yml` (volume persistant) :
```bash
docker compose -f docker-compose.prod.yml up --build -d
```
2) Les fichiers sont stockés sur le disque hôte :  
`/var/www/one_cpk_data/uploads`

### Accès sécurisé (X-Accel-Redirect)
- En production, désactiver le service public des uploads :
  - `SERVE_UPLOADS_PUBLICLY=false`
- Côté frontend, activer l’accès sécurisé :
  - `VITE_SECURE_UPLOADS=true`
- Les fichiers sont servis via l’API sécurisée :
  - `GET /api/v1/secure-uploads/tenants/{tenant_uuid}/...`
- Nginx sert ensuite le fichier via un `internal` location.  
Un exemple est fourni : `docs/nginx/backend-secure-uploads.conf`.

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
