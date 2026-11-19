import argparse
from dataclasses import dataclass, field, replace

import plotly.graph_objects as go

from jumeau_poste import ReglagesPoste, evaluer, figure_poste, VERT, JAUNE, ROUGE
from reba import OptionsREBA, niveau_reba

ZONES = ["cou", "epaules", "coudes", "poignets", "dos", "genoux"]
POIDS = {VERT: 0.0, JAUNE: 0.5, ROUGE: 1.0}
TABLE = 95.0
PROF_TABLE = 88.0


@dataclass
class Phase:
    nom: str
    duree: float
    d0: float
    d1: float
    aller_retour: bool = False
    hauteur: float = TABLE
    profondeur: float = PROF_TABLE
    sur_table_de_coupe: bool = True
    main: float = 1.0
    inclinaison: float = 0.0
    charge_kg: float = 0.0
    coupe: bool = False
    regarde_mains: bool = True


@dataclass
class Scenario:
    tache: str
    nom: str
    phases: list
    hypotheses: str = ""

    @property
    def duree(self):
        return sum(p.duree for p in self.phases)

    @property
    def libelle(self):
        return f"{self.tache} – {self.nom}"


ROULEAU_KG = 12.0
PAQUET_KG = 2.5
CHARIOT_BAS = 50.0
HAUTE = 105.0
CISEAU_KG = 0.75

