#!/usr/bin/env bash
# Validation de bout en bout de la generation d'exports en tache de fond.
#
#   ./valider_exports_asynchrones.sh reference    # capture le classeur synchrone
#   ./valider_exports_asynchrones.sh asynchrone   # soumet, suit, telecharge, compare
#   ./valider_exports_asynchrones.sh reprise      # tue le worker en plein job
#
# POURQUOI CE SCRIPT EXISTE. Les phases 0 a 2 ont ete ecrites sans qu'aucune
# base, aucun Redis ni aucun Docker ne soit joignable : la chaine complete n'a
# jamais tourne une seule fois. Ce n'est pas un detail de verification, c'est LE
# risque restant. Le jour ou la pile redemarre, il vaut mieux derouler une
# sequence prevue que deboguer a l'aveugle — surtout pour les trois criteres du
# §7 du document d'architecture, qui ne sont pas des mesures de performance mais
# des proprietes de correction.
#
# Ce que le script NE fait pas : basculer le drapeau lui-meme. `EXPORT_ASYNC_TYPES`
# est lu au demarrage par le backend ET par le worker ; le changer suppose de
# toucher .env puis de redemarrer les deux. Le script detecte le regime a partir
# du code HTTP recu (200 ou 202) et dit quoi faire, plutot que de supposer un
# etat qu'il ne controle pas.

set -uo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RACINE_DEPOT="${RACINE_DEPOT:-$(cd "$ICI/../../../.." && pwd)}"
BASE_URL="${BASE_URL:-http://localhost:8000/api/v1}"
CONTEXTE="${CONTEXTE:-$ICI/../k6/context.json}"
COMPOSE_FILE="${COMPOSE_FILE:-$RACINE_DEPOT/docker-compose.yml}"
SORTIE="${SORTIE:-$ICI/../resultats/validation_exports}"
TYPE_EXPORT="${TYPE_EXPORT:-budget}"
DELAI_MAX="${DELAI_MAX:-600}"

DC="docker compose -f $COMPOSE_FILE"
mkdir -p "$SORTIE"

if [ ! -f "$CONTEXTE" ]; then
  echo "ERREUR : $CONTEXTE absent. Executez seed/mint_tokens.py." >&2
  exit 1
fi

mapfile -t CTX < <(python3 -c "
import json
d = json.load(open('$CONTEXTE'))
u = [x for x in d['utilisateurs'] if x.get('plein_droit')] or d['utilisateurs']
print(u[0]['token'])
print(d['organisation_id'])
print(d.get('annee', ''))
")
JETON="${CTX[0]}"; ORG="${CTX[1]}"; ANNEE="${CTX[2]}"

appel() {
  # Rend « code|corps » : le code HTTP porte ici l'information principale
  # (200 = synchrone, 202 = mis en file, 402/413/429 = refus explicites).
  local methode="$1" chemin="$2" fichier="${3:-/dev/null}"
  local code
  code="$(curl -s -o "$fichier" -w '%{http_code}' -m 120 -X "$methode" \
    -H "Authorization: Bearer $JETON" -H "X-Tenant-ID: $ORG" \
    "$BASE_URL$chemin" 2>/dev/null)"
  echo "$code"
}

verdict() {
  # Un verdict par critere, en clair : ce script sera relu par quelqu'un qui
  # cherche ce qui a casse, pas par quelqu'un qui connait deja la reponse.
  if [ "$1" = "ok" ]; then echo "  [OK]    $2"; else echo "  [ECHEC] $2" >&2; ECHECS=$((ECHECS + 1)); fi
}
ECHECS=0

# ── Suivi d'un job jusqu'a son etat final ───────────────────────────────────
suivre_job() {
  local id="$1" debut statut progression corps
  debut=$(date +%s)
  corps="$SORTIE/job_$id.json"
  while :; do
    appel GET "/exports/jobs/$id" "$corps" > /dev/null
    statut="$(python3 -c "import json;print(json.load(open('$corps')).get('status',''))" 2>/dev/null)"
    progression="$(python3 -c "import json;print(json.load(open('$corps')).get('progress',''))" 2>/dev/null)"
    case "$statut" in
      DONE|FAILED|EXPIRED|CANCELLED) echo "$statut"; return 0 ;;
      "") echo "ILLISIBLE"; return 1 ;;
    esac
    if [ $(( $(date +%s) - debut )) -gt "$DELAI_MAX" ]; then echo "DELAI_DEPASSE"; return 1; fi
    printf '\r    %s %s%%   ' "$statut" "$progression" >&2
    sleep 2
  done
}

cas_reference() {
  echo "== Reference : chemin synchrone =="
  local code
  code="$(appel GET "/exports/$TYPE_EXPORT?annee=$ANNEE" "$SORTIE/reference.xlsx")"
  if [ "$code" = "202" ]; then
    echo "  Le type « $TYPE_EXPORT » est DEJA bascule (202). Fermez EXPORT_ASYNC_TYPES," >&2
    echo "  redemarrez backend et exports-worker, puis relancez ce cas." >&2
    exit 1
  fi
  [ "$code" = "200" ] && verdict ok "chemin synchrone : 200" || verdict ko "chemin synchrone : HTTP $code"
  # Un classeur vide passerait les controles de statut sans rien prouver.
  local taille; taille=$(stat -c%s "$SORTIE/reference.xlsx" 2>/dev/null || echo 0)
  [ "$taille" -gt 1000 ] && verdict ok "classeur de reference : $taille octets" \
                         || verdict ko "classeur de reference vide ou minuscule ($taille octets)"
}

