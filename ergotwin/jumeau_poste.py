import math
from dataclasses import dataclass, asdict

import plotly.graph_objects as go

from reba import OptionsREBA, calculer_reba

VERT, JAUNE, ROUGE = 0, 1, 2
SEUILS = {"cou": (10, 20), "dos": (5, 20), "epaules": (20, 45), "poignets": (15, None), "genoux": (30, 60)}
COUDE_NEUTRE = (60, 100)
COULEURS = {VERT: "#588157", JAUNE: "#E8B86D", ROUGE: "#C8553D", None: "#928779"}
NOMS = {"cou": "Cou", "dos": "Dos", "epaules": "Épaules", "coudes": "Coudes", "poignets": "Poignets", "genoux": "Genoux"}


def niveau(zone, angle, assis=True):
    if angle is None:
        return None
    if zone == "coudes":
        return VERT if COUDE_NEUTRE[0] <= angle <= COUDE_NEUTRE[1] else JAUNE
    if zone == "genoux" and assis:
        return VERT
    j, r = SEUILS[zone]
    if angle < j:
        return VERT
    if r is None or angle < r:
        return JAUNE
    return ROUGE


@dataclass
class ReglagesPoste:
    taille: float = 160.0
    hauteur_chaise: float = 45.0
    hauteur_table: float = 75.0
    distance_table: float = 10.0
    profondeur_travail: float = 12.0
    hauteur_travail: float = 4.0
    inclinaison_plan: float = 0.0
    position: str = "assis"
    objet: str = "machine"
    regarder_travail: bool = True
    allonge: float = 0.98


def segments(H):
    return {
        "tronc": 0.288 * H,
        "cou_tete": 0.118 * H,
        "bras": 0.186 * H,
        "avant_bras": 0.146 * H,
        "main": 0.108 * H,
        "cuisse": 0.245 * H,
        "jambe": 0.246 * H,
        "pied_h": 0.039 * H,
        "pied_l": 0.152 * H,
        "largeur_epaules": 0.259 * H,
        "largeur_hanches": 0.191 * H,
        "hanche_assise": 0.05 * H,
        "ventre": 0.13 * H,
    }


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def point_travail(r: ReglagesPoste, L):
    x_bord_table = L["ventre"] + r.distance_table
    a = math.radians(r.inclinaison_plan)
    x = x_bord_table + r.profondeur_travail * math.cos(a)
    z = r.hauteur_table + r.profondeur_travail * math.sin(a) + r.hauteur_travail
    return (x, z), x_bord_table


