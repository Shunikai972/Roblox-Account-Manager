# Changelog

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

- **269 tests passés**, compilation Python et syntaxe JavaScript valides ;
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

- taille : 20 666 396 octets ;
- SHA-256 :
  `B5F7FC368A79B5F4B157DEB6D7416E828421E98FDA602526FA3E78517D792868`.

### Travail restant explicite

- cinq lignes `PARTIAL` : import username/password, clones UWP, région serveur,
  validation in-game de `RAMAccount.lua` et réponses API legacy ;
- validations réelles encore dépendantes d'une donnée ou cible externe : login
  navigateur complet, OAuth, VIP, certaines opérations utilitaires mutantes,
  client Nexus en jeu, paquet UWP et extension CAPTCHA.

Voir la [validation individuelle des 42 lignes](../QA_MATRIX_2026-08-11.md).
