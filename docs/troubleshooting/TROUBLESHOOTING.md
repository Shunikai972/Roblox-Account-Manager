# Dépannage

## L'application ne démarre pas

1. Vérifiez `python --version` (3.12+).
2. Réinstallez les dépendances : `python -m pip install -r requirements.txt`.
3. Installez le runtime WebView2 Evergreen si pywebview n'affiche aucune fenêtre.
4. Consultez `%LOCALAPPDATA%\AstroAccountManager\logs\astro-account-manager.log`. Une installation migrée depuis Asteria peut conserver son ancien dossier de données.

## Roblox ne se lance pas

- Vérifiez que Roblox est installé et que le protocole `roblox://` est enregistré.
- Vérifiez que le PlaceId est un entier positif et que le JobId ne contient que lettres, chiffres ou tirets.
- Un blocage par le client Roblox est affiché comme une erreur de lancement ; l'application ne modifie pas le client pour le contourner.

## La migration ne lit pas `AccountData.json`

- Assurez-vous d'être connecté au même utilisateur Windows que lors de la création du fichier DPAPI.
- Si le fichier était protégé par mot de passe, utilisez le mot de passe exact dans l'assistant.
- Ne renommez ni ne remplacez le fichier source : une copie est déjà créée avant migration.

## Aucun processus n'apparaît

- Lancez Roblox puis utilisez **Instances → Refresh**.
- Assurez-vous que le watcher est activé dans Settings.
- Les processus sans permission d'inspection sont signalés mais ne font pas planter l'application.

## Signaler un problème

Joignez un export de diagnostics redacted, la version de l'application, Windows et une description reproductible. Ne joignez jamais de session, token, mot de passe ou fichier legacy non chiffré.
