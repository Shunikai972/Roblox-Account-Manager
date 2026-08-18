# Configuration

Les préférences sont persistées dans la base locale et exposées dans la page **Settings**. Elles sont centralisées et validées avant écriture.

| Catégorie | Exemples |
| --- | --- |
| General | délai de lancement, backups automatiques, historique récent. |
| Appearance | thème, accent, densité, reduced motion. |
| Accounts | présence et rafraîchissement de session opt-in. |
| Instances | Multi Roblox, prévention de doublons, file de lancement et positions de fenêtres. |
| Watcher | intervalle, association prudente PID+création, fermeture manuelle confirmée, règles automatiques opt-in et relance bornée. |
| Network | timeout et résolution de région opt-in. |
| OAuth | liaison d'identité Roblox opt-in via client ID public, callback loopback et PKCE. |
| API | serveur local désactivé par défaut, loopback par défaut et exposition LAN séparément opt-in. |
| Notifications | durée des toasts et notifications desktop. |
| Developer | logs détaillés, sans capacités de lecture de secrets. |

Le bouton **Reset settings** restaure une catégorie canonique ou toutes les
préférences après confirmation. Les comptes, sessions, groupes, jeux et backups
ne sont pas touchés. Un reset incluant General désactive aussi proprement le
démarrage Windows s’il était actif.

## Régions de serveurs

Settings → Network expose la reprise de `IPApiLink` et
`ServerRegionFormat` de RAM 3.7.2. Cette fonction est désactivée par défaut :
elle peut envoyer l’adresse IP publique d’un serveur au fournisseur configuré.

| Clé | Défaut | Borne |
|---|---|---|
| `network.region_lookup_enabled` | `false` | booléen |
| `network.region_lookup_provider` | vide, donc `http://ip-api.com/json/{ip}` | URL HTTP(S) de 300 caractères contenant `{ip}` |
| `network.region_lookup_format` | `{city}, {country}` | 1–120 caractères |
| `network.region_lookup_timeout_seconds` | `4` | 0,5–30 secondes |
| `network.region_cache_ttl_seconds` | `900` | 30–86400 secondes |

La réponse est limitée à 64 Kio, les redirections sont refusées, le cache LRU
est borné à 512 entrées et les erreurs sont mises en cache brièvement. Les
adresses privées, loopback, link-local, multicast et réservées ne sont jamais
envoyées. Le bouton **Load regions** reproduit la sonde authentifiée RAM
`join-game-instance` pour au plus 16 JobIds avec le compte sélectionné. Seuls
région, ping et statut sont renvoyés à l’interface ; l’adresse reste backend-only.

## Watcher d'instances

Le switch **Settings → Instances → Multi Roblox** appelle directement le
contrôleur desktop et persiste `instances.allow_multiple_launches`. Astro
détient le mutex historique et l’événement singleton sur un thread persistant ;
au lancement il surveille aussi brièvement les nouveaux processus et détache
leur handle `ROBLOX_singletonEvent` moderne. Astro doit rester ouvert, mais
l’activation n’exige plus de fermer un client déjà en cours.

`watcher.enabled` démarre le polling local au lancement de l'application.
`scan_interval_seconds` est validé entre 1 et 300 secondes. Les scans partiels
ne produisent pas de fausse fermeture : une instance non confirmée devient
simplement `unknown` jusqu'au prochain scan complet.

La fermeture est désactivée par défaut. Une fermeture manuelle exige
`watcher.termination_enabled=true` puis une confirmation dans le bridge. Les
règles automatiques exigent en plus leur propre option
`close_if_memory_low`, `close_if_title_mismatch` ou `close_unconnected`.
Les seuils `memory_low_mb`, `health_grace_seconds`,
`unconnected_timeout_seconds` et `expected_window_title` sont validés dans
Settings. Toutes ces voies utilisent une terminaison gracieuse, ignorent la
fenêtre au premier plan et ne forcent jamais un `kill`.

`instances.remember_window_positions` capture la géométrie d’une fenêtre
Roblox liée après 30 secondes et tente de restaurer la géométrie du compte
pendant 45 secondes au prochain lancement associé. Les actions Save/Restore
de la page Instances permettent aussi un contrôle explicite.

La relance est également désactivée par défaut. Pour l'activer, définissez
`watcher.auto_relaunch_enabled=true`, puis configurez explicitement le compte
avec `configure_account_watcher`. Les options globales bornent le délai,
l'association de lancement, la fenêtre de crash et le nombre d'essais. Une
relance rouvre seulement une destination `roblox://` validée : elle ne lit ni
n'exporte de cookie et ne modifie pas le client Roblox.

## OAuth Roblox

`oauth.enabled` reste à `false` par défaut. Pour le flux officiel, configurez
un `oauth.client_id` numérique et un `oauth.redirect_uri` exact enregistré
chez Roblox, obligatoirement de la forme `http://127.0.0.1:port/chemin`.
`oauth.callback_timeout_seconds` est borné entre 60 et 900 secondes. Aucun
client secret, cookie ou token OAuth ne peut être ajouté aux réglages : les
grants sont protégés séparément par DPAPI. Voir [OAuth](docs/OAUTH.md).

