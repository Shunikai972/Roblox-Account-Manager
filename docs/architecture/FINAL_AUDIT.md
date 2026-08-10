# Audit final — Asteria Account Manager 4.0.0a1

> Audit réalisé le 10 août 2026 sur le contenu réellement présent dans `app/`, `tests/`, `scripts/` et la documentation associée. Référence historique analysée : Roblox Account Manager 3.7.2 (tag `3.7.2`, commit `79f61f3351df61fb3774dfa854ab868954da5389`).

## Verdict

La réécriture fournit un **socle desktop local fonctionnel et testé** pour organiser des profils, groupes et destinations Roblox, consulter des données publiques de jeux/serveurs, lancer une destination validée, surveiller les processus locaux, sauvegarder/restaurer les données et migrer ou transférer des métadonnées sans modifier la source.

Elle ne constitue pas encore une parité totale avec l'application WinForms 3.7.2 ni un artefact de production prêt à distribuer. Les parcours qui exigent une authentification Roblox complète, le contrôle d'instances avancé, l'UWP, les outils de compte et le smoke test graphique Windows restent explicitement à finaliser. Cette distinction est importante : un élément n'est considéré « porté et testé » dans [FEATURE_MATRIX.md](FEATURE_MATRIX.md) que lorsqu'un code correspondant et au moins un test automatisé sont présents.

## Fonctionnalités portées

| Domaine | État audité | Éléments vérifiés |
| --- | --- | --- |
| Architecture desktop | Porté | `main.py` crée une fenêtre pywebview locale avec `app/frontend/`; le frontend ne communique avec Python qu'au travers du bridge. |
| Comptes et groupes | Porté partiellement | CRUD de métadonnées, recherche, favoris, notes, groupes, déplacement groupé, activité et notifications sont servis par `ApplicationService`/SQLite. Les écrans frontend existent ; leur validation est encore manuelle. |
| Stockage | Porté et testé | SQLite versionnée, WAL, transactions, contraintes de groupe, tables de paramètres/activité/notifications et filtrage des champs sensibles. |
| Vault | Porté et testé | DPAPI Windows `CurrentUser` isole les secrets de la base de métadonnées ; les modèles et payloads publics n'exposent qu'un marqueur `has_session`. |
| Backups et restauration | Porté et testé | Snapshots SQLite cohérents, manifestes versionnés SHA-256, vérification, confirmation UI/bridge, backup pré-restauration, checkpoint/fermeture et réouverture de la base après remplacement atomique. |
| Migration legacy | Porté partiellement | Détection JSON/DPAPI/mot de passe historique, copie préalable, import de réglages/jeux/métadonnées et consentement distinct pour les secrets. L'import est limité au contexte DPAPI de l'utilisateur courant. |
| Transfert de métadonnées | Porté et testé | Export/import JSON public versionné et checksummé ; écriture atomique, limite de 8 Mio, import transactionnel sans dépendance au vault et backup de sûreté avant ajout. |
| Jeux et serveurs | Porté partiellement | Client Roblox public isolé : détails de jeu, recherche côté client, serveurs publics, validation d'identifiants, timeout et retry borné. Les filtres/pagination UX et la recherche de joueur ne sont pas encore portés. |
| Lancement | Porté partiellement | Lancement `roblox://experiences/start` validé pour `placeId` et `jobId`, sans ticket ni cookie dans l'URI. Le protocole ne réalise pas encore une authentification par profil. |
| Instances | Porté partiellement | Monitor `psutil` local : PID, durée, mémoire, états et historique borné. La terminaison est désactivée par défaut ; si elle est activée, elle exige une confirmation et vérifie l'identité du processus. |
| Paramètres et diagnostics | Porté partiellement | Préférences catégorisées/persistées, logs rotatifs redacted, diagnostics, activité, notifications et interface de réglages sont présents. Certaines préférences ne pilotent pas encore tous les comportements runtime. |
| API locale | Porté et testé | API HTTP v1 optionnelle, exclusivement `127.0.0.1`, Bearer token en mémoire obligatoire, réponses `no-store`, erreurs normalisées et OpenAPI dans `docs/api/openapi.yaml`. |
| Packaging | Build produit, validation manuelle restante | PyInstaller a produit `dist/AsteriaAccountManager.exe` avec frontend, transfert de métadonnées et icônes ; taille 19 976 186 octets, SHA-256 `DAB4C2A2AA152076B285A3264291A11B87243EB356EF5A0A9D5DAC42B86400E1`. L'archive a été inspectée ; un smoke test sur machine propre et une signature restent requis. |

