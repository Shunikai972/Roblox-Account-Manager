# Astro Account Manager

Astro Account Manager est une conversion desktop moderne et fidèle de Roblox
Account Manager 3.7.2. L'application reste locale : Python 3.12, pywebview,
SQLite, DPAPI Windows et une interface HTML/CSS/JavaScript.

L'objectif est une parité fonctionnelle prouvée, jamais un « 100 % » déclaré
sur la base de mocks. La [matrice canonique](docs/user-guide/FEATURE_MATRIX.md)
compte actuellement 48 fonctionnalités `VERIFIED PARITY`, aucune `PARTIAL` et
37 `TESTED BUT NOT VERIFIED`. Ces dernières sont implémentées et testées, mais
attendent encore un prérequis externe précis. Les preuves sont détaillées dans le
[rapport QA du 11 août 2026](docs/QA_MATRIX_2026-08-11.md).

## Fonctionnalités principales

- comptes réels par cookie validé ou navigateur Edge/CDP dédié, profils locaux
  et OAuth Open Cloud PKCE ;
- extension Chromium de solveur CAPTCHA facultative dans le profil de connexion
  isolé via `ASTRO_CAPTCHA_SOLVER_EXTENSION` ;
- sessions et mots de passe hors SQLite dans le vault DPAPI `CurrentUser` ;
- affichage, copie et export volontaire de sessions brutes, tickets
  d'authentification et liens `rbx-player` ;
- lancement authentifié par compte, PlaceId/JobId propre à chaque compte,
  serveur privé, Follow, serveur aléatoire et file de lancement ;
- multi-instance par mutex historique et événement singleton moderne, vérifié avec
  deux comptes, deux PID et deux Place ID distincts ;
- watcher processus/logs, association PID, fermeture, règles mémoire/titre/
  timeout opt-in, géométrie par compte et auto-relaunch ;
- groupes, tri persistant, recherche, alias, descriptions, champs, avatars et
  présence ;
- utilitaires authentifiés : mot de passe, email, sessions, display name, amis,
  blocage, confidentialité, PIN, avatar et Quick Log In ;
- Nexus WebSocket avec handshake authentifié et commandes RAM/Lua ;
- découverte et clones UWP confirmés, ClientSettings/FPS natif et positionnement de fenêtres ;
- API loopback/LAN opt-in compatible RAM, bearer obligatoire et permissions séparées ;
- migration 3.7.2, backups vérifiés, restauration confirmée et transfert de
  métadonnées publiques.

## Exécution depuis les sources

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

## Validation

```powershell
python -m pytest -q
python -m compileall -q app main.py scripts\build_windows.py
node --check app/frontend/src/app.js
node --check app/frontend/src/bridge.js
```

Dernier résultat complet : **360 tests passés, 2 ignorés**, sans lancer ni fermer Roblox.

## Build Windows

```powershell
python -m pip install ".[dev]"
python scripts/build_windows.py
```

Artefact actuel : `dist/AstroAccountManager.exe`, 20 781 538 octets,
SHA-256
`39B85AAED6286CB3C375CBE4EF7C5B6837166ABECBCA0D09B9A1A0E6C4A07D23`.

Consultez aussi [l'audit d'intégration](docs/architecture/FINAL_AUDIT.md), le
[registre de portage](docs/PORTING_LEDGER.md) et la
[documentation API](docs/API.md) avant toute distribution.

## Licence

GPL-3.0-or-later. Voir [LICENSE](LICENSE).

## Ecran Fleet

Depuis le 14 aout 2026, une seule entree de barre laterale, **Fleet**, regroupe
neuf onglets pour piloter une flotte sans surcharger l'interface :

- **Statistiques** : tableau de bord, heatmap horaire, score de fiabilite par
  compte, taux de reussite des macros, comparaison de deux sessions ;
- **Planification** : taches horaires par jour (lancer un groupe a 18:00,
  arreter les macros a 23:00) ;
- **Sante** : session expiree, authentification requise, echec de lancement,
  avec tags filtrables, champs personnalises et priorite ;
- **Serveurs** : inspecteur JobId, historique, liste noire, choix intelligent et
  affinite de region ;
- **Coordination** : Spread, Main + followers, lancement synchronise, party
  interne ;
- **Confort** : Focus, Sleep, mixer par instance, arret securise, file de
  lancement gardee par CPU et memoire ;
- **Alertes** : webhook Discord, relais telephone, rapport quotidien ;
- **Regles** : ce que l'automatisation peut faire, ce qu'elle vient de faire, et
  ce qu'elle ne fera jamais ;
- **Studio de macros** : debogueur pas-a-pas, profiler, profils de touches,
  variables par compte, versions et retour arriere, execution par groupe.

L'editeur visuel de macros accepte desormais les blocs Condition, Launch,
Teleport et Restart, disponibles aussi en DSL (`IF ... END`, `LAUNCH`,
`TELEPORT`, `RESTART`).

Ce que cette version ne pretend pas faire : envoyer des entrees a une fenetre
minimisee, appliquer un volume par processus, inviter dans une vraie party
Roblox, ni fermer un client vivant sans geste humain. Les details et les preuves
encore dues sont dans la
[matrice fonctionnelle](docs/user-guide/FEATURE_MATRIX.md) et le
[rapport QA](docs/QA_MATRIX_2026-08-11.md).

## v11

Three things changed, and one of them is a habit rather than a feature.

1. **Launch profiles** — *Fleet → Launch profiles*. Save a destination once
   (place, optional JobId or private code, optional FPS target, a group, a note)
   and launch it later in one click. The launch is handed to the wave launcher,
   so the concurrency cap and the pauses you configured still rule the pace.
2. **Emergency stop** — the red button at the bottom of *Fleet → Comfort* stops
   every macro, cancels the launch queue, drops pending macro resumes and
   disarms the automatic rules. It does not close a single Roblox client, on
   purpose: that is your call, never the app's.
3. **A dashboard that admits what it does not know** — a client that is in a game
   with no macro on it, past the sleep delay, is shown as *In game, unattended*.
   Roblox does not share a player's idle timer, so the label says "unattended"
   instead of pretending to know the player is AFK.

And the habit: `python scripts/feature_inventory.py` verifies every feature this
project claims to ship against a real symbol in the source tree, then
`--markdown` regenerates `docs/user-guide/FEATURE_INVENTORY.md`. If a refactor
drops a feature, that command turns red instead of the documentation quietly
lying.
