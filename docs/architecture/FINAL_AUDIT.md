# Audit d'intégration — Astro Account Manager 5.1.0

Audit actualisé le 21 août 2026 dans
`D:\Noam\Downloads\Code Account manager`, après comparaison RAM 3.7.2,
correctifs de lancement, tests automatisés, essais Windows/Roblox réels et
reconstruction de l'EXE.

## Verdict honnête

Les défauts bloquants observés pendant la conversion sont corrigés : ticket
Roblox HTTP 415, intentions de lancement enregistrées trop tard, faux états
`in_game`, cible globale appliquée au mauvais compte, association de plusieurs
logs Roblox, recherche de jeux sur un endpoint retiré et opération navigateur
restant bloquée après fermeture.

Deux comptes Roblox distincts ont été lancés simultanément avec leurs sessions
et leurs Place ID propres. Deux PID, deux identités et deux destinations ont été
confirmés par le watcher et les logs. Le multi-instance est donc réellement
validé sur cette machine, et plus seulement simulé.

Le projet ne doit toutefois pas être déclaré « terminé à 100 % ». La matrice
compte **0 fonctionnalité `PARTIAL`**, **38 `TESTED BUT NOT VERIFIED`** et
**1 `BLOCKED`** par le retrait du PIN parental côté Roblox. Les validations
externes restantes ne sont pas transformées artificiellement en parité.

## Synthèse fonctionnelle

| Domaine | Preuve actuelle | Statut |
|---|---|---|
| CRUD comptes/groupes/ordre | SQLite, service, bridge et UI testés | VERIFIED PARITY |
| Ajout par cookie | deux sessions réelles importées et revalidées, secrets DPAPI | VERIFIED PARITY |
| Ajout par navigateur | vraie fenêtre Edge isolée et cycle annulation/reprise | TESTED BUT NOT VERIFIED |
| Lancement authentifié | vrai ticket CSRF/JSON, handler `rbx-player`, deux comptes | VERIFIED PARITY |
| Place ID par compte | deux clients simultanés vers deux Place ID distincts | VERIFIED PARITY |
| Multi-instance | mutex exact, deux identités et deux PID simultanés | VERIFIED PARITY |
| Watcher processus/logs | PID+create-time, états réconciliés, deux logs associés | VERIFIED PARITY |
| Auto-relaunch | crash réel, nouveau PID et bonne cible/session | VERIFIED PARITY |
| Fenêtres Roblox | déplacement, capture et restauration réels | VERIFIED PARITY |
| Recherche jeux | endpoint Omni réel, cache borné | VERIFIED PARITY |
| API RAM | 22 routes exercées individuellement sur HTTP loopback réel | VERIFIED PARITY |
| Auth API RAM | bearer + password historique opt-in testés sur loopback | TESTED BUT NOT VERIFIED |
| Région serveur | transport/cache/UI portés sans requête terrain | TESTED BUT NOT VERIFIED |
| Nexus | serveur WebSocket/handshake/messages réels en local | TESTED BUT NOT VERIFIED |
| UWP | lecture Windows réelle, aucun paquet Roblox installé | TESTED BUT NOT VERIFIED |
| Frontend | trois résolutions, clavier, contrat bridge et actions | VERIFIED PARITY |
| Build Windows | onefile reconstruit et lancé réellement | VERIFIED PARITY |

La preuve détaillée des 42 lignes qui n'étaient pas vérifiées au début de la
passe est consignée dans [QA_MATRIX_2026-08-11.md](../QA_MATRIX_2026-08-11.md).

## Comptage canonique

| Statut | Nombre |
|---|---:|
| Total | 90 |
| VERIFIED PARITY | 51 |
| PARTIAL | 0 |
| TESTED BUT NOT VERIFIED | 38 |
| MISSING | 0 |
| BLOCKED | 1 |

## Validation exécutée

```powershell
python -m pytest -q
python -m compileall -q app main.py scripts\build_windows.py
node --check app/frontend/src/app.js
node --check app/frontend/src/bridge.js
python scripts\build_windows.py --dry-run
```

Résultats :

- **825 tests passés, 2 ignorés, 0 échec** en 105,13 s après la passe du 21 août ;
- compilation Python et syntaxe JavaScript sans erreur ;
- les 22 routes historiques testées une par une sur un serveur loopback réel ;
- 189 méthodes bridge alignées, 147 actions frontend toutes prises en charge ;
- interface inspectée à 1080×680, 1366×768 et 1500×960 ;
- deux sessions Roblox réelles revalidées sans imprimer cookie ni ticket ;
- deux vrais clients simultanés, puis fermeture séparée et réconciliation
  correcte de chaque état ;
- crash/relaunch réel : nouveau PID, compte et Place ID corrects ;
- ClientSettings réel : FPS 144 écrit, vérifié, retiré, fichier original
  restauré avec le même SHA ;
- PyInstaller onefile/windowed 5.1.0 reconstruit avec le frontend embarqué ;
  l'EXE n'a pas été lancé pendant la session Roblox active de l'utilisateur.

## Artefact 5.1.0 courant

- chemin : `dist/AstroAccountManager.exe` ;
- taille : **21 039 286 octets** ;
- SHA-256 :
  `52CA90BF1D4863EDA85B75F7F4F372A63D42C05F6111DE10767E7057379C7757` ;
- mode : PyInstaller onefile, windowed, icône Astro ;
- environnement validé : Windows 11, Python 3.12, PyInstaller 6.21.

Cet artefact correspond aux sources et à la documentation 5.1.0 du 21 août.
Son en-tête PE, son archive PyInstaller et la présence des assets frontend ont
été contrôlés statiquement. Le smoke test de remplacement/redémarrage frozen
reste distinct afin de ne pas interrompre le client Roblox déjà ouvert.

## Travail restant concret

Il ne reste aucune ligne `PARTIAL` ni `MISSING`. Les 38 lignes
`TESTED BUT NOT VERIFIED` ont une implémentation et des tests, mais demandent
encore une preuve externe adaptée : plusieurs vraies fenêtres pour Hide/Show et
distribution serveur, session longue pour calibrer la fuite mémoire, client
Discord avec assets, cycle de mise à jour Roblox, login navigateur/OAuth,
serveur VIP, client Nexus et paquet UWP réel. Les changements authentifiés de
mot de passe/email/relations sociales ne sont jamais exécutés sans valeurs
cibles et confirmation explicites. Le PIN parental est le seul `BLOCKED`, car
Roblox a supprimé cette fonctionnalité côté plateforme.

La génération automatisée de comptes, les adresses jetables et le contournement
automatique de CAPTCHA ne font pas partie de cette livraison. Les parcours
d'ajout restent le navigateur isolé manuel, le cookie explicite, l'import bulk
et OAuth pour l'identité/profil.

## État laissé sur la machine

- le 12 août, l’intégration source a été validée sans lancer ni fermer Astro ou Roblox ;
- le processus Roblox déjà ouvert par l’utilisateur est resté présent avant et après les tests ;
- les états et sessions des comptes n’ont pas été modifiés pendant cette passe ;
- les cibles sauvegardées restent respectivement `2512643572` et
  `16146832113` ;
- l'auto-relaunch global a été remis à `false`, scan à 6 s et délai à 15 s
  après le scénario de crash contrôlé.
