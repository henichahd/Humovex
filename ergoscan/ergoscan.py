import argparse
import csv
import os
import sys
import time
import unicodedata
import urllib.request
from dataclasses import replace
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision

from angles import (ZONES, NOMS, points_en_pixels, calculer_angles, angles_par_zone, niveau, Lisseur)
from reba import OptionsREBA, calculer_reba, niveau_reba, NIVEAUX_REBA, PRISES
from affichage import composer, dessiner_squelette, fond_squelette_bgr, appliquer_palette, PALETTES, PALETTE_PAR_DEFAUT

DOSSIER = Path(__file__).parent
URL_MODELE = ("https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
              "pose_landmarker_full/float16/latest/pose_landmarker_full.task")
MODELE = DOSSIER / "pose_landmarker_full.task"
TITRE = "ErgoScan"

CONNEXIONS = [(c.start, c.end) for c in vision.PoseLandmarksConnections.POSE_LANDMARKS
              if c.start >= 11 and c.end >= 11 and c.start <= 28 and c.end <= 28]

CLES_ANGLES = ["cou", "dos", "epaule_G", "epaule_D", "coude_G", "coude_D",
               "poignet_G", "poignet_D", "genou_G", "genou_D"]

ROTATIONS = {0: None, 90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}
TACHES_COUPE = "Ouvrir rouleau,Couper,Classer,Transporter"
SANS_TACHE = "Non précisée"
DUREE_MIN_S = 20
SAUT_MAX_MS = 500
TRAVAILLE, REPOS = 0.50, 0.25


def ascii(texte):
    return unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()


def telecharger_modele():
    if MODELE.exists():
        return
    print("Téléchargement du modèle MediaPipe (environ 9 Mo)...")
    try:
        urllib.request.urlretrieve(URL_MODELE, MODELE)
        print("Modèle téléchargé ✔")
    except Exception as e:
        print(f"\n❌ Téléchargement impossible : {e}")
        print("Télécharge ce fichier à la main et place-le à côté de ergoscan.py :")
        print(f"   {URL_MODELE}")
        sys.exit(1)


