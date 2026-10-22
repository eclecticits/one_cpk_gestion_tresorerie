from types import SimpleNamespace

from app.api.v1.endpoints.whatsapp import _group_by_person, _recipient_out


def _fiche(id_: int, nom: str, service: str, fonction: str, telephone: str | None = None, notify: bool = False):
    return SimpleNamespace(
        id=id_,
        full_name=nom,
        service_id=id_,
        service=SimpleNamespace(libelle=service, code=""),
        function=SimpleNamespace(label=fonction),
        custom_title=None,
        role_type=None,
        email=None,
        telephone=telephone,
        notify_whatsapp=notify,
    )


def test_une_ligne_par_personne_quel_que_soit_le_nombre_de_services():
    # Une personne siège au Bureau, au Conseil et dans une commission : trois
    # fiches, qui s'affichaient sur trois lignes.
    fiches = [
        _fiche(1, "Jean MUKENDI", "Commission Tableau", "Membre"),
        _fiche(2, "jean  mukendi", "BUREAU", "Président(e)", telephone="0810123456", notify=True),
        _fiche(3, "Jean Mukendi", "Conseil Provincial", "Membre du conseil"),
        _fiche(4, "Marie KABILA", "BUREAU", "Trésorier"),
    ]
    lignes = [_recipient_out(groupe) for groupe in _group_by_person(fiches)]

    assert [ligne.full_name for ligne in lignes] == ["jean  mukendi", "Marie KABILA"]
    jean = lignes[0]
    # La fonction la plus haute est celle affichée ; le numéro et l'opt-in
    # viennent de la fiche qui les porte.
    assert jean.function == "Président(e)"
    assert jean.status == "ready"
    assert jean.services == ["Commission Tableau", "BUREAU", "Conseil Provincial"]
    assert jean.member_ids == [1, 2, 3]
