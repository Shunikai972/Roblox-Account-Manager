# Développement

## Conventions

- Python 3.12+, type hints, dataclasses et fonctions petites/testables.
- Les erreurs traversent le bridge sous forme d'objets `AppError` stables.
- Tout accès réseau a un timeout et une erreur utilisateur compréhensible.
- Toute mutation de données est transactionnelle et journalisée.
- Les secrets ne sont jamais ajoutés à un modèle public, un log ou un export de diagnostic.

## Frontend

Le frontend est statique afin que `python main.py` ne dépende pas d'un serveur Node. Il emploie des modules ES, des tokens CSS et un adaptateur `bridge.js` qui fournit un mode aperçu dans un navigateur standard.

## Validation locale

```powershell
python -m compileall -q app
python -m pytest
```

Avant une livraison Windows, exécutez aussi le build et le smoke test documentés dans [INSTALLATION.md](INSTALLATION.md).

