# Installation

## Prérequis développement

- Windows 10/11 64 bits.
- Python 3.12 ou plus récent.
- Roblox installé pour les fonctions de lancement et de monitoring.

```powershell
python -m pip install -r requirements.txt
python main.py
```

pywebview utilise le runtime WebView2/Edge disponible sur les versions Windows maintenues. Si l'interface ne s'ouvre pas, installez le runtime WebView2 Evergreen puis relancez l'application.

## Répertoire de données

Les données de la nouvelle application sont séparées de la distribution legacy :

```text
%LOCALAPPDATA%\AstroAccountManager\
  astro.db
  backups\
  logs\
  cache\
  exports\
```

Une installation Asteria existante n’est pas déplacée automatiquement : Astro Account Manager continue d’utiliser `%LOCALAPPDATA%\AsteriaAccountManager\asteria.db` tant que cet espace de travail existe, afin de ne pas dupliquer ni masquer les données locales.

Ne déplacez pas les fichiers legacy dans ce dossier manuellement. Utilisez l'assistant de migration pour obtenir une copie datée et un rapport.

## Build Windows

```powershell
python -m pip install ".[dev]"
python scripts\build_windows.py
```

Le script produit un exécutable autonome dans `dist\`. Consultez le journal de build et lancez le smoke test généré avant toute distribution.
