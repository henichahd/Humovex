from dataclasses import dataclass, field
from itertools import permutations
from pathlib import Path

import numpy as np
import pandas as pd

ZONES = ["cou", "epaules", "coudes", "poignets", "dos", "genoux"]
NOMS_ZONES = {
    "cou": "Cou", "epaules": "Épaules", "coudes": "Coudes",
    "poignets": "Poignets", "dos": "Dos", "genoux": "Genoux",
}
DOSSIER = Path(__file__).parent


@dataclass
class Parametres:
    vidange: float = 22.0
    recharge: float = 8.0
    L: float = 10.0
    r_repos: float = 1.0
    par_articulation: bool = False
    intensite_max: float = 1.0

    seuil_critique: float = 40.0
    seuil_critique_antecedent: float = 50.0

    seuil_zone_extreme: float = 0.95
    seuil_zone_haute: float = 0.75
    nb_zones_hautes: int = 3

    debut: float = 7.5
    nb_creneaux: int = 19
    duree_creneau: float = 0.5
    pas_minutes: int = 5
    pauses: list = field(default_factory=lambda: [(12.0, 12.5)])

    marge_alerte: float = 15.0
    reprise: float = 5.0
    micro_pause_min: int = 2
    micro_pause_en_priorite: bool = False
    boitier_actif: bool = True
    attente_apres_pause_min: int = 10
    relais_min: int = 5
    ratio_classer: float = 7 / 15
    ratio_transporter: float = 3 / 15
    rouleau_min_jour: float = 20.0
    panneaux_jour: float = 500.0
    panneaux_par_paquet: float = 30.0
    coupe_min_par_paquet: float = 15.0
    charge_autres: float = 0.1

    @property
    def paquets_jour(self) -> float:
        return self.panneaux_jour / self.panneaux_par_paquet

    @property
    def coupe_min_jour(self) -> float:
        return self.paquets_jour * self.coupe_min_par_paquet

    taille_max_cycle: int = 4

    @property
    def fin(self) -> float:
        return self.debut + self.nb_creneaux * self.duree_creneau


FREY_LAW_2012 = {
    "epaules":  (0.01820, 0.00168),
    "coudes":   (0.00912, 0.00094),
    "poignets": (0.00980, 0.00064),
    "dos":      (0.00755, 0.00075),
    "genoux":   (0.01500, 0.00149),
    "cou":      (0.01820, 0.00168),
}


def taux_par_zone(p: "Parametres"):
    F0, R0 = p.vidange / 100, p.recharge / 100
    if not p.par_articulation:
        return np.full(len(ZONES), F0), np.full(len(ZONES), R0)
    F_tab = np.array([FREY_LAW_2012[z][0] for z in ZONES])
    R_tab = np.array([FREY_LAW_2012[z][1] for z in ZONES])
    return F0 * F_tab / F_tab.mean(), R0 * R_tab / R_tab.mean()


def charger_postes(chemin=DOSSIER / "postes.csv") -> pd.DataFrame:
    df = pd.read_csv(chemin).set_index("poste")
    return df[ZONES].astype(float).clip(0, 1)


def charger_ouvrieres(chemin=DOSSIER / "ouvrieres.csv") -> pd.DataFrame:
    df = pd.read_csv(chemin)
    df["competences"] = df["competences"].apply(lambda s: [c.strip() for c in str(s).split(";") if c.strip()])
    df["antecedent_tms"] = df["antecedent_tms"].astype(str).str.lower().isin(["oui", "true", "1", "yes"])
    if "zones_atteintes" not in df.columns:
        df["zones_atteintes"] = ""
    df["zones_atteintes"] = df["zones_atteintes"].fillna("").apply(
        lambda s: [z.strip() for z in str(s).split(";") if z.strip() in ZONES])
    return df.set_index("ouvriere")


def integrer_ergoscan(postes: pd.DataFrame, poste: str, pourcentages_risque: dict) -> pd.DataFrame:
    postes = postes.copy()
    if poste not in postes.index:
        postes.loc[poste] = 0.0
    for zone, pct in pourcentages_risque.items():
        if zone in ZONES:
            postes.loc[poste, zone] = float(np.clip(pct / 100, 0, 1))
    return postes


def integrer_bracelet(postes: pd.DataFrame, poste: str, gestes_par_minute: float,
                      gestes_max: float = 40.0, pct_poignet_plie: float = 0.0) -> pd.DataFrame:
    postes = postes.copy()
    charge_bracelet = float(np.clip(max(gestes_par_minute / gestes_max, pct_poignet_plie / 100), 0, 1))
    postes.loc[poste, "poignets"] = max(postes.loc[poste, "poignets"], charge_bracelet)
    return postes


