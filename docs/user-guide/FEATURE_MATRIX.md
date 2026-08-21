# Matrice fonctionnelle — RAM 3.7.2 vers Astro Account Manager

Référence historique : tag `3.7.2`, commit `79f61f3351df61fb3774dfa854ab868954da5389`, plus le commit UWP public `73a291e` lorsque le binaire 3.7.2 contient une fonction absente du tag.

Statuts autorisés : `VERIFIED PARITY`, `PARTIAL`, `TESTED BUT NOT VERIFIED`, `MISSING`, `BLOCKED`. Un test mocké ne suffit jamais à déclarer une parité réelle.

| # | Fonctionnalité | RAM 3.7.2 | Astro | Tests / preuve | Statut | Écart restant |
|---:|---|---|---|---|---|---|
| 1 | Chargement et CRUD comptes | `AccountManager.cs`, `Account.cs` | SQLite + service + bridge + UI | tests stockage/service/bridge | VERIFIED PARITY | — |
| 2 | Ajout par cookie | `AccountBrowser.cs`, `Account.Refresh` | validation `/users/authenticated`, DPAPI, UI | deux sessions réelles importées, identité revalidée et secrets conservés dans DPAPI | VERIFIED PARITY | — |
| 3 | Ajout par navigateur dédié | `AccountBrowser.cs` | Edge CDP port dynamique + fallback pywebview + polling UI | vraie fenêtre Edge isolée ouverte/fermée, opération correctement terminée + tests CDP | TESTED BUT NOT VERIFIED | saisie d’un login Roblox complet et capture finale non exécutées |
| 4 | OAuth PKCE | absent de RAM | ajout Astro Open Cloud, vault DPAPI | tests OAuth/callback | TESTED BUT NOT VERIFIED | application OAuth réelle requise |
| 5 | Import bulk user/pass/cookie | import historique | parser multi-format, champs traînants tolérés, déduplication insensible à la casse, mot de passe DPAPI et connexion Edge CDP préremplie/auto-soumise avec contrôle d’identité avant stockage du cookie | tests parser/service/SQLite/CDP, secret absent des arguments, réponses et logs | TESTED BUT NOT VERIFIED | aucun compte disposant d’un mot de passe importé n’a été utilisé pour une connexion Roblox réelle pendant cette passe |
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
| 31 | Multi-instance mutex | `ROBLOX_singletonMutex` et objet moderne `ROBLOX_singletonEvent` | détenteur Win32 persistant, détachement borné du handle singleton des nouveaux clients, préférence persistante et switch UI | deux identités distinctes, deux PID simultanés et deux Place ID distincts confirmés | VERIFIED PARITY | — |
| 32 | UWP découverte/lancement | binaire 3.7.2 / `73a291e` | Get-AppxPackage + AppsFolder | tests PowerShell simulés | TESTED BUT NOT VERIFIED | aucun paquet UWP installé |
| 33 | UWP clones par compte | `UWPInstanceManager.cs` expérimental | copie en staging, manifeste/identité propres au compte, `SupportsMultipleInstances`, enregistrement AppX et désenregistrement exact avec rollback et confirmations | tests PowerShell, manifeste, rollback et bridge/UI | TESTED BUT NOT VERIFIED | aucun paquet Roblox UWP n’est installé sur cette machine pour une preuve réelle |
| 34 | Détails/recherche jeux | `ServerList.cs` | univers, détails, recherche Omni moderne, cache 60 s | endpoint réel : 20 résultats ; premier appel 837 ms, cache 0,009 ms + tests | VERIFIED PARITY | ancien `/v1/games/list` 404 remplacé |
| 35 | Liste serveurs | `ServerList.cs` | pagination bornée et modèle typé | endpoint réel, 50 serveurs retournés + tests | VERIFIED PARITY | — |
| 36 | Recherche joueur dans tous les serveurs | scan `playerTokens` + batch thumbnails RAM | pagination bornée, batch 100, comparaison d’avatar, UI Follow | vrai scan Roblox sur 2 pages sans correspondance + tests pagination/match | TESTED BUT NOT VERIFIED | tentative plus large limitée par HTTP 429 ; aucune cible présente dans les pages testées |
| 37 | Région/ping | `ServerList.loadRegionToolStripMenuItem_Click` appelle `join-game-instance`, lit `MachineAddress`/`ServerPort`, puis géolocalise et ping | sonde authentifiée bornée (16 serveurs), CSRF, résolveur opt-in/cache, ping TCP, bridge et modal de sélection de compte ; aucune IP renvoyée au frontend | tests payload/CSRF/timeout/cache/fallback/UI | TESTED BUT NOT VERIFIED | la sonde authentifiée réelle n’a pas été déclenchée pendant que Roblox était en cours d’utilisation |
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
| 48 | Déverrouillage PIN historique | `UnlockPin` | action legacy conservée uniquement pour diagnostiquer proprement un ancien endpoint ; les réponses 404/410 expliquent le retrait Roblox | validation, CSRF et retrait 404/410 testés | BLOCKED | Roblox a retiré l'Account PIN parental et ses endpoints en novembre 2024 ; Astro ne peut ni créer ni déverrouiller un PIN qui n'existe plus côté plateforme |
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
| 62 | `RAMAccount.lua` | script historique | script généré avec jeton éphémère, handshake et reconnexion automatique, entièrement raccordé au serveur/UI | audit de chaîne + tests WebSocket/protocole | TESTED BUT NOT VERIFIED | comportement en jeu non vérifié faute de client Nexus connecté |
| 63 | 22 routes Developer API RAM | `AccountManager.cs`, `WebServer.cs`, GitBook | 22 routes racine en texte brut, enveloppe historique `/v2`, REST JSON `/api/v1`, permission `AllowGetAccounts` et écoute LAN explicitement activable | matrice complète nom/verbe/query/body/status/content-type + vrai accès LAN à `/api/v1/health` | VERIFIED PARITY | — |
| 64 | Auth API | `EveryRequestRequiresPassword` | bearer 32+ et mot de passe RAM facultatif via query/header, secrets runtime, loopback et permissions communes | tests HTTP Windows : bearer, query, header, refus config/mauvais secret et permission 403 | TESTED BUT NOT VERIFIED | validation restante depuis un vrai script RAM tiers |
| 65 | Permissions API | trois flags RAM | quatre permissions indépendantes + UI | tests 403 | VERIFIED PARITY | import cookie séparé ajouté |
| 66 | Port/bind/erreurs API | WebServer RAM | 127.0.0.1, no-store, limites, erreurs sûres | tests serveur | VERIFIED PARITY | — |
| 67 | Réglages généraux/thème | `SettingsForm.cs` | catégories persistantes, reset par catégorie/global confirmé et UI | tests service/bridge/UI | VERIFIED PARITY | — |
| 68 | Réglages watcher/instances | `ServerList.cs` | relance, timeout, mémoire, titre, Beta Home, capture/restore fenêtre | vrais chemins lancement/fermeture/géométrie + tests service/UI | TESTED BUT NOT VERIFIED | aucun dépassement mémoire/timeout réel n’a été attendu volontairement |
| 69 | Démarrage Windows | `SettingsForm.cs` | HKCU Run Astro confirmé | tests registre simulé + lecture réelle | VERIFIED PARITY | build frozen requis pour activer |
| 70 | Mises à jour | `Updater.cs` | release GitHub Astro + semver | requête GitHub réelle : dépôt et release `v4.0.2` avec asset disponibles + tests HTTP | VERIFIED PARITY | — |
| 71 | ClientSettings/FPS | `ClientSettingsPatcher.cs` | découverte/rebasculement version-*, mirroring atomique, flag >240, plus éditeur typé `GlobalBasicSettings_13.xml` (FPS, volume, qualité, plein écran, caméra), profils et association par groupe avec backup/readback | trois dossiers réels et XML Roblox relus/écrits ; tests mirroring, profil, limites, écriture atomique, rollback et mise à jour | VERIFIED PARITY | les réglages Roblox sont globaux au client installé ; un profil de groupe est appliqué avant lancement, jamais prétendu simultanément différent par processus |
| 72 | Bridge backend→UI | formulaires RAM | parité AST DesktopBridge/adapter | tests contrat | VERIFIED PARITY | — |
| 73 | Ajout compte UI | formulaire/navigateur RAM | cookie, navigateur, bulk, OAuth | UI réelle inspectée ; Edge isolé réel ouvert/fermé ; cookie réel couvert ligne 2 | TESTED BUT NOT VERIFIED | login complet par navigateur et OAuth réel non exécutés |
| 74 | Nexus UI | `AccountControl` | serveur, clients, éditeur, quick scripts, logs | inspection visuelle | TESTED BUT NOT VERIFIED | client en jeu absent |
| 75 | Responsive/accessibilité | WinForms | navigation clavier, labels, états vides, focus visible | inspection réelle à 1080×680, 1366×768 et 1500×960 ; navigation Tab vérifiée | VERIFIED PARITY | — |
| 76 | Build Windows | distribution RAM | PyInstaller onefile avec frontend/webview/websockets | build actuel et smoke test réel de l’EXE sur Windows 11 | VERIFIED PARITY | validation machine propre/signature à répéter pour une publication publique |
| 77 | Solveur CAPTCHA navigateur | `AccountBrowser.Page_FrameAttached`, API NopeCHA + auto-click | profil Edge isolé pouvant charger une extension Chromium de solveur validée via `ASTRO_CAPTCHA_SOLVER_EXTENSION` | tests commande/manifest, aucun CAPTCHA réel | TESTED BUT NOT VERIFIED | extension et challenge Roblox réels non testés ; intégration moderne différente du DOM 3.7.2 |
| 78 | Macro maker intégré | automatisations manuelles autour des instances RAM | page Macros, blocs visuels et DSL strict compilé vers actions bornées persistées en SQLite v4 ; livraison Windows locale sans Nexus | parseur/limites/persistance, bouton `Run` réel, déplacement `W` et ouverture Inventory par clic coordonné sur PID 37660 alors que Roblox était minimisé et Astro restait visible | VERIFIED PARITY | — |
| 79 | Macros concurrentes par instance | watcher RAM associe compte/PID/fenêtre | runs liés à PID+create-time+HWND ; clavier envoyé au HWND iconifié par files d'entrée attachées ; clic coordonné via surface Windows alpha 1/255 invisible puis retour immédiat au bouton `—` | un vrai client : déplacements et clics réels, état `completed`, fenêtre et focus restaurés ; deux PID simulés, cancellation et réemploi PID testés | TESTED BUT NOT VERIFIED | isolation de deux ou trois vrais clients exécutant des macros différentes dans la même période encore à prouver ; les séquences d'entrée Windows sont sérialisées pour empêcher tout mélange |
| 80 | Discord Rich Presence | absent de RAM 3.7.2 | RPC local `discord-ipc-*`, jeu actif ou agrégat, modèles `{game}/{place_id}/{account}/{instances}`, assets conformes au protocole, overrides par PlaceId, bouton HTTPS et alias supprimé en mode streamer | framing/handshake/agrégat/templates/assets/overrides/redaction + Settings UI | TESTED BUT NOT VERIFIED | Discord Application ID, assets publiés et client Discord réels requis |
| 81 | Crash logs et bundle support | logs RAM | hooks fatals et ZIP local expurgé (logs, diagnostics, settings publics, manifeste/hash) | fichier/ZIP réels temporaires, secrets et chemin utilisateur absents | TESTED BUT NOT VERIFIED | crash fatal volontaire de l'EXE non provoqué |
| 82 | Auto-update de l'EXE | `Updater.cs` vérifie une release | source GitHub fixe, asset fixe, taille/PE/SHA-256, staging, backup `.previous.exe`, remplacement seulement en build frozen et au prochain arrêt | release v5.0.0 téléchargée réellement en temporaire (20 992 263 octets), PE/taille/SHA validés + tests staging/tampering/helper/UI | TESTED BUT NOT VERIFIED | remplacement/redémarrage réel du build frozen encore requis ; la release ne publie pas de checksum éditeur séparé |
| 83 | Alerte Roblox déjà ouvert | prérequis historique Multi Roblox | scan exact des processus, modal au bootstrap désactivable, choix de garder ou fermeture confirmée avec revalidation PID/create-time | tests processus/confirmation/identité + audit UI | TESTED BUT NOT VERIFIED | bouton Close volontairement non cliqué pendant la partie de l'utilisateur |
| 84 | Navigateur Roblox authentifié par compte | `OpenBrowser_Click` / `AccountBrowser` | profil Edge/Chrome isolé, cookie HttpOnly injecté via CDP local puis URL `https://*.roblox.com` validée ; sélection explicite de l'onglet `about:blank`, sync/extensions neutralisées | page réelle `https://www.roblox.com/home` affichant `Astrolucifer972`, aucun bouton de connexion, profil temporaire distinct + tests domaine/onglet | VERIFIED PARITY | — |
| 85 | Outils historiques additionnels | Copy Password, Join Group, Universe viewer, Outfits viewer/wear | vault→copie explicite, join group authentifié, pagination universe, liste/détails/port tenue via utilitaires | validation, parsing, HTTP simulé, contrat bridge/UI | TESTED BUT NOT VERIFIED | mutations/réponses Roblox réelles non déclenchées sans cible explicite |
| 86 | Headless / visibilité par instance | ajout Evanovar postérieur à RAM 3.7.2 | recherche de la fenêtre top-level appartenant au PID observé, Hide/Show sans activation, état réel et action globale Show All | API Win32 simulée, identité PID, snapshot groupé, bridge/contrat/UI | TESTED BUT NOT VERIFIED | Hide/Show n'a pas été déclenché sur une fenêtre Roblox réelle pendant cette passe |
| 87 | Server Intelligence et distribution | évolution Fleet, absente de RAM 3.7.2 | score borné ping/places/FPS/stabilité/échecs, filtres, blacklist/historique et distribution multi-compte avec cible JobId distincte préservée jusqu'au worker | score/filtres/plafonds, plans et preuve anti-bleed des cibles dans `test_server_intelligence.py` et `test_automations.py` | TESTED BUT NOT VERIFIED | distribution de plusieurs comptes vers plusieurs JobId réels non lancée pendant cette passe |
| 88 | Mode streamer persistant | évolution RoPilot, absente de RAM 3.7.2 | préférence backend, noms/UserId masqués, avatars floutés, alias Discord supprimé et rollback UI si la sauvegarde échoue | validation config, rendu/contrat frontend et redaction Discord | VERIFIED PARITY | — |
| 89 | HUD performance / fuite mémoire | évolution Evanovar/RoPilot, absente de RAM 3.7.2 | télémétrie read-only CPU/RAM par PID, historique borné, runtime/restarts existants et détection prudente de croissance mémoire | `test_performance_telemetry.py`, payload instance/service/UI | TESTED BUT NOT VERIFIED | seuil de fuite à calibrer sur une session Roblox longue réelle ; le FPS et le réseau par PID ne sont pas inventés quand indisponibles |
| 90 | Scanner de compatibilité / version Roblox | fonctionnalité Astro, absente de RAM 3.7.2 | rapport read-only installation/version, multi-instance, contrôle fenêtre, macros background, auto-rejoin et settings ; changement de version acquitté séparément | capacités simulées, calcul du score, changement de version et bridge/UI | TESTED BUT NOT VERIFIED | une vraie mise à jour Roblox reste nécessaire pour vérifier le cycle complet avant/après |

