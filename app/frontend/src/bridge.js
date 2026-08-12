/*
 * The UI only talks to this adapter. In desktop mode it delegates to
 * window.pywebview.api; in a browser it uses a deterministic local preview.
 */

const CONTRACT_METHODS = [
  'bootstrap', 'list_accounts', 'create_account', 'update_account',
  'delete_accounts', 'get_public_profile', 'refresh_account_public_profile', 'get_public_presence', 'refresh_account_presence',
  'start_oauth_login', 'poll_oauth_login', 'cancel_oauth_login',
  'refresh_oauth_account', 'disconnect_oauth_account', 'list_groups', 'create_group', 'update_group', 'delete_group', 'move_accounts', 'reorder_accounts', 'list_games',
  'list_recent_games', 'list_favorite_games', 'get_game', 'set_game_favorite', 'remove_game', 'list_servers',
  'resolve_server_region', 'launch_account', 'list_uwp_packages', 'launch_uwp_package', 'list_instances',
  'refresh_instances', 'get_instance_monitor', 'close_instance', 'bind_instance', 'configure_account_watcher', 'get_settings', 'update_settings',
  'get_windows_startup_status', 'set_windows_startup', 'get_activity',
  'get_notifications', 'dismiss_notification', 'backup_data', 'list_backups',
  'restore_backup', 'export_metadata', 'import_metadata', 'migrate_legacy', 'get_diagnostics',
  'start_nexus_server', 'stop_nexus_server', 'get_nexus_status', 'send_nexus_command', 'get_nexus_lua_script',
  'get_multi_instance_status', 'set_multi_instance',
  'get_fps_cap', 'set_fps_cap', 'remove_fps_cap', 'start_batch_launch', 'cancel_batch_launch', 'get_batch_launch_status',
  'generate_auth_ticket', 'get_account_csrf_token', 'generate_rbx_player_link', 'get_account_cookie', 'refresh_account_session', 'export_account_sessions', 'import_bulk_accounts', 'position_instance_window', 'capture_instance_window', 'restore_instance_window',
  'change_account_password', 'change_account_email', 'logout_all_account_sessions', 'set_account_display_name',
  'send_account_friend_request', 'block_account_user', 'unblock_account_user', 'quick_log_in_account',
  'set_account_follow_privacy', 'unlock_account_pin',
  'parse_vip_link', 'search_players', 'get_player_presence', 'find_player_server', 'get_random_server', 'close_beta_home_windows', 'check_for_updates',
  'get_account_blocked_list', 'unblock_all_account_users', 'set_account_avatar',
  'add_account_from_cookie', 'start_manual_browser_login', 'poll_manual_browser_login'
];

const DAY = 86400000;

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function uid(prefix) {
  return prefix + '_' + Math.random().toString(36).slice(2, 10);
}

function optionalPublicUserId(value) {
  const userId = String(value === undefined || value === null ? '' : value).trim();
  if (!userId) return null;
  if (!/^[1-9][0-9]*$/.test(userId)) throw new Error('Roblox User ID must be a positive whole number.');
  return userId;
}

function storageGet(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : clone(fallback);
  } catch (_) {
    return clone(fallback);
  }
}

function storageSet(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch (_) {
    // Browser privacy modes can deny local storage. The in-memory state remains usable.
  }
}

