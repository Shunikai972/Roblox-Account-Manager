# Prompt de passation pour Opus — Astro Account Manager

Tu reprends entièrement le projet **Astro Account Manager** depuis le code
source contenu dans cette archive.

## 1. Mission non négociable

Astro Account Manager est une **conversion fidèle** de Roblox Account Manager
(RAM) 3.7.2 vers une architecture Python 3.12 + pywebview + SQLite/DPAPI +
HTML/CSS/JavaScript.

Ton objectif n'est pas de réinventer le produit ni de choisir les fonctions à
conserver. Tu dois :

1. retrouver le comportement historique exact ;
2. le traduire dans la nouvelle architecture ;
3. l'exposer réellement backend → service → bridge → frontend ;
4. le tester ;
5. le valider en environnement réel dès que possible ;
6. mettre à jour la matrice avec une preuve honnête.

Une ligne `PARTIAL` signifie **travail à implémenter**, pas « limitation connue ».
Une ligne `TESTED BUT NOT VERIFIED` signifie que le code existe mais qu'une
preuve réelle suffisante manque encore. Ne transforme jamais ces états en
`VERIFIED PARITY` sur la seule base de mocks.

Ne retire ou ne remplace aucune fonction historique de ta propre initiative.
En particulier, les fonctions suivantes font partie du périmètre voulu :

- affichage, copie et export brut volontaire des sessions/cookies ;
- génération/copie des tickets et liens d'authentification ;
- ajout par cookie et navigateur isolé ;
- multi-instance Roblox ;
- outils de compte authentifiés ;
- Nexus, script Lua et commandes historiques ;
- UWP et fonctions expérimentales documentées ;
- solveur CAPTCHA facultatif fourni/configuré par l'utilisateur.

Les secrets doivent rester protégés au repos et redacted dans les logs, mais
l'utilisateur doit conserver les actions explicites d'affichage/export déjà
portées. Ne supprime pas ces actions sous prétexte de redesign.

## 2. Sources historiques

La distribution binaire et les logiciels compilés ne sont volontairement pas
inclus dans cette archive.

Sources de référence :

- dépôt : `https://github.com/ic3w0lf22/Roblox-Account-Manager.git` ;
- tag RAM 3.7.2 : commit
  `79f61f3351df61fb3774dfa854ab868954da5389` ;
- UWP complémentaire : branche/commit public `73a291e`, qui contient
  `Forms/UWPInstanceManager.cs` ;
- fichiers importants : `AccountManager.cs`, `Account.cs`, `AccountUtils.cs`,
  `AccountBrowser.cs`, `ServerList.cs`, `RobloxWatcher.cs`,
  `ClientSettingsPatcher.cs`, `SettingsForm.cs`, `Nexus/*`, `RAMAccount.lua`.

Clone ces références uniquement dans un dossier d'analyse séparé si tu en as
besoin. Ne mélange pas le code historique compilé avec le nouveau projet.

## 3. État exact de la matrice

La matrice canonique est :

`docs/user-guide/FEATURE_MATRIX.md`

État au 12 août 2026 :

- 77 fonctionnalités recensées ;
- 46 `VERIFIED PARITY` ;
- 5 `PARTIAL` ;
- 26 `TESTED BUT NOT VERIFIED` ;
- 0 `MISSING` ;
- 0 `BLOCKED`.

Le rapport détaillé de la dernière validation est :

`docs/QA_MATRIX_2026-08-11.md`

Lis entièrement ces deux fichiers, puis lis aussi :

- `docs/PORTING_LEDGER.md` ;
- `docs/architecture/PROJECT_ANALYSIS.md` ;
- `docs/architecture/FINAL_AUDIT.md` ;
- `docs/API.md` ;
- `app/frontend/BRIDGE_CONTRACT.md` ;
- `docs/user-guide/CONFIGURATION.md` ;
- `docs/troubleshooting/SECURITY.md`.

## 4. Correctifs récents déjà réalisés — ne pas les régresser

### 4.1 Lancement authentifié et HTTP 415

Le ticket Roblox utilise désormais :

- un POST JSON explicite ;
- le challenge CSRF 403 ;
- le second POST avec le token CSRF ;
- une réponse ticket HTTP 200 ;
- une URI `rbx-player` encodée correctement.

Fichiers principaux :

- `app/backend/roblox/auth_tools.py` ;
- `app/backend/roblox/launcher.py` ;
- `app/backend/services/application_service.py`.

Ne réintroduis pas l'ancien POST qui provoquait HTTP 415.

### 4.2 Multi-compte et faux états `in_game`

Le lancement doit respecter les invariants suivants :