État après la passe du 21 août 2026 : **51 `VERIFIED PARITY`**, **0 `PARTIAL`**, **38 `TESTED BUT NOT VERIFIED`**, **1 `BLOCKED`**, aucune fonctionnalité `MISSING`. Le blocage est externe et précis : l'ancien PIN parental n'existe plus dans Roblox. Le détail des preuves Windows antérieures se trouve dans [`docs/QA_MATRIX_2026-08-11.md`](../QA_MATRIX_2026-08-11.md). Une ligne `TESTED BUT NOT VERIFIED` possède son implémentation et ses tests, mais attend encore une preuve externe spécifique ; ce statut n’est pas une limitation transformée artificiellement en parité.

Les lignes `PARTIAL` et `TESTED BUT NOT VERIFIED` restent du travail réel : elles ne sont jamais transformées en parité vérifiée sans preuve adaptée. Les mutations externes irréversibles (mot de passe, email, relations sociales) exigent en plus une valeur cible explicite avant un essai sur un compte réel. Aucun compte Roblox n'est créé automatiquement et aucun CAPTCHA n'est contourné : l'ajout légitime reste assuré par navigateur isolé manuel, cookie explicite, import bulk ou OAuth identité/profil.

## 2026-08-13 - Corrections de defauts signales en usage reel

