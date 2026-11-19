import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dataclasses import asdict
from collections import Counter
from datetime import datetime

from jumeau_poste import ReglagesPoste, evaluer, figure_poste, NOMS as NOMS_POSTE, VERT as P_VERT, JAUNE as P_JAUNE, ROUGE as P_ROUGE
from reba import OptionsREBA
from cycle_coupe import ParamsCycle, SCENARIOS, simuler_cycle, animation, nom_poste, ZONES as ZONES_CYCLE

from jumeau import (
    ZONES, NOMS_ZONES, Parametres, charger_postes, charger_ouvrieres, integrer_bracelet,
    postes_exclus, simuler, resume, seuil_ouvriere, seuils_ouvriere, planning_sans_rotation,
    simuler_organisation, ORGANISATIONS, ROLES, taches_par_role,
    generer_rotations, suggerer_formation, texte_suggestions, planning_en_tableau, heure_txt, DOSSIER, _tache,
)

st.set_page_config(page_title="ErgoTwin – Jumeau numérique · Humovex", page_icon=":material/accessibility_new:", layout="wide")

COULEURS = {"cou": "#ef5b5b", "epaules": "#f5a142", "coudes": "#a78bfa",
            "poignets": "#4aa3ff", "dos": "#3ecf8e", "genoux": "#94a3b8"}

st.sidebar.title("Qui utilise l'application ?")
vue = st.sidebar.radio("Vue", ["Coupeur et médecin du travail", "Entreprise (HSE, ingénieur)"],
                       help="D1 : les données individuelles restent au coupeur et au médecin. "
                            "D2 : l'entreprise ne voit que des données agrégées par poste.")
VUE_COUPEUR = vue.startswith("Coupeur")
st.sidebar.divider()
st.sidebar.title("Paramètres du modèle")
st.sidebar.caption("Valeurs à calibrer avec le médecin du travail.")
st.sidebar.markdown("**Modèle à 3 compartiments** (Xia & Frey Law, 2008)")
p = Parametres(
    vidange=st.sidebar.slider("F – taux de fatigue (%/h)", 5.0, 40.0, 22.0, 1.0),
    recharge=st.sidebar.slider("R – taux de récupération (%/h)", 1.0, 20.0, 8.0, 1.0),
    r_repos=st.sidebar.slider("r – récupération renforcée en pause (3CC-r)", 1.0, 5.0, 1.0, 0.5),
    par_articulation=st.sidebar.toggle("Rapports entre articulations de Frey-Law 2012 (mis à l'échelle)", False,
                                       help="Garde les écarts entre épaule, coude, main, tronc… de Frey-Law 2012, "
                                            "ramenés à la moyenne des valeurs de démonstration."),
    seuil_critique=st.sidebar.slider("Seuil critique (%)", 10.0, 70.0, 40.0, 5.0),
    seuil_critique_antecedent=st.sidebar.slider("Seuil si antécédent de TMS (%)", 10.0, 80.0, 50.0, 5.0),
    seuil_zone_extreme=st.sidebar.slider("Exclusion : zone extrême ≥", 0.5, 1.0, 0.95, 0.05),
)
st.sidebar.divider()
st.sidebar.subheader("Organisation dynamique")
st.sidebar.caption("Le bracelet alerte, l'application propose, le coupeur choisit.")
p.marge_alerte = st.sidebar.slider("Alerte : points au-dessus du seuil", 0.0, 30.0, 15.0, 1.0,
                                   help="L'alerte arrive AVANT le seuil, pour laisser le temps d'agir")
p.micro_pause_en_priorite = st.sidebar.toggle("Proposer d'abord une micro-pause", False,
                                              help="Sinon : d'abord une tâche qui repose la zone, micro-pause s'il n'y en a pas")
p.micro_pause_min = st.sidebar.slider("Durée d'une micro-pause (min)", 1, 10, 2, 1)
p.boitier_actif = st.sidebar.toggle("Alertes activées", True,
                                    help="H2 : le coupeur peut arrêter l'outil ; il ne reçoit alors plus de propositions")
st.sidebar.divider()
st.sidebar.subheader("Bracelet ErgoBand (IMU au poignet)")
st.sidebar.caption("Le bracelet mesure l'angle du poignet (la caméra le voit mal) et calcule sa part du score REBA.")
poste_bracelet = st.sidebar.selectbox("Tâche mesurée par le bracelet", ["(aucun)"] + list(charger_postes().index))
pct_plie = st.sidebar.slider("Temps avec le poignet plié à plus de 15° (%)", 0, 100, 40,
                             help="Seuil REBA du poignet : au-delà de 15°, 2 points au lieu de 1")
gpm = st.sidebar.slider("Gestes par minute", 0, 60, 32)

st.title("ErgoTwin – Jumeau numérique du poste de coupe")
st.caption("On mesure (ErgoScan, bracelet ErgoBand) → on simule la journée → l'application propose, le coupeur décide. "
           "Niveau « ombre numérique » (Kritzinger 2018) : les mesures arrivent dans le jumeau, le retour vers le "
           "poste passe par le coupeur (humain dans la boucle).")