SCENARIOS = {
    "Couper": {
        "actuel": Scenario("Couper", "actuel", [
            Phase("Étaler le tissu", 6, 20, 60, aller_retour=True),
            Phase("Couper (bord → fond)", 12, 10, 85, main=10, coupe=True, charge_kg=CISEAU_KG),
            Phase("Revenir au bord", 4, 85, 10, main=10, coupe=True, charge_kg=CISEAU_KG),
        ], "table 95 × 88 cm, accès d'un seul côté : il coupe jusqu'au fond"),
        "amélioré": Scenario("Couper", "accès 2 côtés", [
            Phase("Étaler le tissu", 6, 20, 44, aller_retour=True),
            Phase("Couper (bord → milieu)", 12, 10, 44, main=10, coupe=True, charge_kg=CISEAU_KG),
            Phase("Revenir au bord", 4, 44, 10, main=10, coupe=True, charge_kg=CISEAU_KG),
        ], "table accessible des deux côtés : il ne dépasse jamais le milieu (44 cm)"),
        "table moins profonde": Scenario("Couper", "table moins profonde", [
            Phase("Étaler le tissu", 6, 20, 55, aller_retour=True, profondeur=60),
            Phase("Couper (bord → fond)", 12, 10, 55, main=10, coupe=True, charge_kg=CISEAU_KG, profondeur=60),
            Phase("Revenir au bord", 4, 55, 10, main=10, coupe=True, charge_kg=CISEAU_KG, profondeur=60),
        ], "table de 60 cm de profondeur au lieu de 88 (si la largeur du matelas de tissu le permet)"),
        "table plus haute": Scenario("Couper", "table plus haute", [
            Phase("Étaler le tissu", 6, 20, 60, aller_retour=True, hauteur=HAUTE, sur_table_de_coupe=False),
            Phase("Couper (bord → fond)", 12, 10, 85, main=10, coupe=True, charge_kg=CISEAU_KG, hauteur=HAUTE, sur_table_de_coupe=False),
            Phase("Revenir au bord", 4, 85, 10, main=10, coupe=True, charge_kg=CISEAU_KG, hauteur=HAUTE, sur_table_de_coupe=False),
        ], f"table réglée à {HAUTE:.0f} cm (coupeur de 170 cm), toujours accessible d'un seul côté"),
        "2 côtés + table plus haute": Scenario("Couper", "2 côtés + table plus haute", [
            Phase("Étaler le tissu", 6, 20, 44, aller_retour=True, hauteur=HAUTE, sur_table_de_coupe=False),
            Phase("Couper (bord → milieu)", 12, 10, 44, main=10, coupe=True, charge_kg=CISEAU_KG, hauteur=HAUTE, sur_table_de_coupe=False),
            Phase("Revenir au bord", 4, 44, 10, main=10, coupe=True, charge_kg=CISEAU_KG, hauteur=HAUTE, sur_table_de_coupe=False),
        ], f"accès des deux côtés + table réglée à {HAUTE:.0f} cm : le travail remonte vers les yeux"),
    },
    "Ouvrir rouleau": {
        "actuel": Scenario("Ouvrir rouleau", "actuel", [
            Phase("Prendre le rouleau sur le chariot bas", 4, 25, 25, hauteur=CHARIOT_BAS, profondeur=60,
                  sur_table_de_coupe=False, main=15, charge_kg=ROULEAU_KG),
            Phase("Le poser au bout de la table", 3, 15, 35, main=15, charge_kg=ROULEAU_KG),
            Phase("Dérouler et étaler jusqu'au fond", 10, 20, 85, aller_retour=True),
        ], f"rouleau ≈ {ROULEAU_KG:.0f} kg (à confirmer), chariot à {CHARIOT_BAS:.0f} cm (à vérifier)"),
        "amélioré": Scenario("Ouvrir rouleau", "porte-rouleau", [
            Phase("Faire rouler le rouleau du porte-rouleau à la table", 4, 20, 25, main=15,
                  charge_kg=ROULEAU_KG),
            Phase("Dérouler et étaler (accès 2 côtés)", 10, 20, 44, aller_retour=True),
        ], "porte-rouleau à hauteur de table (plus de levée depuis le chariot) + accès des deux côtés"),
    },
    "Classer": {
        "actuel": Scenario("Classer", "actuel", [
            Phase("Trier les panneaux par nuance", 12, 15, 35, aller_retour=True),
            Phase("Former le paquet de 30 panneaux", 4, 15, 15, main=5, charge_kg=PAQUET_KG),
        ], "tri près du bord de la table de coupe, à plat"),
        "amélioré": Scenario("Classer", "pupitre incliné", [
            Phase("Trier les panneaux sur le pupitre", 12, 10, 30, aller_retour=True, hauteur=115, profondeur=45,
                  sur_table_de_coupe=False, inclinaison=30),
            Phase("Former le paquet de 30 panneaux", 4, 15, 15, main=5, charge_kg=PAQUET_KG),
        ], "pupitre de tri à 115 cm incliné de 30° (testé : cou 34° → 13°) ; lampe au-dessus non simulée"),
    },
    "Transporter": {
        "actuel": Scenario("Transporter", "actuel", [
            Phase("Prendre le paquet sur la table", 2, 20, 20, main=5, charge_kg=PAQUET_KG),
            Phase("Le porter contre soi jusqu'au chariot", 6, 0, 0, main=5, charge_kg=PAQUET_KG,
                  regarde_mains=False),
            Phase("Le déposer dans le chariot bas", 3, 20, 40, hauteur=CHARIOT_BAS, profondeur=60,
                  sur_table_de_coupe=False, main=5, charge_kg=PAQUET_KG),
        ], f"chariot à {CHARIOT_BAS:.0f} cm (à vérifier) ; la marche n'est pas simulée (paquet tenu contre soi)"),
        "amélioré": Scenario("Transporter", "chariot haut", [
            Phase("Prendre le paquet sur la table", 2, 20, 20, main=5, charge_kg=PAQUET_KG),
            Phase("Le porter contre soi jusqu'au chariot", 6, 0, 0, main=5, charge_kg=PAQUET_KG,
                  regarde_mains=False),
            Phase("Le déposer dans le chariot à hauteur de table", 3, 20, 40, hauteur=85, profondeur=60,
                  sur_table_de_coupe=False, main=5, charge_kg=PAQUET_KG),
        ], "chariot à plateau haut (85 cm) ou à fond remontant"),
    },
}


