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