Les statuts canoniques ne changent pas dans cette passe ; les preuves Windows
ci-dessous complètent les correctifs sans reclasser artificiellement une ligne.

| Defaut signale | Cause racine trouvee | Correctif | Preuve encore due |
| --- | --- | --- | --- |
| Multi Roblox echoue par intermittence | Handle ferme et operation abandonnee quand l'objet singleton existait deja ; seul le mutex etait detenu ; propriete prise sur un thread quelconque | Objet existant adopte, mutex + event detenus sur un thread dedie longue duree, liberation explicite avant fermeture | Deux clients simultanes confirmes par l'utilisateur |
| FPS unlocker sans effet | Decouverte limitee, dossier devenu obsolete, categorie `performance` absente et echec silencieux | Repli puis rebasculement dynamique, mirroring multi-dossiers, flag >240, relecture et echec visible | Trois vrais fichiers verifies a 144 ; effet d'un changement sur un nouveau client/teleport encore a confirmer |
| Watcher semble inactif | Boucle de polling conforme ; il manquait le reglage par compte | Preuve que la boucle scanne ; cle `enabled` par compte exposee dans la page de gestion | Relance automatique confirmee par l'utilisateur |
| Onglet Games & servers inerte | Donnees non chargees puis callback `find()` non lie a `this`, interrompant tout le rendu avec des jeux sauvegardes | Recherche exposee de bout en bout et callback lie ; test anti-regression | Clic UI reel : deux jeux affiches et 50 serveurs charges |

