# Astro Account Manager frontend bridge contract

The frontend uses `window.pywebview.api` exclusively through `src/bridge.js`.
Every bridge function may return either its documented value directly or an
envelope of the form `{ "data": <value> }`. Errors should reject the call with
a clear, user-safe message; the frontend turns them into an in-app toast.

When the pywebview API is unavailable, `src/bridge.js` provides a local,
persisted preview implementation with the same methods. It is for visual and
interaction preview only and must not be used by the desktop backend.

At desktop startup, the adapter waits for the native `pywebviewready` bridge
instead of immediately substituting preview data. If a native host is detected
but its bridge still cannot initialise, it rejects with a visible error rather
than allowing a preview workspace to look like the user's persisted data.

## Bootstrap payload

`bootstrap()` returns the initial workspace in one call:

```json
{
  "mode": "desktop",
  "accounts": [],
  "groups": [],
  "games": [],
  "instances": [],
  "settings": {},
  "activity": [],
  "notifications": [],
  "diagnostics": {}
}
```

All collections may be empty. The app treats absent optional values as empty
collections, although a complete desktop response should provide every field.

## Methods

| Method | Arguments | Expected result |
| --- | --- | --- |
| `bootstrap` | — | Initial payload above. |
| `list_accounts` | `query: string` | `Account[]`. |
| `create_account` | `payload: AccountInput` | Created `Account`. |
| `update_account` | `id: string`, `payload: Partial<AccountInput>` | Updated `Account`. |
| `delete_accounts` | `ids: string[]` | `{ deleted: string[] }`. |
| `get_public_profile` | `user_id: number | string` | Public `RobloxProfile`; no local session, cookie or OAuth grant. |
| `refresh_account_public_profile` | `id: string` | `{ account: Account, profile: RobloxProfile }`; persists only public profile metadata. |
| `get_public_presence` | `user_ids: (number | string)[]` | `RobloxPresence[]` for 1–50 explicitly requested UserIds, using a short backend cache. |
| `refresh_account_presence` | `ids: string[]` | `{ account_id, user_id, presence }[]`; persists a public snapshot without changing watcher/process state. |
| `start_oauth_login` | — | Starts the official Roblox OAuth PKCE browser flow; returns a public `OAuthLoginStatus`. |
| `poll_oauth_login` | `operation_id: string` | Public `OAuthLoginStatus`; a completed result additionally contains the linked public `Account`. |
| `cancel_oauth_login` | `operation_id: string` | Cancels a pending local OAuth callback listener. |
| `refresh_oauth_account` | `id: string` | Refreshes the stored OAuth grant in the backend and returns the updated public `Account`. |
| `disconnect_oauth_account` | `id: string` | Removes the local OAuth grant and returns the retained public `Account`. |
| `list_groups` | — | `Group[]`. |
| `create_group` | `payload: GroupInput` | Created `Group`. |
| `update_group` | `id: string`, `payload: Partial<GroupInput>` | Updated `Group`; supports persistent `collapsed`, `favorite`, and `order` state. |
| `delete_group` | `id: string` | `{ deleted: string }`; associated accounts become ungrouped. |
| `move_accounts` | `ids: string[]`, `group_id: string \| null` | `{ moved: string[], group_id: string \| null }`. |
| `reorder_accounts` | `account_ids: string[]` | Full ordered `Account[]`; the request must contain each current account exactly once. |
| `list_games` | — | `Game[]`. |
| `list_recent_games` | — | Bounded `Game[]`, newest recent use first. |
| `list_favorite_games` | — | Persisted favourite `Game[]`. |
| `get_game` | `place_id: string` | `Game` with optional `description`. |
| `set_game_favorite` | `place_id: string | number`, `favorite: boolean` | Updated local `Game`; does not modify recency. |
| `remove_game` | `place_id: string | number` | `{ deleted: number }`; removes the local game record and favourite marker. |
| `list_servers` | `place_id: string` | `Server[]`. |
| `launch_account` | `id: string`, `target: LaunchTarget \| null` | `{ accepted: boolean, account_id: string }`. |
| `list_uwp_packages` | — | `{ available, reason?, packages: UwpPackage[] }`; installed-package metadata only. |
| `launch_uwp_package` | `package_full_name: string` | `{ package_full_name, app_user_model_id, launched }` after Windows accepts a launch for an already registered Roblox UWP app. |
| `list_instances` | — | `Instance[]`. |
| `refresh_instances` | — | `Instance[]`. |
| `get_instance_monitor` | — | `{ instances, events, log_watcher, log_events, pending_restarts, last_scan_complete, termination_enabled }`. `log_events` is a bounded, typed and redacted local Player-log history; it contains no path, filename or raw log line and never requests process control. |
| `close_instance` | `pid: number`, `confirm: boolean` | Graceful local close result; requires `confirm: true` and a backend opt-in. |
| `bind_instance` | `pid: number`, `account_id: string`, `target: LaunchTarget`, `confirm: boolean` | Explicitly binds an orphaned observed process; requires `confirm: true`. |
| `configure_account_watcher` | `id: string`, `rule: AccountWatcherRule` | Persists an opt-in bounded relaunch rule for one account. |
| `get_settings` | — | `Settings`. |
| `update_settings` | `values: Partial<Settings>` | Updated `Settings`. |
| `get_windows_startup_status` | — | Current-user Windows Run capability and Astro registration state, without a command or filesystem path. |
| `set_windows_startup` | `enabled: boolean`, `confirm: boolean` | Explicitly enables/disables Astro's own Run value; rejects unconfirmed calls and never registers `python.exe` from a development runtime. |
| `get_activity` | — | `Activity[]`. |
| `get_notifications` | — | `Notification[]`. |
| `dismiss_notification` | `id: string` | `{ dismissed: string }`. |
| `backup_data` | — | `{ path?: string, size?: number, created_at?: number }`. |
| `list_backups` | — | Verified `Backup[]`, newest first. |
| `restore_backup` | `backup_id: string`, `confirm: boolean` | `{ restored: string, pre_restore_backup: string, verified: true }`; requires `confirm: true`. |
| `export_metadata` | — | `{ path: string, filename: string, size: number, classification: "public_metadata_only" }`. |
| `import_metadata` | `path: string`, `confirm: boolean` | Import report with `pre_import_backup`; requires `confirm: true`. |
| `migrate_legacy` | `path: string` | `{ imported: number, skipped?: number, path?: string }`. |
| `get_diagnostics` | — | `Diagnostics`. |

