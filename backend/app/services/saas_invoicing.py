"""Facturation émise aux tenants — identité de l'éditeur, numérotation, PDF.

Deux chemins mènent à une facture SaaS, et ce module les fait converger :

* **paiement en ligne** — le tenant règle, la facture naît déjà acquittée
  (`saas_billing_notifications.create_and_send_saas_invoice`) ;
* **facturation émise** — l'éditeur établit la facture, le tenant la règle
  ensuite, en ligne ou par un moyen hors plateforme (virement, mobile money,
  espèces) constaté ici par un super-admin.

Le second chemin impose trois choses que le premier n'avait pas besoin de
connaître : une identité d'émetteur, une numérotation séquentielle sans trou, et
un PDF qui vaut demande de paiement — donc qui porte les coordonnées de
règlement tant que la facture n'est pas soldée.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import anyio
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.organisation import Organisation
from app.models.platform_settings import PlatformSettings
from app.models.saas_invoice import SaaSInvoice

# ── Identité de l'éditeur ────────────────────────────────────────────────────
# Seul le nom commercial est connu du code. Tout ce qui est légal ou bancaire
# (RCCM, NIF, IBAN…) reste vide par défaut : ces mentions engagent l'entreprise
# et figureront sur des pièces envoyées à de vrais clients. Elles se saisissent
# depuis la console, jamais depuis une valeur codée en dur.
ISSUER_DEFAULTS: dict[str, object] = {
    "name": "Eclectic IT Services",
    "tagline": "Édition et hébergement de solutions de gestion",
    "address": "",
    "city": "",
    "country": "",
    "email": "",
    "phone": "",
    "website": "",
    "rccm": "",
    "id_nat": "",
    "tax_id": "",
    "bank_name": "",
    "bank_account": "",
    "bank_swift": "",
    "mobile_money": "",
    "payment_terms_days": 15,
    # Quelles voies de reglement la facture annonce. Un client sous contrat
    # cadre reglant toujours par virement n'a pas a lire une invitation au
    # paiement en ligne, et inversement : l'affichage se choisit, il ne
    # s'impose pas.
    "online_payment_enabled": True,
    "manual_payment_enabled": True,
    "invoice_prefix": "EIS",
    "footer_note": "",
}

ISSUER_TEXT_FIELDS = tuple(k for k, v in ISSUER_DEFAULTS.items() if isinstance(v, str))

INVOICE_STATUSES = ("DRAFT", "ISSUED", "PAID", "CANCELLED")
OPEN_STATUSES = ("DRAFT", "ISSUED")

PAYMENT_METHODS = {
    "BANK_TRANSFER": "Virement bancaire",
    "MOBILE_MONEY": "Mobile money",
    "CASH": "Espèces",
    "CHECK": "Chèque",
    "ONLINE": "Paiement en ligne",
    "OTHER": "Autre",
}

logger = logging.getLogger("onec_cpk_api.saas_invoicing")

# ── Palette de la facture ────────────────────────────────────────────────────
#
# Le document reprenait un vert fixe, quelle que soit la marque imprimée juste
# au-dessus. La couleur d'accent se déduit maintenant du logo de l'éditeur ; à
# défaut de logo, on retombe sur la teinte alignée sur les exports Excel
# budget, pour que les documents sortant de la plateforme restent d'une même
# famille visuelle.

MARQUE_DEFAUT = "#0F766E"

_ENCRE = colors.HexColor("#0F172A")
_GRIS = colors.HexColor("#64748B")


@dataclass(frozen=True)
class Palette:
    """Les couleurs d'un rendu.

    `marque` est la teinte du logo, telle quelle : elle ne sert qu'à remplir
    des aplats. `accent` en est la version lisible sur blanc — un jaune de
    marque écrit en toutes lettres passerait pour une impression ratée.
    """

    marque: colors.Color
    accent: colors.Color
    ligne: colors.Color
    bandeau: colors.Color
    encre: colors.Color = _ENCRE
    gris: colors.Color = _GRIS


def _hex_vers_rgb(valeur: object) -> tuple[int, int, int] | None:
    brut = str(valeur or "").strip().lstrip("#")
    if len(brut) != 6:
        return None
    try:
        return (int(brut[0:2], 16), int(brut[2:4], 16), int(brut[4:6], 16))
    except ValueError:
        return None


def _rgb_vers_hex(rgb: tuple[int, int, int]) -> str:
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(canal))) for canal in rgb)


def _luminance(rgb: tuple[int, int, int]) -> float:
    """Luminance relative WCAG, celle qui sert à mesurer un contraste."""
    canaux = []
    for canal in rgb:
        c = canal / 255
        canaux.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * canaux[0] + 0.7152 * canaux[1] + 0.0722 * canaux[2]


def _contraste_sur_blanc(rgb: tuple[int, int, int]) -> float:
    return 1.05 / (_luminance(rgb) + 0.05)


def _melanger(rgb: tuple[int, int, int], vers: tuple[int, int, int], part: float) -> tuple[int, int, int]:
    """`part` = 0 garde la couleur, 1 donne `vers`."""
    part = max(0.0, min(1.0, part))
    return tuple(round(canal + (cible - canal) * part) for canal, cible in zip(rgb, vers))  # type: ignore[return-value]


def _lisible_sur_blanc(rgb: tuple[int, int, int], cible: float = 4.5) -> tuple[int, int, int]:
    """Assombrit une teinte jusqu'à ce qu'elle se lise sur le papier.

    On tire vers le noir plutôt que vers une teinte voisine : la couleur reste
    reconnaissable comme celle de la marque, seulement plus sombre.
    """
    couleur = rgb
    for _ in range(20):
        if _contraste_sur_blanc(couleur) >= cible:
            return couleur
        couleur = _melanger(couleur, (0, 0, 0), 0.12)
    return couleur


def couleur_dominante(chemin: str) -> str:
    """Couleur de marque d'un logo, ou chaîne vide s'il n'en porte pas.

    Les pixels transparents, le blanc et le noir sont écartés : un logo posé
    sur un fond blanc donnerait sinon toujours du blanc. Restent les pixels
    colorés, groupés par teintes voisines ; le groupe le plus étendu l'emporte.
    Un logo entièrement gris n'a pas de couleur de marque — on le dit, plutôt
    que d'inventer une teinte.
    """
    if not chemin or not os.path.exists(chemin):
        return ""
    try:
        with Image.open(chemin) as image:
            vignette = image.convert("RGBA")
            # 160 px suffisent pour une dominante et bornent le coût : un logo
            # de 2 Mo ne doit pas coûter une seconde de calcul à l'envoi.
            vignette.thumbnail((160, 160))
            pixels = list(vignette.getdata())
    except Exception:  # noqa: BLE001 - un logo illisible ne bloque pas l'envoi
        logger.exception("Logo illisible, couleur de marque indéterminée : %s", chemin)
        return ""

    groupes: dict[tuple[int, int, int], list[tuple[int, int, int]]] = {}
    for pixel in pixels:
        rouge, vert, bleu, alpha = pixel
        if alpha < 200:
            continue
        haut, bas = max(rouge, vert, bleu), min(rouge, vert, bleu)
        if haut < 40:  # quasi noir
            continue
        if (haut - bas) / haut < 0.25:  # gris, blanc compris
            continue
        cle = (rouge // 32, vert // 32, bleu // 32)
        groupes.setdefault(cle, []).append((rouge, vert, bleu))

    if not groupes:
        return ""
    groupe = max(groupes.values(), key=len)
    moyenne = tuple(sum(pixel[i] for pixel in groupe) // len(groupe) for i in range(3))
    return _rgb_vers_hex(moyenne)  # type: ignore[arg-type]


def palette_facture(marque: object = None) -> Palette:
    """Palette du document à partir d'une couleur de marque (hex, ou rien)."""
    rgb = _hex_vers_rgb(marque) or _hex_vers_rgb(MARQUE_DEFAUT)
    assert rgb is not None  # MARQUE_DEFAUT est un hex valide
    blanc = (255, 255, 255)
    return Palette(
        marque=colors.HexColor(_rgb_vers_hex(rgb)),
        accent=colors.HexColor(_rgb_vers_hex(_lisible_sur_blanc(rgb))),
        # Filets et aplats : la teinte n'y est qu'un souffle, sinon le tableau
        # se met à crier plus fort que les montants qu'il porte.
        ligne=colors.HexColor(_rgb_vers_hex(_melanger(rgb, blanc, 0.86))),
        bandeau=colors.HexColor(_rgb_vers_hex(_melanger(rgb, blanc, 0.94))),
    )