const seed = {
  groups: [
    { id: 'grp_favorites', name: 'Favorites', color: 'violet', icon: 'star', collapsed: false, favorite: true, order: 0 },
    { id: 'grp_raiders', name: 'Raiders', color: 'coral', icon: 'zap', collapsed: false, favorite: false, order: 1 },
    { id: 'grp_builders', name: 'Builders', color: 'mint', icon: 'cube', collapsed: false, favorite: false, order: 2 }
  ],
  accounts: [
    { id: 'acct_aria', username: 'AriaNebula', display_name: 'Aria Nebula', group_id: 'grp_favorites', favorite: true, status: 'ready', last_used: Date.now() - DAY * 0.12, avatar_color: 'violet', notes: 'Main account' },
    { id: 'acct_cho', username: 'ChoBuilds', display_name: 'Cho', group_id: 'grp_builders', favorite: false, status: 'ready', last_used: Date.now() - DAY * 1.4, avatar_color: 'mint', notes: 'Studio & testing' },
    { id: 'acct_niko', username: 'NikoRift', display_name: 'Niko Rift', group_id: 'grp_raiders', favorite: false, status: 'in_game', last_used: Date.now() - DAY * 0.03, avatar_color: 'coral', notes: 'Instance active' },
    { id: 'acct_luma', username: 'LumaLoo', display_name: 'Luma', group_id: 'grp_favorites', favorite: true, status: 'offline', last_used: Date.now() - DAY * 4, avatar_color: 'blue', notes: 'Alt account' },
    { id: 'acct_milo', username: 'MiloByte', display_name: 'Milo Byte', group_id: null, favorite: false, status: 'ready', last_used: Date.now() - DAY * 2.2, avatar_color: 'amber', notes: '' }
  ],
  games: [
    { place_id: '2753915549', title: 'Blox Fruits', creator: 'Gamer Robot Inc', players: 438214, thumbnail_color: 'sunset', category: 'Adventure', last_opened: Date.now() - DAY * 0.2, favorite: true },
    { place_id: '920587237', title: 'Adopt Me!', creator: 'Uplift Games', players: 201490, thumbnail_color: 'lavender', category: 'Roleplay', last_opened: Date.now() - DAY * 1.7, favorite: false },
    { place_id: '6284583030', title: 'Pet Simulator 99!', creator: 'BIG Games Pets', players: 77911, thumbnail_color: 'aqua', category: 'Simulation', last_opened: Date.now() - DAY * 3.1, favorite: true },
    { place_id: '4924922222', title: 'Brookhaven RP', creator: 'Wolfpaq', players: 323991, thumbnail_color: 'orchid', category: 'Roleplay', last_opened: Date.now() - DAY * 7.3, favorite: false }
  ],
  instances: [
    { id: 'inst_4872', account_id: 'acct_niko', pid: 4872, game: 'Blox Fruits', state: 'running', started_at: Date.now() - 1000 * 60 * 23, memory_mb: 843, server: 'Frankfurt, DE' },
    { id: 'inst_5216', account_id: 'acct_aria', pid: 5216, game: 'Roblox Home', state: 'starting', started_at: Date.now() - 1000 * 60 * 1, memory_mb: 217, server: '—' }
  ],
  activity: [
    { id: 'act_1', type: 'launch', title: 'NikoRift joined Blox Fruits', detail: 'Frankfurt server · 17 / 20 players', at: Date.now() - 1000 * 60 * 8 },
    { id: 'act_2', type: 'account', title: 'ChoBuilds was updated', detail: 'Group moved to Builders', at: Date.now() - 1000 * 60 * 46 },
    { id: 'act_3', type: 'backup', title: 'Encrypted backup completed', detail: '3.2 MB · Local vault', at: Date.now() - DAY * 0.5 },
    { id: 'act_4', type: 'system', title: 'Instance watcher is healthy', detail: 'Last checked a minute ago', at: Date.now() - DAY * 1.1 }
  ],
  notifications: [
    { id: 'note_1', kind: 'info', title: 'Welcome to the new workspace', body: 'Your account collection is ready to organize.', at: Date.now() - DAY * 0.1, read: false },
    { id: 'note_2', kind: 'success', title: 'Backup verified', body: 'The latest backup passed its integrity check.', at: Date.now() - DAY * 1.1, read: false }
  ],
  settings: {
    theme: 'dark', accent: 'violet', density: 'comfortable', reduce_motion: false,
    launch_behavior: 'confirm', close_when_empty: false, watcher_enabled: true,
    auto_backup: true, notifications: true, diagnostics: false,
    categories: {
      oauth: {
        enabled: false,
        client_id: '',
        redirect_uri: 'http://127.0.0.1:8989/oauth/callback',
        callback_timeout_seconds: 300
      }
    }
  }
};

class PreviewBridge {
  constructor() {
    this.state = storageGet('orbit-preview-state', seed);
    if (!Array.isArray(this.state.backups)) this.state.backups = [];
    if (!Array.isArray(this.state.metadata_exports)) this.state.metadata_exports = [];
  }

  save() {
    storageSet('orbit-preview-state', this.state);
  }

  event(type, title, detail) {
    this.state.activity.unshift({ id: uid('act'), type: type, title: title, detail: detail || '', at: Date.now() });
    this.state.activity = this.state.activity.slice(0, 32);
  }

  snapshotData() {
    return clone({
      accounts: this.state.accounts, groups: this.state.groups, games: this.state.games,
      instances: this.state.instances, activity: this.state.activity,
      notifications: this.state.notifications, settings: this.state.settings
    });
  }

  createBackup(label) {
    const snapshot = this.snapshotData();
    const record = {
      id: uid('backup'), label: label || 'manual', source_name: 'preview-state',
      created_at: Date.now(), size: JSON.stringify(snapshot).length, verified: true,
      snapshot: snapshot
    };
    this.state.backups.unshift(record);
    this.state.backups = this.state.backups.slice(0, 24);
    return record;
  }

