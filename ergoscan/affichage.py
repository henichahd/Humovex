import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from angles import ZONES, VERT, JAUNE, ROUGE, OREILLE, EPAULE, COUDE, POIGNET, HANCHE, GENOU, VISIBILITE_MIN

NOMS = {"cou": "Cou", "epaules": "Épaules", "coudes": "Coudes",
        "poignets": "Poignets", "dos": "Dos", "genoux": "Genoux"}


def hexa(code):
    return tuple(int(code[i:i + 2], 16) for i in (0, 2, 4))


PALETTES = {
    "sauge": {
        "fond": hexa("CAD2C5"),
        "encre": hexa("3B342C"),
        "fond_barre": hexa("928779"),
        "fond_panneau": hexa("3B342C"),
        "bordure": hexa("928779"),
        "texte_clair": hexa("FCDEBE"),
        "accent": hexa("FCDEBE"),
        "message_fond": hexa("D4D2A5"),
        "message_texte": hexa("3B342C"),
        "piste": hexa("5E564C"),
        "vert": hexa("588157"),
        "jaune": hexa("E8B86D"),
        "rouge": hexa("C8553D"),
        "neutre": hexa("928779"),
    },
    "flamme": {
        "encre": hexa("171123"),
        "fond_barre": hexa("372248"),
        "fond_panneau": hexa("171123"),
        "bordure": hexa("414770"),
        "texte_clair": hexa("ECE8F2"),
        "accent": hexa("F46036"),
        "message_fond": hexa("5B85AA"),
        "message_texte": hexa("ECE8F2"),
        "piste": hexa("414770"),
        "vert": hexa("5B85AA"),
        "jaune": hexa("F5B041"),
        "rouge": hexa("F46036"),
        "neutre": hexa("414770"),
    },
    "sable": {
        "encre": hexa("361D2E"),
        "fond_barre": hexa("361D2E"),
        "fond_panneau": hexa("361D2E"),
        "bordure": hexa("86A397"),
        "texte_clair": hexa("CBC0AD"),
        "accent": hexa("E5BE9E"),
        "message_fond": hexa("E5BE9E"),
        "message_texte": hexa("361D2E"),
        "piste": hexa("5A4652"),
        "vert": hexa("86A397"),
        "jaune": hexa("E1B07E"),
        "rouge": hexa("C96A5B"),
        "neutre": hexa("CBC0AD"),
    },
    "lavande": {
        "encre": hexa("232645"),
        "fond_barre": hexa("7B8CDE"),
        "fond_panneau": hexa("232645"),
        "bordure": hexa("9999C3"),
        "texte_clair": hexa("C0E6DE"),
        "accent": hexa("C0E6DE"),
        "message_fond": hexa("9999C3"),
        "message_texte": hexa("FFFFFF"),
        "piste": hexa("4A4E7A"),
        "vert": hexa("C0E6DE"),
        "jaune": hexa("F0D39A"),
        "rouge": hexa("E07A86"),
        "neutre": hexa("9999C3"),
    },
}
PALETTE_PAR_DEFAUT = "sauge"

P = {}
RGB = {}
BGR = {}


def appliquer_palette(nom=PALETTE_PAR_DEFAUT):
    if nom not in PALETTES:
        raise ValueError(f"Palette inconnue « {nom} ». Choix : {', '.join(PALETTES)}")
    P.clear()
    P.update(PALETTES[nom])
    RGB.clear()
    RGB.update({VERT: P["vert"], JAUNE: P["jaune"], ROUGE: P["rouge"], None: P["neutre"]})
    BGR.clear()
    BGR.update({k: (v[2], v[1], v[0]) for k, v in RGB.items()})