PALETTE_DEFAUT = palette_facture()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _upload_root() -> str:
    default_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "uploads"))
    return os.path.abspath(settings.upload_dir) if settings.upload_dir else default_root


def _fmt_date(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone(timezone.utc).strftime("%d/%m/%Y")


def _fmt_money(amount: Decimal | float | int, currency: str) -> str:
    return f"{float(amount):,.2f} {currency}".replace(",", " ")


def to_decimal(value: object, field: str) -> Decimal:
    """Convertit en Decimal en refusant les entrées inexploitables.

    Les montants transitent en JSON, donc en float ou en chaîne. Passer par
    `str()` avant `Decimal` évite d'hériter du bruit binaire d'un float.
    """
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Montant invalide pour {field} : {value!r}") from exc
    if result.is_nan() or result.is_infinite():
        raise ValueError(f"Montant invalide pour {field} : {value!r}")
    return result.quantize(Decimal("0.01"))


# ── Identité éditeur : lecture / écriture ────────────────────────────────────


async def _platform_settings(db: AsyncSession) -> PlatformSettings:
    res = await db.execute(select(PlatformSettings).where(PlatformSettings.id == 1))
    row = res.scalar_one_or_none()
    if row is None:
        row = PlatformSettings(id=1, billing_config={})
        db.add(row)
        await db.flush()
    return row


def merge_issuer(raw: object) -> dict:
    """Complète une configuration partielle avec les valeurs par défaut."""
    stored = raw if isinstance(raw, dict) else {}
    issuer = dict(ISSUER_DEFAULTS)
    for key in ISSUER_DEFAULTS:
        value = stored.get(key)
        if value is None:
            continue
        if key == "payment_terms_days":
            try:
                issuer[key] = max(0, int(value))
            except (TypeError, ValueError):
                continue
        elif isinstance(ISSUER_DEFAULTS[key], bool):
            issuer[key] = bool(value)
        else:
            issuer[key] = str(value).strip()
    if not str(issuer.get("name") or "").strip():
        issuer["name"] = str(ISSUER_DEFAULTS["name"])
    if not str(issuer.get("invoice_prefix") or "").strip():
        issuer["invoice_prefix"] = str(ISSUER_DEFAULTS["invoice_prefix"])
    return issuer


async def get_issuer(db: AsyncSession) -> dict:
    row = await _platform_settings(db)
    config = row.billing_config if isinstance(row.billing_config, dict) else {}
    return merge_issuer(config.get("issuer"))


async def save_issuer(db: AsyncSession, payload: dict) -> dict:
    row = await _platform_settings(db)
    config = dict(row.billing_config) if isinstance(row.billing_config, dict) else {}
    issuer = merge_issuer({**(config.get("issuer") or {}), **payload})
    config["issuer"] = issuer
    # Réaffectation complète : SQLAlchemy ne détecte pas la mutation d'un JSONB
    # modifié en place.
    row.billing_config = config
    row.updated_at = _utcnow()
    return issuer


# ── Logo de l'éditeur ────────────────────────────────────────────────────────
#
# Le fichier vit sur disque comme les autres pièces de l'application ; seul
# son descripteur est rangé dans `billing_config`. Le mettre en base64 dans le
# JSONB aurait fait grossir une ligne relue à chaque facture.

LOGO_CONTENT_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
}

