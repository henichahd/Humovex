# Humovex – SSTHack 2026

Solution pour réduire les TMS multisites au poste **2.2 Coupe** (track textile, TLS).

Humovex mesure le poste, teste les modifications de la table sur un jumeau numérique avant de les acheter, et
aide le coupeur à protéger son corps pendant la journée, sans jamais le surveiller.

## Contenu du dépôt

| Dossier | Rôle | Lancement |
|---|---|---|
| [`ergoscan/`](ergoscan/README.md) | **ErgoScan** : mesure des postures sur vidéo (MediaPipe) et score REBA, tâche par tâche | `python ergoscan.py --source video.mp4 --poste "Coupe"` |
| [`ergotwin/`](ergotwin/README.md) | **ErgoTwin** : jumeau numérique, avatar du poste, fatigue par zone, vues coupeur, HSE et ingénieur | `python -m streamlit run app.py` |

Chaque dossier a son propre `requirements.txt` :

```
cd ergoscan && pip install -r requirements.txt
cd ../ergotwin && pip install -r requirements.txt
```

## Comment les briques s'enchaînent

1. **ErgoScan** mesure le poste réel sur une vidéo et produit les charges par zone pour chaque tâche.
2. Ces charges sont copiées dans `ergotwin/postes.csv`.
3. **ErgoTwin** rejoue les tâches sur l'avatar, teste les solutions (table plus haute, accès des deux côtés,
   organisation des tâches) et signale les transferts de charge d'une zone à une autre.
4. Le **bracelet ErgoBand** (ESP32 et deux MPU6050, sur l'avant-bras et la main) mesure la flexion et la déviation du
   poignet et calcule RULA et REBA sur le bracelet. Il vibre quand une zone approche de son seuil ; l'**application du
   coupeur** (BLE) propose une autre tâche ou une micro-pause, et le coupeur décide. La passerelle du poste ne reçoit
   que des agrégats. La reconnaissance automatique de la tâche par le bracelet est proposée, pas encore réalisée.

Détails : architecture technique (livrable 6) et calcul économique (livrable 3).

## Exigences du cahier des charges

| Id | Comment |
|---|---|
| H1, H2, H3 | L'application propose, le coupeur décide et peut arrêter l'outil ; il choisit ses tâches et ses pauses, signale une gêne |
| D1 | Données individuelles sur le téléphone du coupeur, transmises au médecin avec son accord |
| D2 | L'entreprise ne voit que des agrégats par poste, publiés à partir de 5 sessions ou 5 personnes |
| D3 | Calcul sur le bracelet ; ErgoScan traite la vidéo en local sans garder d'image |
| M1, M2, M3 | 6 zones suivies par ErgoScan et le jumeau, le poignet aussi par le bracelet ; transferts détectés ; action sur la table et l'organisation ; REBA et RULA avant / après |

## Confidentialité

Les vidéos du poste et les témoignages sont confidentiels (SSTHack 2026) : ils ne sont jamais versionnés.
Les fichiers de mesures individuelles et les données personnelles sont exclus par les `.gitignore` de chaque dossier.

## Limites

- L'avatar a été calé sur une seule vidéo et un seul coupeur.