with st.expander("Le modèle de fatigue utilisé", expanded=False):
    st.markdown(
        "Chaque zone du corps est modélisée avec le **modèle à 3 compartiments** de Xia & Frey Law (2008) : "
        "le muscle est soit **au repos** (MR), soit **actif** (MA), soit **fatigué** (MF)."
    )
    st.latex(r"\frac{dM_A}{dt} = C(t) - F\,M_A \qquad \frac{dM_R}{dt} = -C(t) + R\,M_F \qquad \frac{dM_F}{dt} = F\,M_A - R\,M_F")
    st.markdown(
        "Le contrôleur $C(t)$ active juste assez de muscle pour suivre la charge du poste. "
        "La **batterie** affichée = $100\\% - M_F$, la part du muscle qui n'est pas fatiguée.  \n"
        "Les valeurs de F et R utilisées ici sont des **valeurs de démonstration**, à calibrer."
    )
    st.markdown(
        "**Pourquoi pas directement les valeurs publiées ?** Frey-Law, Looft & Heitsman (2012) donnent F et R par "
        "articulation (par seconde), pour un effort exprimé en **% de la force maximale** et tenu sans pause. "
        "Notre entrée est une **charge posturale** (part du temps en posture à risque, ErgoScan). Avec les valeurs "
        "publiées et cette entrée, toutes les zones s'épuisent en moins de 2 h, ce qui n'a pas de sens pour un travail "
        "intermittent. Étape suivante : convertir les angles en effort (moment articulaire ÷ force maximale) et "
        "utiliser la version 3CC-r (Looft 2018) pour les pauses."
    )
    st.dataframe(pd.DataFrame([{"Articulation": a, "F (1/s)": f, "R (1/s)": r} for a, (f, r) in [
        ("Épaule", (0.01820, 0.00168)), ("Coude", (0.00912, 0.00094)), ("Main / préhension", (0.00980, 0.00064)),
        ("Tronc", (0.00755, 0.00075)), ("Genou", (0.01500, 0.00149))]]), hide_index=True)
    st.caption("Valeurs publiées : Frey-Law, Looft & Heitsman, J. Biomech. 2012, tableau 1.")

with st.expander("Profils de charge des postes (sortie d'ErgoScan, modifiable)", expanded=False):
    st.caption("0 = la zone ne travaille pas · 1 = charge maximale")
    postes = st.data_editor(charger_postes(), num_rows="dynamic", width="stretch")
    postes = postes[ZONES].astype(float).clip(0, 1)

if poste_bracelet != "(aucun)" and poste_bracelet in postes.index:
    postes = integrer_bracelet(postes, poste_bracelet, gpm, pct_poignet_plie=pct_plie)

ouvrieres = charger_ouvrieres()
exclus = postes_exclus(postes, p)

NOMS_ONGLETS = (["Mon corps (coupeur)", "Jumeau du poste"] if VUE_COUPEUR
                else ["Jumeau du poste", "Responsable HSE", "Ingénieur conception"])
ONGLETS = dict(zip(NOMS_ONGLETS, st.tabs(NOMS_ONGLETS)))
onglet_poste = ONGLETS["Jumeau du poste"]
onglet_ouv = ONGLETS.get("Mon corps (coupeur)")
onglet_hse = ONGLETS.get("Responsable HSE")
onglet_ing = ONGLETS.get("Ingénieur conception")
FICHIER_SIGNALEMENTS = DOSSIER / "signalements.csv"
DOSSIER_PERSO = DOSSIER / "donnees_personnelles"


def graphe_batteries(sim: pd.DataFrame, titre: str, seuil: float) -> go.Figure:
    fig = go.Figure()
    for z in ZONES:
        fig.add_trace(go.Scatter(x=sim["heure"], y=sim[z], name=NOMS_ZONES[z], mode="lines",
                                 line=dict(color=COULEURS[z], width=3),
                                 customdata=sim["poste"],
                                 hovertemplate="%{y:.0f} % · %{customdata}<extra>" + NOMS_ZONES[z] + "</extra>"))
    valeurs = sorted(set(seuil.values())) if isinstance(seuil, dict) else [seuil]
    for v in valeurs:
        zones_v = ([NOMS_ZONES[z] for z in ZONES if seuil[z] == v] if isinstance(seuil, dict) else [])
        texte = f"seuil {v:.0f} %" + (f" ({', '.join(zones_v)})" if isinstance(seuil, dict) and len(valeurs) > 1 else "")
        fig.add_hline(y=v, line_dash="dash", line_color="#ef5b5b", annotation_text=texte,
                      annotation_position="bottom right")
    for a, b in p.pauses:
        fig.add_vrect(x0=a, x1=b, fillcolor="#3ecf8e", opacity=0.12, line_width=0)
    ticks = list(range(int(p.debut), int(p.fin) + 1))
    fig.update_layout(title=titre, height=380, margin=dict(l=10, r=10, t=50, b=10),
                      yaxis=dict(title="Batterie (%)", range=[0, 105]),
                      xaxis=dict(title="Heure", tickvals=ticks, ticktext=[f"{h}h" for h in ticks]),
                      legend=dict(orientation="h", y=-0.25))
    return fig


CURSEURS = [
    ("taille", "Taille du coupeur (cm)", 145.0, 190.0, 1.0),
    ("hauteur_table", "Hauteur du plan de travail : table, chariot, pupitre (cm)", 40.0, 120.0, 1.0),
    ("distance_table", "Distance ventre → bord du plan (cm)", 0.0, 40.0, 1.0),
    ("profondeur_travail", "Distance bord du plan → point travaillé (cm)", 5.0, 90.0, 1.0),
    ("hauteur_travail", "Hauteur du point travaillé au-dessus du plan (cm)", 0.0, 20.0, 1.0),
    ("inclinaison_plan", "Inclinaison du plan vers le coupeur (°)", 0.0, 40.0, 1.0),
]
CHAMPS_TEXTE = ["position", "objet"]
FICHIER_REGLAGES = DOSSIER / "postes_reglages.csv"
NIVEAU_TXT = {P_VERT: "vert", P_JAUNE: "jaune", P_ROUGE: "rouge", None: "–"}


def charger_reglages():
    if FICHIER_REGLAGES.exists():
        return pd.read_csv(FICHIER_REGLAGES).set_index("poste")
    return pd.DataFrame(columns=["position", "objet"] + [c for c, *_ in CURSEURS]).rename_axis("poste")