@dataclass
class ParamsCycle:
    scenario: Scenario = field(default_factory=lambda: SCENARIOS["Couper"]["actuel"])
    taille: float = 170.0
    hauteur_table: float = TABLE
    distance_table: float = 5.0

    @property
    def duree(self):
        return self.scenario.duree

    @property
    def phases(self):
        return [(p.nom, p.duree) for p in self.scenario.phases]


def phase_a(t, pc: ParamsCycle):
    debut = 0.0
    for i, ph in enumerate(pc.scenario.phases):
        if t <= debut + ph.duree or i == len(pc.scenario.phases) - 1:
            u = min(1.0, max(0.0, (t - debut) / ph.duree))
            if ph.aller_retour:
                u = 1 - abs(2 * u - 1)
            return ph, ph.d0 + (ph.d1 - ph.d0) * u
        debut += ph.duree


def posture(t, pc: ParamsCycle):
    ph, d = phase_a(t, pc)
    hauteur = pc.hauteur_table if ph.sur_table_de_coupe else ph.hauteur
    r = ReglagesPoste(taille=pc.taille, position="debout", objet="piece", hauteur_table=hauteur,
                      distance_table=pc.distance_table, profondeur_travail=float(d),
                      hauteur_travail=ph.main, inclinaison_plan=ph.inclinaison,
                      regarder_travail=ph.regarde_mains)
    p = evaluer(r, OptionsREBA(repetitif=True, poignet_devie=ph.coupe, charge_kg=ph.charge_kg))
    if ph.coupe and p["niveaux"]["poignets"] == VERT:
        p["niveaux"] = dict(p["niveaux"], poignets=JAUNE)
    p["phase"], p["distance"], p["profondeur_plan"] = ph.nom, d, ph.profondeur
    return p


def simuler_cycle(pc: ParamsCycle, par_seconde=10):
    n = int(pc.duree * par_seconde) + 1
    lignes, stats, scores, hors = [], {z: [0, 0, 0] for z in ZONES}, [], 0
    for i in range(n):
        t = i / par_seconde
        p = posture(t, pc)
        for z in ZONES:
            stats[z][p["niveaux"][z]] += 1
        scores.append(p["reba"]["reba"])
        hors += any("hors d'atteinte" in a for a in p["alertes"])
        lignes.append({"temps_s": round(t, 2), "phase": p["phase"], "distance_cm": round(p["distance"], 1),
                       **{z: round(p["zones"][z], 1) for z in ZONES}, "reba": p["reba"]["reba"]})
    fiche = {}
    for z in ZONES:
        v, j, r = (100 * k / n for k in stats[z])
        fiche[z] = {"vert": v, "jaune": j, "rouge": r, "charge": (j * 0.5 + r) / 100}
    resume = {
        "reba_moyen": sum(scores) / n, "reba_max": max(scores),
        "pct_niveaux": {nom: 100 * sum(1 for s in scores if bas < s <= haut) / n
                        for bas, haut, nom in [(0, 3, "faible"), (3, 7, "moyen"), (7, 15, "élevé")]},
        "pct_hors_atteinte": 100 * hors / n,
    }
    return lignes, fiche, resume