def verifier_poste(charges: pd.Series, p: Parametres):
    extremes = [NOMS_ZONES[z] for z in ZONES if charges[z] >= p.seuil_zone_extreme]
    hautes = [NOMS_ZONES[z] for z in ZONES if charges[z] >= p.seuil_zone_haute]
    if extremes:
        return True, f"charge extrême ({', '.join(extremes)})"
    if len(hautes) >= p.nb_zones_hautes:
        return True, f"{len(hautes)} zones très sollicitées ({', '.join(hautes)})"
    return False, ""


def postes_exclus(postes: pd.DataFrame, p: Parametres) -> dict:
    exclus = {}
    for nom, charges in postes.iterrows():
        est_exclu, raison = verifier_poste(charges, p)
        if est_exclu:
            exclus[nom] = raison
    return exclus


_CACHE = {}


def simuler(planning: list, postes: pd.DataFrame, p: Parametres) -> pd.DataFrame:
    cle = (tuple(planning), tuple(postes.index), postes[ZONES].to_numpy().tobytes(), repr(p))
    if cle not in _CACHE:
        if len(_CACHE) > 5000:
            _CACHE.clear()
        _CACHE[cle] = _simuler(planning, postes, p)
    return _CACHE[cle]


def _simuler(planning: list, postes: pd.DataFrame, p: Parametres) -> pd.DataFrame:
    matrice = {nom: postes.loc[nom, ZONES].to_numpy(float) for nom in set(planning)}
    F, R = taux_par_zone(p)
    pas_h = p.pas_minutes / 60
    n_pas = int(round(p.nb_creneaux * p.duree_creneau / pas_h))
    sous_pas = max(1, int(np.ceil(pas_h * p.L / 0.5)))
    dt = pas_h / sous_pas

    MA = np.zeros(len(ZONES))
    MR = np.ones(len(ZONES))
    MF = np.zeros(len(ZONES))
    lignes = []
    for i in range(n_pas + 1):
        h = p.debut + i * pas_h
        creneau = min(int((h - p.debut) / p.duree_creneau + 1e-9), len(planning) - 1)
        poste = planning[creneau]
        en_pause = any(a <= h < b for a, b in p.pauses)
        lignes.append([h, "Pause" if en_pause else poste, *(100 * (1 - MF))])
        if i == n_pas:
            break
        TL = np.zeros(len(ZONES)) if en_pause else matrice[poste] * p.intensite_max
        Rk = R * (p.r_repos if en_pause else 1.0)
        for _ in range(sous_pas):
            manque = TL - MA
            C = np.where(MA < TL,
                         np.where(MR > manque, p.L * manque, p.L * MR),
                         p.L * manque)
            dMA = C - F * MA
            dMR = -C + Rk * MF
            dMF = F * MA - Rk * MF
            MA, MR, MF = MA + dMA * dt, MR + dMR * dt, MF + dMF * dt
            MA, MR, MF = np.clip(MA, 0, 1), np.clip(MR, 0, 1), np.clip(MF, 0, 1)
    return pd.DataFrame(lignes, columns=["heure", "poste", *ZONES])


def resume(sim: pd.DataFrame, seuil) -> dict:
    s = seuil if isinstance(seuil, dict) else {z: float(seuil) for z in ZONES}
    minima = sim[ZONES].min()
    marges = {z: minima[z] - s[z] for z in ZONES}
    zone_crit = min(marges, key=marges.get)
    sous = np.column_stack([sim[z].to_numpy() < s[z] for z in ZONES]).any(axis=1)
    return {
        "minimum": float(minima.min()),
        "zone_la_plus_basse": NOMS_ZONES[minima.idxmin()],
        "zone_critique": NOMS_ZONES[zone_crit],
        "marge_min": float(marges[zone_crit]),
        "moyenne_fin": float(sim[ZONES].iloc[-1].mean()),
        "heure_alerte": float(sim["heure"].to_numpy()[sous.argmax()]) if sous.any() else None,
        "sure": bool(all(minima[z] >= s[z] for z in ZONES)),
    }


def seuils_ouvriere(ouvriere: pd.Series, p: Parametres) -> dict:
    atteintes = list(ouvriere.get("zones_atteintes", []) or [])
    if ouvriere["antecedent_tms"] and not atteintes:
        atteintes = ZONES
    return {z: p.seuil_critique_antecedent if z in atteintes else p.seuil_critique for z in ZONES}