def reglages_du_poste(nom):
    df = charger_reglages()
    defaut = asdict(ReglagesPoste())
    defaut.update(position="debout", objet="piece")
    if nom in df.index:
        ligne = df.loc[nom].to_dict()
        defaut.update({k: (str(v) if k in CHAMPS_TEXTE else float(v)) for k, v in ligne.items()
                       if pd.notna(v) and k in defaut})
    return defaut


CLES_REGLAGES = [c for c, *_ in CURSEURS] + CHAMPS_TEXTE


def _charger_poste():
    r = reglages_du_poste(st.session_state.jp_poste)
    st.session_state.jp_base = r
    for cle in CLES_REGLAGES:
        st.session_state[f"jp_{cle}"] = r[cle]


def _definir_actuel():
    st.session_state.jp_base = dict(st.session_state.jp_base,
                                    **{cle: st.session_state[f"jp_{cle}"] for cle in CLES_REGLAGES})


def _revenir_actuel():
    for cle in CLES_REGLAGES:
        st.session_state[f"jp_{cle}"] = st.session_state.jp_base[cle]


if "jp_poste" not in st.session_state:
    st.session_state.jp_poste = list(postes.index)[0]
    _charger_poste()

with onglet_poste:
    st.caption("Copie virtuelle du poste de coupe TLS (table 95 × 88 cm, coupeur debout). "
               "Partie 1 : on teste un réglage sur une posture. Partie 2 : l'avatar joue les 4 tâches, avant et après "
               "une amélioration. Avatar calibré sur la vidéo réelle (erreur sur le dos : 2,5°) ; c'est une simulation, "
               "pas une mesure.")

    st.subheader("1. Tester un réglage du poste")
    col_reglages, col_3d = st.columns([1, 2.3])

    with col_reglages:
        poste_jp = st.selectbox("Tâche représentée", list(postes.index), key="jp_poste", on_change=_charger_poste)
        for cle, libelle, mini, maxi, pas in CURSEURS:
            st.slider(libelle, mini, maxi, step=pas, key=f"jp_{cle}")
        st.markdown("**Activité (pour le score REBA)**")
        statique = st.checkbox("Posture tenue plus d'1 minute", True)
        repetitif = st.checkbox("Gestes répétés plus de 4 fois/min", True)
        b1, b2 = st.columns(2)
        b1.button("Garder comme référence", on_click=_definir_actuel, width="stretch",
                  help="Le réglage actuel devient la référence « avant »")
        b2.button("Revenir à la référence", on_click=_revenir_actuel, width="stretch")

    options = OptionsREBA(statique=statique, repetitif=repetitif)
    teste = evaluer(ReglagesPoste(**dict(st.session_state.jp_base,
                                         **{cle: st.session_state[f"jp_{cle}"] for cle in CLES_REGLAGES})), options)
    actuel = evaluer(ReglagesPoste(**st.session_state.jp_base), options)

    with col_3d:
        m1, m2, m3 = st.columns(3)
        ra, rt = actuel["reba"]["reba"], teste["reba"]["reba"]
        m1.metric("Score REBA", f"{rt} · {teste['reba']['niveau']}",
                  f"{rt - ra:+d} vs référence ({ra})" if rt != ra else "= référence",
                  delta_color="inverse" if rt != ra else "off", delta_arrow="auto" if rt != ra else "off")
        rouges_t = sum(1 for z in NOMS_POSTE if teste["niveaux"].get(z) == P_ROUGE)
        rouges_a = sum(1 for z in NOMS_POSTE if actuel["niveaux"].get(z) == P_ROUGE)
        m2.metric("Zones en rouge", rouges_t,
                  f"{rouges_t - rouges_a:+d} vs référence" if rouges_t != rouges_a else "= référence",
                  delta_color="inverse" if rouges_t != rouges_a else "off",
                  delta_arrow="auto" if rouges_t != rouges_a else "off")
        z_max = max(teste["charges"], key=teste["charges"].get)
        m3.metric("Zone la plus chargée", NOMS_ZONES.get(z_max, z_max), f"charge {teste['charges'][z_max]:.2f}",
                  delta_color="off", delta_arrow="off")
        st.plotly_chart(figure_poste(teste), width="stretch", config={"displaylogo": False})
        for a in teste["alertes"]:
            st.warning(a)

    st.dataframe(pd.DataFrame([{
        "Zone": NOMS_POSTE[z],
        "Référence": f"{actuel['zones'][z]:.0f}° ({NIVEAU_TXT[actuel['niveaux'][z]]})",
        "Réglage testé": f"{teste['zones'][z]:.0f}° ({NIVEAU_TXT[teste['niveaux'][z]]})",
        "Évolution": f"{teste['zones'][z] - actuel['zones'][z]:+.0f}°",
    } for z in ["cou", "dos", "epaules", "coudes", "poignets", "genoux"]]), hide_index=True, width="stretch")
    st.caption("Une seule posture : sert à comparer des dimensions entre elles. Les charges du jumeau viennent du geste "
               "complet joué par l'avatar (partie 2). Proportions du corps : Drillis & Contini ; poignet mesuré en réel "
               "par ErgoScan et le bracelet.")

    st.divider()
    st.subheader("2. Les 4 tâches jouées par l'avatar : avant / après")
    st.caption("La vidéo réelle ne montre que la préparation de la coupe : l'avatar joue chaque tâche, phase par phase. "
               "La taille et la distance au ventre viennent de la partie 1.")

    def _pc(tache, cle_sc, taille, hauteur_table, distance_table):
        return ParamsCycle(scenario=SCENARIOS[tache][cle_sc], taille=taille, hauteur_table=hauteur_table,
                           distance_table=distance_table)

    @st.cache_data(show_spinner=False)
    def _cycle(tache, cle_sc, taille, hauteur_table, distance_table):
        return simuler_cycle(_pc(tache, cle_sc, taille, hauteur_table, distance_table))

    @st.cache_data(show_spinner="L'avatar prépare le geste…")
    def _animation(tache, cle_sc, taille, hauteur_table, distance_table):
        return animation(_pc(tache, cle_sc, taille, hauteur_table, distance_table))

    cc1, cc2, cc3, cc4 = st.columns([1.2, 1.2, 1, 1])
    tache_anim = cc1.selectbox("Tâche", list(SCENARIOS), key="anim_tache")
    solutions_anim = [k for k in SCENARIOS[tache_anim] if k != "actuel"]
    cle_sol = cc2.selectbox("Solution comparée", solutions_anim, key=f"anim_sol_{tache_anim}",
                            format_func=lambda k: SCENARIOS[tache_anim][k].nom)
    cle_anim = cc2.radio("Scénario à animer", ["actuel", cle_sol], horizontal=True, key=f"anim_sc_{tache_anim}_{cle_sol}",
                         format_func=lambda k: "Avant (actuel)" if k == "actuel" else "Après")
    h_table_coupe = cc3.slider("Hauteur de la table de coupe (cm)", 70.0, 110.0, 95.0, 1.0, help="95 cm : table TLS")
    voir_anim = cc4.toggle("Afficher l'animation 3D", value=False, help="≈ 5 s de calcul la première fois")
    base_cle = (float(st.session_state.jp_taille), float(h_table_coupe), float(st.session_state.jp_distance_table))

    res_sc = {k: _cycle(tache_anim, k, *base_cle) for k in ("actuel", cle_sol)}
    for k, col in zip(("actuel", cle_sol), st.columns(2)):
        sc = SCENARIOS[tache_anim][k]
        _, f_k, r_k = res_sc[k]
        col.markdown(f"**{'Avant' if k == 'actuel' else 'Après'} : {sc.libelle}**  \n<small>{sc.hypotheses}</small>",
                     unsafe_allow_html=True)
        m1_, m2_, m3_ = col.columns(3)
        delta = None
        if k != "actuel":
            delta = f"{r_k['reba_moyen'] - res_sc['actuel'][2]['reba_moyen']:+.1f} vs avant"
        m1_.metric("REBA moyen", f"{r_k['reba_moyen']:.1f}", delta, delta_color="inverse")
        m2_.metric("REBA max", r_k["reba_max"])
        m3_.metric("Temps en risque moyen+", f"{r_k['pct_niveaux']['moyen'] + r_k['pct_niveaux']['élevé']:.0f} %")

    st.dataframe(pd.DataFrame([{
        "Zone": NOMS_POSTE[z],
        "Charge avant": round(res_sc["actuel"][1][z]["charge"], 2),
        "Charge après": round(res_sc[cle_sol][1][z]["charge"], 2),
        "Évolution": f"{res_sc[cle_sol][1][z]['charge'] - res_sc['actuel'][1][z]['charge']:+.2f}",
        "Rouge avant": f"{res_sc['actuel'][1][z]['rouge']:.0f} %",
        "Rouge après": f"{res_sc[cle_sol][1][z]['rouge']:.0f} %",
    } for z in ZONES_CYCLE]), hide_index=True, width="stretch")
    st.caption("Une zone qui baisse pendant qu'une autre monte = transfert de charge (piège multisite).")

    if voir_anim:
        st.plotly_chart(_animation(tache_anim, cle_anim, *base_cle), width="stretch", config={"displaylogo": False})

    lignes_cycle = res_sc[cle_anim][0]
    df_cycle = pd.DataFrame(lignes_cycle)
    fig_c = go.Figure()
    debut_ph = 0.0
    for ph in SCENARIOS[tache_anim][cle_anim].phases:
        fig_c.add_vrect(x0=debut_ph, x1=debut_ph + ph.duree, fillcolor="#94a3b8", opacity=0.08, line_width=0,
                        annotation_text=ph.nom, annotation_position="top left", annotation_font_size=10)
        debut_ph += ph.duree
    for z in ["dos", "epaules", "cou"]:
        fig_c.add_trace(go.Scatter(x=df_cycle["temps_s"], y=df_cycle[z], name=f"{NOMS_POSTE[z]} (°)",
                                   line=dict(color=COULEURS[z], width=3)))
    fig_c.add_trace(go.Scatter(x=df_cycle["temps_s"], y=df_cycle["reba"], name="REBA", yaxis="y2",
                               line=dict(color="#e5e7eb", width=2, dash="dot")))
    fig_c.update_layout(title=f"{SCENARIOS[tache_anim][cle_anim].libelle} : angles et REBA dans le temps",
                        height=360, margin=dict(l=10, r=10, t=50, b=10), legend=dict(orientation="h", y=-0.2),
                        xaxis=dict(title="Temps dans le cycle (s)"), yaxis=dict(title="Angle (°)"),
                        yaxis2=dict(title="REBA", overlaying="y", side="right", range=[0, 15]))
    st.plotly_chart(fig_c, width="stretch")

    if st.button(f"Enregistrer « {tache_anim} » avant et après dans le jumeau (taille et table choisies)"):
        tout = charger_postes()
        for k in ("actuel", cle_sol):
            nom = nom_poste(SCENARIOS[tache_anim][k])
            for z in ZONES:
                tout.loc[nom, z] = round(res_sc[k][1][z]["charge"], 2)
        tout.reset_index().to_csv(DOSSIER / "postes.csv", index=False)
        st.success("Charges enregistrées dans postes.csv. Recharge la page (F5) pour les autres onglets.")