def calculer_posture(r: ReglagesPoste):
    L = segments(r.taille)
    debout = r.position == "debout"
    hauteur_hanche_debout = L["cuisse"] + L["jambe"] + L["pied_h"]
    hanche = (0.0, hauteur_hanche_debout if debout else r.hauteur_chaise + L["hanche_assise"])
    cible, x_bord_table = point_travail(r, L)
    portee = L["bras"] + L["avant_bras"] + 0.5 * L["main"]
    alertes = []

    tronc = 3.0
    while True:
        epaule = (hanche[0] + L["tronc"] * math.sin(math.radians(tronc)),
                  hanche[1] + L["tronc"] * math.cos(math.radians(tronc)))
        if _dist(epaule, cible) <= r.allonge * portee or tronc >= 60:
            break
        tronc += 1.0
    if _dist(epaule, cible) > portee:
        alertes.append("Point de travail hors d'atteinte, même penchée à 60°")

    l1, l2 = L["bras"], L["avant_bras"] + 0.5 * L["main"]
    d = min(_dist(epaule, cible), l1 + l2 - 1e-6)
    cos_coude = (l1 ** 2 + l2 ** 2 - d ** 2) / (2 * l1 * l2)
    angle_interieur_coude = math.degrees(math.acos(max(-1, min(1, cos_coude))))
    direction = math.atan2(cible[1] - epaule[1], cible[0] - epaule[0])
    cos_a = (l1 ** 2 + d ** 2 - l2 ** 2) / (2 * l1 * d)
    a = math.acos(max(-1, min(1, cos_a)))
    ang_bras = direction - a
    coude = (epaule[0] + l1 * math.cos(ang_bras), epaule[1] + l1 * math.sin(ang_bras))
    main = (coude[0] + l2 * math.cos(math.atan2(cible[1] - coude[1], cible[0] - coude[0])),
            coude[1] + l2 * math.sin(math.atan2(cible[1] - coude[1], cible[0] - coude[0])))
    poignet = (coude[0] + (L["avant_bras"]) / l2 * (main[0] - coude[0]),
               coude[1] + (L["avant_bras"]) / l2 * (main[1] - coude[1]))

    v_bras = (coude[0] - epaule[0], coude[1] - epaule[1])
    v_bas = (hanche[0] - epaule[0], hanche[1] - epaule[1])
    angle_epaule = math.degrees(math.acos(max(-1, min(1, (v_bras[0] * v_bas[0] + v_bras[1] * v_bas[1]) /
                                                     (math.hypot(*v_bras) * math.hypot(*v_bas))))))
    flexion_coude = 180 - angle_interieur_coude

    tete_inclinaison = tronc
    for _ in range(3):
        yeux = (epaule[0] + L["cou_tete"] * math.sin(math.radians(tete_inclinaison)) + 0.04 * r.taille,
                epaule[1] + L["cou_tete"] * math.cos(math.radians(tete_inclinaison)))
        regard = math.degrees(math.atan2(yeux[1] - cible[1], cible[0] - yeux[0]))
        tete_inclinaison = max(tronc, regard - 25) if r.regarder_travail else tronc
    flexion_cou = max(0.0, tete_inclinaison - tronc)
    tete = (epaule[0] + L["cou_tete"] * math.sin(math.radians(tete_inclinaison)),
            epaule[1] + L["cou_tete"] * math.cos(math.radians(tete_inclinaison)))

    if debout:
        genou = (hanche[0] + 2, hanche[1] - L["cuisse"])
        cheville = (hanche[0], L["pied_h"])
        flexion_genou = 0.0
    else:
        genou = (hanche[0] + L["cuisse"], r.hauteur_chaise + 3)
        sol_atteint = genou[1] - L["jambe"] - L["pied_h"] <= 3
        cheville = (genou[0], max(L["pied_h"], genou[1] - L["jambe"]))
        flexion_genou = 90.0
        if not sol_atteint:
            alertes.append(f"Pieds dans le vide ({genou[1] - L['jambe'] - L['pied_h']:.0f} cm) : prévoir un repose-pieds")
        if genou[1] + 10 > r.hauteur_table - 3 and genou[0] > x_bord_table:
            alertes.append("Les genoux touchent le dessous de la table")
    if debout and tronc >= 20:
        alertes.append("Le dos se penche beaucoup : plan de travail trop bas ou trop loin")

    poignet_dev = 10.0

    angles = {"cou": flexion_cou, "dos": tronc, "epaule_G": angle_epaule, "epaule_D": angle_epaule,
              "coude_G": flexion_coude, "coude_D": flexion_coude, "poignet_G": poignet_dev,
              "poignet_D": poignet_dev, "genou_G": flexion_genou, "genou_D": flexion_genou}
    zones = {"cou": flexion_cou, "dos": tronc, "epaules": angle_epaule, "coudes": flexion_coude,
             "poignets": poignet_dev, "genoux": flexion_genou}
    niveaux = {z: niveau(z, v, assis=not debout) for z, v in zones.items()}
    return {
        "L": L, "reglages": asdict(r),
        "points": {"hanche": hanche, "epaule": epaule, "coude": coude, "poignet": poignet, "main": main,
                   "tete": tete, "yeux": yeux, "genou": genou, "cheville": cheville, "cible": cible},
        "x_bord_table": x_bord_table, "angles": angles, "zones": zones, "niveaux": niveaux,
        "alertes": alertes,
    }


def evaluer(r: ReglagesPoste, options: OptionsREBA = None):
    p = calculer_posture(r)
    o = options or OptionsREBA()
    o.assis = r.position != "debout"
    p["reba"] = calculer_reba(p["angles"], o)
    p["charges"] = {z: {VERT: 0.0, JAUNE: 0.5, ROUGE: 1.0}[n] for z, n in p["niveaux"].items()}
    return p