## Annexe 2026-08-13 - reparation du watchdog par compte

Aucun statut n'est promu par cette passe. Les causes racines corrigees sont
consignees ici pour que la preuve Windows attendue soit explicite.

| # | Symptome | Cause racine | Correctif |
| --- | --- | --- | --- |
| 1 | La relance automatique ne se declenche jamais | Quatre verrous, dont deux inaccessibles depuis la fiche du compte | Decision unique `_relaunch_arming_state`, armement depuis la fiche |
| 2 | La case *Watch this account* revient cochee | `_account_payload` n'exposait pas `enabled` | La cle est exposee |
| 3 | La regle de relance affiche un compte desactive comme actif | Defauts du modal sans `enabled` | Defaut ajoute |
| 4 | Aucun reglage de relance par profil | Formulaire limite a un booleen | Delai, tentatives et declencheurs ajoutes |
| 5 | Une regle sauvegardee restait inerte sans le dire | Aucun retour d'etat | `effective` renvoye et affiche |

Preuve Windows attendue : un compte arme, un client tue depuis le gestionnaire
de taches, un relancement observe apres le delai configure, puis l'arret des
tentatives une fois le maximum atteint.

## Annexe 2026-08-14 - ecran Fleet et macros de controle

Aucun statut canonique n'est promu par cette passe. Les surfaces ci-dessous sont
implementees et couvertes par des tests hors ligne ; la preuve Windows reste due
pour tout ce qui touche a une vraie fenetre Roblox.

