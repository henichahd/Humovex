# ErgoScan – mesure des postures et score REBA (SSTHack 2026, poste 2.2 Coupe, TLS)

ErgoScan analyse une vidéo de profil (ou une webcam), suit 33 points du corps avec MediaPipe, calcule les angles
par zone (cou, dos, épaules, coudes, poignets, genoux) et le score REBA image par image. Il produit la fiche du
poste, tâche par tâche, et les lignes à copier dans le jumeau numérique (`../ergotwin/postes.csv`).

Le traitement est local et aucune image n'est enregistrée (exigence D3).

## Installation

```
pip install -r requirements.txt
```

Le modèle `pose_landmarker_full.task` (MediaPipe) est téléchargé automatiquement au premier lancement.

## Utilisation

Analyser une vidéo du poste de coupe, tâche par tâche :

```
python ergoscan.py --source video.mp4 --poste "Coupe" --repetitif
```

Webcam : `--source 0`. Toutes les options : `python ergoscan.py --help`.

| Touche | Action |
|---|---|
| `1` à `4` | Tâche en cours : 1 Ouvrir rouleau, 2 Couper, 3 Classer, 4 Transporter (`0` = non précisée) |
| `c` | Calibrer quand la personne se tient droite |
| `v` | Afficher le squelette seul ou sur la vidéo |
| `i` | Afficher ou masquer les détails |
| `p` | Pause |
| `s` | Choisir une autre personne (avec `--suivre`) |
| `q` | Terminer et enregistrer les résultats |

Options utiles :

| Option | Rôle |
|---|---|
| `--rotation 90` | Redresser une vidéo filmée de travers |
| `--suivre` / `--cible 0.55,0.40` | Ne suivre qu'une personne quand plusieurs sont dans l'image |
| `--taches "A,B,C"` | Changer les noms des tâches (touches 1, 2, 3…) |
| `--charge-kg`, `--prise`, `--torsion-tronc`, `--poignet-devie`… | Ce que la caméra ne voit pas, ajouté au score REBA |

## Fichiers produits (jamais versionnés)

| Fichier | Contenu |
|---|---|
| `mesures_<poste>.csv` | Angles et REBA image par image |
| `fiche_<poste>.csv` | Résumé du poste : % du temps en zone rouge par zone |
| `reba_<poste>.csv` | Répartition des scores REBA |
| `fiche_taches_<poste>.csv` | Résumé par tâche |
| `postes_taches_<poste>.csv` | Lignes à copier dans `ergotwin/postes.csv` |

Ces fichiers contiennent des données individuelles de posture (exigence D1) : ils restent sur le poste et sont
exclus de Git.

## Autres scripts

| Script | Rôle |
|---|---|
| `valider_detection.py --source video.mp4` | Vérifie que le squelette suit bien la personne : planche de vignettes sur fond noir et taux de détection |
| `estimer_taches.py` | Calcule les charges par zone des tâches non filmées à partir de `taches_estimees.csv` |

## Code

| Fichier | Contenu |
|---|---|
| `ergoscan.py` | Programme principal : vidéo, détection, tâches, export |
| `angles.py` | Angles par zone et niveaux vert / jaune / rouge, lissage |
| `reba.py` | Score REBA (Hignett et McAtamney, 2000) |
| `affichage.py` | Squelette, étiquettes et palettes de couleurs |

## Limites

- Vidéo 2D de profil : les torsions et inclinaisons latérales ne sont pas mesurées, elles sont ajoutées en option.
- Le poignet est mal vu par la caméra : il est mesuré par le bracelet (voir le README principal).