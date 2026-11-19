# ErgoTwin Coupe – SSTHack 2026

Solution pour réduire les TMS multisites au poste **2.2 Coupe** (track textile, TLS).

ErgoTwin mesure le poste, teste les modifications de la table sur un jumeau numérique avant de les acheter, et
aide le coupeur à protéger son corps pendant la journée, sans jamais le surveiller.

## Contenu du dépôt

| Dossier | Rôle | Lancement |
|---|---|---|
| [`ergoscan/`](ergoscan/README.md) | Mesure des postures sur vidéo (MediaPipe) et score REBA, tâche par tâche | `python ergoscan.py --source video.mp4 --poste "Coupe"` |
| [`ergotwin/`](ergotwin/README.md) | Jumeau numérique : avatar du poste, fatigue par zone, vues coupeur, HSE et ingénieur | `python -m streamlit run app.py` |

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
4. Le **bracelet ErgoBand** (ESP32 + MPU6050) mesure l'angle du poignet et sa part du REBA. Le **boîtier de table**
   propose une autre tâche ou une micro-pause ; le coupeur décide. La reconnaissance automatique de la tâche par
   le bracelet est proposée, pas encore réalisée.

## Exigences du cahier des charges

| Id | Comment |
|---|---|
| H1, H2, H3 | Le boîtier propose, le coupeur décide et peut l'éteindre ; il choisit ses tâches et ses pauses, signale une gêne |
| D1 | Données individuelles au coupeur et au médecin du travail seulement |
| D2 | L'entreprise ne voit que des moyennes par poste, masquées sous 3 personnes |
| D3 | Traitement local ; aucune image enregistrée |
| M1, M2, M3 | 6 zones suivies ensemble, transferts détectés ; action sur la table et l'organisation ; REBA avant / après |

## Confidentialité

Les vidéos du poste et les témoignages sont confidentiels (SSTHack 2026) : ils ne sont jamais versionnés.
Les fichiers de mesures individuelles et les données personnelles sont exclus par les `.gitignore` de chaque dossier.

## Limites

- L'avatar a été calé sur une seule vidéo et un seul coupeur.
