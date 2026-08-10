# Changelog

Ce projet suit le versionnage sémantique. La version `4.0.0a1` est une préversion de migration, destinée à la validation fonctionnelle et de sécurité avant une première version stable.

## [4.0.0a1] — 2026-08-10

### Ajouté

- Nouvelle application desktop locale Python + pywebview et interface HTML/CSS/JavaScript modulaire.
- Stockage SQLite transactionnel pour les métadonnées de comptes, groupes, jeux, activité, notifications et réglages.
- Vault de secrets Windows DPAPI ; les modèles publics, exports de diagnostic et journaux sont expurgés des sessions.
- Gestion des comptes et groupes, recherche, sélections groupées, activité et notifications depuis le bridge desktop.
- Consultation de jeux et de serveurs publics Roblox avec délais réseau bornés et retours d’erreurs lisibles.
- Lancement local de destinations Roblox validées par le protocole Windows officiel, sans lien portable contenant de session.
- Monitoring opt-in des processus Roblox avec informations PID, durée et consommation mémoire ; terminaison seulement après confirmation explicite.
- Backups SQLite versionnés et vérifiés, ainsi qu’un import legacy non destructif qui crée d’abord une copie datée.
- Export/import Astro de métadonnées publiques versionnées et checksummées, avec confirmation, limite de taille et backup de sûreté avant import ; aucune session ou donnée de vault n'est transférée.
- Documentation d’architecture, sécurité, migration, configuration, dépannage et contrat de bridge.
- Script de packaging Windows PyInstaller avec assets frontend et icônes embarqués, contrôle `--dry-run` et build réel vérifié.

### Migration et compatibilité

- La distribution historique 3.7.2 a été analysée à partir du tag source correspondant et du binaire fourni ; les fichiers d’origine ne sont jamais modifiés par le nouvel outil.
- L’import de métadonnées est séparé des secrets. L’import de sessions doit être explicitement confirmé et reste local à l’utilisateur Windows qui l’effectue.
- Les fonctions historiques de copie de cookie, export de lien `rbx-player` avec session, exécution distante Nexus et patch/bypass de client ne sont pas reprises. Elles sont remplacées ou laissées hors périmètre conformément à la matrice de fonctionnalités.

### Sécurité

- Les secrets ne sont ni retournés au frontend, ni écrits dans les logs, ni inclus dans les diagnostics.
- Les URLs et destinations de lancement sont validées ; les appels HTTP ont des délais explicites.
- Le nouveau stockage évite les effets de bord directs et les sauvegardes silencieuses de la base legacy.

### À valider avant une version stable

- Tests manuels WebView2 sur Windows 10 et Windows 11.
- Vérification de la migration sur des copies de jeux de données représentatifs, y compris les cas chiffrés autorisés.
- Signature Authenticode, scan de l’artefact et revue de licence de toute distribution publique.
- Complément intégral des 22 routes de la Developer API officielle RAM GitBook (LaunchAccount, FollowUser, SetServer, SetRecommendedServer, BlockUser, UnblockUser, UnblockEveryone, GetBlockedList, GetField, SetField, RemoveField, SetAlias, GetAlias, SetDescription, GetDescription, AppendDescription, SetAvatar, GetCookie, GetAccounts, GetAccountsJson, GetCSRFToken, ImportCookie).
- Intégration du serveur WebSocket Nexus (port 5242) avec relai Lua et auto-relaunch.
- Intégration de la gestion Multi-Instance Mutex Win32 et du nettoyeur Beta Home.
