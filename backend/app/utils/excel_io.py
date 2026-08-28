"""Sérialisation des classeurs Excel hors de la boucle d'événements.

`Workbook.save()` est du CPU pur et représente ~80 % du coût d'un export
(2,3 s pour 20 000 lignes, mesuré le 17/08/2026). Appelé directement depuis une
coroutine, il fige la boucle d'événements : plus aucune requête n'avance, y
compris celles qui ne touchent pas à l'export. Sur un export volumineux le gel
dépasse le `--timeout` de gunicorn, qui tue alors le worker — et comme le
redémarrage prend plusieurs minutes, l'incident se propage à tous les
utilisateurs.

Tout export doit donc passer par `save_workbook()`.
"""

from __future__ import annotations

import logging
import time
from io import BytesIO

import anyio
from openpyxl import Workbook

logger = logging.getLogger("onec_cpk_api.excel")


def _volumetrie(wb: Workbook) -> tuple[int, int]:
    """Nombre de feuilles et nombre total de lignes du classeur."""
    lignes = 0
    for ws in wb.worksheets:
        lignes += ws.max_row or 0
    return len(wb.worksheets), lignes


def save_workbook_sync(wb: Workbook) -> BytesIO:
    """Sérialise le classeur en mémoire. À n'appeler que depuis un thread."""
    debut = time.monotonic()
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    taille = output.getbuffer().nbytes
    feuilles, lignes = _volumetrie(wb)
    # Volumétrie de sortie, pour les cinq exports d'un coup : c'est elle qui
    # dira où placer le seuil de bascule en génération asynchrone (phase 2 de
    # docs/architecture-exports-asynchrones-20260828.md). Le comptage se fait
    # APRÈS construction, à partir du classeur en mémoire : aucune requête
    # supplémentaire, et le contenu produit reste inchangé. La ligne se
    # rapproche du SLOW_REQUEST correspondant par l'horodatage.
    logger.info(
        "EXPORT_WORKBOOK feuilles=%d lignes=%d octets=%d serialisation_ms=%d",
        feuilles,
        lignes,
        taille,
        int((time.monotonic() - debut) * 1000),
    )
    return output


async def save_workbook(wb: Workbook) -> BytesIO:
    """Sérialise le classeur dans un thread, en laissant le worker disponible."""
    return await anyio.to_thread.run_sync(save_workbook_sync, wb)