if onglet_ouv is not None:
  with onglet_ouv:
      nom = st.selectbox("Ouvrière", list(ouvrieres.index))
      ouv = ouvrieres.loc[nom].copy()

      with st.expander("Version de chaque tâche pour ce profil (poste actuel ou amélioré)", expanded=False):
          st.caption("Choisis le matériel utilisé pour chaque tâche. Tout l'onglet se recalcule. "
                     "La version de « Couper » devient la tâche principale.")
          roles_actuels = taches_par_role(ouv, postes)
          choix_versions = {}
          cols_v = st.columns(len(ROLES))
          for col, (cle_r, prefixe) in zip(cols_v, ROLES.items()):
              options_v = [n for n in postes.index if n.startswith(prefixe + " – ") and "(mesuré)" not in n]
              if not options_v:
                  continue
              defaut_v = roles_actuels.get(cle_r, options_v[0])
              choix_versions[cle_r] = col.selectbox(
                  prefixe, options_v, index=options_v.index(defaut_v) if defaut_v in options_v else 0,
                  key=f"version_{nom}_{cle_r}",
                  format_func=lambda n: n.split(" – ", 1)[1].replace(" (simulé)", ""))
          nouvelles_comp = list(choix_versions.values())
          if ouv["poste_principal"].startswith("Couper") and "couper" in choix_versions:
              ouv["poste_principal"] = choix_versions["couper"]
          ouv["competences"] = nouvelles_comp
          modifie = set(nouvelles_comp) != set(ouvrieres.loc[nom, "competences"])
          if modifie:
              st.info("Profil modifié pour cette simulation (pas encore enregistré).")
              if st.button("Enregistrer ces versions dans ouvrieres.csv", key=f"save_versions_{nom}"):
                  brut = pd.read_csv(DOSSIER / "ouvrieres.csv")
                  ligne = brut["ouvriere"] == nom
                  brut.loc[ligne, "poste_principal"] = ouv["poste_principal"]
                  brut.loc[ligne, "competences"] = ";".join(nouvelles_comp)
                  brut.to_csv(DOSSIER / "ouvrieres.csv", index=False)
                  st.success("Enregistré dans ouvrieres.csv. Recharge la page (F5) pour que l'onglet HSE en tienne compte.")
      seuils = seuils_ouvriere(ouv, p)
      atteintes = [NOMS_ZONES[z] for z in ouv["zones_atteintes"]]
      c1, c2, c3 = st.columns(3)
      c1.metric("Tâche principale", ouv["poste_principal"])
      c2.metric("Zones déjà atteintes", ", ".join(atteintes) if atteintes else ("toutes (antécédent)" if ouv["antecedent_tms"] else "aucune"))
      c3.metric("Seuils de protection", " · ".join(f"{v:.0f} %" for v in sorted(set(seuils.values()), reverse=True)),
                "plus protecteur sur les zones atteintes" if len(set(seuils.values())) > 1 else None, delta_color="off")
      st.caption(f"Journée simulée : {heure_txt(p.debut)} → {heure_txt(p.fin)}, pause "
                 + ", ".join(f"{heure_txt(a)}–{heure_txt(b)}" for a, b in p.pauses)
                 + f". Même travail dans toutes les organisations : {p.panneaux_jour:.0f} panneaux "
                   f"({p.paquets_jour:.1f} paquets de {p.panneaux_par_paquet:.0f}) ; par paquet : 15 min de coupe, "
                   "7 min de classement, 3 min de chariot ; 4 rouleaux par jour. Le temps restant = autres activités "
                   "(déplacements, attente…), charge faible.")
      if ouv["poste_principal"] in exclus:
          st.error(f"La tâche principale « {ouv['poste_principal']} » est exclue : {exclus[ouv['poste_principal']]}.")

      st.subheader("Comparer l'organisation de la journée")
      resultats = {k: simuler_organisation(ouv, postes, p, k) for k in ORGANISATIONS}
      st.dataframe(pd.DataFrame([{
          "Organisation": ORGANISATIONS[k].split(" (")[0],
          "Batterie la plus basse": f"{r['minimum']:.0f} % ({r['zone_la_plus_basse']})",
          "Passe sous son seuil à": heure_txt(r["heure_alerte"]) if r["heure_alerte"] else "jamais",
          "Production": f"{r['panneaux']:.0f} panneaux ({r['paquets']:.1f} paquets)",
          "Rangement non fait": f"{r['travail_restant']:.0f} min",
          "Autres activités": f"{r['minutes_autres']:.0f} min",
          "Propositions reçues": str(r["nb_alertes"]) if k == "dynamique" else "—",
          "Micro-pauses": f"{r['nb_micro_pauses']} ({r['nb_micro_pauses'] * p.micro_pause_min} min)" if k == "dynamique" else "—",
      } for k, (_, r) in resultats.items()]), hide_index=True, width="stretch")
      st.caption("L'organisation change le MOMENT où une zone s'épuise ; seul l'aménagement du poste réduit la charge "
                 "totale (comparer les profils « poste actuel » et « poste amélioré »).")

      org = st.radio("Voir la journée", list(ORGANISATIONS), format_func=lambda k: ORGANISATIONS[k], index=2)
      sim_o, r_o = resultats[org]
      st.plotly_chart(graphe_batteries(sim_o, ORGANISATIONS[org].split(" (")[0], seuils), width="stretch")

      seg, debut_seg = [], 0
      for i in range(1, len(sim_o)):
          if sim_o["poste"].iat[i] != sim_o["poste"].iat[debut_seg] or i == len(sim_o) - 1:
              seg.append((sim_o["heure"].iat[debut_seg], sim_o["heure"].iat[i], sim_o["poste"].iat[debut_seg]))
              debut_seg = i
      couleur_tache = {"Couper": "#ef5b5b", "Ouvrir rouleau": "#a78bfa", "Classer": "#f5a142", "Transporter": "#4aa3ff",
                       "Micro-pause": "#3ecf8e", "Pause": "#94a3b8", "Autres activités": "#d1d5db"}
      fig_t = go.Figure()
      deja = set()
      for a, b, nom_t in seg:
          cle = next((c for c in couleur_tache if nom_t.startswith(c)), "Pause")
          fig_t.add_trace(go.Bar(x=[b - a], y=["Tâches"], base=[a], orientation="h", marker_color=couleur_tache[cle],
                                 name=cle, showlegend=cle not in deja, hovertemplate=f"{nom_t}<extra></extra>"))
          deja.add(cle)
      ticks_t = list(range(int(p.debut), int(p.fin) + 1))
      fig_t.update_layout(barmode="stack", height=150, margin=dict(l=10, r=10, t=10, b=10),
                          xaxis=dict(range=[p.debut, p.fin], tickvals=ticks_t, ticktext=[f"{h}h" for h in ticks_t]),
                          legend=dict(orientation="h", y=-0.6))
      st.plotly_chart(fig_t, width="stretch")

      if org == "dynamique":
          st.subheader("Ce que l'application a proposé au coupeur")
          st.caption("Simulation : on suppose que le coupeur accepte chaque proposition. En vrai, il peut choisir une autre "
                     "tâche, une pause, ou continuer (exigences H1 et H3).")
          if r_o["propositions"]:
              st.dataframe(pd.DataFrame([{"Heure": heure_txt(h), "Zone fatiguée": z, "Proposition": prop}
                                         for h, z, prop in r_o["propositions"]]), hide_index=True, width="stretch",
                           height=min(400, 40 + 35 * len(r_o["propositions"])))
          else:
              st.success("Aucune alerte : aucune zone n'a approché son seuil.")

      st.subheader("Signaler un problème")
      st.caption("H3 : le coupeur signale ; le HSE reçoit le signalement sans nom (D2).")
      with st.form(f"signal_{nom}", clear_on_submit=True):
          s1, s2 = st.columns(2)
          type_s = s1.selectbox("Quoi ?", ["J'ai mal", "Table gênante", "Éclairage insuffisant",
                                           "Ciseau / outil", "Autre"])
          zone_s = s2.selectbox("Zone (si douleur)", ["—"] + [NOMS_ZONES[z] for z in ZONES] + ["Mains / doigts"])
          if st.form_submit_button("Envoyer"):
              ligne_s = pd.DataFrame([{"semaine": datetime.now().strftime("%Y-S%W"),
                                       "poste": _tache(ouv["poste_principal"]), "type": type_s, "zone": zone_s}])
              ligne_s.to_csv(FICHIER_SIGNALEMENTS, mode="a", index=False, header=not FICHIER_SIGNALEMENTS.exists())
              st.success("Signalement envoyé, sans nom.")

      st.subheader("Check-in du soir (30 s)")
      st.caption("Douleur de 0 (aucune) à 10 (maximale) par zone, inspiré du questionnaire nordique. "
                 "Reste sur ce poste, visible par le coupeur et le médecin du travail seulement (D1).")
      fichier_perso = DOSSIER_PERSO / f"checkin_profil_{list(ouvrieres.index).index(nom) + 1}.csv"
      with st.form(f"checkin_{nom}", clear_on_submit=False):
          zones_ci = ["Cou", "Épaules", "Coudes", "Poignets", "Mains / doigts", "Dos"]
          cols_ci = st.columns(len(zones_ci))
          notes = {z: c.slider(z, 0, 10, 0, key=f"ci_{nom}_{z}") for z, c in zip(zones_ci, cols_ci)}
          if st.form_submit_button("Enregistrer ma soirée"):
              DOSSIER_PERSO.mkdir(exist_ok=True)
              pd.DataFrame([{"date": datetime.now().strftime("%Y-%m-%d"), **notes}]).to_csv(
                  fichier_perso, mode="a", index=False, header=not fichier_perso.exists())
              st.success("Enregistré dans ton bilan personnel.")
      if fichier_perso.exists():
          st.markdown("**Mon bilan (derniers jours)**")
          st.dataframe(pd.read_csv(fichier_perso).tail(7), hide_index=True, width="stretch")

      with st.expander("Rotations fixes par créneaux de 30 min (méthode précédente)"):
          st.caption("Ancienne méthode : la journée est découpée en 19 créneaux de 30 min, une tâche par créneau, en "
                     "répétant un cycle. Toujours avec la tâche principale (sinon rien n'est coupé). Elle ne tient pas "
                     "compte de la production (classer et transporter n'existent que si on a coupé) : préférer "
                     "l'organisation dynamique ci-dessus.")
          rotations, _ = generer_rotations(ouv, postes, p)
          if not rotations:
              st.warning("Aucune tâche autorisée dans ses compétences.")
          else:
              labels = [f"Option {chr(65 + i)} : {' → '.join(r['cycle'])}  |  minimum {r['minimum']:.0f} %  |  "
                        + ("sûre" if r["sure"] else "sous le seuil") for i, r in enumerate(rotations)]
              choix = st.radio("Choisir une rotation", range(len(rotations)), format_func=lambda i: labels[i])
              rot = rotations[choix]
              if not any(r["sure"] for r in rotations):
                  sugg = suggerer_formation(ouv, postes, p)
                  if sugg:
                      st.warning(f"Aucune rotation sûre. **Pour en trouver une** : {texte_suggestions(ouv, sugg)}.")
                  else:
                      st.error("Aucune rotation sûre possible : le poste doit être redessiné.")
              st.plotly_chart(graphe_batteries(rot["simulation"], "Avec la rotation choisie", seuils), width="stretch")
              st.dataframe(planning_en_tableau(rot["planning"], p), hide_index=True, width="stretch")

