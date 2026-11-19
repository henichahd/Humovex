import math

NEZ = 0
OREILLE = {"G": 7, "D": 8}
EPAULE = {"G": 11, "D": 12}
COUDE = {"G": 13, "D": 14}
POIGNET = {"G": 15, "D": 16}
INDEX = {"G": 19, "D": 20}
HANCHE = {"G": 23, "D": 24}
GENOU = {"G": 25, "D": 26}
CHEVILLE = {"G": 27, "D": 28}

ZONES = ["cou", "epaules", "coudes", "poignets", "dos", "genoux"]
NOMS = {"cou": "Cou", "epaules": "Epaules", "coudes": "Coudes",
        "poignets": "Poignets", "dos": "Dos", "genoux": "Genoux"}

VISIBILITE_MIN = 0.5

SEUILS = {
    "cou":     (10, 20),
    "dos":     (5, 20),
    "epaules": (20, 45),
    "poignets": (15, None),
    "genoux":  (30, 60),
}
COUDE_NEUTRE = (60, 100)

VERT, JAUNE, ROUGE = 0, 1, 2


def _vec(a, b):
    return (b[0] - a[0], b[1] - a[1])


def angle_entre(v1, v2):
    n1 = math.hypot(*v1)
    n2 = math.hypot(*v2)
    if n1 == 0 or n2 == 0:
        return None
    cos = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


def angle_3_points(a, b, c):
    return angle_entre(_vec(b, a), _vec(b, c))


def _milieu(a, b):
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def points_en_pixels(landmarks, largeur, hauteur):
    return [(lm.x * largeur, lm.y * hauteur, getattr(lm, "visibility", 1.0) or 0.0) for lm in landmarks]


def _ok(pts, *indices):
    return all(pts[i][2] >= VISIBILITE_MIN for i in indices)


def _xy(pts, i):
    return (pts[i][0], pts[i][1])


def calculer_angles(pts):
    a = {}
    VERTICALE_HAUT = (0, -1)

    epaules = [_xy(pts, EPAULE[s]) for s in "GD" if _ok(pts, EPAULE[s])]
    hanches = [_xy(pts, HANCHE[s]) for s in "GD" if _ok(pts, HANCHE[s])]
    oreilles = [_xy(pts, OREILLE[s]) for s in "GD" if _ok(pts, OREILLE[s])]
    mil_ep = _milieu(*epaules) if len(epaules) == 2 else (epaules[0] if epaules else None)
    mil_ha = _milieu(*hanches) if len(hanches) == 2 else (hanches[0] if hanches else None)
    mil_or = _milieu(*oreilles) if len(oreilles) == 2 else (oreilles[0] if oreilles else None)

    tronc = _vec(mil_ha, mil_ep) if (mil_ep and mil_ha) else None

    a["dos"] = angle_entre(tronc, VERTICALE_HAUT) if tronc else None

    a["cou"] = angle_entre(_vec(mil_ep, mil_or), tronc) if (tronc and mil_or) else None

    for s in "GD":
        e, c, p, i = EPAULE[s], COUDE[s], POIGNET[s], INDEX[s]
        h, g, ch = HANCHE[s], GENOU[s], CHEVILLE[s]

        a[f"epaule_{s}"] = (angle_entre(_vec(_xy(pts, e), _xy(pts, c)), _vec(_xy(pts, e), _xy(pts, h)))
                            if _ok(pts, e, c, h) else None)

        ang = angle_3_points(_xy(pts, e), _xy(pts, c), _xy(pts, p)) if _ok(pts, e, c, p) else None
        a[f"coude_{s}"] = 180 - ang if ang is not None else None

        ang = angle_3_points(_xy(pts, c), _xy(pts, p), _xy(pts, i)) if _ok(pts, c, p, i) else None
        a[f"poignet_{s}"] = 180 - ang if ang is not None else None

        ang = angle_3_points(_xy(pts, h), _xy(pts, g), _xy(pts, ch)) if _ok(pts, h, g, ch) else None
        a[f"genou_{s}"] = 180 - ang if ang is not None else None
    return a


def niveau(zone, angle, assis=False):
    if angle is None:
        return None
    if zone == "coudes":
        return VERT if COUDE_NEUTRE[0] <= angle <= COUDE_NEUTRE[1] else JAUNE
    if zone == "genoux" and assis:
        return VERT
    jaune, rouge = SEUILS[zone]
    if angle < jaune:
        return VERT
    if rouge is None or angle < rouge:
        return JAUNE
    return ROUGE


def angles_par_zone(a):
    z = {"cou": a.get("cou"), "dos": a.get("dos")}
    for zone, cle in [("epaules", "epaule"), ("poignets", "poignet"), ("genoux", "genou")]:
        vals = [a.get(f"{cle}_{s}") for s in "GD" if a.get(f"{cle}_{s}") is not None]
        z[zone] = max(vals) if vals else None
    coudes = [a.get(f"coude_{s}") for s in "GD" if a.get(f"coude_{s}") is not None]

    def ecart(v):
        return 0 if COUDE_NEUTRE[0] <= v <= COUDE_NEUTRE[1] else min(abs(v - COUDE_NEUTRE[0]), abs(v - COUDE_NEUTRE[1]))
    z["coudes"] = max(coudes, key=ecart) if coudes else None
    return z


class Lisseur:

    def __init__(self, alpha=0.4):
        self.alpha = alpha
        self.valeurs = {}

    def __call__(self, angles):
        sortie = {}
        for k, v in angles.items():
            if v is None:
                sortie[k] = None
                self.valeurs.pop(k, None)
                continue
            ancien = self.valeurs.get(k)
            nouveau = v if ancien is None else self.alpha * v + (1 - self.alpha) * ancien
            self.valeurs[k] = nouveau
            sortie[k] = nouveau
        return sortie
