from cycle_coupe import SCENARIOS, ParamsCycle, simuler_cycle, ZONES

NOMS = {"cou": "cou", "epaules": "épaules", "coudes": "coudes", "poignets": "poignets", "dos": "dos", "genoux": "genoux"}


def main():
    for taille in (155, 170, 185):
        print(f"\n=== Coupeur de {taille} cm ===")
        print(f"{'Tâche':<16}{'Amélioration':<18}{'REBA avant → après':>20}   zones qui baissent / qui montent (charge)")
        for tache, scs in SCENARIOS.items():
            _, fa, ra = simuler_cycle(ParamsCycle(scenario=scs["actuel"], taille=taille))
            _, fb, rb = simuler_cycle(ParamsCycle(scenario=scs["amélioré"], taille=taille))
            baisse = [f"{NOMS[z]} {fa[z]['charge']:.2f}→{fb[z]['charge']:.2f}" for z in ZONES
                      if fb[z]["charge"] < fa[z]["charge"] - 0.1]
            hausse = [f"{NOMS[z]} {fa[z]['charge']:.2f}→{fb[z]['charge']:.2f}" for z in ZONES
                      if fb[z]["charge"] > fa[z]["charge"] + 0.1]
            print(f"{tache:<16}{scs['amélioré'].nom:<18}{ra['reba_moyen']:9.1f} → {rb['reba_moyen']:.1f}{'':6}"
                  f"↓ {', '.join(baisse) or '—'}" + (f"   ↑ {', '.join(hausse)}" if hausse else ""))
    print("\n↑ = transfert de charge vers une autre zone (piège multisite).")
    print("⚠️ Simulation : avatar calibré sur la vidéo réelle (phase « étaler ») ; hypothèses dans cycle_coupe.py.")


if __name__ == "__main__":
    main()
