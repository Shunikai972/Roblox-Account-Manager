# Passation — Astro Account Manager v11

Document destiné à un autre assistant (ChatGPT) ou à un développeur qui reprend le
projet à froid. Il dit **ce qui existe**, **pourquoi c'est écrit comme ça**, et
**ce qu'il ne faut surtout pas casser**. Tout ce qui est affirmé ici est
vérifiable par une commande listée en fin de document.

---

## 1. Le projet en trois phrases

Astro Account Manager est une application de bureau Windows (Python 3.12 +
pywebview, frontend en JavaScript sans framework, base SQLite locale) qui gère
plusieurs comptes Roblox : lancement, surveillance des processus, macros par
instance, statistiques, planification, alertes. Le backend expose un service
unique (`ApplicationService`) que le frontend appelle via un pont de 176
méthodes. Il n'y a pas de serveur distant : tout est local, et les secrets ne
sortent jamais du stockage protégé de l'OS.

Version actuelle : **4.0.3, livraison v11**. Build précédent (v9) validé sous
Windows par le propriétaire : `762` tests collectés, `760` passés, `2` ignorés,
`0` échec ; exécutable PyInstaller de `20 977 306` octets, 0 erreur.

---

## 2. Ce que v11 ajoute, et pourquoi

La demande était : « liste TOUTES les fonctionnalités, vérifie qu'elles sont
présentes, implémente ce qui manque, optimise, et fais une passation ».

### 2.1 Un inventaire que le dépôt peut prouver

Une liste de fonctionnalités écrite à la main devient fausse en une semaine. J'ai
donc écrit `scripts/feature_inventory.py` : chaque fonctionnalité annoncée est
associée à un **symbole réel** (fichier + chaîne à trouver dedans). Le script
sort en erreur si une preuve disparaît, et `--markdown` régénère
`docs/user-guide/FEATURE_INVENTORY.md`.

Résultat aujourd'hui : **91 fonctionnalités prouvées, 0 manquante, 3 volontairement
absentes**. C'est l'audit qui a servi à répondre à la question « est-ce que tout
est là ? » — pas ma mémoire.

### 2.2 Les trois vrais manques trouvés par cet audit

| Manque | Ce qui a été écrit | Pourquoi cette forme |
| --- | --- | --- |
| **Launch profiles** | `app/backend/automations/launch_profiles.py` (moteur pur, 195 lignes), 5 méthodes de service dans `fleet_features.py`, 5 méthodes de pont, onglet *Fleet → Launch profiles* | Un profil est une **destination nommée**, pas un second chemin de lancement. `launch_with_profile` délègue à `start_wave_launch`, donc le plafond de simultanéité, le délai entre lancements et la pause entre vagues continuent de s'appliquer. Un profil interdit d'avoir à la fois un `job_id` et un code de serveur privé : ce sont deux destinations différentes, l'ambiguïté serait un bug silencieux. |
| **Emergency stop** | `emergency_stop()` dans `fleet_features.py`, bouton rouge en bas de *Fleet → Comfort* | Il arrête les macros, annule la file de lancement, purge les reprises de macro en attente et désarme les règles automatiques. Il **ne ferme aucun client Roblox** : le propriétaire a explicitement refusé toute fermeture automatique (décision « Non » du 14/08). `clients_closed` vaut toujours `0` et la réponse le dit. |
| **État « unattended » (AFK) et « error » au tableau de bord** | `_dashboard_state()` dans `application_service.py` | Roblox n'expose pas le minuteur d'inactivité d'un joueur. L'état est **inféré** : en jeu + aucune macro + durée supérieure à `comfort.sleep_after_minutes`. Le libellé affiché est « In game, unattended » et non « AFK » tout court, pour ne pas prétendre lire l'état du jeu. |

Tout le reste de la liste de souhaits existait déjà et a été vérifié plutôt que
réécrit (délais aléatoires dans les macros, dry run, notes par compte, tags,
champs personnalisés, spread mode, main+followers, party, scheduler, heatmap,
fiabilité, webhooks Discord, rapport quotidien, etc.).

