# Sécurité

## Stockage des secrets

- Les sessions sont protégées par Windows DPAPI en scope **CurrentUser**.
- SQLite ne contient que des métadonnées de compte et un indicateur de session.
- Les mots de passe ne sont pas importés ou enregistrés par défaut.
- Les grants OAuth Roblox (access token, refresh token éventuel et ID token) sont stockés ensemble dans un blob DPAPI `CurrentUser` distinct ; ils ne sont ni une session du client Roblox ni des données de profil publiques.
- Les exports, logs et diagnostics appliquent une redaction automatique aux cookies, tickets, mots de passe et tokens.
- Le transfert portable Astro est strictement limité aux groupes, comptes et jeux publics : ni vault, ni session, ni cookie, ni token, ni mot de passe ne peuvent être exportés ou importés. Les exports Asteria existants restent lisibles pour la migration de nom.

## Migration legacy

Le fichier `AccountData.json` historique n'est jamais modifié. L'assistant crée une sauvegarde horodatée avant lecture et n'importe une session qu'après consentement explicite. Les données illisibles ou chiffrées sous un autre utilisateur Windows sont signalées, jamais contournées.

## Réseau et API

- Le bridge pywebview est le canal principal entre UI et backend.
- L'API HTTP locale est désactivée par défaut, limitée à `127.0.0.1` et n'expose aucune session brute.
- Les opérations de compte à effet de bord nécessitent une confirmation UI et des réponses Roblox valides.
- Les secrets n'apparaissent ni dans les URLs, ni dans les journaux, ni dans une commande shell.
- Le callback OAuth ne peut écouter que sur `127.0.0.1`; le navigateur système reçoit un flux PKCE et le bridge ne retourne jamais l'URL d'autorisation, le code, le verifier ou les tokens.

## Processus et instances

Le monitor ne suit que les processus Roblox connus. Toute terminaison est opt-in, vérifie l'identité PID/date de démarrage et est journalisée. L'application ne patche aucun binaire Roblox, n'injecte pas de code, ne contourne pas de CAPTCHA et ne relaye pas de scripts distants.

## Signalement

N'ajoutez jamais une session ou un mot de passe dans un ticket, un log partagé ou un rapport de bug. Utilisez l'export de diagnostic redacted.