def seuil_ouvriere(ouvriere: pd.Series, p: Parametres) -> float:
    return max(seuils_ouvriere(ouvriere, p).values())


def planning_sans_rotation(ouvriere: pd.Series, p: Parametres) -> list:
    return [ouvriere["poste_principal"]] * p.nb_creneaux


def generer_rotations(ouvriere: pd.Series, postes: pd.DataFrame, p: Parametres, nb: int = 3):
    exclus = postes_exclus(postes, p)
    autorises = [c for c in ouvriere["competences"] if c in postes.index and c not in exclus]
    if not autorises:
        return [], exclus
    seuil = seuils_ouvriere(ouvriere, p)

    vus, candidats = set(), []
    for k in range(1, min(p.taille_max_cycle, len(autorises)) + 1):
        for cycle in permutations(autorises, k):
            if ouvriere["poste_principal"] in autorises and ouvriere["poste_principal"] not in cycle:
                continue
            planning = tuple(cycle[i % k] for i in range(p.nb_creneaux))
            if planning in vus:
                continue
            vus.add(planning)
            sim = simuler(list(planning), postes, p)
            r = resume(sim, seuil)
            part_principal = planning.count(ouvriere["poste_principal"]) / p.nb_creneaux
            candidats.append({
                "planning": list(planning),
                "cycle": list(cycle),
                "part_poste_principal": part_principal,
                "simulation": sim,
                **r,
            })

    candidats.sort(key=lambda c: (c["sure"],
                                  c["part_poste_principal"] if c["sure"] else 0,
                                  round(c["minimum"], 1),
                                  c["moyenne_fin"]),
                   reverse=True)

    choisis, cycles_vus = [], set()
    for c in candidats:
        cle = frozenset(c["cycle"]), c["cycle"][0]
        if cle in cycles_vus:
            continue
        cycles_vus.add(cle)
        choisis.append(c)
        if len(choisis) == nb:
            break
    return choisis, exclus


def suggerer_formation(ouvriere: pd.Series, postes: pd.DataFrame, p: Parametres) -> list:
    exclus = postes_exclus(postes, p)
    suggestions = []
    for poste in postes.index:
        if poste in exclus or poste in ouvriere["competences"]:
            continue
        test = ouvriere.copy()
        test["competences"] = ouvriere["competences"] + [poste]
        rotations, _ = generer_rotations(test, postes, p, nb=1)
        if rotations and rotations[0]["sure"]:
            suggestions.append((poste, rotations[0]["minimum"]))
    return sorted(suggestions, key=lambda x: -x[1])


def _tache(nom_poste: str) -> str:
    return nom_poste.split(" – ")[0].strip()


def texte_suggestions(ouvriere: pd.Series, suggestions: list) -> str:
    if not suggestions:
        return "Redessiner les postes"
    deja = {_tache(c) for c in ouvriere["competences"]}
    equiper, former = [], []
    for poste, _ in suggestions:
        tache = _tache(poste)
        solution = poste.split(" – ", 1)[1].replace(" (simulé)", "") if " – " in poste else poste
        if tache in deja:
            equiper.append(f"{solution} ({tache})")
        else:
            former.append(tache)
    morceaux = []
    if equiper:
        morceaux.append("Équiper : " + ", ".join(equiper))
    if former:
        morceaux.append("Former à : " + ", ".join(former))
    return " · ".join(morceaux)


ROLES = {"couper": "Couper", "rouleau": "Ouvrir rouleau", "classer": "Classer", "transporter": "Transporter"}
ORGANISATIONS = {
    "blocs": "Grands blocs (couper toute la matinée, puis classer et transporter)",
    "petits_lots": "Petits lots fixes (cycle de 30 min de la fiche : 5 rouleau · 15 couper · 7 classer · 3 chariot)",
    "dynamique": "Dynamique (alerte → le boîtier propose une autre tâche ou une micro-pause, le coupeur choisit)",
}


def taches_par_role(ouvriere: pd.Series, postes: pd.DataFrame) -> dict:
    roles = {}
    for c in [ouvriere["poste_principal"]] + list(ouvriere["competences"]):
        for cle, prefixe in ROLES.items():
            if cle not in roles and c in postes.index and c.startswith(prefixe):
                roles[cle] = c
    return roles


