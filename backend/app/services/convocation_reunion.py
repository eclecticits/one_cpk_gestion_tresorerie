"""Convocation des participants d'une réunion en préparation.

La réunion vit, avant sa tenue, dans un brouillon de remboursement de
transport : c'est lui qui porte la date, le lieu, les travaux (l'ordre du jour)
et la liste des personnes attendues. La convocation part de là, par e-mail,
avec un fichier .ics pour que chacun l'ajoute à son agenda.

Un message par destinataire : les adresses des uns ne sont pas montrées aux
autres, et un refus du serveur pour une adresse n'empêche pas les suivantes.
"""

from __future__ import annotations

import html
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from app.services.email_config import SMTPConfig
from app.services.mailer import _send_email_message

logger = logging.getLogger(__name__)

# Les heures saisies sont celles de Kinshasa ; l'invitation les porte avec leur
# fuseau pour qu'un agenda réglé ailleurs les affiche correctement.
FUSEAU_REUNION = ZoneInfo("Africa/Kinshasa")
DUREE_PAR_DEFAUT = timedelta(hours=2)

TYPES_REUNION = {
    "bureau": "Réunion du Bureau",
    "commission": "Réunion de la Commission permanente",
    "commission_ad_hoc": "Réunion de la Commission ad hoc",
    "conseil": "Réunion du Conseil",
    "atelier": "Atelier / Séminaire / Formation",
}


@dataclass(frozen=True)
class Reunion:
    titre: str
    nature: str
    lieu: str
    jour: date
    heure_debut: time | None
    heure_fin: time | None
    travaux: list[str]
    service: str


def _heure(value: object) -> time | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%H:%M", "%H:%M:%S", "%Hh%M", "%Hh"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


def reunion_depuis_brouillon(contenu: dict, service_label: str) -> Reunion:
    """Lit la réunion dans le contenu du formulaire et valide son horaire."""
    fd_brut = (contenu or {}).get("formData") or {}
    if not isinstance(fd_brut, dict):
        raise ValueError("Les informations de la réunion sont invalides.")
    fd = fd_brut
    jour_txt = str(fd.get("date_reunion") or "").strip()[:10]
    try:
        jour = date.fromisoformat(jour_txt)
    except ValueError:
        raise ValueError("La date de la réunion est à renseigner avant d'envoyer la convocation.")
    type_reunion = str(fd.get("type_reunion") or "")
    debut_brut = str(fd.get("heure_debut") or "").strip()
    fin_brut = str(fd.get("heure_fin") or "").strip()
    heure_debut = _heure(debut_brut)
    heure_fin = _heure(fin_brut)
    if debut_brut and heure_debut is None:
        raise ValueError("L'heure de début de la réunion est invalide.")
    if fin_brut and heure_fin is None:
        raise ValueError("L'heure de fin de la réunion est invalide.")
    if heure_fin and not heure_debut:
        raise ValueError("Renseignez l'heure de début avant l'heure de fin.")
    if heure_debut and heure_fin and heure_fin <= heure_debut:
        raise ValueError("L'heure de fin doit être postérieure à l'heure de début.")
    travaux_bruts = fd.get("nature_travail") or []
    travaux = travaux_bruts if isinstance(travaux_bruts, list) else []
    return Reunion(
        titre=TYPES_REUNION.get(type_reunion, type_reunion or "Réunion"),
        nature=str(fd.get("nature_reunion") or "").strip(),
        lieu=str(fd.get("lieu") or "").strip(),
        jour=jour,
        heure_debut=heure_debut,
        heure_fin=heure_fin,
        travaux=[str(t).strip() for t in travaux if str(t or "").strip()],
        service=service_label,
    )


def _date_fr(jour: date) -> str:
    jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    mois = [
        "janvier", "février", "mars", "avril", "mai", "juin",
        "juillet", "août", "septembre", "octobre", "novembre", "décembre",
    ]
    return f"{jours[jour.weekday()]} {jour.day} {mois[jour.month - 1]} {jour.year}"


def _horaire(r: Reunion) -> str:
    if r.heure_debut and r.heure_fin:
        return f"de {r.heure_debut:%H:%M} à {r.heure_fin:%H:%M}"
    if r.heure_debut:
        return f"à {r.heure_debut:%H:%M}"
    return ""


