from types import SimpleNamespace

from app.utils.hierarchie_fonctions import trier_participants


def _p(nom: str, fonction: str, type_participant: str = "principal", ordre: int | None = None) -> SimpleNamespace:
    return SimpleNamespace(nom=nom, titre_fonction=fonction, type_participant=type_participant, ordre=ordre)


def test_conseil_president_puis_bureau_puis_membres_puis_assistants():
    # Composition réelle du Conseil : les membres, alphabétiquement avant le
    # Président, passaient devant lui.
    participants = [
        _p("KIPAMPE", "Membre du conseil"),
        _p("ASSISTANTE", "Assistant(e)", "assistant"),
        _p("BUKASA", "Trésorier adjoint"),
        _p("KULE", "Membre du conseil"),
        _p("BENGA", "Trésorière"),
        _p("LIGBAKELO", "Rapporteur adjoint"),
        _p("OKENDE", "Rapporteur"),
        _p("MAMPASI", "Vice-président"),
        _p("TUMBA", "Président"),
    ]
    assert [p.nom for p in trier_participants(participants)] == [
        "TUMBA",
        "MAMPASI",
        "OKENDE",
        "LIGBAKELO",
        "BENGA",
        "BUKASA",
        "KIPAMPE",
        "KULE",
        "ASSISTANTE",
    ]


def test_ordre_saisi_prime_sur_la_fonction():
    # « Membre du bureau » n'est pas reconnu par le classement par fonction :
    # l'ordre fixé à la saisie le place où l'utilisateur l'a voulu.
    participants = [
        _p("KIPAMPE", "Membre du conseil", ordre=3),
        _p("ASSISTANTE", "Assistant(e)", "assistant", ordre=1),
        _p("MUKENDI", "Membre du bureau", ordre=2),
        _p("TUMBA", "Président", ordre=1),
    ]
    assert [p.nom for p in trier_participants(participants)] == ["TUMBA", "MUKENDI", "KIPAMPE", "ASSISTANTE"]