def simuler_organisation(ouvriere: pd.Series, postes: pd.DataFrame, p: Parametres, organisation: str):
    roles = taches_par_role(ouvriere, postes)
    charges = {r: postes.loc[t, ZONES].to_numpy(float) for r, t in roles.items()}
    charges["autres"] = np.full(len(ZONES), p.charge_autres)
    roles = dict(roles, autres="Autres activités (déplacements, attente…)")
    seuils = seuils_ouvriere(ouvriere, p)
    alerte = {z: seuils[z] + p.marge_alerte for z in ZONES}
    F, R = taux_par_zone(p)
    dt = 1 / 60
    n = int(round((p.fin - p.debut) * 60))
    MA, MR, MF = np.zeros(len(ZONES)), np.ones(len(ZONES)), np.zeros(len(ZONES))
    fait = {"couper": 0.0, "classer": 0.0, "transporter": 0.0, "rouleau": 0.0, "autres": 0.0}
    role, zone_relais, micro, attente, debut_relais = "couper", None, 0, 0, 0
    nb_alertes, nb_micro, propositions = 0, 0, []
    lignes = []

    def dispo(r):
        if r == "classer":
            return p.ratio_classer * fait["couper"] - fait["classer"]
        if r == "transporter":
            return p.ratio_transporter * fait["couper"] - fait["transporter"]
        if r == "rouleau":
            return p.rouleau_min_jour - fait["rouleau"]
        if r == "couper":
            return p.coupe_min_jour - fait["couper"]
        return 1e9

    for m in range(n):
        h = p.debut + m / 60
        batt = 100 * (1 - MF)
        bz = dict(zip(ZONES, batt))
        en_pause = any(a <= h < b for a, b in p.pauses)
        fin_journee = h >= p.fin - 0.5

        if en_pause:
            role_m = "pause"
        elif organisation == "blocs":
            if h < p.debut + p.rouleau_min_jour / 60 and dispo("rouleau") >= 1:
                role_m = "rouleau"
            elif role in ("classer", "transporter") or fin_journee or dispo("classer") >= 120:
                role_m = ("classer" if dispo("classer") >= 1 else "transporter" if dispo("transporter") >= 1
                          else "couper")
            else:
                role_m = "couper"
        elif organisation == "petits_lots":
            c = m % 30
            if fin_journee:
                role_m = ("classer" if dispo("classer") >= 1 else "transporter" if dispo("transporter") >= 1
                          else "couper")
            elif c < 5:
                role_m = "rouleau" if dispo("rouleau") >= 1 else "couper"
            elif c < 20:
                role_m = "couper"
            elif c < 27:
                role_m = "classer" if dispo("classer") >= 1 else "couper"
            else:
                role_m = "transporter" if dispo("transporter") >= 1 else "couper"
        else:
            if micro > 0:
                role_m = "micro"
                micro -= 1
            elif fin_journee:
                role_m = ("classer" if dispo("classer") >= 1 else "transporter" if dispo("transporter") >= 1
                          else "couper")
            elif h < p.debut + p.rouleau_min_jour / 60 and dispo("rouleau") >= 1:
                role_m = "rouleau"
            elif role in ("classer", "transporter") and zone_relais is None:
                role_m = (role if dispo(role) >= 1 else "transporter" if (role == "classer" and dispo("transporter") >= 1)
                          else "couper")
            elif role != "couper" and role in charges and zone_relais is not None:
                ok = bz[zone_relais] >= alerte[zone_relais] + p.reprise and m - debut_relais >= p.relais_min
                role_m = "couper" if (ok or dispo(role) < 1) else role
                if role_m == "couper":
                    zone_relais = None
                    attente = p.attente_apres_pause_min
            else:
                role_m = "couper"
                if dispo("classer") >= 2 * 7:
                    role_m, zone_relais = "classer", None
                elif attente > 0:
                    attente -= 1
                elif dispo("couper") >= 1 and p.boitier_actif:
                    en_alerte = [z for z in ZONES if bz[z] < alerte[z] and charges["couper"][ZONES.index(z)] >= 0.3]
                    if en_alerte:
                        z = min(en_alerte, key=lambda z: bz[z] - alerte[z])
                        iz = ZONES.index(z)
                        nb_alertes += 1
                        relais = [r for r in ("transporter", "classer", "rouleau") if r in charges
                                  and dispo(r) >= 1 and charges[r][iz] <= charges["couper"][iz] - 0.2]
                        if relais and not p.micro_pause_en_priorite:
                            role_m = min(relais, key=lambda r: (charges[r][iz], charges[r].sum()))
                            zone_relais, debut_relais = z, m
                            propositions.append((h, NOMS_ZONES[z], roles[role_m]))
                        else:
                            role_m, micro, attente = "micro", p.micro_pause_min - 1, p.attente_apres_pause_min
                            nb_micro += 1
                            propositions.append((h, NOMS_ZONES[z], "Micro-pause"))
        if role_m == "couper" and dispo("couper") < 1:
            role_m = ("classer" if dispo("classer") >= 1 else "transporter" if dispo("transporter") >= 1
                      else "autres")
            if organisation == "dynamique":
                zone_relais = None
        role = role_m if role_m not in ("pause", "micro") else role

        nom = {"pause": "Pause", "micro": "Micro-pause"}.get(role_m, roles.get(role_m, role_m))
        lignes.append([h, nom, *batt])
        if role_m in fait:
            fait[role_m] += 1

        TL = charges[role_m] * p.intensite_max if role_m in charges else np.zeros(len(ZONES))
        Rk = R * (p.r_repos if role_m in ("pause", "micro") else 1.0)
        manque = TL - MA
        C = np.where(MA < TL, np.where(MR > manque, p.L * manque, p.L * MR), p.L * manque)
        MA, MR, MF = (np.clip(MA + (C - F * MA) * dt, 0, 1), np.clip(MR + (-C + Rk * MF) * dt, 0, 1),
                      np.clip(MF + (F * MA - Rk * MF) * dt, 0, 1))

    lignes.append([p.fin, "Fin", *(100 * (1 - MF))])
    sim = pd.DataFrame(lignes, columns=["heure", "poste", *ZONES])
    r = resume(sim, seuils)
    temps_travail = n - sum(1 for l in lignes if l[1] == "Pause")
    r.update({
        "minutes_coupe": fait["couper"],
        "paquets": fait["couper"] / p.coupe_min_par_paquet,
        "panneaux": fait["couper"] / p.coupe_min_par_paquet * p.panneaux_par_paquet,
        "minutes_autres": fait["autres"],
        "part_coupe": fait["couper"] / temps_travail,
        "travail_restant": float(int(max(0, dispo("classer")) + max(0, dispo("transporter")))),
        "nb_alertes": nb_alertes, "nb_micro_pauses": nb_micro, "propositions": propositions,
        "minutes_par_role": dict(fait), "seuils": seuils, "alertes": alerte,
    })
    return sim, r