def _luminance(c):
    def canal(v):
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (canal(v) for v in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def texte_sur(fond):
    lf = _luminance(fond)
    contraste_fonce = (lf + 0.05) / (_luminance(P["encre"]) + 0.05)
    contraste_blanc = 1.05 / (lf + 0.05)
    return P["encre"] if contraste_fonce >= contraste_blanc else (255, 255, 255)


def fond_squelette_bgr():
    e = P.get("fond", P["encre"])
    return (e[2], e[1], e[0])


def _encre_bgr():
    e = P["encre"]
    return (e[2], e[1], e[0])


appliquer_palette()

ZONE_DU_SEGMENT = {
    (11, 13): "epaules", (12, 14): "epaules",
    (13, 15): "coudes", (14, 16): "coudes",
    (15, 17): "poignets", (15, 19): "poignets", (15, 21): "poignets", (17, 19): "poignets",
    (16, 18): "poignets", (16, 20): "poignets", (16, 22): "poignets", (18, 20): "poignets",
    (11, 23): "dos", (12, 24): "dos", (11, 12): "dos", (23, 24): "dos",
    (23, 25): "genoux", (24, 26): "genoux", (25, 27): "genoux", (26, 28): "genoux",
}


def _police(taille, gras=False):
    candidats = (["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"] if gras else
                 ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"])
    for c in candidats:
        if Path(c).exists():
            return ImageFont.truetype(c, taille)
    return ImageFont.load_default()


_POLICES = {}


def police(taille, gras=False):
    if (taille, gras) not in _POLICES:
        _POLICES[(taille, gras)] = _police(taille, gras)
    return _POLICES[(taille, gras)]


def dessiner_squelette(img, pts, niveaux, connexions):
    contour = _encre_bgr()

    def vis(i):
        return pts[i][2] >= VISIBILITE_MIN

    def p(i):
        return int(pts[i][0]), int(pts[i][1])

    for a, b in connexions:
        if vis(a) and vis(b):
            zone = ZONE_DU_SEGMENT.get((a, b))
            couleur = BGR[niveaux.get(zone)] if zone else BGR[None]
            cv2.line(img, p(a), p(b), contour, 9, cv2.LINE_AA)
            cv2.line(img, p(a), p(b), couleur, 5, cv2.LINE_AA)

    ep = [p(EPAULE[s]) for s in "GD" if vis(EPAULE[s])]
    ore = [p(OREILLE[s]) for s in "GD" if vis(OREILLE[s])]
    if ep and ore:
        m_ep = tuple(int(v) for v in np.mean(ep, axis=0))
        m_or = tuple(int(v) for v in np.mean(ore, axis=0))
        cv2.line(img, m_ep, m_or, contour, 9, cv2.LINE_AA)
        cv2.line(img, m_ep, m_or, BGR[niveaux.get("cou")], 5, cv2.LINE_AA)

    for i in range(11, 29):
        if vis(i):
            cv2.circle(img, p(i), 6, contour, -1, cv2.LINE_AA)
            cv2.circle(img, p(i), 4, (255, 255, 255), -1, cv2.LINE_AA)


def _ancres(pts):
    def meilleur(dico):
        vis = [dico[s] for s in "GD" if pts[dico[s]][2] >= VISIBILITE_MIN]
        if not vis:
            return None
        i = max(vis, key=lambda k: pts[k][2])
        return pts[i][0], pts[i][1]

    a = {"cou": meilleur(OREILLE), "epaules": meilleur(EPAULE), "coudes": meilleur(COUDE),
         "poignets": meilleur(POIGNET), "genoux": meilleur(GENOU)}
    ep, ha = meilleur(EPAULE), meilleur(HANCHE)
    a["dos"] = ((ep[0] + ha[0]) / 2, (ep[1] + ha[1]) / 2) if (ep and ha) else None
    return a


def _pastille(d, xy, texte, fond, fnt, couleur_texte=None, ancre="lm", marge=(12, 6), contour=None, epaisseur=2):
    couleur_texte = couleur_texte or P["encre"]
    x0, y0, x1, y1 = d.textbbox((0, 0), texte, font=fnt)
    w, h = x1 - x0, y1 - y0
    x, y = xy
    if ancre == "mm":
        x -= w / 2 + marge[0]
    elif ancre == "rm":
        x -= w + 2 * marge[0]
    boite = [x, y - h / 2 - marge[1], x + w + 2 * marge[0], y + h / 2 + marge[1] + 2]
    d.rounded_rectangle(boite, radius=(boite[3] - boite[1]) / 2, fill=fond,
                        outline=contour, width=epaisseur if contour else 0)
    d.text((x + marge[0], y), texte, font=fnt, fill=couleur_texte, anchor="lm")
    return boite


def composer(frame_bgr, *, pts, zones, niveaux, stats, poste, debut, fps,
             message="", details=False, en_pause=False, reba=None,
             tache=None, num_tache=0, n_taches=0, invite=None, suivi=False):
    h, w = frame_bgr.shape[:2]
    k = w / 960
    f_et = police(int(17 * k), True)
    f_bar = police(int(16 * k), False)
    f_bar_g = police(int(17 * k), True)
    f_pt = police(int(14 * k), False)
    blanc = P["texte_clair"] + (255,)

    base = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)).convert("RGBA")
    calque = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(calque)

    hb = int(46 * k)
    d.rectangle([0, 0, w, hb], fill=P["fond_barre"] + (240,))
    pulse = int(time.time() * 2) % 2 == 0
    d.ellipse([int(16 * k), hb / 2 - 6 * k, int(28 * k), hb / 2 + 6 * k],
              fill=(P["rouge"] if (pulse and not en_pause) else P["vert"]) + (255,))
    d.text((int(38 * k), hb / 2), "ErgoScan", font=f_bar_g, fill=blanc, anchor="lm")
    d.text((int(140 * k), hb / 2), f"·  {poste}", font=f_bar, fill=P["accent"] + (255,), anchor="lm")
    duree = int(time.time() - debut)
    droite = ("PAUSE   " if en_pause else "") + f"{duree // 60:02d}:{duree % 60:02d}"
    d.text((w - int(16 * k), hb / 2), droite, font=f_bar_g, fill=blanc, anchor="rm")

    if reba:
        sc = reba["reba"]
        niv = VERT if sc <= 3 else (JAUNE if sc <= 7 else ROUGE)
        fond = RGB[niv]
        _pastille(d, (w - int(90 * k), hb / 2), f"REBA {sc} · {reba['niveau']}", fond + (255,), f_bar_g,
                  couleur_texte=texte_sur(fond), ancre="rm", marge=(12, 4))

    if n_taches:
        if tache:
            fond_t = P["accent"]
            texte_t = f"Tâche {num_tache} · {tache}"
        else:
            fond_t = P["neutre"]
            texte_t = f"Tâche non précisée · touches 1 à {n_taches}"
        _pastille(d, (int(16 * k), hb + 26 * k), texte_t, fond_t + (240,), f_bar_g,
                  couleur_texte=texte_sur(fond_t), ancre="lm", marge=(12, 5),
                  contour=P["encre"] + (200,), epaisseur=max(1, int(2 * k)))

    if pts is not None:
        ancres = _ancres(pts)
        items = [(z, ancres[z]) for z in ZONES if ancres.get(z) is not None and zones.get(z) is not None]
        if items:
            xs = [p[0] for p in pts[11:29] if p[2] >= VISIBILITE_MIN]
            droite_libre = w - max(xs)
            cote_droit = droite_libre >= 200 * k or droite_libre >= min(xs)
            x_col = (max(xs) + 40 * k) if cote_droit else (min(xs) - 40 * k)
            x_col = min(max(x_col, 10 * k), w - 10 * k)
            items.sort(key=lambda it: it[1][1])
            pas = 38 * k
            ys, y_prec = [], hb + 24 * k
            for _, (ax, ay) in items:
                y = max(ay, y_prec + pas)
                ys.append(y)
                y_prec = y
            depasse = ys[-1] - (h - 50 * k)
            if depasse > 0:
                ys = [max(hb + 24 * k, y - depasse) for y in ys]
            for (z, (ax, ay)), y in zip(items, ys):
                couleur = RGB[niveaux[z]]
                ep_trait = max(2, int(2 * k))
                d.line([(ax, ay), (x_col, y)], fill=P["encre"] + (150,), width=ep_trait + 2)
                d.line([(ax, ay), (x_col, y)], fill=couleur + (255,), width=ep_trait)
                d.ellipse([ax - 6 * k, ay - 6 * k, ax + 6 * k, ay + 6 * k], fill=P["encre"] + (255,))
                d.ellipse([ax - 4 * k, ay - 4 * k, ax + 4 * k, ay + 4 * k], fill=couleur + (255,))
                texte = f"{NOMS[z]}  {zones[z]:.0f}°"
                _pastille(d, (x_col, y), texte, couleur + (245,), f_et, couleur_texte=texte_sur(couleur),
                          ancre="lm" if cote_droit else "rm",
                          contour=P["encre"] + (200,), epaisseur=max(1, int(2 * k)))
    else:
        _pastille(d, (w / 2, h / 2), invite or "Personne non détectée — de profil, corps entier visible",
                  P["encre"] + (215,), f_et, couleur_texte=P["texte_clair"], ancre="mm", marge=(18, 10))

    if message:
        _pastille(d, (w / 2, hb + 34 * k), message, P["message_fond"] + (245,), f_et,
                  couleur_texte=P["message_texte"], ancre="mm", marge=(16, 8))

    if details:
        lw, lh = int(310 * k), int((60 + 32 * len(ZONES)) * k)
        x0, y0 = int(16 * k), h - lh - int(52 * k)
        d.rounded_rectangle([x0, y0, x0 + lw, y0 + lh], radius=int(14 * k), fill=P["fond_panneau"] + (225,),
                            outline=P["bordure"] + (255,), width=max(1, int(2 * k)))
        titre = f"Zone rouge · {tache}" if tache else "Temps passé en zone rouge"
        d.text((x0 + 16 * k, y0 + 22 * k), titre, font=f_bar_g,
               fill=P["accent"] + (255,), anchor="lm")
        for i, z in enumerate(ZONES):
            y = y0 + (54 + 32 * i) * k
            total = sum(stats[z])
            pct = 100 * stats[z][ROUGE] / total if total else 0
            d.text((x0 + 16 * k, y), NOMS[z], font=f_bar, fill=blanc, anchor="lm")
            bx0, bx1 = x0 + 115 * k, x0 + 235 * k
            d.rounded_rectangle([bx0, y - 5 * k, bx1, y + 5 * k], radius=5 * k, fill=P["piste"] + (255,))
            if pct > 0:
                d.rounded_rectangle([bx0, y - 5 * k, bx0 + (bx1 - bx0) * pct / 100, y + 5 * k],
                                    radius=5 * k, fill=P["rouge"] + (255,))
            d.text((x0 + lw - 16 * k, y), f"{pct:.0f} %", font=f_bar, fill=blanc, anchor="rm")

    aide = "c calibrer   ·   v squelette seul   ·   i détails   ·   p pause   ·   q terminer"
    if suivi:
        aide = "s choisir la personne   ·   " + aide
    if n_taches:
        aide = f"1–{n_taches} tâche   ·   0 aucune   ·   " + aide
    d.text((w / 2, h - 18 * k), aide, font=f_pt, fill=(255, 255, 255, 215), anchor="mm",
           stroke_width=2, stroke_fill=P["encre"] + (200,))

    image = Image.alpha_composite(base, calque).convert("RGB")
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
