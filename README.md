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

Artefact actuel : `dist/AstroAccountManager.exe`, 20 774 084 octets,
SHA-256
`EC68F3995DC9B6A7BBE470D64337585E57EEFDCA879E965BE46E9B06F093F0BA`.

Consultez aussi [l'audit d'intégration](docs/architecture/FINAL_AUDIT.md), le
[registre de portage](docs/PORTING_LEDGER.md) et la
[documentation API](docs/API.md) avant toute distribution.

## Licence

GPL-3.0-or-later. Voir [LICENSE](LICENSE).