1. une cible explicitement fournie gagne ;
2. sinon, le PlaceId/JobId sauvegardé du compte gagne ;
3. la cible globale n'est qu'un fallback ;
4. un lancement ponctuel ne doit pas écraser la cible sauvegardée ;
5. le bulk launch doit laisser chaque compte résoudre sa propre cible ;
6. une intention watcher doit être enregistrée **avant** le handoff Windows ;
7. l'intention doit être annulée si le launcher échoue ;
8. un compte ne devient `in_game` qu'après association avec un vrai PID ;
9. après un scan complet, un état persistant sans PID/intention doit revenir à
   `ready` ;
10. les boutons doivent empêcher le double clic sans bloquer les autres comptes.

Les fichiers clés sont :

- `app/backend/services/application_service.py` ;
- `app/backend/watchers/process_monitor.py` ;
- `app/frontend/src/app.js` ;
- `tests/test_application_service.py` ;
- `tests/test_deep_qa_repairs.py` ;
- `tests/test_frontend_bridge.py`.

Preuve réelle obtenue :

- compte Astrolucifer972 → PlaceId `2512643572` ;
- compte Pierremayou → PlaceId `16146832113` ;
- deux sessions et identités distinctes ;
- deux PID Roblox simultanés ;
- deux logs associés au bon PID et au bon PlaceId ;
- fermeture indépendante de chaque client ;
- les deux comptes reviennent ensuite à `ready`.

Ne mets jamais les cookies, tickets ou lignes de commande complètes dans les
logs, tests, captures ou rapports.

### 4.3 Watcher multi-log

La corrélation multi-processus utilise l'horodatage UTC du fichier Player log et
la date de création du processus. La découverte reste bornée, traite la rotation
et refuse une association ambiguë/incomplète.

Fichiers :

- `app/backend/watchers/roblox_log_runtime.py` ;
- `app/backend/watchers/roblox_log_watcher.py` ;
- `tests/test_roblox_log_runtime.py` ;
- `tests/test_roblox_log_watcher.py`.

Treize tests ciblés couvrent actuellement ce sous-système.

### 4.4 Auto-relaunch et Error 267

Le vrai scénario suivant a été exécuté : lancement, association PID, crash
forcé, planification, nouveau PID, nouvelle jointure vers le PlaceId du compte.

Une valeur volontairement agressive de 1 seconde a provoqué un code Roblox 267
pendant le test, probablement parce que l'ancienne session n'était pas encore
libérée côté serveur. Les valeurs ont été restaurées :

- `watcher.auto_relaunch_enabled = false` ;
- `watcher.scan_interval_seconds = 6` ;
- `watcher.relaunch_delay_seconds = 15`.

Si tu renforces cette zone, conserve la compatibilité et ajoute une attente
fondée sur la disparition/fin du processus plus un cooldown serveur borné. Ne
masque pas un kick 267 provenant réellement de l'expérience ou des modérateurs.

### 4.5 Recherche de jeux et performances

L'ancien endpoint `/v1/games/list` répondait 404. `RobloxClient.search_games`
utilise maintenant Omni Search, parse `searchResults[].contents`, limite les
résultats et utilise un cache de 60 secondes.

Mesure réelle observée :

- premier appel : environ 837 ms ;
- appel en cache : environ 0,009 ms ;
- 20 résultats pour la requête de test.

Le frontend ne charge plus jeux/serveurs au démarrage. Il attend l'ouverture de
la page Games. Le monitor utilise des payloads compacts et un polling protégé
contre les requêtes concurrentes.

### 4.6 Connexion navigateur

Une vraie fenêtre Edge isolée a été ouverte. Fermer cette fenêtre termine
désormais l'opération avec une erreur propre au lieu de laisser `waiting` pour
toujours. Le modal frontend se ferme dès que le navigateur externe démarre.

Fichiers :

- `app/backend/roblox/browser_login.py` ;
- `app/backend/services/application_service.py` ;
- `app/frontend/src/app.js` ;
- `tests/test_browser_login_flow.py`.

Le login complet et la capture finale n'ont pas été exécutés pendant la dernière
passe. Cette validation reste à faire avec une connexion utilisateur réelle.

### 4.7 Boutons et frontend

Les contrôles Launch, bulk launch, fermeture/association d'instance, favoris,
OAuth, startup et connexion navigateur possèdent des erreurs visibles et ne
doivent plus échouer silencieusement.

Audit obtenu :

- 81 noms `data-action` ;
- 82 handlers click ;
- les deux noms non-click sont gérés par `change` et `input` ;
- 24 formulaires ont un handler ;
- contrôle visuel à 1080×680, 1366×768 et 1500×960 ;
- navigation Tab et focus visibles.

Conserve la parité AST entre `DesktopBridge`, `CONTRACT_METHODS`, le bridge
frontend et la documentation. Le test `test_frontend_contract_covers_desktop_bridge_methods`
doit rester vert.

