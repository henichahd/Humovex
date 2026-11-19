import argparse
import csv
from collections import defaultdict
from pathlib import Path

from angles import ZONES, NOMS, niveau, VERT, JAUNE, ROUGE
from reba import OptionsREBA, calculer_reba, niveau_reba

DOSSIER = Path(__file__).parent
POIDS = {VERT: 0.0, JAUNE: 0.5, ROUGE: 1.0}


def angles_reba(ligne):
    a = {"cou": float(ligne["cou"]), "dos": float(ligne["dos"])}
    for cle, col in [("epaule", "epaules"), ("coude", "coudes"), ("poignet", "poignets"), ("genou", "genoux")]:
        a[f"{cle}_G"] = a[f"{cle}_D"] = float(ligne[col])
    return a


def estimer(chemin):
    with open(chemin, encoding="utf-8") as f:
        lignes = list(csv.DictReader(f))

    taches = defaultdict(list)
    for L in lignes:
        taches[L["tache"]].append(L)

    resultats = {}
    for tache, postures in taches.items():
        total = sum(float(p["pct_temps"]) for p in postures)
        charges = {z: 0.0 for z in ZONES}
        reba_moyen, reba_max = 0.0, 0
        for p in postures:
            part = float(p["pct_temps"]) / total
            zones = {"cou": float(p["cou"]), "dos": float(p["dos"]), "epaules": float(p["epaules"]),
                     "coudes": float(p["coudes"]), "poignets": float(p["poignets"]), "genoux": float(p["genoux"])}
            for z in ZONES:
                charges[z] += part * POIDS[niveau(z, zones[z])]
            options = OptionsREBA(charge_kg=float(p["charge_kg"] or 0),
                                  repetitif=p["repetitif"].strip().lower() == "oui")
            r = calculer_reba(angles_reba(p), options)["reba"]
            reba_moyen += part * r
            reba_max = max(reba_max, r)
        resultats[tache] = {"charges": charges, "reba_moyen": reba_moyen, "reba_max": reba_max,
                            "postures": len(postures)}
    return resultats


def main():
    parser = argparse.ArgumentParser(description="Charges estimées des tâches sans vidéo")
    parser.add_argument("--fichier", default=str(DOSSIER / "taches_estimees.csv"))
    args = parser.parse_args()

    res = estimer(args.fichier)
    abr = {"cou": "Cou", "epaules": "Epa", "coudes": "Cde", "poignets": "Poi", "dos": "Dos", "genoux": "Gen"}
    print("=== Charges ESTIMÉES (postures décrites dans le fichier, calculs identiques à ErgoScan) ===")
    print(f"{'Tâche':<16}{'REBA moy':>9}{'max':>5}  |  " + " ".join(f"{abr[z]:>4}" for z in ZONES))
    for t, r in res.items():
        print(f"{t:<16}{r['reba_moyen']:9.1f}{r['reba_max']:5d}  |  " +
              " ".join(f"{r['charges'][z]:4.2f}" for z in ZONES) + f"   ({niveau_reba(round(r['reba_moyen']))[0]})")

    print("\nLignes pour ergotwin/postes.csv (marquées « estimé ») :")
    for t, r in res.items():
        print(f"  {t} (estimé)," + ",".join(f"{r['charges'][z]:.2f}" for z in ZONES))
    print("\n⚠️ Estimations : à remplacer par la mesure ErgoScan dès qu'une vidéo de la tâche existe.")


if __name__ == "__main__":
    main()