def heure_txt(h: float) -> str:
    return f"{int(h):02d}h{int(round((h % 1) * 60)) % 60:02d}"


def planning_en_tableau(planning: list, p: Parametres) -> pd.DataFrame:
    return pd.DataFrame({
        "Créneau": [f"{heure_txt(p.debut + i * p.duree_creneau)} – {heure_txt(p.debut + (i + 1) * p.duree_creneau)}"
                    for i in range(len(planning))],
        "Poste": ["Pause" if any(a <= p.debut + (i + 0.5) * p.duree_creneau < b for a, b in p.pauses) else poste
                  for i, poste in enumerate(planning)],
    })


if __name__ == "__main__":
    p = Parametres()
    postes = charger_postes()
    ouvrieres = charger_ouvrieres()

    postes = integrer_bracelet(postes, postes.index[0], gestes_par_minute=32)

    print("=== Postes exclus de la rotation (à redessiner) ===")
    for nom, raison in postes_exclus(postes, p).items():
        print(f"  - {nom} : {raison}")

    for nom, ouv in ouvrieres.iterrows():
        seuil = seuil_ouvriere(ouv, p)
        print(f"\n=== {nom} (poste principal : {ouv['poste_principal']}, seuil {seuil:.0f} %) ===")
        sans = resume(simuler(planning_sans_rotation(ouv, p), postes, p), seuil)
        alerte = heure_txt(sans["heure_alerte"]) if sans["heure_alerte"] else "jamais"
        print(f"  Sans rotation : batterie minimale {sans['minimum']:.0f} % "
              f"({sans['zone_la_plus_basse']}), passe sous le seuil à {alerte}")
        rotations, _ = generer_rotations(ouv, postes, p)
        for i, r in enumerate(rotations):
            etat = "sûre" if r["sure"] else "sous le seuil"
            print(f"  Option {chr(65 + i)} : {' → '.join(r['cycle'])} (en boucle) | "
                  f"min {r['minimum']:.0f} % ({r['zone_la_plus_basse']}) | "
                  f"{r['part_poste_principal'] * 100:.0f} % sur le poste principal | {etat}")
        if not any(r["sure"] for r in rotations):
            sugg = suggerer_formation(ouv, postes, p)
            if sugg:
                print(f"  → Aucune rotation sûre. {texte_suggestions(ouv, sugg)}")
            else:
                print("  → Aucune rotation sûre : les postes doivent être redessinés.")
