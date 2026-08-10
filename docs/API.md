# API et bridge

## Bridge pywebview

L’application desktop appelle `window.pywebview.api`, jamais SQLite, Windows ou Roblox directement. Le bridge expose des cas d’usage synchrones et redacted :

| Méthode | Rôle |
| --- | --- |
| `bootstrap()` | État initial sans secret pour le dashboard. |
| `list_accounts(query)`, `create_account(payload)`, `update_account(id, payload)`, `delete_accounts(ids)` | Gestion des métadonnées de comptes. |
| `get_public_profile(userId)`, `refresh_account_public_profile(id)` | Lecture et actualisation du profil public Roblox (identité, avatar, URL canonique) via les endpoints publics ; aucun cookie, secret ou grant OAuth ne traverse le bridge. |
| `get_public_presence(userIds)`, `refresh_account_presence(ids)` | Présence publique par lot de 50 utilisateurs maximum, cache mémoire borné ; la persistance du snapshot ne modifie jamais l’état de processus local. |
| `start_oauth_login()`, `poll_oauth_login(operationId)`, `cancel_oauth_login(operationId)` | Connexion officielle Roblox OAuth + PKCE dans le navigateur système ; seuls des états publics et le profil associé sont retournés. |
| `refresh_oauth_account(id)`, `disconnect_oauth_account(id)` | Rotation locale d'un grant OAuth DPAPI ou suppression locale de ce grant, sans session de client Roblox. |
| `list_groups()`, `create_group(payload)`, `update_group(id, payload)`, `delete_group(id)`, `move_accounts(ids, groupId)` | Groupes et réorganisation persistante. |
| `list_games()`, `list_recent_games()`, `list_favorite_games()`, `get_game(placeId)`, `list_servers(placeId)` | Catalogue, historique récent borné, favoris et serveurs publics Roblox. |
| `set_game_favorite(placeId, favorite)`, `remove_game(placeId)` | Marquage/démarquage d’un favori et retrait explicite d’un jeu enregistré localement. Ces opérations ne traitent aucune session. |
| `launch_account(id, target)` | Hand-off Windows vers `roblox://`, avec `place_id` validé ; aucun ticket n’est retourné. |
| `list_uwp_packages()`, `launch_uwp_package(packageFullName)` | Découverte des applications Roblox UWP déjà enregistrées pour l’utilisateur Windows et lancement via `shell:AppsFolder`. La réponse ne contient ni chemin d’installation, ni manifeste, ni session ; une cible est redécouverte avant lancement. |
| `list_instances()`, `refresh_instances()`, `get_instance_monitor()` | Snapshot local, historique de processus borné et état d'intégrité du dernier scan (`last_scan_complete`). `get_instance_monitor()` expose aussi l’observation locale de logs Player via `log_watcher` et `log_events`, sans chemin, nom de fichier ni ligne brute. |
| `close_instance(pid, confirm)` | Fermeture gracieuse d'un PID suivi, seulement si `watcher.termination_enabled=true` **et** `confirm=true`; aucun `kill()` forcé. |
| `bind_instance(pid, accountId, target, confirm)` | Association manuelle confirmée d'une instance orpheline à un compte/PlaceId local ; ne modifie jamais le processus. |
| `configure_account_watcher(accountId, rule)` | Règle par compte : `auto_relaunch`, délai, plafond de tentatives et déclencheurs crash/exit. Les valeurs sont validées/persistées et ne contiennent aucun secret. |
| `get_settings()`, `update_settings(values)` | Préférences validées et persistées. |
| `get_windows_startup_status()`, `set_windows_startup(enabled, confirm)` | État réel et modification explicitement confirmée de la seule valeur HKCU Run d’Astro. Le réglage persistant `general.start_with_windows` est mis à jour uniquement après confirmation de Windows ; en développement Python la capacité est annoncée indisponible et `python.exe` n’est jamais enregistré. |
| `get_activity()`, `get_notifications()`, `dismiss_notification(id)` | Historique local et centre de notifications. |
| `backup_data()`, `list_backups()`, `restore_backup(id, confirm)`, `export_metadata()`, `import_metadata(path, confirm)`, `migrate_legacy(path)`, `get_diagnostics()` | Maintenance, restauration et import explicitement confirmés, transfert de métadonnées publiques, migration et diagnostics redacted. |

Les exceptions de domaine deviennent des promesses rejetées avec un message sûr pour l’utilisateur. Les détails techniques restent dans les logs locaux.

### Watcher d'instances et relance locale

Le watcher suit les exécutables Roblox connus par la paire `PID + heure de
création`, pour se protéger contre le recyclage de PID. Une énumération
`psutil` incomplète ne ferme jamais artificiellement toutes les instances : les
enregistrements absents deviennent temporairement `unknown` jusqu'à un scan
complet. Les états courants sont `running`, `orphaned`, `terminating` et
`unknown`; les événements terminaux différencient `exited`, `crashed` et
`terminated`.

Après un lancement local accepté, le bridge enregistre une intention éphémère
sans cookie ni ticket. Une instance est associée automatiquement seulement si
une seule intention est plausible. Deux lancements simultanés ou un processus
déjà ouvert restent donc `orphaned` jusqu'à `bind_instance(..., confirm=true)`.