| Domaine | Ce qui est reellement fait | Test | Preuve encore due |
| --- | --- | --- | --- |
| Statistiques | tableau de bord, heatmap horaire par jour, score de fiabilite par compte, taux de reussite des macros, comparaison de deux sessions | `test_statistics.py`, `test_fleet_features.py` | fenetre reelle de plusieurs jours de farm |
| Planification | taches horaires par jour de semaine (lancer un groupe, arreter les macros, fermer des clients), prochaine execution calculee, balayage silencieux dans le watcher | `test_scheduler.py`, `test_fleet_features.py` | une tache 18:00 declenchee sur la machine de l'utilisateur |
| Sante des comptes | session expiree, authentification requise, echec de lancement, client ferme, plus tags filtrables, champs personnalises et priorite 0-10 | `test_account_health.py`, `test_fleet_features.py` | un compte a la session reellement expiree |
| Serveurs | inspecteur JobId, historique, liste noire annotee, choix intelligent avec motif de rejet, affinite de region | `test_server_registry.py`, `test_fleet_features.py` | hopping reel entre deux serveurs pleins |
| Coordination | Spread, Main + followers, lancement synchronise, party interne bornee a 8 | `test_coordination.py`, `test_fleet_features.py` | huit clients reels rejoignant le meme JobId |
| Confort | Focus, Sleep, mixer par instance (niveaux stockes), arret securise confirme, file de lancement gardee par CPU/RAM | `test_comfort.py`, `test_fleet_features.py` | minimisation reelle et arret securise sur Windows |
| Alertes | webhook Discord, relais telephone, evenements filtrables, intervalle minimal, rapport quotidien | `test_alerts.py`, `test_fleet_features.py` | un webhook reel appele une fois |
| Macros avancees | blocs Condition / Launch / Teleport / Restart dans l'editeur visuel et dans le DSL, profils de touches, variables par compte, debogueur pas-a-pas, profiler, versions et rollback, execution par groupe | `test_macro_engine_features.py`, `test_macro_studio.py`, `test_frontend_fleet_ui.py` | une macro conditionnelle qui pilote vraiment un avatar |
| Vagues de lancement | pause entre deux vagues en plus de la sonde de disponibilite | `test_batch_waves.py` | dix comptes lances par vagues de trois |
| Reprise de macro | une macro interrompue repart apres une relance automatique, avec plafond de tentatives | `test_rejoin_rules.py`, `test_macro_studio.py` | un client tue puis relance pendant une macro |

