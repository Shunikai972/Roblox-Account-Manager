# Registre de portage 3.7.2 → Astro Account Manager

Ce registre relie chaque fonction observée dans la source historique et la Developer API officielle (`https://ic3w0lf22.gitbook.io/roblox-account-manager/`) à son état dans le nouveau code.

## Convention de statut

- **Portée et vérifiée** : comportement implémenté et testé dans Astro.

## 1. Ajout de compte et authentification

| Élément | Référence 3.7.2 & API Officielle | Équivalent Astro | État |
| --- | --- | --- | --- |
| Authentification OAuth 2.0 & PKCE | `AccountManager.cs` | `roblox/oauth.py`, navigateurs systèmes, callback loopback | Portée et vérifiée |
| Importation en masse user:pass / cookie | `AccountManager.cs` | `storage/bulk_import.py`, parseur multi-format | Portée et vérifiée |
| Extraction de Cookie & Secret Vault | `Account.cs` | `security/dpapi.py`, vault chiffré `CurrentUserDPAPI` | Portée et vérifiée |

## 2. Developer API Officielle (GitBook 1:1 Parity)

| Endpoint Developer API | Route Officielle GitBook | Implémentation Astro Loopback & Bridge | État |
| --- | --- | --- | --- |
| `LaunchAccount` | `GET /LaunchAccount?Account=...&PlaceId=...&JobId=...` | `app/backend/api/loopback.py` (`_route`) + `launch_account` | Portée et vérifiée |
| `FollowUser` | `GET /FollowUser?Account=...&User=...` | `app/backend/api/loopback.py` + `search_players` & `get_player_presence` | Portée et vérifiée |
| `SetServer` | `GET /SetServer?Account=...&PlaceId=...&JobId=...` | `app/backend/api/loopback.py` + `update_account` | Portée et vérifiée |
| `SetRecommendedServer` | `GET /SetRecommendedServer?Account=...&PlaceId=...` | `app/backend/api/loopback.py` + `RandomServerSelector` | Portée et vérifiée |
| `BlockUser` | `GET /BlockUser?Account=...&User=...` | `app/backend/api/loopback.py` + `AccountUtils.block_user` | Portée et vérifiée |
| `UnblockUser` | `GET /UnblockUser?Account=...&User=...` | `app/backend/api/loopback.py` + `AccountUtils.unblock_user` | Portée et vérifiée |
| `GetCookie` | `GET /GetCookie?Account=...` | `app/backend/api/loopback.py` + `get_account_cookie` | Portée et vérifiée |
| `GetField` / `SetField` | `GET /GetField` / `GET /SetField` | `app/backend/api/loopback.py` + SQLite metadata fields | Portée et vérifiée |
| `SetAlias` / `SetDescription` | `GET /SetAlias` / `GET /SetDescription` | `app/backend/api/loopback.py` + `update_account` | Portée et vérifiée |

## 3. Utilitaires de Compte & Lancement Avancé

| Élément | Référence 3.7.2 | Équivalent Astro | État |
| --- | --- | --- | --- |
| Plafond FPS Client | `ClientSettingsPatcher.cs` | `roblox/client_settings.py` (`ClientSettingsPatcher`) | Portée et vérifiée |
| Multi-Instance Mutex | `AccountManager.cs` | `roblox/multi_instance.py` (`WindowsMultiInstanceController`) | Portée et vérifiée |
| Lancement en lot (`Batch Launch`) | `Classes/Batch.cs` | `roblox/batch_launcher.py` (`BatchLauncher`) | Portée et vérifiée |
| Serveurs Privés / VIP | `ServerList.cs` | `roblox/private_servers.py` (`PrivateServerHelper`) | Portée et vérifiée |
| Nettoyage Beta Home | `RobloxWatcher.cs` | `watchers/beta_home_cleaner.py` (`BetaHomeCleaner`) | Portée et vérifiée |
| Account Control / Nexus | `Nexus/*` | `app/backend/nexus/server.py` (`NexusServer` WebSocket `5242`) | Portée et vérifiée |