## 5. Les cinq fonctions `PARTIAL` — priorité de développement

### Nº 5 — Import username/password/cookie

Historique : import RAM de comptes avec identifiants, mots de passe et cookies.

État Astro : parser, transactions, validation cookie et stockage DPAPI existent.
Le login automatique username/password n'existe pas.

Travail demandé :

1. relire l'import historique ;
2. déterminer un flow de connexion actuel compatible ;
3. le porter sans exposer le mot de passe ;
4. raccorder service/bridge/UI ;
5. ajouter tests succès/erreur/annulation/identité ;
6. valider réellement si des identifiants de test sont explicitement fournis.

### Nº 33 — Clones UWP par compte

Historique : `UWPInstanceManager.cs` expérimental, copie/register/uninstall de
paquets par compte.

État Astro : découverte lecture seule et lancement d'un paquet existant.

Travail demandé : retrouver précisément les opérations historiques, ajouter des
préflights, backups/rollback et confirmations, puis tester sur une machine avec
paquet UWP Roblox. Ne simule pas une validation réelle si aucun paquet n'existe.

### Nº 37 — Région serveur

Historique : région/ping dans ServerList.

État Astro : transport borné, cache, modèles, service, bridge et Settings sont
raccordés. La preuve réelle manque parce que la liste publique ne fournit
généralement pas d’adresse machine.

Travail demandé : obtenir une adresse machine réelle, vérifier la résolution et
le rendu sans exposer l’adresse, puis ajuster le fournisseur si nécessaire.

### Nº 62 — `RAMAccount.lua` en jeu

État : script généré avec token, reconnexion et protocole ; serveur Nexus local
testé. Le comportement dans un vrai client en jeu reste à vérifier.

Travail demandé : connecter un vrai client Nexus autorisé, tester handshake,
Ping/Log/Echo/Set*, execute, teleport, mute/unmute, déconnexion/reconnexion et
redaction. Corriger toute divergence RAM observée.

### Nº 63 — 22 routes Developer API RAM

État : les 22 routes sont présentes et exercées individuellement sur un vrai
serveur loopback authentifié. Certaines formes de réponses legacy diffèrent.

Travail demandé : pour chaque route, comparer nom, verb, query/body, lookup,
code HTTP, content-type et schéma de réponse avec RAM 3.7.2/GitBook. Conserver
REST v1 en parallèle. Étendre `tests/test_legacy_api_route_matrix.py`.

## 6. Les 26 lignes `TESTED BUT NOT VERIFIED`

Elles doivent être validées une par une, sans les oublier :

- Nº 3 : login navigateur complet/capture ;
- Nº 4 : OAuth PKCE avec vraie application Roblox Open Cloud ;
- Nº 24 : vrai serveur privé/VIP ;
- Nº 25 : Follow avec présence exposant réellement Place/Job ;
- Nº 32 : vrai paquet Roblox UWP ;
- Nº 36 : scan réel trouvant effectivement le joueur, en respectant les 429 ;
- Nº 39 : changement mot de passe avec nouvelle valeur explicite ;
- Nº 40 : changement email avec adresse explicite ;
- Nº 41 : logout des autres sessions avec consentement explicite ;
- Nº 42 : mutation de confidentialité follow ;
- Nº 43 : display name réel ;
- Nº 44 : demande d'ami réelle ;
- Nº 45 : block/unblock réel ;
- Nº 46 : vrai code Quick Login ;
- Nº 47 : vraie tenue/avatar ;
- Nº 48 : vrai PIN si l'endpoint existe encore ;
- Nº 55 : vraie fenêtre Beta Home après la grâce de 30 s ;
- Nº 59 : client Nexus en jeu et handshake ;
- Nº 60 : Ping/Log/Echo/Set* en jeu ;
- Nº 61 : execute/teleport/mute/unmute en jeu ;
- Nº 64 : authentification password depuis un vrai script RAM tiers ;
- Nº 68 : vrais déclenchements automatiques mémoire/titre/timeout ;
- Nº 70 : release GitHub valide ; le dépôt configuré répond actuellement 404 ;
- Nº 73 : parcours UI complet browser/OAuth ;
- Nº 74 : UI Nexus avec client réel ;
- Nº 77 : extension solver et vrai challenge Roblox actuel.

Pour les mutations externes, « contrôle du PC » ne fournit pas à lui seul la
nouvelle valeur ou la cible. Demande seulement l'information indispensable
(nouveau mot de passe, email, joueur, tenue, PIN, code, VIP) puis exécute le test.
Ne révoque ni ne change silencieusement un compte réel.

## 7. Architecture à respecter

Flux normal :

`frontend → bridge.js → DesktopBridge → ApplicationService → client/repository`

Rôles :

