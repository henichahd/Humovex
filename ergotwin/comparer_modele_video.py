import argparse
import csv
import statistics as st

from jumeau_poste import ReglagesPoste, evaluer


def classe_dos(a):
    return 1 if a <= 5 else 2 if a <= 20 else 3 if a <= 60 else 4


def classe_bras(a):
    return 1 if a <= 20 else 2 if a <= 45 else 3 if a <= 90 else 4


def courbe_modele(taille, hauteur_table, distance_table, hauteur_main, allonge=0.98):
    pts = []
    for d in range(5, 89):
        e = evaluer(ReglagesPoste(taille=taille, position="debout", objet="piece", hauteur_table=hauteur_table,
                                  distance_table=distance_table, profondeur_travail=float(d),
                                  hauteur_travail=hauteur_main, allonge=allonge))
        pts.append((d, e["zones"]["epaules"], e["zones"]["dos"], e["zones"]["coudes"]))
    return pts


def main():
    parser = argparse.ArgumentParser(description="Avatar ↔ vidéo réelle")
    parser.add_argument("--mesures", required=True, help="mesures_<poste>.csv produit par ergoscan.py")
    parser.add_argument("--debut", type=float, default=0.0)
    parser.add_argument("--fin", type=float, default=12.0)
    parser.add_argument("--taille", type=float, default=170.0, help="taille du coupeur (cm), inconnue → 170")
    parser.add_argument("--hauteur-table", type=float, default=95.0)
    parser.add_argument("--distance-table", type=float, default=5.0)
    parser.add_argument("--hauteur-main", type=float, default=1.0)
    parser.add_argument("--allonge", type=float, default=0.98,
                        help="part du bras tendu avant de se pencher (paramètre de l'avatar à calibrer)")
    parser.add_argument("--calibrer", action="store_true",
                        help="chercher l'allonge qui colle le mieux à la vidéo (écart du dos le plus petit)")
    args = parser.parse_args()

    with open(args.mesures, encoding="utf-8") as f:
        mesures = [r for r in csv.DictReader(f) if args.debut <= float(r["temps_s"]) <= args.fin]

    if args.calibrer:
        print("Calibration de l'allonge (écart absolu moyen sur le dos, images où le bras est tendu > 20°) :")
        meilleur = None
        for allonge in [0.80, 0.85, 0.90, 0.92, 0.94, 0.96, 0.98, 1.00]:
            m = courbe_modele(args.taille, args.hauteur_table, args.distance_table, args.hauteur_main, allonge)
            e = []
            for r in mesures:
                ep = max([float(r[c]) for c in ("epaule_G", "epaule_D") if r.get(c)] or [-1])
                if ep > 20 and r.get("dos") and min(x[1] for x in m) <= ep <= max(x[1] for x in m):
                    e.append(abs(min(m, key=lambda x: abs(x[1] - ep))[2] - float(r["dos"])))
            if e:
                print(f"   allonge {allonge:.2f} → écart moyen du dos {st.mean(e):5.1f}° ({len(e)} images)")
                if meilleur is None or st.mean(e) < meilleur[1]:
                    meilleur = (allonge, st.mean(e))
        print(f"→ meilleure allonge : {meilleur[0]:.2f}\n")
        args.allonge = meilleur[0]
    modele = courbe_modele(args.taille, args.hauteur_table, args.distance_table, args.hauteur_main, args.allonge)
    ep_min, ep_max = min(m[1] for m in modele), max(m[1] for m in modele)

    def val(r, *cles):
        v = [float(r[c]) for c in cles if r.get(c)]
        return max(v) if v else None

    ecarts_dos, ecarts_coude, meme_dos, meme_bras, n, hors = [], [], 0, 0, 0, 0
    paires = []
    for r in mesures:
        ep, dos = val(r, "epaule_G", "epaule_D"), val(r, "dos")
        coude = val(r, "coude_G", "coude_D")
        if ep is None or dos is None:
            continue
        if not (ep_min <= ep <= ep_max):
            hors += 1
            continue
        d, ep_m, dos_m, coude_m = min(modele, key=lambda m: abs(m[1] - ep))
        n += 1
        ecarts_dos.append(dos_m - dos)
        meme_dos += classe_dos(dos_m) == classe_dos(dos)
        meme_bras += classe_bras(ep_m) == classe_bras(ep)
        if coude is not None:
            ecarts_coude.append(coude_m - coude)
        paires.append((ep, dos, dos_m, d))

    if not n:
        print("Aucune image comparable.")
        return
    abs_dos = [abs(e) for e in ecarts_dos]
    print(f"=== Avatar ↔ vidéo réelle : {n} images de {args.debut:.0f} à {args.fin:.0f} s "
          f"(coupeur supposé de {args.taille:.0f} cm, table {args.hauteur_table:.0f} cm, allonge {args.allonge:.2f}) ===")
    print(f"DOS   : écart moyen avatar − réel {st.mean(ecarts_dos):+.1f}° ; écart absolu médian {st.median(abs_dos):.1f}° ; "
          f"90 % des images sous {sorted(abs_dos)[int(0.9 * n) - 1]:.1f}°")
    print(f"        même tranche REBA du tronc sur {100 * meme_dos / n:.0f} % des images")
    if ecarts_coude:
        print(f"COUDE : écart absolu médian {st.median([abs(e) for e in ecarts_coude]):.1f}°")
    if hors:
        print(f"({hors} image(s) ignorée(s) : épaule hors de ce que l'avatar peut faire en atteignant la table)")

    print("\nDétail par tranche de bras tendu :")
    print(f"{'Épaule mesurée':<16}{'images':>7}{'dos réel':>10}{'dos avatar':>12}")
    for lo, hi in [(0, 20), (20, 35), (35, 50), (50, 70), (70, 180)]:
        g = [p for p in paires if lo <= p[0] < hi]
        if g:
            print(f"{lo:3d}–{hi:<3d}°{'':8}{len(g):7d}{st.median(p[1] for p in g):9.0f}°{st.median(p[2] for p in g):11.0f}°")
    print("\nLecture : un écart de quelques degrés, inférieur aux tranches REBA (15 à 40°), rend l'avatar crédible "
          "pour simuler la coupe ; un écart systématique dit dans quel sens il se trompe.")


if __name__ == "__main__":
    main()
