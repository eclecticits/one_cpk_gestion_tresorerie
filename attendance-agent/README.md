# ONEC Attendance Agent

Agent local de synchronisation des pointages vers ONEC Smart.

Architecture phase 1 :

```text
Pointeuse/Mock -> Agent local -> SQLite queue -> HTTPS -> ONEC Smart API
```

La phase 1 fonctionne sans pointeuse Hikvision réelle grâce au provider `mock`.
Le provider `hikvision` est volontairement un squelette : il faudra confirmer le
modèle, firmware, API/ISAPI/SDK, port et méthode d'authentification avant toute
implémentation matérielle.

## Configuration

Copier `config.example.json` vers un fichier local non versionné, par exemple :

```bash
cp config.example.json config.local.json
export ATTENDANCE_AGENT_API_BASE_URL="http://192.168.1.20:8000"
export ONEC_AGENT_TOKEN="token-agent-fourni-par-admin"
```

`ATTENDANCE_AGENT_API_BASE_URL` doit pointer vers ONEC Smart depuis la machine
où l'agent est installé. En LAN de développement, utiliser l'adresse IP du PC qui
expose le backend, par exemple `http://192.168.1.20:8000`. En production, utiliser
le domaine HTTPS, par exemple `https://onec.example.com`.

Ne jamais configurer un agent distant avec `localhost`, `127.0.0.1`,
`backend:8000` ou un nom interne Docker : ces adresses désignent la machine de
l'agent ou le réseau Docker, pas ONEC Smart.

Les secrets Hikvision doivent rester dans l'environnement local, jamais dans Git.

## Commandes

```bash
python -m onec_attendance_agent.cli --config config.local.json status
python -m onec_attendance_agent.cli --config config.local.json test-device CPK-HIK-MOCK
python -m onec_attendance_agent.cli --config config.local.json sync
python -m onec_attendance_agent.cli --config config.local.json run
```

Enrollment Phase 2 :

```bash
python -m onec_attendance_agent.cli enroll \
  --enrollment-url "http://192.168.1.20:8000/api/v1/hr/attendance-agent/enroll" \
  --enrollment-token "token-temporaire-fourni-par-onec-smart" \
  --out config.local.json
```

Le fichier généré contient l'identifiant agent, le token machine permanent et la
configuration de la pointeuse pour ce tenant. Le binaire reste universel.

## Installation service

Linux : créer un service `systemd` qui lance `python -m onec_attendance_agent.cli --config /etc/onec-attendance-agent/config.json run`.

Windows : utiliser un Windows Service via NSSM ou le Task Scheduler avec redémarrage automatique.

## Informations Hikvision à collecter

- modèle exact ;
- firmware ;
- IP/port local ;
- API ISAPI disponible ou SDK requis ;
- méthode d'authentification ;
- support push/event stream ou polling seulement ;
- format des identifiants employés ;
- timezone configurée sur l'appareil.