## Solveur CAPTCHA du navigateur isolé

Astro peut charger une extension Chromium de solveur fournie par l’utilisateur
dans le profil Edge/CDP temporaire. Définissez
`ASTRO_CAPTCHA_SOLVER_EXTENSION` vers le dossier absolu de l’extension
décompressée contenant `manifest.json`, puis démarrez l’ajout par navigateur.
Astro ne lit ni ne stocke la clé du prestataire : elle reste gérée par
l’extension dans ce profil isolé. Un dossier invalide est simplement ignoré.

## API locale

L’API HTTP est un complément opt-in du bridge pywebview, jamais un service exposé par défaut. Activez `api.enabled`, conservez `api.host` à `127.0.0.1`, choisissez un port local, puis définissez un `ASTRO_LOCAL_API_TOKEN` d’au moins 32 caractères avant de démarrer l’application. `api.allow_external` est une autorisation indépendante : si elle est cochée, Astro utilise `0.0.0.0`/`::` pour le LAN tout en conservant authentification et permissions. Sans jeton, Astro Account Manager laisse l’API arrêtée. `ASTERIA_LOCAL_API_TOKEN` reste accepté uniquement pour les scripts locaux existants.

`api.allow_get_accounts` gouverne séparément `GetAccounts` et
`GetAccountsJson`. La compatibilité facultative avec le mot de passe RAM
s’active par `api.legacy_password_auth_enabled` et lit uniquement
`ASTRO_LOCAL_API_PASSWORD` au démarrage. Le bearer reste actif et les mêmes
permissions s’appliquent aux deux schémas.

Voir [la documentation API](docs/API.md) pour les routes, l’authentification et les restrictions sur les secrets.

## Performance (`performance`)

`performance.global_max_fps` fixe la limite d'images par seconde appliquee au
lancement quand le compte n'a pas sa propre valeur. `0` signifie "ne rien
imposer". `performance.potato_graphics` active les FastFlags graphiques minimaux
de maniere globale.

Ordre de resolution au lancement, du plus specifique au plus general :

1. cible de lancement explicite (`fps` / `fps_cap`) ;
2. options du compte (`launch_options.max_fps`, `launch_options.potato_graphics`) ;
3. preference globale ci-dessus ;
4. valeur deja presente dans `ClientAppSettings.json`.

Astro cherche le dossier de version via le protocole `roblox` enregistre, puis
via `Roblox/Versions/version-*`. Il met aussi à jour le réglage natif
`GlobalBasicSettings_13.xml` (`FramerateCap`) avec backup et relecture, car les
FastFlags seuls peuvent être refusés par le client moderne. Un échec d’écriture
n’est plus silencieux : il apparaît dans l’activité et une notification.

Attention : `ClientAppSettings.json` est un fichier unique partage par toutes
les instances. La valeur d'un compte est donc appliquee au moment de son
lancement ; deux clients simultanes ne peuvent pas avoir deux limites
differentes.

## Watcher par compte

En plus des reglages globaux `watcher.*`, chaque compte possede une regle locale
enregistree via `configure_account_watcher`. La cle `enabled` (vraie par defaut)
se regle depuis la page de gestion du compte. Un compte desactive ne participe
pas au relancement automatique, meme si `watcher.auto_relaunch_enabled` est vrai.

## Multi Roblox

`allow_multiple_launches` demande a Astro de detenir `ROBLOX_singletonMutex` et
`ROBLOX_singletonEvent` sur un thread dedie. Astro doit rester ouvert pendant
toute la session multi-instance : si le processus se termine, les objets sont
liberes et Roblox reprend la porte d'instance unique.

## Watchdog par compte

La relance automatique n'est jamais implicite. Elle exige, dans cet ordre :

1. `watcher.enabled` - le moniteur de processus local tourne.
2. La case *Watch this account* du compte.
3. La case *Auto-relaunch this account if it stops* du compte.
4. `watcher.auto_relaunch_enabled` - l'autorisation globale des regles de relance.
5. Au moins un declencheur : crash ou fermeture propre.
6. Un nombre maximal de tentatives superieur a zero.

Depuis la fiche du compte, cocher la relance arme aussi les points 1 et 4 ; le
libelle de la case l'indique. Si une regle reste inerte, Astro renvoie la raison
exacte dans le champ `effective` et l'affiche au lieu de laisser croire a un
succes.

Windows n'indique pas la cause d'un arret de client. Un processus qui disparaît
dans la fenetre `watcher.crash_window_seconds` est traite comme un crash ; une
session plus longue qui se termine est traitee comme une sortie. Pour couvrir
les deux cas, activez aussi *Relaunch even when the client closes without
crashing*.

## Lancement par vagues (`launcher`)