BOIS, METAL, MACHINE, SOL = "#B8A88A", "#7A7065", "#E8E1D3", "#CAD2C5"


def _boite(x0, x1, y0, y1, z0, z1, couleur, nom, opacite=1.0):
    xs = [x0, x1, x1, x0, x0, x1, x1, x0]
    ys = [y0, y0, y1, y1, y0, y0, y1, y1]
    zs = [z0, z0, z0, z0, z1, z1, z1, z1]
    i = [0, 0, 4, 4, 0, 0, 1, 1, 0, 0, 3, 3]
    j = [1, 2, 5, 6, 1, 5, 2, 6, 3, 7, 2, 6]
    k = [2, 3, 6, 7, 5, 4, 6, 5, 7, 4, 6, 7]
    return go.Mesh3d(x=xs, y=ys, z=zs, i=i, j=j, k=k, color=couleur, opacity=opacite, name=nom,
                     flatshading=True, hoverinfo="name", showscale=False,
                     lighting=dict(ambient=0.6, diffuse=0.8, specular=0.1))


def _plateau_incline(x0, x1, y0, y1, z, epaisseur, angle, couleur, nom):
    a = math.radians(angle)
    dx, dz = (x1 - x0) * math.cos(a), (x1 - x0) * math.sin(a)
    xs, ys, zs = [], [], []
    for ep in (0, epaisseur):
        for (xx, zz) in [(x0, z), (x0 + dx, z + dz)]:
            for yy in (y0, y1):
                xs.append(xx)
                ys.append(yy)
                zs.append(zz + ep)
    i = [0, 1, 4, 5, 0, 2, 1, 3, 0, 1, 2, 3]
    j = [1, 3, 5, 7, 2, 6, 3, 7, 1, 5, 3, 7]
    k = [2, 2, 6, 6, 6, 4, 7, 5, 4, 4, 6, 6]
    return go.Mesh3d(x=xs, y=ys, z=zs, i=i, j=j, k=k, color=couleur, name=nom, flatshading=True,
                     hoverinfo="name", lighting=dict(ambient=0.6, diffuse=0.8))


def _cylindre(a, b, rayon, couleur, nom, n=14, r2=None):
    import numpy as np
    a, b = np.array(a, float), np.array(b, float)
    axe = b - a
    long = np.linalg.norm(axe)
    if long < 1e-6:
        return _sphere(tuple(a), rayon, couleur, nom)
    axe /= long
    aide = np.array([0, 0, 1.0]) if abs(axe[2]) < 0.9 else np.array([1.0, 0, 0])
    u = np.cross(axe, aide); u /= np.linalg.norm(u)
    v = np.cross(axe, u)
    r2 = rayon if r2 is None else r2
    xs, ys, zs = [], [], []
    for centre, rr in ((a, rayon), (b, r2)):
        for t in np.linspace(0, 2 * np.pi, n, endpoint=False):
            pt = centre + rr * (np.cos(t) * u + np.sin(t) * v)
            xs.append(pt[0]); ys.append(pt[1]); zs.append(pt[2])
    xs += [a[0], b[0]]; ys += [a[1], b[1]]; zs += [a[2], b[2]]
    I, J, K = [], [], []
    for t in range(n):
        t2 = (t + 1) % n
        I += [t, t2]; J += [t2, n + t2]; K += [n + t, n + t]
        I += [2 * n, 2 * n + 1]; J += [t2, n + t]; K += [t, n + t2]
    return go.Mesh3d(x=xs, y=ys, z=zs, i=I, j=J, k=K, color=couleur, name=nom, hoverinfo="name",
                     flatshading=False, lighting=dict(ambient=0.55, diffuse=0.8, specular=0.2, roughness=0.6))


