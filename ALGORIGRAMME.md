# Algorigramme — S.T.E.A.M Vision

Fonctionnement complet du système, de l'acquisition caméra au déclenchement des effets.

> Mis à jour le 2026-07-18 pour refléter le code réel de `apps/rpi/main.py`
> (le diagramme précédent décrivait une architecture antérieure — modes
> `card_first`/`legacy`, états `INSPECTION`/`TRIGGERED` — qui n'existe plus).

---

## Pipeline principale — mode `card` (`pipeline_mode: "card"`, défaut STYX)

Pas de vérification de présence joueur (YOLO) dans ce mode : uniquement piloté
par la détection de carte.

```mermaid
flowchart TD
    A([🟢 Démarrage]) --> B[boot_checks + Initialisation\nPicamera2 · ORB · UDP · WebSocket]
    B --> C[/Lecture frame\nIMX708/]
    C --> D{État = STANDBY ?}
    D -- OUI --> D2{Vidéo finie\nET idle_after_s écoulé ?}
    D2 -- NON --> C
    D2 -- OUI --> E0[Retour IDLE]
    E0 --> C

    D -- NON, IDLE --> E[🔍 L1 — FastDetector\nContours + Canny, scan losange]
    E --> G{Losange détecté ?}
    G -- NON --> Reset[Reset streak consécutive] --> C

    G -- OUI --> L[🔎 L2 — CardDetector\nbackend ORB par défaut + homographie RANSAC\nWarp 400×400 normalisé]
    L --> M{Warp valide\n≥ card_min_matches ?}
    M -- NON --> Reset

    M -- OUI --> N[🧠 L3 — CardRecognizer\nORB matching warp vs images PLATEST\nmeilleur score parmi toutes les images]
    N --> O{Score ORB ≥ card_score_threshold\nET matches ≥ min_matches ?}
    O -- NON --> Reset
    O -- OUI --> P{Même card_id que\nla frame précédente ?}
    P -- NON --> Restart[Nouvelle streak\nconsec_count = 1] --> C
    P -- OUI --> Q{consec_count ≥\ncard_consec_frames ?}
    Q -- NON --> C
    Q -- OUI --> R[✅ Carte confirmée\nDémarre/poursuit le hold]
    R --> S{held_ms ≥ card_hold_ms ?}
    S -- NON --> C

    S -- OUI --> T[🚀 TRIGGER\nrun_actions : lookup config/rules.yaml]
    T --> U[📡 UDP → Loxone] & V[🎬 Vidéo mpv] & W[🔊 Audio] & X[📺 WS card_detected]
    U & V & W & X --> Y[État = STANDBY]
    Y --> C
```

---

## Pipeline — mode `person` (`pipeline_mode: "person"`)

Mode alternatif exclusif — un seul des deux modes tourne à la fois, sélectionné
par `pipeline_mode` dans `config/features.yaml`.

```mermaid
flowchart TD
    A([IDLE]) --> B[YOLODetector.detect_persons]
    B --> C[PersonTracker.update]
    C --> D{ready_for_inspect ?\nprésence continue ≥ person_duration}
    D -- NON --> A
    D -- OUI --> E[🚀 TRIGGER\nrun_actions cible = 'person']
    E --> F[Audio + UDP + WS]
    F --> G[État = STANDBY\nattend idle_after_s]
    G --> A
```

---

## Machine à états réelle

```mermaid
stateDiagram-v2
    [*] --> IDLE : Démarrage

    IDLE --> IDLE : Aucune carte confirmée / joueur pas encore prêt
    IDLE --> STANDBY : TRIGGER (carte confirmée ou joueur présent selon le mode)

    STANDBY --> IDLE : Vidéo terminée ET idle_after_s écoulé

    note right of IDLE : Détection active (L1→L2→L3 ou YOLO)
    note right of STANDBY : Détection suspendue\nUDP · Vidéo · Audio en cours
```

Pas d'état `INSPECTION` ni `TRIGGERED` distinct dans le code actuel — seulement
`IDLE` et `STANDBY` (`class State(Enum)` dans `apps/rpi/main.py`).

---

## Détail détection carte (L2 → L3)

```mermaid
flowchart LR
    subgraph L2 [L2 — CardDetector, backend ORB par défaut]
        A2[ROI recadrée par L1] --> B2[Extraction keypoints ORB]
        B2 --> C2[BFMatcher vs templates PLATEST]
        C2 --> D2{≥ card_min_matches\npoints correspondants ?}
        D2 -- OUI --> E2[Homographie RANSAC\n4 coins → warp]
        E2 --> F2[Patch normalisé\n400×400 px]
    end

    subgraph L3 [L3 — CardRecognizer ORB]
        F2 --> G3[ORB matching\nwarp vs CHAQUE image du dossier PLATEST/plate_xxx/]
        G3 --> H3[Meilleur score\nparmi toutes les images testées]
        H3 --> I3{Score ≥ threshold\nET matches ≥ min_matches ?}
        I3 -- OUI --> J3[Card identifiée ✅\ncard_id · score · matches]
        I3 -- NON --> K3[Rejeté ❌]
    end
```

> Le backend SIFT existe dans `CardDetector`/le pipeline `RecognitionPipeline`
> mais n'est pas utilisé par `apps/rpi/main.py` en production (il instancie
> `CardDetector()` sans préciser de backend → ORB par défaut, et n'appelle
> jamais `load_config()` dessus). La dépendance `opencv-contrib-python`
> documentée comme "requise pour SIFT" n'est donc pas nécessaire pour la
> configuration de production actuelle.

---

## Communication réseau

```mermaid
flowchart LR
    STYX["🖥️ STYX\n(Raspberry Pi 5)"]

    STYX -->|UDP port 8888\nSTEAM_CARD_xxx| LOX[🏠 Loxone\nBox domotique]
    STYX -->|UDP Heartbeat\nSTEAM_RUN_OK toutes 5s| LOX
    LOX -->|UDP commandes retour\nport 8888| STYX

    STYX -->|WebSocket\nws://STYX:8889| MON[📊 Monitor\nNavigateur / Dashboard]

    STYX -->|mpv IPC socket| VID[🎬 VideoPlayer\nPlein écran HDMI]
```

---

## Ajout d'une nouvelle plate

```mermaid
flowchart TD
    S([Nouvelle plaque physique]) --> P[📸 Photographier la plaque\n10-15 photos, angles variés]
    P --> CP[Copier dans\nPLATEST/plate_xxx/]
    CP --> SPLIT[Lancer split_plate.py\nou add_plate.sh]
    SPLIT --> QUADS[Génération quadrants\ntop / bottom / left / right]
    QUADS --> AUG[Augmentation\ngenerate_samples.py --count 15]
    AUG --> BENCH[Validation bench\nplate_bench.py --pi]
    BENCH --> OK{Score\nsatisfaisant ?}
    OK -- NON --> P
    OK -- OUI --> CFG[Ajouter dans\nconfig/rules.yaml]
    CFG --> PROD([✅ Plate opérationnelle])
```

> ⚠️ `plate_bench.py` valide via `steamcore.recognition.pipeline.RecognitionPipeline`
> (orchestrateur threadé avec expiration TTL), qui n'est **pas** celui utilisé par
> `apps/rpi/main.py` en production (boucle séquentielle avec confirmation par
> frames consécutives + maintien `card_hold_ms`). Le matching bas niveau
> (`CardDetector`/`CardRecognizer`) est identique dans les deux cas, mais le
> timing de confirmation diffère — un score jugé "satisfaisant" au bench ne
> garantit pas exactement le même comportement en prod. À unifier ou à
> documenter explicitement.