LOGO_MAX_BYTES = 2 * 1024 * 1024


def logo_dir() -> str:
    return os.path.join(_upload_root(), "platform")


def logo_fs_path(descripteur: object) -> str:
    """Chemin disque du logo, ou chaîne vide s'il n'y en a pas d'exploitable."""
    if not isinstance(descripteur, dict):
        return ""
    nom = str(descripteur.get("stored_name") or "").strip()
    # `basename` : le descripteur vient du JSONB, on ne le laisse pas désigner
    # un fichier hors du répertoire prévu.
    nom = os.path.basename(nom)
    if not nom:
        return ""
    return os.path.join(logo_dir(), nom)


async def get_logo(db: AsyncSession) -> dict | None:
    row = await _platform_settings(db)
    config = row.billing_config if isinstance(row.billing_config, dict) else {}
    descripteur = config.get("logo")
    if not isinstance(descripteur, dict):
        return None
    chemin = logo_fs_path(descripteur)
    if not chemin or not os.path.exists(chemin):
        return None
    if "accent" not in descripteur:
        # Logo déposé avant que la facture prenne les couleurs de la marque :
        # on la calcule à la première relecture, plutôt que de demander un
        # nouveau dépôt. Une couleur vide reste une réponse : elle sera là.
        detectee = couleur_dominante(chemin)
        descripteur = {**descripteur, "accent_detecte": detectee, "accent": detectee}
        config = dict(config)
        config["logo"] = descripteur
        row.billing_config = config
        row.updated_at = _utcnow()
    return descripteur


async def save_logo(db: AsyncSession, *, contenu: bytes, filename: str, content_type: str) -> dict:
    extension = LOGO_CONTENT_TYPES.get((content_type or "").lower())
    if extension is None:
        raise ValueError("Format de logo non pris en charge : PNG ou JPEG attendus.")
    if len(contenu) > LOGO_MAX_BYTES:
        raise ValueError("Logo trop volumineux : 2 Mo au maximum.")
    if not contenu:
        raise ValueError("Fichier vide.")

    dossier = logo_dir()
    os.makedirs(dossier, exist_ok=True)
    stored_name = f"logo-{uuid.uuid4().hex}{extension}"
    with open(os.path.join(dossier, stored_name), "wb") as fichier:
        fichier.write(contenu)

    row = await _platform_settings(db)
    config = dict(row.billing_config) if isinstance(row.billing_config, dict) else {}
    ancien = config.get("logo")

    # La couleur de marque se calcule une fois, au dépôt : la facture la relit
    # ensuite sans rouvrir l'image. `accent` est la couleur effectivement
    # employée, `accent_detecte` celle du logo — les distinguer permet de
    # revenir à la teinte d'origine après un réglage à la main.
    detectee = couleur_dominante(os.path.join(dossier, stored_name))

    descripteur = {
        "stored_name": stored_name,
        "filename": os.path.basename(filename or stored_name)[:255],
        "content_type": (content_type or "").lower(),
        "size": len(contenu),
        "uploaded_at": _utcnow().isoformat(),
        "accent_detecte": detectee,
        "accent": detectee,
    }
    config["logo"] = descripteur
    row.billing_config = config
    row.updated_at = _utcnow()

    _supprimer_fichier_logo(ancien)
    return descripteur


async def set_logo_accent(db: AsyncSession, accent: object) -> dict | None:
    """Impose une couleur de marque, ou rétablit celle du logo.

    L'extraction se trompe parfois : un liseré rouge sur un logo bleu suffit à
    l'emporter en surface. Plutôt que d'affiner indéfiniment l'algorithme, on
    laisse la main — et une valeur vide revient à ce que le logo dit.
    """
    row = await _platform_settings(db)
    config = dict(row.billing_config) if isinstance(row.billing_config, dict) else {}
    descripteur = config.get("logo")
    if not isinstance(descripteur, dict):
        raise ValueError("Aucun logo enregistré : la couleur suit le logo.")

    demande = str(accent or "").strip()
    if demande:
        rgb = _hex_vers_rgb(demande)
        if rgb is None:
            raise ValueError("Couleur attendue au format hexadécimal, par exemple #0F766E.")
        retenue = _rgb_vers_hex(rgb)
    else:
        retenue = str(descripteur.get("accent_detecte") or "")

    descripteur = {**descripteur, "accent": retenue}
    config["logo"] = descripteur
    row.billing_config = config
    row.updated_at = _utcnow()
    return descripteur