## Améliorations et fonctions nouvelles

- Séparation nette entre UI, bridge, services, repositories, sécurité, client Roblox et monitor, contrairement aux formulaires WinForms historiques très couplés.
- Persistance transactionnelle et versionnée avec journal de migrations, plutôt qu'un fichier de comptes mutable sans version de schéma.
- Centre de notifications, activité persistée, diagnostics redacted, palette de commandes, recherche et vues responsives dans le frontend local.
- Import legacy non destructif : le dossier sélectionné n'est ni déplacé ni réécrit ; un backup horodaté est créé avant le parsing d'`AccountData.json`.
- Transfert public Asteria à Asteria : les groupes, comptes et jeux peuvent être échangés dans un JSON versionné et checksummé, sans session, vault, cookie, token, mot de passe, marqueur de session ou identifiant de navigateur.
- API locale explicitement activée, limitée au loopback et documentée. Elle expose seulement des métadonnées et actions autorisées ; elle refuse récursivement les clés de type session, cookie, mot de passe, token ou secret.
- Lancement local reposant sur le protocole Roblox enregistré par Windows, sans export de capacité d'authentification transportable.
- Icônes `asteria.ico`, PNG et SVG dédiées pour la fenêtre Windows, l'UI et l'archive PyInstaller.

## Défauts historiques ou de reconstruction corrigés

- Le stockage de secrets ne partage plus la même charge JSON que les métadonnées. Le nouveau vault utilise DPAPI `CurrentUser`, ce qui supprime le choix historique incohérent entre `CurrentUser` à la lecture et `LocalMachine` à l'écriture.
- Les sessions, cookies, mots de passe et tokens sont retirés des modèles publics, des réglages ordinaires, des diagnostics et des logs par filtres de redaction testés.
- Les snapshots SQLite ferment explicitement leurs connexions avant le remplacement atomique, évitant le verrou de fichier Windows rencontré lors du backup.
- La restauration ne laisse plus une connexion SQLite en mémoire sur un fichier remplacé : elle impose une confirmation, crée une copie pré-restauration, checkpoint/ferme les sidecars WAL, restaure puis rouvre le repository.
- L'ancien export implicite de données est remplacé par un format JSON public explicitement allowlisté : checksum, limite de taille, profondeur/collections bornées et rejet d'un document sensible avant toute écriture.
- Les erreurs réseau et bridge sont normalisées, ne reflètent pas les réponses distantes sensibles et disposent de délais/retry limités.
- Le monitor ne lit ni mémoire Roblox, ni lignes de commande, ni binaires ; il ne force jamais un `kill` après timeout et protège contre le recyclage de PID.
- Les surfaces historiques de copie de cookie, ticket copiable, lien `rbx-player`, injection Nexus et patch/bypass client ne sont pas reproduites. Elles sont supprimées ou remplacées par un flux local sûr.

## Validation exécutée

Les commandes suivantes ont été exécutées depuis la racine du projet pendant cet audit :

```powershell
python -m pytest -q
python -m compileall -q app main.py scripts\build_windows.py
node --check app/frontend/src/app.js
node --check app/frontend/src/bridge.js
python scripts\build_windows.py --dry-run
python scripts\build_windows.py
```

Résultats :

- **52 tests passés** : stockage/transactions, redaction, DPAPI disponible ou dégradé de manière sûre, vault, backups/restauration, migration legacy, client Roblox, lancement, monitor, service d'application, API loopback et transfert de métadonnées.
- Compilation Python et analyse syntaxique des deux modules JavaScript sans erreur.
- Le dry-run PyInstaller valide l'entrée `main.py`, les assets `app/frontend`, les répertoires de sortie bornés et l'artefact attendu `dist\AsteriaAccountManager.exe`.
- Le build Windows final a réussi. L'archive contrôlée contient `app/frontend/index.html`, les trois modules frontend et les icônes Asteria ; `dist\AsteriaAccountManager.exe` mesure **19 976 186 octets** avec le SHA-256 `DAB4C2A2AA152076B285A3264291A11B87243EB356EF5A0A9D5DAC42B86400E1`.