  publicMetadata() {
    const groupNames = new Map(this.state.groups.map(function (group) { return [group.id, group.name]; }));
    return {
      version: 1,
      groups: this.state.groups.map(function (group) {
        return { name: group.name, color: group.color, icon: group.icon, favorite: Boolean(group.favorite), order: group.order || 0 };
      }),
      accounts: this.state.accounts.map(function (account) {
        return {
          username: account.username, user_id: account.user_id || null, display_name: account.display_name,
          group_name: account.group_id ? groupNames.get(account.group_id) || null : null,
          favorite: Boolean(account.favorite), avatar_color: account.avatar_color || 'violet'
        };
      }),
      games: this.state.games.map(function (game) {
        return {
          place_id: game.place_id, title: game.title, creator: game.creator,
          players: game.players, thumbnail_color: game.thumbnail_color,
          category: game.category, favorite: Boolean(game.favorite)
        };
      })
    };
  }

  checksum(value) {
    let hash = 2166136261;
    const text = JSON.stringify(value);
    for (let index = 0; index < text.length; index += 1) {
      hash ^= text.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(16).padStart(8, '0');
  }

  account(id) {
    const value = this.state.accounts.find(function (account) { return account.id === id; });
    if (!value) throw new Error('Account not found');
    return value;
  }

  async bootstrap() {
    return {
      mode: 'preview',
      accounts: clone(this.state.accounts), groups: clone(this.state.groups),
      games: clone(this.state.games), instances: clone(this.state.instances),
      settings: clone(this.state.settings), activity: clone(this.state.activity),
      notifications: clone(this.state.notifications), diagnostics: await this.get_diagnostics()
    };
  }

  async list_accounts(query) {
    const phrase = String(query || '').trim().toLowerCase();
    const rows = phrase ? this.state.accounts.filter(function (account) {
      return [account.username, account.display_name, account.notes].join(' ').toLowerCase().includes(phrase);
    }) : this.state.accounts;
    return clone(rows);
  }

  async create_account(payload) {
    const username = String(payload.username || '').trim();
    if (!username) throw new Error('A username is required.');
    if (this.state.accounts.some(function (item) { return item.username.toLowerCase() === username.toLowerCase(); })) {
      throw new Error('That username is already in your workspace.');
    }
    const account = {
      id: uid('acct'), username: username, display_name: String(payload.display_name || username).trim(),
      user_id: optionalPublicUserId(payload.user_id), group_id: payload.group_id || null, favorite: Boolean(payload.favorite), status: 'ready',
      last_used: null, avatar_color: payload.avatar_color || 'violet', notes: String(payload.notes || '').trim()
    };
    this.state.accounts.unshift(account);
    this.event('account', username + ' was added', account.group_id ? 'Added to a group' : 'Ready to launch');
    this.save();
    return clone(account);
  }

  async update_account(id, payload) {
    const account = this.account(id);
    const next = Object.assign({}, payload || {});
    if (Object.prototype.hasOwnProperty.call(next, 'user_id')) next.user_id = optionalPublicUserId(next.user_id);
    Object.assign(account, next);
    this.event('account', account.username + ' was updated', 'Account details saved');
    this.save();
    return clone(account);
  }

  async delete_accounts(ids) {
    const set = new Set(ids || []);
    const deleted = this.state.accounts.filter(function (account) { return set.has(account.id); });
    this.state.accounts = this.state.accounts.filter(function (account) { return !set.has(account.id); });
    this.state.instances = this.state.instances.filter(function (instance) { return !set.has(instance.account_id); });
    this.event('account', deleted.length + ' account' + (deleted.length === 1 ? '' : 's') + ' removed', 'Removed from this device');
    this.save();
    return { deleted: deleted.map(function (item) { return item.id; }) };
  }

  publicDataUnavailable() {
    throw new Error('Public Roblox profile and presence lookups require the desktop bridge. Preview mode never simulates remote Roblox data.');
  }

  async get_public_profile() { return this.publicDataUnavailable(); }
  async refresh_account_public_profile() { return this.publicDataUnavailable(); }
  async get_public_presence() { return this.publicDataUnavailable(); }
  async refresh_account_presence() { return this.publicDataUnavailable(); }

  oauthUnavailable() {
    throw new Error('Roblox OAuth requires the desktop bridge and a registered local OAuth configuration. Preview mode never simulates sign-in.');
  }

  desktopOperationUnavailable(operation) {
    throw new Error((operation || 'This operation') + ' requires the Astro Account Manager desktop bridge. Preview mode never simulates Windows, Roblox, session, or remote account actions.');
  }

  async start_oauth_login() { return this.oauthUnavailable(); }
  async poll_oauth_login() { return this.oauthUnavailable(); }
  async cancel_oauth_login() { return this.oauthUnavailable(); }
  async refresh_oauth_account() { return this.oauthUnavailable(); }
  async disconnect_oauth_account() { return this.oauthUnavailable(); }

  async list_groups() { return clone(this.state.groups); }

  async create_group(payload) {
    const name = String(payload.name || '').trim();
    if (!name) throw new Error('A group name is required.');
    const group = { id: uid('grp'), name: name, color: payload.color || 'violet', icon: payload.icon || 'folder', collapsed: false, favorite: false, order: this.state.groups.length };
    this.state.groups.push(group);
    this.event('group', name + ' group created', 'Ready for accounts');
    this.save();
    return clone(group);
  }

  async update_group(id, payload) {
    const group = this.state.groups.find(function (item) { return item.id === id; });
    if (!group) throw new Error('Group not found');
    const next = Object.assign({}, payload || {});
    if (Object.prototype.hasOwnProperty.call(next, 'name')) {
      const name = String(next.name || '').trim();
      if (!name) throw new Error('A group name is required.');
      next.name = name;
    }
    Object.assign(group, next);
    this.event('group', group.name + ' group updated', 'Group preferences saved');
    this.save();
    return clone(group);
  }

  async delete_group(id) {
    const group = this.state.groups.find(function (item) { return item.id === id; });
    if (!group) throw new Error('Group not found');
    this.state.accounts.forEach(function (account) { if (account.group_id === id) account.group_id = null; });
    this.state.groups = this.state.groups.filter(function (item) { return item.id !== id; });
    this.event('group', group.name + ' group removed', 'Associated accounts are now ungrouped');
    this.save();
    return { deleted: id };
  }

  async move_accounts(ids, groupId) {
    const set = new Set(ids || []);
    this.state.accounts.forEach(function (account) { if (set.has(account.id)) account.group_id = groupId || null; });
    this.event('group', set.size + ' account' + (set.size === 1 ? '' : 's') + ' reorganized', groupId ? 'Moved to a group' : 'Moved to ungrouped');
    this.save();
    return { moved: Array.from(set), group_id: groupId || null };
  }

  async reorder_accounts(accountIds) {
    if (!Array.isArray(accountIds) || accountIds.length !== this.state.accounts.length) throw new Error('A complete account order is required.');
    const current = new Map(this.state.accounts.map(function (account) { return [account.id, account]; }));
    const unique = new Set(accountIds);
    if (unique.size !== accountIds.length) throw new Error('Account order cannot contain duplicates.');
    if (accountIds.some(function (id) { return !current.has(id); })) throw new Error('Account order contains an unknown account.');
    this.state.accounts = accountIds.map(function (id) { return current.get(id); });
    this.event('account', 'Account order updated', 'Local preview order saved');
    this.save();
    return clone(this.state.accounts);
  }

  async list_games() { return clone(this.state.games); }

  async list_recent_games() {
    return clone(this.state.games.slice().sort(function (left, right) { return Number(right.last_opened || 0) - Number(left.last_opened || 0); }));
  }

  async list_favorite_games() {
    return clone(this.state.games.filter(function (game) { return Boolean(game.favorite); }));
  }

  async get_game(placeId) {
    const game = this.state.games.find(function (item) { return String(item.place_id) === String(placeId); });
    if (!game) throw new Error('Game not found');
    return clone(Object.assign({}, game, { description: 'A popular world in your recent collection. Browse available public servers or launch directly with an account.' }));
  }

  async set_game_favorite(placeId, favorite) {
    const game = this.state.games.find(function (item) { return String(item.place_id) === String(placeId); });
    if (!game) throw new Error('Game not found');
    game.favorite = Boolean(favorite);
    this.event('game', game.title + (game.favorite ? ' added to favorites' : ' removed from favorites'), 'Local preview game preference');
    this.save();
    return clone(game);
  }

  async remove_game(placeId) {
    const index = this.state.games.findIndex(function (item) { return String(item.place_id) === String(placeId); });
    if (index < 0) throw new Error('Game not found');
    const removed = this.state.games.splice(index, 1)[0];
    this.event('game', removed.title + ' removed', 'Local preview game history');
    this.save();
    return { deleted: Number(removed.place_id) };
  }

  async list_servers(placeId) {
    const game = await this.get_game(placeId);
    const regions = ['Frankfurt, DE', 'Paris, FR', 'London, GB', 'Ashburn, US', 'Singapore, SG'];
    const output = [];
    for (let index = 0; index < 12; index += 1) {
      const capacity = index % 3 === 0 ? 20 : 12;
      const playing = Math.max(1, Math.min(capacity, capacity - ((index * 3 + 2) % 7)));
      output.push({
        id: 'srv_' + game.place_id + '_' + index, place_id: game.place_id,
        job_id: 'a' + (7831 + index) + '-b71f-' + (940 + index) + '-c' + (200 + index),
        players: playing, capacity: capacity, ping: 31 + index * 11,
        region: regions[index % regions.length], vip: index === 8, uptime: (index + 1) * 14
      });
    }
    return output;
  }

  async resolve_server_region() {
    return this.desktopOperationUnavailable('Resolving a live server region');
  }

  async launch_account(id, target) {
    const account = this.account(id);
    const game = target && target.place_id ? this.state.games.find(function (item) { return String(item.place_id) === String(target.place_id); }) : null;
    account.status = 'in_game';
    account.last_used = Date.now();
    if (game) game.last_opened = Date.now();
    const existing = this.state.instances.find(function (item) { return item.account_id === id; });
    if (!existing) this.state.instances.unshift({ id: uid('inst'), account_id: id, pid: Math.floor(3000 + Math.random() * 6000), game: game ? game.title : 'Roblox Home', state: 'starting', started_at: Date.now(), memory_mb: 210, server: target && target.region ? target.region : '—' });
    this.event('launch', account.username + ' launch requested', game ? game.title : 'Roblox Home');
    this.save();
    return { accepted: true, account_id: id, target: target || null };
  }

  uwpUnavailable() {
    throw new Error('Roblox UWP package discovery and launch require the desktop bridge. Preview mode never invents installed Windows packages.');
  }

  async list_uwp_packages() { return this.uwpUnavailable(); }
  async launch_uwp_package() { return this.uwpUnavailable(); }

  windowsStartupUnavailable() {
    throw new Error('Windows startup registration requires the desktop bridge. Preview mode never simulates a Windows Run registration.');
  }

  async get_windows_startup_status() { return this.windowsStartupUnavailable(); }
  async set_windows_startup() { return this.windowsStartupUnavailable(); }

  async list_instances() { return clone(this.state.instances); }

  async refresh_instances() {
    this.state.instances.forEach(function (instance) { if (instance.state === 'starting') instance.state = 'running'; });
    this.save();
    return clone(this.state.instances);
  }

  async get_instance_monitor() {
    return { instances: clone(this.state.instances), events: [], pending_restarts: [], last_scan_complete: true, termination_enabled: false };
  }

  async close_instance(pid, confirm) {
    if (!confirm) throw new Error('Closing an instance requires confirmation.');
    const index = this.state.instances.findIndex(function (item) { return Number(item.pid) === Number(pid); });
    if (index < 0) throw new Error('Instance not found.');
    const instance = this.state.instances[index];
    this.state.instances.splice(index, 1);
    const account = this.state.accounts.find(function (item) { return item.id === instance.account_id; });
    if (account) account.status = 'ready';
    this.event('instance', 'Local instance closed', 'PID ' + pid);
    this.save();
    return { pid: Number(pid), status: 'terminated', message: 'Instance closed in preview.' };
  }

  async bind_instance(pid, accountId, target, confirm) {
    if (!confirm) throw new Error('Binding an instance requires confirmation.');
    const instance = this.state.instances.find(function (item) { return Number(item.pid) === Number(pid); });
    const account = this.account(accountId);
    if (!instance) throw new Error('Instance not found.');
    instance.account_id = account.id;
    instance.state = 'running';
    account.status = 'in_game';
    this.event('instance', 'Instance associated', account.username);
    this.save();
    return clone(instance);
  }

  async configure_account_watcher(id, rule) {
    const account = this.account(id);
    account.watcher = Object.assign({}, account.watcher || {}, rule || {});
    this.event('watcher', 'Account watcher rule updated', account.username);
    this.save();
    return Object.assign({ account_id: id }, clone(account.watcher));
  }

  async get_settings() { return clone(this.state.settings); }

  async update_settings(values) {
    const next = Object.assign({}, values || {});
    if (next.categories && typeof next.categories === 'object') {
      this.state.settings.categories = Object.assign({}, this.state.settings.categories || {}, next.categories);
      delete next.categories;
    }
    Object.assign(this.state.settings, next);
    this.save();
    return clone(this.state.settings);
  }

  async get_activity() { return clone(this.state.activity); }
  async get_notifications() { return clone(this.state.notifications); }

  async dismiss_notification(id) {
    this.state.notifications = this.state.notifications.filter(function (item) { return item.id !== id; });
    this.save();
    return { dismissed: id };
  }

  async backup_data() {
    const record = this.createBackup('manual');
    this.event('backup', 'Preview backup completed', 'Local preview data has been snapshotted');
    this.save();
    return { id: record.id, path: 'Preview vault', size: record.size, created_at: record.created_at, verified: true };
  }

  async list_backups() {
    return clone(this.state.backups.map(function (record) {
      return {
        id: record.id, label: record.label, source_name: record.source_name,
        created_at: record.created_at, size: record.size, verified: Boolean(record.verified)
      };
    }));
  }

  async restore_backup(id, confirm) {
    if (!confirm) throw new Error('Restoring a backup requires explicit confirmation.');
    const record = this.state.backups.find(function (item) { return item.id === id; });
    if (!record || !record.verified || !record.snapshot) throw new Error('Verified backup not found.');
    const safety = this.createBackup('pre-restore');
    const snapshot = clone(record.snapshot);
    this.state.accounts = snapshot.accounts || [];
    this.state.groups = snapshot.groups || [];
    this.state.games = snapshot.games || [];
    this.state.instances = snapshot.instances || [];
    this.state.activity = snapshot.activity || [];
    this.state.notifications = snapshot.notifications || [];
    this.state.settings = snapshot.settings || {};
    this.event('restore', 'Preview backup restored', 'A pre-restore snapshot is available');
    this.save();
    return { restored: id, pre_restore_backup: safety.id, verified: true };
  }

  async export_metadata() {
    const payload = this.publicMetadata();
    const filename = 'astro-metadata-' + new Date().toISOString().replace(/[-:.]/g, '') + '.json';
    const record = {
      id: uid('export'), filename: filename, path: 'Preview exports/' + filename,
      payload: payload, checksum: this.checksum(payload), size: JSON.stringify(payload).length,
      classification: 'public_metadata_only', created_at: Date.now()
    };
    this.state.metadata_exports.unshift(record);
    this.state.metadata_exports = this.state.metadata_exports.slice(0, 16);
    this.event('export', 'Preview metadata exported', filename);
    this.save();
    return {
      path: record.path, filename: record.filename, size: record.size,
      checksum: record.checksum, classification: record.classification
    };
  }

  async import_metadata(path, confirm) {
    if (!confirm) throw new Error('Importing metadata requires explicit confirmation.');
    const record = this.state.metadata_exports.find(function (item) { return item.path === path || item.filename === path; });
    if (!record || !record.payload) throw new Error('Preview can import only a metadata export created in this preview workspace.');
    if (record.checksum !== this.checksum(record.payload)) throw new Error('Metadata checksum verification failed.');
    const safety = this.createBackup('pre-metadata-import');
    const payload = record.payload;
    const groupMap = new Map(this.state.groups.map(function (group) { return [group.name.toLowerCase(), group.id]; }));
    let groupsImported = 0;
    let accountsImported = 0;
    let gamesImported = 0;
    (payload.groups || []).forEach(function (group) {
      const key = String(group.name || '').toLowerCase();
      if (!key || groupMap.has(key)) return;
      const created = { id: uid('grp'), name: String(group.name), color: group.color || 'violet', icon: group.icon || 'folder', collapsed: false, favorite: Boolean(group.favorite), order: this.state.groups.length };
      this.state.groups.push(created);
      groupMap.set(key, created.id);
      groupsImported += 1;
    }.bind(this));
    (payload.accounts || []).forEach(function (account) {
      const username = String(account.username || '').trim();
      if (!username || this.state.accounts.some(function (item) { return item.username.toLowerCase() === username.toLowerCase(); })) return;
      this.state.accounts.push({
        id: uid('acct'), username: username, user_id: optionalPublicUserId(account.user_id), display_name: String(account.display_name || username),
        group_id: account.group_name ? groupMap.get(String(account.group_name).toLowerCase()) || null : null,
        favorite: Boolean(account.favorite), status: 'ready', last_used: null,
        avatar_color: account.avatar_color || 'violet', notes: ''
      });
      accountsImported += 1;
    }.bind(this));
    (payload.games || []).forEach(function (game) {
      const placeId = String(game.place_id || '').trim();
      if (!placeId || this.state.games.some(function (item) { return String(item.place_id) === placeId; })) return;
      this.state.games.push({
        place_id: placeId, title: String(game.title || 'Imported game'), creator: String(game.creator || 'Roblox'),
        players: Number(game.players || 0), thumbnail_color: game.thumbnail_color || 'violet',
        category: game.category || 'Game', favorite: Boolean(game.favorite), last_opened: null
      });
      gamesImported += 1;
    }.bind(this));
    this.event('import', 'Preview metadata imported', accountsImported + ' accounts, ' + groupsImported + ' groups, ' + gamesImported + ' games');
    this.save();
    return {
      accounts_imported: accountsImported, groups_imported: groupsImported, games_imported: gamesImported,
      pre_import_backup: safety.id, classification: 'public_metadata_only'
    };
  }

  async migrate_legacy(path) {
    this.event('migration', 'Legacy migration inspected', path || 'No path supplied');
    this.save();
    return { imported: 0, skipped: 0, path: path || null, preview: true };
  }

  async get_diagnostics() {
    return {
      status: 'healthy', mode: 'preview', checked_at: Date.now(),
      services: [
        { name: 'Storage vault', status: 'healthy', detail: 'Local preview persistence' },
        { name: 'Instance watcher', status: 'unavailable', detail: 'Desktop bridge required' },
        { name: 'Roblox gateway', status: 'degraded', detail: 'Preview mode has no network bridge' }
      ],
      logs: [
        { level: 'INFO', at: Date.now() - 1000 * 60 * 2, message: 'Preview bridge ready.' },
        { level: 'INFO', at: Date.now() - 1000 * 60 * 4, message: 'No native pywebview API detected.' },
        { level: 'WARN', at: Date.now() - 1000 * 60 * 8, message: 'Remote and Windows operations are disabled in Preview.' }
      ]
    };
  }

  async start_nexus_server(host, port) {
    return this.desktopOperationUnavailable('Starting Nexus');
  }

  async stop_nexus_server() {
    return this.desktopOperationUnavailable('Stopping Nexus');
  }

  async get_nexus_status() {
    return {
      running: false,
      available: false,
      host: '127.0.0.1',
      port: 5242,
      url: 'ws://127.0.0.1:5242/Nexus',
      accounts: [],
      reason: 'Desktop bridge required'
    };
  }

  async send_nexus_command(target_account, command_name, payload) {
    return this.desktopOperationUnavailable('Sending a Nexus command');
  }

  async get_nexus_lua_script(host, port) {
    return this.desktopOperationUnavailable('Generating the Nexus client script');
  }

  async get_multi_instance_status() {
    return { supported: false, enabled: false, handle_count: 0, reason: 'Desktop bridge required' };
  }

  async set_multi_instance(enabled) {
    return this.desktopOperationUnavailable('Changing multi-instance support');
  }

  async get_fps_cap() {
    return { supported: false, fps: null, file: null, reason: 'Desktop bridge required' };
  }

  async set_fps_cap(fps) {
    return this.desktopOperationUnavailable('Changing Roblox ClientSettings');
  }

  async remove_fps_cap() {
    return this.desktopOperationUnavailable('Removing the Roblox FPS cap');
  }

  async start_batch_launch(account_ids, target, delay_seconds) {
    return this.desktopOperationUnavailable('Launching Roblox accounts');
  }

  async cancel_batch_launch() {
    return this.desktopOperationUnavailable('Cancelling a desktop launch queue');
  }

  async get_batch_launch_status() {
    return { available: false, in_progress: false, total: 0, launched: 0, failed: 0, current_account: null };
  }

  async generate_auth_ticket(account_id) {
    return this.desktopOperationUnavailable('Generating an authentication ticket');
  }

  async get_account_csrf_token(account_id) {
    return this.desktopOperationUnavailable('Generating an X-CSRF token');
  }

  async generate_rbx_player_link(account_id, place_id, job_id) {
    return this.desktopOperationUnavailable('Generating a roblox-player link');
  }

  async get_account_cookie(account_id) {
    return this.desktopOperationUnavailable('Reading an account session');
  }

  async refresh_account_session(account_id) {
    return this.desktopOperationUnavailable('Validating a Roblox account session');
  }

  async export_account_sessions(account_ids, confirm) {
    return this.desktopOperationUnavailable('Exporting raw account sessions');
  }

  async import_bulk_accounts(raw_text, group_id) {
    return this.desktopOperationUnavailable('Importing authenticated accounts');
  }

  async position_instance_window(pid, x, y, width, height) {
    return this.desktopOperationUnavailable('Positioning a Roblox window');
  }

  async capture_instance_window() {
    return this.desktopOperationUnavailable('Saving a Roblox window position');
  }

  async restore_instance_window() {
    return this.desktopOperationUnavailable('Restoring a Roblox window position');
  }

  async change_account_password(account_id, current_pass, new_pass) {
    return this.desktopOperationUnavailable('Changing a Roblox password');
  }

  async change_account_email(account_id, password, new_email) {
    return this.desktopOperationUnavailable('Changing a Roblox email address');
  }

  async logout_all_account_sessions(account_id) {
    return this.desktopOperationUnavailable('Logging out Roblox sessions');
  }

  async set_account_display_name(account_id, new_display_name) {
    return this.desktopOperationUnavailable('Changing a Roblox display name');
  }

  async send_account_friend_request(account_id, target_user_id) {
    return this.desktopOperationUnavailable('Sending a Roblox friend request');
  }

  async block_account_user(account_id, target_user_id) {
    return this.desktopOperationUnavailable('Blocking a Roblox user');
  }

  async unblock_account_user(account_id, target_user_id) {
    return this.desktopOperationUnavailable('Unblocking a Roblox user');
  }

  async quick_log_in_account(account_id, code) {
    return this.desktopOperationUnavailable('Submitting a Roblox Quick Log In code');
  }

  async set_account_follow_privacy(account_id, privacy) {
    return this.desktopOperationUnavailable('Changing Roblox follow privacy');
  }

  async unlock_account_pin(account_id, pin) {
    return this.desktopOperationUnavailable('Unlocking a Roblox account PIN');
  }

  async parse_vip_link(link) {
    const parsed = new URL(String(link || ''));
    const match = parsed.pathname.match(/\/games\/(\d+)/i);
    const code = parsed.searchParams.get('privateServerLinkCode') || parsed.searchParams.get('code');
    return match && code ? { place_id: Number(match[1]), link_code: code } : null;
  }

  async search_players(keyword, limit) {
    return this.desktopOperationUnavailable('Searching Roblox users');
  }

  async get_player_presence(user_id) {
    return this.desktopOperationUnavailable('Reading Roblox presence');
  }

  async find_player_server() {
    return this.desktopOperationUnavailable('Scanning Roblox public servers for a player');
  }

  async get_random_server(place_id) {
    return this.desktopOperationUnavailable('Selecting a Roblox server');
  }

  async close_beta_home_windows() {
    return this.desktopOperationUnavailable('Closing Roblox windows');
  }

  async check_for_updates() {
    return this.desktopOperationUnavailable('Checking for application updates');
  }

  async get_account_blocked_list(account_id) {
    return this.desktopOperationUnavailable('Reading a Roblox blocked-user list');
  }

  async unblock_all_account_users(account_id) {
    return this.desktopOperationUnavailable('Unblocking Roblox users');
  }

  async set_account_avatar(account_id, asset_ids) {
    return this.desktopOperationUnavailable('Changing a Roblox avatar');
  }

  async add_account_from_cookie(cookie, group_id) {
    return this.desktopOperationUnavailable('Adding an authenticated Roblox account');
  }

  async start_manual_browser_login(group_id) {
    return this.desktopOperationUnavailable('Opening the Roblox sign-in browser');
  }

  async poll_manual_browser_login(operation_id) {
    return this.desktopOperationUnavailable('Checking Roblox browser sign-in');
  }
}

function nativeApi() {
  const api = window.pywebview && window.pywebview.api;
  return api && typeof api.bootstrap === 'function' ? api : null;
}

function waitForPywebview(timeout) {
  const immediatelyAvailable = nativeApi();
  if (immediatelyAvailable) return Promise.resolve({ api: immediatelyAvailable, nativeHostSeen: true });
  return new Promise(function (resolve) {
    let finished = false;
    let nativeHostSeen = Boolean(window.pywebview);
    let interval = null;
    let timer = null;
    const onReady = function () { check(); };

    function done(api) {
      if (finished) return;
      finished = true;
      if (interval !== null) window.clearInterval(interval);
      if (timer !== null) window.clearTimeout(timer);
      window.removeEventListener('pywebviewready', onReady);
      resolve({ api: api || null, nativeHostSeen: nativeHostSeen || Boolean(window.pywebview) });
    }

    function check() {
      nativeHostSeen = nativeHostSeen || Boolean(window.pywebview);
      const api = nativeApi();
      if (api) done(api);
    }

    window.addEventListener('pywebviewready', onReady);
    interval = window.setInterval(check, 50);
    timer = window.setTimeout(function () { done(nativeApi()); }, timeout);
    check();
  });
}

export class Bridge {
  constructor(api, preview) {
    this.api = api;
    this.preview = preview;
    this.mode = api ? 'desktop' : 'preview';
  }

  static async connect() {
    // A pywebview host can inject its API after the module has loaded.  Do not
    // silently turn a desktop workspace into a local browser preview during
    // that short startup window: preview data is useful for development, but
    // must never masquerade as the user's persisted desktop data.
    const connection = await waitForPywebview(5000);
    if (connection.api) return new Bridge(connection.api, new PreviewBridge());
    if (connection.nativeHostSeen) {
      throw new Error('The Astro Account Manager desktop bridge did not start. Restart the application; no accounts were modified.');
    }
    return new Bridge(null, new PreviewBridge());
  }

  async call(method) {
    const args = Array.prototype.slice.call(arguments, 1);
    if (!CONTRACT_METHODS.includes(method)) throw new Error('Unknown bridge method: ' + method);
    const target = this.api && typeof this.api[method] === 'function' ? this.api : this.preview;
    try {
      return await target[method].apply(target, args);
    } catch (error) {
      const message = error && error.message ? error.message : String(error || 'Unknown bridge error');
      throw new Error(message);
    }
  }
}

export { CONTRACT_METHODS };
