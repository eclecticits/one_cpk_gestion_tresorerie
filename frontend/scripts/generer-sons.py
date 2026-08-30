#!/usr/bin/env python3
"""Fabrique les signaux sonores de l'application.

Les `.wav` sont versionnés, mais leur recette vit ici : un fichier audio est
illisible en revue et impossible à ajuster. Rejouer ce script régénère
`public/sons/`.

    python3 scripts/generer-sons.py

Rien n'est emprunté. Le langage sonore visé — bref, doux, professionnel, avec
une résolution nette — se décrit par des principes, jamais par la copie d'une
œuvre existante.

## Le timbre : « cristal »

Un verre frotté ou un célesta n'est pas une onde harmonique parfaite. Ses
partiels supérieurs sont légèrement décalés (inharmonicité) et meurent beaucoup
plus vite que la fondamentale. C'est exactement ce qui produit l'impression de
« scintillement qui se résout » : le son s'assombrit tout seul en s'éteignant,
sans qu'aucun filtre balayé n'intervienne. Un empilement harmonique parfait,
lui, sonnerait comme un orgue.

## Le geste : une cadence, pas un accord

L'ouverture monte La → Ré, c'est-à-dire V → I. L'oreille ENTEND une résolution
au lieu de constater un accord posé : c'est la différence entre « ça s'arrête »
et « ça se pose ». Les cinq notes de l'accord final entrent décalées de 6 à
40 ms — il s'ouvre au lieu d'être plaqué.

## Le grave : de la profondeur, pas de la boue

Ré3 (146,8 Hz) est sous le seuil des haut-parleurs d'ordinateur portable. Sa
fondamentale est donc volontairement plus faible que ses harmoniques 2 et 3,
qui tombent dans le médium : l'oreille RECONSTRUIT la hauteur qu'elle ne reçoit
pas. Sans cela, le grave n'existerait que sur un bon casque. Il ne part pas
dans l'écho, sinon l'ensemble devient boueux.
"""
from __future__ import annotations

import math
import pathlib
import struct
import wave

TAUX = 22050
CRETE_CIBLE = 0.72       # Sous 1.0 : aucune marge de saturation n'est prise.
SEUIL_ELAGAGE = 0.0015   # Sous ce niveau relatif, la traîne est inaudible.


# --------------------------------------------------------------------------
# Outils de traitement du signal
# --------------------------------------------------------------------------

class Bruit:
    """Générateur pseudo-aléatoire maison : rend le fichier reproductible.

    `random` donnerait un souffle différent à chaque exécution, donc un `.wav`
    qui change sans que la recette ait bougé — insupportable en revue.
    """

    def __init__(self, graine: int = 20260830) -> None:
        self.etat = graine & 0xFFFFFFFF

    def suivant(self) -> float:
        self.etat = (1664525 * self.etat + 1013904223) & 0xFFFFFFFF
        return (self.etat / 2147483648.0) - 1.0


def passe_bas(signal: list[float], coupure: float) -> list[float]:
    """Un pôle. Chaque reprise d'écho doit être plus sombre que la précédente."""
    x = math.exp(-2.0 * math.pi * coupure / TAUX)
    a, y, sortie = 1.0 - x, 0.0, []
    for v in signal:
        y = a * v + x * y
        sortie.append(y)
    return sortie


def passe_haut(signal: list[float], coupure: float) -> list[float]:
    """Nettoie la composante continue et l'infra-grave.

    Un haut-parleur de portable ne descend pas sous ~150 Hz : l'amplitude
    dépensée plus bas est perdue, et elle mange la marge avant saturation.
    """
    x = math.exp(-2.0 * math.pi * coupure / TAUX)
    sortie, y_prec, v_prec = [], 0.0, 0.0
    for v in signal:
        y = x * (y_prec + v - v_prec)
        sortie.append(y)
        y_prec, v_prec = y, v
    return sortie


def melanger(destination: list[float], source: list[float], debut: int, gain: float = 1.0) -> None:
    for i, v in enumerate(source):
        j = debut + i
        if 0 <= j < len(destination):
            destination[j] += v * gain


# --------------------------------------------------------------------------
# Les timbres
# --------------------------------------------------------------------------