async def delete_logo(db: AsyncSession) -> None:
    row = await _platform_settings(db)
    config = dict(row.billing_config) if isinstance(row.billing_config, dict) else {}
    ancien = config.pop("logo", None)
    row.billing_config = config
    row.updated_at = _utcnow()
    _supprimer_fichier_logo(ancien)


def _supprimer_fichier_logo(descripteur: object) -> None:
    """Le remplacement ne doit pas laisser s'accumuler les anciens fichiers.
    Un échec de suppression ne compromet rien : on garde le nouveau logo."""
    chemin = logo_fs_path(descripteur)
    if not chemin:
        return
    try:
        os.remove(chemin)
    except OSError:
        pass


# ── Grille tarifaire : le catalogue des plans ────────────────────────────────
#
# `Organisation.plan_type` portait une chaîne libre sans rien derrière : deux
# organisations sur le même plan pouvaient s'écrire différemment, et le prix
# facturé n'avait aucun lien avec le plan affiché. Le catalogue vit ici, à
# côté de l'identité éditeur, dans le même JSONB `billing_config`.

PLAN_INTERVALS = ("monthly", "quarterly", "semiannual", "yearly")

PLAN_INTERVAL_LABELS = {
    "monthly": "mensuel",
    "quarterly": "trimestriel",
    "semiannual": "semestriel",
    "yearly": "annuel",
}
PLAN_CURRENCIES = ("USD", "CDF")

PLAN_DEFAULTS: dict[str, object] = {
    "code": "",
    "name": "",
    "description": "",
    "price": "0.00",
    "currency": "USD",
    "interval": "monthly",
    "active": True,
}


def normalise_plan_code(value: object) -> str:
    """Un code de plan sert de clé : majuscules, sans espace ni ponctuation."""
    brut = str(value or "").strip().upper()
    garde = [c if (c.isalnum() or c in "_-") else "_" for c in brut]
    return "".join(garde).strip("_")[:50]


def merge_plan(raw: object) -> dict | None:
    """Complète un plan partiel. Renvoie None si le code est inexploitable."""
    stored = raw if isinstance(raw, dict) else {}
    code = normalise_plan_code(stored.get("code"))
    if not code:
        return None

    plan = dict(PLAN_DEFAULTS)
    plan["code"] = code
    plan["name"] = str(stored.get("name") or "").strip() or code
    plan["description"] = str(stored.get("description") or "").strip()

    devise = str(stored.get("currency") or "").strip().upper()
    plan["currency"] = devise if devise in PLAN_CURRENCIES else str(PLAN_DEFAULTS["currency"])

    periodicite = str(stored.get("interval") or "").strip().lower()
    plan["interval"] = periodicite if periodicite in PLAN_INTERVALS else str(PLAN_DEFAULTS["interval"])

    # Le prix transite en texte : un flottant JSON perdrait des centimes sur
    # les montants qui ne tombent pas juste en binaire.
    try:
        montant = to_decimal(stored.get("price", "0"), "price")
    except ValueError:
        montant = Decimal("0.00")
    plan["price"] = f"{max(montant, Decimal('0.00')):.2f}"

    plan["active"] = bool(stored.get("active", True))
    return plan


def merge_plans(raw: object) -> list[dict]:
    """Catalogue nettoyé : codes uniques, dernier arrivé gagnant."""
    if not isinstance(raw, list):
        return []
    par_code: dict[str, dict] = {}
    for element in raw:
        plan = merge_plan(element)
        if plan is not None:
            par_code[str(plan["code"])] = plan
    return sorted(par_code.values(), key=lambda p: str(p["name"]).lower())


async def get_plans(db: AsyncSession) -> list[dict]:
    row = await _platform_settings(db)
    config = row.billing_config if isinstance(row.billing_config, dict) else {}
    return merge_plans(config.get("plans"))


async def save_plans(db: AsyncSession, payload: object) -> list[dict]:
    row = await _platform_settings(db)
    config = dict(row.billing_config) if isinstance(row.billing_config, dict) else {}
    plans = merge_plans(payload)
    config["plans"] = plans
    # Réaffectation complète : SQLAlchemy ne détecte pas la mutation en place
    # d'un JSONB.
    row.billing_config = config
    row.updated_at = _utcnow()
    return plans


async def get_plan(db: AsyncSession, code: object) -> dict | None:
    """Le plan d'un code donné, actif ou non — une organisation déjà rattachée
    à un plan retiré du catalogue doit continuer d'être facturée."""
    recherche = normalise_plan_code(code)
    if not recherche:
        return None
    for plan in await get_plans(db):
        if plan["code"] == recherche:
            return plan
    return None


# ── Numérotation ─────────────────────────────────────────────────────────────


async def next_invoice_number(db: AsyncSession, *, prefix: str, issued_at: datetime) -> str:
    """Numéro séquentiel `PREFIX-AAAA-0001`, continu sur l'année civile.

    Une numérotation à trous se défend mal devant un contrôle : on repart donc
    du plus grand rang déjà attribué pour l'année, et non d'un compte de lignes
    (qui reculerait si une facture était supprimée).
    """
    year = issued_at.astimezone(timezone.utc).year
    stem = f"{prefix}-{year}-"
    res = await db.execute(
        select(func.max(SaaSInvoice.invoice_number)).where(SaaSInvoice.invoice_number.like(f"{stem}%"))
    )
    highest = res.scalar_one_or_none()
    rank = 0
    if highest:
        tail = str(highest)[len(stem):]
        if tail.isdigit():
            rank = int(tail)
    return f"{stem}{rank + 1:04d}"