def animation(pc: ParamsCycle, images_par_seconde=2, vitesse=1.0):
    pas = 1.0 / images_par_seconde
    temps = [round(i * pas, 2) for i in range(int(pc.duree / pas) + 1)]
    xmax = 40 + pc.distance_table + PROF_TABLE + 30
    plage = (-60, max(160, xmax), max(200, pc.taille + 30))
    images = []
    for t in temps:
        p = posture(t, pc)
        z = p["zones"]
        titre = (f"{t:4.1f} s · {p['phase']} · dos {z['dos']:.0f}° · épaules {z['epaules']:.0f}° · "
                 f"cou {z['cou']:.0f}° · REBA {p['reba']['reba']}")
        images.append((t, titre, figure_poste(p, profondeur_table=p["profondeur_plan"], plage=plage)))

    base = images[0][2]
    fig = go.Figure(data=base.data, layout=base.layout)
    fig.update_layout(title=images[0][1], height=600, margin=dict(l=0, r=0, t=50, b=0))
    fig.frames = [go.Frame(data=f.data, name=f"{t:.1f}", layout=go.Layout(title=titre)) for t, titre, f in images]
    duree_image = int(1000 * pas / vitesse)
    fig.update_layout(
        updatemenus=[dict(type="buttons", showactive=False, x=0.02, y=0.02, xanchor="left", yanchor="bottom",
                          buttons=[dict(label="Jouer", method="animate",
                                        args=[None, dict(frame=dict(duration=duree_image, redraw=True),
                                                         transition=dict(duration=0), fromcurrent=True)]),
                                   dict(label="Pause", method="animate",
                                        args=[[None], dict(frame=dict(duration=0, redraw=False), mode="immediate")])])],
        sliders=[dict(active=0, x=0.15, len=0.83, y=0.02, currentvalue=dict(prefix="Temps : ", suffix=" s"),
                      steps=[dict(label=f"{t:.1f}", method="animate",
                                  args=[[f"{t:.1f}"], dict(frame=dict(duration=0, redraw=True), mode="immediate")])
                             for t, _, _ in images])])
    return fig


def nom_poste(sc: Scenario):
    return f"{sc.tache} – {sc.nom} (simulé)"


def ligne_postes(nom, fiche):
    return nom + "," + ",".join(f"{fiche[z]['charge']:.2f}" for z in ZONES)


def main():
    parser = argparse.ArgumentParser(description="Cycles des tâches de coupe joués par l'avatar")
    parser.add_argument("--taille", type=float, default=170.0)
    parser.add_argument("--hauteur-table", type=float, default=TABLE)
    parser.add_argument("--tache", choices=list(SCENARIOS), help="une seule tâche")
    parser.add_argument("--detail", action="store_true", help="posture toutes les secondes")
    args = parser.parse_args()

    abr = {"cou": "Cou", "epaules": "Epa", "coudes": "Cde", "poignets": "Poi", "dos": "Dos", "genoux": "Gen"}
    print(f"Coupeur de {args.taille:.0f} cm, table de coupe à {args.hauteur_table:.0f} cm (avatar calibré sur la vidéo)\n")
    print(f"{'Tâche – scénario':<36}{'durée':>6}{'REBA moy':>9}{'max':>5}  |  " + " ".join(f"{abr[z]:>4}" for z in ZONES))
    lignes_csv = []
    for tache, scs in SCENARIOS.items():
        if args.tache and tache != args.tache:
            continue
        for cle, sc in scs.items():
            pc = ParamsCycle(scenario=sc, taille=args.taille, hauteur_table=args.hauteur_table)
            serie, fiche, res = simuler_cycle(pc)
            fl = "→ " if cle != "actuel" else "  "
            print(f"{fl}{sc.libelle:<34}{sc.duree:5.0f}s{res['reba_moyen']:9.1f}{res['reba_max']:5d}  |  " +
                  " ".join(f"{fiche[z]['charge']:4.2f}" for z in ZONES) +
                  f"   ({niveau_reba(round(res['reba_moyen']))[0]})")
            print(f"{'':6}hypothèses : {sc.hypotheses}")
            if args.detail:
                for s in serie[::10]:
                    print(f"{'':8}{s['temps_s']:4.0f} s  {s['phase']:<48} dos {s['dos']:3.0f}°  "
                          f"épaules {s['epaules']:3.0f}°  cou {s['cou']:3.0f}°  REBA {s['reba']}")
            lignes_csv.append(ligne_postes(nom_poste(sc), fiche))
        print()
    print("Lignes pour ergotwin/postes.csv :")
    for l in lignes_csv:
        print("  " + l)
    print("\nSimulation : avatar calibré sur la phase « étaler » de la vidéo réelle. "
          "Hypothèses (poids du rouleau, hauteur du chariot) à confirmer avec TLS.")


if __name__ == "__main__":
    main()
