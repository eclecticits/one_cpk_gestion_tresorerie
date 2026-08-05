from __future__ import annotations

"""Validation défensive des fichiers uploadés.

Le type déclaré par le client (``Content-Type``) et l'extension du nom de
fichier sont tous deux sous son contrôle : ils ne prouvent rien sur le contenu
réel. Ces helpers ajoutent (1) un plafond de taille appliqué pendant la lecture
plutôt qu'après, et (2) une vérification de la signature binaire du fichier.
"""

from fastapi import HTTPException, UploadFile, status

CHUNK_SIZE = 64 * 1024

# Signatures binaires ("magic bytes") des formats acceptés.
MAGIC_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "application/pdf": (b"%PDF-",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/jpg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
}


def content_length_exceeds(content_length: str | None, max_bytes: int) -> bool:
    """Vrai si l'en-tête Content-Length annonce déjà un corps trop gros.

    Permet de refuser avant d'avoir consommé le corps de la requête. L'en-tête
    étant déclaratif, il ne dispense pas du plafond appliqué à la lecture.
    """
    if not content_length:
        return False
    try:
        return int(content_length) > max_bytes
    except (TypeError, ValueError):
        return False


async def read_upload_limited(file: UploadFile, max_bytes: int, *, error_detail: str) -> bytes:
    """Lit le fichier par blocs et abandonne dès le dépassement du plafond.

    ``await file.read()`` sans argument matérialise l'intégralité du corps avant
    tout contrôle : un client peut faire gonfler le worker à volonté.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_detail)
        chunks.append(chunk)
    return b"".join(chunks)


def matches_declared_type(contents: bytes, content_type: str) -> bool:
    """Vrai si le contenu porte bien la signature du type déclaré."""
    signatures = MAGIC_SIGNATURES.get((content_type or "").lower())
    if not signatures:
        return False
    return any(contents.startswith(signature) for signature in signatures)
