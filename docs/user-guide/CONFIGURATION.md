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
| API | serveur local désactivé par défaut, bind loopback uniquement. |
| Notifications | durée des toasts et notifications desktop. |
| Developer | logs détaillés, sans capacités de lecture de secrets. |

Le reset fin par catégorie et le reset global sont recensés dans la matrice de migration mais ne sont pas encore exposés par l’interface ; modifier une valeur existante est immédiatement persistant. Ils ne doivent donc pas être présentés comme disponibles avant leur implémentation.

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
envoyées. Si Roblox ne fournit aucune adresse machine dans la liste publique,
la région reste simplement inconnue.

## Watcher d'instances

Le switch **Settings → Instances → Multi Roblox** appelle directement le
contrôleur desktop et persiste `instances.allow_multiple_launches`. Activez-le
avant d’ouvrir Roblox. Astro détient alors le mutex historique exact
`ROBLOX_singletonMutex` pendant toute sa durée de vie. Si Roblox est déjà
ouvert, le choix est conservé et l’interface demande de fermer Roblox puis de
redémarrer Astro avant les prochains lancements.

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

L’API HTTP est un complément opt-in du bridge pywebview, jamais un service exposé par défaut. Activez `api.enabled`, conservez `api.host` à `127.0.0.1`, choisissez un port local, puis définissez un `ASTRO_LOCAL_API_TOKEN` d’au moins 32 caractères avant de démarrer l’application. Sans ce jeton, Astro Account Manager laisse l’API arrêtée et le reste du desktop fonctionne normalement. `ASTERIA_LOCAL_API_TOKEN` reste accepté uniquement pour les scripts locaux existants.

`api.allow_get_accounts` gouverne séparément `GetAccounts` et
`GetAccountsJson`. La compatibilité facultative avec le mot de passe RAM
s’active par `api.legacy_password_auth_enabled` et lit uniquement
`ASTRO_LOCAL_API_PASSWORD` au démarrage. Le bearer reste actif et les mêmes
permissions s’appliquent aux deux schémas.

Voir [la documentation API](docs/API.md) pour les routes, l’authentification et les restrictions sur les secrets.