# ── Lignes de facture ────────────────────────────────────────────────────────


def normalize_line_items(raw: object) -> tuple[list[dict], Decimal]:
    """Valide les lignes saisies et renvoie (lignes normalisées, total)."""
    if not isinstance(raw, list) or not raw:
        raise ValueError("Au moins une ligne de facturation est requise.")

    lines: list[dict] = []
    total = Decimal("0.00")
    for index, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"Ligne {index} : format invalide.")
        designation = str(entry.get("designation") or "").strip()
        if not designation:
            raise ValueError(f"Ligne {index} : la désignation est obligatoire.")
        quantity = to_decimal(entry.get("quantite", 1) or 0, f"quantité (ligne {index})")
        unit_price = to_decimal(entry.get("prix_unitaire", 0) or 0, f"prix unitaire (ligne {index})")
        if quantity <= 0:
            raise ValueError(f"Ligne {index} : la quantité doit être strictement positive.")
        if unit_price < 0:
            raise ValueError(f"Ligne {index} : le prix unitaire ne peut pas être négatif.")
        amount = (quantity * unit_price).quantize(Decimal("0.01"))
        lines.append(
            {
                "designation": designation,
                "quantite": float(quantity),
                "prix_unitaire": float(unit_price),
                "montant": float(amount),
            }
        )
        total += amount

    if total <= 0:
        raise ValueError("Le total de la facture doit être strictement positif.")
    return lines, total.quantize(Decimal("0.01"))


def default_due_date(issued_at: datetime, issuer: dict) -> datetime:
    try:
        days = int(issuer.get("payment_terms_days") or 0)
    except (TypeError, ValueError):
        days = 0
    return issued_at + timedelta(days=max(0, days))


# ── PDF ──────────────────────────────────────────────────────────────────────


def _issuer_lines(issuer: dict) -> list[str]:
    rows = [issuer.get("address"), issuer.get("city"), issuer.get("country")]
    contact = " · ".join(x for x in (issuer.get("phone"), issuer.get("email")) if x)
    rows.append(contact)
    rows.append(issuer.get("website"))
    legal = " · ".join(
        f"{label} {issuer.get(key)}"
        for key, label in (("rccm", "RCCM"), ("id_nat", "Id. Nat."), ("tax_id", "NIF"))
        if issuer.get(key)
    )
    rows.append(legal)
    return [str(row).strip() for row in rows if str(row or "").strip()]


def _payment_lines(issuer: dict) -> list[str]:
    rows: list[str] = []
    if issuer.get("bank_name") or issuer.get("bank_account"):
        bank = " — ".join(x for x in (issuer.get("bank_name"), issuer.get("bank_account")) if x)
        rows.append(f"Virement : {bank}")
        if issuer.get("bank_swift"):
            rows.append(f"SWIFT/BIC : {issuer['bank_swift']}")
    if issuer.get("mobile_money"):
        rows.append(f"Mobile money : {issuer['mobile_money']}")
    return rows


def _fit(c: canvas.Canvas, text: str, max_width: float, font: str, size: float) -> str:
    """Tronque une chaine pour qu'elle tienne dans la largeur donnee.

    Les coordonnees bancaires sont saisies librement : sans garde-fou, un IBAN
    verbeux depasse la marge droite et se fait rogner par le lecteur PDF.
    """
    if c.stringWidth(text, font, size) <= max_width:
        return text
    trimmed = text
    while trimmed and c.stringWidth(trimmed + "..", font, size) > max_width:
        trimmed = trimmed[:-1]
    return (trimmed + "..") if trimmed else ""


def _dessiner_logo(c: canvas.Canvas, logo_path: str, x: float, sommet: float) -> float:
    """Trace le logo et renvoie la largeur qu'il occupe (0 s'il n'y en a pas).

    Le fichier peut avoir disparu du disque entre deux rendus : une facture ne
    doit pas échouer pour un logo manquant, on se contente de l'omettre.
    """
    if not logo_path or not os.path.exists(logo_path):
        return 0.0
    try:
        image = ImageReader(logo_path)
        largeur_px, hauteur_px = image.getSize()
        if largeur_px <= 0 or hauteur_px <= 0:
            return 0.0
        hauteur = 1.4 * cm
        largeur = hauteur * (largeur_px / hauteur_px)
        largeur_max = 4.2 * cm
        if largeur > largeur_max:
            largeur = largeur_max
            hauteur = largeur * (hauteur_px / largeur_px)
        c.drawImage(
            image,
            x,
            sommet - hauteur,
            width=largeur,
            height=hauteur,
            mask="auto",
            preserveAspectRatio=True,
            anchor="sw",
        )
        return largeur
    except Exception:  # noqa: BLE001 - un logo illisible ne bloque pas la facture
        logger.exception("Logo de l'éditeur illisible : %s", logo_path)
        return 0.0


