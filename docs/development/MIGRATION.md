# Migration depuis Roblox Account Manager 3.7.2

## Avant de commencer

1. Fermez la distribution legacy.
2. Conservez son dossier complet, en particulier `AccountData.json` et `RAMSettings.ini`.
3. Lancez Astro Account Manager sous le même utilisateur Windows si le fichier de comptes est chiffré DPAPI.

## Étapes

1. Ouvrez **Settings → Advanced → Legacy migration**.
2. Sélectionnez le dossier contenant l'ancienne installation.
3. L'assistant détecte le format, crée une copie horodatée dans les backups et valide les fichiers.
4. Consultez le rapport : comptes, groupes, champs, jeux/favoris/récents et paramètres convertis.
5. Importez les sessions uniquement si l'assistant peut les déchiffrer localement et que vous le confirmez.

## Formats pris en charge

- JSON historique en clair (rare, et explicitement signalé comme non sûr).
- DPAPI Windows legacy, sous le même profil Windows et avec les variantes d'entropie connues.
- Format à mot de passe legacy : en-tête RAM, Argon2, SecretBox (mot de passe demandé uniquement pendant l'opération).
- Paramètres `RAMSettings.ini`, thème `RAMTheme.ini`, jeux récents/favoris et contrôles locaux lorsqu'ils existent.

## Ce qui n'est pas importé automatiquement

- mots de passe enregistrés ;
- tickets d'authentification, CSRF, liens de lancement et cookies bruts exportables ;
- scripts/extensions/proxies de navigateur ;
- configurations Nexus de contrôle distant.

Ces éléments sont sensibles, périmés ou ne disposent pas d'une alternative sûre. Les données et fichiers d'origine restent disponibles dans leur dossier legacy et dans le backup de migration.

## Récupération

Si l'import échoue, ne supprimez aucun fichier. Exportez le rapport redacted, vérifiez que vous utilisez le même compte Windows, puis restaurez la copie legacy depuis les backups si besoin.
