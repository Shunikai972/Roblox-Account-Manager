# API et bridge

## Bridge pywebview

Le frontend appelle exclusivement `window.pywebview.api` via `app/frontend/src/bridge.js`. `DesktopBridge` convertit les erreurs de domaine en messages sûrs et ne renvoie jamais de traceback.

### Comptes et données publiques

- `bootstrap`, `list_accounts`, `create_account`, `update_account`, `delete_accounts`, `reorder_accounts`
- `list_groups`, `create_group`, `update_group`, `delete_group`, `move_accounts`, `reorder_groups`
- `get_public_profile`, `refresh_account_public_profile`, `get_public_presence`, `refresh_account_presence`
- `list_games`, `list_recent_games`, `list_favorite_games`, `get_game`, `list_servers`, `resolve_server_region`, `set_game_favorite`, `remove_game`

### Authentification et sessions

- `add_account_from_cookie(cookie, groupId)` valide l’identité Roblox avant toute sauvegarde DPAPI.
- `start_manual_browser_login(groupId)` et `poll_manual_browser_login(operationId)` pilotent le navigateur dédié sans faux succès.
- `start_saved_password_browser_login(accountId)` déchiffre uniquement dans le backend un mot de passe importé, préremplit Edge via CDP sans secret dans la ligne de commande, puis vérifie l’identité avant de sauvegarder le cookie capturé.
- `start_oauth_login`, `poll_oauth_login`, `cancel_oauth_login`, `refresh_oauth_account`, `disconnect_oauth_account` gèrent uniquement le grant Open Cloud ; OAuth ne crée pas de session du client Roblox.
- `refresh_account_session(id)` revalide une session stockée et refuse une identité différente.
- `get_account_cookie(id)` renvoie la session brute après une action UI explicite.
- `export_account_sessions(ids, confirm)` exige `confirm=true` et écrit un fichier plaintext sous le dossier d’exports.
- `generate_auth_ticket`, `get_account_csrf_token`, `generate_rbx_player_link` renvoient les valeurs demandées uniquement à l’appelant explicite.

Ces réponses sensibles ne sont jamais incluses dans `bootstrap`, les diagnostics, les notifications, les logs, les backups automatiques ou l’export de métadonnées publiques. PreviewBridge rejette toutes ces opérations.

### Lancement, instances et Nexus

- `launch_account`, `start_batch_launch`, `cancel_batch_launch`, `get_batch_launch_status`
- `parse_vip_link`, `search_players`, `get_player_presence`, `find_player_server`, `get_random_server`
- `get_multi_instance_status`, `set_multi_instance`, `get_fps_cap`, `set_fps_cap`, `remove_fps_cap`
- `list_uwp_packages`, `launch_uwp_package`, `create_uwp_account_clone`, `unregister_uwp_account_clone`
- `list_instances`, `refresh_instances`, `get_instance_monitor`, `bind_instance`, `close_instance`, `configure_account_watcher`, `position_instance_window`, `capture_instance_window`, `restore_instance_window`, `close_beta_home_windows`

`find_player_server(place_id, user_id, max_pages=10)` reproduit le scan RAM par `playerTokens` et miniatures, avec pagination et lots bornés ; les tokens opaques ne quittent jamais le backend. Les règles automatiques mémoire/titre/timeout exigent `watcher.termination_enabled` et leur option indépendante, ignorent la fenêtre au premier plan et ne ciblent qu’un processus/fenêtre Roblox vérifiés. La capture/restauration de géométrie est opt-in via `instances.remember_window_positions` ; les actions manuelles exigent une confirmation.

`probe_server_regions(account_id, place_id, job_ids)` reproduit la sonde RAM
`join-game-instance` avec la session sélectionnée, au plus 16 serveurs, puis
résout la région et mesure un ping TCP borné. L’adresse machine reste backend-only.
Les clones UWP utilisent staging, identité de manifeste propre au compte,
enregistrement/désenregistrement exact et rollback ; leurs mutations exigent
une confirmation distincte dans l’interface.
- `start_nexus_server`, `stop_nexus_server`, `get_nexus_status`, `send_nexus_command`, `get_nexus_lua_script`

La fermeture d’une instance requiert l’activation globale et une confirmation distincte. La relance requiert un opt-in global et un opt-in par compte. Nexus exige son jeton éphémère dans le handshake.

### Utilitaires authentifiés

`change_account_password`, `change_account_email`, `logout_all_account_sessions`, `set_account_display_name`, `send_account_friend_request`, `block_account_user`, `unblock_account_user`, `get_account_blocked_list`, `unblock_all_account_users`, `quick_log_in_account`, `set_account_follow_privacy`, `unlock_account_pin` et `set_account_avatar` sont raccordés à Accounts → Utilities.

### Maintenance

`get_settings`, `update_settings`, `reset_settings`, `get_windows_startup_status`, `set_windows_startup`, `get_activity`, `get_notifications`, `dismiss_notification`, `backup_data`, `list_backups`, `restore_backup`, `export_metadata`, `import_metadata`, `migrate_legacy`, `get_diagnostics` et `check_for_updates`.

## API HTTP loopback