def _draw_header(
    c: canvas.Canvas,
    width: float,
    height: float,
    issuer: dict,
    invoice: SaaSInvoice,
    logo_path: str = "",
    p: Palette = PALETTE_DEFAUT,
) -> float:
    # Le bandeau de tête est un aplat : il porte la teinte du logo telle
    # quelle, là où les textes prennent la version assombrie.
    c.setFillColor(p.marque)
    c.rect(0, height - 0.5 * cm, width, 0.5 * cm, stroke=0, fill=1)

    y = height - 2.2 * cm

    # Le logo occupe la marge gauche ; le bloc de texte se décale d'autant,
    # de façon qu'un logo large ne vienne pas sous la raison sociale.
    largeur_logo = _dessiner_logo(c, logo_path, 2 * cm, y + 0.45 * cm)
    texte_x = 2 * cm + (largeur_logo + 0.45 * cm if largeur_logo else 0.0)

    c.setFillColor(p.encre)
    c.setFont("Helvetica-Bold", 17)
    c.drawString(texte_x, y, str(issuer.get("name") or ISSUER_DEFAULTS["name"]))

    if issuer.get("tagline"):
        c.setFont("Helvetica-Oblique", 9)
        c.setFillColor(p.gris)
        c.drawString(texte_x, y - 0.5 * cm, str(issuer["tagline"]))

    c.setFillColor(p.gris)
    c.setFont("Helvetica", 8.5)
    line_y = y - 1.05 * cm
    for row in _issuer_lines(issuer):
        c.drawString(texte_x, line_y, row)
        line_y -= 0.36 * cm

    c.setFillColor(p.encre)
    c.setFont("Helvetica-Bold", 20)
    c.drawRightString(width - 2 * cm, y, "FACTURE")
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(p.accent)
    c.drawRightString(width - 2 * cm, y - 0.65 * cm, invoice.invoice_number)

    status_label = {
        "DRAFT": "BROUILLON",
        "ISSUED": "EN ATTENTE DE PAIEMENT",
        "PAID": "PAYÉE",
        "CANCELLED": "ANNULÉE",
    }.get(invoice.status, invoice.status)
    c.setFillColor(p.gris if invoice.status != "PAID" else p.accent)
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(width - 2 * cm, y - 1.15 * cm, status_label)

    return min(line_y, y - 1.8 * cm) - 0.5 * cm


def _draw_parties(
    c: canvas.Canvas,
    width: float,
    y: float,
    org: Organisation,
    invoice: SaaSInvoice,
    p: Palette = PALETTE_DEFAUT,
) -> float:
    c.setFillColor(p.bandeau)
    c.rect(2 * cm, y - 2.5 * cm, width - 4 * cm, 2.5 * cm, stroke=0, fill=1)

    c.setFillColor(p.gris)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(2.4 * cm, y - 0.6 * cm, "FACTURÉ À")
    c.drawString(width / 2, y - 0.6 * cm, "DÉTAILS")

    c.setFillColor(p.encre)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(2.4 * cm, y - 1.15 * cm, org.nom)
    c.setFont("Helvetica", 9)
    c.setFillColor(p.gris)
    c.drawString(2.4 * cm, y - 1.6 * cm, f"Tenant : {org.slug}")
    if org.email_contact:
        c.drawString(2.4 * cm, y - 2.0 * cm, str(org.email_contact))

    c.setFillColor(p.encre)
    c.setFont("Helvetica", 9)
    meta = [
        ("Date d'émission", _fmt_date(invoice.issue_date)),
        ("Échéance", _fmt_date(invoice.due_date)),
        (
            "Période",
            # « → » n'appartient pas a WinAnsiEncoding, la police Helvetica de
            # reportlab le rendrait en « ® ». On reste sur des caracteres surs.
            f"{_fmt_date(invoice.period_start)} au {_fmt_date(invoice.period_end)}"
            if invoice.period_start or invoice.period_end
            else "—",
        ),
    ]
    meta_y = y - 1.15 * cm
    for label, value in meta:
        c.setFillColor(p.gris)
        c.drawString(width / 2, meta_y, f"{label} :")
        c.setFillColor(p.encre)
        c.drawRightString(width - 2.4 * cm, meta_y, value)
        meta_y -= 0.45 * cm

    return y - 3.2 * cm


def _draw_items(
    c: canvas.Canvas,
    width: float,
    y: float,
    invoice: SaaSInvoice,
    fallback: str,
    p: Palette = PALETTE_DEFAUT,
) -> float:
    c.setFillColor(p.encre)
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(2 * cm, y, "DÉSIGNATION")
    c.drawRightString(width - 8.2 * cm, y, "QTÉ")
    c.drawRightString(width - 5.2 * cm, y, "P.U.")
    c.drawRightString(width - 2 * cm, y, "MONTANT")
    y -= 0.25 * cm
    c.setStrokeColor(p.accent)
    c.setLineWidth(1.1)
    c.line(2 * cm, y, width - 2 * cm, y)
    y -= 0.65 * cm

    currency = invoice.currency
    rows = invoice.line_items if isinstance(invoice.line_items, list) and invoice.line_items else None
    if rows is None:
        # Factures nées d'un paiement en ligne : pas de détail saisi, on restitue
        # le libellé d'abonnement plutôt qu'un tableau vide.
        rows = [
            {
                "designation": fallback,
                "quantite": 1,
                "prix_unitaire": float(invoice.amount),
                "montant": float(invoice.amount),
            }
        ]

    c.setFont("Helvetica", 9.5)
    for row in rows:
        designation = str(row.get("designation") or "")
        # Le tableau ne gère pas le retour à la ligne : on tronque plutôt que de
        # laisser le texte chevaucher la colonne des quantités.
        if len(designation) > 58:
            designation = designation[:57] + ".."
        c.setFillColor(p.encre)
        c.drawString(2 * cm, y, designation)
        c.setFillColor(p.gris)
        c.drawRightString(width - 8.2 * cm, y, f"{float(row.get('quantite') or 0):g}")
        c.drawRightString(width - 5.2 * cm, y, _fmt_money(row.get("prix_unitaire") or 0, currency))
        c.setFillColor(p.encre)
        c.drawRightString(width - 2 * cm, y, _fmt_money(row.get("montant") or 0, currency))
        y -= 0.55 * cm
        c.setStrokeColor(p.ligne)
        c.setLineWidth(0.4)
        c.line(2 * cm, y + 0.18 * cm, width - 2 * cm, y + 0.18 * cm)

    y -= 0.4 * cm
    c.setFillColor(p.bandeau)
    c.rect(width - 8.6 * cm, y - 0.9 * cm, 6.6 * cm, 0.9 * cm, stroke=0, fill=1)
    c.setFillColor(p.encre)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(width - 8.3 * cm, y - 0.6 * cm, "TOTAL")
    c.drawRightString(width - 2.2 * cm, y - 0.6 * cm, _fmt_money(invoice.amount, currency))
    return y - 1.8 * cm


