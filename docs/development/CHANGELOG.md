# Changelog

## 5.1.0 - 2026-08-21

- Rebuilt the Windows onefile/windowed artifact from the 5.1.0 sources
  (21,039,286 bytes; SHA-256
  `52CA90BF1D4863EDA85B75F7F4F372A63D42C05F6111DE10767E7057379C7757`).
- Reworked Dashboard Fleet Control into a full-width launch workspace with a
  readable group picker, capacity metrics, four explicit actions and a compact
  machine-health status strip.
- Rebuilt the Macros page around a three-step Visual/DSL workflow, action
  library, ordered step cards and clearer saved/live-run panels. Unsaved name,
  description, account, DSL and block values now survive background refreshes.
- Replaced the Fleet hourly activity list with an accessible 24-by-7 heatmap,
  hour axis, daily totals, peak/measurement summary, range switch and tooltips.
- Parallelized independent Macro runtime and Fleet comfort bridge requests and
  removed redundant watcher metadata from Dashboard activity rows.
- Hardened auto-update staging and shutdown replacement: malformed releases,
  redirects, PE/size/hash tampering and invalid pending payloads are rejected;
  explicit installs are honored even when automatic install is disabled; and
  the hidden swap helper now waits correctly on Windows PowerShell 5.1.
- Live updater smoke test downloaded the official v5.0.0 asset (20,992,263
  bytes) to an isolated temporary directory, validated its PE header and staged
  SHA-256, then removed it without installing or launching it.
- Added a typed, bounded `GlobalBasicSettings_13.xml` manager for FPS, volume,
  graphics quality, fullscreen and camera mode, with advanced existing-field
  overrides, atomic writes, readback, profiles and group associations.
- Added verified-PID Roblox window Hide/Show controls that do not activate the
  shown window, plus an honest per-instance capability/status surface.
- Added server quality scoring, filters and multi-account distribution while
  preserving each account's exact PlaceId/JobId through the batch worker.
- Added persistent streamer privacy, CPU/RAM instance telemetry, bounded memory
  growth detection and a read-only Roblox version/compatibility scanner.
- Expanded Discord Rich Presence with stable elapsed time, templates, protocol-
  correct assets, HTTPS buttons and per-PlaceId overrides.
- Fixed the Fleet comfort action that previously reported successful window
  changes after calling a nonexistent method; it now reports every real result.
- Fixed secret clipboard error handling, cursor restoration for keyboard-only
  macros, periodic UI rebuild/drag interruption and failed privacy-toggle rollback.
- Hardened password/email validation and pinned password changes to explicit
  JSON plus the exact CSRF retry, preventing ambiguous HTTP 415 requests.
- Marked legacy parental PIN operations as platform-blocked after Roblox's
  November 2024 removal instead of advertising a mutation that no longer exists.
- Validation: 825 passed, 2 platform-conditional skips; Python compilation,
  JavaScript syntax, bridge parity, `git diff --check` and build dry-run passed.

## 4.0.3 - 2026-08-14

- Added the bounded block/DSL macro studio with independent concurrent runs pinned to verified Roblox PID creation times. Keyboard input reaches a truly minimized client; coordinate clicks use a 1/255-alpha Windows surface and immediately return it to the taskbar. The macro path does not use Nexus or Roblox injection.
- Added redacted Discord Rich Presence, support ZIP generation, fixed-source GitHub update staging, private-server links per account, and the configurable existing-Roblox warning.
- Restored authenticated browser, Join Group, saved-password copy, universe places and outfit list/wear utilities from the historical 3.7.2 behavior.
- Fixed oversized Discord settings checkboxes found during the real Windows smoke test.
- Modern Roblox multi-instance support now handles `ROBLOX_singletonEvent` as well as the historical mutex, with a bounded launch guard.
- Saved imported passwords can drive an isolated Edge CDP login without entering secrets in process arguments or bridge responses; the Roblox identity is checked before the captured session is stored.
- Per-account UWP clones now support staged copy, manifest identity rewrite, AppX registration/unregistration, confirmation and rollback.
- Historical server-region probing now uses authenticated `join-game-instance` data, a 16-server cap, cache, TCP ping and a redacted UI result.
- The 22 RAM routes now preserve their historical text content type, `/v2` keeps its compatibility envelope, `/api/v1` remains structured JSON, and external binding requires a separate opt-in.
- The native Roblox `GlobalBasicSettings_13.xml` FPS cap is backed up, updated and read back alongside ClientAppSettings.
- Nexus bridge duplication and the Games favorites accessibility label were corrected.

## 2026-08-13 - Watcher, FPS unlocker, Multi Roblox and Games page fixes