### 2.3 L'optimisation

`get_settings()` reconstruisait tout l'arbre de réglages à **chaque** appel : copie
profonde des valeurs par défaut, lecture SQLite de toutes les lignes, décodage
JSON, écriture des chemins. Or il est appelé 39 fois dans le code, dont plusieurs
fois par rafraîchissement du tableau de bord et à chaque tick du watcher.

Correctif : le dépôt (`sqlite_repository.py`) expose maintenant
`settings_revision`, incrémentée par **toute** écriture de réglage
(`set_setting`, `delete_setting`). Le service garde un instantané et le réutilise
tant que la révision ne bouge pas, en renvoyant toujours une copie privée. Le
comportement est identique, le coût s'effondre.

Garde-fou : `tests/test_fleet_features.py::test_settings_are_read_once_until_something_changes`
vérifie qu'une seule lecture dépôt sert 9 appels, qu'une écriture invalide bien
l'instantané, et qu'un appelant qui modifie sa copie ne peut pas empoisonner la
lecture suivante.

### 2.4 Bugs corrigés en route

- `_dashboard_state` renvoyait `in_game` pour un client planté : un client
  `crashed` / `exited` / `terminated` est désormais `error`, visible comme tel.
- `get_dashboard` lisait les réglages deux fois par rafraîchissement (nouveau
  besoin `comfort` + `_launcher_settings`). Avec le cache, la seconde lecture est
  gratuite.