def _draw_settlement(
    c: canvas.Canvas,
    width: float,
    y: float,
    invoice: SaaSInvoice,
    issuer: dict,
    p: Palette = PALETTE_DEFAUT,
) -> float:
    if invoice.status == "PAID":
        c.setFillColor(p.accent)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(2 * cm, y, "Facture acquittée")
        c.setFillColor(p.gris)
        c.setFont("Helvetica", 9)
        details = [f"Réglée le {_fmt_date(invoice.paid_at)}"]
        if invoice.payment_method:
            details.append(PAYMENT_METHODS.get(invoice.payment_method, invoice.payment_method))
        if invoice.payment_reference:
            details.append(f"Réf. {invoice.payment_reference}")
        c.drawString(2 * cm, y - 0.45 * cm, " · ".join(details))
        return y - 1.3 * cm

    if invoice.status == "CANCELLED":
        c.setFillColor(p.gris)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(2 * cm, y, "Facture annulée")
        if invoice.cancel_reason:
            c.setFont("Helvetica", 9)
            c.drawString(2 * cm, y - 0.45 * cm, str(invoice.cancel_reason)[:110])
        return y - 1.3 * cm

    online = bool(issuer.get("online_payment_enabled", True))
    manual = bool(issuer.get("manual_payment_enabled", True))
    if not online and not manual:
        # Aucune voie annoncee : la facture reste muette sur le reglement, ce
        # qui se defend quand les modalites vivent dans un contrat signe.
        return y

    c.setFillColor(p.encre)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(2 * cm, y, "Modalités de règlement")

    online_rows = [
        "Espace Facturation du compte,",
        "rubrique « Régler ma facture ».",
        "Règlement constaté immédiatement.",
    ]
    manual_rows = (_payment_lines(issuer) or [
        "Coordonnées de règlement communiquées",
        "par l'éditeur sur simple demande.",
    ]) + [
        "Transmettez la preuve de paiement :",
        "la facture est soldée après contrôle.",
    ]

    columns: list[tuple[str, list[str]]] = []
    if online:
        columns.append(("En ligne", online_rows))
    if manual:
        columns.append(("Paiement manuel", manual_rows))

    head_y = y - 0.5 * cm
    if len(columns) == 2:
        # Les deux voies coexistent : on les numerote pour dire au client qu'il
        # choisit, plutot que de laisser croire a une sequence obligatoire.
        c.setFont("Helvetica-Oblique", 8.5)
        c.setFillColor(p.gris)
        c.drawString(2 * cm, head_y, "Deux options, au choix du client.")
        head_y -= 0.55 * cm
        positions = [2 * cm, width / 2 + 0.4 * cm]
        titles = ["1. En ligne", "2. Paiement manuel"]
    else:
        positions = [2 * cm]
        titles = [columns[0][0]]

    lowest = head_y
    for index, (position, title) in enumerate(zip(positions, titles)):
        c.setFillColor(p.accent)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(position, head_y, title)

        available = (width - 2 * cm) - position
        c.setFillColor(p.gris)
        c.setFont("Helvetica", 8.5)
        line_y = head_y - 0.42 * cm
        for row in columns[index][1][:5]:
            c.drawString(position, line_y, _fit(c, row, available, "Helvetica", 8.5))
            line_y -= 0.36 * cm
        lowest = min(lowest, line_y)

    return lowest - 0.6 * cm


def render_invoice_pdf(
    *,
    invoice: SaaSInvoice,
    org: Organisation,
    issuer: dict,
    fallback_designation: str,
    logo_path: str = "",
    palette: Palette | None = None,
) -> str:
    """Trace le PDF sur disque et renvoie son chemin. Synchrone : à confier à un thread."""
    target_dir = os.path.join(_upload_root(), "saas-invoices", str(org.id))
    os.makedirs(target_dir, exist_ok=True)
    path = os.path.join(target_dir, f"{invoice.invoice_number}.pdf")

    c = canvas.Canvas(path, pagesize=A4)
    width, height = A4
    p = palette or PALETTE_DEFAUT

    y = _draw_header(c, width, height, issuer, invoice, logo_path, p)
    y = _draw_parties(c, width, y, org, invoice, p)
    y = _draw_items(c, width, y, invoice, fallback_designation, p)
    y = _draw_settlement(c, width, y, invoice, issuer, p)

    if invoice.notes:
        c.setFillColor(p.encre)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(2 * cm, y, "Note")
        c.setFillColor(p.gris)
        c.setFont("Helvetica", 9)
        c.drawString(2 * cm, y - 0.42 * cm, str(invoice.notes)[:120])

    c.setStrokeColor(p.ligne)
    c.setLineWidth(0.5)
    c.line(2 * cm, 1.9 * cm, width - 2 * cm, 1.9 * cm)
    c.setFillColor(p.gris)
    c.setFont("Helvetica", 7.5)
    footer = str(issuer.get("footer_note") or "").strip()
    c.drawString(2 * cm, 1.45 * cm, footer or f"{issuer.get('name')} — facture émise par la plateforme.")
    c.drawRightString(width - 2 * cm, 1.45 * cm, f"{invoice.invoice_number} · page 1/1")

    c.showPage()
    c.save()
    return path


