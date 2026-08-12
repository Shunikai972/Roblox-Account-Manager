# Matrice fonctionnelle — RAM 3.7.2 vers Astro Account Manager

Référence historique : tag `3.7.2`, commit `79f61f3351df61fb3774dfa854ab868954da5389`, plus le commit UWP public `73a291e` lorsque le binaire 3.7.2 contient une fonction absente du tag.

Statuts autorisés : `VERIFIED PARITY`, `PARTIAL`, `TESTED BUT NOT VERIFIED`, `MISSING`, `BLOCKED`. Un test mocké ne suffit jamais à déclarer une parité réelle.

| # | Fonctionnalité | RAM 3.7.2 | Astro | Tests / preuve | Statut | Écart restant |
|---:|---|---|---|---|---|---|
| 1 | Chargement et CRUD comptes | `AccountManager.cs`, `Account.cs` | SQLite + service + bridge + UI | tests stockage/service/bridge | VERIFIED PARITY | — |
| 2 | Ajout par cookie | `AccountBrowser.cs`, `Account.Refresh` | validation `/users/authenticated`, DPAPI, UI | deux sessions réelles importées, identité revalidée et secrets conservés dans DPAPI | VERIFIED PARITY | — |
| 3 | Ajout par navigateur dédié | `AccountBrowser.cs` | Edge CDP port dynamique + fallback pywebview + polling UI | vraie fenêtre Edge isolée ouverte/fermée, opération correctement terminée + tests CDP | TESTED BUT NOT VERIFIED | saisie d’un login Roblox complet et capture finale non exécutées |
| 4 | OAuth PKCE | absent de RAM | ajout Astro Open Cloud, vault DPAPI | tests OAuth/callback | TESTED BUT NOT VERIFIED | application OAuth réelle requise |
| 5 | Import bulk user/pass/cookie | import historique | parser multi-format, champs traînants tolérés, déduplication insensible à la casse conservant cookie puis mot de passe, validation cookie et mot de passe DPAPI | tests parser/service/SQLite, y compris formats virgule et absence du secret en clair | PARTIAL | le login automatique par mot de passe reste à implémenter ; le mot de passe importé est protégé mais pas encore utilisé pour ouvrir une session |
| 6 | Suppression de comptes | liste WinForms | suppression transactionnelle + oubli watcher/vault | tests service | VERIFIED PARITY | — |
| 7 | Alias | `Account.Alias` | champ distinct, UI et API | tests service/API | VERIFIED PARITY | — |
| 8 | Description | `Account.Description` | édition/remplacement/append | tests API | VERIFIED PARITY | — |
| 9 | Champs personnalisés | `Account.Fields` | mapping persistant + API | tests API | VERIFIED PARITY | — |
| 10 | Groupes | préfixes de groupes RAM | CRUD, déplacement, collapse, ordre | tests stockage/migration/UI | VERIFIED PARITY | — |
| 11 | Tri comptes/groupes | ordre RAM | `sort_order` atomique et stale-safe | tests stockage/service | VERIFIED PARITY | — |
| 12 | Recherche/filtres | liste RAM | recherche, statut, cartes/table | tests UI + inspection visuelle | VERIFIED PARITY | — |
| 13 | Avatar public | thumbnails RAM | profil/headshot publics et cache | endpoint Roblox réel + UI + tests | VERIFIED PARITY | — |
| 14 | Présence publique | `Presence.cs` | batch 50, cache, UI | endpoint Roblox réel + tests client/service | VERIFIED PARITY | — |
| 15 | Dernière utilisation | `LastUse` | `last_used_at` et récents | tests repository/service | VERIFIED PARITY | — |
| 16 | Validation/refresh session | `Account.Refresh` | identité authentifiée et contrôle de correspondance | vraie session revalidée + tests | VERIFIED PARITY | — |
| 17 | DPAPI / vault | `ProtectedData` historique | DPAPI CurrentUser, secrets hors SQLite | tests Windows et migration | VERIFIED PARITY | format différent, migration dédiée |
| 18 | Backup/restauration | copies RAM | manifestes SHA-256, restore atomique confirmé | tests réels SQLite | VERIFIED PARITY | — |
| 19 | Export/import métadonnées | export RAM | JSON public checksummé, sans vault | tests transfert | VERIFIED PARITY | — |
| 20 | Affichage/copie session brute | cookie RAM | action UI explicite + bridge | tests service/bridge | VERIFIED PARITY | presse-papiers système non inspecté |
| 21 | Export sessions brutes | export cookie RAM | fichier plaintext confirmé, dossier exports | test fichier réel | VERIFIED PARITY | ACL Windows dépend du profil courant |
| 22 | Lancement authentifié normal | `Account.JoinServer` | ticket JSON/CSRF + URI `rbx-player` par session | deux vrais comptes/clients lancés, identités des logs concordantes | VERIFIED PARITY | — |
| 23 | PlaceId / JobId | `JoinServer` | priorité cible explicite puis cible sauvegardée par compte, sans écrasement croisé | deux vrais comptes lancés simultanément vers deux Place ID distincts, confirmés par PID et logs | VERIFIED PARITY | JobId réel couvert séparément par les tests URI |
| 24 | Serveur privé/VIP | `ServerList.cs` | parse code/lien et URI authentifiée | tests URI | TESTED BUT NOT VERIFIED | vrai serveur privé non testé |
| 25 | Suivre un joueur | API/ServerList | résolution + présence + JobId | présence Roblox réelle interrogée + tests de résolution/lancement | TESTED BUT NOT VERIFIED | Place/Job masqués par la confidentialité pendant l’essai réel |
| 26 | Serveur aléatoire | `SetRecommendedServer` | sélection page publique | endpoint Roblox réel interrogé, JobId valide retourné + tests typés | VERIFIED PARITY | — |
| 27 | Sauvegarde PlaceId/JobId | champs RAM | compte + Quick Controls | tests service/UI | VERIFIED PARITY | — |
| 28 | Lancement multiple/file | délai RAM | worker borné, annulation, statut, UI | tests batch | VERIFIED PARITY | — |
| 29 | Délai entre lancements | `AccountJoinDelayMS` | 0,5–3600 s validé | tests batch | VERIFIED PARITY | — |
| 30 | Prévention doublon compte | option instances RAM | instance ou intention pending atomique | test watcher | VERIFIED PARITY | — |
| 31 | Multi-instance mutex | `ROBLOX_singletonMutex` | mutex Win32 exact, préférence persistante et switch UI | deux identités distinctes, deux PID simultanés et deux Place ID distincts confirmés | VERIFIED PARITY | — |
| 32 | UWP découverte/lancement | binaire 3.7.2 / `73a291e` | Get-AppxPackage + AppsFolder | tests PowerShell simulés | TESTED BUT NOT VERIFIED | aucun paquet UWP installé |
| 33 | UWP clones par compte | `UWPInstanceManager.cs` expérimental | découverte seulement | audit source | PARTIAL | copie/register/uninstall non portés |
| 34 | Détails/recherche jeux | `ServerList.cs` | univers, détails, recherche Omni moderne, cache 60 s | endpoint réel : 20 résultats ; premier appel 837 ms, cache 0,009 ms + tests | VERIFIED PARITY | ancien `/v1/games/list` 404 remplacé |
| 35 | Liste serveurs | `ServerList.cs` | pagination bornée et modèle typé | endpoint réel, 50 serveurs retournés + tests | VERIFIED PARITY | — |
| 36 | Recherche joueur dans tous les serveurs | scan `playerTokens` + batch thumbnails RAM | pagination bornée, batch 100, comparaison d’avatar, UI Follow | vrai scan Roblox sur 2 pages sans correspondance + tests pagination/match | TESTED BUT NOT VERIFIED | tentative plus large limitée par HTTP 429 ; aucune cible présente dans les pages testées |
| 37 | Région/ping | `ServerList`, `IPApiLink`, `ServerRegionFormat` | résolveur opt-in, transport HTTP borné sans redirection, cache LRU/TTL, fallback, filtrage IP, service/bridge/UI Settings et rendu serveur | tests timeout/cache/format/transport/settings sans appel réseau réel | PARTIAL | la liste publique Roblox ne fournit généralement pas l’adresse machine ; preuve réelle à faire lorsqu’une adresse de serveur est disponible |
| 38 | Univers | résolution PlaceId→UniverseId | client public typé | résolution réelle pendant le test jeu + tests | VERIFIED PARITY | — |
| 39 | Changement mot de passe | `Account.ChangePassword` | endpoint authentifié + UI | validation/CSRF/réponses HTTP contrôlées | TESTED BUT NOT VERIFIED | aucune nouvelle valeur réelle fournie |
| 40 | Changement email | `Account.ChangeEmail` | endpoint authentifié + UI | validation/CSRF/réponses HTTP contrôlées | TESTED BUT NOT VERIFIED | aucune adresse cible réelle fournie |
| 41 | Logout autres sessions | `LogOutOfOtherSessions` | endpoint authentifié + UI | succès/erreurs/rotation testés | TESTED BUT NOT VERIFIED | non exécuté sur les sessions réelles pour ne pas les révoquer |
| 42 | Confidentialité follow | `SetFollowPrivacy` | cinq valeurs historiques + UI | tests HTTP simulés | TESTED BUT NOT VERIFIED | endpoint historique peut évoluer |
| 43 | Display name | `SetDisplayName` | PATCH authentifié + UI | validation et réponses HTTP testées | TESTED BUT NOT VERIFIED | aucun nouveau nom réel fourni |
| 44 | Ami | `SendFriendRequest` | ID ou username exact + UI | résolution et réponses HTTP testées | TESTED BUT NOT VERIFIED | aucun joueur cible réel fourni |
| 45 | Blocage/déblocage | `TogglePlayerBlocked` | block/unblock/list/all + API/UI | lecture réelle des listes des deux comptes ; mutations HTTP testées | TESTED BUT NOT VERIFIED | aucune cible réelle fournie pour block/unblock |
| 46 | Quick Log In | login rapide RAM | code six chiffres + UI | tests validation/HTTP | TESTED BUT NOT VERIFIED | vrai code non testé |
| 47 | Avatar/tenue | `SetAvatar` | assets portés + UI/API | tests validation/HTTP | TESTED BUT NOT VERIFIED | échelle/type avatar partiels |
| 48 | Déverrouillage PIN | `UnlockPin` | PIN quatre chiffres + UI | tests HTTP simulés | TESTED BUT NOT VERIFIED | endpoint Roblox possiblement retiré |
| 49 | Auth ticket | `GetCSRFToken`/launcher | POST JSON, challenge CSRF, ticket Roblox + copie UI | vrai endpoint : 403 CSRF puis 200 ticket + tests | VERIFIED PARITY | — |
| 50 | Lien `rbx-player` | launcher RAM | URI encodée et copiable | vrai handler/client lancé + tests URI | VERIFIED PARITY | — |
| 51 | Détection processus | `RobloxWatcher.cs` | psutil PID+create-time | vrai `RobloxPlayerBeta` détecté + tests état | VERIFIED PARITY | — |
| 52 | Association compte/PID | tracker RAM | intentions non ambiguës + bind confirmé | vrai PID associé au compte (`launch_matched`) + tests | VERIFIED PARITY | — |
| 53 | Watcher logs | `RobloxProcess.cs` | découverte par horodatage de création, tail incrémental borné et association PID/log | deux vrais clients et deux logs associés aux bons PID/Place ID + 13 tests | VERIFIED PARITY | — |
| 54 | Fermeture timeout/mémoire/titre | `RobloxWatcher.cs` après grâce, fenêtre non focus | règles opt-in, fenêtre/processus vérifiés, seuils UI, fermeture gracieuse | deux vrais clients fermés séparément ; statuts réconciliés sans faux `in_game` + tests | VERIFIED PARITY | fermeture automatique par seuil reste couverte ligne 68 |
| 55 | Beta Home | titre attendu RAM | règle automatique après grâce de 30 s, processus et titre exacts vérifiés | tests plateforme/âge/processus | TESTED BUT NOT VERIFIED | aucune vraie fenêtre Beta Home n’est apparue pendant la validation |
| 56 | Auto-relaunch | watcher/Nexus RAM | double opt-in, délai/tentatives bornés et réutilisation session/cible du compte | vrai client forcé en crash puis nouveau PID relancé vers le bon Place ID + tests | VERIFIED PARITY | le test agressif à 1 s a produit un 267 ; valeur sûre par défaut restaurée à 15 s |
| 57 | Positionnement fenêtre | `AdjustWindowPosition` | déplacement Win32 vérifié par PID | vraie fenêtre Roblox déplacée à des coordonnées exactes puis restaurée + tests | VERIFIED PARITY | — |
| 58 | Mémorisation fenêtre | champs `Window_*`, capture après 30 s, restore 45 s | géométrie par compte, capture périodique, restore borné, actions UI | vraie géométrie capturée en métadonnées puis restaurée par le service + tests | VERIFIED PARITY | — |
| 59 | Nexus serveur/handshake | `Nexus/*` | WebSocket `/Nexus`, jeton, identité | tests réseau locaux | TESTED BUT NOT VERIFIED | aucun client Roblox en jeu |
| 60 | Nexus Ping/Log/Echo/Set* | `RAMAccount.lua` | messages typés et logs redacted | tests serveur | TESTED BUT NOT VERIFIED | client réel non testé |
| 61 | Nexus execute/teleport/mute/unmute | `AccountControl.cs` | commandes et UI exécuteur | tests serveur/UI | TESTED BUT NOT VERIFIED | exécution en jeu non testée |
| 62 | `RAMAccount.lua` | script historique | script généré avec jeton et auto-reconnect | audit/tests chaîne | PARTIAL | comportement en jeu non vérifié |
| 63 | 22 routes Developer API RAM | `AccountManager.cs`, `WebServer.cs`, GitBook | 22 routes compat + REST v1 et permission `AllowGetAccounts` distincte | routes exercées individuellement sur HTTP loopback + tests 403/200 de la permission | PARTIAL | réponses legacy texte brut encore enveloppées en JSON ; `AllowExternalConnections` reste requis mais non porté |
| 64 | Auth API | `EveryRequestRequiresPassword` | bearer 32+ et mot de passe RAM facultatif via query/header, secrets runtime, loopback et permissions communes | tests HTTP Windows : bearer, query, header, refus config/mauvais secret et permission 403 | TESTED BUT NOT VERIFIED | validation restante depuis un vrai script RAM tiers |
| 65 | Permissions API | trois flags RAM | quatre permissions indépendantes + UI | tests 403 | VERIFIED PARITY | import cookie séparé ajouté |
| 66 | Port/bind/erreurs API | WebServer RAM | 127.0.0.1, no-store, limites, erreurs sûres | tests serveur | VERIFIED PARITY | — |
| 67 | Réglages généraux/thème | `SettingsForm.cs` | catégories persistantes + UI | tests service/UI | VERIFIED PARITY | — |
| 68 | Réglages watcher/instances | `ServerList.cs` | relance, timeout, mémoire, titre, Beta Home, capture/restore fenêtre | vrais chemins lancement/fermeture/géométrie + tests service/UI | TESTED BUT NOT VERIFIED | aucun dépassement mémoire/timeout réel n’a été attendu volontairement |
| 69 | Démarrage Windows | `SettingsForm.cs` | HKCU Run Astro confirmé | tests registre simulé + lecture réelle | VERIFIED PARITY | build frozen requis pour activer |
| 70 | Mises à jour | `Updater.cs` | release GitHub Astro + semver | requête GitHub réelle exécutée + tests HTTP | TESTED BUT NOT VERIFIED | dépôt/release configuré répond actuellement 404 |
| 71 | ClientSettings/FPS | `ClientSettingsPatcher.cs` | découverte registre version-* + écriture atomique | installation réelle découverte ; FPS 144 écrit, vérifié, retiré puis SHA original restauré + tests | VERIFIED PARITY | — |
| 72 | Bridge backend→UI | formulaires RAM | parité AST DesktopBridge/adapter | tests contrat | VERIFIED PARITY | — |
| 73 | Ajout compte UI | formulaire/navigateur RAM | cookie, navigateur, bulk, OAuth | UI réelle inspectée ; Edge isolé réel ouvert/fermé ; cookie réel couvert ligne 2 | TESTED BUT NOT VERIFIED | login complet par navigateur et OAuth réel non exécutés |
| 74 | Nexus UI | `AccountControl` | serveur, clients, éditeur, quick scripts, logs | inspection visuelle | TESTED BUT NOT VERIFIED | client en jeu absent |
| 75 | Responsive/accessibilité | WinForms | navigation clavier, labels, états vides, focus visible | inspection réelle à 1080×680, 1366×768 et 1500×960 ; navigation Tab vérifiée | VERIFIED PARITY | — |
| 76 | Build Windows | distribution RAM | PyInstaller onefile avec frontend/webview/websockets | build actuel et smoke test réel de l’EXE sur Windows 11 | VERIFIED PARITY | validation machine propre/signature à répéter pour une publication publique |
| 77 | Solveur CAPTCHA navigateur | `AccountBrowser.Page_FrameAttached`, API NopeCHA + auto-click | profil Edge isolé pouvant charger une extension Chromium de solveur validée via `ASTRO_CAPTCHA_SOLVER_EXTENSION` | tests commande/manifest, aucun CAPTCHA réel | TESTED BUT NOT VERIFIED | extension et challenge Roblox réels non testés ; intégration moderne différente du DOM 3.7.2 |

État après l’intégration du 12 août 2026 : **46 `VERIFIED PARITY`**, **5 `PARTIAL`**, **26 `TESTED BUT NOT VERIFIED`**, aucune fonctionnalité `MISSING`. Le détail de la passe réelle précédente se trouve dans [`docs/QA_MATRIX_2026-08-11.md`](../QA_MATRIX_2026-08-11.md) ; la ligne 64 a depuis quitté `PARTIAL` grâce à la coexistence bearer/password testée localement.

Les lignes `PARTIAL` et `TESTED BUT NOT VERIFIED` restent du travail réel : elles ne sont jamais transformées en parité vérifiée sans preuve adaptée. Les mutations externes irréversibles (mot de passe, email, PIN, relations sociales) exigent en plus une valeur cible explicite avant un essai sur un compte réel.
