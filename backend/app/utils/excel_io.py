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

from io import BytesIO

import anyio
from openpyxl import Workbook


def save_workbook_sync(wb: Workbook) -> BytesIO:
    """Sérialise le classeur en mémoire. À n'appeler que depuis un thread."""
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output


async def save_workbook(wb: Workbook) -> BytesIO:
    """Sérialise le classeur dans un thread, en laissant le worker disponible."""
    return await anyio.to_thread.run_sync(save_workbook_sync, wb)