def _sphere(c, rayon, couleur, nom, n=12):
    import numpy as np
    xs, ys, zs = [], [], []
    for i in range(n + 1):
        th = np.pi * i / n
        for j in range(n):
            ph = 2 * np.pi * j / n
            xs.append(c[0] + rayon * np.sin(th) * np.cos(ph))
            ys.append(c[1] + rayon * np.sin(th) * np.sin(ph))
            zs.append(c[2] + rayon * np.cos(th))
    I, J, K = [], [], []
    for i in range(n):
        for j in range(n):
            a = i * n + j; b = i * n + (j + 1) % n; c2 = (i + 1) * n + j; d = (i + 1) * n + (j + 1) % n
            I += [a, b]; J += [b, d]; K += [c2, c2]
    return go.Mesh3d(x=xs, y=ys, z=zs, i=I, j=J, k=K, color=couleur, name=nom, hoverinfo="name",
                     lighting=dict(ambient=0.55, diffuse=0.8, specular=0.2, roughness=0.6))


def _segment(a, b, couleur, largeur, nom, y=0.0):
    return go.Scatter3d(x=[a[0], b[0]], y=[y, y], z=[a[1], b[1]], mode="lines",
                        line=dict(color=couleur, width=largeur), name=nom, hoverinfo="name", showlegend=False)


