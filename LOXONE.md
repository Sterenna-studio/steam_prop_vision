# Communication Loxone — catalogue de messages

> Référence complète des échanges UDP entre STYX et la Miniserver Loxone.
> Tous les ports/IP sont configurables dans [`config/features.yaml`](config/features.yaml)
> (`loxone_ip`, `loxone_port`, `udp_listen_port`).

## Vue d'ensemble

```
STYX (Pi 5)                              Loxone (Miniserver)
  |-- STEAM_CARD_xxx / STEAM_DETECT_xxx -->|   port loxone_port (déf. 7777)
  |<---------------- ACK:<message même texte> --|   (optionnel, voir plus bas)
  |
  |-- STEAM_RUN_OK (broadcast, /5s) ------->|   port broadcast (9999)
  |
  |<--- STEAM_PING / STEAM_RESET / --------|   port udp_listen_port (déf. 8888)
  |     STEAM_TRIGGER:<card_id>            |
  |-- STEAM_PONG (réponse à PING) -------->|   port loxone_port
```

## 1. STYX → Loxone (déclenchements)

| Message | Origine | Quand |
|---|---|---|
| `STEAM_CARD_<NOM>` | `action.message` explicite dans `config/rules.yaml` (ex. `STEAM_CARD_BOUGIE`) | Carte reconnue et maintenue `card_hold_ms`, une action `type: udp` existe pour ce `card_id` |
| `STEAM_DETECT_<CARD_ID>` | Généré automatiquement (`card_id.upper()`) | Carte reconnue mais **aucune règle** définie pour elle dans `rules.yaml` (fallback), ou mode `person` sans message explicite |
| `STEAM_RUN_OK` | `steamcore.udp.HeartbeatThread`, broadcast LAN (pas ciblé sur `loxone_ip`) | Toutes les 5s tant que `enable_heartbeat: true`, indépendant de toute détection |
| `STEAM_PONG` | Réponse à `STEAM_PING` (voir §3) | Sur demande de Loxone |

`STEAM_VISION READY`/`FLUX INATTENDU` (validation QR GM) et le bandeau
`plate_ready_check` **ne génèrent aucun message UDP** — visuels uniquement sur
`/view`, volontairement (voir README.md).

## 2. Fiabilité — ACK et retry

Les messages de la section 1 partent toujours en fire-and-forget
(`send_event`) **et** sont doublés d'une attente d'accusé de réception
(`send_event_reliable`, dans `steamcore/udp.py`) :

1. STYX envoie le message normalement (ex. `STEAM_CARD_BOUGIE`).
2. Si Loxone répond `ACK:STEAM_CARD_BOUGIE` sur `udp_listen_port` dans la
   seconde, c'est validé.
3. Sinon, STYX **renvoie le même message** (jusqu'à 2 fois en plus par
   défaut), puis abandonne en loggant une erreur et en poussant un event
   monitor `udp_ack_failed` si aucun ACK n'est jamais reçu.

**Important — sans configuration côté Loxone, ce mécanisme est invisible et
sans risque** : Loxone continue de recevoir le message normalement (au pire,
il est envoyé jusqu'à 3 fois au lieu d'1 si aucun ACK n'arrive jamais). Pour
activer la confirmation, programmer côté Miniserver : à la réception d'un
message STYX sur le Virtual Input existant, renvoyer immédiatement
`ACK:<texte reçu tel quel>` vers STYX sur le port `udp_listen_port`
(8888 par défaut). Aucune modification du format des messages existants
n'est nécessaire — l'ACK est un message séparé, pas un préfixe/suffixe ajouté
au message d'origine.

## 3. Loxone → STYX (commandes)

Reçues sur `udp_listen_port` (8888 par défaut), traitées par
`_handle_loxone_command()` dans `apps/rpi/main.py` :

| Commande | Effet | Réponse |
|---|---|---|
| `STEAM_PING` | Aucun effet sur le pipeline | `STEAM_PONG` immédiat vers `loxone_port` — health-check à la demande, sans attendre le prochain heartbeat (jusqu'à 5s) |
| `STEAM_RESET` | Force le retour à `IDLE` au prochain tick de boucle (~frame suivante) : arrête vidéo/audio en cours, réinitialise la détection | Aucune (voir event WS `state: IDLE`) |
| `STEAM_TRIGGER:<card_id>` | Rejoue les actions de `<card_id>` définies dans `rules.yaml`, **sans** montrer la carte physique (ex. `STEAM_TRIGGER:plate_vampire`) | Les actions elles-mêmes (vidéo/audio/UDP) |
| `ACK:<message>` | Intercepté avant `on_message` — jamais transmis comme commande | Débloque `send_event_reliable()` en attente (§2) |
| Tout autre texte | Loggé (`[UDP RX]`) + event WS `udp_rx`, aucune action | — |

`STEAM_TRIGGER` réutilise directement `run_actions()` — mêmes règles,
mêmes seuils de `rules.yaml`, aucune duplication de logique avec la
détection carte normale. Aucune limite de fréquence appliquée (cohérent avec
le reste du pipeline, où `cooldown`/`min_duration` de `rules.yaml` ne sont
pas non plus appliqués aujourd'hui — voir README.md).

## 4. Ce qui reste à faire côté Loxone (hors dépôt)

Cette liste est **côté Miniserver**, pas dans ce dépôt — à programmer dans
Loxone Config :

- [ ] Virtual Input(s) existants pour `STEAM_CARD_xxx`/`STEAM_DETECT_xxx` :
      ajouter l'envoi retour `ACK:<texte>` pour activer la fiabilité (§2).
- [ ] Décider si/quand Loxone doit envoyer `STEAM_RESET` (ex. bouton
      physique GM, fin de session programmée) ou `STEAM_TRIGGER:<card_id>`
      (ex. rejouer un effet depuis un panneau tactile Loxone).
- [ ] Surveiller l'absence de `STEAM_RUN_OK` (heartbeat) comme signal de
      crash/coupure STYX — déjà émis, juste à câbler côté Loxone si pas
      déjà fait.

Non testé avec une vraie Miniserver Loxone depuis ce poste de dev (pas
d'accès réseau à une installation réelle) — la validation ci-dessus a été
faite avec deux sockets UDP en boucle locale simulant Loxone.