### Multi Roblox (intermittent failures)
- The Roblox singleton objects are now created and owned on one dedicated
  long-lived holder thread. Win32 ownership of a mutex is thread affine: if the
  owning thread ends without releasing, the object is *abandoned* and Roblox can
  reclaim the gate. This is the mechanism the reliable launchers use, and it is
  why they must stay running.
- An object that already exists is adopted instead of refused. The previous code
  closed its handle and returned failure on ERROR_ALREADY_EXISTS, which is
  exactly the "works only when Roblox is not already open" symptom.
- The modern `ROBLOX_singletonEvent` is held alongside `ROBLOX_singletonMutex`.
- Ownership is released with `ReleaseMutex` before the handle is closed, so no
  abandoned mutex is left behind.
- The holder thread retries any object it could not create yet, and
  `get_status()` reports `mutex_held`, `event_held`, `owned_objects`,
  `adopted_existing`, `holder_thread_alive`, `reacquisitions` and `last_error`.

### FPS unlocker (no effect, per instance or globally)
- `ClientSettingsPatcher` gained a validated fallback that scans the Roblox
  `Versions/version-*` directories when the `roblox` protocol registry probe
  fails. That probe used to be the only discovery path, so ClientSettings writes
  were permanently unavailable on many installs.
- The `performance` settings category was missing, so the existing
  `global_max_fps` and `potato_graphics` switches had nowhere to persist.
- Launch-time resolution now consults the global preference. Most specific
  first: explicit launch target, account launch options, global preference, then
  the value already in `ClientAppSettings.json`.
- A failed patch was a log warning only. It now also raises an activity entry
  and a user notice.
- The cap is mirrored into every installed Roblox player version, while
  preserving unrelated flags already present in each folder. Astro re-discovers
  and rebases onto a version installed after startup instead of recreating a
  stale folder.
- Values above 240 set `FFlagTaskSchedulerLimitTargetFpsTo2402=False`; lowering
  or removing the cap removes that companion flag. Every target is read back
  and reported after a write.

### Watcher
- The background polling loop was verified to really scan; passing a bound
  interval callable is correct by design.
- The per-account rule gained a validated `enabled` switch, preserved across
  partial updates. A disabled account is excluded from the relaunch policy.
- The switch is exposed in the account management page and in the watcher rule
  dialog, both calling `configure_account_watcher`.

### Games & servers page
- The page rendered an empty list forever: nothing asked the backend for games,
  and the search box only filtered an array that was never populated.
- `search_games` already existed in the Roblox client (omni-search) but was
  exposed nowhere. It is now available through the service, the desktop bridge
  and the frontend contract, with a debounced lookup that ignores stale answers
  and falls back to saved games when Roblox is unreachable.
- A second runtime defect was fixed: the selected-game `find()` callback read
  `this.state` without binding `this`, so any saved game aborted the complete
  render before the DOM changed.

### Validation
- `315 passed, 2 skipped`; Python compilation, JavaScript syntax and the
  frontend/bridge/action audit are green.
- Real UI click confirmed that Games & servers opens with two saved games and
  loads 50 public servers.
- Real read/write verification targeted all three installed Roblox version
  folders at 144 FPS without starting or stopping Roblox.


## [4.0.0a1] — 2026-08-11

### Intégration du lot Opus — 2026-08-12

- ajout de la permission RAM `AllowGetAccounts` sur `GetAccounts` et
  `GetAccountsJson`, avec switch Settings et tests 403/200 ;
- coexistence bearer moderne / mot de passe RAM facultatif via
  `ASTRO_LOCAL_API_PASSWORD`, query historique ou header, sans persistance ;
- reprise de la région serveur : transport HTTP réellement câblé, taille,
  timeout et redirections bornés, cache, filtrage IP, service, bridge et onglet
  Network ;
- bulk import durci : champ traînant toléré, déduplication, préférence au cookie
  et correction du format `username,password,cookie` ;
- corrections apportées au lot reçu avant fusion : contrat Markdown, réglages
  UI manquants et chemins `/data` non portables non intégrés ;
- validations exécutées sans lancer ou fermer Roblox ; l’EXE a été reconstruit
  après ce lot le 12 août, sans être lancé pendant la session Roblox active.

### Conversion et parité

- ajout réel par cookie validé, vault DPAPI et navigateur Edge/CDP avec état
  d'opération suivi par le frontend ;
- fermeture du navigateur de connexion correctement détectée : aucun faux
  `waiting` ne bloque l'essai suivant ;
- lancement authentifié par session, ticket Roblox et URI `rbx-player`, avec
  PlaceId, JobId et lien privé ;
- correction HTTP 415 du ticket : POST JSON explicite, challenge CSRF puis
  ticket HTTP 200 ;
- intention de lancement enregistrée avant le handoff Windows, annulée en cas
  d'échec, puis associée au PID observé ;