## Data shapes

### Account

```json
{
  "id": "acct_123",
  "username": "AriaNebula",
  "user_id": 123456789,
  "display_name": "Aria Nebula",
  "group_id": "grp_123",
  "favorite": true,
  "status": "ready",
  "last_used": 1770000000000,
  "avatar_color": "violet",
  "notes": "Optional local note"
}
```

`status` should be one of `ready`, `in_game`, `offline`, `starting`, or
`error`. `last_used` accepts an epoch millisecond number or a date string.
`user_id` is an optional positive Roblox User ID. It enables credential-free
public profile and presence refreshes; it does not represent an authenticated
session.
`oauth_connected` is a public boolean only. `oauth_expires_at` is an optional
timestamp. Neither field is a Roblox game-client session, and no OAuth code,
verifier, access token, refresh token, cookie, or browser data may be exposed
to JavaScript.

`watcher` is public configuration only, never a credential. It can contain
`auto_relaunch`, `relaunch_delay_seconds`, `relaunch_max_attempts`,
`relaunch_on_crash`, and `relaunch_on_exit`.

### OAuthLoginStatus

```json
{
  "operation_id": "opaque-local-operation-id",
  "status": "waiting",
  "expires_at": "2026-08-10T12:05:00+00:00",
  "message": null
}
```

Valid statuses are `waiting`, `completed`, `cancelled`, `expired`, and
`failed`. A completed `poll_oauth_login` result adds a public `account` field.
The OAuth capability is unavailable unless the desktop owner configured a
registered Roblox client ID and a loopback redirect URI; the frontend must not
simulate a successful connection when that configuration is absent.

### AccountInput

`username` is required. `user_id`, `display_name`, `group_id`, `favorite`, `notes`, and
`avatar_color` are optional. The frontend currently offers `violet`, `mint`,
`coral`, `blue`, and `amber` avatar colors.

### RobloxProfile and RobloxPresence

`RobloxProfile` contains only public values returned by Roblox: `user_id`,
`username`, optional `display_name`, `description`, `created_at`,
`is_banned`, `has_verified_badge`, `avatar_url`, `avatar_state`, and the
locally constructed `profile_url`. Avatar URLs are accepted only from HTTPS
Roblox CDN hosts.

`RobloxPresence` contains `user_id`, `state` (`offline`, `online`, `in_game`,
or `in_studio`), optional `last_location`, `place_id`, `root_place_id`,
`game_id`, `universe_id`, and `last_online`. It is a public remote snapshot,
not a claim about a locally observed Roblox process.

### Group

```json
{
  "id": "grp_123",
  "name": "Favorites",
  "color": "violet",
  "icon": "star",
  "collapsed": false,
  "favorite": true,
  "order": 0
}
```

### Game and Server

```json
{
  "place_id": "2753915549",
  "title": "Blox Fruits",
  "creator": "Gamer Robot Inc",
  "players": 438214,
  "thumbnail_color": "sunset",
  "category": "Adventure",
  "favorite": true
}
```

```json
{
  "id": "srv_123",
  "place_id": "2753915549",
  "job_id": "server-job-id",
  "players": 17,
  "capacity": 20,
  "ping": 42,
  "region": "Paris, FR",
  "vip": false
}
```