async def refresh_invoice_pdf(
    db: AsyncSession,
    invoice: SaaSInvoice,
    *,
    org: Organisation | None = None,
    fallback_designation: str = "Abonnement SaaS",
) -> str:
    """(Re)génère le PDF d'une facture après un changement d'état."""
    if org is None:
        res = await db.execute(select(Organisation).where(Organisation.id == invoice.organisation_id))
        org = res.scalar_one_or_none()
    if org is None:
        raise ValueError("Organisation introuvable pour cette facture.")

    issuer = merge_issuer(invoice.issuer_snapshot) if invoice.issuer_snapshot else await get_issuer(db)
    # Le logo n'entre pas dans l'instantané figé sur la facture : c'est une
    # marque, pas une mention légale. Un rendu ultérieur reprend donc le logo
    # courant, comme le ferait un papier à en-tête réimprimé.
    descripteur = await get_logo(db)
    logo_path = logo_fs_path(descripteur)
    palette = palette_facture((descripteur or {}).get("accent"))
    path = await anyio.to_thread.run_sync(
        lambda: render_invoice_pdf(
            invoice=invoice,
            org=org,
            issuer=issuer,
            fallback_designation=fallback_designation,
            logo_path=logo_path,
            palette=palette,
        )
    )
    invoice.pdf_path = path
    invoice.updated_at = _utcnow()
    return path


# ── Création ─────────────────────────────────────────────────────────────────


async def create_issued_invoice(
    db: AsyncSession,
    *,
    org: Organisation,
    line_items: list[dict],
    total: Decimal,
    currency: str,
    period_start: datetime | None,
    period_end: datetime | None,
    due_date: datetime | None,
    notes: str | None,
    status: str,
    subscription_id: uuid.UUID | None = None,
) -> SaaSInvoice:
    if status not in ("DRAFT", "ISSUED"):
        raise ValueError("Une facture se crée en brouillon ou émise.")

    issuer = await get_issuer(db)
    now = _utcnow()
    prefix = str(issuer.get("invoice_prefix") or ISSUER_DEFAULTS["invoice_prefix"])

    invoice = SaaSInvoice(
        invoice_number=await next_invoice_number(db, prefix=prefix, issued_at=now),
        organisation_id=org.id,
        subscription_id=subscription_id,
        status=status,
        amount=total,
        currency=currency,
        issue_date=now,
        due_date=due_date or default_due_date(now, issuer),
        period_start=period_start,
        period_end=period_end,
        line_items=line_items,
        issuer_snapshot=issuer,
        notes=notes,
        metadata_json={"origin": "console", "created_at": now.isoformat()},
    )
    db.add(invoice)
    await db.flush()

    await refresh_invoice_pdf(db, invoice, org=org)
    return invoice


async def mark_invoice_paid(
    db: AsyncSession,
    invoice: SaaSInvoice,
    *,
    method: str,
    reference: str | None,
    paid_at: datetime | None,
    recorded_by: uuid.UUID | None,
    org: Organisation | None = None,
) -> SaaSInvoice:
    if invoice.status == "PAID":
        raise ValueError("Cette facture est déjà réglée.")
    if invoice.status == "CANCELLED":
        raise ValueError("Une facture annulée ne peut pas être réglée.")
    if method not in PAYMENT_METHODS:
        raise ValueError(f"Moyen de paiement inconnu : {method}")

    invoice.status = "PAID"
    invoice.payment_method = method
    invoice.payment_reference = (reference or "").strip() or None
    invoice.paid_at = paid_at or _utcnow()
    invoice.paid_by_user_id = recorded_by
    invoice.updated_at = _utcnow()

    await refresh_invoice_pdf(db, invoice, org=org)
    return invoice


async def cancel_invoice(db: AsyncSession, invoice: SaaSInvoice, *, reason: str | None) -> SaaSInvoice:
    if invoice.status == "PAID":
        raise ValueError("Une facture réglée ne s'annule pas : émettez un avoir.")
    if invoice.status == "CANCELLED":
        raise ValueError("Cette facture est déjà annulée.")

    invoice.status = "CANCELLED"
    invoice.cancelled_at = _utcnow()
    invoice.cancel_reason = (reason or "").strip() or None
    invoice.updated_at = _utcnow()

    await refresh_invoice_pdf(db, invoice)
    return invoice


async def find_open_invoice(db: AsyncSession, *, organisation_id: int) -> SaaSInvoice | None:
    """Facture ouverte la plus ancienne d'un tenant — celle qu'un paiement solde."""
    res = await db.execute(
        select(SaaSInvoice)
        .where(
            SaaSInvoice.organisation_id == organisation_id,
            SaaSInvoice.status.in_(OPEN_STATUSES),
        )
        .order_by(SaaSInvoice.issue_date.asc())
        .limit(1)
    )
    return res.scalars().first()