- priorité de cible corrigée : cible explicite, puis Place/Job sauvegardé pour
  le compte, puis cible globale ; un lancement ponctuel n'écrase plus la
  configuration du compte ;
- lancement multiple corrigé : le bulk n'applique plus le même Place ID à tous
  les comptes et les boutons possèdent un état `Launching` par compte ;
- états `launching`/`in_game` réconciliés après un scan complet pour supprimer
  les faux comptes « en jeu » ;
- mutex multi-instance historique exact `ROBLOX_singletonMutex`, activable par
  un switch persistant dans Settings ;
- association multi-log revue : les logs Player sont corrélés aux PID par
  heure de création et ordre de lancement ;
- auto-relaunch réel réutilisant la session et la cible du compte ;
- Beta Home fermé automatiquement après la grâce historique de 30 secondes,
  uniquement si le processus et le titre Roblox sont exacts ;
- recherche jeux migrée de l'ancien `/v1/games/list` retiré vers l'endpoint
  Omni Search actuel, avec cache 60 secondes ;
- affichage/copie de session, export plaintext confirmé, ticket, CSRF et lien
  de lancement accessibles depuis les outils de compte ;
- scan paginé de joueur, Follow, serveur aléatoire, ClientSettings/FPS,
  géométrie de fenêtre, Nexus, UWP et API loopback conservés dans la nouvelle
  architecture ;
- assets, titre visible et binaire renommés `Astro Account Manager`.

### Interface et performances

- suppression des appels réseau de jeux au démarrage : chargement à la première
  ouverture de la page Games ;
- polling monitor compact toutes les trois secondes et resynchronisation ciblée
  après lancement ;
- boutons rapides protégés contre les doubles clics, avec erreurs visibles au
  lieu d'échecs silencieux ;
- picker/modal de connexion fermé dès que le navigateur isolé démarre ;
- inspection réelle à 1080×680, 1366×768 et 1500×960, navigation Tab et focus
  visibles ;
- audit des actions : 81 actions déclarées, 82 handlers click et 24 formulaires
  pris en charge.

### Validation réelle

- **362 tests passés, 2 ignorés**, compilation Python et syntaxe JavaScript valides ;
- deux sessions Roblox distinctes revalidées sans afficher les secrets ;
- Astrolucifer972 et Pierremayou lancés simultanément avec deux PID et deux
  Place ID propres, confirmés par les logs ;
- fermeture réelle et séparée de chaque client, statuts revenus à `ready` ;
- crash forcé puis relance automatique réelle vers la cible du bon compte ;
- fenêtre Roblox réellement déplacée, capturée et restaurée ;
- ClientSettings réel modifié à 144 FPS puis restauré bit pour bit ;
- 22 routes historiques exercées individuellement sur HTTP loopback réel ;
- vrai build et smoke test de `dist/AstroAccountManager.exe`.

### Artefact

- taille : 20 781 538 octets ;
- SHA-256 :
  `39B85AAED6286CB3C375CBE4EF7C5B6837166ABECBCA0D09B9A1A0E6C4A07D23`.

### Travail restant explicite

- cinq lignes `PARTIAL` : import username/password, clones UWP, région serveur,
  validation in-game de `RAMAccount.lua` et réponses API legacy ;
- validations réelles encore dépendantes d'une donnée ou cible externe : login
  navigateur complet, OAuth, VIP, certaines opérations utilitaires mutantes,
  client Nexus en jeu, paquet UWP et extension CAPTCHA.

Voir la [validation individuelle des 42 lignes](../QA_MATRIX_2026-08-11.md).

## 2026-08-13 - Per-account watchdog repair

### Fixed
- The automatic relaunch could never fire from the account page. Four independent
  switches gated it and two of them were unreachable from that page, so the
  watchdog stayed inactive whatever the user checked.
- `_account_payload` never returned the saved `enabled` flag of a per-account
  watcher rule, so both the account form and the relaunch-rule modal always
  rendered the checkbox as checked, even after the rule had been disabled.
- The relaunch-rule modal merged its defaults without `enabled`, hiding a
  disabled account behind a checked box.

### Added
- The account page now carries the full watchdog rule: watch on/off, automatic
  relaunch, relaunch delay, maximum attempts, and relaunch after a clean exit.
  Arming the relaunch from that page also arms the global watcher switches, and
  the checkbox label states it.
- `ApplicationService._relaunch_arming_state` is the single decision point that
  reports whether a relaunch is really armed and, when it is not, which switch
  is responsible. `configure_account_watcher` returns it as `effective`, and the
  interface warns instead of silently saving an inert rule.

### Notes
- Windows never tells Astro why a client stopped. A process that disappears
  within the crash window counts as a crash; a longer session that ends counts
  as an exit. Cover both cases with the new "relaunch after a clean exit"
  option rather than assuming a crash was missed.