Nouvelles commandes du DSL de macros : `IF <condition> [valeur] ... END`,
`LAUNCH`, `TELEPORT <place_id> [job_id]`, `RESTART`, en plus de `WAIT`, `PRESS`,
`DOWN`, `UP`, `CLICK`, `TEXT`, `REPEAT ... END` et `STOP`. Aucune evaluation de
code arbitraire n'est ajoutee : un bloc Condition n'accepte que les huit
verifications que le moteur sait reellement repondre.

Limites assumees, non contournees :

- l'envoi d'entrees reste au premier plan pour une seule fenetre Roblox ; le
  farm fenetre minimisee demanderait `PostMessage`/`SendMessage` ou un pilote
  d'entree virtuel ;
- un bloc Condition visuel contient exactement une action ; un arbre plus
  profond s'ecrit dans l'editeur DSL ;
- Roblox n'expose aucune API de party : une party interne signifie le meme
  JobId, pas une vraie invitation ;
- le volume par instance est stocke, pas applique ;
- les notifications telephone passent par un relais webhook, sans application
  mobile ;
- l'onglet Nexus reste masque derriere `ASTRO_ENABLE_NEXUS`, conserve pour un
  developpement ulterieur et retire des chemins de macros.

## v11 additions

| Feature | Where | State |
| --- | --- | --- |
| Launch profiles (place, server, FPS, group, note) | Fleet → Launch profiles | Shipped, 12 tests |
| Launch a profile through the wave launcher | Fleet → Launch profiles → Launch | Shipped, delegates to `start_wave_launch` |
| Emergency stop (macros + launch queue + resumes + rules) | Fleet → Comfort | Shipped, never closes a client |
| Unattended state on the dashboard | Dashboard status pill | Shipped, inferred from "in game, no macro, past the sleep delay" |
| Machine-checked feature inventory | `python scripts/feature_inventory.py` | 91 features proven, exits non-zero if a claim breaks |
| Settings snapshot cache | internal | Shipped, guard test included |

### What "unattended" means

Roblox does not expose a player's idle timer to another program. Astro reports a
client as unattended when it is in a game, no macro is running on it, and it has
been up longer than `comfort.sleep_after_minutes`. It is an inference, not a read
of the game state, and the label in the UI says so.

### Still deliberately absent

| Area | Why |
| --- | --- |
| Vision (screenshots, timeline, frozen screen, pixel conditions, template matching, visual triggers) | Excluded by the project owner. |
| Remote (phone dashboard, QR pairing, remote screenshot) | Excluded by the project owner. |
| Farming a minimized window | Input goes to the foreground window. Doing it properly needs `PostMessage`/`SendMessage` per HWND or an isolated virtual input driver: a separate project, not a flag. |