#: (rapport de fréquence, amplitude relative, vitesse d'extinction).
#: Les rapports 5,41 et 8,72 ne sont pas des harmoniques : c'est cette
#: inharmonicité qui donne la signature « verre ».
PARTIELS_CRISTAL = (
    (1.000, 1.000, 1.00),   # porte la hauteur, s'éteint lentement
    (2.005, 0.420, 1.70),   # octave à peine désaccordée -> léger battement
    (3.014, 0.170, 2.60),   # la quinte : le « pincé »
    (4.030, 0.115, 3.40),
    (5.410, 0.062, 4.60),   # inharmonique : la touche verre
    (6.830, 0.030, 6.20),   # très bref, l'éclat de l'attaque
    (8.720, 0.011, 8.50),   # pointe de scintillement, éteinte en ~50 ms
)

#: Pour le grave : fondamentale discrète, harmoniques 2 et 3 dominantes.
PARTIELS_GRAVE = (
    (1.000, 0.55, 1.00),
    (2.000, 0.80, 1.35),
    (3.000, 0.45, 1.90),
    (4.000, 0.16, 2.80),
    (5.000, 0.06, 3.80),
)


def note(freq: float, duree: float, amplitude: float, partiels=PARTIELS_CRISTAL,
         attaque: float = 0.006, souffle: float = 0.0) -> list[float]:
    """Une note pincée.

    `attaque` : rampe en cosinus surélevé. Même la plus vive garde 4 à 6 ms de
    montée — c'est ce qui sépare un son pincé d'un clic.

    `souffle` : micro-bouffée de bruit filtrée 400–1800 Hz au tout début, qui
    imite le contact de l'ongle. Dosée très bas, elle donne le grain sans
    ajouter de stridence.
    """
    n = int(duree * TAUX)
    n_attaque = max(4, int(attaque * TAUX))
    buf = [0.0] * n

    for rapport, amp_rel, vitesse in partiels:
        f = freq * rapport
        if f > TAUX * 0.45:      # au-delà, le partiel se replierait (aliasing)
            continue
        tau = duree / (2.9 * vitesse)
        omega = 2.0 * math.pi * f / TAUX
        # Phase de départ propre à chaque partiel : sans cela ils s'additionnent
        # tous au même instant et créent une crête qui ne sert à rien.
        phase = (rapport * 1.7) % (2.0 * math.pi)
        a = amp_rel * amplitude
        for i in range(n):
            buf[i] += a * math.exp(-i / (tau * TAUX)) * math.sin(omega * i + phase)

    if souffle > 0.0:
        rng = Bruit(int(freq * 97) & 0xFFFF)
        n_bruit = min(n, int(0.012 * TAUX))
        brut = [rng.suivant() * math.exp(-i / (0.0035 * TAUX)) for i in range(n_bruit)]
        for i, v in enumerate(passe_haut(passe_bas(brut, 1800.0), 400.0)):
            buf[i] += v * souffle * amplitude * 8.0

    for i in range(min(n_attaque, n)):
        buf[i] *= 0.5 - 0.5 * math.cos(math.pi * i / n_attaque)

    # Retour à zéro en fin de note : sans lui, la coupe ferait un clic.
    n_fin = min(n, int(0.030 * TAUX))
    for k in range(n_fin):
        buf[n - n_fin + k] *= 0.5 + 0.5 * math.cos(math.pi * k / n_fin)
    return buf


# --------------------------------------------------------------------------
# Les partitions — ré majeur, pour les deux sons
# --------------------------------------------------------------------------
#
# La même tonalité et le même timbre partout : l'alerte doit s'entendre comme
# venant de la même application que l'ouverture, sans être le même geste.

RE3, RE4, FA4, LA4 = 146.83, 293.66, 369.99, 440.00   # Fa4 = Fa dièse
RE5, FA5, LA5 = 587.33, 739.99, 880.00                # Fa5 = Fa dièse
RE6, LA6 = 1174.66, 1760.00

#: (instant, fréquence, amplitude, durée, attaque, souffle)
OUVERTURE_CLAIR = [
    # L'arpège : la question (La), la réponse (Ré), le sourire (Fa#), l'éclat.
    (0.000, LA4, 0.52, 1.05, 0.005, 0.020),
    (0.150, RE5, 0.50, 1.05, 0.005, 0.018),
    (0.310, FA5, 0.44, 1.00, 0.005, 0.016),
    (0.470, LA5, 0.30, 0.90, 0.006, 0.010),
    # L'accord de résolution, volontairement désynchronisé : il respire.
    (0.700, RE4, 0.44, 2.30, 0.010, 0.008),
    (0.706, LA4, 0.30, 2.20, 0.010, 0.006),
    (0.716, FA4, 0.34, 2.25, 0.010, 0.006),
    (0.726, RE5, 0.26, 2.10, 0.009, 0.005),
    (0.740, FA5, 0.13, 1.90, 0.009, 0.000),
    # Étincelles de queue : elles entretiennent le scintillement pendant que
    # l'accord s'éteint, à un niveau où on les sent plus qu'on ne les entend.
    (1.150, RE6, 0.070, 0.70, 0.006, 0.0),
    (1.400, LA6, 0.030, 0.55, 0.006, 0.0),
    (1.520, LA5, 0.050, 0.80, 0.006, 0.0),
    (1.880, FA5, 0.036, 0.75, 0.007, 0.0),
]
OUVERTURE_GRAVE = [(0.690, RE3, 0.42, 2.40, 0.035, 0.0)]