When joining a server, the UI sends `launch_account(id, target)` where target
contains `place_id`, `job_id`, and `region`.

`get_game(place_id)` and a successful `launch_account` also update the local
recent-game history. The backend enforces `general.max_recent_games` (1–1000)
and keeps a favourite record if its recency entry is pruned.

### UWP package

```json
{
  "package_name": "RobloxCorporation.Roblox",
  "package_full_name": "RobloxCorporation.Roblox_1.2.3.4_x64__abc",
  "package_family_name": "RobloxCorporation.Roblox_abc",
  "display_name": "Roblox",
  "status": "Ok",
  "app_user_model_id": "RobloxCorporation.Roblox_abc!App",
  "launchable": true
}
```

UWP discovery is desktop-only and reports only a current-user registered
package and launch metadata. It never exposes an installation path, manifest,
session, account, cookie, or token. `launch_uwp_package` re-discovers the
requested registered package before asking Windows to launch it; it does not
install, register, edit, or remove an AppX package.

### Instance, Activity, Notification, Diagnostics

```json
{
  "id": "inst_123",
  "account_id": "acct_123",
  "pid": 4872,
  "game": "Blox Fruits",
  "state": "running",
  "started_at": 1770000000000,
  "memory_mb": 843,
  "server": "Paris, FR"
}
```

An observed but unassociated process uses `state: "orphaned"`. A partial OS
process enumeration can temporarily expose `state: "unknown"`; this is not a
confirmed close. Terminal events use `exited`, `crashed`, or `terminated`.

```json
{
  "status": "healthy",
  "checked_at": 1770000000000,
  "services": [{ "name": "Storage vault", "status": "healthy", "detail": "Available" }],
  "logs": [{ "level": "INFO", "at": 1770000000000, "message": "Ready" }]
}
```

`Activity` records use `id`, `type`, `title`, `detail`, and `at`.
`Notification` records use `id`, `kind`, `title`, `body`, `at`, and optional
`read`. Valid kinds are `success`, `info`, `warning`, and `error`.

### Backup

```json
{
  "id": "backup_123",
  "label": "manual",
  "source_name": "asteria.sqlite3",
  "created_at": "2026-08-10T12:00:00+00:00",
  "size": 32768,
  "verified": true
}
```

Only verified backups are listed. A restore operation must always receive an
explicit `true` confirmation from the UI; the backend creates a safety backup
before atomically restoring the selected record.

### Metadata transfer

`export_metadata()` creates a checksummed JSON file in Astro Account Manager's export folder.
It contains public account, group, and game metadata only: it never carries a
session, vault entry, cookie, token, or saved credential. `import_metadata()`
accepts a path to that checked export and must receive an explicit `true`
confirmation. The backend creates a pre-import backup before adding compatible
public records and returns counts such as `accounts_imported`, `groups_imported`,
and `games_imported`.

### Settings

The app currently consumes these persisted keys:

```json
{
  "theme": "dark",
  "accent": "#9c85ff",
  "density": "comfortable",
  "reduce_motion": false,
  "launch_behavior": "confirm",
  "close_when_empty": false,
  "watcher_enabled": true,
  "auto_backup": true,
  "notifications": true,
  "diagnostics": false
}
```

The UI presents the built-in accent choices as names, then sends their hex
values to the desktop bridge (`violet` is `#9c85ff`, `mint` is `#47cfa1`,
`coral` is `#f58283`, `blue` is `#73a9ff`, and `amber` is `#efb55d`). Unknown
valid hex colors remain usable as a custom accent. Unknown settings may be retained by the backend. The desktop bridge must not
log credentials, cookies, session tokens, or other sensitive payload fields.

### Windows startup

`get_windows_startup_status()` returns a current-user capability snapshot:

```json
{
  "available": true,
  "supported": true,
  "accessible": true,
  "registered": true,
  "enabled": true,
  "needs_repair": false,
  "configured": true,
  "reason": null
}
```

The snapshot deliberately excludes the Run command and executable path.
`set_windows_startup(enabled, true)` is the only way to change it; it updates
only Astro Account Manager's own current-user Run value after explicit UI
confirmation. It is unavailable for a Python development runtime and Preview
must reject both methods rather than simulate a Windows registration.

Official Roblox sign-in configuration is nested under `categories.oauth` and
is updated as a partial nested object:

```json
{
  "categories": {
    "oauth": {
      "enabled": false,
      "client_id": "1234567890",
      "redirect_uri": "http://127.0.0.1:8989/oauth/callback",
      "callback_timeout_seconds": 300
    }
  }
}
```

`client_id` and `redirect_uri` are registration metadata, not credentials. The
desktop bridge validates them before allowing OAuth to start. A client secret,
OAuth code verifier, access token, refresh token, cookie, and game-client
session must never appear in this object or in any bridge response.
