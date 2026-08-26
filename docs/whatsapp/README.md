# Notifications WhatsApp — index de la documentation

Le canal WhatsApp est livré par le commit `666855a` (24/08/2026). Cette page dit
où regarder, et surtout ce qu'il ne faut plus croire dans les rapports archivés.

## Où se trouve le code

| Sujet | Emplacement |
|---|---|
| Routeur HTTP | `backend/app/api/v1/endpoints/whatsapp.py` |
| Schémas Pydantic | `backend/app/schemas/whatsapp.py` |
| Service et fournisseurs | `backend/app/services/notifications/` |
| Journal d'envoi | `backend/app/models/notification_log.py` |
| Migration | `backend/alembic/versions/20260823_whatsapp_notifs.py` |
| Écran de réglages | `frontend/src/components/settings/WhatsAppSettings.tsx` |
| Appels typés | `frontend/src/api/whatsapp.ts` |

Trois fournisseurs sont enregistrés dans `notifications/providers/registry.py` :
Evolution API (Baileys, auto-hébergé), Meta WhatsApp Business Cloud et Twilio.

La clé API entre par `PUT /whatsapp/settings`, part chez `encrypt_secret` et ne
ressort d'aucune route, sous aucune forme — `has_api_key: bool` est la seule
information rendue à son sujet.

## Rapports de livraison — archives, à lire avec précaution

Les quatre `RAPPORT-*.md` sont les notes de livraison des agents qui ont écrit le
module. Ils gardent leur valeur pour le **pourquoi** des décisions ; ils ne sont
pas une référence à jour :

- ils citent des chemins `/home/claude/wa/…` qui n'existent pas dans ce dépôt ;
- ils citent des décomptes de lignes d'avant la fusion (p. ex. `Settings.tsx`
  « 3 722 → 3 685 » alors que le fichier a bougé plusieurs fois depuis).

| Fichier | Contenu | Statut |
|---|---|---|
| `RAPPORT-api.md` | Endpoints, charges utiles, traitement du secret | rationale à jour, chemins périmés |
| `RAPPORT-frontend.md` | Découpage de l'écran de réglages | rationale à jour, décomptes périmés |
| `RAPPORT-hooks.md` | Branchement des six événements sur la production | rationale à jour, décomptes périmés |
| `RAPPORT-migration.md` | Schéma, colonnes ajoutées, idempotence | rationale à jour, chemins périmés |

## Correctif de code mort — appliqué

`requisitions-code-mort.patch` accompagnait ces rapports : il retirait les 78
lignes inatteignables qui suivaient le `return` de `vise_requisition`, ainsi que
l'import déprécié `app.services.whatsapp` devenu sans usage.

**Il a été appliqué le 26/08/2026** (`requisitions.py` : 2 382 → 2 299 lignes), et
le fichier `.patch` a été retiré pour qu'on ne tente pas de le rejouer. Le
raisonnement complet — en particulier pourquoi il fallait *supprimer* ce bloc et
non le « réanimer », `old_status` n'y étant jamais assignée — est conservé dans
le message du commit et dans l'historique Git du fichier `.patch`.
