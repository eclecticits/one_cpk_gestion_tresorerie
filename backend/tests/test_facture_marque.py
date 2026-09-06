"""La facture SaaS porte le logo de l'éditeur et prend ses couleurs.

Le document sortait avec un vert fixe, quelle que soit la marque imprimée
juste au-dessus. Ces tests fixent les deux règles qui rendent le rendu
prévisible : d'où vient la couleur, et ce qu'on en fait quand elle serait
illisible sur du papier blanc.
"""

import base64
import re
import uuid
import zlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from PIL import Image

from app.models.organisation import Organisation
from app.models.saas_invoice import SaaSInvoice
from app.services import saas_invoicing


def _png(chemin, couleur, *, fond=(255, 255, 255, 255), taille=(64, 64)):
    """Un logo : un fond, et un carré de couleur en son centre."""
    image = Image.new("RGBA", taille, fond)
    largeur, hauteur = taille
    for x in range(largeur // 4, 3 * largeur // 4):
        for y in range(hauteur // 4, 3 * hauteur // 4):
            image.putpixel((x, y), couleur)
    image.save(chemin)
    return str(chemin)


# ── Couleur de marque ────────────────────────────────────────────────────────


def test_couleur_dominante_ignore_le_fond_blanc(tmp_path):
    chemin = _png(tmp_path / "logo.png", (192, 24, 91, 255))
    assert saas_invoicing.couleur_dominante(chemin) == "#C0185B"


def test_couleur_dominante_ignore_le_fond_transparent(tmp_path):
    """Un PNG détouré : le fond ne doit pas peser dans le vote."""
    chemin = _png(tmp_path / "logo.png", (16, 90, 200, 255), fond=(0, 0, 0, 0))
    assert saas_invoicing.couleur_dominante(chemin) == "#105AC8"


def test_logo_gris_ne_donne_aucune_couleur(tmp_path):
    """Un logo noir et blanc n'a pas de couleur de marque : mieux vaut le dire
    que d'élire un gris au hasard."""
    chemin = _png(tmp_path / "logo.png", (34, 34, 34, 255))
    assert saas_invoicing.couleur_dominante(chemin) == ""


def test_fichier_illisible_ne_leve_pas(tmp_path):
    chemin = tmp_path / "logo.png"
    chemin.write_bytes(b"ceci n'est pas une image")
    assert saas_invoicing.couleur_dominante(str(chemin)) == ""
    assert saas_invoicing.couleur_dominante(str(tmp_path / "absent.png")) == ""


# ── Palette ──────────────────────────────────────────────────────────────────


def test_la_teinte_de_marque_reste_intacte_sur_les_aplats():
    palette = saas_invoicing.palette_facture("#FFC400")
    assert palette.marque.hexval()[2:] == "ffc400"


def test_une_teinte_claire_est_assombrie_pour_le_texte():
    """Un jaune de marque écrit en toutes lettres passerait pour une
    impression ratée : le texte prend une version contrastée."""
    palette = saas_invoicing.palette_facture("#FFC400")
    rgb = (
        round(palette.accent.red * 255),
        round(palette.accent.green * 255),
        round(palette.accent.blue * 255),
    )
    assert saas_invoicing._contraste_sur_blanc(rgb) >= 4.5
    # Assombrie, pas remplacée : le jaune reste un jaune.
    assert rgb[0] > rgb[2] and rgb[1] > rgb[2]


def test_une_teinte_deja_sombre_n_est_pas_touchee():
    palette = saas_invoicing.palette_facture("#0F766E")
    assert palette.accent.hexval()[2:] == "0f766e"


def test_les_aplats_sont_des_teintes_pales():
    """Filets et bandeaux ne doivent pas crier plus fort que les montants."""
    palette = saas_invoicing.palette_facture("#C0185B")
    for couleur in (palette.ligne, palette.bandeau):
        rgb = (couleur.red * 255, couleur.green * 255, couleur.blue * 255)
        assert saas_invoicing._contraste_sur_blanc(rgb) < 1.6


def test_sans_couleur_la_palette_reste_celle_de_la_plateforme():
    for valeur in (None, "", "pas une couleur", "#GGGGGG"):
        palette = saas_invoicing.palette_facture(valeur)
        assert palette.marque.hexval()[2:] == saas_invoicing.MARQUE_DEFAUT[1:].lower()


# ── Rendu du PDF ─────────────────────────────────────────────────────────────


def _facture(**extra) -> SaaSInvoice:
    maintenant = datetime.now(timezone.utc)
    facture = SaaSInvoice(
        id=uuid.uuid4(),
        invoice_number="FA-TEST-0001",
        organisation_id=1,
        status="ISSUED",
        amount=Decimal("250.50"),
        currency="USD",
        issue_date=maintenant,
        due_date=maintenant + timedelta(days=30),
        line_items=[
            {
                "designation": "Abonnement Socle (annuel)",
                "quantite": 1,
                "prix_unitaire": 250.50,
                "montant": 250.50,
            }
        ],
    )
    for champ, valeur in extra.items():
        setattr(facture, champ, valeur)
    return facture


def _organisation() -> Organisation:
    return Organisation(
        id=1,
        uuid=uuid.uuid4(),
        nom="Conseil provincial",
        slug="conseil-provincial",
        plan_type="SOCLE",
        status_abonnement="ACTIVE",
    )


def _rendre(tmp_path, monkeypatch, **kwargs) -> bytes:
    monkeypatch.setattr(saas_invoicing, "_upload_root", lambda: str(tmp_path))
    chemin = saas_invoicing.render_invoice_pdf(
        invoice=_facture(),
        org=_organisation(),
        issuer=saas_invoicing.merge_issuer({}),
        fallback_designation="Abonnement SaaS",
        **kwargs,
    )
    with open(chemin, "rb") as fichier:
        return fichier.read()


def _aplats(pdf: bytes) -> set[tuple[int, int, int]]:
    """Les couleurs de remplissage posées sur la page.

    Le flux de contenu est compressé puis encodé en ASCII85 par reportlab : on
    le rouvre plutôt que de chercher la couleur dans des octets illisibles.
    Chaque aplat s'y écrit « .752941 .094118 .356863 rg ».
    """
    clair = []
    for flux in re.findall(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        brut = flux.strip(b"\r\n")
        for decodeur in (
            lambda b: zlib.decompress(base64.a85decode(b, adobe=True)),
            zlib.decompress,
            lambda b: b,
        ):
            try:
                clair.append(decodeur(brut))
                break
            except Exception:  # noqa: BLE001 - flux binaire (image), on passe
                continue

    couleurs = set()
    for trouve in re.finditer(rb"([\d.]+) ([\d.]+) ([\d.]+) rg", b"\n".join(clair)):
        couleurs.add(tuple(round(float(canal.decode()) * 255) for canal in trouve.groups()))
    return couleurs


def test_le_logo_est_embarque_dans_le_pdf(tmp_path, monkeypatch):
    sans_logo = _rendre(tmp_path, monkeypatch)
    assert b"/Subtype /Image" not in sans_logo

    logo = _png(tmp_path / "logo.png", (192, 24, 91, 255))
    avec_logo = _rendre(tmp_path, monkeypatch, logo_path=logo)
    assert b"/Subtype /Image" in avec_logo


def test_un_logo_disparu_du_disque_ne_casse_pas_la_facture(tmp_path, monkeypatch):
    """Le descripteur peut survivre au fichier : la facture doit sortir quand
    même, sans logo, plutôt que d'échouer à l'émission."""
    pdf = _rendre(tmp_path, monkeypatch, logo_path=str(tmp_path / "envole.png"))
    assert pdf.startswith(b"%PDF")
    assert b"/Subtype /Image" not in pdf


def test_la_couleur_de_marque_atteint_le_document(tmp_path, monkeypatch):
    """Deux palettes, deux documents : la couleur n'est pas décorative dans le
    code, elle descend jusqu'à l'encre posée sur la page."""
    defaut = _rendre(tmp_path, monkeypatch)
    marque = _rendre(
        tmp_path, monkeypatch, palette=saas_invoicing.palette_facture("#C0185B")
    )
    assert defaut != marque

    # Le bandeau de tête est un aplat de la teinte demandée, telle quelle.
    assert (192, 24, 91) in _aplats(marque)
    assert (192, 24, 91) not in _aplats(defaut)
