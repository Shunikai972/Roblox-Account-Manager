# Inventaire Exhaustif des Fonctionnalités — Roblox Account Manager (RAM 3.7.2)

Ce document recense **l'intégralité** des fonctionnalités de l'application originale **Roblox Account Manager (RAM 3.7.2)** par ic3w0lf22, issues de l'analyse du dépôt GitHub original (`ic3w0lf22/Roblox-Account-Manager`) et de la documentation Developer API officielle.

---

## 1. 🔐 Authentification & Gestion des Comptes

- **Stockage d'Identifiants Multi-Champs** :
  - Nom d'utilisateur (`Username`) et Identifiant numérique Roblox (`UserId`).
  - Mémorisation optionnelle du mot de passe (`SavePasswords`).
  - Cookie de session Roblox (`.ROBLOSECURITY`).
  - Statut de validité de la session, date de dernière utilisation (`LastUsed`) et dernier rafraîchissement.
- **Méthodes d'Importation** :
  - Importation par cookie brut (`.ROBLOSECURITY`).
  - Importation multi-formats en masse : `User:Pass`, `User:Pass:Cookie`, `Cookie`.
  - Connexion manuelle via navigateur embarqué (CefSharp / Puppeteer / WebBrowser) avec capture automatique du cookie de session.
- **Sécurité et Chiffrement du Magasin de Données (`AccountData.json`)** :
  - Chiffrement natif Windows DPAPI (`CryptProtectData` avec entropie spécifique).
  - Chiffrement symétrique Sodium (Argon2 + SecretBox avec mot de passe maître).
  - Option de stockage non chiffré (`NoEncryption.IUnderstandTheRisks.iautamor`).
- **Organisation & Structure des Comptes** :
  - Création et gestion de **Groupes de comptes** personnalisés.
  - Ordre et préfixes hiérarchiques (ex: `001 MonGroupe`) avec tri automatique.
  - Couleurs et icônes personnalisées par groupe.
  - Filtrage, recherche textuelle et masque de visibilité des comptes.
- **Métadonnées et Personnalisation par Compte** :
  - **Alias / Pseudonymes** : attribution d'un nom d'affichage personnalisé.
  - **Descriptions / Notes** : bloc de notes associé à chaque compte.
  - **Champs Personnalisés Clé/Valeur** (`Custom Fields`) : ajout/suppression de métadonnées arbitraires par compte.
- **Présence & Profil Roblox en Temps Réel** :
  - Consultation du statut de présence (Hors ligne, En ligne, En jeu, Studio).
  - Récupération de l'avatar et du nom d'affichage officiel (`DisplayName`).
  - Mise à jour automatique de la présence (`ShowPresence`, `PresenceUpdateRate`).
  - Rafraîchissement automatique des cookies de session (`AutoCookieRefresh`).
- **Opérations sur le Compte Roblox (via API Roblox)** :
  - Modification du mot de passe (`change_password`).
  - Modification de l'adresse email associée (`change_email`).
  - Déconnexion de toutes les sessions actives (`logout_all_sessions`).
  - Changement du nom d'affichage Roblox (`set_display_name`).
  - Changement des assets de l'avatar (`set_avatar` / Wearing Assets).
  - Connexion rapide via code à 6 caractères (`Quick Log In`).
  - Envoi d'invitations d'amis (`send_friend_request`).
  - Gestion des utilisateurs bloqués : Blocage (`BlockUser`), Déblocage (`UnblockUser`), Déblocage de tous (`UnblockEveryone`), Liste des bloqués (`GetBlockedList`).

---

## 2. 🚀 Lancement de Jeu & Gestion des Serveurs

- **Protocole de Lancement Roblox** :
  - Lancement des sessions via protocole d'URI Windows (`roblox-player://` ou `roblox://`).
  - Transmission des jetons d'authentification (`AuthTicket`) sécurisés.
- **Lancement Groupé / En Lot (`Batch Launch`)** :
  - Sélection multiple de comptes pour lancement simultané/séquentiel.
  - Délai configurable entre les lancements (`AccountJoinDelayMS`).
- **Explorateur & Liste de Serveurs Publics** :
  - Recherche par **Place ID** d'expérience Roblox.
  - Affichage de la liste des serveurs avec : nombre de joueurs, capacité max, Ping (ms), Job ID.
  - Géolocalisation des serveurs via l'API IP (`IPApiLink` / `ip-api.com`) avec formatage de la région (`ServerRegionFormat`).
  - Tri et sélection automatique du serveur avec le moins de joueurs ou le meilleur ping (`ShuffleChoosesLowestServer`, `ShufflePageCount`).
- **Serveurs Privés & Liens VIP** :
  - Analyse et gestion des liens de serveurs privés (VIP Links).
  - Extraction et stockage des codes de serveur privé (`privateServerLinkCode`).
- **Suivi de Joueur / Rejoindre un Ami (`FollowUser`)** :
  - Recherche d'un joueur par nom d'utilisateur.
  - Récupération de sa présence actuelle (Place ID et Job ID).
  - Lancement automatique d'un compte sur le même serveur que le joueur ciblé.
- **Historique & Favoris** :
  - Sauvegarde des jeux récents (`RecentGames.json`) avec limite configurable (`MaxRecentGames`).
  - Marquage de jeux favoris.
  - Mémorisation du dernier Place ID rejoint (`SavedPlaceId`).

---

## 3. ⚙️ Optimisation du Client Roblox & Gestion des Processus