Les validations non effectuées sont volontairement signalées : aucune signature Authenticode, aucun smoke test WebView2 sur Windows 10/11 propre, aucun lancement avec un vrai compte/session ni migration d'un jeu de données utilisateur réel n'ont été exécutés dans cet audit.

## Sécurité et confidentialité

- Les secrets ne sont jamais retournés au frontend, au bridge HTTP, aux diagnostics ou aux journaux. Le vault stocke uniquement des blobs DPAPI protégés.
- Le transfert JSON portable est classé `public_metadata_only` : l'export omet les entrées vault, `has_session` et le tracker navigateur ; l'import force les comptes à `has_session=False` et rejette tout champ ressemblant à un identifiant sensible.
- L'import legacy ignore les sessions et mots de passe par défaut. L'import d'une session requiert une demande explicite et une confirmation distincte ; un mot de passe legacy chiffré n'est tenté que lorsqu'il est fourni localement.
- L'API HTTP est arrêtée par défaut. Quand elle est activée, elle requiert `ASTERIA_LOCAL_API_TOKEN`, n'écoute que sur `127.0.0.1`, applique une comparaison en temps constant, limite les corps JSON à 64 Kio et désactive le cache.
- Les destinations de lancement acceptent uniquement un `placeId` positif et un `jobId` strictement validé ; aucune session n'est injectée dans une URL.
- Les opérations de restauration demandent l'autorisation d'écraser une destination existante. Le monitor de processus exige une confirmation au moment de la terminaison et n'escalade jamais en fermeture forcée.

## Résilience et performance

- SQLite est utilisé en WAL avec transactions et verrous internes ; les backups utilisent l'API SQLite plutôt qu'une copie brute pendant que la base est ouverte.
- Les exports de métadonnées sont écrits atomiquement et limités à 8 Mio ; les documents importés sont checksummés, canoniques, bornés en profondeur et en nombre d'entités avant l'ouverture d'une transaction.
- Les clients HTTP Roblox ont des timeout, une pagination bornée et des retry limités ; une erreur publique peut retomber sur un cache local sans masquer une absence de données.
- Le monitor borne l'historique et le nombre de processus suivis afin qu'un état anormal ne fasse pas croître la mémoire sans limite.
- Les handlers de l'API loopback limitent la taille des corps, cachent les détails d'exception et s'arrêtent proprement à la fermeture de la fenêtre.

## Limites connues et travail restant

1. Le lancement identifie aujourd'hui le profil dans les métadonnées, mais Windows ouvre le client Roblox enregistré sans authentifier automatiquement ce profil avec sa session stockée. Il ne faut donc pas le présenter comme un gestionnaire de login multi-compte complet.
2. Aucun navigateur d'authentification isolé, rafraîchissement de session, import bulk `user:pass`, présence, recherche de joueur, utilitaires de compte authentifiés, avatar/tenue ou changement de paramètres de compte n'est livré.
3. Les fonctions de queue de lancement, prévention réelle de doublons par compte, lecture de logs Roblox, règles de fermeture automatique, disposition de fenêtres, auto-relaunch et UWP restent partielles ou absentes.
4. L'interface est implémentée et syntaxiquement vérifiée, mais nécessite un test manuel pywebview/WebView2 : focus clavier, redimensionnement, thème, persistance, erreurs réseau et interactions sur une installation propre.
5. La route HTTP de lancement et certaines mutations de groupe existent mais doivent recevoir davantage de tests d'intégration de route. L'API protège toutes les routes par jeton, mais ne met pas encore en œuvre le rate limit/capability granulaire prévu pour les actions mutantes.
6. Le build réel final est disponible, mais le scan de l'artefact, la revue GPL/distribution, la signature Authenticode et un smoke test sur machine propre restent des gates obligatoires avant publication externe.

## Décision de livraison

**Acceptable comme préversion locale 4.0.0a1 destinée aux tests fonctionnels et de migration sur copies de données.**

**Non acceptable comme remplacement complet ou release publique finale** avant les smoke tests Windows, la signature et le scan de l'artefact, la validation sur données legacy représentatives et la réduction des écarts indiqués dans la matrice.