def _echapper_ics(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _plier_ics(ligne: str) -> str:
    """Plie à 75 octets comme l'exige la RFC 5545, sans couper un caractère UTF-8."""
    morceaux: list[str] = []
    courant = ""
    for car in ligne:
        limite = 75 if not morceaux else 74
        if len((courant + car).encode("utf-8")) > limite:
            morceaux.append(courant)
            courant = car
        else:
            courant += car
    morceaux.append(courant)
    return "\r\n ".join(morceaux)


def construire_ics(
    r: Reunion,
    *,
    uid: str,
    organisateur: str,
    sequence: int = 0,
    destinataire: tuple[str, str] | None = None,
    maintenant: datetime | None = None,
) -> str:
    """Invitation agenda (iCalendar). Sans heure de début : événement sur la journée."""
    stamp = (maintenant or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if r.heure_debut:
        debut = datetime.combine(r.jour, r.heure_debut, FUSEAU_REUNION)
        fin = datetime.combine(r.jour, r.heure_fin, FUSEAU_REUNION) if r.heure_fin else debut + DUREE_PAR_DEFAUT
        if fin <= debut:
            fin = debut + DUREE_PAR_DEFAUT
        bornes = [
            f"DTSTART:{debut.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}",
            f"DTEND:{fin.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}",
        ]
    else:
        bornes = [
            f"DTSTART;VALUE=DATE:{r.jour:%Y%m%d}",
            f"DTEND;VALUE=DATE:{r.jour + timedelta(days=1):%Y%m%d}",
        ]
    resume = " — ".join(x for x in (r.titre, r.nature) if x)
    description = "Ordre du jour :\n" + "\n".join(f"- {t}" for t in r.travaux) if r.travaux else ""
    lignes = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ONEC//Convocation reunion//FR",
        "METHOD:REQUEST",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"SEQUENCE:{max(0, sequence)}",
        f"DTSTAMP:{stamp}",
        *bornes,
        f"SUMMARY:{_echapper_ics(resume)}",
        f"LOCATION:{_echapper_ics(r.lieu)}",
        f"DESCRIPTION:{_echapper_ics(description)}",
        f"ORGANIZER:mailto:{organisateur}",
        *(
            [
                f'ATTENDEE;CN="{_echapper_ics(destinataire[0]).replace(chr(34), chr(39))}";'
                f"RSVP=TRUE:mailto:{destinataire[1]}"
            ]
            if destinataire
            else []
        ),
        "STATUS:CONFIRMED",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(_plier_ics(l) for l in lignes) + "\r\n"


def texte_convocation(r: Reunion, *, nom: str, message: str, organisation: str) -> str:
    quand = " ".join(x for x in (_date_fr(r.jour), _horaire(r)) if x)
    lignes = [
        f"Bonjour {nom}," if nom else "Bonjour,",
        "",
        "Vous êtes convoqué(e) à la séance suivante : "
        + r.titre
        + (f" ({r.service})" if r.service else "")
        + ".",
        "",
        f"Date : {quand}",
    ]
    if r.lieu:
        lignes.append(f"Lieu : {r.lieu}")
    if r.nature:
        lignes.append(f"Objet : {r.nature}")
    if r.travaux:
        lignes += ["", "Ordre du jour :"] + [f"  {i}. {t}" for i, t in enumerate(r.travaux, start=1)]
    if message.strip():
        lignes += ["", message.strip()]
    lignes += [
        "",
        "Une liste de présence sera à signer en séance.",
        "L'invitation jointe (.ics) ajoute la réunion à votre agenda.",
        "",
        organisation,
    ]
    return "\n".join(lignes)


def _html(texte: str) -> str:
    corps = "<br>".join(html.escape(l) for l in texte.split("\n"))
    return (
        '<div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.5;color:#1f2937">'
        f"{corps}</div>"
    )


def envoyer_convocations(
    r: Reunion,
    destinataires: list[tuple[str, str]],
    *,
    smtp: SMTPConfig,
    message: str,
    organisation: str,
    uid: str | None = None,
    sequence: int = 0,
) -> list[tuple[str, str]]:
    """Envoie un message par (nom, e-mail). Renvoie les échecs : (e-mail, raison).

    Même UID pour tous : un renvoi après modification met à jour l'événement
    déjà importé au lieu d'en créer un second.
    """
    uid = uid or f"{uuid.uuid4()}@onec"
    sujet = f"Convocation — {r.titre} du {r.jour:%d/%m/%Y}"
    echecs: list[tuple[str, str]] = []
    for nom, email in destinataires:
        ics = construire_ics(
            r,
            uid=uid,
            organisateur=smtp.sender,
            sequence=sequence,
            destinataire=(nom, email),
        )
        texte = texte_convocation(r, nom=nom, message=message, organisation=organisation)
        msg = EmailMessage()
        msg["Subject"] = sujet
        msg["From"] = smtp.sender
        msg["To"] = email
        msg.set_content(texte)
        msg.add_alternative(_html(texte), subtype="html")
        msg.add_attachment(
            ics.encode("utf-8"),
            maintype="text",
            subtype="calendar",
            filename="convocation.ics",
            params={"method": "REQUEST", "charset": "utf-8"},
        )
        try:
            _send_email_message(
                smtp_host=smtp.host,
                smtp_port=smtp.port,
                smtp_user=smtp.user,
                smtp_password=smtp.password,
                msg=msg,
            )
        except Exception as exc:  # noqa: BLE001 — l'échec est rapporté, pas avalé
            logger.exception("convocation.email_failed to=%s", email)
            echecs.append((email, str(exc) or exc.__class__.__name__))
    return echecs
