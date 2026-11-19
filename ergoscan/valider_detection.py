import argparse
import csv
from pathlib import Path

import cv2
import numpy as np

import ergoscan as es
from affichage import dessiner_squelette, fond_squelette_bgr, appliquer_palette

POINTS = {
    "Oreille": (7, 8), "Épaule": (11, 12), "Coude": (13, 14), "Poignet": (15, 16), "Index": (19, 20),
    "Hanche": (23, 24), "Genou": (25, 26), "Cheville": (27, 28),
}
ANGLES_SUIVIS = ["cou", "dos", "epaule_G", "epaule_D", "coude_G", "coude_D", "genou_G", "genou_D"]


def longueur(pts, a, b):
    return float(np.hypot(pts[a][0] - pts[b][0], pts[a][1] - pts[b][1]))


def verdict(ok):
    return "✅" if ok else "⚠️"


def main():
    parser = argparse.ArgumentParser(description="Validation de la détection MediaPipe")
    parser.add_argument("--source", required=True)
    parser.add_argument("--rotation", type=int, default=0, choices=list(es.ROTATIONS))
    parser.add_argument("--taille-min", type=float, default=0.35)
    parser.add_argument("--vignettes", type=int, default=8, help="nombre d'images sur la planche")
    parser.add_argument("--superposer", action="store_true",
                        help="dessiner le squelette SUR la vidéo (seulement si les visages sont déjà floutés)")
    args = parser.parse_args()

    es.telecharger_modele()
    appliquer_palette()
    cap, _ = es.ouvrir_source(args.source)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cadre = es.zone_utile(cap)
    a = es.Analyseur(es.creer_detecteur(1))
    a.taille_min = args.taille_min

    vis = {nom: [] for nom in POINTS}
    rapports = {"Bras / tronc": [], "Avant-bras / tronc": [], "Cuisse / tronc": [], "Jambe / tronc": []}
    angles_prec, sauts = None, {k: [] for k in ANGLES_SUIVIS}
    sans_personne, n, gardees = 0, 0, []
    pas_vignette = max(1, total // args.vignettes)

    while True:
        ok, img = cap.read()
        if not ok:
            break
        if cadre:
            x0, y0, x1, y1 = cadre
            img = img[y0:y1, x0:x1]
        if es.ROTATIONS[args.rotation] is not None:
            img = cv2.rotate(img, es.ROTATIONS[args.rotation])
        if img.shape[1] > 960:
            e = 960 / img.shape[1]
            img = cv2.resize(img, None, fx=e, fy=e, interpolation=cv2.INTER_AREA)
        pts, zones, niveaux = a.traiter(img, int(n * 1000 / fps))
        if not a.candidats:
            sans_personne += 1
        if pts:
            for nom, (g, d) in POINTS.items():
                vis[nom].append(max(pts[g][2], pts[d][2]))
            s = 0 if pts[11][2] + pts[13][2] + pts[23][2] >= pts[12][2] + pts[14][2] + pts[24][2] else 1
            e_, c_, p_, h_, g_, ch_ = (11 + s, 13 + s, 15 + s, 23 + s, 25 + s, 27 + s)
            tronc = longueur(pts, e_, h_)
            if tronc > 0 and min(pts[i][2] for i in (e_, c_, p_, h_, g_, ch_)) >= 0.5:
                rapports["Bras / tronc"].append(longueur(pts, e_, c_) / tronc)
                rapports["Avant-bras / tronc"].append(longueur(pts, c_, p_) / tronc)
                rapports["Cuisse / tronc"].append(longueur(pts, h_, g_) / tronc)
                rapports["Jambe / tronc"].append(longueur(pts, g_, ch_) / tronc)
            brut = a.dernier_brut
            if angles_prec is not None:
                for k in ANGLES_SUIVIS:
                    if brut.get(k) is not None and angles_prec.get(k) is not None:
                        sauts[k].append(abs(brut[k] - angles_prec[k]))
            angles_prec = dict(brut)
            if n % pas_vignette == 0 and len(gardees) < args.vignettes:
                fond = img.copy() if args.superposer else np.full_like(img, fond_squelette_bgr())
                dessiner_squelette(fond, pts, niveaux, es.CONNEXIONS)
                cv2.putText(fond, f"{n / fps:.1f} s", (12, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (60, 52, 44), 3)
                gardees.append(cv2.resize(fond, (240, int(240 * img.shape[0] / img.shape[1]))))
        else:
            angles_prec = None
        n += 1

    base = es.nom_fichier(Path(args.source).stem)
    acceptees = len(a.mesures)
    rejets = sum(a.rejets.values())
    print(f"\n=== Validation de la détection : {args.source} ({n} images, {n / fps:.0f} s) ===")
    print(f"1. DÉTECTION   personne trouvée sur {100 * (n - sans_personne) / n:.0f} % des images ; "
          f"squelette accepté par le filtre sur {100 * acceptees / n:.0f} % "
          f"({rejets} écartés : gros plans, corps coupé…)")

    lignes_csv = []
    print("\n2. CONFIANCE   visibilité moyenne de chaque point (1 = certain), sur les images acceptées :")
    for nom, v in vis.items():
        if v:
            m, part = float(np.mean(v)), 100 * float(np.mean(np.array(v) >= 0.5))
            print(f"   {verdict(m >= 0.8)} {nom:<9} {m:.2f}   (fiable ≥ 0,5 sur {part:.0f} % des images)")
            lignes_csv.append(["confiance", nom, f"{m:.3f}", f"{part:.1f}"])

    print("\n3. OS CONSTANTS   variation de la longueur des os (coefficient de variation, plus c'est bas mieux c'est) :")
    for nom, r in rapports.items():
        if len(r) > 10:
            cv = 100 * float(np.std(r) / np.mean(r))
            print(f"   {verdict(cv <= 15)} {nom:<19} rapport moyen {np.mean(r):.2f}   variation {cv:4.1f} %")
            lignes_csv.append(["os", nom, f"{np.mean(r):.3f}", f"{cv:.1f}"])

    print("   (en 2D, un membre qui pointe vers la caméra paraît plus court : une partie de la variation est réelle,\n"
          "    pas une erreur ; caméra tenue à la main qui change d'angle → variation plus forte)")

    print("\n4. STABILITÉ   variation d'un angle entre deux images consécutives (1/30 s), en degrés :")
    for k, s in sauts.items():
        if s:
            med, p95 = float(np.median(s)), float(np.percentile(s, 95))
            print(f"   {verdict(med <= 3)} {k:<10} médiane {med:4.1f}°   95 % des cas sous {p95:4.1f}°")
            lignes_csv.append(["stabilite", k, f"{med:.2f}", f"{p95:.2f}"])

    print("\nRepère : la littérature donne environ 6° d'erreur pour MediaPipe en vue de profil ; "
          "les seuils REBA vont par tranches de 15 à 25°.")

    with open(es.DOSSIER / f"validation_{base}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["test", "element", "valeur", "complement"])
        w.writerows(lignes_csv)
    if gardees:
        h = max(g.shape[0] for g in gardees)
        gardees = [cv2.copyMakeBorder(g, 0, h - g.shape[0], 0, 4, cv2.BORDER_CONSTANT, value=(255, 255, 255))
                   for g in gardees]
        cv2.imwrite(str(es.DOSSIER / f"validation_{base}.png"), np.hstack(gardees))
    genre = "squelette sur la vidéo" if args.superposer else "squelette seul, sans visage"
    print(f"\nFichiers : validation_{base}.png ({genre}) et validation_{base}.csv")


if __name__ == "__main__":
    main()