if onglet_hse is not None:
  with onglet_hse:
      st.subheader("Carte des postes à risque")
      fig = go.Figure(go.Heatmap(
          z=postes[ZONES].values, x=[NOMS_ZONES[z] for z in ZONES], y=list(postes.index),
          colorscale=[[0, "#3ecf8e"], [0.5, "#f5c542"], [1, "#ef5b5b"]], zmin=0, zmax=1,
          text=postes[ZONES].round(2).values, texttemplate="%{text}", hovertemplate="%{y} · %{x} : %{z:.2f}<extra></extra>"))
      fig.update_layout(height=60 + 60 * len(postes), margin=dict(l=10, r=10, t=10, b=10))
      st.plotly_chart(fig, width="stretch")

      st.subheader("Situation par poste (données agrégées)")
      st.caption("D2 : aucune donnée individuelle. Un poste suivi par moins de 5 personnes est masqué, "
                 "pour qu'on ne puisse pas reconnaître quelqu'un.")
      par_poste = {}
      for n, o in ouvrieres.iterrows():
          rots, _ = generer_rotations(o, postes, p, nb=1)
          sure = bool(rots and rots[0]["sure"])
          action = "—" if sure else texte_suggestions(o, suggerer_formation(o, postes, p))
          g = par_poste.setdefault(_tache(o["poste_principal"]), {"n": 0, "sures": 0, "actions": Counter()})
          g["n"] += 1
          g["sures"] += sure
          g["actions"][action] += 1
      st.dataframe(pd.DataFrame([{
          "Poste": poste_g,
          "Personnes suivies": g["n"] if g["n"] >= 5 else "moins de 5",
          "Avec une organisation sûre": f"{g['sures']} sur {g['n']}" if g["n"] >= 5 else "masqué",
          "Action la plus utile": g["actions"].most_common(1)[0][0] if g["n"] >= 5 else "masqué",
      } for poste_g, g in par_poste.items()]), hide_index=True, width="stretch")
      st.caption("« Équiper » = acheter ou modifier du matériel pour une tâche déjà faite. "
                 "« Former à » = apprendre une nouvelle tâche. Calculé avec les rotations fixes de 30 min "
                 "(méthode simplifiée).")

      st.subheader("Signalements reçus (sans nom)")
      if FICHIER_SIGNALEMENTS.exists():
          sig = pd.read_csv(FICHIER_SIGNALEMENTS)
          st.dataframe(sig.groupby(["poste", "type", "zone"]).size().reset_index(name="nombre")
                       .sort_values("nombre", ascending=False), hide_index=True, width="stretch")
      else:
          st.info("Aucun signalement pour l'instant.")