#: L'alerte doit interrompre, pas bercer. Deux notes seulement, une quarte
#: ascendante prélevée sur le même accord, sans queue ni étincelles.
#: Attaque à 9 ms et non 5 : le banc mesurait 4 ms pour atteindre la mi-crête,
#: soit la limite sous laquelle l'oreille commence à percevoir un clic. Une
#: alerte doit être franche, pas claquante — et c'est sur un son bref, joué
#: plusieurs fois par jour, qu'un défaut d'attaque devient insupportable.
ALERTE_CLAIR = [
    (0.000, LA5, 0.46, 0.55, 0.009, 0.018),
    (0.110, RE6, 0.40, 0.85, 0.009, 0.012),
]
ALERTE_GRAVE = [(0.010, RE4, 0.20, 0.60, 0.020, 0.0)]


def composer(clair: list, grave: list, *, duree_brute: float,
             echos: tuple = ((0.118, 0.26, 3200.0), (0.236, 0.11, 2000.0))) -> list[float]:
    """Assemble, spatialise, élague, normalise.

    Le grave est tenu HORS de l'écho : l'y envoyer empile des basses décalées
    de 118 ms, ce qui s'entend comme de la boue et non comme une salle.
    """
    n = int(duree_brute * TAUX)
    bus_clair, bus_grave = [0.0] * n, [0.0] * n
    for t, f, a, d, att, sf in clair:
        melanger(bus_clair, note(f, d, a, PARTIELS_CRISTAL, att, sf), int(t * TAUX))
    for t, f, a, d, att, sf in grave:
        melanger(bus_grave, note(f, d, a, PARTIELS_GRAVE, att, sf), int(t * TAUX))

    # Deux reprises, chacune plus sombre : une petite salle vitrée. Elles
    # étalent le scintillement dans le temps sans ajouter d'aigu.
    echo = [0.0] * n
    for retard, gain, coupure in echos:
        melanger(echo, passe_bas(bus_clair, coupure), int(retard * TAUX), gain)

    melange = passe_haut([bus_clair[i] + bus_grave[i] + echo[i] for i in range(n)], 55.0)

    crete = max((abs(v) for v in melange), default=1.0) or 1.0
    fin = len(melange)
    while fin > 1 and abs(melange[fin - 1]) < SEUIL_ELAGAGE * crete:
        fin -= 1
    melange = melange[:fin]

    n_fondu = min(len(melange), int(0.025 * TAUX))
    for k in range(n_fondu):
        melange[len(melange) - n_fondu + k] *= 0.5 + 0.5 * math.cos(math.pi * k / n_fondu)

    crete = max((abs(v) for v in melange), default=1.0) or 1.0
    return [v * (CRETE_CIBLE / crete) for v in melange]


def ecrire(chemin: pathlib.Path, echantillons: list[float]) -> int:
    """Écrit un WAV mono 16 bits, borné à 32759 : zéro échantillon saturé."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(chemin), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(TAUX)
        f.writeframes(b"".join(
            struct.pack("<h", max(-32759, min(32759, int(round(v * 32767.0)))))
            for v in echantillons))
    return chemin.stat().st_size


if __name__ == "__main__":
    base = pathlib.Path(__file__).resolve().parent.parent / "public" / "sons"
    for nom, clair, grave, duree, echos in (
        ("ouverture", OUVERTURE_CLAIR, OUVERTURE_GRAVE, 4.2, None),
        # L'alerte n'a qu'une reprise, plus courte : elle doit se refermer vite.
        ("a-valider", ALERTE_CLAIR, ALERTE_GRAVE, 1.8, ((0.090, 0.18, 2800.0),)),
    ):
        options = {} if echos is None else {"echos": echos}
        sons = composer(clair, grave, duree_brute=duree, **options)
        taille = ecrire(base / f"{nom}.wav", sons)
        print(f"  {nom}.wav  {taille:>8} octets  {len(sons) / TAUX:.2f} s")
