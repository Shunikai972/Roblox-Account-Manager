# Checklist de livraison — 4.0.0a1

Cette checklist concerne une livraison Windows de la préversion `4.0.0a1`. Ne distribuez pas l’artefact si une étape de blocage échoue.

## 1. Préparer un checkout propre

- [ ] Confirmer la version `4.0.0a1` dans `pyproject.toml` et `CHANGELOG.md`.
- [ ] Vérifier que les fichiers legacy sont hors des sorties `build/` et `dist/` et n’ont pas été modifiés.
- [ ] Installer les dépendances de développement : `python -m pip install ".[dev]"`.
- [ ] Utiliser Windows 10/11 64 bits, Python 3.12+ et le runtime WebView2 Evergreen.

## 2. Contrôles automatiques

Depuis la racine du projet, exécuter :

```powershell
python -m compileall -q app main.py
python -m pytest
python scripts\build_windows.py --dry-run
python scripts\build_windows.py
```

- [ ] Les deux premières commandes se terminent sans erreur.
- [ ] Le dry-run affiche `app/frontend` dans les assets et l’artefact attendu dans `dist\AstroAccountManager.exe`.
- [ ] Le build se termine sans erreur et l’exécutable attendu existe.
- [ ] Le hash SHA-256 de l’exécutable est calculé et archivé avec la livraison :

```powershell
Get-FileHash .\dist\AstroAccountManager.exe -Algorithm SHA256
```

## 3. Smoke test manuel sur une machine Windows propre

- [ ] Lancer `dist\AstroAccountManager.exe` depuis une session Windows standard.
- [ ] Vérifier que la fenêtre Astro Account Manager s’ouvre sans serveur Node ni console parasite dans un build normal.
- [ ] Ouvrir toutes les vues principales, changer thème et taille de fenêtre, puis fermer et relancer l’application.
- [ ] Ajouter, modifier, grouper, rechercher et supprimer des comptes de test sans exposer de session dans l’interface.
- [ ] Demander un backup, relancer, puis vérifier que les données locales et la liste de backups sont cohérentes.
- [ ] Vérifier les jeux/serveurs avec réseau disponible et le message d’erreur hors ligne sans blocage de l’interface.
- [ ] Vérifier le monitor avec un processus Roblox de test ; ne demander une terminaison qu’après confirmation explicite.

## 4. Contrôles de migration et de secrets

- [ ] Utiliser uniquement une **copie** d’un dossier 3.7.2 de test.
- [ ] Confirmer que l’assistant crée une sauvegarde datée avant tout import et ne change aucun fichier source.
- [ ] Tester un import de métadonnées sans sessions, puis vérifier que le rapport indique clairement ce qui a été ignoré.
- [ ] Si l’import de session est autorisé pour le test, vérifier qu’elle n’apparaît jamais dans les logs, diagnostics, exports ou captures d’écran.
- [ ] Vérifier que le dossier `%LOCALAPPDATA%\AstroAccountManager\logs\` ne contient ni cookie, ni mot de passe, ni jeton de session. Une installation migrée peut conserver son ancien dossier local.

## 5. Préparer la distribution

- [ ] Relire [SECURITY.md](SECURITY.md), [MIGRATION.md](MIGRATION.md) et [FEATURE_MATRIX.md](FEATURE_MATRIX.md) avec le périmètre réellement livré.
- [ ] Inclure `README.md`, `CHANGELOG.md`, `INSTALLATION.md`, `MIGRATION.md`, `SECURITY.md` et cette checklist avec l’artefact.
- [ ] Signer l’exécutable avec un certificat Authenticode de publication valide, si une diffusion externe est prévue.
- [ ] Soumettre l’artefact final au scan antimalware organisationnel et vérifier le hash publié après signature.
- [ ] Ne pas publier de base SQLite, backup, journal ou fichier legacy contenant des données utilisateur.

## Critères de blocage

La livraison est bloquée si le build ne contient pas `app/frontend`, si le smoke test échoue, si la migration modifie sa source, si un secret est visible dans une sortie, ou si les tests automatiques échouent.