if onglet_ing is not None:
  with onglet_ing:
      st.subheader("Postes exclus de la rotation : à redessiner en priorité")
      if not exclus:
          st.success("Aucun poste n'est exclu avec les paramètres actuels.")
      for nom_exclu, raison in exclus.items():
          st.error(f"**{nom_exclu}** : {raison}")

      st.subheader("Comparer le poste actuel et une solution, zone par zone")
      st.caption("On simule une journée entière sur la tâche, avant et après. Ne pas regarder seulement la batterie "
                 "la plus basse : toute zone chargée à plus de ~0,6 toute la journée finit au même plancher (~33 %). "
                 "L'amélioration se voit sur les AUTRES zones, le nombre de zones sous le seuil et le temps passé dessous.")

      def _indicateurs(nom_t, table):
          sim_t = simuler([nom_t] * p.nb_creneaux, table, p)
          pas_min = float(sim_t["heure"].iat[1] - sim_t["heure"].iat[0]) * 60
          minima = sim_t[ZONES].min()
          return sim_t, {
              "minima": minima,
              "zones_sous": int((minima < p.seuil_critique).sum()),
              "minutes_sous": float((sim_t[ZONES] < p.seuil_critique).sum().sum() * pas_min),
              "moyenne": float(minima.mean()),
          }

      noms = list(postes.index)

      def _evolution(nouveau, ancien, fmt, plus_est_mieux):
          ecart = nouveau - ancien
          if round(ecart, 0) == 0:
              return dict(delta="= vs actuel", delta_color="off", delta_arrow="off")
          return dict(delta=f"{ecart:{fmt}} vs actuel", delta_color="normal" if plus_est_mieux else "inverse")

      taches_ing = [t for t in SCENARIOS if nom_poste(SCENARIOS[t]["actuel"]) in noms]
      i1, i2 = st.columns(2)
      tache_ing = i1.selectbox("Poste actuel", taches_ing, key="ing_avant",
                               format_func=lambda t: nom_poste(SCENARIOS[t]["actuel"]))
      p_avant = nom_poste(SCENARIOS[tache_ing]["actuel"])
      sim_av, ind_av = _indicateurs(p_avant, postes)

      lignes_cl = []
      for k, sc in SCENARIOS[tache_ing].items():
          n_sol = nom_poste(sc)
          if k == "actuel" or n_sol not in noms:
              continue
          _, ind = _indicateurs(n_sol, postes)
          ecarts = {z: ind["minima"][z] - ind_av["minima"][z] for z in ZONES}
          soulagees = [NOMS_ZONES[z] for z in ZONES if ecarts[z] >= 3]
          chargees = [NOMS_ZONES[z] for z in ZONES if ecarts[z] <= -3]
          lignes_cl.append({"nom": n_sol, "solution": sc.nom, "ind": ind, "soulagees": soulagees, "chargees": chargees,
                            "gain": bool(soulagees) or ind["minutes_sous"] < ind_av["minutes_sous"]})
      lignes_cl.sort(key=lambda l: (l["ind"]["minutes_sous"], l["ind"]["zones_sous"], -l["ind"]["moyenne"]))
      sans_transfert = [l for l in lignes_cl if l["gain"] and not l["chargees"]]
      recommandee = sans_transfert[0] if sans_transfert else (lignes_cl[0] if lignes_cl else None)

      def _verdict(l):
          if not l["gain"]:
              return "pas de gain"
          if l is recommandee:
              return "RECOMMANDÉE (sans transfert)" if not l["chargees"] else "meilleur compromis (transfert)"
          return "transfert de charge" if l["chargees"] else "sans transfert"

      st.markdown(f"**Toutes les solutions testées pour « {tache_ing} »** (classées de la meilleure à la moins bonne)")
      st.dataframe(pd.DataFrame([{
          "Solution": l["solution"],
          "Zones sous le seuil": f"{l['ind']['zones_sous']} (actuel {ind_av['zones_sous']})",
          "Temps sous le seuil": f"{l['ind']['minutes_sous']:.0f} min (actuel {ind_av['minutes_sous']:.0f})",
          "Zones soulagées": ", ".join(l["soulagees"]) or "—",
          "Zones plus chargées": ", ".join(l["chargees"]) or "aucune",
          "Verdict": _verdict(l),
      } for l in lignes_cl]), hide_index=True, width="stretch")
      if recommandee and recommandee["chargees"]:
          st.warning("Aucune solution ne soulage sans charger une autre zone : on garde le meilleur compromis et on "
                     f"protège {', '.join(recommandee['chargees'])} autrement (alternance de tâches, micro-pauses proposées).")

      noms_sol = [l["nom"] for l in lignes_cl]
      p_apres = i2.selectbox("Solution détaillée ci-dessous", noms_sol, key=f"ing_apres_{tache_ing}",
                             index=noms_sol.index(recommandee["nom"]) if recommandee else 0)
      sim_ap, ind_ap = _indicateurs(p_apres, postes)

      k1, k2, k3 = st.columns(3)
      k1.metric("Zones qui passent sous le seuil", ind_ap["zones_sous"],
                **_evolution(ind_ap["zones_sous"], ind_av["zones_sous"], "+d", False))
      k2.metric("Temps sous le seuil (min, toutes zones)", f"{ind_ap['minutes_sous']:.0f}",
                **_evolution(ind_ap["minutes_sous"], ind_av["minutes_sous"], "+.0f", False))
      k3.metric("Batterie moyenne des zones en fin de journée (minimum)", f"{ind_ap['moyenne']:.0f} %",
                **_evolution(ind_ap["moyenne"], ind_av["moyenne"], "+.0f", True))

      st.dataframe(pd.DataFrame([{
          "Zone": NOMS_ZONES[z],
          "Charge avant": round(float(postes.loc[p_avant, z]), 2),
          "Charge après": round(float(postes.loc[p_apres, z]), 2),
          "Batterie mini avant": f"{ind_av['minima'][z]:.0f} %",
          "Batterie mini après": f"{ind_ap['minima'][z]:.0f} %",
          "Évolution": f"{ind_ap['minima'][z] - ind_av['minima'][z]:+.0f} points",
          "Verdict": ("soulagée" if ind_ap["minima"][z] - ind_av["minima"][z] >= 3 else
                      "plus chargée (transfert)" if ind_ap["minima"][z] - ind_av["minima"][z] <= -3 else "="),
      } for z in ZONES]), hide_index=True, width="stretch")
      zones_pires = [NOMS_ZONES[z] for z in ZONES if ind_ap["minima"][z] - ind_av["minima"][z] <= -3]
      if zones_pires:
          st.warning(f"Transfert de charge vers : {', '.join(zones_pires)}. La solution soulage certaines zones mais en "
                     "charge d'autres (piège multisite) : à compléter (ex. hauteur de l'écran / du regard, pupitre).")
      g1, g2 = st.columns(2)
      g1.plotly_chart(graphe_batteries(sim_av, f"Avant : {p_avant}", p.seuil_critique), width="stretch")
      g2.plotly_chart(graphe_batteries(sim_ap, f"Après : {p_apres}", p.seuil_critique), width="stretch")

      with st.expander("Tester une modification à la main (scénario « et si… »)"):
          st.caption("Change les charges d'une tâche pour voir l'effet. Sans modification, avant = après.")
          poste_test = st.selectbox("Poste à modifier", noms, key="ing_test")
          cols = st.columns(len(ZONES))
          nouvelles = {}
          for col, z in zip(cols, ZONES):
              nouvelles[z] = col.number_input(NOMS_ZONES[z], 0.0, 1.0, float(postes.loc[poste_test, z]), 0.05,
                                              key=f"mod_{poste_test}_{z}")
          modif = postes.copy()
          for z, v in nouvelles.items():
              modif.loc[poste_test, z] = v
          _, i_av = _indicateurs(poste_test, postes)
          sim_m, i_ap = _indicateurs(poste_test, modif)
          a1, a2, a3 = st.columns(3)
          a1.metric("Zones sous le seuil", i_ap["zones_sous"], **_evolution(i_ap["zones_sous"], i_av["zones_sous"], "+d", False))
          a2.metric("Temps sous le seuil (min)", f"{i_ap['minutes_sous']:.0f}",
                    **_evolution(i_ap["minutes_sous"], i_av["minutes_sous"], "+.0f", False))
          a3.metric("Batterie moyenne (minimum)", f"{i_ap['moyenne']:.0f} %",
                    **_evolution(i_ap["moyenne"], i_av["moyenne"], "+.0f", True))
          if poste_test in exclus and poste_test not in postes_exclus(modif, p):
              st.success("Après modification, le poste peut réintégrer la rotation.")
          st.plotly_chart(graphe_batteries(sim_m, f"Simulation après modification de « {poste_test} »", p.seuil_critique),
                          width="stretch")