- Mon propre test de cache était faux au départ (il comptait 0 lecture parce que
  l'instantané pris au démarrage du service était encore valide). Corrigé en
  forçant une écriture avant de compter — le test prouve maintenant vraiment le
  cache.

---

## 3. Carte du code

```
app/backend/
  api/bridge.py                 176 méthodes, zéro logique : normalise et transmet
  services/application_service.py  cœur : comptes, lancement, instances, réglages, macros
  services/fleet_features.py       mixin "fleet" : stats, scheduler, santé, serveurs,
                                   coordination, confort, alertes, studio macro,
                                   règles, launch profiles, emergency stop
  automations/macros.py            moteur de macros (DSL + blocs), bornes, runs
  automations/macro_studio.py      profils de touches, variables, debugger, versions
  automations/launch_profiles.py    (v11) destinations nommées
  automations/coordination.py       spread / main+followers / sync / party
  automations/scheduler.py          tâches horaires
  automations/batch_launcher.py     vagues de lancement
  automations/direct_input.py       pydirectinput, une seule fenêtre Roblox
  watchers/                        process_monitor, statistics, comfort, rejoin_rules,
                                   resource_plan, rule_engine, window_positioner
  roblox/                          launcher, client_settings (FPS), server_registry
  integrations/alerts.py           Discord, relais push, rapport quotidien
  core/                            config (réglages par défaut), errors, account_health
  repositories/sqlite_repository.py  SQLite + garde des clés sensibles
app/frontend/src/app.js           tout l'écran (3753 lignes), 137 actions déclarées
app/frontend/src/bridge.js        contrat des 176 méthodes + stubs de prévisualisation
scripts/portable_audit.py         parité pont / contrat / actions cliquables
scripts/feature_inventory.py      (v11) inventaire prouvé des fonctionnalités
scripts/build_windows.py          PyInstaller --onefile --windowed
```

---

## 4. Invariants — à ne pas casser

1. **Aucune fermeture automatique d'un client Roblox.** Les règles, le watchdog
   et l'emergency stop mettent en pause, relancent, avertissent. Fermer reste un
   acte humain, avec confirmation explicite.
2. **Jamais de clé de réglage contenant** `password`, `passwd`, `pwd`, `cookie`,
   `token`, `secret`, `credential`, `authorization`, `api_key`, `session`,
   `roblosecurity`. Le dépôt lève `RepositoryError: Sensitive settings must use
   OS-protected storage.` — un simple `rules.session_max_hours` avait fait tomber
   69 tests d'un coup. Un test de garde existe :
   `tests/test_settings_persistence_guard.py`.
3. **Macros = une seule fenêtre Roblox**, via pydirectinput, au premier plan. Le
   chemin multi-fenêtres reste derrière le flag `ASTRO_ENABLE_MULTI_WINDOW_MACROS`,
   inactif par défaut, conservé sans être promu.
4. **Nexus est caché, pas supprimé** (flag `ASTRO_ENABLE_NEXUS`). Aucune route de
   macro ne passe par Nexus.
5. **Les URL de webhook sont en écriture seule** : jamais renvoyées à l'UI, jamais
   journalisées (`alerts.redact`).
6. **Pas d'interrupteur mort** : aucun réglage ne doit exister sans code qui le
   lit. L'audit et l'inventaire servent à ça.
7. **Le pont ne contient pas de logique.** Une nouvelle fonctionnalité = moteur
   pur testable + méthode de service + méthode de pont + entrée dans
   `bridge.js` + action UI + tests. `scripts/portable_audit.py` doit rester à
   parité exacte (176/176, 0 action non gérée).

---

## 5. Limites assumées (à répéter dans l'UI, pas à cacher)

| Limite | Détail |
| --- | --- |
| Entrées clavier/souris | délivrées à la fenêtre **au premier plan** ; une fenêtre minimisée n'est pas pilotée dans ce build |
| FPS | le cap Roblox est **global** (FFlag), donc pas de FPS par instance ; un profil qui fixe un FPS change le cap pour tous |
| Audio | pas de contrôle audio par processus sur cette machine : les niveaux sont **stockés** et l'UI le dit |
| Party | pas d'API Roblox de groupe : une « party » = tout le monde sur le même `JobId` |
| Notifications téléphone | relais webhook, pas d'app mobile |
| Auto-rejoin | détecte les codes de déconnexion des logs (277, 278…) mais pas la boîte de dialogue in-app |
| État « unattended » | inféré (en jeu, sans macro, au-delà du délai de veille), pas lu dans le jeu |
| `start_group_macro` | démarre une fenêtre, les autres passent en `queued` |

---

## 6. Volontairement non construit

Exclu par le propriétaire, à ne pas ajouter sans son accord :

- **Vision** : captures par instance, timeline, détecteur d'écran figé, conditions
  par pixel, template matching, déclencheurs visuels.
- **Distant** : tableau de bord mobile, appairage QR, vue distante, capture à
  distance.
- **Macros en fenêtre minimisée**. Si ce chantier est un jour ouvert : il faut
  passer de `SendInput` à des messages Win32 ciblés (`PostMessage`/`SendMessage`
  avec `WM_KEYDOWN`/`WM_LBUTTONDOWN` adressés au HWND) ou à un pilote d'entrée
  virtuel isolé. Ce n'est pas un flag à activer, c'est un backend d'entrée à
  écrire et à tester séparément.

---

## 7. Valider le dépôt

Sous Windows (autorité de référence) :

```powershell
python -m pip install -e .[dev]
python -m pytest                       # attendu : ~776 collectés, 0 échec, 2 ignorés
python scripts/feature_inventory.py    # attendu : 91 proven, 0 missing
python scripts/portable_audit.py       # attendu : 176/176, listes de manques vides
python scripts/evidence_acceptance_test.py
python -m compileall -q app main.py scripts\build_windows.py
python scripts/build_windows.py        # produit dist/AstroAccountManager.exe
```

À savoir sur l'environnement de développement portable (Linux, sans réseau) :
`tests/test_nexus.py` ne peut pas s'importer (`websockets` absent), et 84 tests
sont structurellement en échec hors Windows (API Windows, `pytest.raises(match=)`
non géré par le harnais portable). Ces 84 échecs existent déjà sur la base
intacte : ce n'est pas une régression, c'est l'absence de Windows.

---

## 8. Chiffres de référence de v11

| Mesure | Valeur |
| --- | --- |
| Méthodes de pont / contrat frontend | 176 / 176 |
| Actions UI déclarées, non gérées | 137 / 0 |
| Fonctions de test dans le dépôt | 666 |
| Fonctionnalités prouvées par l'inventaire | 91 |
| Suites nouvelles ou touchées | 37 passés, 0 échec |
| Suite complète, harnais portable | 684 passés, 84 échecs environnementaux, 2 ignorés |
| `app/frontend/src/app.js` | 3753 lignes |
| `app/backend/services/fleet_features.py` | 1630 lignes |

---

## 9. Suites possibles (par ordre d'utilité)

1. **Backend d'entrée pour fenêtre minimisée** (`PostMessage`/pilote virtuel) :
   c'est le seul vrai plafond fonctionnel restant.
2. **Détection de la boîte de dialogue de déconnexion in-app** pour compléter
   l'auto-rejoin, qui ne voit aujourd'hui que les logs.
3. **Audio par processus** via les API de session audio Windows, pour que le mixer
   agisse au lieu de seulement mémoriser.
4. **Étendre `feature_inventory.py`** à chaque nouvelle fonctionnalité : c'est le
   garde-fou le moins coûteux du dépôt.
5. Vision / Distant, uniquement si le propriétaire les rouvre.

---

## 10. Pièges connus du dépôt

- `zip -x '*.git*'` supprime `docs/*/.gitkeep` et `.gitignore` : l'archive doit
  contenir 6 entrées de ce type.
- `updatePage`-style édition de `app.js` : préférer des ancres uniques et vérifier
  avec `node --check` ; le fichier fait 3753 lignes d'une seule classe.
- Les tests de contrat frontend lisent le **source JS** : renommer une action sans
  mettre à jour `tests/test_frontend_fleet_ui.py` fera échouer la suite, ce qui est
  voulu.
- `pytest.raises(..., match=...)` fonctionne sous Windows mais pas dans le harnais
  portable : ne pas conclure à une régression sur ces échecs.

## 11. Correctifs v12 (rapportés depuis l'usage réel)

Deux bugs signalés par l'utilisateur, tous deux reproduits dans le code avant
correction.

**1. « Le lien n'est pas valide » sur un lien de serveur privé qui fonctionne.**
`PrivateServerHelper.parse_vip_link` exigeait un `placeId` dans l'URL. Les liens
modernes `https://www.roblox.com/share?code=<opaque>&type=Server` n'en
contiennent aucun : le code est opaque et seul Roblox peut le développer, via
`POST https://apis.roblox.com/sharelinks/v1/resolve-link` avec une session
signée. Le parseur reconnaît désormais cette forme et la renvoie avec
`needs_resolution`; `ApplicationService._resolve_share_link` demande à Roblox,
sous l'identité du compte qui va rejoindre, puis lance avec le `placeId` et le
`linkCode` obtenus. Un lien `type=Profile` est refusé en le nommant, un compte
sans session stockée reçoit un message sur la session — plus jamais « lien
invalide » pour un lien correct. Preuves : `tests/test_private_server_links.py`
(10 tests, aucun accès réseau).

**2. Les champs alias et description perdaient le focus pendant la frappe.**
Le sondage de 3 s (`refreshRuntimeSilently` → `render`) réassignait
`root.innerHTML` dès qu'un chiffre changeait (temps de session, présence,
mémoire). L'élément sous le curseur était détruit, avec le texte déjà tapé.
`OrbitApp.swapHtml(container, html)` remplace les deux assignations directes :
valeur, sélection et focus sont transportés à travers le remplacement. Preuves :
`tests/test_frontend_focus_preservation.py` (2 tests, dont un vrai passage par
Node contre un DOM factice).

Chiffres après v12 : 176 méthodes de pont, 137 actions, **678 fonctions de
test**, 91 fonctionnalités prouvées par `scripts/feature_inventory.py`.