- `app/backend/models/` : dataclasses et modèles de domaine ;
- `app/backend/repositories/` : SQLite uniquement ;
- `app/backend/security/` : DPAPI, vault et redaction ;
- `app/backend/roblox/` : HTTP Roblox, lancement, auth, UWP, outils ;
- `app/backend/watchers/` : processus, logs, fenêtres ;
- `app/backend/nexus/` : serveur et protocole Nexus ;
- `app/backend/services/application_service.py` : orchestration métier ;
- `app/backend/api/bridge.py` : surface desktop ;
- `app/backend/api/loopback.py` : API locale ;
- `app/frontend/` : interface ;
- `tests/` : tests unitaires/intégration/contrat ;
- `docs/` : matrice et preuves canoniques.

Ne place pas de logique Roblox sensible uniquement dans le frontend. Ne contourne
pas `ApplicationService` avec des accès SQLite directs depuis le bridge.

## 8. Invariants de stockage et secrets

- Métadonnées : SQLite.
- Sessions, mots de passe et grants OAuth : vault DPAPI CurrentUser.
- Ne journalise jamais cookie, ticket, mot de passe, bearer ou commande complète
  d'un processus Roblox.
- L'affichage/export brut ne doit se produire qu'après l'action explicite prévue.
- Ne transfère pas les secrets dans l'export metadata public-only.
- Respecte l'ancien workspace `AsteriaAccountManager` s'il existe ; le rebrand ne
  doit jamais masquer ou dupliquer les données existantes.
- N'écrase pas `AccountData.json` historique sans backup préalable.
- La migration legacy doit rester bornée, consentie et testable.

## 9. Protocole de travail attendu

Pour chaque fonction traitée, fournis exactement :

1. **Fonctionnalité historique** ;
2. **Implémentation historique retrouvée** avec fichier/méthode ;
3. **Équivalent nouvelle architecture** ;
4. **Fichiers modifiés** ;
5. **Tests effectués**, en distinguant mocks et preuve réelle ;
6. **Statut final dans FEATURE_MATRIX.md**.

Avant toute modification :

1. lire la matrice, le ledger et les tests voisins ;
2. inspecter `git status` ou au minimum l'inventaire de l'archive ;
3. préserver les changements existants ;
4. chercher l'implémentation historique ;
5. écrire ou ajuster le test qui démontre l'écart.

Après modification :

1. exécuter les tests ciblés ;
2. exécuter la suite complète ;
3. vérifier Python et JavaScript ;
4. tester l'UI réelle si le changement est visible ;
5. reconstruire l'EXE seulement après la suite verte ;
6. faire un smoke test du nouvel EXE ;
7. recalculer taille et SHA-256 ;
8. mettre à jour matrice, ledger, QA et changelog.

## 10. Commandes de validation

Depuis la racine :

```powershell
python -m pip install -r requirements.txt
python -m pytest -q
python -m compileall -q app main.py scripts\build_windows.py
node --check app/frontend/src/app.js
node --check app/frontend/src/bridge.js
python scripts/build_windows.py --dry-run
python scripts/build_windows.py
Get-FileHash .\dist\AstroAccountManager.exe -Algorithm SHA256
```

Dernière base connue :

- `269 passed in 50.92s` après l’intégration du 12 août ;
- build final 20 653 079 octets ;
- SHA-256
  `961F5650F41860CBDA938D86CFFC0AEBFF78D873DA75F5779C831E95753EF91E`.

Si ton résultat de collecte diffère de 269, commence par expliquer précisément
les tests ajoutés/retirés ou l'échec avant de poursuivre.

## 11. Priorité immédiate recommandée

1. Refaire un smoke rapide Launch avec les deux comptes sans afficher leurs
   secrets et confirmer que les deux cibles restent distinctes.
2. Finaliser le login navigateur complet, car c'est le chemin d'ajout le plus
   visible encore non vérifié.
3. Aligner les dernières réponses des 22 routes API legacy.
4. Valider la région serveur avec une adresse machine réellement fournie.
5. Préparer la validation Nexus in-game.
6. Ne traiter UWP clone/CAPTCHA/mutations qu'avec l'environnement ou les valeurs
   réelles nécessaires.

## 12. Critère de fin

Ne déclare pas le projet terminé tant qu'il reste une ligne `PARTIAL` portable.
La fin acceptable est atteinte seulement lorsque :

- chaque comportement portable est réellement implémenté ;
- chaque bouton visible mène à une méthode bridge réelle ;
- chaque méthode bridge possède service, validation et tests ;
- les tests complets sont verts ;
- les preuves réelles sont consignées sans secrets ;
- la matrice reflète exactement les faits ;
- le build courant correspond au code courant et son hash est documenté.

Commence par lire les documents canoniques, reproduis l'état de validation, puis
attaque immédiatement les cinq lignes `PARTIAL` sans réduire le périmètre.