La relance nécessite deux activations : `watcher.auto_relaunch_enabled=true`
et `auto_relaunch=true` dans la règle du compte. Elle est bornée (1–3 600 s de
délai, 0–20 tentatives), ne concerne qu'une instance associée avec certitude et
rejoue uniquement le hand-off Windows validé vers `roblox://`. Elle n'injecte
pas de session et ne peut pas sélectionner ou forcer un profil Roblox client.

### Observation locale des logs Player

À chaque scan de processus complet, le backend examine de façon bornée le seul
répertoire `%LOCALAPPDATA%\Roblox\logs` du profil Windows courant : au plus 256
entrées, 32 candidats `*_Player_*_last.log` et 64 Mio par fichier. Il ne crée
une association que lorsqu’il observe exactement un processus Roblox et un seul
candidat; un scan incomplet, plusieurs processus ou plusieurs logs reste sans
association. Aucun chemin, nom de fichier, contenu brut ou secret n’est envoyé
au bridge.

`get_instance_monitor()` ajoute donc deux champs redacted :

```json
{
  "log_watcher": {
    "directory_available": true,
    "discovery_complete": true,
    "candidate_count": 1,
    "observed_instance_count": 1,
    "association_state": "associated",
    "associated_pid": 4242
  },
  "log_events": [
    {
      "kind": "disconnected",
      "occurred_at": "2026-08-10T12:00:00+00:00",
      "pid": 4242,
      "place_id": null,
      "job_id": null,
      "disconnect_code": 279
    }
  ]
}
```

Les valeurs possibles de `association_state` sont `associated`, `ambiguous`,
`no_instance`, `no_log`, `directory_unavailable`, `process_scan_incomplete` et
`discovery_truncated`. Les événements sont un historique en mémoire borné de
types `game_joined`, `disconnected`, `data_model_*`, `returned_to_app` et des
événements de disponibilité/rotation du parseur. Ils sont observationnels :
ils ne déclenchent ni fermeture, ni association de compte, ni relance.

### OAuth Roblox (opt-in)

Le flux OAuth est indépendant de l'API HTTP loopback. Il exige un `client_id`
et un callback `http://127.0.0.1:port/chemin` enregistrés auprès de Roblox,
ainsi que `oauth.enabled=true` dans les réglages. Le bridge n'expose ni URL
d'autorisation, ni state, ni verifier PKCE, ni code, ni access/refresh token.
`poll_oauth_login` renvoie seulement `{ operation_id, status, expires_at,
message? }` et ajoute `account` public au statut `completed`. Consultez
[OAuth](OAUTH.md) pour les limites d'API et la configuration.

## API HTTP loopback optionnelle

`app.backend.api.LoopbackApiServer` fournit une surface HTTP versionnée pour une automatisation locale explicite. Elle est désactivée par défaut, liée exclusivement à `127.0.0.1`, et exige un Bearer token pour **toutes** les routes.

Pour l’activer au prochain démarrage, définissez `api.enabled` à `true` dans les préférences et fournissez un jeton aléatoire d’au moins 32 caractères dans `ASTRO_LOCAL_API_TOKEN`. `main.py` démarre alors le serveur avec le port `api.port` (7963 par défaut) ; le jeton n’est jamais persisté ni journalisé. `ASTERIA_LOCAL_API_TOKEN` reste accepté comme compatibilité de migration pour des scripts locaux existants.

```powershell
$env:ASTRO_LOCAL_API_TOKEN = [guid]::NewGuid().ToString() + [guid]::NewGuid().ToString()
python main.py
```

Exemple :

```powershell
Invoke-RestMethod http://127.0.0.1:7963/api/v1/accounts `
  -Headers @{ Authorization = "Bearer $env:ASTRO_LOCAL_API_TOKEN" }
```

Routes implémentées :

| Méthode | Route | Rôle |
| --- | --- | --- |
| `GET` | `/api/v1/health` | État de service sans chemin ni log sensible. |
| `GET` | `/api/v1/accounts?q=…`, `/groups`, `/games`, `/instances`, `/settings`, `/activity` | Lecture locale redacted. |
| `POST` | `/accounts`, `/groups`, `/backups` | Création ou backup vérifié. |
| `PATCH` / `DELETE` | `/accounts/{id}`, `/groups/{id}` | Mutation validée. |
| `POST` | `/accounts/{id}/launch` | Lancement local avec cible `{ "place_id": 123 }`. |

Les succès sont enveloppés sous `{ "data": … }`; les échecs sous `{ "error": { "code", "message", "details?" } }`. Les statuts importants sont `400` (validation), `401` (absence de jeton), `403` (secret interdit), `404`, `409`, `422`, `502` et `503`.

L’API HTTP refuse récursivement les champs ressemblant à des mots de passe, cookies, sessions, tokens ou secrets. Les sessions ne peuvent être ajoutées que depuis le bridge desktop explicitement autorisé, puis sont protégées par DPAPI ; elles ne sont jamais retournées par l’un ou l’autre API. CORS n’est pas activé, les réponses sont `no-store`, et l’API ne doit jamais être exposée via un proxy ou une interface réseau.

La spécification OpenAPI est disponible dans [openapi.yaml](api/openapi.yaml).