| Clé | Défaut | Effet |
| --- | --- | --- |
| `max_concurrent` | 3 | clients lancés en parallèle dans une vague |
| `delay_seconds` | 4.0 | délai entre deux lancements d'une même vague, borné de 0,5 à 3600 s |
| `wait_for_wave` | vrai | attend qu'une vague soit prête avant d'entamer la suivante |
| `wave_pause_seconds` | 6.0 | pause imposée entre deux vagues, même quand la sonde répond « prêt » |
| `skip_running` | vrai | ignore un compte dont le client tourne déjà |

Exemple demandé : dix comptes, trois clients simultanés au maximum et quatre
secondes entre chaque lancement se règlent avec `max_concurrent = 3` et
`delay_seconds = 4.0` ; `wave_pause_seconds` laisse en plus respirer la machine
entre deux vagues.

## Confort (`comfort`)

| Clé | Défaut | Effet |
| --- | --- | --- |
| `focus_volume` | 100 | volume visé pour la fenêtre au premier plan |
| `background_volume` | 0 | volume visé pour les autres fenêtres |
| `focus_minimizes_others` | vrai | le mode Focus minimise les fenêtres non ciblées |
| `sleep_after_minutes` | 15 | inactivité avant de proposer le mode Sleep |
| `queue_cpu_percent` | 80 | au-delà, la file de lancement attend |
| `queue_memory_percent` | 85 | au-delà, la file de lancement attend |
| `queue_max_instances` | 0 | plafond d'instances simultanées ; 0 signifie « pas de plafond » |

Le mixer par instance **stocke** les niveaux mais ne les applique pas : Windows
n'expose pas de volume par processus sans pilote audio dédié, et
`get_comfort_overview` renvoie donc `audio.supported = false`. Les modes Focus
et Sleep ne touchent jamais une fenêtre en train d'exécuter une macro.

## Macros (`macros`)

| Clé | Défaut | Effet |
| --- | --- | --- |
| `enabled` | vrai | autorise le moteur de macros |
| `allow_background_delivery` | vrai | autorise la livraison hors premier plan quand le backend le permet |
| `resume_after_relaunch` | vrai | reprend une macro interrompue après une relance automatique |

La reprise attend que le client soit de nouveau détecté, avec un plafond de
tentatives et de durée ; passé ce plafond, elle abandonne et le dit.

## Ce que les règles ne font pas (`rules`)

Une règle peut mettre en pause, relancer un client absent ou avertir. Elle ne
ferme **jamais** un client vivant. Fermer un client demande une tâche planifiée
`close_instances` écrite à la main, un arrêt sécurisé confirmé, ou un bloc
`RESTART` placé volontairement dans une macro. `get_rules_overview()` expose
cette limite dans `limits.never_closes_clients`.

## Nom des clés de réglages

Une clé de réglage contenant `password`, `passwd`, `pwd`, `cookie`, `token`,
`secret`, `credential`, `authorization`, `api_key`, `session` ou
`roblosecurity` est refusée par le dépôt : ces valeurs doivent passer par le
stockage protégé par l'OS. C'est pourquoi la durée maximale d'exécution
s'appelle `max_runtime_hours` et non `session_max_hours`.
`tests/test_settings_persistence_guard.py` garde cette règle.

## Launch profiles (v11)

Launch profiles are stored under the settings key `launcher.profiles` as a list
of objects. The screen is **Fleet → Launch profiles**.

| Field | Meaning | Bounds |
| --- | --- | --- |
| `name` | what you see in the list | 1 to 60 characters |
| `place_id` | the game to open | digits only, required |
| `job_id` | send everyone to one server | Roblox server id, optional |
| `link_code` | private server code | 6 to 64 characters, optional |
| `fps` | FPS target applied at launch | `0` keeps the current cap, otherwise 24 to 1000 |
| `group_id` | group launched when you press Launch without selecting accounts | optional |
| `note` | free reminder | up to 200 characters |

Limits: 40 profiles per workspace. A profile with both a `job_id` and a
`link_code` is refused, because those are two different destinations.

Two honest notes that the UI repeats:

- The FPS value is written into the Roblox client settings, which are **global**.
  Launching a profile with an FPS target changes the cap for every client.
- A profile launch goes through the wave launcher, so `launcher.max_concurrent`,
  `launcher.delay_seconds` and `launcher.wave_pause_seconds` still decide the pace.

## Emergency stop (v11)

The red **Emergency stop** button lives at the bottom of **Fleet → Comfort**. It
stops every macro run, cancels whatever the launch queue still owes, drops the
pending macro resumes and disarms the automatic rules (`rules.enabled` becomes
`false`). It never closes a Roblox client: that decision stays yours, which is
the same invariant the rules engine follows.

## Settings snapshot cache (v11)

`get_settings()` is now cached per repository revision. Any settings write bumps
that revision and the next read rebuilds the tree, so behaviour is unchanged
while the dashboard poll stops re-reading the whole settings table several times
per refresh. There is no setting to tune here; it is an internal optimisation
pinned by `tests/test_fleet_features.py::test_settings_are_read_once_until_something_changes`.
