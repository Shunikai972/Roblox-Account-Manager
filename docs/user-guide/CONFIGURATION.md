# Configuration

Les préférences sont persistées dans la base locale et exposées dans la page **Settings**. Elles sont centralisées et validées avant écriture.

| Catégorie | Exemples |
| --- | --- |
| General | délai de lancement, backups automatiques, historique récent. |
| Appearance | thème, accent, densité, reduced motion. |
| Accounts | présence et rafraîchissement de session opt-in. |
| Instances | prévention de doublons, file de lancement et positions de fenêtres. |
| Watcher | intervalle, association prudente PID+création, fermeture confirmée et règles de relance bornées. |
| Network | timeout et résolution de région opt-in. |
| OAuth | liaison d'identité Roblox opt-in via client ID public, callback loopback et PKCE. |
| API | serveur local désactivé par défaut, bind loopback uniquement. |
| Notifications | durée des toasts et notifications desktop. |
| Developer | logs détaillés, sans capacités de lecture de secrets. |

Le reset fin par catégorie et le reset global sont recensés dans la matrice de migration mais ne sont pas encore exposés par l’interface ; modifier une valeur existante est immédiatement persistant. Ils ne doivent donc pas être présentés comme disponibles avant leur implémentation.

## Watcher d'instances

`watcher.enabled` démarre le polling local au lancement de l'application.
`scan_interval_seconds` est validé entre 1 et 300 secondes. Les scans partiels
ne produisent pas de fausse fermeture : une instance non confirmée devient
simplement `unknown` jusqu'au prochain scan complet.

La fermeture est désactivée par défaut. Elle exige à la fois
`watcher.termination_enabled=true` et une confirmation dans le bridge; elle
utilise une terminaison gracieuse et ne force jamais un `kill`.

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

## API locale

L’API HTTP est un complément opt-in du bridge pywebview, jamais un service exposé par défaut. Activez `api.enabled`, conservez `api.host` à `127.0.0.1`, choisissez un port local, puis définissez un `ASTRO_LOCAL_API_TOKEN` d’au moins 32 caractères avant de démarrer l’application. Sans ce jeton, Astro Account Manager laisse l’API arrêtée et le reste du desktop fonctionne normalement. `ASTERIA_LOCAL_API_TOKEN` reste accepté uniquement pour les scripts locaux existants.

Voir [la documentation API](docs/API.md) pour les routes, l’authentification et les restrictions sur les secrets.
