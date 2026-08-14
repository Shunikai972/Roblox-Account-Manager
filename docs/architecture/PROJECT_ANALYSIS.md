# Analyse du projet — Astro Account Manager

État vérifié le 14 août 2026 depuis `D:\Noam\Downloads\Code Account manager`.

## Sources de vérité

- distribution locale RAM 3.7.2 : `Roblox.Account.Manager.3.7.2/` ;
- source publique : tag `3.7.2`, commit `79f61f3351df61fb3774dfa854ab868954da5389` ;
- UWP : le binaire 3.7.2 contient des types absents du tag ; le commit public `73a291e` fournit `UWPInstanceManager.cs` comme référence complémentaire ;
- comportement vérifié dans `AccountManager.cs`, `Account.cs`, `AccountUtils.cs`, `AccountBrowser.cs`, `ServerList.cs`, `RobloxWatcher.cs`, `SettingsForm.cs`, `ClientSettingsPatcher.cs`, `Nexus/*`, `RAMAccount.lua` et les classes API/launcher.

Le dossier historique local est une distribution .NET Framework/WinForms compilée, pas le projet source. Le dépôt public détaché a donc été utilisé en lecture seule pour retrouver les comportements, sans modifier les fichiers RAM.

## Architecture actuelle

| Couche | Astro |
|---|---|
| Desktop | `main.py`, fenêtre pywebview locale, frontend embarqué |
| UI | HTML/CSS/JavaScript, bridge unique, preview explicitement distinct du desktop |
| Cas d’usage | `ApplicationService`, validation et erreurs de domaine |
| Stockage | SQLite versionnée/WAL pour les métadonnées ; vault DPAPI `CurrentUser` pour les secrets |
| Roblox | clients publics/authentifiés bornés, launcher Windows, browser Edge/CDP, UWP, ClientSettings |
| Processus | état PID+create-time, association d’intentions, logs typés, relance, règles de fenêtre |
| Intégrations | API HTTP loopback authentifiée et Nexus WebSocket authentifié |
| Livraison | PyInstaller onefile windowed avec frontend, webview, websockets, sqlite3 et ctypes |

Le chemin fonctionnel UI est contrôlé de bout en bout :

`backend → ApplicationService → DesktopBridge → bridge.js → app.js → UI`.

Un hôte pywebview détecté mais tardif n’est plus remplacé silencieusement par le mode Preview. Le frontend attend le bridge natif et affiche une erreur explicite si l’injection échoue.

## Comportements historiques retrouvés et portés

### Comptes, authentification et lancement

- ajout par cookie validé contre l’identité authentifiée ; secret protégé avant persistance ;
- navigateur Edge/Chrome isolé avec port CDP dynamique, profil temporaire et capture HttpOnly ;
- extension Chromium de solveur CAPTCHA facultative dans ce profil via `ASTRO_CAPTCHA_SOLVER_EXTENSION` ;
- OAuth Open Cloud PKCE comme fonction Astro additionnelle, sans le présenter comme une session du client Roblox ;
- affichage/copie/export plaintext volontaire d’une session, refresh d’identité et bulk import borné ;
- ticket, CSRF, URI `rbx-player`, PlaceId, JobId, VIP, Follow, serveur aléatoire et file de lancement ;
- intention enregistrée avant le handoff Windows, priorité de cible propre au compte et réconciliation des faux états `in_game` ;
- mutex historique et gestion de l’événement singleton moderne pour le mode multi-instance, vérifiés avec deux comptes et deux clients simultanés.

### Jeux et serveurs

Le scan historique d’un joueur dans les serveurs a été retrouvé dans `ServerList.cs` : pagination par 100, transformation des `playerTokens` en requêtes `/v1/batch`, puis comparaison de l’URL de miniature avec le headshot public cible. Astro porte le même algorithme avec nombre de pages borné, lots de 100 et sans exposer les tokens opaques au bridge. La recherche de jeux utilise désormais l’endpoint Roblox Omni Search actuel avec cache 60 secondes ; l’ancien `/v1/games/list`, qui répondait 404, n’est plus appelé.

### Watcher et fenêtres

`RobloxWatcher.cs` attendait 30 secondes, ignorait la fenêtre active, pouvait tuer un processus sous un seuil mémoire ou avec un titre inattendu, capturait quatre champs `Window_*`, puis `Account.AdjustWindowPosition` réessayait pendant 45 secondes.

Astro fournit l’équivalent adapté à son architecture :

- détection PID+date de création, scan partiel sans faux exit et association prudente compte/PID ;
- règles mémoire, titre et instance non associée, toutes désactivées par défaut et doublement bornées par `termination_enabled` + option individuelle ;
- vérification du nom du processus et de la fenêtre visible, fenêtre active ignorée, terminaison gracieuse sans `kill` forcé ;
- géométrie persistée par compte, capture après 30 secondes et restauration réessayée jusqu’à 45 secondes ;
- actions manuelles Save/Restore et Close accessibles depuis Instances ;
- lecture incrémentale bornée des logs Roblox avec association multi-processus par horodatage de création ;
- auto-relaunch borné/doublement opt-in qui réutilise la session et la cible du compte.

### Nexus, API et UWP

- Nexus expose le serveur WebSocket, handshake/identité, Ping/Log/Echo/Set*, execute, teleport, mute/unmute et le script `RAMAccount.lua`, avec jeton éphémère et messages bornés ;
- l’API porte les 22 routes RAM en texte brut, `/v2`, REST v1, bearer, permissions distinctes et bind LAN explicitement opt-in ;
- UWP découvre/lance les paquets et porte les clones par compte avec staging, manifeste, register/unregister exact et rollback ; aucun paquet UWP local n’est présent pour la preuve terrain.

## Sécurité conservée

- les sessions, mots de passe sauvegardés et grants OAuth sont protégés par DPAPI et ne figurent pas dans les payloads ordinaires ;
- logs, diagnostics, backups et transfert de métadonnées sont redacted/public-only ;
- l’affichage/export brut de session existe uniquement par des actions explicites ; l’API exige en plus `allow_get_cookie` ;
- l’API écoute `127.0.0.1` par défaut ; l’exposition LAN exige un opt-in séparé et conserve bearer/permissions ;
- Nexus exige son jeton de session et n’accepte pas un client non identifié ;
- les erreurs réseau ne reflètent ni corps distant, ni cookie, ni chemin sensible.

## État honnête

La matrice canonique contient 85 fonctionnalités : 48 `VERIFIED PARITY`, 0 `PARTIAL`, 37 `TESTED BUT NOT VERIFIED`, 0 `MISSING`, 0 `BLOCKED`.

`TESTED BUT NOT VERIFIED` signifie qu’un comportement existe et possède des tests sans preuve réelle suffisante pour cette ligne. Les derniers portages couvrent le login par mot de passe importé via Edge CDP, les clones UWP, la sonde région historique, le client Lua Nexus et les réponses exactes de l’API legacy. Leurs preuves restantes dépendent respectivement d’un mot de passe importé, d’un paquet UWP, d’un essai réseau authentifié choisi, et d’un client Nexus en jeu ; aucune ligne portable ne reste `PARTIAL`.

Voir [la matrice exhaustive](../user-guide/FEATURE_MATRIX.md), [la validation individuelle des 42 lignes](../QA_MATRIX_2026-08-11.md), [le registre de portage](../PORTING_LEDGER.md) et [l’audit final](FINAL_AUDIT.md).
