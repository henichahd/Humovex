from dataclasses import dataclass

TABLE_A = [
    [[1, 2, 3, 4], [2, 3, 4, 5], [2, 4, 5, 6], [3, 5, 6, 7], [4, 6, 7, 8]],
    [[1, 2, 3, 4], [3, 4, 5, 6], [4, 5, 6, 7], [5, 6, 7, 8], [6, 7, 8, 9]],
    [[3, 3, 5, 6], [4, 5, 6, 7], [5, 6, 7, 8], [6, 7, 8, 9], [7, 8, 9, 9]],
]

TABLE_B = [
    [[1, 2, 2], [1, 2, 3], [3, 4, 5], [4, 5, 5], [6, 7, 8], [7, 8, 8]],
    [[1, 2, 3], [2, 3, 4], [4, 5, 5], [5, 6, 7], [7, 8, 8], [8, 9, 9]],
]

TABLE_C = [
    [1, 1, 1, 2, 3, 3, 4, 5, 6, 7, 7, 7],
    [1, 2, 2, 3, 4, 4, 5, 6, 6, 7, 7, 8],
    [2, 3, 3, 3, 4, 5, 6, 7, 7, 8, 8, 8],
    [3, 4, 4, 4, 5, 6, 7, 8, 8, 9, 9, 9],
    [4, 4, 4, 5, 6, 7, 8, 8, 9, 9, 9, 9],
    [6, 6, 6, 7, 8, 8, 9, 9, 10, 10, 10, 10],
    [7, 7, 7, 8, 9, 9, 9, 10, 10, 11, 11, 11],
    [8, 8, 8, 9, 10, 10, 10, 10, 10, 11, 11, 11],
    [9, 9, 9, 10, 10, 10, 11, 11, 11, 12, 12, 12],
    [10, 10, 10, 11, 11, 11, 11, 12, 12, 12, 12, 12],
    [11, 11, 11, 11, 12, 12, 12, 12, 12, 12, 12, 12],
    [12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12, 12],
]

NIVEAUX_REBA = [
    (1, "Négligeable", "Aucune action nécessaire"),
    (3, "Faible", "Changement peut-être nécessaire"),
    (7, "Moyen", "Analyser davantage, changer bientôt"),
    (10, "Élevé", "Analyser et changer rapidement"),
    (15, "Très élevé", "Changer immédiatement"),
]

PRISES = {"bonne": 0, "correcte": 1, "mauvaise": 2, "inacceptable": 3}


@dataclass
class OptionsREBA:
    assis: bool = False
    appui_instable: bool = False
    charge_kg: float = 0.0
    choc: bool = False
    prise: str = "bonne"
    torsion_tronc: bool = False
    torsion_cou: bool = False
    epaule_haussee: bool = False
    bras_ecarte: bool = False
    bras_soutenu: bool = False
    poignet_devie: bool = False
    statique: bool = False
    repetitif: bool = False
    instable: bool = False


def score_cou(angle, o):
    s = 1 if angle <= 20 else 2
    return s + (1 if o.torsion_cou else 0)


def score_tronc(angle, o):
    if angle <= 5:
        s = 1
    elif angle <= 20:
        s = 2
    elif angle <= 60:
        s = 3
    else:
        s = 4
    return s + (1 if o.torsion_tronc else 0)


def score_jambes(flexion_genou, o):
    s = 2 if o.appui_instable else 1
    if not o.assis and flexion_genou is not None:
        if flexion_genou > 60:
            s += 2
        elif flexion_genou >= 30:
            s += 1
    return s


def score_bras(angle, o):
    if angle <= 20:
        s = 1
    elif angle <= 45:
        s = 2
    elif angle <= 90:
        s = 3
    else:
        s = 4
    s += (1 if o.epaule_haussee else 0) + (1 if o.bras_ecarte else 0) - (1 if o.bras_soutenu else 0)
    return max(1, min(6, s))


def score_avant_bras(flexion):
    return 1 if 60 <= flexion <= 100 else 2


def score_poignet(angle, o):
    s = 1 if (angle is None or angle <= 15) else 2
    return min(3, s + (1 if o.poignet_devie else 0))


def score_charge(o):
    s = 0 if o.charge_kg < 5 else (1 if o.charge_kg <= 10 else 2)
    return s + (1 if o.choc else 0)


def niveau_reba(score):
    for maxi, nom, action in NIVEAUX_REBA:
        if score <= maxi:
            return nom, action
    return NIVEAUX_REBA[-1][1:]


def calculer_reba(a, o=None):
    o = o or OptionsREBA()
    if a.get("cou") is None or a.get("dos") is None:
        return None

    cou = score_cou(a["cou"], o)
    tronc = score_tronc(a["dos"], o)
    genoux = [a.get(f"genou_{s}") for s in "GD" if a.get(f"genou_{s}") is not None]
    jambes = score_jambes(max(genoux) if genoux else None, o)
    table_a = TABLE_A[min(cou, 3) - 1][min(tronc, 5) - 1][min(jambes, 4) - 1]
    score_a = table_a + score_charge(o)

    meilleur = None
    for s in "GD":
        if a.get(f"epaule_{s}") is None or a.get(f"coude_{s}") is None:
            continue
        bras = score_bras(a[f"epaule_{s}"], o)
        avant = score_avant_bras(a[f"coude_{s}"])
        poignet = score_poignet(a.get(f"poignet_{s}"), o)
        tb = TABLE_B[avant - 1][bras - 1][poignet - 1]
        if meilleur is None or tb > meilleur["table_b"]:
            meilleur = {"cote": s, "bras": bras, "avant_bras": avant, "poignet": poignet, "table_b": tb}
    if meilleur is None:
        return None
    score_b = meilleur["table_b"] + PRISES.get(o.prise, 0)

    score_c = TABLE_C[min(score_a, 12) - 1][min(score_b, 12) - 1]
    activite = int(o.statique) + int(o.repetitif) + int(o.instable)
    final = min(15, score_c + activite)
    nom, action = niveau_reba(final)

    return {
        "cou": cou, "tronc": tronc, "jambes": jambes, "table_a": table_a, "score_a": score_a,
        **meilleur, "score_b": score_b, "score_c": score_c, "activite": activite,
        "reba": final, "niveau": nom, "action": action,
    }
