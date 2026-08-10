# Matrice des Fonctionnalités — Astro Account Manager (Parité RAM 3.7.2 & Developer API)

Cette matrice recense l’intégralité des fonctionnalités de **Roblox Account Manager (RAM) 3.7.2** et de sa **Developer API officielle**, comparées à leur implémentation réelle dans **Astro Account Manager**.

## Convention de statut

- `[VERIFIED PARITY]` : La fonctionnalité existe et son comportement est réellement équivalent.
- `[PARTIAL]` : Une partie du comportement existe mais il manque une capacité spécifique (ex: navigateur WebView autonome).
- `[TESTED BUT NOT VERIFIED]` : Le code et les tests existent mais requièrent un environnement physique (vrai client Roblox Windows, session active `.ROBLOSECURITY` ou serveur WebSocket en jeu).
- `[MISSING]` : La fonctionnalité n'existe pas.
- `[BLOCKED]` : Non portable pour une raison technique.

---

## 1. Authentification & Compte

| Fonctionnalité | Source RAM 3.7.2 | Astro Account Manager | Statut |
|---|---|---|---|
| Authentification OAuth 2.0 PKCE | `AccountManager.cs` | `roblox/oauth.py`, callback loopback local | `[VERIFIED PARITY]` |
| Importation utilisateur:motdepasse:cookie | `AccountManager.cs` | `storage/bulk_import.py`, parseur multi-format | `[VERIFIED PARITY]` |
| Export / Import de métadonnées | Fichiers RAM | `storage/metadata_transfer.py` JSON versionné | `[VERIFIED PARITY]` |
| Chiffrement Windows DPAPI | `Cryptography.cs` | `security/dpapi.py` `CurrentUserDPAPI` | `[VERIFIED PARITY]` |
| Parcours avec navigateur embarqué | `AccountBrowser.cs` | Opt-in OAuth PKCE (navigateur embarqué direct non requis) | `[PARTIAL]` |

---

## 2. Developer API Officielle GitBook 1:1

| Endpoint Developer API | Documentation GitBook | Implémentation Loopback Astro | Statut |
|---|---|---|---|
| `LaunchAccount` | `GET /LaunchAccount` | `loopback.py` + `launch_account()` | `[TESTED BUT NOT VERIFIED]` |
| `FollowUser` | `GET /FollowUser` | `loopback.py` + `search_players` & `get_player_presence` | `[TESTED BUT NOT VERIFIED]` |
| `SetServer` | `GET /SetServer` | `loopback.py` + update `saved_place_id` & `saved_job_id` | `[VERIFIED PARITY]` |
| `SetRecommendedServer` | `GET /SetRecommendedServer` | `loopback.py` + `RandomServerSelector` | `[TESTED BUT NOT VERIFIED]` |
| `BlockUser` | `GET /BlockUser` | `loopback.py` + `AccountUtils.block_user` | `[TESTED BUT NOT VERIFIED]` |
| `UnblockUser` | `GET /UnblockUser` | `loopback.py` + `AccountUtils.unblock_user` | `[TESTED BUT NOT VERIFIED]` |
| `UnblockEveryone` | `GET /UnblockEveryone` | `loopback.py` + `AccountUtils.unblock_everyone` | `[TESTED BUT NOT VERIFIED]` |
| `GetBlockedList` | `GET /GetBlockedList` | `loopback.py` + `AccountUtils.get_blocked_users` | `[TESTED BUT NOT VERIFIED]` |
| `GetField` | `GET /GetField` | `loopback.py` + métadonnées SQLite | `[VERIFIED PARITY]` |
| `SetField` | `GET /SetField` | `loopback.py` + métadonnées SQLite | `[VERIFIED PARITY]` |
| `RemoveField` | `GET /RemoveField` | `loopback.py` + suppression métadonnée | `[VERIFIED PARITY]` |
| `SetAlias` | `GET /SetAlias` | `loopback.py` + modification `display_name` | `[VERIFIED PARITY]` |
| `GetAlias` | `GET /GetAlias` | `loopback.py` + consultation `display_name` | `[VERIFIED PARITY]` |
| `SetDescription` | `GET /SetDescription` | `loopback.py` + modification `description` | `[VERIFIED PARITY]` |
| `GetDescription` | `GET /GetDescription` | `loopback.py` + consultation `description` | `[VERIFIED PARITY]` |
| `AppendDescription` | `GET /AppendDescription` | `loopback.py` + concaténation `description` | `[VERIFIED PARITY]` |
| `SetAvatar` | `GET /SetAvatar` | `loopback.py` + `AccountUtils.set_avatar` | `[TESTED BUT NOT VERIFIED]` |
| `GetCookie` | `GET /GetCookie` | `loopback.py` + `get_account_cookie` | `[VERIFIED PARITY]` |
| `GetAccounts` | `GET /GetAccounts` | `loopback.py` + liste des pseudos | `[VERIFIED PARITY]` |
| `GetAccountsJson` | `GET /GetAccountsJson` | `loopback.py` + liste des comptes JSON | `[VERIFIED PARITY]` |
| `GetCSRFToken` | `GET /GetCSRFToken` | `loopback.py` + `generate_auth_ticket` | `[TESTED BUT NOT VERIFIED]` |
| `ImportCookie` | `GET /ImportCookie` | `loopback.py` + `import_bulk_accounts` | `[VERIFIED PARITY]` |

---

## 3. Client, Processus & Lancement

| Fonctionnalité | Source RAM 3.7.2 | Astro Account Manager | Statut |
|---|---|---|---|
| Plafond FPS (`TargetFps`) | `ClientSettingsPatcher.cs` | `ClientSettingsPatcher` (`ClientAppSettings.json`) | `[VERIFIED PARITY]` |
| Multi-Instance Mutex | `AccountManager.cs` | `WindowsMultiInstanceController` poignées Win32 | `[TESTED BUT NOT VERIFIED]` |
| Lancement en lot (`Batch Launch`) | `Classes/Batch.cs` | `BatchLauncher` file d'attente asynchrone | `[VERIFIED PARITY]` |
| Serveurs Privés / Links VIP | `ServerList.cs` | `PrivateServerHelper` parseur & URI formatter | `[TESTED BUT NOT VERIFIED]` |
| Nettoyage Beta Home | `RobloxWatcher.cs` | `BetaHomeCleaner` Win32 WM_CLOSE | `[TESTED BUT NOT VERIFIED]` |
| Account Control / Nexus | `Nexus/*` | `NexusServer` WebSocket `5242` + relai Lua | `[TESTED BUT NOT VERIFIED]` |