def creer_detecteur(nb_personnes=1):
    options = vision.PoseLandmarkerOptions(
        base_options=mp_tasks.BaseOptions(model_asset_path=str(MODELE)),
        running_mode=vision.RunningMode.VIDEO,
        num_poses=nb_personnes,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    return vision.PoseLandmarker.create_from_options(options)


def ouvrir_source(source):
    if source.isdigit():
        cap = cv2.VideoCapture(int(source), cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY)
        est_webcam = True
    else:
        if not Path(source).exists():
            print(f"❌ Fichier introuvable : « {source} ». Mets la vidéo dans le dossier du projet.")
            sys.exit(1)
        cap = cv2.VideoCapture(source)
        est_webcam = False
    if not cap.isOpened():
        print(f"❌ Impossible d'ouvrir « {source} ».")
        if not est_webcam:
            print("   Vidéo d'iPhone ? Réglages → Appareil photo → Formats → « Le plus compatible ».")
        sys.exit(1)
    return cap, est_webcam


def zone_utile(cap, n_images=30, seuil=16):
    position = cap.get(cv2.CAP_PROP_POS_FRAMES)
    maxi = None
    for _ in range(n_images):
        ok, img = cap.read()
        if not ok:
            break
        gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        maxi = gris if maxi is None else np.maximum(maxi, gris)
    cap.set(cv2.CAP_PROP_POS_FRAMES, position)
    if maxi is None:
        return None
    h, w = maxi.shape
    cols = np.where(maxi.max(axis=0) > seuil)[0]
    lignes = np.where(maxi.max(axis=1) > seuil)[0]
    if len(cols) == 0 or len(lignes) == 0:
        return None
    x0, x1, y0, y1 = int(cols[0]), int(cols[-1]) + 1, int(lignes[0]), int(lignes[-1]) + 1
    if (x1 - x0) > 0.95 * w and (y1 - y0) > 0.95 * h:
        return None
    return x0, y0, x1, y1


def lire_taches(texte):
    taches = [t.strip() for t in texte.split(",") if t.strip()]
    if not 1 <= len(taches) <= 9:
        print("❌ --taches : entre 1 et 9 tâches, séparées par des virgules.")
        sys.exit(1)
    return taches


def lire_charges_taches(texte, taches):
    charges = {}
    if not texte:
        return charges
    for morceau in texte.split(","):
        try:
            num, kg = morceau.split("=")
            num, kg = int(num), float(kg)
            charges[taches[num - 1]] = kg
        except (ValueError, IndexError):
            print(f"❌ --charges-taches : « {morceau} » ne va pas. Exemple : 1=15,4=3 (numéro de tâche = kg)")
            sys.exit(1)
    return charges


def stats_vides():
    return {z: [0, 0, 0] for z in ZONES}


def resumer(stats):
    lignes = {}
    for z in ZONES:
        total = sum(stats[z])
        if total == 0:
            lignes[z] = None
            continue
        v, j, r = (100 * n / total for n in stats[z])
        lignes[z] = {"vert": v, "jaune": j, "rouge": r, "charge": (j * 0.5 + r) / 100}
    return lignes


RAISONS_REJET = {
    "trop_petit": "squelette trop petit (corps écrasé sur un bras ou un objet)",
    "coupe": "épaules ou hanches hors de l'image (corps coupé par le bord)",
    "proportions": "proportions du corps impossibles",
    "saut": "saut brutal d'une image à l'autre",
}


def squelette_plausible(pts, w, h, taille_min=0.35, angles_avant=None, angles=None):
    ys = [p[1] for p in pts[11:29] if p[2] >= 0.3]
    if len(ys) < 6 or (max(ys) - min(ys)) / h < taille_min:
        return "trop_petit"
    hors = sum(1 for i in (11, 12, 23, 24)
               if not (-0.02 * w <= pts[i][0] <= 1.02 * w and -0.02 * h <= pts[i][1] <= 1.02 * h))
    if hors >= 2:
        return "coupe"
    ep = [(pts[i][0], pts[i][1]) for i in (11, 12)]
    ha = [(pts[i][0], pts[i][1]) for i in (23, 24)]
    me = ((ep[0][0] + ep[1][0]) / 2, (ep[0][1] + ep[1][1]) / 2)
    mh = ((ha[0][0] + ha[1][0]) / 2, (ha[0][1] + ha[1][1]) / 2)
    tronc = float(np.hypot(me[0] - mh[0], me[1] - mh[1]))
    if tronc < 0.12 * h:
        return "proportions"
    bras = [float(np.hypot(pts[e][0] - pts[c][0], pts[e][1] - pts[c][1]))
            for e, c in ((11, 13), (12, 14)) if pts[e][2] >= 0.5 and pts[c][2] >= 0.5]
    if bras and not all(0.25 <= b / tronc <= 1.3 for b in bras):
        return "proportions"
    if angles_avant and angles and angles_avant.get("dos") is not None and angles.get("dos") is not None:
        if abs(angles["dos"] - angles_avant["dos"]) > 40:
            return "saut"
    return None


def centre_et_taille(pts, vis_min=0.3):
    ep = [(pts[i][0], pts[i][1]) for i in (11, 12) if pts[i][2] >= vis_min]
    ha = [(pts[i][0], pts[i][1]) for i in (23, 24) if pts[i][2] >= vis_min]
    if not ep and not ha:
        return None
    tous = ep + ha
    cx = sum(p[0] for p in tous) / len(tous)
    cy = sum(p[1] for p in tous) / len(tous)
    if ep and ha:
        me = (sum(p[0] for p in ep) / len(ep), sum(p[1] for p in ep) / len(ep))
        mh = (sum(p[0] for p in ha) / len(ha), sum(p[1] for p in ha) / len(ha))
        taille = float(np.hypot(me[0] - mh[0], me[1] - mh[1]))
    elif len(ep) == 2:
        taille = 2 * float(np.hypot(ep[0][0] - ep[1][0], ep[0][1] - ep[1][1]))
    else:
        taille = None
    return (cx, cy), (taille if taille and taille > 5 else None)


def signature_couleur(frame_bgr, pts, vis_min=0.3):
    if frame_bgr is None:
        return None
    coins = [(pts[i][0], pts[i][1]) for i in (11, 12, 23, 24) if pts[i][2] >= vis_min]
    if len(coins) < 3:
        return None
    xs, ys = [c[0] for c in coins], [c[1] for c in coins]
    h, w = frame_bgr.shape[:2]
    x0, x1 = int(max(0, min(xs))), int(min(w, max(xs)))
    y0, y1 = int(max(0, min(ys))), int(min(h, max(ys)))
    if x1 - x0 < 6 or y1 - y0 < 6:
        return None
    hsv = cv2.cvtColor(frame_bgr[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1, 2], None, [8, 4, 4], [0, 180, 0, 256, 0, 256])
    return cv2.normalize(hist, hist).flatten()


def ecart_couleur(a, b):
    if a is None or b is None:
        return None
    return float(cv2.compareHist(a, b, cv2.HISTCMP_BHATTACHARYYA))


class Suivi:

    ECART_COULEUR_MAX = 0.60
    RAYON_MAX = 1.5

    def __init__(self):
        self.oublier()

    @property
    def choisi(self):
        return self.centre is not None

    def oublier(self):
        self.centre, self.taille, self.perdu, self.couleur = None, None, 0, None

    def selectionner(self, x, y, candidats, frame=None):
        meilleur, d_min = None, None
        for i, pts in enumerate(candidats):
            ct = centre_et_taille(pts)
            if ct is None:
                continue
            vis = [(p[0], p[1]) for p in pts[0:29] if p[2] >= 0.3]
            xs, ys = [p[0] for p in vis], [p[1] for p in vis]
            dedans = xs and min(xs) <= x <= max(xs) and min(ys) <= y <= max(ys)
            d = float(np.hypot(ct[0][0] - x, ct[0][1] - y)) - (1e6 if dedans else 0)
            if d_min is None or d < d_min:
                meilleur, d_min = i, d
        if meilleur is None:
            return False
        (c, t) = centre_et_taille(candidats[meilleur])
        self.centre, self.taille, self.perdu = c, t or 100.0, 0
        self.couleur = signature_couleur(frame, candidats[meilleur])
        return True

    def choisir(self, candidats, frame=None):
        if self.centre is None:
            return None
        rayon = self.taille * min(self.RAYON_MAX, 0.8 + 0.1 * self.perdu)
        meilleur, score_min = None, None
        for i, pts in enumerate(candidats):
            ct = centre_et_taille(pts)
            if ct is None:
                continue
            (c, t) = ct
            if t and not (0.5 <= t / self.taille <= 2.0):
                continue
            d = float(np.hypot(c[0] - self.centre[0], c[1] - self.centre[1]))
            if d > rayon:
                continue
            sig = signature_couleur(frame, pts)
            ec = ecart_couleur(self.couleur, sig)
            if ec is not None and ec > self.ECART_COULEUR_MAX:
                continue
            score = d / rayon + (ec if ec is not None else 0.3)
            if score_min is None or score < score_min:
                meilleur, score_min, c_m, t_m, sig_m = i, score, c, t, sig
        if meilleur is None:
            self.perdu += 1
            return None
        self.centre = c_m
        if t_m:
            self.taille = 0.8 * self.taille + 0.2 * t_m
        if self.couleur is None and sig_m is not None:
            self.couleur = sig_m
        self.perdu = 0
        return meilleur


class Analyseur:
    def __init__(self, detecteur, assis=False, options_reba=None, taches=None, charges_taches=None,
                 suivi=None):
        self.detecteur = detecteur
        self.suivi = suivi
        self.candidats = []
        self.images_ignorees = 0
        self.filtrer = True
        self.taille_min = 0.35
        self.rejets = {k: 0 for k in RAISONS_REJET}
        self.dernier_rejet = None
        self._angles_precedents = None
        self.assis = assis
        self.options_reba = options_reba or OptionsREBA(assis=assis)
        self.taches = taches or []
        self.options_par_tache = {t: replace(self.options_reba, charge_kg=kg)
                                  for t, kg in (charges_taches or {}).items()}
        self.tache = SANS_TACHE
        self.par_tache = {}
        self.scores_reba = []
        self.lisseur = Lisseur(alpha=0.4)
        self.calibration = {"cou": 0.0, "dos": 0.0}
        self.dernier_brut = {}
        self.stats = stats_vides()
        self.mesures = []
        self.dernier_reba = None
        self.dernier_ts = None

    def changer_tache(self, numero):
        if numero == 0:
            self.tache = SANS_TACHE
            return True
        if 1 <= numero <= len(self.taches):
            self.tache = self.taches[numero - 1]
            return True
        return False

    def numero_tache(self):
        return self.taches.index(self.tache) + 1 if self.tache in self.taches else 0

    def _bloc(self, tache):
        if tache not in self.par_tache:
            self.par_tache[tache] = {"stats": stats_vides(), "reba": [], "duree_ms": 0, "images": 0}
        return self.par_tache[tache]

    def stats_affichees(self):
        if self.tache != SANS_TACHE and self.tache in self.par_tache:
            return self.par_tache[self.tache]["stats"]
        return self.stats

    def calibrer(self):
        for k in ("cou", "dos"):
            if self.dernier_brut.get(k) is not None:
                self.calibration[k] = self.dernier_brut[k]
        return self.calibration

    def traiter(self, frame_bgr, horodatage_ms):
        bloc = self._bloc(self.tache)
        if self.dernier_ts is not None:
            bloc["duree_ms"] += min(horodatage_ms - self.dernier_ts, SAUT_MAX_MS)
        self.dernier_ts = horodatage_ms

        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        res = self.detecteur.detect_for_video(image, horodatage_ms)
        self.candidats = [points_en_pixels(lm, w, h) for lm in (res.pose_landmarks or [])]
        if not self.candidats:
            return None, None, None

        if self.suivi is None:
            pts = self.candidats[0]
        else:
            i = self.suivi.choisir(self.candidats, frame_bgr)
            if i is None:
                if self.suivi.choisi:
                    self.images_ignorees += 1
                return None, None, None
            pts = self.candidats[i]

        brut = calculer_angles(pts)
        if self.filtrer:
            avant = None
            if self._angles_precedents and horodatage_ms - self._angles_precedents[0] <= 200:
                avant = self._angles_precedents[1]
            raison = squelette_plausible(pts, w, h, self.taille_min, avant, brut)
            if raison:
                self.rejets[raison] += 1
                self.dernier_rejet = raison
                return None, None, None
            self._angles_precedents = (horodatage_ms, dict(brut))
        self.dernier_rejet = None
        self.dernier_brut = dict(brut)
        for k in ("cou", "dos"):
            if brut[k] is not None:
                brut[k] = max(0.0, brut[k] - self.calibration[k])
        lisse = self.lisseur(brut)
        zones = angles_par_zone(lisse)
        niveaux = {z: niveau(z, zones[z], self.assis) for z in ZONES}

        bloc["images"] += 1
        for z in ZONES:
            if niveaux[z] is not None:
                self.stats[z][niveaux[z]] += 1
                bloc["stats"][z][niveaux[z]] += 1

        reba = calculer_reba(lisse, self.options_par_tache.get(self.tache, self.options_reba))
        if reba:
            self.scores_reba.append(reba["reba"])
            bloc["reba"].append(reba["reba"])
        self.dernier_reba = reba
        self.mesures.append([round(horodatage_ms / 1000, 2), self.tache] +
                            [round(lisse[k], 1) if lisse.get(k) is not None else "" for k in CLES_ANGLES] +
                            [reba["reba"] if reba else ""])
        return pts, zones, niveaux

    def resume(self):
        return resumer(self.stats)


def nom_fichier(poste):
    return "".join(c if c.isalnum() else "_" for c in ascii(poste)).strip("_") or "poste"


def enregistrer(analyseur, poste):
    base = nom_fichier(poste)
    with open(DOSSIER / f"mesures_{base}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["temps_s", "tache"] + CLES_ANGLES + ["reba"])
        w.writerows(analyseur.mesures)

    res = analyseur.resume()
    with open(DOSSIER / f"fiche_{base}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["zone", "pct_vert", "pct_jaune", "pct_rouge", "charge"])
        for z in ZONES:
            r = res[z]
            w.writerow([z] + (["", "", "", ""] if r is None else
                              [f"{r['vert']:.1f}", f"{r['jaune']:.1f}", f"{r['rouge']:.1f}", f"{r['charge']:.2f}"]))

    print(f"\n=== Fiche du poste « {poste} » ({len(analyseur.mesures)} images analysées) ===")
    print(f"{'Zone':<10}{'vert':>8}{'jaune':>8}{'rouge':>8}{'charge':>9}")
    for z in ZONES:
        r = res[z]
        if r is None:
            print(f"{NOMS[z]:<10}{'pas assez visible':>33}")
        else:
            print(f"{NOMS[z]:<10}{r['vert']:7.0f}%{r['jaune']:7.0f}%{r['rouge']:7.0f}%{r['charge']:9.2f}")
    sc = analyseur.scores_reba
    if sc:
        moyen, maxi = sum(sc) / len(sc), max(sc)
        print(f"\n--- Score REBA (Hignett & McAtamney 2000) sur {len(sc)} images ---")
        print(f"  Moyen : {moyen:.1f} ({niveau_reba(round(moyen))[0]})   Maximum : {maxi} ({niveau_reba(maxi)[0]})")
        print(f"  Action recommandée (score moyen) : {niveau_reba(round(moyen))[1]}")
        bas = 0
        with open(DOSSIER / f"reba_{base}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["niveau", "scores", "pct_temps"])
            for haut, nom, _ in NIVEAUX_REBA:
                n = sum(1 for v in sc if bas < v <= haut)
                pct = 100 * n / len(sc)
                print(f"  {nom:<12} ({bas + 1}–{haut}) : {pct:5.1f} % du temps")
                w.writerow([nom, f"{bas + 1}-{haut}", f"{pct:.1f}"])
                bas = haut
            w.writerow([])
            w.writerow(["reba_moyen", f"{moyen:.2f}"])
            w.writerow(["reba_max", maxi])
        print(f"  → reba_{base}.csv")
    ligne = ",".join([poste] + [f"{res[z]['charge']:.2f}" if res[z] else "0.00" for z in ZONES])
    print("\nLigne à copier dans postes.csv du jumeau numérique (poste entier) :")
    print(f"  {ligne}")
    print(f"\nFichiers enregistrés : mesures_{base}.csv et fiche_{base}.csv")

    enregistrer_taches(analyseur, poste, base)


def enregistrer_taches(analyseur, poste, base):
    ordre = [t for t in analyseur.taches if t in analyseur.par_tache]
    if SANS_TACHE in analyseur.par_tache and analyseur.par_tache[SANS_TACHE]["images"] > 0:
        ordre.append(SANS_TACHE)
    mesurees = [t for t in ordre if t != SANS_TACHE and analyseur.par_tache[t]["images"] > 0]
    if not mesurees:
        print("\n(Aucune tâche indiquée pendant l'analyse : appuie sur 1 à 4 la prochaine fois "
              "pour obtenir la fiche par tâche.)")
        return

    duree_totale = sum(analyseur.par_tache[t]["duree_ms"] for t in ordre) or 1
    lignes = []
    for t in ordre:
        b = analyseur.par_tache[t]
        res = resumer(b["stats"])
        sc = b["reba"]
        lignes.append({
            "tache": t,
            "duree_s": b["duree_ms"] / 1000,
            "pct_temps": 100 * b["duree_ms"] / duree_totale,
            "images": b["images"],
            "reba_moyen": sum(sc) / len(sc) if sc else None,
            "reba_max": max(sc) if sc else None,
            "res": res,
        })

    with open(DOSSIER / f"fiche_taches_{base}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["tache", "duree_s", "pct_temps", "images", "reba_moyen", "reba_max", "niveau_reba"] +
                   [f"charge_{z}" for z in ZONES] + [f"pct_rouge_{z}" for z in ZONES])
        for L in lignes:
            rm = L["reba_moyen"]
            w.writerow([L["tache"], f"{L['duree_s']:.1f}", f"{L['pct_temps']:.1f}", L["images"],
                        f"{rm:.2f}" if rm is not None else "", L["reba_max"] if L["reba_max"] else "",
                        niveau_reba(round(rm))[0] if rm is not None else ""] +
                       [f"{L['res'][z]['charge']:.2f}" if L["res"][z] else "" for z in ZONES] +
                       [f"{L['res'][z]['rouge']:.1f}" if L["res"][z] else "" for z in ZONES])

    with open(DOSSIER / f"postes_taches_{base}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["poste"] + ZONES)
        for L in lignes:
            if L["tache"] == SANS_TACHE:
                continue
            w.writerow([L["tache"]] + [f"{L['res'][z]['charge']:.2f}" if L["res"][z] else "0.00" for z in ZONES])

    abr = {"cou": "Cou", "epaules": "Epa", "coudes": "Cde", "poignets": "Poi", "dos": "Dos", "genoux": "Gen"}
    print(f"\n=== Par tâche ({len(mesurees)} tâche(s) mesurée(s)) ===")
    print(f"{'Tâche':<16}{'durée':>7}{'temps':>7}{'REBA moy':>10}{'max':>5}  |  charge par zone : " +
          " ".join(f"{abr[z]:>4}" for z in ZONES))
    for L in lignes:
        rm = f"{L['reba_moyen']:.1f}" if L["reba_moyen"] is not None else "–"
        rx = str(L["reba_max"]) if L["reba_max"] else "–"
        charges = " ".join(f"{L['res'][z]['charge']:4.2f}" if L["res"][z] else "   –" for z in ZONES)
        print(f"{L['tache'][:15]:<16}{L['duree_s']:6.0f}s{L['pct_temps']:6.0f}%{rm:>10}{rx:>5}  |  "
              f"{'':18}{charges}")

    print("\nQuelles zones travaillent et lesquelles se reposent, tâche par tâche :")
    for L in lignes:
        if L["tache"] == SANS_TACHE:
            continue
        res = L["res"]
        travaille = [NOMS[z] for z in ZONES if res[z] and res[z]["charge"] >= TRAVAILLE]
        repos = [NOMS[z] for z in ZONES if res[z] and res[z]["charge"] < REPOS]
        print(f"  {L['tache']:<16} travaillent : {', '.join(travaille) or '—':<30} se reposent : "
              f"{', '.join(repos) or '—'}")

    if len(mesurees) < 2:
        print("\nAlternances : une seule tâche mesurée → impossible de comparer. Mesure au moins une autre "
              "tâche (touches 1 à 4) pour savoir si l'alternance repose des zones différentes.")
        lignes_alternance = []
    else:
        lignes_alternance = lignes
    print("\nAlternances utiles (la 2e tâche repose une zone que la 1re charge) :" if lignes_alternance else "")
    utiles = 0
    for a in lignes_alternance:
        for b in lignes_alternance:
            if a is b or SANS_TACHE in (a["tache"], b["tache"]):
                continue
            zones = [NOMS[z] for z in ZONES if a["res"][z] and b["res"][z]
                     and a["res"][z]["charge"] >= TRAVAILLE and b["res"][z]["charge"] < REPOS]
            if zones:
                utiles += 1
                print(f"  {a['tache']} → {b['tache']} : repose {', '.join(zones)}")
    if lignes_alternance and not utiles:
        print("  aucune avec les mesures actuelles : les tâches chargent les mêmes zones → il faut corriger le poste.")

    for L in lignes:
        if L["tache"] != SANS_TACHE and round(L["duree_s"]) < DUREE_MIN_S:
            print(f"⚠️  « {L['tache']} » : seulement {L['duree_s']:.0f} s mesurées — "
                  f"filme au moins {DUREE_MIN_S} s pour une valeur fiable.")
    print(f"\nFichiers enregistrés : fiche_taches_{base}.csv et postes_taches_{base}.csv")
    print(f"→ Copie les lignes de postes_taches_{base}.csv dans ergotwin/postes.csv "
          f"pour remplacer les charges supposées du jumeau Ouvrier.")
    print("  (0.00 = zone non visible dans la vidéo, pas forcément au repos : à vérifier.)")


def main():
    parser = argparse.ArgumentParser(description="ErgoScan : analyse de posture")
    parser.add_argument("--source", default="0", help="vidéo (ex. couture.mp4) ou numéro de webcam (0, 1...)")
    parser.add_argument("--poste", default="Poste test", help="nom du poste analysé")
    parser.add_argument("--assis", action="store_true", help="poste assis : genoux non comptés à risque")
    parser.add_argument("--largeur", type=int, default=960, help="largeur maximale de l'image en pixels")
    parser.add_argument("--rotation", type=int, default=0, choices=list(ROTATIONS),
                        help="redresser une vidéo couchée : 90 (horaire), 270 (anti-horaire) ou 180")
    parser.add_argument("--palette", default=PALETTE_PAR_DEFAUT, choices=list(PALETTES),
                        help="couleurs de l'interface")
    parser.add_argument("--sans-filtre", action="store_true",
                        help="garder tous les squelettes, même douteux (trop petits, coupés, impossibles)")
    parser.add_argument("--taille-min", type=float, default=0.35,
                        help="hauteur minimale du corps dans l'image (0.35 = 35 %%) ; baisser si on filme de loin")
    parser.add_argument("--sans-recadrage", action="store_true",
                        help="ne pas enlever automatiquement les bandes noires de la vidéo")
    s = parser.add_argument_group("plusieurs personnes dans l'image")
    s.add_argument("--suivre", action="store_true",
                   help="au début, clique sur la personne à analyser : ErgoScan ne suit qu'elle")
    s.add_argument("--cible", default="",
                   help="choisir la personne sans cliquer : position dans l'image, ex. 0.55,0.40 "
                        "(0,0 = coin en haut à gauche ; 1,1 = coin en bas à droite)")
    t = parser.add_argument_group("mesure tâche par tâche")
    t.add_argument("--taches", default=TACHES_COUPE,
                   help="noms des tâches, séparés par des virgules (touches 1, 2, 3...)")
    t.add_argument("--tache-initiale", type=int, default=0, help="tâche active au démarrage (0 = non précisée)")
    t.add_argument("--charges-taches", default="",
                   help="charge propre à certaines tâches, ex. 1=15,4=3 (numéro de tâche = kg)")
    g = parser.add_argument_group("options REBA (ce que la caméra ne voit pas)")
    g.add_argument("--charge-kg", type=float, default=0.0, help="charge manipulée en kg")
    g.add_argument("--choc", action="store_true", help="effort brusque ou choc")
    g.add_argument("--prise", default="bonne", choices=list(PRISES), help="qualité de la prise")
    g.add_argument("--appui-instable", action="store_true", help="debout sur une jambe ou appui instable")
    for nom in ["torsion-tronc", "torsion-cou", "epaule-haussee", "bras-ecarte", "bras-soutenu",
                "poignet-devie", "statique", "repetitif", "instable"]:
        g.add_argument(f"--{nom}", action="store_true")
    args = parser.parse_args()
    appliquer_palette(args.palette)
    options_reba = OptionsREBA(
        assis=args.assis, appui_instable=args.appui_instable, charge_kg=args.charge_kg, choc=args.choc,
        prise=args.prise, torsion_tronc=args.torsion_tronc, torsion_cou=args.torsion_cou,
        epaule_haussee=args.epaule_haussee, bras_ecarte=args.bras_ecarte, bras_soutenu=args.bras_soutenu,
        poignet_devie=args.poignet_devie, statique=args.statique, repetitif=args.repetitif,
        instable=args.instable)
    taches = lire_taches(args.taches)
    charges_taches = lire_charges_taches(args.charges_taches, taches)

    telecharger_modele()
    cap, est_webcam = ouvrir_source(args.source)
    fps_video = cap.get(cv2.CAP_PROP_FPS) or 30
    cadre = None if (est_webcam or args.sans_recadrage) else zone_utile(cap)
    if cadre:
        print(f"Bandes noires enlevées : on garde la zone {cadre[2] - cadre[0]}×{cadre[3] - cadre[1]} px "
              f"(option --sans-recadrage pour l'éviter).")
    cible = None
    if args.cible:
        try:
            cible = tuple(float(v) for v in args.cible.split(","))
            assert len(cible) == 2 and all(0 <= v <= 1 for v in cible)
        except (ValueError, AssertionError):
            print("❌ --cible : deux nombres entre 0 et 1, ex. 0.55,0.40")
            sys.exit(1)
    suivi = Suivi() if (args.suivre or cible) else None
    analyseur = Analyseur(creer_detecteur(4 if suivi else 1), assis=args.assis, options_reba=options_reba,
                          taches=taches, charges_taches=charges_taches, suivi=suivi)
    analyseur.changer_tache(args.tache_initiale)
    analyseur.filtrer = not args.sans_filtre
    analyseur.taille_min = args.taille_min

    print("Tâches : " + "   ".join(f"{i} = {nom}" for i, nom in enumerate(taches, 1)) + "   0 = non précisée")

    cv2.namedWindow(TITRE, cv2.WINDOW_NORMAL)
    clic = {}

    def souris(evenement, x, y, *_):
        if evenement == cv2.EVENT_LBUTTONDOWN:
            clic["xy"] = (x, y)
    cv2.setMouseCallback(TITRE, souris)
    taille_fenetre_reglee = False

    mode_video, pause, details = True, False, False
    message, fin_message = "Appuie sur c quand la personne se tient droite", time.time() + 6
    n_image, dernier_ts = 0, -1
    debut, t_fps, n_fps, fps = time.time(), time.time(), 0, 0.0
    pts = zones = niveaux = None
    frame = None

    while True:
        if not pause:
            ok, lu = cap.read()
            if not ok:
                break
            if cadre:
                x0, y0, x1, y1 = cadre
                lu = lu[y0:y1, x0:x1]
            if ROTATIONS[args.rotation] is not None:
                lu = cv2.rotate(lu, ROTATIONS[args.rotation])
            if est_webcam:
                lu = cv2.flip(lu, 1)
            if lu.shape[1] > args.largeur:
                e = args.largeur / lu.shape[1]
                lu = cv2.resize(lu, None, fx=e, fy=e, interpolation=cv2.INTER_AREA)
            frame = lu

            ts = int((time.time() - debut) * 1000) if est_webcam else int(n_image * 1000 / fps_video)
            ts = max(ts, dernier_ts + 1)
            dernier_ts = ts
            n_image += 1
            pts, zones, niveaux = analyseur.traiter(frame, ts)

            n_fps += 1
            if time.time() - t_fps >= 1:
                fps, n_fps, t_fps = n_fps / (time.time() - t_fps), 0, time.time()

        if frame is None:
            continue

        invite = None
        if suivi is not None and not suivi.choisi:
            if analyseur.candidats:
                if cible:
                    hh, ww = frame.shape[:2]
                    suivi.selectionner(cible[0] * ww, cible[1] * hh, analyseur.candidats, frame)
                elif "xy" in clic:
                    if suivi.selectionner(*clic.pop("xy"), analyseur.candidats, frame):
                        message, fin_message = "Personne choisie : seule elle est analysée", time.time() + 3
                if suivi.choisi:
                    pause = False
                    analyseur.lisseur = Lisseur(alpha=0.4)
                    pts, zones, niveaux = None, None, None
                else:
                    pause = True
                    invite = f"Clique sur le coupeur ({len(analyseur.candidats)} personne(s) détectée(s))"
            clic.pop("xy", None)
        elif pts is None and analyseur.dernier_rejet:
            invite = "Squelette douteux écarté : " + RAISONS_REJET[analyseur.dernier_rejet]
        elif suivi is not None and pts is None and analyseur.candidats:
            invite = "Coupeur caché ou sorti du cadre — image ignorée (s pour re-choisir)"

        fond = frame.copy() if mode_video else np.full_like(frame, fond_squelette_bgr())
        if suivi is not None and not suivi.choisi:
            for c in analyseur.candidats:
                dessiner_squelette(fond, c, {}, CONNEXIONS)
        if pts:
            dessiner_squelette(fond, pts, niveaux, CONNEXIONS)
        tache = analyseur.tache if analyseur.tache != SANS_TACHE else None
        vue = composer(fond, pts=pts, zones=zones, niveaux=niveaux, stats=analyseur.stats_affichees(),
                       poste=args.poste, debut=debut, fps=fps,
                       message=message if time.time() < fin_message else "",
                       details=details, en_pause=pause,
                       reba=analyseur.dernier_reba if pts else None,
                       tache=tache, num_tache=analyseur.numero_tache(), n_taches=len(taches),
                       invite=invite, suivi=suivi is not None)

        if not taille_fenetre_reglee:
            h, w = vue.shape[:2]
            e = min(1.0, 1280 / w, 720 / h)
            cv2.resizeWindow(TITRE, int(w * e), int(h * e))
            taille_fenetre_reglee = True
        cv2.imshow(TITRE, vue)

        touche = cv2.waitKey(1 if not pause else 50) & 0xFF
        if touche == ord("q"):
            break
        elif ord("0") <= touche <= ord("9"):
            if analyseur.changer_tache(touche - ord("0")):
                message, fin_message = f"Tâche : {analyseur.tache}", time.time() + 2
            else:
                message, fin_message = f"Pas de tâche n°{touche - ord('0')}", time.time() + 2
        elif touche == ord("c"):
            cal = analyseur.calibrer()
            message, fin_message = f"Calibré : cou {cal['cou']:.0f}°, dos {cal['dos']:.0f}°", time.time() + 3
        elif touche == ord("s") and suivi is not None:
            suivi.oublier()
            cible = None
            message, fin_message = "Clique sur la personne à analyser", time.time() + 3
        elif touche == ord("v"):
            mode_video = not mode_video
        elif touche == ord("i"):
            details = not details
        elif touche == ord("p"):
            pause = not pause
        if cv2.getWindowProperty(TITRE, cv2.WND_PROP_VISIBLE) < 1:
            break

    cap.release()
    cv2.destroyAllWindows()
    total_rejets = sum(analyseur.rejets.values())
    if total_rejets:
        total = total_rejets + len(analyseur.mesures)
        print(f"\nFiltre qualité : {total_rejets} squelette(s) douteux écarté(s) sur {total} "
              f"({100 * total_rejets / total:.0f} %) :")
        for k, n in analyseur.rejets.items():
            if n:
                print(f"  - {n:4d} × {RAISONS_REJET[k]}")
        print("  (option --sans-filtre pour tout garder, --taille-min 0.25 si la personne est filmée de loin)")
    if suivi is not None and analyseur.images_ignorees:
        total = analyseur.images_ignorees + len(analyseur.mesures)
        print(f"\nSuivi : {analyseur.images_ignorees} image(s) ignorée(s) sur {total} "
              f"({100 * analyseur.images_ignorees / total:.0f} %) — coupeur caché ou hors du cadre.")
    if analyseur.mesures:
        enregistrer(analyseur, args.poste)
    else:
        print("Aucune personne détectée : rien à enregistrer.")


if __name__ == "__main__":
    main()