def figure_poste(p, titre="", profondeur_table=70.0, plage=None):
    L, pts, r = p["L"], p["points"], p["reglages"]
    niv = p["niveaux"]
    c = {z: COULEURS[n] for z, n in niv.items()}
    traces = []

    traces.append(_boite(-60, 160, -80, 80, -1, 0, SOL, "Sol"))

    hc = r["hauteur_chaise"]
    if r["position"] == "assis":
      traces.append(_boite(-0.25 * L["cuisse"], 0.8 * L["cuisse"], -22, 22, hc - 4, hc, BOIS, "Assise"))
      traces.append(_boite(-0.25 * L["cuisse"] - 4, -0.25 * L["cuisse"], -20, 20, hc, hc + 40, BOIS, "Dossier"))
      for xx in (-0.2 * L["cuisse"], 0.7 * L["cuisse"]):
          for yy in (-18, 18):
              traces.append(_boite(xx - 1.5, xx + 1.5, yy - 1.5, yy + 1.5, 0, hc - 4, METAL, "Pied de chaise"))

    xt, ht = p["x_bord_table"], r["hauteur_table"]
    pt_ = float(profondeur_table)
    traces.append(_plateau_incline(xt, xt + pt_, -60, 60, ht - 3, 3, r["inclinaison_plan"], BOIS, "Plateau"))
    pente = math.tan(math.radians(r["inclinaison_plan"]))
    for xx in (xt + 3, xt + pt_ - 3):
        for yy in (-57, 57):
            traces.append(_boite(xx - 2, xx + 2, yy - 2, yy + 2, 0, ht - 3 + (xx - xt) * pente, METAL, "Pied de table"))

    cx, cz = pts["cible"]
    if r["objet"] == "machine":
        traces.append(_boite(cx - 6, cx + 30, -22, 22, cz - r["hauteur_travail"], cz - 1, MACHINE, "Machine à coudre"))
        traces.append(_boite(cx + 18, cx + 30, -22, 22, cz - 1, cz + 22, MACHINE, "Bras de la machine"))
        traces.append(_boite(cx - 6, cx + 30, -22, -12, cz + 14, cz + 24, MACHINE, "Tête de la machine"))
    else:
        traces.append(_boite(cx - 15, cx + 15, -20, 20, cz - max(r["hauteur_travail"], 1), cz,
                             "#A3B4C8", "Pièce travaillée"))
    traces.append(go.Scatter3d(x=[cx], y=[-8], z=[cz], mode="markers", name="Point de travail",
                               marker=dict(size=6, color="#361D2E", symbol="diamond"), hoverinfo="name",
                               showlegend=False))

    ye, yh = L["largeur_epaules"] / 2 - 4, L["largeur_hanches"] / 2 - 3
    H, E, C, P, M = pts["hanche"], pts["epaule"], pts["coude"], pts["poignet"], pts["main"]
    G, Ch, T = pts["genou"], pts["cheville"], pts["tete"]
    k = r["taille"] / 160

    def p3(pt, y):
        return (pt[0], y, pt[1])

    traces.append(_cylindre(p3(H, 0), p3(E, 0), 13 * k, c["dos"], f"Dos {p['zones']['dos']:.0f}°", r2=15 * k))
    traces.append(_sphere(p3(H, 0), 13 * k, c["dos"], "Bassin"))
    for yy in (-ye, ye):
        traces.append(_sphere(p3(E, yy), 5 * k, c["epaules"], "Épaule"))
        traces.append(_cylindre(p3(E, 0), p3(E, yy), 6 * k, c["dos"], "Épaules"))
        traces.append(_cylindre(p3(E, yy), p3(C, yy), 4.5 * k, c["epaules"], f"Épaule {p['zones']['epaules']:.0f}°"))
        traces.append(_sphere(p3(C, yy), 4 * k, c["coudes"], "Coude"))
        traces.append(_cylindre(p3(C, yy), p3(P, yy * 0.9), 3.8 * k, c["coudes"], f"Coude {p['zones']['coudes']:.0f}°"))
        traces.append(_cylindre(p3(P, yy * 0.9), p3(M, yy * 0.8), 3.0 * k, c["poignets"],
                                f"Poignet {p['zones']['poignets']:.0f}° (supposé)"))
    for yy in (-yh, yh):
        traces.append(_cylindre(p3(H, yy), p3(G, yy), 7 * k, c["genoux"], "Cuisse"))
        traces.append(_sphere(p3(G, yy), 6 * k, c["genoux"], "Genou"))
        traces.append(_cylindre(p3(G, yy), p3(Ch, yy), 5 * k, c["genoux"], "Jambe"))
        traces.append(_boite(Ch[0] - 4, Ch[0] + 0.7 * L["pied_l"], yy - 4.5, yy + 4.5,
                             max(0, Ch[1] - L["pied_h"]), Ch[1] + 1, "#5E564C", "Pied"))
    traces.append(_cylindre(p3(E, 0), p3(T, 0), 5 * k, c["cou"], f"Cou {p['zones']['cou']:.0f}°"))
    angle_tete = math.atan2(T[0] - E[0], T[1] - E[1])
    centre_tete = (T[0] + 9 * k * math.sin(angle_tete), 0, T[1] + 9 * k * math.cos(angle_tete))
    traces.append(_sphere(centre_tete, 11 * k, c["cou"], f"Tête (cou {p['zones']['cou']:.0f}°)"))
    Y = pts["yeux"]
    traces.append(go.Scatter3d(x=[centre_tete[0] + 8 * k, cx], y=[0, -8], z=[centre_tete[2] - 2 * k, cz],
                               mode="lines", line=dict(color="#361D2E", width=3, dash="dash"),
                               name="Ligne du regard", hoverinfo="name", showlegend=False))

    fig = go.Figure(traces)
    fig.update_layout(
        title=titre, height=560, margin=dict(l=0, r=0, t=40 if titre else 0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        scene=dict(
            xaxis=dict(visible=False), yaxis=dict(visible=False), zaxis=dict(visible=False),
            aspectmode="data" if plage is None else "manual",
            camera=dict(eye=dict(x=-0.85, y=-1.25, z=0.45), center=dict(x=0.05, y=0, z=-0.12)),
            bgcolor="rgba(0,0,0,0)",
        ),
        showlegend=False,
    )
    if plage is not None:
        x0, x1, z1 = plage
        fig.update_layout(scene=dict(
            xaxis=dict(visible=False, range=[x0, x1]), yaxis=dict(visible=False, range=[-80, 80]),
            zaxis=dict(visible=False, range=[0, z1]),
            aspectratio=dict(x=(x1 - x0) / 160, y=1.0, z=z1 / 160)))
    return fig


if __name__ == "__main__":
    for nom, r in [("Poste actuel", ReglagesPoste()),
                   ("Table plus haute + plan incliné", ReglagesPoste(hauteur_table=80, inclinaison_plan=10))]:
        p = evaluer(r)
        z = {k: f"{v:.0f}°" for k, v in p["zones"].items()}
        print(f"{nom:<35} REBA {p['reba']['reba']} ({p['reba']['niveau']}) | {z} | {p['alertes']}")
