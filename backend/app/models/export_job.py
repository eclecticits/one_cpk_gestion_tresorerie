"""Jobs de génération d'export : la vérité vit ici, pas dans Redis.

Pourquoi une table et pas une clé Redis : `app/core/cache.py` traite Redis comme
faillible **par conception** — toutes ses opérations avalent `RedisError` et
retournent `None`. C'est le bon choix pour un cache, et c'est exactement ce qui
interdit d'en faire la source de vérité d'un job. Un `FLUSHALL` ou un
redémarrage sans persistance effacerait l'historique des exports d'une
organisation. Ici, PostgreSQL porte l'état, Redis ne transporte qu'un
identifiant ; si le message est perdu, le balayage des jobs `QUEUED` trop vieux
les remet en file. La criticité de Redis reste celle qu'elle a aujourd'hui :
dégradation, pas perte.

Voir docs/architecture-exports-asynchrones-20260828.md pour la cible complète.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Vocabulaire ──────────────────────────────────────────────────────────────
# Des constantes de chaînes plutôt qu'un Enum PostgreSQL, comme pour
# notification_logs : ajouter un statut ne doit pas exiger un ALTER TYPE, qui
# verrouille la table.

STATUT_EN_FILE = "QUEUED"
STATUT_EN_COURS = "RUNNING"
STATUT_TERMINE = "DONE"
STATUT_ECHOUE = "FAILED"
STATUT_EXPIRE = "EXPIRED"
STATUT_ANNULE = "CANCELLED"

# Statuts au-delà desquels le job ne bougera plus de lui-même.
STATUTS_FINAUX = frozenset({STATUT_TERMINE, STATUT_ECHOUE, STATUT_EXPIRE, STATUT_ANNULE})
# Statuts qui occupent la file : servent au contrôle d'équité entre tenants.
STATUTS_ACTIFS = frozenset({STATUT_EN_FILE, STATUT_EN_COURS})


class ExportJob(Base):
    """Une demande d'export, de sa soumission à la péremption de son fichier."""

    __tablename__ = "export_jobs"

    # L'identifiant est public : il voyage dans l'URL de consultation et donne
    # son nom au fichier produit. UUID et non séquence, pour qu'il ne révèle ni
    # le volume d'exports de la plateforme ni celui des autres organisations.
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Cloisonnement. NON NULLABLE, contrairement à notification_logs : un job
    # sans organisation serait un job dont le worker ne saurait pas quel
    # contexte tenant poser, donc un job qui produirait un fichier non filtré.
    # La contrainte est le premier des trois garde-fous du §4.1.
    # Pas d'`index=True` ici : l'index composite (organisation_id, created_at)
    # ci-dessous a organisation_id en tête et sert les mêmes recherches. Un
    # index simple en plus serait redondant — c'est précisément ce que
    # perf-postgres.md reproche à une vingtaine d'index existants.
    organisation_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("organisations.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Qui a demandé. ON DELETE SET NULL : la suppression d'un compte ne doit pas
    # effacer la trace de l'export ni son fichier.
    # Pas d'index : aucune requête ne cherche par demandeur aujourd'hui. On en
    # ajoutera un le jour où un écran « mes exports à moi » existera, pas avant.
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Quoi exporter, et avec quels filtres. `params` est repris tel quel par le
    # worker : c'est le contrat entre l'endpoint et la tâche.
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Empreinte de (type + params + organisation), pour la déduplication : le
    # motif « l'utilisateur clique cinq fois parce que rien ne se passe » a été
    # observé dans les tirs de charge, et il coûte cinq fois le prix.
    params_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # Les quatre `server_default` de ce modèle — `status` et `progress` ici,
    # `attempts` et `created_at` plus bas — ne servent jamais à l'ORM, qui
    # fournit toujours la valeur. Ils sont là parce que la MIGRATION les
    # déclare : sans eux, `alembic revision --autogenerate` proposerait à chaque
    # passage un `alter_column` pour combler un écart qui n'existe qu'entre les
    # deux fichiers, et ce bruit finirait par masquer une vraie divergence.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=STATUT_EN_FILE, server_default=STATUT_EN_FILE
    )
    # Retour à l'utilisateur pendant l'attente. `progress` est un pourcentage
    # grossier : il vaut mieux une barre approximative qu'un écran figé.
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Artefact produit. `file_path` est RELATIF à UPLOAD_DIR : un chemin absolu
    # en base rendrait la table dépendante du montage, et casserait au premier
    # déplacement du volume.
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Échec exploitable côté interface, sans trace technique : `error_code` pour
    # décider quoi afficher, `error_message` pour le dire à l'utilisateur.
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Reprise après mort du worker. Le générateur a déjà été tué par l'OOM-killer
    # pendant la campagne du 27/08 : un job RUNNING dont le worker meurt resterait
    # bloqué pour toujours sans bail. `lease_until` est renouvelé pendant le
    # traitement ; le balayage remet en file ce dont le bail a expiré.
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(80), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=text("now()")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Péremption de l'ARTEFACT, pas du job : la ligne reste pour l'historique,
    # le fichier est supprimé. Ces classeurs portent des données financières
    # nominatives et ne doivent pas s'accumuler indéfiniment sur disque.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # La liste « Mes exports » : par organisation, les plus récents d'abord.
        Index("ix_export_jobs_org_created", "organisation_id", "created_at"),
        # Équité entre organisations : « cette organisation a-t-elle déjà un job
        # actif ? », posée à chaque soumission.
        Index("ix_export_jobs_org_status", "organisation_id", "status"),
        # Déduplication : « un artefact identique et récent existe-t-il ? »
        Index("ix_export_jobs_dedup", "organisation_id", "params_hash", "status"),
        # Balayages du worker : baux expirés, puis artefacts périmés. Deux index
        # partiels, parce que ces requêtes ne regardent qu'une fraction infime
        # de la table et tournent en boucle.
        Index(
            "ix_export_jobs_baux",
            "lease_until",
            postgresql_where=text("status = 'RUNNING'"),
        ),
        Index(
            "ix_export_jobs_peremption",
            "expires_at",
            postgresql_where=text("status = 'DONE'"),
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - confort de débogage
        return f"<ExportJob {self.type} {self.status} org={self.organisation_id} id={self.id}>"