- **Plafond FPS (`UnlockFPS` / `MaxFPSValue`)** :
  - Débridage et configuration de la limite de FPS du client Roblox via la modification du fichier `ClientAppSettings.json` (`DFIntTaskSchedulerTargetFps`).
- **Gestion Multi-Instance (Bypass Mutex)** :
  - Suppression/fermeture du mutex Windows `ROBLOX_singletonEvent` (`EnableMultiRBX`).
  - Autorise l'exécution simultanée de plusieurs clients Roblox indépendants sur la même machine.
- **Surveillant de Processus (`RobloxWatcher`)** :
  - Monitoring en temps réel des processus Windows Roblox (`RobloxPlayerBeta.exe`).
  - Vérification de l'état du DataModel (`VerifyDataModel`).
  - Détection des déconnexions et plantages (`NoConnectionTimeout`, `ScanInterval`).
  - Redémarrage automatique des comptes déconnectés / plantés.
- **Gestion et Nettoyage Automatique** :
  - Fermeture automatique du dernier processus Roblox actif lors du lancement d'un nouveau compte (`AutoCloseLastProcess`).
  - Nettoyage automatique de la fenêtre d'accueil Roblox Beta (`BetaHomeCleaner`).
  - Sauvegarde et restauration du positionnement/redimensionnement des fenêtres Roblox (`SaveWindowPositions`).

---

## 4. 🌐 Developer API Officielle (Serveur HTTP Local - Port 7963)

Serveur HTTP local embarqué (`Classes/WebServer.cs`) exposant une API REST/Query pour le contrôle à distance de RAM :

| Endpoint API | Description & Action |
|---|---|
| `GET /LaunchAccount` | Lance un compte spécifié vers un Place ID et Job ID optionnel. |
| `GET /FollowUser` | Recherche un joueur et lance le compte sur son serveur. |
| `GET /SetServer` | Définit le Place ID et Job ID cible pour un compte. |
| `GET /SetRecommendedServer` | Attribue un serveur recommandé optimisé. |
| `GET /BlockUser` | Bloque un utilisateur Roblox spécifié. |
| `GET /UnblockUser` | Débloque un utilisateur Roblox spécifié. |
| `GET /UnblockEveryone` | Débloque la totalité des utilisateurs bloqués. |
| `GET /GetBlockedList` | Renvoie la liste JSON des utilisateurs bloqués. |
| `GET /GetField` | Récupère la valeur d'un champ personnalisé. |
| `GET /SetField` | Définit un champ personnalisé pour un compte. |
| `GET /RemoveField` | Supprime un champ personnalisé. |
| `GET /SetAlias` | Modifie le pseudonyme/alias d'un compte. |
| `GET /GetAlias` | Renvoie le pseudonyme/alias d'un compte. |
| `GET /SetDescription` | Remplace la description d'un compte. |
| `GET /GetDescription` | Renvoie la description d'un compte. |
| `GET /AppendDescription` | Concatène du texte à la description existante. |
| `GET /SetAvatar` | Modifie la tenue/avatar du compte Roblox. |
| `GET /GetCookie` | Récupère le cookie `.ROBLOSECURITY` d'un compte. |
| `GET /GetAccounts` | Liste les noms d'utilisateurs enregistrés. |
| `GET /GetAccountsJson` | Renvoie la liste complète des comptes au format JSON. |
| `GET /GetCSRFToken` | Génère un jeton CSRF / AuthTicket Roblox validé. |
| `GET /ImportCookie` | Importe un nouveau cookie de session à distance. |

**Paramètres de sécurité du Serveur Web** (`RAMSettings.ini`) :
- `AllowGetCookie`, `AllowGetAccounts`, `AllowLaunchAccount`, `AllowAccountEditing`, `EveryRequestRequiresPassword`, `AllowExternalConnections`.

---

## 5. ⚡ Nexus Account Control (Serveur WebSocket Local - Port 5242)

Serveur WebSocket bidirectionnel (`NexusServer`) assurant le contrôle temps réel des clients Roblox via le script client `RAMAccount.lua` / `Nexus.lua` :

- **Connexion WebSocket Client-Manager** : écoute sur `ws://127.0.0.1:5242/Nexus`.
- **Relais de Commandes Lua** :
  - `execute` : envoi et exécution de scripts Lua arbitraires sur un ou plusieurs clients.
  - `ping` / `heartbeat` : maintien de connexion et transmission du Job ID / Place ID actif.
  - `setplaceid`, `setjobid` : mise à jour de la destination.
  - `setautorelaunch` : activation du maintien en jeu automatique.
- **Console de Log Temps Réel** : réception et affichage des messages `print()` et journaux des scripts Roblox.
- **Relancement Automatique en Jeu** : détection de déconnexion côté client et relancement automatique.

---

## 6. 🎨 Thèmes, UI & Configuration

- **Gestionnaire de Thèmes Complètement Personnalisable (`RAMTheme.ini`)** :
  - Couleurs de fond et de texte (`AccountsBG`, `AccountsFG`, `FormsBG`, `FormsFG`).
  - Style et couleurs des boutons (`ButtonsBG`, `ButtonsFG`, `ButtonsBC`, `ButtonStyle`).
  - Style des zones de saisie et d'en-tête (`TextBoxesBG`, `TextBoxesFG`, `DarkTopBar`, `ShowHeaders`).
- **Sauvegarde et Restauration Automatique** :
  - Génération automatique de copies de secours (`AccountData.json.backup`).
  - Restauration en 1 clic en cas de fichier corrompu.
- **Mises à Jour Logiciel** :
  - Vérification automatique des nouvelles versions de RAM (`CheckForUpdates`).