cas_asynchrone() {
  echo "== Chaine asynchrone : soumission, file, worker, artefact =="
  local code id statut taille
  code="$(appel GET "/exports/$TYPE_EXPORT?annee=$ANNEE" "$SORTIE/soumission.json")"
  if [ "$code" = "200" ]; then
    echo "  Reponse 200 : le type n'est pas bascule. Posez dans .env" >&2
    echo "    EXPORT_ASYNC_TYPES=$TYPE_EXPORT" >&2
    echo "    EXPORT_ASYNC_ROW_THRESHOLD=0        # sinon un petit export reste synchrone" >&2
    echo "  puis redemarrez backend ET exports-worker." >&2
    exit 1
  fi
  [ "$code" = "202" ] && verdict ok "soumission : 202" || verdict ko "soumission : HTTP $code"
  [ "$code" = "202" ] || return

  id="$(python3 -c "import json;print(json.load(open('$SORTIE/soumission.json'))['id'])")"
  echo "  job $id"
  statut="$(suivre_job "$id")"; printf '\r%*s\r' 40 '' >&2
  [ "$statut" = "DONE" ] && verdict ok "job termine" || verdict ko "job en statut $statut"
  [ "$statut" = "DONE" ] || return

  # Le corps VIDE est le piege : sans la location internal de nginx,
  # X-Accel-Redirect est ignore et le navigateur enregistre 0 octet en .xlsx.
  appel GET "/exports/jobs/$id/download" "$SORTIE/asynchrone.xlsx" > /dev/null
  taille=$(stat -c%s "$SORTIE/asynchrone.xlsx" 2>/dev/null || echo 0)
  [ "$taille" -gt 1000 ] && verdict ok "artefact telecharge : $taille octets" \
                         || verdict ko "artefact vide ($taille octets) — X-Accel-Redirect non traite ?"

  # Le critere qui compte vraiment : le fichier doit etre le MEME que celui du
  # chemin direct. Deux chemins qui produisent deux classeurs differents, c'est
  # la divergence que toute l'architecture cherche a rendre impossible.
  if [ -f "$SORTIE/reference.xlsx" ] && [ "$taille" -gt 1000 ]; then
    if python3 "$ICI/comparer_classeurs.py" "$SORTIE/reference.xlsx" "$SORTIE/asynchrone.xlsx"; then
      verdict ok "classeur asynchrone identique au synchrone"
    else
      verdict ko "classeur asynchrone DIFFERENT du synchrone"
    fi
  else
    echo "  (comparaison ignoree : lancez d'abord le cas « reference »)"
  fi

  # Cloisonnement : le job doit appartenir a l'organisation qui l'a demande.
  appel GET "/exports/jobs?limite=5" "$SORTIE/liste.json" > /dev/null
  python3 - "$SORTIE/liste.json" "$id" <<'PY' && verdict ok "job visible dans la liste de son organisation" \
                                            || verdict ko "job absent de la liste"
import json, sys
d = json.load(open(sys.argv[1]))
sys.exit(0 if any(j["id"] == sys.argv[2] for j in d.get("items", [])) else 1)
PY
}

cas_reprise() {
  echo "== Reprise : un worker tue en plein job doit repartir et finir =="
  local code id statut
  code="$(appel GET "/exports/$TYPE_EXPORT?annee=$ANNEE" "$SORTIE/soumission_reprise.json")"
  [ "$code" = "202" ] || { echo "  Type non bascule (HTTP $code)." >&2; exit 1; }
  id="$(python3 -c "import json;print(json.load(open('$SORTIE/soumission_reprise.json'))['id'])")"
  echo "  job $id — arret brutal du worker dans 2 s"
  sleep 2
  $DC kill exports-worker >/dev/null 2>&1
  $DC up -d exports-worker >/dev/null 2>&1
  # Le bail dure EXPORT_JOB_LEASE_SECONDS (300 s par defaut) : la reprise n'est
  # pas immediate, c'est le balayage a la minute qui la declenche une fois le
  # bail expire. D'ou un delai d'attente volontairement large ici.
  statut="$(DELAI_MAX=900 suivre_job "$id")"; printf '\r%*s\r' 40 '' >&2
  [ "$statut" = "DONE" ] && verdict ok "job repris et termine apres la mort du worker" \
                         || verdict ko "job en statut $statut apres la mort du worker"
}

case "${1:-}" in
  reference)  cas_reference ;;
  asynchrone) cas_asynchrone ;;
  reprise)    cas_reprise ;;
  *) echo "usage : $0 {reference|asynchrone|reprise}" >&2; exit 2 ;;
esac

echo
[ "$ECHECS" -eq 0 ] && echo "Tous les criteres sont satisfaits." || echo "$ECHECS critere(s) en echec." >&2
exit $(( ECHECS > 0 ))