`LoopbackApiServer` est désactivé par défaut et écoute `127.0.0.1`. Une option
séparée `api.allow_external=true` autorise explicitement un bind
`0.0.0.0`/`::`; elle ne retire ni l’authentification ni les permissions. Chaque
route exige un bearer d’au moins 32 caractères ou, si activé, le mot de passe
RAM. Les secrets runtime restent en mémoire et ne sont jamais journalisés.

L’activation, le port et les permissions se règlent dans Settings → Advanced. Un redémarrage est requis.

| Permission | Routes concernées |
|---|---|
| `allow_get_cookie` | `GetCookie`, `GetCSRFToken`, `GetAccountsJson?IncludeCookies=true` |
| `allow_launch_account` | `LaunchAccount`, `FollowUser` |
| `allow_account_editing` | `SetField`, `RemoveField`, `SetAlias`, `SetDescription`, `AppendDescription`, `SetAvatar` et mutations REST comptes/groupes |
| `allow_import_cookie` | `ImportCookie` |
| `allow_get_accounts` | `GetAccounts`, `GetAccountsJson` (`AllowGetAccounts` historique) |

Toutes les permissions sont `false` par défaut dans l’application. Même un bearer correct reçoit `403` si la capacité est désactivée.

### Authentification bearer et compatibilité RAM

Le bearer moderne reste obligatoire par défaut. La compatibilité avec
`EveryRequestRequiresPassword` est facultative et doit être activée dans
Settings → Advanced.

| | Bearer Astro | Mot de passe RAM |
|---|---|---|
| Réglage | toujours actif lorsque l’API démarre | `api.legacy_password_auth_enabled` |
| Secret runtime | `ASTRO_LOCAL_API_TOKEN` | `ASTRO_LOCAL_API_PASSWORD` |
| Transport | `Authorization: Bearer <token>` | `X-RAM-Password` ou `?Password=` |
| Minimum | 32 caractères | 12 caractères |

Les deux schémas restent limités à `127.0.0.1`, utilisent une comparaison à
temps constant et respectent exactement les mêmes permissions. Aucun secret
n’est persisté ou journalisé. Le header `X-RAM-Password` est préférable au
paramètre historique, car une valeur placée dans une URL peut rester dans
l’historique du client appelant.

### Routes RAM compatibles

`LaunchAccount`, `FollowUser`, `SetServer`, `SetRecommendedServer`, `BlockUser`, `UnblockUser`, `UnblockEveryone`, `GetBlockedList`, `GetField`, `SetField`, `RemoveField`, `SetAlias`, `GetAlias`, `SetDescription`, `GetDescription`, `AppendDescription`, `SetAvatar`, `GetCookie`, `GetAccounts`, `GetAccountsJson`, `GetCSRFToken`, `ImportCookie`.

Les paramètres historiques `Account`, `PlaceId`, `JobId`, `User`/`Username`, `Group`, `IncludeCookies`, `Field`, `Value`, `Alias`, `Description`, `AssetId` et `Cookie` sont pris en charge selon la route. Les routes d’édition texte acceptent également un corps POST borné.

Les routes historiques à la racine répondent en `text/plain` comme RAM 3.7.2.
Le préfixe `/v2` conserve l’enveloppe texte JSON `{Success, Message}` attendue
par les scripts compatibles. Les routes `/api/v1` restent la surface Astro
structurée en `application/json`.

### Routes REST Astro

- `GET /api/v1/health`, `/accounts`, `/groups`, `/games`, `/instances`, `/settings`, `/activity`
- `POST /api/v1/accounts`, `/groups`, `/backups`
- `PATCH` / `DELETE /api/v1/accounts/{id}`, `/groups/{id}`
- `POST /api/v1/accounts/{id}/launch`

Les succès utilisent `{ "data": ... }`, les erreurs `{ "error": { "code", "message" } }`. Les corps sont bornés à 64 Kio, les réponses utilisent `Cache-Control: no-store`, CORS n’est pas activé et les exceptions internes ne sont pas réfléchies.

La spécification [OpenAPI](api/openapi.yaml) documente la surface REST Astro ; les routes RAM de compatibilité restent décrites ici.

## Surfaces desktop ajoutées le 14 août 2026

Ces méthodes pywebview ne sont pas exposées par l'API HTTP :

- macros : `list_macros`, `save_macro`, `delete_macro`, `start_macro`, `stop_macro`, `list_macro_runs` ;
- Discord : `get_discord_presence_status`, `refresh_discord_presence` ;
- updater : `get_update_status`, `check_for_updates`, `download_update`, `schedule_update_install`, `cancel_update` ;
- préparation locale : `get_roblox_background_status`, `close_running_roblox(confirm)` ;
- serveur privé : `launch_account_from_private_link(account_id, link)` ;
- diagnostic : `export_support_bundle` ;
- parité 3.7.2 : `open_account_browser`, `join_account_group`, `get_account_saved_password`, `list_universe_places`, `list_user_outfits`, `wear_account_outfit`.

Les actions de fermeture, suppression, installation ou mutation de compte exigent un geste utilisateur distinct. Les cookies, mots de passe et tickets ne figurent jamais dans les statuts des nouveaux moteurs.
