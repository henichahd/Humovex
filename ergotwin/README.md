# ErgoTwin Coupe – jumeau numérique du poste de coupe (SSTHack 2026, poste 2.2, TLS)

Acteur principal : le coupeur. Le jumeau aide le coupeur à protéger son corps et aide l'entreprise à choisir
le bon aménagement, sans jamais surveiller le rendement.

## Installation et lancement

```
pip install -r requirements.txt
python -m streamlit run app.py
```

## Ce que fait l'application

| Vue | Onglet | Rôle |
|---|---|---|
| Coupeur et médecin | Mon corps (coupeur) | Batteries par zone sur la journée, 3 organisations (blocs, petits lots, dynamique), propositions du boîtier, bouton Signaler, check-in du soir |
| Les deux | Jumeau du poste | Avatar 3D : tester un réglage (taille, hauteur, profondeur…) et jouer les 4 tâches avant / après |
| Entreprise | Responsable HSE | Carte des postes à risque, situation agrégée par poste, signalements sans nom |
| Entreprise | Ingénieur conception | Toutes les solutions d'une tâche classées ; recommandée = baisse le risque sans charger une autre zone |

## Fichiers

| Fichier | Contenu |
|---|---|
| `app.py` | Tableau de bord Streamlit |
| `jumeau.py` | Modèle de fatigue à 3 compartiments (Xia & Frey Law 2008), organisations de la journée, seuils |
| `jumeau_poste.py` | Avatar 3D (proportions Drillis & Contini), angles, REBA |
| `cycle_coupe.py` | Les 4 tâches jouées par l'avatar, scénarios avant / après |
| `comparer_modele_video.py` | Calibration de l'avatar sur les angles mesurés par ErgoScan |
| `reba.py` | Score REBA (Hignett & McAtamney 2000) |
| `postes.csv` | Charge par zone (0 à 1) de chaque tâche et de chaque solution |
| `postes_reglages.csv` | Dimensions de chaque poste |
| `ouvrieres.csv` | Profils de démonstration (dont le coupeur du cahier des charges : épaules et poignets atteints) |

Créés à l'usage, jamais versionnés : `signalements.csv` (sans nom), `donnees_personnelles/` (check-in du soir).

## Exigences couvertes

| Id | Comment |
|---|---|
| H1 | Le boîtier propose, le coupeur décide ; aucune tâche automatisée |
| H2 | Interface simple ; « Boîtier allumé » : le coupeur peut l'arrêter |
| H3 | Choix de la tâche et des micro-pauses ; bouton Signaler |
| D1 | Vue coupeur et médecin séparée ; check-in stocké localement |
| D2 | Vue entreprise agrégée par poste, masquée sous 3 personnes ; signalements sans nom |
| D3 | ErgoScan : aucune vidéo enregistrée ; le bracelet ne filme pas |
| M1 | 6 zones suivies, transfert de charge détecté et signalé |
| M2 | Aménagement du poste, organisation, variété des tâches |
| M3 | REBA avant / après (avatar calibré sur la vidéo réelle, bracelet IMU pour le poignet) |
