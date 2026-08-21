import { Bridge } from './bridge.js';

const $ = function (selector, root) { return (root || document).querySelector(selector); };
const $$ = function (selector, root) { return Array.from((root || document).querySelectorAll(selector)); };
const ACCENT_HEX = { violet: '#9c85ff', mint: '#47cfa1', coral: '#f58283', blue: '#73a9ff', amber: '#efb55d' };

function accentToken(value) {
  const accent = String(value || '').toLowerCase();
  const matches = Object.keys(ACCENT_HEX).find(function (key) { return ACCENT_HEX[key] === accent; });
  if (matches) return matches;
  if (Object.prototype.hasOwnProperty.call(ACCENT_HEX, accent)) return accent;
  return accent.startsWith('#') ? 'custom' : 'violet';
}

function hexToRgb(value) {
  const hex = String(value || '').replace('#', '');
  if (!/^[0-9a-f]{6}$/i.test(hex)) return null;
  return parseInt(hex.slice(0, 2), 16) + ', ' + parseInt(hex.slice(2, 4), 16) + ', ' + parseInt(hex.slice(4, 6), 16);
}

function escapeHtml(value) {
  return String(value === undefined || value === null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function unwrap(value) {
  if (value && typeof value === 'object' && Object.prototype.hasOwnProperty.call(value, 'data')) return value.data;
  return value;
}

function asArray(value) {
  const content = unwrap(value);
  if (Array.isArray(content)) return content;
  if (content && Array.isArray(content.items)) return content.items;
  if (content && Array.isArray(content.results)) return content.results;
  return [];
}

function initials(value) {
  const words = String(value || '?').trim().split(/[\s_]+/).filter(Boolean);
  return words.slice(0, 2).map(function (word) { return word[0]; }).join('').toUpperCase() || '?';
}

function relativeTime(value) {
  if (!value) return 'Not used yet';
  const delta = Math.max(0, Date.now() - new Date(value).getTime());
  const minute = 60000;
  const hour = minute * 60;
  const day = hour * 24;
  if (delta < minute) return 'Just now';
  if (delta < hour) return Math.floor(delta / minute) + 'm ago';
  if (delta < day) return Math.floor(delta / hour) + 'h ago';
  if (delta < day * 7) return Math.floor(delta / day) + 'd ago';
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(new Date(value));
}

function formatNumber(value) {
  return new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(Number(value || 0));
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return '—';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function statusText(value) {
  return { ready: 'Ready', in_game: 'In game', running: 'Running', starting: 'Launching', launching: 'Launching', offline: 'Offline', orphaned: 'Unassociated', unknown: 'Unknown', terminating: 'Closing', exited: 'Exited', crashed: 'Crashed', terminated: 'Closed', healthy: 'Healthy', degraded: 'Limited', error: 'Issue', farming: 'Farming', macro_paused: 'Macro paused', afk: 'In game, unattended' }[value] || String(value || 'Unknown');
}

// Icons are pure markup and one render calls this helper dozens of times.
// Rebuilding the same SVG string on every poll was pure waste.
const ICON_CACHE = new Map();

function icon(name, title) {
  const cacheKey = String(name) + '\u0000' + (title || '');
  const cached = ICON_CACHE.get(cacheKey);
  if (cached !== undefined) return cached;
  const label = title ? ' aria-label="' + escapeHtml(title) + '" role="img"' : ' aria-hidden="true"';
  const open = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"' + label + '>';
  const paths = {
    orbit: '<path d="M12 3.2c4.86 0 8.8 3.94 8.8 8.8s-3.94 8.8-8.8 8.8S3.2 16.86 3.2 12 7.14 3.2 12 3.2Z"/><path d="M7.4 16.6c2.3 1.5 6.1 1.4 8.7-.4 2.7-1.8 3.4-4.8 1.5-6.7-1.8-1.9-5.5-2.1-8.2-.5-2.7 1.6-3.5 4.7-1.9 7.6Z"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/>',
    grid: '<rect x="4" y="4" width="6" height="6" rx="1"/><rect x="14" y="4" width="6" height="6" rx="1"/><rect x="4" y="14" width="6" height="6" rx="1"/><rect x="14" y="14" width="6" height="6" rx="1"/>',
    users: '<path d="M16 20v-1.4a4.6 4.6 0 0 0-4.6-4.6H8.6A4.6 4.6 0 0 0 4 18.6V20"/><circle cx="10" cy="7.5" r="3.5"/><path d="M16.6 4.3a3.5 3.5 0 0 1 0 6.5M20 20v-1.4a4.6 4.6 0 0 0-3.1-4.35"/>',
    gamepad: '<path d="M7.3 8.5h9.4c2.2 0 3.1 1.5 3.8 4.3l.4 1.8c.45 2.1-.55 3.5-2.15 3.5-1.15 0-1.85-.7-2.75-1.8H7.95c-.9 1.1-1.6 1.8-2.75 1.8-1.6 0-2.6-1.4-2.15-3.5l.4-1.8c.7-2.8 1.65-4.3 3.85-4.3Z"/><path d="M7.2 12v3M5.7 13.5h3M16.2 12.5h.01M18.6 14.2h.01"/>',
    monitor: '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.4 2.4-.06-.06a1.7 1.7 0 0 0-1.88-.34 1.7 1.7 0 0 0-1.04 1.56v.1h-3.4v-.1a1.7 1.7 0 0 0-1.04-1.56 1.7 1.7 0 0 0-1.88.34l-.06.06-2.4-2.4.06-.06A1.7 1.7 0 0 0 6.04 15 1.7 1.7 0 0 0 4.5 13.96h-.1v-3.4h.1A1.7 1.7 0 0 0 6.04 9a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.4-2.4.06.06A1.7 1.7 0 0 0 9.98 5.06 1.7 1.7 0 0 0 11.02 3.5v-.1h3.4v.1a1.7 1.7 0 0 0 1.04 1.56 1.7 1.7 0 0 0 1.88-.34l.06-.06 2.4 2.4-.06.06A1.7 1.7 0 0 0 19.4 9a1.7 1.7 0 0 0 1.56 1.04h.1v3.4h-.1A1.7 1.7 0 0 0 19.4 15Z"/>',
    search: '<circle cx="10.8" cy="10.8" r="6.3"/><path d="m16 16 4.3 4.3"/>',
    bell: '<path d="M18 9.7a6 6 0 0 0-12 0c0 7-2.4 7-2.4 8.8h16.8C20.4 16.7 18 16.7 18 9.7ZM10 21h4"/>',
    sun: '<circle cx="12" cy="12" r="3.5"/><path d="M12 2v2M12 20v2M4.93 4.93l1.42 1.42M17.65 17.65l1.42 1.42M2 12h2M20 12h2M4.93 19.07l1.42-1.42M17.65 6.35l1.42-1.42"/>',
    moon: '<path d="M20.5 14.4A8.5 8.5 0 0 1 9.6 3.5 8.5 8.5 0 1 0 20.5 14.4Z"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    chevronDown: '<path d="m6 9 6 6 6-6"/>',
    chevronRight: '<path d="m9 18 6-6-6-6"/>',
    play: '<path d="m8 5 11 7-11 7V5Z" fill="currentColor" stroke="none"/>',
    star: '<path d="m12 3 2.78 5.63 6.22.9-4.5 4.39 1.06 6.2L12 17.2l-5.56 2.92 1.06-6.2L3 9.53l6.22-.9L12 3Z"/>',
    dots: '<circle cx="5" cy="12" r="1" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none"/><circle cx="19" cy="12" r="1" fill="currentColor" stroke="none"/>',
    check: '<path d="m5 12 4.2 4.2L19 6.7"/>',
    x: '<path d="m6 6 12 12M18 6 6 18"/>',
    edit: '<path d="M12 20h8"/><path d="M16.2 3.3a2.1 2.1 0 0 1 3 3L9.4 16.1 5 17l.9-4.4 10.3-9.3Z"/>',
    trash: '<path d="M4 7h16M10 11v5M14 11v5M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    refresh: '<path d="M20 11a8.1 8.1 0 0 0-14.4-4.9L4 8"/><path d="M4 4v4h4M4 13a8.1 8.1 0 0 0 14.4 4.9L20 16"/><path d="M20 20v-4h-4"/>',
    folder: '<path d="M3 6.5A2.5 2.5 0 0 1 5.5 4H10l2 2.5h6.5A2.5 2.5 0 0 1 21 9v8.5a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5v-11Z"/>',
    rocket: '<path d="M13.5 4.2C16.7 2.8 19.8 3 20.8 3.2c.2 1 .4 4.1-1 7.3-1.3 3-4.3 5.1-7.3 5.9l-4.8-4.8c.8-3 2.8-6 5.8-7.4Z"/><path d="M7.7 11.6 4 12l-1 3 3.2-.6M12.4 16.3 12 20l3 1 1.2-3.6"/><circle cx="15.5" cy="8.4" r="1.5"/>',
    clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3.5 2"/>',
    activity: '<path d="M3 12h4l2-6 4 12 2-6h6"/>',
    database: '<ellipse cx="12" cy="5" rx="7" ry="3"/><path d="M5 5v7c0 1.66 3.13 3 7 3s7-1.34 7-3V5M5 12v7c0 1.66 3.13 3 7 3s7-1.34 7-3v-7"/>',
    shield: '<path d="M12 3.5 19 6v5.5c0 4.2-2.7 7.55-7 9-4.3-1.45-7-4.8-7-9V6l7-2.5Z"/><path d="m8.7 12 2.1 2.1 4.5-4.6"/>',
    command: '<path d="M9 9a3 3 0 1 1-3-3c1.2 0 2.2.7 2.7 1.7h6.6A3 3 0 1 1 18 9c0-1.2-.7-2.2-1.7-2.7v11.4A3 3 0 1 1 15 15c0 1.2.7 2.2 1.7 2.7H8.3A3 3 0 1 1 6 15c1.2 0 2.2.7 2.7 1.7V8.3A3 3 0 0 1 9 9Z"/>',
    filter: '<path d="M4 5h16M7 12h10M10 19h4"/>',
    list: '<path d="M8 6h12M8 12h12M8 18h12"/><path d="M4 6h.01M4 12h.01M4 18h.01"/>',
    layout: '<rect x="4" y="4" width="6" height="7" rx="1"/><rect x="14" y="4" width="6" height="7" rx="1"/><rect x="4" y="15" width="6" height="5" rx="1"/><rect x="14" y="15" width="6" height="5" rx="1"/>',
    circlePlay: '<circle cx="12" cy="12" r="8.5"/><path d="m10 8.5 5 3.5-5 3.5v-7Z" fill="currentColor" stroke="none"/>',
    copy: '<rect x="9" y="9" width="10" height="10" rx="1.5"/><path d="M15 9V6.5A1.5 1.5 0 0 0 13.5 5h-8A1.5 1.5 0 0 0 4 6.5v8A1.5 1.5 0 0 0 5.5 16H9"/>',
    alert: '<path d="M10.4 4.1 2.8 17.3A1.8 1.8 0 0 0 4.4 20h15.2a1.8 1.8 0 0 0 1.6-2.7L13.6 4.1a1.8 1.8 0 0 0-3.2 0Z"/><path d="M12 9v4M12 16.5h.01"/>',
    info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5M12 8h.01"/>',
    upload: '<path d="M12 16V4M7.5 8.5 12 4l4.5 4.5"/><path d="M5 14.5V19h14v-4.5"/>',
    download: '<path d="M12 4v12M7.5 11.5 12 16l4.5-4.5"/><path d="M5 19.5h14"/>',
    sliders: '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="2" fill="var(--surface-2)"/><circle cx="15" cy="17" r="2" fill="var(--surface-2)"/>',
    logout: '<path d="M10 5H5v14h5M14 8l4 4-4 4M18 12H9"/>',
    cube: '<path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Z"/><path d="m4 7.5 8 4.5 8-4.5M12 12v9"/>',
    code: '<path d="m16 18 6-6-6-6M8 6l-6 6 6 6"/>',
    terminal: '<path d="m5 7 5 5-5 5M13 19h6"/><rect x="2" y="3" width="20" height="18" rx="2"/>',
    crosshair: '<circle cx="12" cy="12" r="8"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/>',
    globe: '<circle cx="12" cy="12" r="8.5"/><path d="M12 3.5c-3 3-4 6-4 8.5s1 5.5 4 8.5M12 3.5c3 3 4 6 4 8.5s-1 5.5-4 8.5M3.5 12h17"/>'
  };
  const markup = open + (paths[name] || paths.info) + '</svg>';
  ICON_CACHE.set(cacheKey, markup);
  return markup;
}

function publicAvatarUrl(value) {
  try {
    const url = new URL(String(value || ''));
    const host = url.hostname.toLowerCase();
    return url.protocol === 'https:' && (host === 'rbxcdn.com' || host.endsWith('.rbxcdn.com')) ? url.href : '';
  } catch (_) {
    return '';
  }
}

function avatar(account, size) {
  const label = escapeHtml(account.display_name || account.username || '?');
  const image = publicAvatarUrl(account.avatar_url);
  const content = image ? '<img src="' + escapeHtml(image) + '" alt="" loading="lazy" referrerpolicy="no-referrer" />' : '<span>' + escapeHtml(initials(account.display_name || account.username)) + '</span>';
  return '<span class="avatar ' + escapeHtml(account.avatar_color || 'neutral') + (size ? ' avatar-' + size : '') + '" aria-label="' + label + '">' + content + '</span>';
}

/* Actions belonging to the hidden Nexus surface.  They stay implemented so the
   feature can be restored, but handleClick ignores them while it is hidden. */
const NEXUS_ACTIONS = new Set([
  'open-nexus-panel', 'open-send-nexus', 'start-nexus-server', 'stop-nexus-server',
  'copy-nexus-script', 'refresh-nexus-status', 'nexus-execute', 'nexus-clear-editor',
  'nexus-clear-log', 'nexus-target-client', 'nexus-quick'
]);

class OrbitApp {
  constructor() {
    this.root = $('#app');
    this.overlayRoot = $('#overlay-root');
    this.toastRoot = $('#toast-root');
    this.bridge = null;
    this.oauthPollTimer = null;
    this.oauthPollInFlight = false;
    this.state = {
      route: 'dashboard', accounts: [], groups: [], games: [], instances: [], activity: [], notifications: [],
      diagnostics: { services: [], logs: [], status: 'healthy' }, settings: {},
      macros: [], macroRuns: [], macroEditorMode: 'blocks',
      fleet: { groupId: '', plan: null, resources: null }, dashboard: null,
      fleetTab: 'stats', fleetData: {}, fleetWindowDays: null,
      fleetFilters: { query: '', tags: [], status: '', placeId: '' }, fleetStudio: { macroId: '', accountId: '' },
      lastRenderHtml: null, lastSidebarHtml: null, lastTopbarHtml: null, lastPageHtml: null, lastOverlayHtml: null,
      macroDraftBlocks: [{ type: 'wait', milliseconds: 1000 }, { type: 'key_press', key: 'W', milliseconds: 80 }], macroDraftSource: '',
      macroDraftName: '', macroDraftDescription: '', macroDraftAccountId: '',
      discordPresence: { enabled: false, connected: false }, updater: {}, robloxBackground: { running: false, count: 0, processes: [] },
      instanceMonitor: { instances: [], events: [], pending_restarts: [], last_scan_complete: null, termination_enabled: false },
      multiInstance: { supported: false, enabled: false, configured: false, restart_required: false },
      robloxSettings: { loaded: false, available: false, reason: '', basic: {}, advanced: [], profiles: [], groups: [] },
      windowsStartup: { loaded: false, error: false, available: false, supported: null, accessible: null, registered: false, enabled: false, needs_repair: false, configured: false, reason: '' },
      accountView: 'cards', accountQuery: '', accountStatus: 'all', selected: new Set(),
      publicRefreshErrors: {}, draggedAccountId: null,
      launchingAccounts: new Set(), batchPollTimer: null, runtimePollTimer: null, runtimePollInFlight: false,
      gameQuery: '', gameId: null, gameDetail: null, servers: [], serversLoading: false, gamesLoading: false,
      serverFilters: { sort: 'score', min_free_slots: 1, avoid_previous: false },
      settingsTab: 'general', modal: null, notificationsOpen: false, paletteOpen: false, paletteQuery: '',
      features: { nexus: false },
      nexusExecutorCode: "-- Write your Lua script here\nprint('Hello from Nexus!')\n",
      nexusExecutorTarget: 'all', nexusExecutorLog: [],
      mode: 'preview', loading: true
    };
    this.handleClick = this.handleClick.bind(this);
    this.handleSubmit = this.handleSubmit.bind(this);
    this.handleInput = this.handleInput.bind(this);
    this.handleChange = this.handleChange.bind(this);
    this.handleKeydown = this.handleKeydown.bind(this);
  }

  async init() {
    this.renderLoading();
    document.addEventListener('click', this.handleClick);
    document.addEventListener('submit', this.handleSubmit);
    document.addEventListener('input', this.handleInput);
    document.addEventListener('change', this.handleChange);
    document.addEventListener('keydown', this.handleKeydown);
    document.addEventListener('dragstart', this.handleDragStart.bind(this));
    document.addEventListener('dragover', this.handleDragOver.bind(this));
    document.addEventListener('drop', this.handleDrop.bind(this));
    document.addEventListener('dragend', this.handleDragEnd.bind(this));
    try {
      this.bridge = await Bridge.connect();
      const boot = unwrap(await this.bridge.call('bootstrap')) || {};
      this.applyBootstrap(boot);
      this.state.mode = this.bridge.mode;
      this.state.loading = false;
      this.applyTheme();
      this.render();
      this.startRuntimePolling();
      this.maybeWarnRunningRoblox();
    } catch (error) {
      this.state.loading = false;
      this.render();
      this.toast('error', 'Could not initialize the workspace', error.message);
    }
  }

  applyBootstrap(boot) {
    this.state.accounts = asArray(boot.accounts);
    this.state.groups = asArray(boot.groups);
    this.state.games = asArray(boot.games);
    this.state.instances = asArray(boot.instances);
    this.state.activity = asArray(boot.activity);
    this.state.notifications = asArray(boot.notifications);
    const settings = Object.assign({ theme: 'dark', accent: 'violet', density: 'comfortable', reduce_motion: false }, unwrap(boot.settings) || {});
    settings.accent_raw = settings.accent;
    settings.accent = accentToken(settings.accent);
    this.state.settings = settings;
    this.state.hideUsernames = Boolean(settings.privacy_mode || settings.categories && settings.categories.appearance && settings.categories.appearance.privacy_mode);
    this.state.multiInstance = Object.assign(
      { supported: false, enabled: false, configured: Boolean(settings.allow_multiple_launches), restart_required: false },
      unwrap(boot.multi_instance) || {}
    );
    this.state.instanceMonitor = {
      instances: this.state.instances,
      events: [],
      pending_restarts: [],
      last_scan_complete: null,
      termination_enabled: Boolean(settings.watcher_termination_enabled)
    };
    this.state.diagnostics = unwrap(boot.diagnostics) || this.state.diagnostics;
    this.state.macros = asArray(boot.macros);
    this.state.macroRuns = asArray(boot.macro_runs);
    this.state.discordPresence = unwrap(boot.discord_presence) || this.state.discordPresence;
    this.state.updater = unwrap(boot.updater) || this.state.updater;
    this.state.robloxBackground = unwrap(boot.roblox_background) || this.state.robloxBackground;
    this.state.features = Object.assign({ nexus: false }, unwrap(boot.features) || {});
    this.state.nexus = unwrap(boot.nexus) || { running: false, host: '127.0.0.1', port: 5242, url: 'ws://127.0.0.1:5242/Nexus', accounts: [] };
    if (!this.state.gameId && this.state.games[0]) this.state.gameId = String(this.state.games[0].place_id);
  }

  oauthSettings() {
    const categories = this.state.settings && this.state.settings.categories;
    const configured = categories && typeof categories.oauth === 'object' ? categories.oauth : {};
    return Object.assign({
      enabled: false,
      client_id: '',
      redirect_uri: 'http://127.0.0.1:8989/oauth/callback',
      callback_timeout_seconds: 300
    }, configured || {});
  }

  isOAuthConfigured() {
    const oauth = this.oauthSettings();
    return this.state.mode === 'desktop' && Boolean(oauth.enabled) && /^\d+$/.test(String(oauth.client_id || '').trim()) && Boolean(String(oauth.redirect_uri || '').trim());
  }

  oauthStateLabel(account) {
    return account && account.oauth_connected ? 'Open Cloud OAuth linked' : 'Local profile';
  }

  renderOAuthAccountState(account) {
    const connected = Boolean(account && account.oauth_connected);
    return '<span class="oauth-account-status ' + (connected ? 'is-connected' : '') + '">' + icon(connected ? 'shield' : 'info') + escapeHtml(this.oauthStateLabel(account)) + '</span>';
  }

  publicUserId(account) {
    const userId = String(account && account.user_id !== undefined && account.user_id !== null ? account.user_id : '').trim();
    return /^[1-9][0-9]*$/.test(userId) ? userId : '';
  }

  publicAccountMetadata(account) {
    const metadata = account && account.metadata && typeof account.metadata === 'object' ? account.metadata : {};
    return {
      profile: metadata.public_profile && typeof metadata.public_profile === 'object' ? metadata.public_profile : null,
      presence: metadata.public_presence && typeof metadata.public_presence === 'object' ? metadata.public_presence : null
    };
  }

  publicPresenceLabel(presence) {
    const state = String(presence && presence.state || '').toLowerCase();
    return { offline: 'Offline', online: 'Online', in_game: 'In game', in_studio: 'In Studio', unavailable: 'Unavailable' }[state] || (presence ? 'Unknown' : 'Not refreshed');
  }

  publicPresenceDetail(presence) {
    if (!presence) return 'No public presence snapshot has been saved yet.';
    if (String(presence.state || '').toLowerCase() === 'unavailable') return 'Roblox did not return a current public presence for this account.';
    const location = String(presence.last_location || '').trim();
    const refreshed = presence.refreshed_at ? 'Snapshot ' + relativeTime(presence.refreshed_at) : 'Public snapshot saved locally.';
    return location ? location + ' · ' + refreshed : refreshed;
  }

  renderOAuthAccountActions(account, includePublic) {
    const publicActions = includePublic ? this.renderPublicAccountActions(account, true) : '';
    const watcher = this.renderAccountWatcherAction(account);
    if (!account || !account.oauth_connected) return publicActions + watcher;
    const id = escapeHtml(account.id);
    const name = escapeHtml(account.display_name || account.username);
    return '<button class="icon-button" type="button" data-action="refresh-oauth-account" data-id="' + id + '" aria-label="Refresh Roblox OAuth for ' + name + '" title="Refresh Roblox OAuth">' + icon('refresh') + '</button><button class="icon-button" type="button" data-action="open-disconnect-oauth" data-id="' + id + '" aria-label="Disconnect Roblox OAuth for ' + name + '" title="Disconnect Roblox OAuth">' + icon('logout') + '</button>' + publicActions + watcher;
  }

  renderPublicAccountActions(account, compact) {
    const userId = this.publicUserId(account);
    if (!account || !userId) return '';
    if (this.state.mode !== 'desktop') return compact
      ? '<span class="public-preview-unavailable" title="Preview never simulates public Roblox data">' + icon('info') + '</span>'
      : '<p class="public-preview-unavailable">' + icon('info') + ' Public Roblox data is unavailable in Preview and is never simulated.</p>';
    const id = escapeHtml(account.id);
    const name = escapeHtml(account.display_name || account.username);
    if (compact) return '<button class="icon-button" type="button" data-action="refresh-public-profile" data-id="' + id + '" aria-label="Refresh public profile for ' + name + '" title="Refresh public profile">' + icon('refresh') + '</button><button class="icon-button" type="button" data-action="refresh-public-presence" data-id="' + id + '" aria-label="Refresh public presence for ' + name + '" title="Refresh public presence">' + icon('activity') + '</button>';
    return '<div class="public-account-actions"><button class="button button-sm" type="button" data-action="refresh-public-profile" data-id="' + id + '">' + icon('refresh') + ' Refresh public profile</button><button class="button button-sm" type="button" data-action="refresh-public-presence" data-id="' + id + '">' + icon('activity') + ' Refresh presence</button></div>';
  }

  renderPublicAccountSnapshot(account, compact) {
    const hidden = Boolean(this.state.hideUsernames);
    const userId = this.publicUserId(account);
    if (!userId) return compact ? '' : '';
    const data = this.publicAccountMetadata(account);
    const profile = data.profile;
    const presence = data.presence;
    const preview = this.state.mode !== 'desktop';
    const errors = (this.state.publicRefreshErrors || {})[account.id] || {};
    const identity = hidden ? 'Account #' + String(this.state.accounts.indexOf(account) + 1).padStart(2, '0') : (!preview && profile && (profile.display_name || profile.username) || account.display_name || account.username);
    const username = hidden ? '••••••••' : (!preview && profile && profile.username || account.username);
    const displayUserId = hidden ? '**********' : userId;
    const profileState = preview ? 'Public profile unavailable in Preview' : profile ? (profile.refreshed_at ? 'Public profile · ' + relativeTime(profile.refreshed_at) : 'Public profile saved') : 'Public profile not refreshed';
    const verified = !preview && profile && profile.has_verified_badge ? '<span class="public-verified">' + icon('shield') + ' Verified</span>' : '';
    const presenceState = preview ? 'preview-unavailable' : String(presence && presence.state || 'not-refreshed').toLowerCase();
    const profileError = errors.profile ? '<p class="public-account-error">Profile: ' + escapeHtml(errors.profile) + '</p>' : '';
    const presenceError = errors.presence ? '<p class="public-account-error">Presence: ' + escapeHtml(errors.presence) + '</p>' : '';
    if (compact) return '<div class="public-account-table-snapshot"><strong>' + escapeHtml(identity) + verified + '</strong><small>@' + escapeHtml(username) + ' · ID ' + escapeHtml(displayUserId) + '</small><span class="public-presence-state ' + escapeHtml(presenceState) + '">' + icon('activity') + escapeHtml(preview ? 'Preview unavailable' : this.publicPresenceLabel(presence)) + '</span></div>';
    const previewDetail = preview ? 'Preview never simulates public Roblox profile or presence data.' : this.publicPresenceDetail(presence);
    return '<section class="account-public-snapshot"><div class="public-identity"><span class="public-identity-label">Roblox public identity</span><strong>' + escapeHtml(identity) + verified + '</strong><small>@' + escapeHtml(username) + ' · ID ' + escapeHtml(displayUserId) + '</small><em>' + escapeHtml(profileState) + '</em></div><div class="public-presence-snapshot"><span class="public-presence-state ' + escapeHtml(presenceState) + '">' + icon('activity') + escapeHtml(preview ? 'Preview unavailable' : this.publicPresenceLabel(presence)) + '</span><small>' + escapeHtml(previewDetail) + '</small></div>' + profileError + presenceError + this.renderPublicAccountActions(account, false) + '</section>';
  }

  renderAccountWatcherAction(account) {
    if (!account || !account.id) return '';
    const id = escapeHtml(account.id);
    const name = escapeHtml(account.display_name || account.username);
    return '<button class="icon-button" type="button" data-action="open-account-watcher" data-id="' + id + '" aria-label="Configure watcher rule for ' + name + '" title="Configure watcher rule">' + icon('monitor') + '</button>';
  }

  applyTheme() {
    const settings = this.state.settings;
    document.documentElement.dataset.theme = settings.theme === 'light' ? 'light' : 'dark';
    document.documentElement.dataset.accent = settings.accent || 'violet';
    document.documentElement.dataset.density = settings.density || 'comfortable';
    document.documentElement.dataset.privacy = this.state.hideUsernames ? 'on' : 'off';
    document.documentElement.style.colorScheme = settings.theme === 'light' ? 'light' : 'dark';
    if (settings.accent === 'custom' && typeof settings.accent_raw === 'string') {
      const rgb = hexToRgb(settings.accent_raw);
      document.documentElement.style.setProperty('--accent', settings.accent_raw);
      if (rgb) document.documentElement.style.setProperty('--accent-rgb', rgb);
    } else {
      document.documentElement.style.removeProperty('--accent');
      document.documentElement.style.removeProperty('--accent-rgb');
    }
  }

  async resync() {
    const boot = unwrap(await this.bridge.call('bootstrap')) || {};
    this.applyBootstrap(boot);
    this.applyTheme();
  }

  applyInstanceMonitor(payload) {
    const monitor = unwrap(payload) || {};
    if (Object.prototype.hasOwnProperty.call(monitor, 'accounts')) this.state.accounts = asArray(monitor.accounts);
    const hasInstances = Object.prototype.hasOwnProperty.call(monitor, 'instances');
    const instances = hasInstances ? asArray(monitor.instances) : this.state.instances;
    this.state.instances = instances;
    this.state.instanceMonitor = {
      instances: instances,
      events: asArray(monitor.events),
      pending_restarts: asArray(monitor.pending_restarts),
      last_scan_complete: typeof monitor.last_scan_complete === 'boolean' ? monitor.last_scan_complete : null,
      termination_enabled: Boolean(monitor.termination_enabled)
    };
  }

  applyDashboard(payload) {
    const data = unwrap(payload) || {};
    // Accounts, windows, macro runs and the resource verdict all come from the
    // same join, so the dashboard can no longer show an offline account next
    // to a running macro.
    if (Object.prototype.hasOwnProperty.call(data, 'accounts')) this.state.accounts = asArray(data.accounts);
    if (Object.prototype.hasOwnProperty.call(data, 'instances')) {
      this.state.instances = asArray(data.instances);
      this.state.instanceMonitor = Object.assign({}, this.state.instanceMonitor, { instances: this.state.instances });
    }
    if (Object.prototype.hasOwnProperty.call(data, 'groups')) this.state.groups = asArray(data.groups);
    if (Object.prototype.hasOwnProperty.call(data, 'macro_runs')) this.state.macroRuns = asArray(data.macro_runs);
    if (data.resources) this.state.fleet.resources = data.resources;
    this.state.dashboard = data;
  }

  async loadInstanceMonitor(announce) {
    try {
      const monitor = unwrap(await this.bridge.call('get_instance_monitor')) || {};
      this.applyInstanceMonitor(monitor);
      if (this.state.route === 'instances') this.render();
      if (announce) this.toast('success', 'Instance monitor updated', this.state.instances.length + ' observed process' + (this.state.instances.length === 1 ? '.' : 'es.'));
      return monitor;
    } catch (error) {
      if (announce) this.toast('error', 'Could not load the instance monitor', error.message || 'The local monitor did not return a status.');
      return null;
    }
  }

  async startNexusServer() {
    try {
      const status = unwrap(await this.bridge.call('start_nexus_server')) || {};
      this.state.nexus = status;
      this.render();
      this.toast('success', 'Nexus Server Started', 'Listening on ' + (status.url || 'ws://127.0.0.1:5242/Nexus'));
    } catch (error) {
      this.toast('error', 'Nexus Error', error.message);
    }
  }

  async stopNexusServer() {
    try {
      const status = unwrap(await this.bridge.call('stop_nexus_server')) || {};
      this.state.nexus = status;
      this.render();
      this.toast('info', 'Nexus Server Stopped');
    } catch (error) {
      this.toast('error', 'Nexus Error', error.message);
    }
  }

  async sendNexusCommand(targetAccount, commandName, payload) {
    try {
      await this.bridge.call('send_nexus_command', targetAccount, commandName, payload);
      this.toast('success', 'Nexus Command Sent', '\'' + commandName + '\' to ' + targetAccount);
      const status = unwrap(await this.bridge.call('get_nexus_status')) || {};
      this.state.nexus = status;
      this.render();
    } catch (error) {
      this.toast('error', 'Nexus Send Error', error.message);
    }
  }

  async copyNexusLuaScript() {
    try {
      const script = await this.bridge.call('get_nexus_lua_script');
      await this.writeClipboard(script);
      this.toast('success', 'Nexus Lua Script Copied', 'Paste this script into your Roblox client executor.');
    } catch (error) {
      this.toast('error', 'Lua Script Error', error.message);
    }
  }

  /* --- Nexus Executor methods --- */
  async nexusExecute() {
    const code = this.state.nexusExecutorCode || '';
    const target = this.state.nexusExecutorTarget || 'all';
    if (!code.trim()) { this.toast('warning', 'Empty script', 'Write or select a Lua script first.'); return; }
    const now = new Date();
    const timeStr = String(now.getHours()).padStart(2, '0') + ':' + String(now.getMinutes()).padStart(2, '0') + ':' + String(now.getSeconds()).padStart(2, '0');
    try {
      await this.bridge.call('send_nexus_command', target, 'execute', code);
      this.nexusAddLog({ time: timeStr, target: target, level: 'success', message: 'Script sent (' + code.length + ' chars)' });
      this.toast('success', 'Script executed', 'Sent to ' + target);
    } catch (error) {
      this.nexusAddLog({ time: timeStr, target: target, level: 'error', message: 'Failed: ' + (error.message || 'Unknown error') });
      this.toast('error', 'Execution failed', error.message);
    }
    const status = await this.bridge.call('get_nexus_status');
    this.state.nexus = unwrap(status) || this.state.nexus;
    this.render();
    this.nexusSyncLineNumbers();
  }

  async refreshNexusStatus() {
    try {
      const status = unwrap(await this.bridge.call('get_nexus_status')) || {};
      this.state.nexus = status;
      this.render();
      this.nexusSyncLineNumbers();
    } catch (error) {
      this.toast('error', 'Nexus status error', error.message);
    }
  }

  nexusAddLog(entry) {
    if (!Array.isArray(this.state.nexusExecutorLog)) this.state.nexusExecutorLog = [];
    this.state.nexusExecutorLog.push(entry);
    if (this.state.nexusExecutorLog.length > 200) this.state.nexusExecutorLog = this.state.nexusExecutorLog.slice(-200);
  }

  nexusSyncLineNumbers() {
    const editor = document.getElementById('nexus-code-editor');
    const lineNums = document.getElementById('nexus-line-numbers');
    if (!editor || !lineNums) return;
    const lines = (editor.value || '').split('\n');
    lineNums.innerHTML = lines.map(function (_, i) { return '\u003cspan\u003e' + (i + 1) + '\u003c/span\u003e'; }).join('');
    lineNums.scrollTop = editor.scrollTop;
  }

  windowsStartupStatus() {
    return Object.assign({ loaded: false, error: false, available: false, supported: null, accessible: null, registered: false, enabled: false, needs_repair: false, configured: false, reason: '' }, this.state.windowsStartup || {});
  }

  applyWindowsStartupStatus(payload) {
    const status = unwrap(payload) || {};
    this.state.windowsStartup = Object.assign({ loaded: true, error: false, available: false, supported: false, accessible: false, registered: false, enabled: false, needs_repair: false, configured: false, reason: '' }, status, { loaded: true, error: false });
    return this.state.windowsStartup;
  }

  async loadWindowsStartupStatus(announce) {
    if (this.state.mode !== 'desktop') {
      this.state.windowsStartup = { loaded: true, error: false, available: false, supported: false, accessible: false, registered: false, enabled: false, needs_repair: false, configured: false, reason: 'Preview mode does not inspect or simulate the Windows startup registration.' };
      if (this.state.route === 'settings' && this.state.settingsTab === 'general') this.render();
      return this.state.windowsStartup;
    }
    try {
      const status = this.applyWindowsStartupStatus(await this.bridge.call('get_windows_startup_status'));
      if (this.state.route === 'settings' && this.state.settingsTab === 'general') this.render();
      if (announce) this.toast('success', 'Windows startup status refreshed', status.enabled ? 'Astro Account Manager is enabled for the current Windows user.' : 'Astro Account Manager is not enabled at Windows sign-in.');
      return status;
    } catch (error) {
      this.state.windowsStartup = { loaded: true, error: true, available: false, supported: null, accessible: null, registered: false, enabled: false, needs_repair: false, configured: false, reason: error.message || 'The desktop bridge could not inspect Windows startup.' };
      if (this.state.route === 'settings' && this.state.settingsTab === 'general') this.render();
      if (announce) this.toast('error', 'Could not check Windows startup', this.state.windowsStartup.reason);
      return null;
    }
  }

  async loadRobloxSettings(announce) {
    if (this.state.mode !== 'desktop') {
      this.state.robloxSettings = { loaded: true, available: false, reason: 'Preview mode never reads or edits Roblox installation files.', basic: {}, advanced: [], profiles: [], groups: [] };
      if (this.state.route === 'settings' && this.state.settingsTab === 'roblox') this.render();
      return null;
    }
    try {
      const payload = unwrap(await this.bridge.call('get_roblox_settings_manager', '')) || {};
      this.state.robloxSettings = Object.assign({ loaded: true, basic: {}, advanced: [], profiles: [], groups: [] }, payload, { loaded: true });
      if (this.state.route === 'settings' && this.state.settingsTab === 'roblox') this.render();
      if (announce) this.toast('success', 'Roblox settings refreshed', asArray(payload.advanced).length + ' scalar setting(s) read from GlobalBasicSettings_13.xml.');
      return payload;
    } catch (error) {
      this.state.robloxSettings = { loaded: true, available: false, reason: error.message || 'Roblox settings could not be read.', basic: {}, advanced: [], profiles: [], groups: [] };
      if (this.state.route === 'settings' && this.state.settingsTab === 'roblox') this.render();
      if (announce) this.toast('error', 'Could not read Roblox settings', this.state.robloxSettings.reason);
      return null;
    }
  }

  renderWindowsStartupSetting() {
    const status = this.windowsStartupStatus();
    if (this.state.mode !== 'desktop') return this.settingRow('Start with Windows', 'Preview mode cannot inspect or simulate the current-user Windows startup registration.', '<span class="badge warning">Desktop only</span>');
    if (!status.loaded) return this.settingRow('Start with Windows', 'Checking whether the packaged desktop application can use the current-user Windows startup entry.', '<span class="badge">Checking...</span>');
    const reason = status.reason ? ' ' + escapeHtml(status.reason) : '';
    if (status.error) return this.settingRow('Start with Windows', 'The desktop bridge could not read the current Windows startup state.' + reason, '<button class="button button-sm" type="button" data-action="refresh-windows-startup">' + icon('refresh') + ' Retry</button>');
    if (!status.supported) return this.settingRow('Start with Windows', 'This desktop runtime does not support a Windows startup registration.' + reason, '<span class="badge warning">Not supported</span>');
    if (!status.available) return this.settingRow('Start with Windows', 'Windows startup is supported, but its current-user Run entry is unavailable.' + reason, '<span class="badge warning">Unavailable</span>');
    const targetEnabled = !Boolean(status.enabled);
    const actionLabel = status.enabled ? 'Disable startup' : status.needs_repair ? 'Repair startup' : 'Enable startup';
    const body = status.enabled
      ? 'Astro Account Manager is registered to start for the current Windows user. Disabling removes only its own startup entry.'
      : status.needs_repair
        ? 'An outdated Astro startup entry needs repair before the packaged application can start at sign-in.'
        : 'Register the packaged Astro Account Manager application for the current Windows user. This always needs a separate confirmation.';
    const badge = status.enabled ? '<span class="badge success">Enabled</span>' : status.needs_repair ? '<span class="badge warning">Needs repair</span>' : '<span class="badge">Off</span>';
    return this.settingRow('Start with Windows', body, '<span class="startup-control">' + badge + '<button class="button button-sm' + (status.enabled ? ' button-danger' : ' button-primary') + '" type="button" data-action="open-windows-startup" data-enabled="' + targetEnabled + '">' + icon(status.enabled ? 'x' : 'check') + ' ' + actionLabel + '</button></span>');
  }

  openWindowsStartupModal(enabled) {
    const status = this.windowsStartupStatus();
    if (this.state.mode !== 'desktop') {
      this.toast('info', 'Windows startup is desktop-only', 'Preview mode never simulates a Windows Run registration.');
      return;
    }
    if (!status.loaded) {
      this.toast('info', 'Checking Windows startup', 'Wait for the desktop bridge to return the current capability state.');
      void this.loadWindowsStartupStatus(false);
      return;
    }
    if (!status.available) {
      this.toast('error', 'Windows startup is unavailable', status.reason || 'The current desktop runtime cannot change this setting.');
      return;
    }
    this.openModal({ kind: 'windows-startup', enabled: Boolean(enabled), status: status });
  }

  async setWindowsStartup(enabled) {
    if (this.state.mode !== 'desktop') throw new Error('Windows startup can only be changed through the desktop bridge. Preview mode never simulates a Windows Run registration.');
    const status = this.applyWindowsStartupStatus(await this.bridge.call('set_windows_startup', Boolean(enabled), true));
    await this.resync();
    this.applyWindowsStartupStatus(status);
    return status;
  }

  renderLoading() {
    this.root.innerHTML = '<main class="loading-page"><div class="loading-card"><div class="wordmark-mark">' + icon('orbit') + '</div><strong>Opening Astro Account Manager</strong><p>Preparing your workspace</p><div class="loading-bar"><i></i></div></div></main>';
    // This replaces the document outside render(), so the markup cache must be
    // dropped or the next render would skip the rebuild and keep this screen.
    this.state.lastRenderHtml = null;
    this.state.lastSidebarHtml = null;
    this.state.lastTopbarHtml = null;
    this.state.lastPageHtml = null;
  }

  navItem(route, label, iconName, count) {
    return '<button class="nav-item ' + (this.state.route === route ? 'is-active' : '') + '" data-action="navigate" data-route="' + route + '" type="button">' + icon(iconName) + '<span>' + label + '</span>' + (count !== undefined ? '<small class="nav-count">' + escapeHtml(count) + '</small>' : '') + '</button>';
  }

  /* Nexus is retained in this file but hidden from the product.  The backend
     reports features.nexus, so nothing below renders or responds until the
     ASTRO_ENABLE_NEXUS flag restores it. */
  nexusEnabled() {
    return Boolean((this.state.features || {}).nexus);
  }

  pageMeta() {
    const nexusAccts = asArray((this.state.nexus || {}).accounts);
    const metas = {
      dashboard: ['Overview', 'Your account workspace at a glance'],
      accounts: ['Accounts', this.state.accounts.length + ' identities in your workspace'],
      games: ['Games & servers', 'Browse a game and choose where to join'],
      instances: ['Instances', 'Live Roblox process monitoring'],
      nexus: ['Nexus Executor', nexusAccts.length + ' connected client' + (nexusAccts.length === 1 ? '' : 's')],
      macros: ['Macros', 'Independent block or DSL automations for verified Roblox instances'],
      fleet: ['Fleet', 'Statistics, schedule, account health, servers, coordination, comfort, alerts and rules'],
      diagnostics: ['Diagnostics', 'Service health and recent events'],
      settings: ['Settings', 'Make Astro Account Manager feel like your workspace']
    };
    return metas[this.state.route] || metas.dashboard;
  }

  // A background poll must never steal the caret.  When the element being typed
  // into lives inside the container we are about to rebuild, its value, its
  // selection and its focus are carried across the swap.  Without this the 3 s
  // runtime poll quietly destroyed whatever was half-typed in a text box.
  swapHtml(container, html) {
    if (!container) return;
    const active = (typeof document !== 'undefined' && document.activeElement) ? document.activeElement : null;
    const tag = active && active.tagName ? String(active.tagName).toLowerCase() : '';
    const inside = active && typeof container.contains === 'function' && container.contains(active);
    if (!inside || !['input', 'textarea', 'select'].includes(tag)) { container.innerHTML = html; return; }
    const memo = {
      id: active.id || '',
      name: (typeof active.getAttribute === 'function' ? active.getAttribute('name') : '') || '',
      value: typeof active.value === 'string' ? active.value : null,
      start: typeof active.selectionStart === 'number' ? active.selectionStart : null,
      end: typeof active.selectionEnd === 'number' ? active.selectionEnd : null
    };
    container.innerHTML = html;
    const selector = memo.id ? '[id="' + memo.id + '"]' : (memo.name ? '[name="' + memo.name + '"]' : '');
    const next = (selector && typeof container.querySelector === 'function') ? container.querySelector(selector) : null;
    if (!next) return;
    if (memo.value !== null && typeof next.value === 'string' && next.value !== memo.value) next.value = memo.value;
    if (typeof next.focus === 'function') { try { next.focus({ preventScroll: true }); } catch (_) { next.focus(); } }
    if (memo.start !== null && typeof next.setSelectionRange === 'function') {
      try { next.setSelectionRange(memo.start, memo.end === null ? memo.start : memo.end); } catch (_) {}
    }
  }

  render() {
    const meta = this.pageMeta();
    const unread = this.state.notifications.filter(function (item) { return !item.read; }).length;
    const sidebarHtml =
      '<div class="wordmark"><span class="wordmark-mark">' + icon('orbit') + '</span><span class="wordmark-copy"><strong>astro</strong><small>account manager</small></span></div>' +
      '<nav class="nav">' +
      '<p class="nav-label">Workspace</p>' +
      this.navItem('dashboard', 'Dashboard', 'grid') +
      this.navItem('accounts', 'Accounts', 'users', this.state.accounts.length) +
      this.navItem('games', 'Games & servers', 'gamepad') +
      this.navItem('instances', 'Instances', 'monitor', this.state.instances.length) +
      (this.nexusEnabled() ? this.navItem('nexus', 'Nexus', 'command', asArray((this.state.nexus || {}).accounts).length) : '') +
      this.navItem('macros', 'Macros', 'zap', this.state.macros.length) +
      this.navItem('fleet', 'Fleet', 'shield') +
      '<p class="nav-label">System</p>' +
      this.navItem('diagnostics', 'Diagnostics', 'activity') +
      this.navItem('settings', 'Settings', 'settings') +
      '</nav><div class="sidebar-spacer"></div>' +
      (this.state.mode === 'preview' ? '<div class="sidebar-preview"><strong><span></span> Preview workspace</strong><p>Native bridge unavailable. Changes are stored only in this browser.</p></div>' : '') +
      '<button type="button" class="profile-button" data-action="navigate" data-route="settings">' + avatar({ username: 'You', avatar_color: 'blue' }, 'sm') + '<span class="profile-copy"><strong>Local workspace</strong><small>' + (this.state.mode === 'desktop' ? 'Desktop bridge connected' : 'Preview mode') + '</small></span>' + icon('chevronRight') + '</button>';
    const topbarHtml = '<div class="page-title"><h1>' + escapeHtml(meta[0]) + '</h1><p>' + escapeHtml(meta[1]) + '</p></div><div class="topbar-spacer"></div>' +
      '<button class="search-button" type="button" data-action="open-palette">' + icon('search') + '<span>Search anything</span><span class="kbd">Ctrl K</span></button>' +
      '<button class="icon-button" type="button" data-action="toggle-theme" aria-label="Toggle color theme">' + icon(this.state.settings.theme === 'light' ? 'moon' : 'sun') + '</button>' +
      '<span class="topbar-divider"></span><button class="icon-button" type="button" data-action="toggle-notifications" aria-label="Notifications">' + icon('bell') + (unread ? '<span class="notification-pip"></span>' : '') + '</button>';
    const pageHtml = this.renderPage();
    const html = '<aside class="sidebar" aria-label="Main navigation">' + sidebarHtml +
      '</aside><section class="workspace"><header class="topbar">' + topbarHtml +
      '</header><main id="app-main" class="page" tabindex="-1">' + pageHtml + '</main></section>';
    const sidebar = this.root.querySelector('.sidebar');
    const topbar = this.root.querySelector('.topbar');
    const page = this.root.querySelector('#app-main');
    if (!sidebar || !topbar || !page) {
      this.swapHtml(this.root, html);
    } else {
      if (sidebarHtml !== this.state.lastSidebarHtml) this.swapHtml(sidebar, sidebarHtml);
      if (topbarHtml !== this.state.lastTopbarHtml) this.swapHtml(topbar, topbarHtml);
      if (pageHtml !== this.state.lastPageHtml) this.swapHtml(page, pageHtml);
    }
    this.state.lastRenderHtml = html;
    this.state.lastSidebarHtml = sidebarHtml;
    this.state.lastTopbarHtml = topbarHtml;
    this.state.lastPageHtml = pageHtml;
    this.renderOverlays();
    if (this.state.route === 'nexus' && this.nexusEnabled()) {
      this.nexusSyncLineNumbers();
      const editor = document.getElementById('nexus-code-editor');
      const lineNums = document.getElementById('nexus-line-numbers');
      if (editor && lineNums) {
        editor.onscroll = function () { lineNums.scrollTop = editor.scrollTop; };
      }
    }
  }

  renderPage() {
    if (this.state.route === 'accounts') return this.renderAccounts();
    if (this.state.route === 'games') return this.renderGames();
    if (this.state.route === 'instances') return this.renderInstances();
    if (this.state.route === 'nexus') return this.nexusEnabled() ? this.renderNexusExecutor() : this.renderDashboard();
    if (this.state.route === 'macros') return this.renderMacros();
    if (this.state.route === 'fleet') return this.renderFleet();
    if (this.state.route === 'diagnostics') return this.renderDiagnostics();
    if (this.state.route === 'settings') return this.renderSettings();
    return this.renderDashboard();
  }

  renderDashboard() {
    const active = this.state.accounts.filter(function (item) { return item.status === 'in_game'; });
    const ready = this.state.accounts.filter(function (item) { return item.status === 'ready'; });
    const favorites = this.state.accounts.filter(function (item) { return item.favorite; });
    const recent = this.state.accounts.slice().sort(function (a, b) { return Number(b.last_used || 0) - Number(a.last_used || 0); }).slice(0, 3);
    const primary = active[0] || ready[0] || this.state.accounts[0];
    return '<section class="page-heading"><div class="page-heading-copy"><h2>Your workspace, in focus.</h2><p>Launch the right account, see active instances, and catch what changed without digging through settings.</p></div><div class="page-heading-actions"><button class="button button-quiet" type="button" data-action="refresh-instances">' + icon('refresh') + ' Refresh</button><button class="button button-primary" type="button" data-action="create-account">' + icon('plus') + ' Add account</button></div></section>' +
      '<section class="stats-grid" aria-label="Account summary">' +
      this.statCard('Accounts', this.state.accounts.length, 'users', 'Ready to use') +
      this.statCard('Active now', active.length, 'activity', active.length ? '<em>Instances detected</em>' : 'No active sessions') +
      this.statCard('Favorites', favorites.length, 'star', favorites.length ? 'Pinned for quick launch' : 'Pin your first favorite') +
      this.statCard('Services', this.state.diagnostics.status === 'healthy' ? 'Good' : 'Check', 'shield', '<em>' + escapeHtml(this.state.diagnostics.status || 'Healthy') + '</em>') +
      '</section>' + this.renderFleetCard() + '<section class="section-header"><h3>Continue where you left off</h3><span class="section-line"></span><button class="section-link" type="button" data-action="navigate" data-route="accounts">All accounts</button></section>' +
      '<section class="dashboard-grid"><article class="panel launch-feature"><div class="eyebrow"><span class="live-dot"></span> Quick launch</div><h3>' + (primary ? escapeHtml(primary.display_name || primary.username) + ' is ready for the next session.' : 'Add your first account to begin.') + '</h3><p>' + (primary ? escapeHtml(primary.username) + ' can launch into your selected experience in one step.' : 'Keep sessions, groups, and launches organized in one calm workspace.') + '</p><div class="launch-feature-actions">' + (primary ? '<button class="button button-primary" type="button" data-action="launch" data-id="' + escapeHtml(primary.id) + '">' + icon('play') + ' Launch now</button><button class="button" type="button" data-action="edit-account" data-id="' + escapeHtml(primary.id) + '">' + icon('edit') + ' Details</button>' : '<button class="button button-primary" type="button" data-action="create-account">' + icon('plus') + ' Add your first account</button>') + '</div><div class="feature-meta"><span><strong>' + this.state.instances.length + '</strong> tracked instances</span><span><strong>' + this.state.games.length + '</strong> recent games</span></div></article>' +
      '<article class="panel"><div class="panel-head"><h3>' + icon('clock') + ' Recent activity</h3><button class="section-link" data-action="navigate" data-route="diagnostics" type="button">View log</button></div><div class="activity-list">' + this.renderActivity(this.state.activity.slice(0, 4)) + '</div></article></section>' +
      '<section class="section-header"><h3>Recently used accounts</h3><p>Jump right back in</p><span class="section-line"></span></section><section class="recent-accounts">' + (recent.length ? recent.map(this.renderMiniAccount.bind(this)).join('') : this.emptyInline('users', 'No accounts yet', 'Add an account to build a launch history.')) + '</section>';
  }

  renderFleetCard() {
    const fleet = this.state.fleet || {};
    const plan = fleet.plan || null;
    const resources = fleet.resources || null;
    const groups = asArray(this.state.groups);
    const options = ['<option value="">Choose a group</option>'].concat(groups.map(function (group) {
      const selected = fleet.groupId === group.id ? ' selected' : '';
      return '<option value="' + escapeHtml(group.id) + '"' + selected + '>' + escapeHtml(group.name) + '</option>';
    })).join('');
    const lines = [];
    if (plan) {
      lines.push('Planned ' + escapeHtml(plan.planned || 0) + ' account(s) in ' + escapeHtml(plan.waves || 0) + ' wave(s), ' +
        escapeHtml(plan.delay_seconds || 0) + 's apart, about ' + escapeHtml(plan.estimated_seconds || 0) + 's total.');
      if (asArray(plan.skipped).length) lines.push('Skipped ' + escapeHtml(asArray(plan.skipped).length) + ' already running or duplicated account(s).');
    }
    if (resources) {
      if (resources.applied_fps) lines.push('Frame rate target ' + escapeHtml(resources.applied_fps) + ' FPS for ' + escapeHtml(resources.instance_count || 0) + ' window(s).');
      if (resources.message) lines.push(escapeHtml(resources.message));
      if (resources.estimated_additional_instances !== null && resources.estimated_additional_instances !== undefined) {
        lines.push('Room for about ' + escapeHtml(resources.estimated_additional_instances) + ' more client(s).');
      }
      lines.push('Roblox exposes a single global frame rate cap, so per-window rates are not applied.');
    }
    const detail = lines.length ? '<div class="fleet-control-status" role="status"><span class="fleet-control-status-icon">' + icon('activity') + '</span><p>' + lines.join('<br>') + '</p></div>' : '<div class="fleet-control-status is-idle"><span class="fleet-control-status-icon">' + icon('info') + '</span><p>Choose a group, preview the waves, then launch when the plan looks right.</p></div>';
    const capacity = resources && resources.estimated_additional_instances !== null && resources.estimated_additional_instances !== undefined ? resources.estimated_additional_instances : '—';
    const planned = plan ? Number(plan.planned || 0) : 0;
    const waves = plan ? Number(plan.waves || 0) : 0;
    return '<section class="section-header"><h3>Fleet control</h3><p>Stagger launches and keep the machine breathing</p><span class="section-line"></span></section>' +
      '<section class="panel fleet-control-card"><div class="fleet-control-overview"><div class="fleet-control-copy"><span class="fleet-control-mark">' + icon('rocket') + '</span><div><span class="eyebrow">Smart launch</span><h3>Prepare a safe launch plan</h3><p>Astro spaces accounts into bounded waves and checks the current machine budget first.</p></div></div><div class="fleet-control-metrics"><span><strong>' + escapeHtml(planned) + '</strong> planned</span><span><strong>' + escapeHtml(waves) + '</strong> waves</span><span><strong>' + escapeHtml(capacity) + '</strong> capacity</span></div></div>' +
      '<div class="fleet-control-workspace"><div class="fleet-control-picker"><label for="fleet-group">Account group</label><select class="input" id="fleet-group">' + options + '</select><small>Previewing never launches or closes a client.</small></div>' +
      '<div class="fleet-action-grid"><button class="fleet-action is-primary" type="button" data-action="smart-launch-preview"><span>' + icon('layout') + '</span><strong>Preview waves</strong><small>See order, delays and skipped accounts</small></button><button class="fleet-action" type="button" data-action="apply-resource-plan"><span>' + icon('activity') + '</span><strong>Apply resource plan</strong><small>Use the safe global frame-rate target</small></button><button class="fleet-action is-danger" type="button" data-action="stop-all-macros"><span>' + icon('x') + '</span><strong>Stop all macros</strong><small>End automation runs without closing Roblox</small></button><button class="fleet-action is-launch" type="button" data-action="smart-launch-group"><span>' + icon('play') + '</span><strong>Launch group</strong><small>Queue the selected group after validation</small></button></div></div>' +
      '<div class="fleet-control-foot">' + detail + '<button class="section-link" type="button" data-action="navigate" data-route="fleet">Open advanced Fleet workspace ' + icon('chevronRight') + '</button></div></section>';
  }

  statCard(label, value, symbol, hint) {
    return '<article class="stat-card"><span class="stat-card-label">' + icon(symbol) + escapeHtml(label) + '</span><strong>' + escapeHtml(value) + '</strong><small>' + hint + '</small></article>';
  }

  renderActivity(rows) {
    if (!rows.length) return '<div class="empty-notices">' + icon('activity') + '<p>No activity yet.</p></div>';
    const symbol = { launch: 'rocket', account: 'users', backup: 'database', system: 'shield', group: 'folder', migration: 'upload' };
    return rows.map(function (row) {
      return '<div class="activity-row"><span class="activity-icon">' + icon(symbol[row.type] || 'activity') + '</span><div class="activity-copy"><strong>' + escapeHtml(row.title) + '</strong><small>' + escapeHtml(row.detail || '') + '</small></div><time class="activity-time">' + relativeTime(row.at) + '</time></div>';
    }).join('');
  }

  renderMiniAccount(account) {
    const hidden = Boolean(this.state.hideUsernames);
    const label = hidden ? 'Account #' + String(this.state.accounts.indexOf(account) + 1).padStart(2, '0') : (account.display_name || account.username);
    const username = hidden ? '••••••••' : account.username;
    return '<button class="mini-account" type="button" data-action="edit-account" data-id="' + escapeHtml(account.id) + '">' + avatar(account, 'sm') + '<span class="mini-account-copy"><strong>' + escapeHtml(label) + '</strong><span>' + escapeHtml(username) + ' · ' + relativeTime(account.last_used) + '</span></span><span class="status ' + escapeHtml(account.status) + '" aria-label="' + statusText(account.status) + '"></span></button>';
  }

  renderClassicRamPanel() {
    const hideUsernames = Boolean(this.state.hideUsernames);
    const uwpMode = Boolean(this.state.uwpMode);
    return '<aside class="panel classic-ram-panel" style="width: 320px; flex-shrink: 0; padding: 16px; display: flex; flex-direction: column; gap: 14px; background: var(--surface-card); border-radius: 12px; border: 1px solid var(--border); box-shadow: 0 4px 12px rgba(0,0,0,0.15);">' +
      '<div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 8px;">' +
      '<strong style="font-size: 0.95rem; display: flex; align-items: center; gap: 6px;">🕹️ Quick Controls</strong>' +
      '<button class="button button-sm ' + (uwpMode ? 'button-primary' : 'button-quiet') + '" type="button" data-action="toggle-uwp" title="Toggle UWP Launch Mode">UWP</button>' +
      '</div>' +
      '<div style="display: flex; flex-direction: column; gap: 8px;">' +
      '<label style="font-size: 0.8rem; font-weight: 600; opacity: 0.8;">Current Place & Job ID</label>' +
      '<div style="display: flex; gap: 6px; align-items: center;">' +
      '<input id="ram-place-id" type="number" placeholder="Place ID" style="flex: 1; padding: 6px 8px; font-size: 0.85rem; border-radius: 6px; border: 1px solid var(--border); background: var(--surface-bg);" value="' + escapeHtml(this.state.ramPlaceId || '') + '" />' +
      '<input id="ram-job-id" type="text" placeholder="Job ID" style="flex: 1; padding: 6px 8px; font-size: 0.85rem; border-radius: 6px; border: 1px solid var(--border); background: var(--surface-bg);" value="' + escapeHtml(this.state.ramJobId || '') + '" />' +
      '<button class="button button-sm" type="button" data-action="shuffle-job-id" title="Generate random Job ID">🔀</button>' +
      '<button class="button button-sm" type="button" data-action="save-place-id" title="Save Place ID & Job ID">💾</button>' +
      '</div>' +
      '<button class="button button-primary" style="width: 100%; margin-top: 4px;" type="button" data-action="ram-join-server">' + icon('play') + ' Join Server</button>' +
      '<button class="button" style="width: 100%;" type="button" data-action="open-private-link">' + icon('link') + ' Join private server link</button>' +
      '</div>' +
      '<div style="display: flex; gap: 6px; margin-top: 2px;">' +
      '<button class="button button-secondary" style="flex: 1; font-size: 0.8rem; padding: 6px;" type="button" data-action="open-account-utilities">⚙️ Utilities</button>' +
      (this.nexusEnabled() ? '<button class="button button-secondary" style="flex: 1; font-size: 0.8rem; padding: 6px;" type="button" data-action="open-nexus-panel">🚀 Nexus Control</button>' : '') +
      '</div>' +
      '<hr style="border: 0; border-top: 1px solid var(--border); margin: 2px 0;" />' +
      '<div style="display: flex; flex-direction: column; gap: 8px;">' +
      '<div style="display: flex; gap: 6px; align-items: center;">' +
      '<input id="ram-follow-user" type="text" placeholder="Username to follow" style="flex: 1; padding: 6px 8px; font-size: 0.85rem; border-radius: 6px; border: 1px solid var(--border); background: var(--surface-bg);" />' +
      '<button class="button button-sm" type="button" data-action="ram-follow-user">Follow</button>' +
      '</div>' +
      '<div style="display: flex; gap: 6px; align-items: center;">' +
      '<input id="ram-alias-input" type="text" placeholder="New Alias" style="flex: 1; padding: 6px 8px; font-size: 0.85rem; border-radius: 6px; border: 1px solid var(--border); background: var(--surface-bg);" />' +
      '<button class="button button-sm" type="button" data-action="ram-set-alias">Set Alias</button>' +
      '</div>' +
      '<div style="display: flex; flex-direction: column; gap: 4px;">' +
      '<textarea id="ram-desc-input" rows="2" placeholder="Description / Notes" style="padding: 6px 8px; font-size: 0.85rem; border-radius: 6px; border: 1px solid var(--border); background: var(--surface-bg); resize: vertical;"></textarea>' +
      '<button class="button button-sm" type="button" data-action="ram-set-description" style="align-self: flex-end;">Set Description</button>' +
      '</div>' +
      '</div>' +
      '<hr style="border: 0; border-top: 1px solid var(--border); margin: 2px 0;" />' +
      '<div style="display: flex; justify-content: space-between; align-items: center;">' +
      '<label class="form-check" style="font-size: 0.85rem; cursor: pointer;">' +
      '<input type="checkbox" data-action="toggle-hide-usernames"' + (hideUsernames ? ' checked' : '') + ' /> Hide Usernames' +
      '</label>' +
      '<button class="button button-sm button-quiet" type="button" data-action="navigate" data-route="settings">🎨 Edit Theme</button>' +
      '</div>' +
      '</aside>';
  }

  renderAccounts() {
    const filtered = this.filteredAccounts();
    const selection = this.state.selected.size;
    const oauthReady = this.isOAuthConfigured();
    const connectAction = oauthReady
      ? '<button class="button button-primary" type="button" data-action="start-oauth-login">' + icon('shield') + ' Connect Roblox account</button>'
      : '<button class="button" type="button" data-action="open-oauth-settings">' + icon('shield') + ' Configure Roblox sign-in</button>';
    const oauthHint = oauthReady
      ? '<span class="oauth-toolbar-status is-ready">' + icon('shield') + ' Official OAuth ready</span>'
      : '<span class="oauth-toolbar-status">' + icon('info') + (this.state.mode === 'desktop' ? ' Roblox sign-in needs configuration' : ' Preview does not simulate sign-in') + '</span>';
    return '<section class="page-heading"><div class="page-heading-copy"><h2>Accounts & Quick Controls</h2><p>Manage your accounts, organize groups, and launch custom Roblox sessions.</p></div><div class="page-heading-actions"><button class="button button-primary" type="button" data-action="open-bulk-import">' + icon('plus') + ' Add / Import accounts</button><button class="button" type="button" data-action="create-group">' + icon('folder') + ' New group</button>' + connectAction + '</div></section>' +
      '<section class="toolbar" aria-label="Account tools"><label class="input-shell" title="Search accounts">' + icon('search') + '<input id="account-filter" type="search" autocomplete="off" placeholder="Search accounts" value="' + escapeHtml(this.state.accountQuery) + '" /></label><select class="filter-select" id="account-status" aria-label="Filter account status"><option value="all"' + (this.state.accountStatus === 'all' ? ' selected' : '') + '>All statuses</option><option value="ready"' + (this.state.accountStatus === 'ready' ? ' selected' : '') + '>Ready</option><option value="in_game"' + (this.state.accountStatus === 'in_game' ? ' selected' : '') + '>In game</option><option value="offline"' + (this.state.accountStatus === 'offline' ? ' selected' : '') + '>Offline</option></select>' + oauthHint + '<span class="toolbar-spacer"></span><div class="segmented" aria-label="View mode"><button type="button" class="' + (this.state.accountView === 'cards' ? 'is-active' : '') + '" data-action="account-view" data-view="cards" aria-label="Card view">' + icon('layout') + '</button><button type="button" class="' + (this.state.accountView === 'table' ? 'is-active' : '') + '" data-action="account-view" data-view="table" aria-label="Table view">' + icon('list') + '</button></div></section>' +
      '<div style="display: flex; gap: 16px; align-items: flex-start;"><div style="flex: 1; min-width: 0;">' +
      (this.state.accountView === 'table' ? this.renderAccountsTable(filtered) : this.renderAccountGroups(filtered)) +
      '</div>' + this.renderClassicRamPanel() + '</div>' +
      (selection ? '<div class="bulk-bar" role="status"><strong>' + selection + ' selected</strong><span>Configure, move, launch, or remove in one go.</span><span class="toolbar-spacer"></span><button class="button button-sm" type="button" data-action="bulk-edit">' + icon('edit') + ' Bulk Edit</button><button class="button button-sm" type="button" data-action="bulk-move">' + icon('folder') + ' Move</button><button class="button button-sm" type="button" data-action="bulk-launch">' + icon('play') + ' Launch</button><button class="button button-sm button-danger" type="button" data-action="bulk-delete">' + icon('trash') + ' Remove</button><button class="icon-button" type="button" data-action="clear-selection" aria-label="Clear selection">' + icon('x') + '</button></div>' : '');
  }

  filteredAccounts() {
    const phrase = this.state.accountQuery.trim().toLowerCase();
    const status = this.state.accountStatus;
    return this.state.accounts.filter(function (account) {
      const matchesWords = !phrase || [account.username, account.display_name, account.notes].join(' ').toLowerCase().includes(phrase);
      return matchesWords && (status === 'all' || account.status === status);
    });
  }

  renderAccountGroups(accounts) {
    const groups = this.state.groups.slice().sort(function (a, b) { return Number(a.order || 0) - Number(b.order || 0); });
    if (!accounts.length) {
      if (!this.state.accounts.length) return this.emptyState('users', 'No accounts in this workspace', 'Add a local profile to create your first account card.', 'Add profile', 'create-account');
      return this.emptyState('search', 'No matching accounts', 'Try a different search or clear the filters.', 'Clear filters', 'clear-account-filter');
    }
    const chunks = groups.map(function (group) {
      const members = accounts.filter(function (account) { return String(account.group_id || '') === String(group.id); });
      return this.renderGroupSection(group, members);
    }.bind(this));
    const ungrouped = accounts.filter(function (account) { return !account.group_id || !groups.some(function (group) { return String(group.id) === String(account.group_id); }); });
    if (ungrouped.length || !groups.length) chunks.push(this.renderGroupSection({ id: '', name: 'Ungrouped', color: 'blue', collapsed: false }, ungrouped));
    return '<section class="group-stack">' + chunks.join('') + '</section>';
  }

  renderGroupSection(group, members) {
    const collapsed = Boolean(group.collapsed);
    const cards = members.length ? members.map(this.renderAccountCard.bind(this)).join('') : '<div class="empty-card"><div>' + icon('folder') + '<strong>Drop accounts here</strong><p>Drag an account card into ' + escapeHtml(group.name) + ' to keep your workspace ordered.</p></div></div>';
    const actions = group.id
      ? '<button class="icon-button" type="button" data-action="edit-group" data-id="' + escapeHtml(group.id) + '" aria-label="Edit ' + escapeHtml(group.name) + '">' + icon('edit') + '</button><button class="icon-button" type="button" data-action="delete-group" data-id="' + escapeHtml(group.id) + '" aria-label="Remove ' + escapeHtml(group.name) + '">' + icon('trash') + '</button><button class="icon-button" type="button" data-action="toggle-group" data-id="' + escapeHtml(group.id) + '" aria-label="' + (collapsed ? 'Expand ' : 'Collapse ') + escapeHtml(group.name) + '">' + icon(collapsed ? 'chevronRight' : 'chevronDown') + '</button>'
      : '';
    return '<section class="group-section" data-group-target="' + escapeHtml(group.id || '') + '"><header class="group-heading"><span class="group-dot ' + escapeHtml(group.color || '') + '"></span><h3>' + escapeHtml(group.name) + '</h3><span>' + members.length + ' account' + (members.length === 1 ? '' : 's') + '</span><span class="group-actions">' + actions + '</span></header>' + (collapsed ? '' : '<div class="account-grid">' + cards + '</div>') + '</section>';
  }

  renderAccountCard(account) {
    const selected = this.state.selected.has(account.id);
    const launching = this.state.launchingAccounts.has(String(account.id));
    const hide = Boolean(this.state.hideUsernames);
    const displayUser = hide ? '••••••••' : escapeHtml(account.username);
    const displayAlias = hide ? '••••••••' : escapeHtml(account.display_name || account.username);
    return '<article class="account-card ' + (selected ? 'is-selected' : '') + '" data-account-id="' + escapeHtml(account.id) + '" draggable="true"><button class="account-card-check" type="button" data-action="account-select" data-id="' + escapeHtml(account.id) + '" aria-label="' + (selected ? 'Deselect' : 'Select') + ' ' + displayUser + '">' + icon(selected ? 'check' : 'plus') + '</button><div class="account-card-top">' + avatar(account) + '<div class="account-card-info"><strong>' + displayAlias + '</strong><span>@' + displayUser + '</span></div></div><div class="account-status-row"><span class="status ' + escapeHtml(account.status) + '">' + statusText(account.status) + '</span><span class="last-used">' + relativeTime(account.last_used) + '</span></div><div class="account-oauth-row">' + this.renderOAuthAccountState(account) + '</div>' + this.renderPublicAccountSnapshot(account, false) + '<div class="account-card-bottom"><button class="button button-sm button-primary" type="button" data-action="launch" data-id="' + escapeHtml(account.id) + '"' + (launching ? ' disabled aria-busy="true"' : '') + '>' + icon(launching ? 'refresh' : 'play') + (launching ? ' Launching…' : ' Launch') + '</button><button class="favorite-star ' + (account.favorite ? 'is-favorite' : '') + '" type="button" data-action="toggle-favorite" data-id="' + escapeHtml(account.id) + '" aria-label="' + (account.favorite ? 'Remove favorite' : 'Add favorite') + '">' + icon('star') + '</button>' + this.renderOAuthAccountActions(account, false) + '<button class="icon-button" type="button" data-action="edit-account" data-id="' + escapeHtml(account.id) + '" aria-label="Edit ' + displayUser + '">' + icon('dots') + '</button></div></article>';
  }

  renderAccountsTable(accounts) {
    if (!accounts.length) return this.emptyState('search', 'No matching accounts', 'Try a different search or clear the filters.', 'Clear filters', 'clear-account-filter');
    const hide = Boolean(this.state.hideUsernames);
    return '<div class="data-table-wrap"><table class="data-table"><thead><tr><th aria-label="Select"></th><th>Account</th><th>Status</th><th>Roblox</th><th>Group</th><th>Last used</th><th aria-label="Actions"></th></tr></thead><tbody>' + accounts.map(function (account) {
      const group = this.groupFor(account.group_id);
      const selected = this.state.selected.has(account.id);
      const launching = this.state.launchingAccounts.has(String(account.id));
      const displayUser = hide ? '••••••••' : escapeHtml(account.username);
      const displayAlias = hide ? '••••••••' : escapeHtml(account.display_name || account.username);
      return '<tr><td><input type="checkbox" data-action="account-select" data-id="' + escapeHtml(account.id) + '" aria-label="Select ' + displayUser + '"' + (selected ? ' checked' : '') + ' /></td><td><div class="table-account">' + avatar(account, 'sm') + '<span><strong>' + displayAlias + '</strong><small>@' + displayUser + '</small></span></div></td><td><span class="status ' + escapeHtml(account.status) + '">' + statusText(account.status) + '</span></td><td><div class="table-roblox-state">' + this.renderOAuthAccountState(account) + this.renderPublicAccountSnapshot(account, true) + '</div></td><td>' + (group ? '<span class="group-chip"><i class="' + escapeHtml(group.color || '') + '"></i>' + escapeHtml(group.name) + '</span>' : '<span class="mono">Ungrouped</span>') + '</td><td><span class="mono">' + relativeTime(account.last_used) + '</span></td><td><div class="table-actions"><button class="icon-button" type="button" data-action="launch" data-id="' + escapeHtml(account.id) + '" aria-label="' + (launching ? 'Launching ' : 'Launch ') + displayUser + '"' + (launching ? ' disabled aria-busy="true"' : '') + '>' + icon(launching ? 'refresh' : 'play') + '</button>' + this.renderOAuthAccountActions(account, true) + '<button class="icon-button" type="button" data-action="edit-account" data-id="' + escapeHtml(account.id) + '" aria-label="Edit ' + displayUser + '">' + icon('edit') + '</button></div></td></tr>';
    }.bind(this)).join('') + '</tbody></table></div>';
  }

  groupFor(id) { return this.state.groups.find(function (group) { return String(group.id) === String(id); }) || null; }

  renderGames() {
    const games = this.state.games.filter(function (game) { return !this.state.gameQuery || [game.title, game.creator, game.category].join(' ').toLowerCase().includes(this.state.gameQuery.toLowerCase()); }.bind(this));
    // This callback must keep the OrbitApp instance. Without the binding, one
    // saved game raised before innerHTML was assigned and the page appeared to
    // ignore the Games & servers navigation entirely.
    const selectedGame = this.state.gameDetail || this.state.games.find(function (game) { return String(game.place_id) === String(this.state.gameId); }.bind(this));
    return '<section class="page-heading"><div class="page-heading-copy"><h2>Find the room, not just the game.</h2><p>Keep your recent worlds close, then choose a server by region, capacity, and latency before launching an account.</p></div><div class="page-heading-actions"><button class="button" type="button" data-action="refresh-servers">' + icon('refresh') + ' Refresh servers</button></div></section><section class="toolbar"><label class="input-shell">' + icon('search') + '<input id="game-filter" type="search" autocomplete="off" placeholder="Search games" value="' + escapeHtml(this.state.gameQuery) + '" /></label><span class="toolbar-spacer"></span><span class="offline-note">' + icon(this.state.mode === 'desktop' ? 'shield' : 'info') + (this.state.mode === 'desktop' ? ' Live bridge connected' : ' Preview data') + '</span></section><section class="games-layout"><div><div class="section-header"><h3>Recent & favorites</h3><span class="section-line"></span><span>' + games.length + ' games</span></div><div class="game-list">' + (games.length ? games.map(this.renderGameCard.bind(this)).join('') : this.emptyState('search', this.state.gamesLoading ? 'Searching Roblox...' : 'No games yet', this.state.gamesLoading ? 'Looking for experiences that match your search.' : 'Type a game name in the search box to look it up on Roblox, or launch an account to build your saved list.', 'Clear search', 'clear-game-filter')) + '</div></div><aside class="panel game-detail">' + this.renderGameDetail(selectedGame) + '</aside></section>';
  }

  renderGameCard(game) {
    return '<button class="game-card ' + (String(game.place_id) === String(this.state.gameId) ? 'is-active' : '') + '" type="button" data-action="select-game" data-id="' + escapeHtml(game.place_id) + '"><span class="game-image ' + escapeHtml(game.thumbnail_color || '') + '"><span>' + escapeHtml(initials(game.title).slice(0, 1)) + '</span></span><span class="game-copy"><strong>' + escapeHtml(game.title) + '</strong><span>' + escapeHtml(game.creator || 'Unknown creator') + ' · ' + escapeHtml(game.category || 'Game') + '</span><small><b>●</b> ' + formatNumber(game.players) + ' playing</small></span><span class="game-arrow">' + icon('chevronRight') + '</span></button>';
  }

  renderGameDetail(game) {
    if (!game) return '<div class="empty-notices">' + icon('gamepad') + '<p>Select a game to explore its servers.</p></div>';
    const servers = this.state.servers;
    const placeId = escapeHtml(game.place_id);
    const favorite = Boolean(game.favorite);
    const filters = this.state.serverFilters || {};
    const serverFilters = '<div class="form-grid"><div class="field"><label>Order</label><select id="server-sort"><option value="score"' + (filters.sort === 'score' ? ' selected' : '') + '>Best quality score</option><option value="lowest_players"' + (filters.sort === 'lowest_players' ? ' selected' : '') + '>Lowest players</option><option value="lowest_ping"' + (filters.sort === 'lowest_ping' ? ' selected' : '') + '>Lowest ping</option><option value="most_players"' + (filters.sort === 'most_players' ? ' selected' : '') + '>Most players</option></select></div><div class="field"><label>Minimum free slots</label><input id="server-min-slots" type="number" min="0" max="100" value="' + escapeHtml(filters.min_free_slots || 0) + '" /></div><label class="form-check field full"><input id="server-avoid-previous" type="checkbox"' + (filters.avoid_previous ? ' checked' : '') + ' /> Avoid previously used servers</label></div>';
    return '<div class="game-detail-hero"><span class="badge accent">' + escapeHtml(game.category || 'Game') + '</span><h3>' + escapeHtml(game.title) + '</h3><p>' + escapeHtml(game.creator || 'Unknown creator') + '</p></div><div class="detail-meta"><div><small>Place ID</small><strong title="' + placeId + '">' + placeId + '</strong></div><div><small>Playing now</small><strong>' + formatNumber(game.players) + '</strong></div><button class="icon-button" type="button" data-action="copy-place" data-value="' + placeId + '" aria-label="Copy Place ID">' + icon('copy') + '</button><button class="favorite-star ' + (favorite ? 'is-favorite' : '') + '" type="button" data-action="toggle-game-favorite" data-id="' + placeId + '" aria-label="' + (favorite ? 'Remove game from favorites' : 'Add game to favorites') + '" title="' + (favorite ? 'Remove from favorites' : 'Add to favorites') + '">' + icon('star') + '</button><button class="icon-button" type="button" data-action="open-remove-game" data-id="' + placeId + '" aria-label="Remove ' + escapeHtml(game.title) + ' from local games" title="Remove local game">' + icon('trash') + '</button></div>' + serverFilters + '<div class="panel-head"><h3>' + icon('monitor') + ' Public servers</h3><span>' + (this.state.serversLoading ? 'Refreshing...' : servers.length + ' visible') + '</span><button class="button button-sm" type="button" data-action="open-server-distribution"' + (servers.length ? '' : ' disabled') + '>Distribute</button><button class="button button-sm" type="button" data-action="open-region-probe"' + (servers.length ? '' : ' disabled') + '>' + icon('globe') + ' Load regions</button></div><div class="server-list">' + (this.state.serversLoading ? '<div class="empty-notices">' + icon('refresh') + '<p>Checking available servers...</p></div>' : servers.length ? servers.slice(0, 7).map(this.renderServer.bind(this)).join('') : '<div class="empty-notices">' + icon('monitor') + '<p>No server list yet.</p></div>') + '</div>';
  }

  renderGameDetailSnapshot(game) {
    if (!game) return '<div class="empty-notices">' + icon('gamepad') + '<p>Select a game to explore its servers.</p></div>';
    const servers = this.state.servers;
    return '<div class="game-detail-hero"><span class="badge accent">' + escapeHtml(game.category || 'Game') + '</span><h3>' + escapeHtml(game.title) + '</h3><p>' + escapeHtml(game.creator || 'Unknown creator') + '</p></div><div class="detail-meta"><div><small>Place ID</small><strong title="' + escapeHtml(game.place_id) + '">' + escapeHtml(game.place_id) + '</strong></div><div><small>Playing now</small><strong>' + formatNumber(game.players) + '</strong></div><button class="icon-button" type="button" data-action="copy-place" data-value="' + escapeHtml(game.place_id) + '" aria-label="Copy Place ID">' + icon('copy') + '</button></div><div class="panel-head"><h3>' + icon('monitor') + ' Public servers</h3><span>' + (this.state.serversLoading ? 'Refreshing…' : servers.length + ' visible') + '</span></div><div class="server-list">' + (this.state.serversLoading ? '<div class="empty-notices">' + icon('refresh') + '<p>Checking available servers…</p></div>' : servers.length ? servers.slice(0, 7).map(this.renderServer.bind(this)).join('') : '<div class="empty-notices">' + icon('monitor') + '<p>No server list yet.</p></div>') + '</div>';
  }

  renderServer(server) {
    const percent = Math.min(100, Math.round(Number(server.players || 0) / Math.max(1, Number(server.capacity || 1)) * 100));
    const score = server.score === null || server.score === undefined ? '—' : String(server.score) + '/100';
    const breakdown = server.score_breakdown || {};
    return '<div class="server-row"><div class="server-copy"><strong>' + escapeHtml(server.region || 'Unknown region') + (server.vip ? ' · VIP' : '') + ' · Score ' + escapeHtml(score) + '</strong><span title="Ping ' + escapeHtml(breakdown.ping) + ' · slots ' + escapeHtml(breakdown.free_slots) + ' · FPS ' + escapeHtml(breakdown.fps) + ' · stability ' + escapeHtml(breakdown.stability) + '">' + escapeHtml(server.ping === null || server.ping === undefined ? 'unknown' : server.ping) + ' ms · ' + escapeHtml(server.free_slots) + ' free · ' + escapeHtml(server.job_id || 'No JobId') + '</span></div><div class="capacity"><span>' + escapeHtml(server.players) + ' / ' + escapeHtml(server.capacity) + '</span><i><b class="' + (percent > 78 ? 'warn' : '') + '" style="width:' + percent + '%"></b></i></div><button class="button button-sm" type="button" data-action="join-server" data-server="' + escapeHtml(server.id) + '"' + (server.eligible === false ? ' disabled' : '') + '>Join</button></div>';
  }

  renderInstances() {
    const services = (this.state.diagnostics.services || []).slice(0, 3);
    const monitor = this.state.instanceMonitor || {};
    const scanLabel = monitor.last_scan_complete === true ? 'Last scan complete' : monitor.last_scan_complete === false ? 'Last scan partial' : 'Monitor details load on refresh';
    const closeLabel = monitor.termination_enabled ? 'Closing enabled' : 'Closing disabled in Settings';
    const events = asArray(monitor.events).slice(0, 5).map(function (event) {
      return { type: 'system', title: statusText(event.kind || 'instance'), detail: 'PID ' + (event.pid || 'unknown') + (event.reason ? ' - ' + event.reason : ''), at: event.occurred_at };
    });
    const pending = asArray(monitor.pending_restarts);
    const pendingBlock = pending.length ? '<section class="panel monitor-detail-panel"><div class="panel-head"><h3>' + icon('refresh') + ' Pending restarts</h3><span>' + pending.length + '</span></div><div class="activity-list">' + pending.slice(0, 5).map(function (request) { const account = this.findAccount(request.account_id); return '<div class="activity-row"><span class="activity-icon">' + icon('refresh') + '</span><div class="activity-copy"><strong>' + escapeHtml(account ? account.display_name || account.username : 'Account') + '</strong><small>Place ' + escapeHtml(request.place_id || 'unknown') + ' - attempt ' + escapeHtml(request.attempt || 0) + '</small></div><time class="activity-time">' + relativeTime(request.due_at) + '</time></div>'; }.bind(this)).join('') + '</div></section>' : '';
    const eventBlock = events.length ? '<section class="panel monitor-detail-panel"><div class="panel-head"><h3>' + icon('activity') + ' Recent monitor events</h3><span>' + events.length + '</span></div><div class="activity-list">' + this.renderActivity(events) + '</div></section>' : '';
    return '<section class="page-heading"><div class="page-heading-copy"><h2>Every running session, accounted for.</h2><p>Astro Account Manager keeps launch state, process IDs, and lightweight health signals together so active accounts never become guesswork.</p></div><div class="page-heading-actions"><button class="button" type="button" data-action="show-all-instances">Show all</button><button class="button button-primary" type="button" data-action="refresh-instances">' + icon('refresh') + ' Refresh instances</button></div></section><section class="instance-summary"><article class="panel monitor-card"><h3>Instance watcher</h3><p>Current local process observations from the desktop bridge.</p><div class="pulse-track"><svg class="pulse-svg" preserveAspectRatio="none" viewBox="0 0 400 55"><polyline points="0,33 22,33 32,19 42,42 54,28 67,33 97,33 112,18 123,42 138,25 152,33 193,33 204,21 217,38 231,33 279,33 294,16 305,42 320,27 334,33 400,33"></polyline></svg></div><div class="monitor-footer"><span>' + escapeHtml(scanLabel) + '</span><span>' + this.state.instances.length + ' tracked process' + (this.state.instances.length === 1 ? '' : 'es') + '</span><span class="monitor-mode">' + escapeHtml(closeLabel) + '</span></div></article><article class="panel"><div class="panel-head"><h3>' + icon('shield') + ' Service health</h3><span>' + escapeHtml(this.state.diagnostics.status || 'Healthy') + '</span></div><div class="health-list">' + services.map(function (service) { return '<div class="health-row"><span class="health-symbol">' + icon(service.status === 'degraded' ? 'alert' : 'check') + '</span><span class="health-copy"><strong>' + escapeHtml(service.name) + '</strong><span>' + escapeHtml(service.detail) + '</span></span><span class="status ' + escapeHtml(service.status || 'healthy') + '"></span></div>'; }).join('') + '</div></article></section><section class="section-header"><h3>Observed instances</h3><p>Tracked locally by the desktop bridge</p><span class="section-line"></span></section>' + this.renderInstancesTable() + '<section class="monitor-detail-grid">' + pendingBlock + eventBlock + '</section>' + (this.nexusEnabled() ? this.renderNexusSection() : '');
  }

  renderNexusSection() {
    const nexus = this.state.nexus || { running: false, host: '127.0.0.1', port: 5242, url: 'ws://127.0.0.1:5242/Nexus', accounts: [] };
    const running = Boolean(nexus.running);
    const accounts = asArray(nexus.accounts);

    const clientRows = accounts.length ? accounts.map(function (client) {
      const name = escapeHtml(client.username);
      const isOnline = client.status === 'Online';
      return '<div class="server-row"><div class="server-copy"><strong>' + name + ' <small class="mono">(ID: ' + escapeHtml(client.user_id || '—') + ')</small></strong><span>JobId: ' + escapeHtml(client.job_id || '—') + ' · Connected: ' + relativeTime(client.connected_at) + '</span></div><div class="capacity"><span class="status ' + (isOnline ? 'ready' : 'offline') + '">' + escapeHtml(client.status) + '</span></div><button class="button button-sm" type="button" data-action="open-send-nexus" data-target="' + name + '">' + icon('command') + ' Command</button></div>';
    }).join('') : '<div class="empty-notices">' + icon('monitor') + '<p>' + (running ? 'No Roblox client connected to ws://' + escapeHtml(nexus.host) + ':' + escapeHtml(nexus.port) + '/Nexus.' : 'The Nexus server is currently stopped.') + '</p></div>';

    return '<section class="section-header"><h3>Nexus / Account Control (WebSocket)</h3><p>Real-time control and command relay with Roblox clients</p><span class="section-line"></span></section>' +
      '<section class="instance-summary"><article class="panel monitor-card"><h3>Nexus WebSocket Server</h3><p>Listens for WebSocket connections from Roblox client scripts (Nexus.lua).</p><div class="monitor-footer"><span>' + escapeHtml(nexus.url) + '</span><span class="status ' + (running ? 'ready' : 'offline') + '">' + (running ? 'Online' : 'Stopped') + '</span></div><div class="launch-feature-actions" style="margin-top: 1rem;">' +
      (running ? '<button class="button button-danger button-sm" type="button" data-action="stop-nexus-server">' + icon('x') + ' Stop Nexus</button>' : '<button class="button button-primary button-sm" type="button" data-action="start-nexus-server">' + icon('play') + ' Start Nexus</button>') +
      '<button class="button button-sm" type="button" data-action="copy-nexus-script">' + icon('copy') + ' Copy Nexus.lua</button></div></article>' +
      '<article class="panel"><div class="panel-head"><h3>' + icon('users') + ' Connected Clients</h3><span>' + accounts.length + ' connected</span></div><div class="server-list">' + clientRows + '</div></article></section>';
  }

  renderNexusExecutor() {
    const self = this;
    const nexus = this.state.nexus || { running: false, host: '127.0.0.1', port: 5242, url: 'ws://127.0.0.1:5242/Nexus', accounts: [] };
    const running = Boolean(nexus.running);
    const accounts = asArray(nexus.accounts);
    const onlineAccounts = accounts.filter(function (a) { return a.status === 'Online'; });
    const logEntries = asArray(this.state.nexusExecutorLog);

    /* --- Help Banner --- */
    const helpBanner =
      '<div class="panel" style="margin-bottom:14px;padding:12px 16px;background:var(--surface-2);border-left:4px solid var(--accent)">' +
        '<strong style="font-size:0.85rem;display:block;margin-bottom:4px">💡 How to connect your Roblox client to Nexus Executor:</strong>' +
        '<span style="font-size:0.8rem;color:var(--text-soft);line-height:1.5">' +
          '1. Click <strong>Copy Nexus.lua</strong> above.<br/>' +
          '2. Execute this script in Roblox (via your executor or auto-execute folder).<br/>' +
          '3. Your account will appear in <strong>Connected Clients</strong> on the right (<code class="mono">ws://127.0.0.1:5242/Nexus</code>).<br/>' +
          '4. Execute your Lua scripts below; <code class="mono">print()</code> results and logs will appear live in the console!' +
        '</span>' +
      '</div>';

    /* --- Server status bar --- */
    const serverBar =
      '\u003cdiv class="nexus-server-bar"\u003e' +
        '\u003cdiv class="nexus-server-info"\u003e' +
          '\u003cspan class="nexus-status-dot ' + (running ? 'online' : 'offline') + '"\u003e\u003c/span\u003e' +
          '\u003cstrong\u003e' + (running ? 'Nexus Server Online' : 'Nexus Server Offline') + '\u003c/strong\u003e' +
          '\u003cspan class="mono" style="opacity:.6"\u003e' + escapeHtml(nexus.url || 'ws://127.0.0.1:5242/Nexus') + '\u003c/span\u003e' +
        '\u003c/div\u003e' +
        '\u003cdiv class="nexus-server-actions"\u003e' +
          (running
            ? '\u003cbutton class="button button-danger button-sm" type="button" data-action="stop-nexus-server"\u003e' + icon('x') + ' Stop\u003c/button\u003e'
            : '\u003cbutton class="button button-primary button-sm" type="button" data-action="start-nexus-server"\u003e' + icon('play') + ' Start Server\u003c/button\u003e') +
          '<button class="button button-sm" type="button" data-action="copy-nexus-script">' + icon('copy') + ' Copy Nexus.lua</button>' +
          '<button class="button button-sm" type="button" data-action="refresh-nexus-status">' + icon('refresh') + '</button>' +
        '</div>' +
      '</div>';

    /* --- Connected clients sidebar --- */
    const clientList = onlineAccounts.length
      ? onlineAccounts.map(function (client) {
          const name = escapeHtml(client.username || 'Unknown');
          return '<div class="nexus-client-row">' +
            '<span class="nexus-status-dot online"></span>' +
            '<div class="nexus-client-info">' +
              '<strong>' + name + '</strong>' +
              '<small>ID: ' + escapeHtml(String(client.user_id || '—')) + '</small>' +
            '</div>' +
            '<button class="button button-xs" type="button" data-action="nexus-target-client" data-target="' + name + '" title="Target this client">' + icon('crosshair') + '</button>' +
          '</div>';
        }).join('')
      : '<div class="nexus-empty-clients">' + icon('monitor') + '<p>' + (running ? 'No clients connected' : 'Start server first') + '</p></div>';

    const offlineAccounts = accounts.filter(function (a) { return a.status !== 'Online'; });
    const offlineList = offlineAccounts.length
      ? '<div class="nexus-offline-header">Offline (' + offlineAccounts.length + ')</div>' +
        offlineAccounts.map(function (client) {
          const name = escapeHtml(client.username || 'Unknown');
          return '<div class="nexus-client-row offline">' +
            '<span class="nexus-status-dot offline"></span>' +
            '<div class="nexus-client-info">' +
              '<strong>' + name + '</strong>' +
              '<small>Last: ' + relativeTime(client.connected_at) + '</small>' +
            '</div>' +
          '</div>';
        }).join('')
      : '';

    const clientsPanel =
      '<aside class="nexus-clients-panel panel">' +
        '<div class="panel-head"><h3>' + icon('users') + ' Connected Clients</h3><span>' + onlineAccounts.length + '/' + accounts.length + '</span></div>' +
        '<div class="nexus-clients-list">' + clientList + offlineList + '</div>' +
      '</aside>';

    /* --- Target selector --- */
    const targetOptions = '<option value="all"' + (this.state.nexusExecutorTarget === 'all' ? ' selected' : '') + '>All Clients</option>' +
      onlineAccounts.map(function (client) {
        const name = client.username || 'Unknown';
        return '<option value="' + escapeHtml(name) + '"' + (self.state.nexusExecutorTarget === name ? ' selected' : '') + '>' + escapeHtml(name) + '</option>';
      }).join('');

    /* --- Code editor --- */
    const codeValue = escapeHtml(this.state.nexusExecutorCode || '');
    const editorPanel =
      '<div class="nexus-editor-panel">' +
        '<div class="nexus-editor-toolbar">' +
          '<div class="nexus-editor-toolbar-left">' +
            '<span class="nexus-editor-label">' + icon('code') + ' Lua Script Editor</span>' +
          '</div>' +
          '<div class="nexus-editor-toolbar-right">' +
            '<label class="nexus-target-label">Target:</label>' +
            '<select class="nexus-target-select" id="nexus-exec-target">' + targetOptions + '</select>' +
            '<button class="button button-primary button-sm nexus-exec-btn" type="button" data-action="nexus-execute"' + (!running ? ' disabled title="Start Nexus server first"' : '') + '>' + icon('play') + ' Execute</button>' +
            '<button class="button button-sm" type="button" data-action="nexus-clear-editor" title="Clear editor">' + icon('trash') + '</button>' +
          '</div>' +
        '</div>' +
        '<div class="nexus-editor-wrap">' +
          '<div class="nexus-line-numbers" id="nexus-line-numbers"></div>' +
          '<textarea class="nexus-code-editor" id="nexus-code-editor" spellcheck="false" autocomplete="off" autocorrect="off" autocapitalize="off" wrap="off">' + codeValue + '</textarea>' +
        '</div>' +
      '</div>';

    /* --- Log output console --- */
    const logContent = logEntries.length
      ? logEntries.map(function (entry) {
          const levelClass = entry.level === 'error' ? 'log-error' : entry.level === 'success' ? 'log-success' : entry.level === 'warn' ? 'log-warn' : 'log-info';
          return '<div class="nexus-log-entry ' + levelClass + '">' +
            '<span class="nexus-log-time">' + escapeHtml(entry.time || '') + '</span>' +
            '<span class="nexus-log-target">[' + escapeHtml(entry.target || 'all') + ']</span> ' +
            '<span class="nexus-log-msg">' + escapeHtml(entry.message || '') + '</span>' +
          '</div>';
        }).join('')
      : '<div class="nexus-log-empty">No execution log entries yet. Execute a script to see output here.</div>';

    const logPanel =
      '<div class="nexus-log-panel panel">' +
        '<div class="panel-head"><h3>' + icon('terminal') + ' Execution Log</h3>' +
          '<div style="display:flex;gap:6px;align-items:center">' +
            '<span>' + logEntries.length + ' entries</span>' +
            '<button class="button button-xs" type="button" data-action="nexus-clear-log" title="Clear log">' + icon('trash') + '</button>' +
          '</div>' +
        '</div>' +
        '<div class="nexus-log-output" id="nexus-log-output">' + logContent + '</div>' +
      '</div>';

    /* --- Quick script buttons --- */
    const quickScripts =
      '<div class="nexus-quick-scripts">' +
        '<span class="nexus-quick-label">Quick Scripts:</span>' +
        '<button class="button button-xs" type="button" data-action="nexus-quick" data-script="print(\'Hello from Nexus! ✨\')" title="Test connection">🧪 Hello World</button>' +
        '<button class="button button-xs" type="button" data-action="nexus-quick" data-script="game:GetService(\'TeleportService\'):Teleport(game.PlaceId, game.Players.LocalPlayer)" title="Rejoin current server">🔄 Rejoin Server</button>' +
        '<button class="button button-xs" type="button" data-action="nexus-quick" data-script="game.Players.LocalPlayer:Kick(\'Kicked via Nexus\')" title="Kick from game">🚪 Kick Self</button>' +
        '<button class="button button-xs" type="button" data-action="nexus-quick" data-script="game:GetService(\'SoundService\').MainAudioGroup.Volume = 0" title="Mute game audio">🔇 Mute</button>' +
        '<button class="button button-xs" type="button" data-action="nexus-quick" data-script="game:GetService(\'SoundService\').MainAudioGroup.Volume = 1" title="Unmute game audio">🔊 Unmute</button>' +
        '<button class="button button-xs" type="button" data-action="nexus-quick" data-script="local p = game.Players.LocalPlayer; local h = p.Character and p.Character:FindFirstChild(\'Humanoid\'); if h then h.Health = 0 end" title="Reset character">💀 Reset Character</button>' +
        '<button class="button button-xs" type="button" data-action="nexus-quick" data-script="local p = game.Players.LocalPlayer; local info = {Name=p.Name, UserId=p.UserId, PlaceId=game.PlaceId, JobId=game.JobId}; for k,v in pairs(info) do print(k..\': \'.$tostring(v)) end" title="Print game info">📋 Game Info</button>' +
      '</div>';

    return '<section class="page-heading"><div class="page-heading-copy"><h2>Nexus Lua Executor</h2><p>Execute Lua scripts remotely on connected Roblox clients via the Nexus WebSocket bridge.</p></div></section>' +
      serverBar +
      '<div class="nexus-executor-layout">' +
        '<div class="nexus-main-area">' +
          quickScripts +
          editorPanel +
          logPanel +
        '</div>' +
        clientsPanel +
      '</div>';
  }

  renderInstancesSnapshot() {
    const services = (this.state.diagnostics.services || []).slice(0, 3);
    return '<section class="page-heading"><div class="page-heading-copy"><h2>Every running session, accounted for.</h2><p>Astro Account Manager keeps launch state, process IDs, and lightweight health signals together so active accounts never become guesswork.</p></div><div class="page-heading-actions"><button class="button button-primary" type="button" data-action="refresh-instances">' + icon('refresh') + ' Refresh instances</button></div></section><section class="instance-summary"><article class="panel monitor-card"><h3>Instance watcher</h3><p>Checking active Roblox processes and matching them to your workspace accounts.</p><div class="pulse-track"><svg class="pulse-svg" preserveAspectRatio="none" viewBox="0 0 400 55"><polyline points="0,33 22,33 32,19 42,42 54,28 67,33 97,33 112,18 123,42 138,25 152,33 193,33 204,21 217,38 231,33 279,33 294,16 305,42 320,27 334,33 400,33"></polyline></svg></div><div class="monitor-footer"><span>Last sync <strong>just now</strong></span><span>' + this.state.instances.length + ' tracked process' + (this.state.instances.length === 1 ? '' : 'es') + '</span><span class="status healthy">Healthy</span></div></article><article class="panel"><div class="panel-head"><h3>' + icon('shield') + ' Service health</h3><span>' + escapeHtml(this.state.diagnostics.status || 'Healthy') + '</span></div><div class="health-list">' + services.map(function (service) { return '<div class="health-row"><span class="health-symbol">' + icon(service.status === 'degraded' ? 'alert' : 'check') + '</span><span class="health-copy"><strong>' + escapeHtml(service.name) + '</strong><span>' + escapeHtml(service.detail) + '</span></span><span class="status ' + escapeHtml(service.status || 'healthy') + '"></span></div>'; }).join('') + '</div></article></section><section class="section-header"><h3>Running instances</h3><p>Tracked locally by the desktop bridge</p><span class="section-line"></span></section>' + this.renderInstancesTable();
  }

  renderInstancesTable() {
    if (!this.state.instances.length) return this.emptyState('monitor', 'No Roblox instances found', 'Launch an account to start watching it here.', 'Go to accounts', 'navigate-accounts');
    return '<div class="data-table-wrap"><table class="data-table"><thead><tr><th>Account</th><th>Experience</th><th>State</th><th>Process</th><th>CPU</th><th>Memory</th><th>Started</th><th aria-label="Actions"></th></tr></thead><tbody>' + this.state.instances.map(function (instance) {
      const account = this.state.accounts.find(function (item) { return String(item.id) === String(instance.account_id); }) || { username: 'Unknown', avatar_color: 'neutral' };
      const hidden = Boolean(this.state.hideUsernames);
      const label = hidden ? 'Account #' + String(this.state.accounts.indexOf(account) + 1).padStart(2, '0') : (account.display_name || account.username);
      const username = hidden ? '••••••••' : account.username;
      const leak = instance.memory_leak && instance.memory_leak.probable ? '<span class="badge warning" title="' + escapeHtml(instance.memory_leak.reason || '') + '">Leak?</span>' : '';
      return '<tr><td><div class="table-account">' + avatar(account, 'sm') + '<span><strong>' + escapeHtml(label) + '</strong><small>@' + escapeHtml(username) + '</small></span></div></td><td><span>' + escapeHtml(instance.game || 'Roblox') + '</span><br /><small class="mono">' + escapeHtml(instance.server || '-') + '</small></td><td><span class="status ' + escapeHtml(instance.state || 'running') + '">' + statusText(instance.state || 'running') + '</span></td><td><span class="mono">PID ' + escapeHtml(instance.pid || '-') + '</span></td><td><span class="mono">' + escapeHtml(instance.cpu_percent === null || instance.cpu_percent === undefined ? '—' : instance.cpu_percent + '%') + '</span></td><td><span class="mono">' + escapeHtml(instance.memory_mb === null || instance.memory_mb === undefined ? '—' : instance.memory_mb + ' MB') + '</span> ' + leak + '</td><td><span class="mono">' + relativeTime(instance.started_at) + '</span></td><td><div class="table-actions">' + this.renderInstanceActions(instance) + '</div></td></tr>';
    }.bind(this)).join('') + '</tbody></table></div>';
  }

  renderInstanceActions(instance) {
    const pid = escapeHtml(instance.pid);
    const canClose = Boolean(this.state.instanceMonitor && this.state.instanceMonitor.termination_enabled);
    const bind = instance.state === 'orphaned' ? '<button class="button button-sm" type="button" data-action="open-bind-instance" data-pid="' + pid + '">' + icon('users') + ' Associate</button>' : '';
    const layout = instance.account_id ? '<button class="icon-button" type="button" data-action="save-window-layout" data-pid="' + pid + '" aria-label="Save Roblox window position" title="Save window position">' + icon('database') + '</button><button class="icon-button" type="button" data-action="restore-window-layout" data-pid="' + pid + '" aria-label="Restore Roblox window position" title="Restore window position">' + icon('layout') + '</button>' : '';
    const visibility = instance.visibility || {};
    const visibilityAction = visibility.supported && visibility.window_found ? '<button class="button button-sm" type="button" data-action="set-instance-visibility" data-pid="' + pid + '" data-visible="' + (visibility.hidden ? 'true' : 'false') + '">' + (visibility.hidden ? 'Show' : 'Hide') + '</button>' : '';
    const close = canClose ? '<button class="icon-button" type="button" data-action="open-close-instance" data-pid="' + pid + '" aria-label="Close Roblox process ' + pid + '" title="Close instance">' + icon('x') + '</button>' : '<span class="instance-action-note" title="Enable instance closing in Settings before closing a process">Closing disabled</span>';
    return bind + visibilityAction + layout + close;
  }

  renderInstancesTableSnapshot() {
    if (!this.state.instances.length) return this.emptyState('monitor', 'No Roblox instances found', 'Launch an account to start watching it here.', 'Go to accounts', 'navigate-accounts');
    return '<div class="data-table-wrap"><table class="data-table"><thead><tr><th>Account</th><th>Experience</th><th>State</th><th>Process</th><th>Memory</th><th>Started</th></tr></thead><tbody>' + this.state.instances.map(function (instance) {
      const account = this.state.accounts.find(function (item) { return String(item.id) === String(instance.account_id); }) || { username: 'Unknown', avatar_color: 'neutral' };
      return '<tr><td><div class="table-account">' + avatar(account, 'sm') + '<span><strong>' + escapeHtml(account.display_name || account.username) + '</strong><small>@' + escapeHtml(account.username) + '</small></span></div></td><td><span>' + escapeHtml(instance.game || 'Roblox Home') + '</span><br /><small class="mono">' + escapeHtml(instance.server || '—') + '</small></td><td><span class="status ' + escapeHtml(instance.state || 'running') + '">' + statusText(instance.state || 'running') + '</span></td><td><span class="mono">PID ' + escapeHtml(instance.pid || '—') + '</span></td><td><span class="mono">' + escapeHtml(instance.memory_mb || '—') + ' MB</span></td><td><span class="mono">' + relativeTime(instance.started_at) + '</span></td></tr>';
    }.bind(this)).join('') + '</tbody></table></div>';
  }

  renderMacroBlock(block, index) {
    const kind = String(block.type || 'wait');
    const meta = {
      wait: ['Wait', 'clock', 'Pause before the next action'],
      key_press: ['Press key', 'command', 'Send one bounded key press'],
      mouse_click: ['Click window', 'crosshair', 'Click at a relative position'],
      text: ['Type text', 'terminal', 'Type a short text value'],
      condition: ['Condition', 'filter', 'Continue only when a check matches'],
      launch: ['Launch', 'rocket', 'Open the assigned account'],
      teleport: ['Teleport', 'globe', 'Move to a PlaceId or JobId'],
      restart: ['Restart', 'refresh', 'Restart and continue this run']
    }[kind] || [kind, 'zap', 'Macro action'];
    let fields = '';
    if (kind === 'wait') fields = '<label>Milliseconds<input data-block-field="milliseconds" type="number" min="0" max="60000" value="' + escapeHtml(block.milliseconds || 0) + '" /></label>';
    if (kind === 'key_press') fields = '<label>Key<input data-block-field="key" maxlength="24" value="' + escapeHtml(block.key || 'W') + '" /></label><label>Hold ms<input data-block-field="milliseconds" type="number" min="1" max="10000" value="' + escapeHtml(block.milliseconds || 80) + '" /></label>';
    if (kind === 'mouse_click') fields = '<label>X (0–1)<input data-block-field="x" type="number" min="0" max="1" step="0.01" value="' + escapeHtml(block.x === undefined ? 0.5 : block.x) + '" /></label><label>Y (0–1)<input data-block-field="y" type="number" min="0" max="1" step="0.01" value="' + escapeHtml(block.y === undefined ? 0.5 : block.y) + '" /></label>';
    if (kind === 'text') fields = '<label>Text<input data-block-field="value" maxlength="500" value="' + escapeHtml(block.value || '') + '" /></label>';
    if (kind === 'condition') fields = '<label>Check<select data-block-field="check">' + ['runtime_above', 'runtime_below', 'checkpoint_reached', 'checkpoint_missing', 'variable_equals', 'variable_missing', 'account_running', 'account_stopped'].map(function (name) { return '<option value="' + name + '"' + (String(block.check || 'runtime_above') === name ? ' selected' : '') + '>' + name.replace(/_/g, ' ') + '</option>'; }).join('') + '</select></label><label>Value<input data-block-field="value" maxlength="120" value="' + escapeHtml(block.value || '') + '" placeholder="seconds, name or VAR value" /></label><label>Then<select data-block-field="then"><option value="stop"' + (String(block.then || 'stop') === 'stop' ? ' selected' : '') + '>Stop the macro</option><option value="launch"' + (block.then === 'launch' ? ' selected' : '') + '>Launch the client</option><option value="restart"' + (block.then === 'restart' ? ' selected' : '') + '>Restart the client</option></select></label>';
    if (kind === 'teleport') fields = '<label>Place id<input data-block-field="place_id" maxlength="20" value="' + escapeHtml(block.place_id || '') + '" /></label><label>JobId (optional)<input data-block-field="job_id" maxlength="64" value="' + escapeHtml(block.job_id || '') + '" /></label>';
    if (kind === 'launch' || kind === 'restart') fields = '<label><small>' + (kind === 'launch' ? 'Launches this account, then re-pins the run to the new client.' : 'Closes this account and relaunches it, then continues.') + '</small></label>';
    return '<article class="macro-block" data-block-index="' + index + '" data-block-type="' + escapeHtml(kind) + '"><header class="macro-block-head"><span class="macro-step-number">' + (index + 1) + '</span><span class="macro-block-icon">' + icon(meta[1]) + '</span><div><strong>' + escapeHtml(meta[0]) + '</strong><small>' + escapeHtml(meta[2]) + '</small></div><div class="macro-block-order"><button class="icon-button macro-move-up" type="button" data-action="move-macro-block" data-index="' + index + '" data-direction="-1" aria-label="Move step up"' + (index === 0 ? ' disabled' : '') + '>' + icon('chevronDown') + '</button><button class="icon-button" type="button" data-action="move-macro-block" data-index="' + index + '" data-direction="1" aria-label="Move step down"' + (index === this.state.macroDraftBlocks.length - 1 ? ' disabled' : '') + '>' + icon('chevronDown') + '</button><button class="icon-button danger" type="button" data-action="remove-macro-block" data-index="' + index + '" aria-label="Remove step">' + icon('trash') + '</button></div></header><div class="macro-block-fields">' + fields + '</div></article>';
  }

  renderMacros() {
    const accountOptions = '<option value="">Any matched account</option>' + this.state.accounts.map(function (account) { return '<option value="' + escapeHtml(account.id) + '"' + (String(account.id) === String(this.state.macroDraftAccountId || '') ? ' selected' : '') + '>' + escapeHtml(account.display_name || account.username) + '</option>'; }.bind(this)).join('');
    const singleInstancePid = this.state.instances.length === 1 ? String(this.state.instances[0].pid) : '';
    const instanceOptions = this.state.instances.map(function (instance) { const account = this.findAccount(instance.account_id); return '<option value="' + escapeHtml(instance.pid) + '"' + (String(instance.pid) === singleInstancePid ? ' selected' : '') + '>PID ' + escapeHtml(instance.pid) + ' · ' + escapeHtml(account ? account.display_name || account.username : 'Unassigned Roblox') + '</option>'; }.bind(this)).join('');
    const runs = this.state.macroRuns.length ? this.state.macroRuns.map(function (run) { const delivery = run.delivery_mode === 'minimized_input' ? 'Background delivery' : 'Foreground delivery'; const running = ['running', 'starting'].includes(run.state); return '<article class="macro-run"><span class="macro-run-state ' + (running ? 'is-live' : '') + '"></span><div><strong>' + escapeHtml(run.macro_name) + '</strong><small>PID ' + escapeHtml(run.pid) + ' · step ' + escapeHtml(run.current_step || 0) + '</small><span>' + escapeHtml(delivery) + '</span></div><span class="badge">' + escapeHtml(run.state) + '</span>' + (running ? '<button class="button button-xs button-danger" type="button" data-action="stop-macro" data-id="' + escapeHtml(run.run_id) + '">Stop</button>' : '') + '</article>'; }).join('') : '<div class="macro-empty-run">' + icon('activity') + '<strong>No active run</strong><p>Start a saved macro on a verified instance. Its progress will appear here.</p></div>';
    const cards = this.state.macros.length ? this.state.macros.map(function (macro) { const account = this.findAccount(macro.account_id); const steps = asArray(macro.actions).length; return '<article class="panel macro-card"><div class="macro-card-copy"><div class="macro-card-meta"><span class="badge accent">' + escapeHtml(macro.mode === 'dsl' ? 'DSL' : 'Visual') + '</span><span>' + escapeHtml(steps) + ' step' + (steps === 1 ? '' : 's') + '</span></div><h3>' + escapeHtml(macro.name) + '</h3><p>' + escapeHtml(macro.description || 'No description yet.') + '</p><small>' + escapeHtml(account ? 'Assigned to ' + (account.display_name || account.username) : 'Available for any matched account') + '</small></div><div class="macro-card-actions"><label for="macro-target-' + escapeHtml(macro.id) + '">Run on</label><select id="macro-target-' + escapeHtml(macro.id) + '" aria-label="Target Roblox instance"><option value=""' + (singleInstancePid ? '' : ' selected') + '>Choose a verified instance…</option>' + instanceOptions + '</select><button class="button button-primary" type="button" data-action="start-macro" data-id="' + escapeHtml(macro.id) + '"' + (instanceOptions ? '' : ' disabled') + '>' + icon('play') + ' Run macro</button><button class="icon-button" type="button" data-action="delete-macro" data-id="' + escapeHtml(macro.id) + '" aria-label="Delete macro">' + icon('trash') + '</button></div></article>'; }.bind(this)).join('') : this.emptyInline('zap', 'No saved macros', 'Build your first sequence above, save it, then choose a verified instance.');
    const tools = [
      ['wait', 'clock', 'Wait', 'Pause the sequence'], ['key_press', 'command', 'Key', 'Press and release'], ['mouse_click', 'crosshair', 'Click', 'Relative window point'], ['text', 'terminal', 'Text', 'Type a value'],
      ['condition', 'filter', 'Condition', 'Branch on state'], ['launch', 'rocket', 'Launch', 'Open the account'], ['teleport', 'globe', 'Teleport', 'Change destination'], ['restart', 'refresh', 'Restart', 'Recover and continue']
    ].map(function (tool) { return '<button type="button" class="macro-tool" data-action="add-macro-block" data-kind="' + tool[0] + '"><span>' + icon(tool[1]) + '</span><strong>' + tool[2] + '</strong><small>' + tool[3] + '</small></button>'; }).join('');
    const blockEditor = this.state.macroEditorMode === 'blocks' ? '<section class="macro-builder"><div class="macro-builder-head"><div><h4>Action library</h4><p>Add steps, then reorder them with the arrows.</p></div><span class="badge accent">' + this.state.macroDraftBlocks.length + ' step' + (this.state.macroDraftBlocks.length === 1 ? '' : 's') + '</span></div><div class="macro-tool-grid">' + tools + '</div><div class="macro-sequence-head"><span>Sequence</span><small>Runs from top to bottom</small></div><div class="macro-block-list">' + (this.state.macroDraftBlocks.length ? this.state.macroDraftBlocks.map(this.renderMacroBlock.bind(this)).join('') : '<div class="macro-sequence-empty">' + icon('plus') + '<strong>Your sequence is empty</strong><p>Choose an action above to add the first step.</p></div>') + '</div></section>' : '<section class="macro-code-editor"><header><div><h4>Astro DSL</h4><p>Write the same bounded actions directly.</p></div><span class="badge">No arbitrary code</span></header><textarea id="macro-source" name="source" rows="16" spellcheck="false" placeholder="PRESS W 120&#10;WAIT 1000&#10;CLICK 0.5 0.5&#10;TEXT &quot;hello&quot;">' + escapeHtml(this.state.macroDraftSource) + '</textarea><div class="macro-command-strip"><span>WAIT</span><span>PRESS</span><span>DOWN / UP</span><span>CLICK</span><span>TEXT</span><span>REPEAT</span><span>IF</span><span>LAUNCH</span><span>TELEPORT</span><span>RESTART</span><span>STOP</span></div></section>';
    const visualActive = this.state.macroEditorMode === 'blocks';
    return '<section class="page-heading macro-page-heading"><div class="page-heading-copy"><span class="eyebrow">Per-instance automation</span><h2>Build a sequence. Pick an instance. Run.</h2><p>Visual steps and Astro DSL use the same bounded engine. Each run is pinned to the verified process you choose.</p></div><div class="page-heading-actions"><button class="button" type="button" data-action="refresh-macros">' + icon('refresh') + ' Refresh</button></div></section><section class="macro-workflow" aria-label="Macro workflow"><span class="is-active"><b>1</b> Define</span><i></i><span class="is-active"><b>2</b> Build actions</span><i></i><span><b>3</b> Save &amp; run</span></section><section class="macro-layout"><div class="macro-main"><section class="panel macro-editor-panel"><form data-form="macro"><header class="macro-editor-head"><div><h3>New macro</h3><p>Give this sequence a clear purpose and optional account scope.</p></div><div class="macro-mode-switch" role="group" aria-label="Macro editor mode"><button type="button" class="' + (visualActive ? 'is-active' : '') + '" data-action="set-macro-editor-mode" data-mode="blocks">' + icon('layout') + ' Visual</button><button type="button" class="' + (!visualActive ? 'is-active' : '') + '" data-action="set-macro-editor-mode" data-mode="dsl">' + icon('code') + ' DSL</button></div></header><div class="macro-editor-body"><p class="form-error" hidden></p><input type="hidden" name="mode" value="' + (visualActive ? 'blocks' : 'dsl') + '" /><div class="macro-setup-grid"><div class="field"><label for="macro-draft-name">Name</label><input id="macro-draft-name" name="name" required maxlength="120" value="' + escapeHtml(this.state.macroDraftName) + '" placeholder="Daily rewards" /></div><div class="field"><label for="macro-draft-account">Assigned account</label><select id="macro-draft-account" name="account_id">' + accountOptions + '</select></div><div class="field full"><label for="macro-draft-description">Description</label><input id="macro-draft-description" name="description" maxlength="500" value="' + escapeHtml(this.state.macroDraftDescription) + '" placeholder="What this macro does and when to use it" /></div></div>' + blockEditor + '</div><footer class="macro-editor-foot"><span>' + icon('shield') + ' Local, bounded and tied to a verified PID</span><button class="button button-primary" type="submit">' + icon('check') + ' Save macro</button></footer></form></section><section class="section-header"><h3>Saved macros</h3><p>' + escapeHtml(this.state.macros.length) + ' available</p><span class="section-line"></span></section><div class="macro-cards">' + cards + '</div></div><aside class="panel macro-runs"><div class="panel-head"><h3>' + icon('activity') + ' Live runs</h3><span class="badge">' + escapeHtml(this.state.macroRuns.filter(function (run) { return ['running', 'starting'].includes(run.state); }).length) + ' active</span></div><div class="macro-run-list">' + runs + '</div></aside></section>';
  }

  maybeWarnRunningRoblox() {
    const general = (((this.state.settings || {}).categories || {}).general || {});
    if (this.state.mode === 'desktop' && general.warn_if_roblox_running !== false && this.state.robloxBackground && this.state.robloxBackground.running) {
      this.openModal({ kind: 'roblox-background', status: this.state.robloxBackground });
    }
  }

  /* -------------------------------------------------------------------
     Fleet workspace.  Statistics, scheduler, account health, servers,
     coordination, comfort, alerts, rules and the macro studio all live
     behind one sidebar entry with a tab strip, so nine new screens cost
     the navigation exactly one line.
     ------------------------------------------------------------------- */

  fleetTabList() {
    return [
      ['stats', 'Statistics'], ['schedule', 'Scheduler'], ['health', 'Account health'],
      ['servers', 'Servers'], ['coord', 'Coordination'], ['comfort', 'Comfort'],
      ['alerts', 'Alerts'], ['rules', 'Rules'], ['studio', 'Macro studio'],
      ['profiles', 'Launch profiles']
    ];
  }

  fleetValue(id) {
    const node = document.getElementById(id);
    return node ? String(node.value === undefined || node.value === null ? '' : node.value).trim() : '';
  }

  fleetNumber(id, fallback) {
    const raw = this.fleetValue(id);
    const value = Number(raw);
    return raw === '' || Number.isNaN(value) ? fallback : value;
  }

  fleetChecked(id) {
    const node = document.getElementById(id);
    return Boolean(node && node.checked);
  }

  fleetPicked(id) {
    const node = document.getElementById(id);
    if (!node) return [];
    return Array.prototype.slice.call(node.selectedOptions || []).map(function (option) { return option.value; }).filter(Boolean);
  }

  fleetPairs(id) {
    // "Level=42, Gems=1200" becomes { Level: '42', Gems: '1200' }.
    const pairs = {};
    this.fleetValue(id).split(/[\n,]/).forEach(function (chunk) {
      const parts = String(chunk).split('=');
      const key = String(parts[0] || '').trim();
      if (!key) return;
      pairs[key] = String(parts.slice(1).join('=') || '').trim();
    });
    return pairs;
  }

  fleetList(id) {
    return this.fleetValue(id).split(/[\n,]/).map(function (item) { return String(item).trim(); }).filter(Boolean);
  }

  fleetMinutes(seconds) {
    const value = Number(seconds || 0);
    if (!value) return '0m';
    if (value < 60) return Math.round(value) + 's';
    if (value < 3600) return Math.round(value / 60) + 'm';
    return (value / 3600).toFixed(1) + 'h';
  }

  fleetClock(epochSeconds) {
    if (!epochSeconds) return 'never';
    return new Date(Number(epochSeconds) * 1000).toLocaleString();
  }

  fleetAccountOptions(selected) {
    return this.state.accounts.map(function (account) {
      return '<option value="' + escapeHtml(account.id) + '"' + (String(selected || '') === String(account.id) ? ' selected' : '') + '>' + escapeHtml(account.display_name || account.username) + '</option>';
    }).join('');
  }

  fleetGroupOptions(selected) {
    return this.state.groups.map(function (group) {
      return '<option value="' + escapeHtml(group.id) + '"' + (String(selected || '') === String(group.id) ? ' selected' : '') + '>' + escapeHtml(group.name) + '</option>';
    }).join('');
  }

  fleetMacroOptions(selected) {
    return this.state.macros.map(function (macro) {
      return '<option value="' + escapeHtml(macro.id) + '"' + (String(selected || '') === String(macro.id) ? ' selected' : '') + '>' + escapeHtml(macro.name) + '</option>';
    }).join('');
  }

  async loadFleet(tab) {
    const wanted = tab || this.state.fleetTab || 'stats';
    this.state.fleetTab = wanted;
    if (!this.bridge) { this.render(); return; }
    const data = this.state.fleetData;
    const filters = this.state.fleetFilters;
    const studio = this.state.fleetStudio;
    try {
      if (wanted === 'stats') data.stats = unwrap(await this.bridge.call('get_statistics', this.state.fleetWindowDays)) || {};
      if (wanted === 'schedule') data.schedule = unwrap(await this.bridge.call('list_scheduled_tasks')) || { tasks: [] };
      if (wanted === 'health') data.health = unwrap(await this.bridge.call('get_account_health', { tags: filters.tags, status: filters.status, query: filters.query })) || {};
      if (wanted === 'servers') data.servers = unwrap(await this.bridge.call('get_server_registry', filters.placeId || '')) || {};
      if (wanted === 'comfort') {
        const comfortPayloads = await Promise.all([this.bridge.call('get_comfort_overview', null), this.bridge.call('get_wave_status')]);
        data.comfort = unwrap(comfortPayloads[0]) || {};
        data.wave = unwrap(comfortPayloads[1]) || {};
      }
      if (wanted === 'alerts') data.alerts = unwrap(await this.bridge.call('get_alert_settings')) || {};
      if (wanted === 'rules') data.rules = unwrap(await this.bridge.call('get_rules_overview')) || {};
      if (wanted === 'studio') data.studio = unwrap(await this.bridge.call('get_macro_studio', studio.macroId, studio.accountId)) || {};
      if (wanted === 'profiles') data.profiles = unwrap(await this.bridge.call('list_launch_profiles')) || { profiles: [] };
    } catch (error) {
      this.toast('error', 'Fleet', error.message);
    }
    this.render();
  }

  renderFleet() {
    const tab = this.state.fleetTab || 'stats';
    const strip = this.fleetTabList().map(function (entry) {
      return '<button type="button" class="button button-sm ' + (tab === entry[0] ? 'button-primary' : '') + '" data-action="fleet-tab" data-tab="' + entry[0] + '">' + escapeHtml(entry[1]) + '</button>';
    }).join('');
    let body = '';
    if (tab === 'stats') body = this.renderFleetStats();
    else if (tab === 'schedule') body = this.renderFleetSchedule();
    else if (tab === 'health') body = this.renderFleetHealth();
    else if (tab === 'servers') body = this.renderFleetServers();
    else if (tab === 'coord') body = this.renderFleetCoordination();
    else if (tab === 'comfort') body = this.renderFleetComfort();
    else if (tab === 'alerts') body = this.renderFleetAlerts();
    else if (tab === 'rules') body = this.renderFleetRules();
    else if (tab === 'studio') body = this.renderFleetStudio();
    else body = this.renderFleetProfiles();
    return '<section class="page-heading"><div class="page-heading-copy"><h2>Run the whole fleet from one place.</h2><p>Every number below is measured on this machine. Nothing here closes a live Roblox client on its own.</p></div><div class="page-heading-actions"><button class="button" type="button" data-action="fleet-refresh">' + icon('refresh') + ' Refresh</button></div></section>' +
      '<section class="macro-toolbox" aria-label="Fleet sections">' + strip + '</section>' + body;
  }

  renderFleetStats() {
    const stats = this.state.fleetData.stats || {};
    const totals = stats.totals || {};
    const heatmap = stats.heatmap || { rows: [] };
    const macros = stats.macros || {};
    const days = stats.window_days || 28;
    const peak = heatmap.peak ? heatmap.peak.day + ' ' + heatmap.peak.hour + 'h (' + heatmap.peak.minutes + ' min)' : 'no peak yet';
    const ceiling = Math.max(1, Number(heatmap.peak_minutes || 0));
    const hourAxis = Array.from({ length: 24 }, function (_, hour) { return '<span>' + (hour % 3 === 0 ? String(hour).padStart(2, '0') : '') + '</span>'; }).join('');
    const grid = asArray(heatmap.rows).map(function (row) {
      const cells = asArray(row.hours).map(function (value, hour) {
        const ratio = Math.min(1, Number(value || 0) / ceiling);
        const tint = ratio === 0 ? 'transparent' : 'rgba(99, 102, 241, ' + (0.12 + ratio * 0.78).toFixed(2) + ')';
        const label = row.day + ' at ' + String(hour).padStart(2, '0') + ':00 · ' + value + ' minute' + (Number(value) === 1 ? '' : 's');
        return '<span class="heat-cell" role="img" aria-label="' + escapeHtml(label) + '" title="' + escapeHtml(label) + '" style="background:' + tint + '"></span>';
      }).join('');
      return '<div class="heat-row"><strong>' + escapeHtml(String(row.day || '').slice(0, 3)) + '</strong><div class="heat-cells">' + cells + '</div><small>' + escapeHtml(row.total_minutes) + 'm</small></div>';
    }).join('');
    const reliability = asArray(stats.reliability).slice(0, 12).map(function (row) {
      const score = row.score === null || row.score === undefined ? '—' : row.score + '%';
      return '<tr><td><strong>' + escapeHtml(row.username || row.account_id) + '</strong></td><td>' + escapeHtml(row.sessions) + '</td><td>' + escapeHtml(row.crashes) + '</td><td>' + escapeHtml(row.total_hours) + ' h</td><td>' + escapeHtml(score) + (row.confident === false ? ' <small>(few samples)</small>' : '') + '</td></tr>';
    }).join('');
    const byMacro = asArray(macros.by_macro).slice(0, 8).map(function (row) {
      return '<div class="activity-row"><div class="activity-copy"><strong>' + escapeHtml(row.name || row.macro_id || 'Macro') + '</strong><small>' + escapeHtml(row.completed || 0) + ' completed · ' + escapeHtml(row.failed || 0) + ' failed</small></div><span class="badge">' + escapeHtml(row.success_rate === null || row.success_rate === undefined ? '—' : row.success_rate + '%') + '</span></div>';
    }).join('') || '<div class="empty-notices">' + icon('activity') + '<p>No macro run has finished yet.</p></div>';
    const comparison = this.state.fleetData.comparison;
    let compare = '<p class="mono">Pick an account to compare its two most recent sessions.</p>';
    if (comparison && comparison.available === false) compare = '<p class="mono">' + escapeHtml(comparison.reason || 'Not enough sessions yet.') + '</p>';
    else if (comparison && comparison.comparable) {
      compare = '<div class="activity-row"><div class="activity-copy"><strong>Earlier</strong><small>' + escapeHtml(this.fleetClock(comparison.earlier.started_at)) + ' · ' + escapeHtml(this.fleetMinutes(comparison.earlier.seconds)) + ' · ' + escapeHtml(comparison.earlier.macro_runs) + ' macro run(s)</small></div></div>' +
        '<div class="activity-row"><div class="activity-copy"><strong>Later</strong><small>' + escapeHtml(this.fleetClock(comparison.later.started_at)) + ' · ' + escapeHtml(this.fleetMinutes(comparison.later.seconds)) + ' · ' + escapeHtml(comparison.later.macro_runs) + ' macro run(s)</small></div><span class="badge accent">' + escapeHtml(comparison.verdict) + ' ' + escapeHtml(comparison.delta_percent === null || comparison.delta_percent === undefined ? '' : comparison.delta_percent + '%') + '</span></div>';
    }
    return '<section class="stats-grid">' +
      this.statCard('Sessions', totals.sessions || 0, 'activity', 'Last ' + days + ' days') +
      this.statCard('Hours played', totals.hours || 0, 'monitor', (totals.accounts || 0) + ' account(s)') +
      this.statCard('Crashes', totals.crashes || 0, 'shield', totals.crash_rate === null || totals.crash_rate === undefined ? 'No sessions yet' : totals.crash_rate + '% of sessions') +
      this.statCard('Macro success', macros.success_rate === null || macros.success_rate === undefined ? '—' : macros.success_rate + '%', 'zap', (macros.completed || 0) + ' of ' + (macros.total || 0) + ' runs') +
      '</section>' +
      '<section class="panel heatmap-panel"><div class="panel-head"><div><h3>' + icon('activity') + ' Hourly activity</h3><p>Minutes with a tracked Roblox session, grouped by weekday and hour.</p></div><div class="segmented-control" aria-label="Statistics window"><button type="button" class="' + (days === 7 ? 'is-active' : '') + '" data-action="fleet-stats-window" data-days="7">7 days</button><button type="button" class="' + (days === 28 ? 'is-active' : '') + '" data-action="fleet-stats-window" data-days="28">28 days</button><button type="button" class="' + (days === 90 ? 'is-active' : '') + '" data-action="fleet-stats-window" data-days="90">90 days</button></div></div><div class="heatmap-summary"><span><small>Peak</small><strong>' + escapeHtml(peak) + '</strong></span><span><small>Measured</small><strong>' + escapeHtml(heatmap.total_minutes || 0) + ' min</strong></span><div class="heatmap-legend"><small>Less</small><i></i><i></i><i></i><i></i><i></i><small>More</small></div></div><div class="heatmap-scroll"><div class="heat-axis"><span></span><div>' + hourAxis + '</div><span>total</span></div><div class="heatmap">' + (grid || '<div class="macro-sequence-empty">' + icon('activity') + '<strong>No activity recorded</strong><p>Tracked session minutes will appear here automatically.</p></div>') + '</div></div></section>' +
      '<section class="data-table-wrap"><table class="data-table"><thead><tr><th>Account</th><th>Sessions</th><th>Crashes</th><th>Played</th><th>Reliability</th></tr></thead><tbody>' + (reliability || '<tr><td colspan="5">No account has a recorded session yet.</td></tr>') + '</tbody></table></section>' +
      '<section class="macro-layout"><section class="panel"><div class="panel-head"><h3>' + icon('zap') + ' Macro success rate</h3></div><div class="activity-list">' + byMacro + '</div></section>' +
      '<section class="panel"><div class="panel-head"><h3>' + icon('users') + ' Session comparison</h3></div><div class="form-grid"><div class="field"><label for="fleet-compare-account">Account</label><select id="fleet-compare-account"><option value="">Choose an account…</option>' + this.fleetAccountOptions('') + '</select></div><div class="field"><label>&nbsp;</label><button class="button button-sm button-primary" type="button" data-action="fleet-compare">Compare last two</button></div></div>' + compare + '</section></section>';
  }

  renderFleetSchedule() {
    const schedule = this.state.fleetData.schedule || { tasks: [] };
    const rows = asArray(schedule.tasks).map(function (task) {
      const next = task.next_run_at ? new Date(task.next_run_at * 1000).toLocaleString() : 'never (no day selected)';
      return '<div class="activity-row"><div class="activity-copy"><strong>' + escapeHtml(task.name) + (task.enabled ? '' : ' <span class="badge">paused</span>') + '</strong><small>' + escapeHtml(task.at) + ' · ' + escapeHtml(task.action_label || task.action) + ' · ' + escapeHtml((task.day_labels || []).join(' ')) + ' · next ' + escapeHtml(next) + '</small></div><button class="icon-button" type="button" data-action="fleet-delete-task" data-id="' + escapeHtml(task.id) + '" aria-label="Delete task">' + icon('trash') + '</button></div>';
    }).join('') || '<div class="empty-notices">' + icon('activity') + '<p>No scheduled task yet. 18:00 launch the Farm group, 23:00 stop the macros.</p></div>';
    const dayBoxes = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map(function (label, index) {
      return '<label class="choice"><input type="checkbox" id="fleet-task-day-' + index + '" checked /> ' + label + '</label>';
    }).join('');
    return '<section class="macro-layout"><section class="panel settings-section"><header class="settings-section-head"><div><h3>New scheduled task</h3><p>The watcher checks the clock on every tick and runs a slot once.</p></div></header><div class="form-grid">' +
      '<div class="field"><label for="fleet-task-name">Name</label><input id="fleet-task-name" maxlength="80" placeholder="Launch Farm group" /></div>' +
      '<div class="field"><label for="fleet-task-at">Time</label><input id="fleet-task-at" maxlength="5" placeholder="18:00" /></div>' +
      '<div class="field"><label for="fleet-task-action">Action</label><select id="fleet-task-action"><option value="launch_group">Launch a group</option><option value="launch_accounts">Launch chosen accounts</option><option value="start_macro">Start a macro</option><option value="stop_macros">Stop every macro</option><option value="apply_resource_plan">Apply the resource plan</option><option value="close_instances">Close instances</option></select></div>' +
      '<div class="field"><label for="fleet-task-group">Group</label><select id="fleet-task-group"><option value="">None</option>' + this.fleetGroupOptions('') + '</select></div>' +
      '<div class="field"><label for="fleet-task-macro">Macro</label><select id="fleet-task-macro"><option value="">None</option>' + this.fleetMacroOptions('') + '</select></div>' +
      '<div class="field"><label for="fleet-task-accounts">Accounts</label><select id="fleet-task-accounts" multiple size="4">' + this.fleetAccountOptions('') + '</select></div>' +
      '<div class="field full"><label>Days</label><div class="macro-toolbox">' + dayBoxes + '</div></div>' +
      '</div><footer class="modal-foot"><button class="button button-primary" type="button" data-action="fleet-save-task">' + icon('check') + ' Save task</button><button class="button" type="button" data-action="fleet-run-due">Run what is due now</button></footer></section>' +
      '<section class="panel"><div class="panel-head"><h3>' + icon('activity') + ' Schedule</h3></div><div class="activity-list">' + rows + '</div></section></section>';
  }

  renderFleetHealth() {
    const health = this.state.fleetData.health || {};
    const filters = this.state.fleetFilters;
    const counts = health.counts || {};
    const tagChips = asArray(health.tags).slice(0, 24).map(function (tag) {
      return '<span class="badge">' + escapeHtml(tag.tag) + ' · ' + escapeHtml(tag.count) + '</span>';
    }).join(' ') || '<small>No tag yet.</small>';
    const rows = asArray(health.accounts).map(function (row) {
      const fields = Object.keys(row.custom_fields || {}).map(function (key) { return key + '=' + row.custom_fields[key]; }).join(', ');
      return '<article class="panel"><div class="panel-head"><h3>' + escapeHtml(row.icon || '') + ' ' + escapeHtml(row.display_name || row.username) + '</h3><span class="status ' + escapeHtml(row.tone || 'healthy') + '">' + escapeHtml(row.label) + '</span></div><p class="mono">' + escapeHtml(row.detail || '') + '</p><div class="form-grid">' +
        '<div class="field"><label>Tags</label><input id="fleet-tags-' + escapeHtml(row.id) + '" value="' + escapeHtml((row.tags || []).join(', ')) + '" placeholder="main, farm" /></div>' +
        '<div class="field"><label>Custom fields</label><input id="fleet-fields-' + escapeHtml(row.id) + '" value="' + escapeHtml(fields) + '" placeholder="Level=42, Gems=1200" /></div>' +
        '<div class="field"><label>Priority</label><input id="fleet-priority-' + escapeHtml(row.id) + '" type="number" min="0" max="10" value="' + escapeHtml(row.priority || 0) + '" /></div>' +
        '</div><footer class="modal-foot"><button class="button button-sm" type="button" data-action="fleet-save-tags" data-id="' + escapeHtml(row.id) + '">Save tags</button><button class="button button-sm" type="button" data-action="fleet-save-fields" data-id="' + escapeHtml(row.id) + '">Save fields</button><button class="button button-sm" type="button" data-action="fleet-save-priority" data-id="' + escapeHtml(row.id) + '">Save priority</button></footer></article>';
    }).join('') || '<div class="empty-notices">' + icon('users') + '<p>No account matches those filters.</p></div>';
    return '<section class="stats-grid">' +
      this.statCard('Accounts', health.total || 0, 'users', (health.shown || 0) + ' shown') +
      this.statCard('Need attention', health.needs_attention || 0, 'shield', 'Session expired or auth required') +
      this.statCard('Healthy', counts.ok || 0, 'check', 'Ready to launch') +
      this.statCard('Roblox closed', counts.idle || 0, 'monitor', 'No client running') +
      '</section>' +
      '<section class="panel"><div class="panel-head"><h3>' + icon('search') + ' Filters</h3></div><div class="form-grid"><div class="field"><label for="fleet-health-query">Search</label><input id="fleet-health-query" value="' + escapeHtml(filters.query || '') + '" placeholder="username, tag or field" /></div><div class="field"><label for="fleet-health-tags">Tags</label><input id="fleet-health-tags" value="' + escapeHtml((filters.tags || []).join(', ')) + '" placeholder="farm, trade" /></div><div class="field"><label for="fleet-health-status">Status</label><select id="fleet-health-status"><option value="">Any</option><option value="ok">OK</option><option value="session_expired">Session expired</option><option value="auth_required">Authentication required</option><option value="launch_failed">Launch failed</option><option value="idle">Roblox closed</option></select></div><div class="field"><label>&nbsp;</label><button class="button button-sm button-primary" type="button" data-action="fleet-health-filter">Apply</button></div></div><p>' + tagChips + '</p></section>' +
      '<section class="macro-cards">' + rows + '</section>';
  }

  renderFleetServers() {
    const registry = this.state.fleetData.servers || {};
    const picked = this.state.fleetData.picked;
    const rows = asArray(registry.servers).slice(0, 40).map(function (row) {
      const action = row.blacklisted
        ? '<button class="button button-sm" type="button" data-action="fleet-unblacklist" data-id="' + escapeHtml(row.job_id) + '">Allow</button>'
        : '<button class="button button-sm button-danger" type="button" data-action="fleet-blacklist" data-id="' + escapeHtml(row.job_id) + '">Blacklist</button>';
      return '<tr><td><span class="mono">' + escapeHtml(row.job_id) + '</span></td><td>' + escapeHtml(row.region || '—') + '</td><td>' + escapeHtml(row.players) + '/' + escapeHtml(row.max_players) + '</td><td>' + escapeHtml(row.fill_percent === null || row.fill_percent === undefined ? '—' : row.fill_percent + '%') + '</td><td>' + escapeHtml(row.joins) + ' / ' + escapeHtml(row.failures) + '</td><td>' + escapeHtml(this.fleetMinutes(row.uptime_seconds)) + '</td><td>' + action + '</td></tr>';
    }.bind(this)).join('') || '<tr><td colspan="7">No server has been recorded yet. Join one and it will be remembered.</td></tr>';
    const regions = asArray(registry.regions).map(function (row) {
      return '<span class="badge">' + escapeHtml(row.region || 'unknown') + ' · ' + escapeHtml(row.servers || row.count || 0) + '</span>';
    }).join(' ') || '<small>No region recorded yet.</small>';
    let pick = '';
    if (picked) {
      pick = picked.found
        ? '<p class="mono">Best server: ' + escapeHtml(picked.job_id) + ' — ' + escapeHtml(picked.reason) + '</p>'
        : '<p class="mono">' + escapeHtml(picked.reason) + '</p>';
    }
    return '<section class="stats-grid">' +
      this.statCard('Known servers', registry.total || 0, 'gamepad', 'Recorded from your joins') +
      this.statCard('Blacklisted', registry.blacklisted || 0, 'shield', 'Never picked again') +
      '</section>' +
      '<section class="panel"><div class="panel-head"><h3>' + icon('search') + ' Smart hopping</h3></div><div class="form-grid"><div class="field"><label for="fleet-server-place">Place id</label><input id="fleet-server-place" placeholder="e.g. 920587237" /></div><div class="field"><label for="fleet-server-region">Preferred region</label><input id="fleet-server-region" maxlength="12" placeholder="eu, us…" /></div><div class="field"><label>&nbsp;</label><button class="button button-sm" type="button" data-action="fleet-server-filter">Filter history</button></div><div class="field"><label>&nbsp;</label><button class="button button-sm button-primary" type="button" data-action="fleet-pick-server">Pick the best server</button></div></div>' + pick + '<p>' + regions + '</p></section>' +
      '<section class="data-table-wrap"><table class="data-table"><thead><tr><th>JobId</th><th>Region</th><th>Players</th><th>Fill</th><th>Joins / fails</th><th>Uptime</th><th></th></tr></thead><tbody>' + rows + '</tbody></table></section>';
  }

  renderFleetCoordination() {
    const plan = this.state.fleetData.plan;
    const steps = plan ? asArray(plan.steps).map(function (step) {
      return '<div class="activity-row"><div class="activity-copy"><strong>' + escapeHtml(step.username || step.account_id) + '</strong><small>#' + escapeHtml(step.order) + ' · +' + escapeHtml(step.offset_seconds) + 's · ' + escapeHtml(step.role || 'member') + (step.job_id ? ' · ' + escapeHtml(step.job_id) : '') + '</small></div></div>';
    }).join('') : '';
    const summary = plan ? '<p class="mono">' + escapeHtml(plan.note || '') + '</p>' : '<p class="mono">Choose a mode and preview the plan before anything launches.</p>';
    return '<section class="macro-layout"><section class="panel settings-section"><header class="settings-section-head"><div><h3>Coordinated launch</h3><p>Preview first. Running a plan queues it through the wave launcher.</p></div></header><div class="form-grid">' +
      '<div class="field"><label for="fleet-coord-mode">Mode</label><select id="fleet-coord-mode"><option value="spread">Spread across servers</option><option value="followers">Main + followers</option><option value="sync">Synchronised launch</option><option value="party">Internal party (same server)</option></select></div>' +
      '<div class="field"><label for="fleet-coord-accounts">Accounts (first one is the main)</label><select id="fleet-coord-accounts" multiple size="6">' + this.fleetAccountOptions('') + '</select></div>' +
      '<div class="field"><label for="fleet-coord-place">Place id</label><input id="fleet-coord-place" placeholder="optional" /></div>' +
      '<div class="field"><label for="fleet-coord-job">JobId</label><input id="fleet-coord-job" placeholder="optional" /></div>' +
      '<div class="field"><label for="fleet-coord-stagger">Stagger (seconds)</label><input id="fleet-coord-stagger" type="number" min="0" max="60" step="0.5" value="1.5" /></div>' +
      '<div class="field"><label for="fleet-coord-max">Accounts per server</label><input id="fleet-coord-max" type="number" min="1" max="20" value="1" /></div>' +
      '</div><footer class="modal-foot"><button class="button" type="button" data-action="fleet-plan-coord">Preview plan</button><button class="button button-primary" type="button" data-action="fleet-run-coord">' + icon('play') + ' Run plan</button></footer></section>' +
      '<section class="panel"><div class="panel-head"><h3>' + icon('users') + ' Plan</h3></div>' + summary + '<div class="activity-list">' + (steps || '<div class="empty-notices">' + icon('activity') + '<p>No plan previewed yet.</p></div>') + '</div></section></section>';
  }

  renderFleetComfort() {
    const comfort = this.state.fleetData.comfort || {};
    const wave = this.state.fleetData.wave || {};
    const gate = comfort.queue || wave.gate || {};
    const audio = comfort.audio || {};
    const sleep = comfort.sleep || {};
    const shutdown = comfort.shutdown || {};
    const instances = asArray(comfort.instances);
    const mixer = instances.map(function (row) {
      const level = ((audio.targets || []).filter(function (target) { return target.pid === row.pid; })[0] || {}).volume;
      return '<div class="activity-row"><div class="activity-copy"><strong>' + escapeHtml(row.username || ('PID ' + row.pid)) + '</strong><small>PID ' + escapeHtml(row.pid) + (row.macro_running ? ' · macro running' : '') + '</small></div><input id="fleet-volume-' + escapeHtml(row.pid) + '" type="number" min="0" max="100" value="' + escapeHtml(level === undefined ? 100 : level) + '" /></div>';
    }).join('') || '<div class="empty-notices">' + icon('monitor') + '<p>No Roblox client is running.</p></div>';
    const focusOptions = instances.map(function (row) {
      return '<option value="' + escapeHtml(row.pid) + '">' + escapeHtml(row.username || ('PID ' + row.pid)) + '</option>';
    }).join('');
    return '<section class="stats-grid">' +
      this.statCard('Launch queue', gate.allowed === false ? 'Holding' : 'Open', 'activity', escapeHtml(gate.reason || 'The machine has room.')) +
      this.statCard('CPU', gate.cpu_percent === null || gate.cpu_percent === undefined ? '—' : gate.cpu_percent + '%', 'monitor', 'Limit ' + (gate.max_cpu_percent || 80) + '%') +
      this.statCard('Memory', gate.memory_percent === null || gate.memory_percent === undefined ? '—' : gate.memory_percent + '%', 'database', 'Limit ' + (gate.max_memory_percent || 85) + '%') +
      this.statCard('Wave', (wave.wave || 0) + '/' + (wave.waves || 0), 'zap', wave.in_progress ? 'Launching' : 'Idle') +
      '</section>' +
      '<section class="macro-layout"><section class="panel"><div class="panel-head"><h3>' + icon('monitor') + ' Focus &amp; sleep</h3></div><div class="form-grid"><div class="field"><label for="fleet-focus-pid">Keep the focus on</label><select id="fleet-focus-pid"><option value="">Choose an instance…</option>' + focusOptions + '</select></div><div class="field"><label>&nbsp;</label><button class="button button-sm button-primary" type="button" data-action="fleet-comfort-focus">Focus this one</button></div></div><p class="mono">Sleep mode minimises clients idle for more than ' + escapeHtml(sleep.idle_minutes || 15) + ' minutes. Macro windows are never touched: minimising them would break foreground input.</p><footer class="modal-foot"><button class="button button-sm" type="button" data-action="fleet-comfort-sleep">Sleep idle clients (' + escapeHtml(sleep.count || 0) + ')</button><button class="button button-sm button-danger" type="button" data-action="fleet-comfort-shutdown">Safe shutdown (' + escapeHtml(shutdown.instances || 0) + ')</button><button class="button button-sm button-danger" type="button" data-action="fleet-emergency-stop">' + icon('alert') + ' Emergency stop</button></footer></section>' +
      '<section class="panel"><div class="panel-head"><h3>' + icon('activity') + ' Audio mixer</h3></div><p class="mono">' + escapeHtml(audio.note || 'Per-process audio control is unavailable on this machine, so levels are stored only.') + '</p><div class="activity-list">' + mixer + '</div><footer class="modal-foot"><button class="button button-sm" type="button" data-action="fleet-comfort-audio">Save levels</button></footer></section></section>';
  }

  renderFleetAlerts() {
    const alerts = this.state.fleetData.alerts || {};
    const report = this.state.fleetData.report;
    const events = asArray(alerts.known_events).map(function (name) {
      const on = (alerts.events || []).indexOf(name) !== -1;
      return '<label class="choice"><input type="checkbox" id="fleet-alert-event-' + escapeHtml(name) + '"' + (on ? ' checked' : '') + ' /> ' + escapeHtml(name.replace(/_/g, ' ')) + '</label>';
    }).join('') || '<small>No event type is available.</small>';
    const preview = report ? '<pre class="mono">' + escapeHtml(String(report.title || '') + '\n' + String(report.body || '')) + '</pre>' : '<p class="mono">Build the report to see today\'s summary.</p>';
    return '<section class="macro-layout"><section class="panel settings-section"><header class="settings-section-head"><div><h3>Alert channels</h3><p>Webhook addresses are write-only: once saved, Astro shows only whether one exists.</p></div></header><div class="form-grid">' +
      '<div class="field"><label class="choice"><input type="checkbox" id="fleet-alert-enabled"' + (alerts.enabled ? ' checked' : '') + ' /> Send alerts</label></div>' +
      '<div class="field"><label for="fleet-alert-interval">Minimum gap (seconds)</label><input id="fleet-alert-interval" type="number" min="0" max="86400" value="' + escapeHtml(alerts.min_interval_seconds || 0) + '" /></div>' +
      '<div class="field"><label for="fleet-alert-discord">Discord webhook ' + (alerts.discord_configured ? '(configured)' : '') + '</label><input id="fleet-alert-discord" type="password" placeholder="https://discord.com/api/webhooks/…" /></div>' +
      '<div class="field"><label for="fleet-alert-phone">Phone relay webhook ' + (alerts.phone_configured ? '(configured)' : '') + '</label><input id="fleet-alert-phone" type="password" placeholder="https://ntfy.sh/…" /></div>' +
      '<div class="field"><label for="fleet-alert-topic">Phone topic</label><input id="fleet-alert-topic" maxlength="60" value="' + escapeHtml(alerts.phone_topic || '') + '" /></div>' +
      '<div class="field"><label for="fleet-alert-report-at">Daily report time</label><input id="fleet-alert-report-at" maxlength="5" placeholder="09:00" value="' + escapeHtml(alerts.daily_report_at || '') + '" /></div>' +
      '<div class="field full"><label>Events</label><div class="macro-toolbox">' + events + '</div></div>' +
      '</div><footer class="modal-foot"><button class="button button-primary" type="button" data-action="fleet-alerts-save">' + icon('check') + ' Save</button><button class="button" type="button" data-action="fleet-alerts-test">Send a test</button></footer></section>' +
      '<section class="panel"><div class="panel-head"><h3>' + icon('activity') + ' Daily report</h3><button class="button button-sm" type="button" data-action="fleet-alerts-report">Build now</button></div>' + preview + '</section></section>';
  }

  renderFleetRules() {
    const overview = this.state.fleetData.rules || {};
    const rules = overview.rules || {};
    const decisions = asArray(overview.decisions).slice(0, 20).map(function (row) {
      return '<div class="activity-row"><div class="activity-copy"><strong>' + escapeHtml(row.rule || row.reason || 'Rule') + '</strong><small>' + escapeHtml(row.detail || row.summary || '') + '</small></div><span class="badge">' + escapeHtml(row.action || row.outcome || '') + '</span></div>';
    }).join('') || '<div class="empty-notices">' + icon('shield') + '<p>No rule has fired yet.</p></div>';
    const resumes = asArray((overview.resumes || {}).pending_resumes).map(function (row) {
      return '<div class="activity-row"><div class="activity-copy"><strong>' + escapeHtml(row.username || row.account_id) + '</strong><small>macro ' + escapeHtml(row.macro_id) + ' · attempt ' + escapeHtml(row.attempts) + ' · ' + escapeHtml(row.reason || '') + '</small></div></div>';
    }).join('') || '<div class="empty-notices">' + icon('zap') + '<p>No macro is waiting for a relaunch.</p></div>';
    const priorities = asArray(overview.priorities).slice(0, 12).map(function (row) {
      return '<tr><td>' + escapeHtml(row.username || row.id) + '</td><td>' + escapeHtml(row.priority) + '</td></tr>';
    }).join('') || '<tr><td colspan="2">No priority set. Everything is treated equally.</td></tr>';
    return '<section class="macro-layout"><section class="panel settings-section"><header class="settings-section-head"><div><h3>Rule engine</h3><p>Rules pause, relaunch and warn. Closing a live client always needs a person.</p></div></header><div class="form-grid">' +
      '<div class="field"><label class="choice"><input type="checkbox" id="fleet-rule-enabled"' + (rules.enabled ? ' checked' : '') + ' /> Run the rule engine</label></div>' +
      '<div class="field"><label class="choice"><input type="checkbox" id="fleet-rule-restart"' + (rules.restart_stuck_macros ? ' checked' : '') + ' /> Restart a stuck macro</label></div>' +
      '<div class="field"><label for="fleet-rule-stuck">Macro stuck after (seconds)</label><input id="fleet-rule-stuck" type="number" min="10" max="3600" value="' + escapeHtml(rules.macro_stuck_seconds || 60) + '" /></div>' +
      '<div class="field"><label for="fleet-rule-runtime">Restart Roblox after (hours)</label><input id="fleet-rule-runtime" type="number" min="1" max="48" step="0.5" value="' + escapeHtml(rules.max_runtime_hours || 6) + '" /></div>' +
      '<div class="field"><label for="fleet-rule-cpu">Pause low priority above CPU %</label><input id="fleet-rule-cpu" type="number" min="10" max="100" value="' + escapeHtml(rules.cpu_pause_percent || 90) + '" /></div>' +
      '<div class="field"><label for="fleet-rule-memory">Pause low priority above memory %</label><input id="fleet-rule-memory" type="number" min="10" max="100" value="' + escapeHtml(rules.memory_pause_percent || 90) + '" /></div>' +
      '<div class="field"><label for="fleet-rule-priority">Low priority means at or below</label><input id="fleet-rule-priority" type="number" min="0" max="10" value="' + escapeHtml(rules.pause_priority_at_or_below || 3) + '" /></div>' +
      '</div><footer class="modal-foot"><button class="button button-primary" type="button" data-action="fleet-rules-save">' + icon('check') + ' Save rules</button></footer></section>' +
      '<section class="panel"><div class="panel-head"><h3>' + icon('activity') + ' Recent decisions</h3></div><div class="activity-list">' + decisions + '</div><div class="panel-head"><h3>' + icon('zap') + ' Macro resumes waiting</h3></div><div class="activity-list">' + resumes + '</div><div class="data-table-wrap"><table class="data-table"><thead><tr><th>Account</th><th>Priority</th></tr></thead><tbody>' + priorities + '</tbody></table></div></section></section>';
  }

  renderFleetStudio() {
    const studio = this.state.fleetData.studio || {};
    const debug = this.state.fleetData.debug;
    const selection = this.state.fleetStudio;
    const steps = asArray((debug || studio).steps).slice(0, 60).map(function (step) {
      return '<div class="activity-row" style="padding-left:' + (12 + Number(step.depth || 0) * 18) + 'px"><div class="activity-copy"><strong>' + escapeHtml(step.path) + ' · ' + escapeHtml(step.label) + '</strong><small>' + escapeHtml(step.type) + ' · ~' + escapeHtml(step.estimated_ms) + ' ms</small></div></div>';
    }).join('') || '<div class="empty-notices">' + icon('zap') + '<p>Choose a macro to inspect its steps.</p></div>';
    const report = studio.profile_report || {};
    const versions = asArray(studio.versions).map(function (row) {
      return '<div class="activity-row"><div class="activity-copy"><strong>v' + escapeHtml(row.version) + ' ' + escapeHtml(row.label || '') + '</strong><small>' + escapeHtml(row.name) + ' · ' + escapeHtml(row.steps) + ' step(s)</small></div><button class="button button-sm" type="button" data-action="fleet-studio-rollback" data-version="' + escapeHtml(row.version) + '">Restore</button></div>';
    }).join('') || '<div class="empty-notices">' + icon('activity') + '<p>No snapshot yet.</p></div>';
    const profiles = asArray(studio.profiles).map(function (profile) {
      const keys = Object.keys(profile.keys || {}).map(function (key) { return key + '=' + profile.keys[key]; }).join(', ');
      return '<div class="activity-row"><div class="activity-copy"><strong>' + escapeHtml(profile.name) + '</strong><small>' + escapeHtml(keys) + '</small></div><button class="icon-button" type="button" data-action="fleet-studio-delete-profile" data-id="' + escapeHtml(profile.name) + '" aria-label="Delete profile">' + icon('trash') + '</button></div>';
    }).join('') || '<div class="empty-notices">' + icon('command') + '<p>No key profile yet.</p></div>';
    const variables = Object.keys(studio.variables || {}).map(function (key) { return key + '=' + studio.variables[key]; }).join(', ');
    const missing = asArray(debug && debug.missing_variables);
    return '<section class="macro-layout"><section class="panel settings-section"><header class="settings-section-head"><div><h3>Macro studio</h3><p>Step-by-step debugger, profiler, key profiles, per-account variables and versions.</p></div></header><div class="form-grid">' +
      '<div class="field"><label for="fleet-studio-macro">Macro</label><select id="fleet-studio-macro"><option value="">Choose a macro…</option>' + this.fleetMacroOptions(selection.macroId) + '</select></div>' +
      '<div class="field"><label for="fleet-studio-account">Account</label><select id="fleet-studio-account"><option value="">Any account</option>' + this.fleetAccountOptions(selection.accountId) + '</select></div>' +
      '<div class="field"><label>&nbsp;</label><button class="button button-sm" type="button" data-action="fleet-studio-load">Load</button></div>' +
      '<div class="field"><label>&nbsp;</label><button class="button button-sm button-primary" type="button" data-action="fleet-studio-debug">Debug steps</button></div>' +
      '<div class="field full"><label for="fleet-studio-variables">Variables for this account</label><input id="fleet-studio-variables" value="' + escapeHtml(variables) + '" placeholder="FarmKey=E, Slot=3" /></div>' +
      '<div class="field"><label for="fleet-studio-profile-name">Key profile name</label><input id="fleet-studio-profile-name" maxlength="60" placeholder="Azerty farm" /></div>' +
      '<div class="field"><label for="fleet-studio-profile-keys">Key remaps</label><input id="fleet-studio-profile-keys" placeholder="W=Z, A=Q" /></div>' +
      '<div class="field"><label for="fleet-studio-group">Group</label><select id="fleet-studio-group"><option value="">Choose a group…</option>' + this.fleetGroupOptions('') + '</select></div>' +
      '<div class="field"><label for="fleet-studio-label">Snapshot label</label><input id="fleet-studio-label" maxlength="60" placeholder="before rewrite" /></div>' +
      '</div><footer class="modal-foot"><button class="button button-sm" type="button" data-action="fleet-studio-save-variables">Save variables</button><button class="button button-sm" type="button" data-action="fleet-studio-save-profile">Save key profile</button><button class="button button-sm" type="button" data-action="fleet-studio-snapshot">Snapshot version</button><button class="button button-sm button-primary" type="button" data-action="fleet-studio-group-run">' + icon('play') + ' Run on group</button></footer>' +
      (missing.length ? '<p class="mono">Missing variables: ' + escapeHtml(missing.join(', ')) + '</p>' : '') +
      '<p class="mono">' + escapeHtml(report.steps || 0) + ' step(s) · about ' + escapeHtml(report.estimated_seconds || 0) + ' s per pass. ' + escapeHtml(report.note || '') + '</p></section>' +
      '<section class="panel"><div class="panel-head"><h3>' + icon('activity') + ' Steps</h3></div><div class="activity-list">' + steps + '</div><div class="panel-head"><h3>' + icon('command') + ' Key profiles</h3></div><div class="activity-list">' + profiles + '</div><div class="panel-head"><h3>' + icon('database') + ' Versions</h3></div><div class="activity-list">' + versions + '</div></section></section>';
  }

  async handleFleetAction(action, button) {
    if (typeof action !== 'string' || action.indexOf('fleet-') !== 0) return false;
    const data = this.state.fleetData;
    const filters = this.state.fleetFilters;
    const studio = this.state.fleetStudio;
    try {
      if (action === 'fleet-tab') { await this.loadFleet(button.dataset.tab); return true; }
      if (action === 'fleet-refresh') { await this.loadFleet(this.state.fleetTab); return true; }
      if (action === 'fleet-profile-save') {
        const payload = {
          name: this.fleetValue('fleet-profile-name'),
          place_id: this.fleetValue('fleet-profile-place'),
          job_id: this.fleetValue('fleet-profile-job'),
          link_code: this.fleetValue('fleet-profile-link'),
          fps: this.fleetNumber('fleet-profile-fps', 0),
          group_id: this.fleetValue('fleet-profile-group'),
          note: this.fleetValue('fleet-profile-note')
        };
        this.state.fleetData.profiles = unwrap(await this.bridge.call('save_launch_profile', payload)) || { profiles: [] };
        this.toast('success', 'Launch profile saved', payload.name);
        this.render(); return true;
      }
      if (action === 'fleet-profile-delete') {
        this.state.fleetData.profiles = unwrap(await this.bridge.call('delete_launch_profile', button.dataset.id)) || { profiles: [] };
        this.toast('success', 'Launch profile deleted', 'The destination is gone. Nothing was closed.');
        this.render(); return true;
      }
      if (action === 'fleet-profile-launch') {
        const picked = this.fleetPicked('fleet-profile-accounts');
        const result = unwrap(await this.bridge.call('launch_with_profile', button.dataset.id, picked)) || {};
        const name = result.profile && result.profile.name ? result.profile.name + ': ' : '';
        const queued = Array.isArray(result.queued) ? result.queued.length : picked.length;
        this.toast('success', 'Launch profile started', name + queued + ' account(s) queued.' + (result.note ? ' ' + result.note : ''));
        return true;
      }
      if (action === 'fleet-emergency-stop') {
        const stop = unwrap(await this.bridge.call('emergency_stop', { disarm_rules: true })) || {};
        this.toast('success', 'Emergency stop', (stop.macros_stopped || 0) + ' macro run(s) stopped and queued launches cancelled'
          + (stop.rules_disarmed ? ', automatic rules disarmed' : '') + '. Running clients were left open on purpose.');
        await this.loadFleet(this.state.fleetTab); return true;
      }
      if (action === 'fleet-stats-window') { this.state.fleetWindowDays = Number(button.dataset.days) || null; await this.loadFleet('stats'); return true; }
      if (action === 'fleet-compare') {
        const accountId = this.fleetValue('fleet-compare-account');
        if (!accountId) { this.toast('warning', 'Choose an account', 'Pick which account to compare.'); return true; }
        data.comparison = unwrap(await this.bridge.call('compare_account_sessions', accountId)) || {};
        this.render();
        return true;
      }
      if (action === 'fleet-save-task') {
        const days = [];
        for (let index = 0; index < 7; index += 1) { if (this.fleetChecked('fleet-task-day-' + index)) days.push(index); }
        const task = {
          name: this.fleetValue('fleet-task-name'),
          at: this.fleetValue('fleet-task-at'),
          action: this.fleetValue('fleet-task-action'),
          group_id: this.fleetValue('fleet-task-group'),
          macro_id: this.fleetValue('fleet-task-macro'),
          account_ids: this.fleetPicked('fleet-task-accounts'),
          days: days,
          enabled: true
        };
        await this.bridge.call('save_scheduled_task', task);
        this.toast('success', 'Task saved', task.name + ' runs at ' + task.at + '.');
        await this.loadFleet('schedule');
        return true;
      }
      if (action === 'fleet-delete-task') { await this.bridge.call('delete_scheduled_task', button.dataset.id); await this.loadFleet('schedule'); return true; }
      if (action === 'fleet-run-due') {
        const outcome = unwrap(await this.bridge.call('run_due_scheduled_tasks')) || {};
        this.toast('success', 'Schedule checked', asArray(outcome.ran).length + ' task(s) ran.');
        await this.loadFleet('schedule');
        return true;
      }
      if (action === 'fleet-health-filter') {
        filters.query = this.fleetValue('fleet-health-query');
        filters.tags = this.fleetList('fleet-health-tags');
        filters.status = this.fleetValue('fleet-health-status');
        await this.loadFleet('health');
        return true;
      }
      if (action === 'fleet-save-tags') {
        await this.bridge.call('update_account_tags', button.dataset.id, this.fleetList('fleet-tags-' + button.dataset.id));
        this.toast('success', 'Tags saved', 'The account tags were updated.');
        await this.loadFleet('health');
        return true;
      }
      if (action === 'fleet-save-fields') {
        await this.bridge.call('update_account_fields', button.dataset.id, this.fleetPairs('fleet-fields-' + button.dataset.id));
        this.toast('success', 'Fields saved', 'Custom fields were updated.');
        await this.loadFleet('health');
        return true;
      }
      if (action === 'fleet-save-priority') {
        await this.bridge.call('set_account_priority', button.dataset.id, this.fleetNumber('fleet-priority-' + button.dataset.id, 0));
        await this.loadFleet('health');
        return true;
      }
      if (action === 'fleet-server-filter') { filters.placeId = this.fleetValue('fleet-server-place'); await this.loadFleet('servers'); return true; }
      if (action === 'fleet-blacklist') { await this.bridge.call('update_server_blacklist', button.dataset.id, true, ''); await this.loadFleet('servers'); return true; }
      if (action === 'fleet-unblacklist') { await this.bridge.call('update_server_blacklist', button.dataset.id, false, ''); await this.loadFleet('servers'); return true; }
      if (action === 'fleet-pick-server') {
        data.picked = unwrap(await this.bridge.call('pick_best_server', { place_id: this.fleetValue('fleet-server-place'), prefer_region: this.fleetValue('fleet-server-region') })) || {};
        this.render();
        return true;
      }
      if (action === 'fleet-plan-coord' || action === 'fleet-run-coord') {
        const payload = {
          mode: this.fleetValue('fleet-coord-mode'),
          account_ids: this.fleetPicked('fleet-coord-accounts'),
          place_id: this.fleetValue('fleet-coord-place'),
          job_id: this.fleetValue('fleet-coord-job'),
          stagger_seconds: this.fleetNumber('fleet-coord-stagger', 1.5),
          max_per_server: this.fleetNumber('fleet-coord-max', 1)
        };
        if (!payload.account_ids.length) { this.toast('warning', 'Choose accounts', 'Select at least one account.'); return true; }
        if (action === 'fleet-plan-coord') {
          data.plan = unwrap(await this.bridge.call('plan_coordination', payload)) || {};
          this.render();
          return true;
        }
        const outcome = unwrap(await this.bridge.call('run_coordination', payload)) || {};
        data.plan = outcome.plan || data.plan;
        this.toast('success', 'Coordination queued', asArray((outcome.plan || {}).steps).length + ' account(s) queued through the wave launcher.');
        this.render();
        return true;
      }
      if (action === 'fleet-comfort-focus') {
        const pid = this.fleetValue('fleet-focus-pid');
        if (!pid) { this.toast('warning', 'Choose an instance', 'Pick which client keeps the focus.'); return true; }
        const plan = unwrap(await this.bridge.call('apply_comfort_action', 'focus', { pid: Number(pid) })) || {};
        this.toast('success', 'Focus applied', (plan.minimized || 0) + ' window(s) minimised.');
        await this.loadFleet('comfort');
        return true;
      }
      if (action === 'fleet-comfort-sleep') {
        const plan = unwrap(await this.bridge.call('apply_comfort_action', 'sleep', {})) || {};
        this.toast('success', 'Sleep applied', (plan.minimized || 0) + ' idle window(s) minimised.');
        await this.loadFleet('comfort');
        return true;
      }
      if (action === 'fleet-comfort-audio') {
        const volumes = {};
        asArray((data.comfort || {}).instances).forEach(function (row) {
          volumes[String(row.pid)] = this.fleetNumber('fleet-volume-' + row.pid, 100);
        }.bind(this));
        await this.bridge.call('apply_comfort_action', 'audio', { volumes: volumes });
        this.toast('success', 'Levels saved', 'Per-instance levels were stored.');
        await this.loadFleet('comfort');
        return true;
      }
      if (action === 'fleet-comfort-shutdown') {
        const preview = unwrap(await this.bridge.call('apply_comfort_action', 'shutdown', {})) || {};
        if (!preview.ready) { this.toast('warning', 'Nothing to close', 'No Roblox client is running.'); return true; }
        if (!window.confirm('Stop every macro and close ' + (preview.instances || 0) + ' Roblox client(s)?')) return true;
        const done = unwrap(await this.bridge.call('apply_comfort_action', 'shutdown', { confirm: true })) || {};
        this.toast('success', 'Safe shutdown', (done.closed || 0) + ' client(s) closed after their macros stopped.');
        await this.loadFleet('comfort');
        return true;
      }
      if (action === 'fleet-alerts-save') {
        const known = asArray((data.alerts || {}).known_events);
        const chosen = known.filter(function (name) { return this.fleetChecked('fleet-alert-event-' + name); }.bind(this));
        const payload = {
          enabled: this.fleetChecked('fleet-alert-enabled'),
          min_interval_seconds: this.fleetNumber('fleet-alert-interval', 0),
          phone_topic: this.fleetValue('fleet-alert-topic'),
          daily_report_at: this.fleetValue('fleet-alert-report-at'),
          events: chosen
        };
        const discord = this.fleetValue('fleet-alert-discord');
        const phone = this.fleetValue('fleet-alert-phone');
        if (discord) payload.discord_webhook_url = discord;
        if (phone) payload.phone_webhook_url = phone;
        data.alerts = unwrap(await this.bridge.call('update_alert_settings', payload)) || {};
        this.toast('success', 'Alerts saved', 'Webhook addresses are stored write-only.');
        this.render();
        return true;
      }
      if (action === 'fleet-alerts-test') {
        const outcome = unwrap(await this.bridge.call('send_alert_test')) || {};
        const failed = asArray(outcome.channels).filter(function (row) { return !row.sent; });
        if (outcome.sent) this.toast('success', 'Test sent', 'At least one channel accepted the alert.');
        else this.toast('warning', 'Nothing was sent', (failed[0] || {}).reason || 'No channel is configured.');
        return true;
      }
      if (action === 'fleet-alerts-report') {
        const outcome = unwrap(await this.bridge.call('get_daily_report', false)) || {};
        data.report = outcome.report || {};
        this.render();
        return true;
      }
      if (action === 'fleet-rules-save') {
        const payload = {
          enabled: this.fleetChecked('fleet-rule-enabled'),
          restart_stuck_macros: this.fleetChecked('fleet-rule-restart'),
          macro_stuck_seconds: this.fleetNumber('fleet-rule-stuck', 60),
          max_runtime_hours: this.fleetNumber('fleet-rule-runtime', 6),
          cpu_pause_percent: this.fleetNumber('fleet-rule-cpu', 90),
          memory_pause_percent: this.fleetNumber('fleet-rule-memory', 90),
          pause_priority_at_or_below: this.fleetNumber('fleet-rule-priority', 3)
        };
        data.rules = unwrap(await this.bridge.call('update_rules', payload)) || {};
        this.toast('success', 'Rules saved', 'The watcher will use them on its next tick.');
        this.render();
        return true;
      }
      if (action === 'fleet-studio-load') {
        studio.macroId = this.fleetValue('fleet-studio-macro');
        studio.accountId = this.fleetValue('fleet-studio-account');
        data.debug = null;
        await this.loadFleet('studio');
        return true;
      }
      if (action === 'fleet-studio-debug') {
        studio.macroId = this.fleetValue('fleet-studio-macro') || studio.macroId;
        studio.accountId = this.fleetValue('fleet-studio-account') || studio.accountId;
        if (!studio.macroId) { this.toast('warning', 'Choose a macro', 'Pick the macro to inspect.'); return true; }
        data.debug = unwrap(await this.bridge.call('debug_macro', studio.macroId, studio.accountId)) || {};
        this.render();
        return true;
      }
      if (action === 'fleet-studio-snapshot') {
        if (!studio.macroId) { this.toast('warning', 'Choose a macro', 'Load a macro first.'); return true; }
        await this.bridge.call('snapshot_macro_version', studio.macroId, this.fleetValue('fleet-studio-label'));
        this.toast('success', 'Snapshot saved', 'You can roll back to this version later.');
        await this.loadFleet('studio');
        return true;
      }
      if (action === 'fleet-studio-rollback') {
        await this.bridge.call('rollback_macro', studio.macroId, Number(button.dataset.version));
        this.state.macros = asArray(await this.bridge.call('list_macros'));
        this.toast('success', 'Macro restored', 'Version ' + button.dataset.version + ' is now the saved macro.');
        await this.loadFleet('studio');
        return true;
      }
      if (action === 'fleet-studio-save-profile') {
        const name = this.fleetValue('fleet-studio-profile-name');
        if (!name) { this.toast('warning', 'Name the profile', 'A key profile needs a name.'); return true; }
        await this.bridge.call('save_key_profile', { name: name, keys: this.fleetPairs('fleet-studio-profile-keys') });
        await this.loadFleet('studio');
        return true;
      }
      if (action === 'fleet-studio-delete-profile') { await this.bridge.call('delete_key_profile', button.dataset.id); await this.loadFleet('studio'); return true; }
      if (action === 'fleet-studio-save-variables') {
        const accountId = this.fleetValue('fleet-studio-account') || studio.accountId;
        if (!accountId) { this.toast('warning', 'Choose an account', 'Variables are stored per account.'); return true; }
        await this.bridge.call('update_macro_variables', accountId, this.fleetPairs('fleet-studio-variables'));
        studio.accountId = accountId;
        this.toast('success', 'Variables saved', 'They are substituted when the macro runs.');
        await this.loadFleet('studio');
        return true;
      }
      if (action === 'fleet-studio-group-run') {
        const groupId = this.fleetValue('fleet-studio-group');
        const macroId = this.fleetValue('fleet-studio-macro') || studio.macroId;
        if (!groupId || !macroId) { this.toast('warning', 'Choose both', 'Pick a group and a macro.'); return true; }
        const outcome = unwrap(await this.bridge.call('start_group_macro', groupId, macroId)) || {};
        this.state.macroRuns = asArray(await this.bridge.call('list_macro_runs'));
        const queued = asArray(outcome.queued).length;
        this.toast('success', 'Group macro started', asArray(outcome.started).length + ' started' + (queued ? ', ' + queued + ' queued (one macro window at a time)' : '') + '.');
        this.render();
        return true;
      }
    } catch (error) {
      this.toast('error', 'Fleet', error.message);
      return true;
    }
    return false;
  }

  renderFleetProfiles() {
    const data = this.state.fleetData.profiles || {};
    const profiles = Array.isArray(data.profiles) ? data.profiles : [];
    const groups = Array.isArray(data.groups) ? data.groups : [];
    const groupOptions = ['<option value="">No group</option>'].concat(groups.map(function (group) {
      return '<option value="' + escapeHtml(group.id) + '">' + escapeHtml(group.name) + '</option>';
    })).join('');
    const rows = profiles.length ? profiles.map(function (profile) {
      return '<tr><td><strong>' + escapeHtml(profile.name) + '</strong><br /><small class="mono">' + escapeHtml(profile.summary || '') + '</small></td>'
        + '<td class="mono">' + escapeHtml(profile.place_id) + '</td>'
        + '<td class="mono">' + escapeHtml(profile.job_id || profile.link_code || 'any server') + '</td>'
        + '<td class="mono">' + escapeHtml(profile.fps ? profile.fps + ' FPS' : 'unchanged') + '</td>'
        + '<td><div class="table-actions"><button class="button button-sm button-primary" type="button" data-action="fleet-profile-launch" data-id="' + escapeHtml(profile.id) + '">Launch</button>'
        + '<button class="button button-sm" type="button" data-action="fleet-profile-delete" data-id="' + escapeHtml(profile.id) + '">Delete</button></div></td></tr>';
    }).join('') : '<tr><td colspan="5" class="mono">No launch profile yet. Save one below and it becomes a one-click destination.</td></tr>';
    return '<section class="macro-layout"><section class="panel"><div class="panel-head"><h3>' + icon('play') + ' Saved profiles (' + profiles.length + '/' + escapeHtml(data.limit || 40) + ')</h3><button class="button button-sm" type="button" data-action="fleet-refresh">' + icon('refresh') + ' Refresh</button></div>'
      + '<table class="data-table"><thead><tr><th>Profile</th><th>Place</th><th>Server</th><th>FPS</th><th></th></tr></thead><tbody>' + rows + '</tbody></table>'
      + '<p class="mono">A profile launch goes through the wave launcher, so the concurrency limit, the delay between launches and the pause between waves all still apply. An FPS target is a global Roblox setting: it applies to every client, not only this profile.</p></section>'
      + '<section class="panel"><div class="panel-head"><h3>' + icon('plus') + ' New profile</h3></div><div class="form-grid">'
      + '<div class="field"><label for="fleet-profile-name">Name</label><input id="fleet-profile-name" maxlength="60" placeholder="Evening farm" /></div>'
      + '<div class="field"><label for="fleet-profile-place">Place ID</label><input id="fleet-profile-place" inputmode="numeric" placeholder="920587237" /></div>'
      + '<div class="field"><label for="fleet-profile-job">JobId (optional)</label><input id="fleet-profile-job" placeholder="Send everyone to one server" /></div>'
      + '<div class="field"><label for="fleet-profile-link">Private server code (optional)</label><input id="fleet-profile-link" placeholder="Used instead of a JobId" /></div>'
      + '<div class="field"><label for="fleet-profile-fps">FPS target (optional)</label><input id="fleet-profile-fps" inputmode="numeric" placeholder="0 keeps the current cap" /></div>'
      + '<div class="field"><label for="fleet-profile-group">Group to launch</label><select id="fleet-profile-group">' + groupOptions + '</select></div>'
      + '<div class="field full"><label for="fleet-profile-note">Note</label><input id="fleet-profile-note" maxlength="200" placeholder="What this destination is for" /></div>'
      + '<div class="field full"><label for="fleet-profile-accounts">Accounts to launch (optional, overrides the group)</label><select id="fleet-profile-accounts" multiple size="6">' + this.fleetAccountOptions('') + '</select></div>'
      + '</div><footer class="modal-foot"><button class="button button-sm button-primary" type="button" data-action="fleet-profile-save">Save profile</button></footer></section></section>';
  }

  renderDiagnostics() {
    const diagnostics = this.state.diagnostics || { services: [], logs: [] };
    return '<section class="page-heading"><div class="page-heading-copy"><h2>Quietly verify the machinery.</h2><p>Health signals are written for people first, with recent technical context available when you need to investigate an issue.</p></div><div class="page-heading-actions"><button class="button" type="button" data-action="open-compatibility-check">System check</button><button class="button" type="button" data-action="refresh-diagnostics">' + icon('refresh') + ' Refresh status</button><button class="button" type="button" data-action="export-metadata">' + icon('upload') + ' Export metadata</button><button class="button" type="button" data-action="open-import-metadata">' + icon('download') + ' Import metadata</button><button class="button" type="button" data-action="open-restore">' + icon('upload') + ' Restore backup</button><button class="button button-primary" type="button" data-action="backup">' + icon('database') + ' Back up data</button></div></section><section class="stats-grid"><article class="stat-card"><span class="stat-card-label">' + icon('shield') + ' Overall health</span><strong>' + escapeHtml(diagnostics.status === 'healthy' ? 'Good' : diagnostics.status || 'Check') + '</strong><small><em>Checked ' + relativeTime(diagnostics.checked_at) + '</em></small></article><article class="stat-card"><span class="stat-card-label">' + icon('monitor') + ' Active instances</span><strong>' + this.state.instances.length + '</strong><small>Processes matched to accounts</small></article><article class="stat-card"><span class="stat-card-label">' + icon('database') + ' Account vault</span><strong>Ready</strong><small>Secure data service available</small></article><article class="stat-card"><span class="stat-card-label">' + icon('activity') + ' Event history</span><strong>' + this.state.activity.length + '</strong><small>Recent workspace events</small></article></section><section class="section-header"><h3>Service checks</h3><span class="section-line"></span></section><section class="data-table-wrap"><table class="data-table"><thead><tr><th>Service</th><th>Status</th><th>Detail</th></tr></thead><tbody>' + (diagnostics.services || []).map(function (service) { return '<tr><td><strong>' + escapeHtml(service.name) + '</strong></td><td><span class="status ' + escapeHtml(service.status || 'healthy') + '">' + statusText(service.status || 'healthy') + '</span></td><td><span class="mono">' + escapeHtml(service.detail || '') + '</span></td></tr>'; }).join('') + '</tbody></table></section><section class="section-header"><h3>Recent diagnostics</h3><p>Technical entries are local to this device.</p><span class="section-line"></span></section><section class="panel"><div class="diagnostic-box"><pre>' + escapeHtml((diagnostics.logs || []).map(function (row) { return '[' + new Date(row.at || Date.now()).toLocaleTimeString() + '] ' + (row.level || 'INFO') + '  ' + (row.message || ''); }).join('\n') || 'No diagnostic entries available.') + '</pre></div></section>';
  }

  renderSettings() {
    const tabs = [['general', 'General'], ['performance', 'Performance & FPS'], ['roblox', 'Roblox settings'], ['appearance', 'Appearance'], ['accounts', 'Accounts'], ['oauth', 'Roblox sign-in'], ['instances', 'Instances'], ['network', 'Network'], ['integrations', 'Discord & updates'], ['notifications', 'Notifications'], ['advanced', 'Advanced']];
    return '<section class="page-heading"><div class="page-heading-copy"><h2>Make the workspace yours.</h2><p>Settings are applied immediately and stay deliberately compact. The desktop bridge persists them securely when it is available.</p></div><div class="page-heading-actions"><button class="button" type="button" data-action="open-settings-reset">' + icon('refresh') + ' Reset settings</button><button class="button" type="button" data-action="backup">' + icon('database') + ' Create backup</button></div></section><section class="settings-layout"><nav class="panel settings-nav" aria-label="Settings categories">' + tabs.map(function (tab) { return '<button type="button" data-action="settings-tab" data-tab="' + tab[0] + '" class="' + (this.state.settingsTab === tab[0] ? 'is-active' : '') + '">' + tab[1] + '</button>'; }.bind(this)).join('') + '</nav><div class="settings-content">' + this.renderSettingsPanel() + '</div></section>';
  }

  settingRow(title, body, control) {
    return '<div class="setting-row"><div class="setting-copy"><strong>' + title + '</strong><span>' + body + '</span></div><div class="setting-control">' + control + '</div></div>';
  }

  toggleSetting(key, checked) {
    return '<label class="switch"><input type="checkbox" data-setting="' + key + '"' + (checked ? ' checked' : '') + ' /><span></span></label>';
  }

  renderRobloxSettingsPanel() {
    const manager = this.state.robloxSettings || {};
    if (!manager.loaded) return '<section class="panel settings-section"><header class="settings-section-head"><div><h3>Roblox settings manager</h3><p>Reading GlobalBasicSettings_13.xml…</p></div></header></section>';
    if (!manager.available) return '<section class="panel settings-section"><header class="settings-section-head"><div><h3>Roblox settings manager</h3><p>' + escapeHtml(manager.reason || 'The Roblox settings file is unavailable.') + '</p></div><button class="button button-sm" type="button" data-action="refresh-roblox-settings">' + icon('refresh') + ' Retry</button></header></section>';
    const basic = manager.basic || {};
    const camera = Number.isFinite(Number(basic.camera_mode)) ? Number(basic.camera_mode) : 0;
    const profiles = asArray(manager.profiles);
    const groups = asArray(manager.groups);
    const groupOptions = '<option value="">No group</option>' + groups.map(function (group) { return '<option value="' + escapeHtml(group.id) + '">' + escapeHtml(group.name) + '</option>'; }).join('');
    const fields = '<div class="form-grid"><div class="field"><label>FPS cap</label><input name="fps" type="number" min="-1" max="1000" required value="' + escapeHtml(basic.fps === null || basic.fps === undefined ? -1 : basic.fps) + '" /><span class="mono">-1 restores Roblox default.</span></div><div class="field"><label>Master volume (%)</label><input name="volume_percent" type="number" min="0" max="100" required value="' + escapeHtml(basic.volume_percent === null || basic.volume_percent === undefined ? 100 : basic.volume_percent) + '" /></div><div class="field"><label>Graphics quality</label><input name="graphics_quality" type="number" min="0" max="10" required value="' + escapeHtml(basic.graphics_quality === null || basic.graphics_quality === undefined ? 0 : basic.graphics_quality) + '" /></div><div class="field"><label>Camera mode token</label><input name="camera_mode" type="number" min="0" max="10" required value="' + escapeHtml(camera) + '" /></div><label class="form-check field full"><input type="checkbox" name="fullscreen"' + (basic.fullscreen ? ' checked' : '') + ' /> Fullscreen</label><div class="field full"><label>Advanced overrides (JSON object, optional)</label><textarea name="advanced_json" rows="4" placeholder="{&quot;SomeExistingScalarSetting&quot;: 1}"></textarea><span class="mono">Only existing scalar XML fields are accepted; unknown names and invalid types are rejected.</span></div></div>';
    const cards = profiles.length ? profiles.map(function (profile) { const group = groups.find(function (item) { return String(item.id) === String(profile.group_id); }); return '<div class="activity-row"><div class="activity-copy"><strong>' + escapeHtml(profile.name) + '</strong><small>' + escapeHtml(group ? group.name : 'Global') + ' · ' + escapeHtml(JSON.stringify(profile.values || {})) + '</small></div><div class="setting-buttons"><button class="button button-sm button-primary" type="button" data-action="apply-roblox-profile" data-id="' + escapeHtml(profile.id) + '">Apply</button><button class="button button-sm button-danger" type="button" data-action="delete-roblox-profile" data-id="' + escapeHtml(profile.id) + '">Delete</button></div></div>'; }).join('') : '<p class="empty-copy">No saved Roblox settings profile yet.</p>';
    return '<section class="panel settings-section"><header class="settings-section-head"><div><h3>Global Roblox settings</h3><p>Typed, atomic edits with read-back verification. These values are global to Roblox, not per running process.</p></div><button class="button button-sm" type="button" data-action="refresh-roblox-settings">' + icon('refresh') + ' Refresh</button></header><form data-form="roblox-global-settings"><div class="modal-body"><p class="form-error" hidden></p>' + fields + '<label class="form-check restore-confirm-check"><input type="checkbox" name="confirm" required /> I confirm Roblox global settings may be changed.</label></div><footer class="modal-foot"><button class="button button-primary" type="submit">' + icon('check') + ' Apply & verify</button></footer></form></section><section class="panel settings-section"><header class="settings-section-head"><div><h3>Profiles by group</h3><p>A group association organises the preset. Astro applies global settings; Roblox does not expose independent XML settings per running process.</p></div></header><div class="activity-list">' + cards + '</div><form data-form="roblox-settings-profile"><div class="modal-body"><p class="form-error" hidden></p><div class="form-grid"><div class="field"><label>Profile name</label><input name="name" maxlength="60" required placeholder="LOW RESOURCE FARM" /></div><div class="field"><label>Group</label><select name="group_id">' + groupOptions + '</select></div></div>' + fields + '</div><footer class="modal-foot"><button class="button button-primary" type="submit">Save profile</button></footer></form></section>';
  }

  renderSettingsPanel() {
    const s = this.state.settings;
    const categories = s.categories || {};
    const watcher = categories.watcher || {};
    const network = categories.network || { region_lookup_enabled: false, region_lookup_provider: '', region_lookup_format: '{city}, {country}', region_lookup_timeout_seconds: 4, region_cache_ttl_seconds: 900 };
    if (this.state.settingsTab === 'performance') return '<section class="panel settings-section"><header class="settings-section-head"><div><h3>Performance & FPS</h3><p>FPS Frame Unlocker cap and Potato Graphics mode for low-end hardware.</p></div></header>' +
      this.settingRow('Frame Unlocker (FPS Target)', 'Frame rate cap target for Roblox clients (DFIntTaskSchedulerTargetFps).', '<select class="setting-select" data-setting="global_max_fps"><option value="0"' + (s.global_max_fps == 0 ? ' selected' : '') + '>Roblox Default</option><option value="60"' + (s.global_max_fps == 60 ? ' selected' : '') + '>60 FPS</option><option value="120"' + (s.global_max_fps == 120 ? ' selected' : '') + '>120 FPS</option><option value="144"' + (s.global_max_fps == 144 ? ' selected' : '') + '>144 FPS</option><option value="240"' + (s.global_max_fps == 240 ? ' selected' : '') + '>240 FPS (Recommended)</option><option value="360"' + (s.global_max_fps == 360 ? ' selected' : '') + '>360 FPS</option></select>') +
      this.settingRow('Potato Graphics Mode 🥔', 'Extreme graphics reduction (textures, shadows, post-fx, materials) via FastFlags for maximum accounts on low-end hardware.', this.toggleSetting('potato_graphics', s.potato_graphics)) + '</section>';
    if (this.state.settingsTab === 'roblox') return this.renderRobloxSettingsPanel();
    if (this.state.settingsTab === 'appearance') return '<section class="panel settings-section"><header class="settings-section-head"><div><h3>Appearance</h3><p>Theme, color and comfortable visual density.</p></div></header>' +
      this.settingRow('Color theme', 'Switch between the premium dark and bright light canvas.', '<select class="setting-select" data-setting="theme"><option value="dark"' + (s.theme !== 'light' ? ' selected' : '') + '>Dark</option><option value="light"' + (s.theme === 'light' ? ' selected' : '') + '>Light</option></select>') +
      this.settingRow('Accent color', 'A focused color used for selection, status, and primary actions.', '<div class="color-options"><button class="color-option ' + (s.accent === 'violet' ? 'is-active' : '') + '" type="button" data-action="set-accent" data-accent="violet" aria-label="Violet accent"><i></i></button><button class="color-option mint ' + (s.accent === 'mint' ? 'is-active' : '') + '" type="button" data-action="set-accent" data-accent="mint" aria-label="Mint accent"><i></i></button><button class="color-option coral ' + (s.accent === 'coral' ? 'is-active' : '') + '" type="button" data-action="set-accent" data-accent="coral" aria-label="Coral accent"><i></i></button><button class="color-option blue ' + (s.accent === 'blue' ? 'is-active' : '') + '" type="button" data-action="set-accent" data-accent="blue" aria-label="Blue accent"><i></i></button><button class="color-option amber ' + (s.accent === 'amber' ? 'is-active' : '') + '" type="button" data-action="set-accent" data-accent="amber" aria-label="Amber accent"><i></i></button></div>') +
      this.settingRow('Interface density', 'Use compact spacing when you manage a larger collection.', '<select class="setting-select" data-setting="density"><option value="comfortable"' + (s.density !== 'compact' ? ' selected' : '') + '>Comfortable</option><option value="compact"' + (s.density === 'compact' ? ' selected' : '') + '>Compact</option></select>') +
      this.settingRow('Reduced motion', 'Disable non-essential transitions and animated status details.', this.toggleSetting('reduce_motion', s.reduce_motion)) +
      this.settingRow('Streamer privacy mode', 'Persistently replace usernames and Roblox User IDs, and blur avatars while streaming.', this.toggleSetting('privacy_mode', Boolean(s.privacy_mode))) + '</section>';
    if (this.state.settingsTab === 'accounts') return '<section class="panel settings-section"><header class="settings-section-head"><div><h3>Accounts</h3><p>Set defaults for adding and launching accounts.</p></div></header>' +
      this.settingRow('Launch confirmation', 'Choose whether a launch is verified before Roblox opens.', '<select class="setting-select" data-setting="launch_behavior"><option value="confirm"' + (s.launch_behavior === 'confirm' ? ' selected' : '') + '>Ask each time</option><option value="direct"' + (s.launch_behavior === 'direct' ? ' selected' : '') + '>Launch directly</option></select>') +
      this.settingRow('Close unused sessions', 'Offer cleanup when no managed account is using an instance.', this.toggleSetting('close_when_empty', s.close_when_empty)) +
      this.settingRow('Automatic backups', 'Create a background data snapshot before sensitive changes.', this.toggleSetting('auto_backup', s.auto_backup)) + '</section>';
    if (this.state.settingsTab === 'oauth') {
      const oauth = this.oauthSettings();
      const desktop = this.state.mode === 'desktop';
      const ready = this.isOAuthConfigured();
      const unavailable = !desktop;
      const disabled = unavailable ? ' disabled' : '';
      const status = ready ? '<span class="badge success">Configured</span>' : '<span class="badge warning">Configuration required</span>';
      const action = ready ? '<button class="button button-sm button-primary" type="button" data-action="start-oauth-login">' + icon('shield') + ' Connect Roblox account</button>' : '';
      const modeNote = unavailable
        ? '<p class="oauth-help oauth-help-warning">Preview mode has no desktop OAuth bridge. It never simulates a Roblox sign-in; open the desktop application to configure and connect an account.</p>'
        : '<p class="oauth-help">Use the client ID and loopback callback registered for this desktop application. A client secret, cookies, and tokens are never entered or displayed here.</p>';
      return '<section class="panel settings-section oauth-settings-section"><header class="settings-section-head"><div><h3>Roblox sign-in</h3><p>Official Open Cloud OAuth linking through the system browser.</p></div>' + status + action + '</header><form data-form="oauth-settings"><div class="modal-body"><p class="form-error" hidden></p>' + modeNote + '<div class="form-grid"><label class="form-check field full"><input type="checkbox" name="enabled"' + (oauth.enabled ? ' checked' : '') + disabled + ' /> Enable official Roblox OAuth for this desktop workspace</label><div class="field"><label for="oauth-client-id">Roblox OAuth client ID</label><input id="oauth-client-id" name="client_id" inputmode="numeric" pattern="[0-9]+" autocomplete="off"' + disabled + ' value="' + escapeHtml(oauth.client_id || '') + '" placeholder="Numeric client ID" /></div><div class="field"><label for="oauth-timeout">Browser callback timeout</label><input id="oauth-timeout" name="callback_timeout_seconds" type="number" min="60" max="900" step="1" required' + disabled + ' value="' + escapeHtml(oauth.callback_timeout_seconds || 300) + '" /></div><div class="field full"><label for="oauth-redirect-uri">Registered loopback redirect URI</label><input id="oauth-redirect-uri" name="redirect_uri" type="url" autocomplete="off" required' + disabled + ' value="' + escapeHtml(oauth.redirect_uri || '') + '" placeholder="http://127.0.0.1:8989/oauth/callback" /><span class="mono">This exact URI must be registered with Roblox before OAuth is enabled.</span></div></div></div><footer class="modal-foot"><button class="button button-primary" type="submit"' + disabled + '>' + icon('check') + ' Save Roblox sign-in settings</button></footer></form></section>';
    }
    if (this.state.settingsTab === 'instances') return '<section class="panel settings-section"><header class="settings-section-head"><div><h3>Instances & watcher</h3><p>Control local process monitoring.</p></div></header>' +
      this.settingRow('Multi Roblox', 'One-click multi-instance mode. Use a different stored account for each client; launching the same Roblox identity twice can trigger Error 267. Enable it before opening Roblox; if Roblox is already running, Astro saves the choice for the next restart.', this.toggleSetting('allow_multiple_launches', Boolean((this.state.multiInstance || {}).configured))) +
      this.settingRow('Instance watcher', 'Detect supported Roblox processes and keep their state current.', this.toggleSetting('watcher_enabled', s.watcher_enabled)) +
      this.settingRow('Allow instance closing', 'Enable confirmed closes and the opt-in automatic health rules below.', this.toggleSetting('watcher_termination_enabled', s.watcher_termination_enabled)) +
      this.settingRow('Allow account relaunch rules', 'Enable the opt-in per-account watcher rules that can request a bounded relaunch after an exit or crash.', this.toggleSetting('watcher_auto_relaunch_enabled', s.watcher_auto_relaunch_enabled)) +
      this.settingRow('Remember window positions', 'Capture bound Roblox window geometry after startup and restore it on the next matched launch.', this.toggleSetting('remember_window_positions', s.remember_window_positions)) +
      this.settingRow('Close low-memory startup', 'After the grace period, close a verified unfocused Roblox window below the configured memory threshold.', this.toggleSetting('watcher_close_if_memory_low', s.watcher_close_if_memory_low)) +
      this.settingRow('Close unexpected window title', 'After the grace period, close a verified unfocused window whose title is not the expected Roblox title.', this.toggleSetting('watcher_close_if_title_mismatch', s.watcher_close_if_title_mismatch)) +
      this.settingRow('Close unconnected instances', 'Close an unfocused orphaned Roblox window after the configured timeout.', this.toggleSetting('watcher_close_unconnected', s.watcher_close_unconnected)) +
      this.settingRow('Refresh now', 'Run an immediate process scan through the desktop bridge.', '<button class="button button-sm" type="button" data-action="refresh-instances">' + icon('refresh') + ' Refresh instances</button>') +
      '<form data-form="watcher-health"><div class="modal-body"><p class="form-error" hidden></p><div class="form-grid"><div class="field"><label for="watcher-memory-low">Low-memory threshold (MB)</label><input id="watcher-memory-low" name="memory_low_mb" type="number" min="50" max="4096" step="1" required value="' + escapeHtml(watcher.memory_low_mb || 200) + '" /></div><div class="field"><label for="watcher-health-grace">Health grace (seconds)</label><input id="watcher-health-grace" name="health_grace_seconds" type="number" min="5" max="600" step="1" required value="' + escapeHtml(watcher.health_grace_seconds || 30) + '" /></div><div class="field"><label for="watcher-expected-title">Expected window title</label><input id="watcher-expected-title" name="expected_window_title" maxlength="128" required value="' + escapeHtml(watcher.expected_window_title || 'Roblox') + '" /></div><div class="field"><label for="watcher-unconnected-timeout">Unconnected timeout (seconds)</label><input id="watcher-unconnected-timeout" name="unconnected_timeout_seconds" type="number" min="5" max="3600" step="1" required value="' + escapeHtml(watcher.unconnected_timeout_seconds || 60) + '" /></div></div></div><footer class="modal-foot"><button class="button button-primary" type="submit">' + icon('check') + ' Save watcher thresholds</button></footer></form></section>';
    if (this.state.settingsTab === 'network') return '<section class="panel settings-section"><header class="settings-section-head"><div><h3>Server regions</h3><p>Optional IP geolocation for server addresses exposed by Roblox.</p></div><span class="badge warning">Opt-in network lookup</span></header><form data-form="region-settings"><div class="modal-body"><p class="form-error" hidden></p><p class="oauth-help">When enabled, public server IP addresses may be sent to the configured provider. Internal addresses are always rejected, failures stay silent, and results are cached.</p><div class="form-grid"><label class="form-check field full"><input type="checkbox" name="region_lookup_enabled"' + (network.region_lookup_enabled ? ' checked' : '') + ' /> Enable server region lookup</label><div class="field full"><label for="region-provider">Provider URL</label><input id="region-provider" name="region_lookup_provider" maxlength="300" value="' + escapeHtml(network.region_lookup_provider || '') + '" placeholder="http://ip-api.com/json/{ip}" /><span class="mono">The URL must contain {ip}. Leave empty for the historical default.</span></div><div class="field"><label for="region-format">Display format</label><input id="region-format" name="region_lookup_format" maxlength="120" required value="' + escapeHtml(network.region_lookup_format || '{city}, {country}') + '" /></div><div class="field"><label for="region-timeout">Timeout (seconds)</label><input id="region-timeout" name="region_lookup_timeout_seconds" type="number" min="0.5" max="30" step="0.5" required value="' + escapeHtml(network.region_lookup_timeout_seconds || 4) + '" /></div><div class="field"><label for="region-cache-ttl">Cache lifetime (seconds)</label><input id="region-cache-ttl" name="region_cache_ttl_seconds" type="number" min="30" max="86400" step="1" required value="' + escapeHtml(network.region_cache_ttl_seconds || 900) + '" /></div></div></div><footer class="modal-foot"><button class="button button-primary" type="submit">' + icon('check') + ' Save region settings</button></footer></form></section>';
    if (this.state.settingsTab === 'notifications') return '<section class="panel settings-section"><header class="settings-section-head"><div><h3>Notifications</h3><p>Control in-app status messages.</p></div></header>' +
      this.settingRow('In-app notifications', 'Surface launch results, backup outcomes, and watcher events.', this.toggleSetting('notifications', s.notifications)) +
      this.settingRow('Notification center', 'Review and dismiss messages from the top bar.', '<button class="button button-sm" type="button" data-action="toggle-notifications">' + icon('bell') + ' Open notifications</button>') + '</section>';
    if (this.state.settingsTab === 'integrations') {
      const discord = categories.discord || { enabled: false, client_id: '', strategy: 'latest', show_account: false, details_template: '{game}', state_template: '{instances} active · {account}', large_image: '', large_text: 'Astro Account Manager', game_overrides: [] };
      const updates = categories.updates || { auto_check: true, auto_download: false, install_on_exit: false };
      const updateStatus = this.state.updater || {};
      return '<section class="panel settings-section"><header class="settings-section-head"><div><h3>Discord Rich Presence</h3><p>Publish one redacted activity with stable elapsed time, correct Discord assets, and optional per-game text.</p></div><span class="badge ' + (this.state.discordPresence.connected ? 'success' : 'warning') + '">' + (this.state.discordPresence.connected ? 'Connected' : 'Idle') + '</span></header><form data-form="discord-settings"><div class="modal-body"><p class="form-error" hidden></p><div class="form-grid"><label class="form-check field full"><input type="checkbox" name="enabled"' + (discord.enabled ? ' checked' : '') + ' /> Enable Discord Rich Presence</label><div class="field"><label>Discord Application ID</label><input name="client_id" inputmode="numeric" maxlength="32" value="' + escapeHtml(discord.client_id || '') + '" placeholder="Numeric application ID" /></div><div class="field"><label>Multiple instances</label><select name="strategy"><option value="latest"' + (discord.strategy !== 'aggregate' ? ' selected' : '') + '>Latest active game</option><option value="aggregate"' + (discord.strategy === 'aggregate' ? ' selected' : '') + '>Aggregate count</option></select></div><label class="form-check field full"><input type="checkbox" name="show_account"' + (discord.show_account ? ' checked' : '') + ' /> Show the local account alias (automatically suppressed in privacy mode)</label><div class="field"><label>Details template</label><input name="details_template" maxlength="256" value="' + escapeHtml(discord.details_template || '{game}') + '" /></div><div class="field"><label>State template</label><input name="state_template" maxlength="256" value="' + escapeHtml(discord.state_template || '{instances} active · {account}') + '" /></div><div class="field"><label>Large image asset key</label><input name="large_image" maxlength="128" value="' + escapeHtml(discord.large_image || '') + '" placeholder="Configured Discord asset key" /></div><div class="field"><label>Large image text</label><input name="large_text" maxlength="256" value="' + escapeHtml(discord.large_text || 'Astro Account Manager') + '" /></div><div class="field full"><label>Per-game overrides (JSON array)</label><textarea name="game_overrides" rows="5" placeholder="[{&quot;place_id&quot;:&quot;123&quot;,&quot;details&quot;:&quot;Farming {game}&quot;}]">' + escapeHtml(JSON.stringify(discord.game_overrides || [], null, 2)) + '</textarea><span class="mono">Available placeholders: {game}, {place_id}, {account}, {instances}.</span></div></div></div><footer class="modal-foot"><button class="button button-primary" type="submit">' + icon('check') + ' Save & refresh presence</button></footer></form></section><section class="panel settings-section"><header class="settings-section-head"><div><h3>Application updates</h3><p>Only the fixed GitHub release asset is downloaded, size-checked, PE-validated and hashed before staging.</p></div><span class="badge">' + escapeHtml(updateStatus.pending_install ? (updateStatus.ready_to_install === false ? 'Update needs re-download' : 'Install pending') : updateStatus.staged ? (updateStatus.staged_valid === false ? 'Invalid download' : 'Downloaded') : 'Current') + '</span></header>' + this.settingRow('Check automatically', 'Check the official releases endpoint in the background at startup.', this.toggleSetting('updates_auto_check', updates.auto_check !== false)) + this.settingRow('Download automatically', 'Stage a newer verified release asset when one exists.', this.toggleSetting('updates_auto_download', Boolean(updates.auto_download))) + this.settingRow('Install on exit', 'Replace only the packaged EXE after Astro has closed; the previous EXE is kept beside it.', this.toggleSetting('updates_install_on_exit', Boolean(updates.install_on_exit))) + this.settingRow('Updater actions', 'Check, download, schedule, or remove the staged update.', '<div class="setting-buttons"><button class="button button-sm" type="button" data-action="check-updates">Check</button><button class="button button-sm" type="button" data-action="download-update">Download</button><button class="button button-sm button-primary" type="button" data-action="install-update">Install on exit</button><button class="button button-sm button-danger" type="button" data-action="cancel-update">Cancel staged</button></div>') + this.settingRow('Support report', 'Create a redacted ZIP with logs, diagnostics and public settings. Vault sessions, database and macro contents are excluded.', '<button class="button button-sm" type="button" data-action="export-support-bundle">' + icon('download') + ' Create support ZIP</button>') + '</section>';
    }
    if (this.state.settingsTab === 'advanced') {
      const api = (s.categories && s.categories.api) || { enabled: false, port: 7963, allow_external: false, allow_get_cookie: false, allow_launch_account: false, allow_account_editing: false, allow_import_cookie: false, allow_get_accounts: false, legacy_password_auth_enabled: false };
      return '<section class="panel settings-section"><header class="settings-section-head"><div><h3>Data tools</h3><p>Use portable backups before importing data from legacy versions.</p></div></header>' +
      this.settingRow('Create backup', 'Request a verified backup from the local data service.', '<button class="button button-sm" type="button" data-action="backup">' + icon('database') + ' Back up now</button>') +
      this.settingRow('Migrate legacy data', 'Inspect an existing Roblox Account Manager data location.', '<button class="button button-sm" type="button" data-action="migrate">' + icon('upload') + ' Start migration</button>') +
      this.settingRow('Developer diagnostics', 'Show extra technical state inside Diagnostics.', this.toggleSetting('diagnostics', s.diagnostics)) + '</section>' +
      '<section class="panel settings-section"><header class="settings-section-head"><div><h3>Authenticated local API</h3><p>RAM-compatible routes plus REST v1 with independent permissions. Changes apply after restarting Astro.</p></div><span class="badge warning">Token required</span></header><form data-form="api-settings"><div class="modal-body"><p class="form-error" hidden></p><p class="oauth-help">Every request requires ASTRO_LOCAL_API_TOKEN (32+ characters). Root routes return RAM 3.7.2 text, /v2 wraps historical responses, and /api/v1 remains structured JSON. The listener stays local unless LAN access is explicitly enabled.</p><div class="form-grid"><label class="form-check field full"><input type="checkbox" name="enabled"' + (api.enabled ? ' checked' : '') + ' /> Enable the API after restart</label><div class="field"><label for="api-port">API port</label><input id="api-port" name="port" type="number" min="1" max="65535" required value="' + escapeHtml(api.port || 7963) + '" /></div><label class="form-check field full"><input type="checkbox" name="allow_external"' + (api.allow_external ? ' checked' : '') + ' /> Allow authenticated LAN connections (bind 0.0.0.0 after restart)</label><label class="form-check field full"><input type="checkbox" name="allow_launch_account"' + (api.allow_launch_account ? ' checked' : '') + ' /> Allow LaunchAccount and FollowUser</label><label class="form-check field full"><input type="checkbox" name="allow_account_editing"' + (api.allow_account_editing ? ' checked' : '') + ' /> Allow account editing routes</label><label class="form-check field full"><input type="checkbox" name="allow_get_cookie"' + (api.allow_get_cookie ? ' checked' : '') + ' /> Allow raw cookie and CSRF retrieval</label><label class="form-check field full"><input type="checkbox" name="allow_import_cookie"' + (api.allow_import_cookie ? ' checked' : '') + ' /> Allow cookie import</label><label class="form-check field full"><input type="checkbox" name="allow_get_accounts"' + (api.allow_get_accounts ? ' checked' : '') + ' /> Allow GetAccounts and GetAccountsJson</label><label class="form-check field full"><input type="checkbox" name="legacy_password_auth_enabled"' + (api.legacy_password_auth_enabled ? ' checked' : '') + ' /> Accept the historical RAM password scheme after restart</label></div></div><footer class="modal-foot"><button class="button button-primary" type="submit">' + icon('check') + ' Save API settings</button></footer></form></section>';
    }
    return '<section class="panel settings-section"><header class="settings-section-head"><div><h3>General</h3><p>Small choices that make daily use feel smoother.</p></div></header>' +
      this.settingRow('Workspace mode', this.state.mode === 'desktop' ? 'Connected to the local pywebview desktop bridge.' : 'Preview mode runs entirely in your browser with sample data.', '<span class="badge ' + (this.state.mode === 'desktop' ? 'success' : 'warning') + '">' + (this.state.mode === 'desktop' ? 'Connected' : 'Preview') + '</span>') +
      this.settingRow('Warn when Roblox is already running', 'Before enabling Multi Roblox, show detected background clients and offer an explicit close.', this.toggleSetting('warn_if_roblox_running', (((s.categories || {}).general || {}).warn_if_roblox_running !== false))) +
      this.renderWindowsStartupSetting() +
      this.settingRow('Command palette', 'Use Ctrl + K to search accounts, games, settings and quick actions.', '<button class="button button-sm" type="button" data-action="open-palette">' + icon('command') + ' Open palette</button>') +
      this.settingRow('Refresh services', 'Update process state and service health now.', '<button class="button button-sm" type="button" data-action="refresh-diagnostics">' + icon('refresh') + ' Refresh</button>') + '</section>';
  }

  emptyInline(symbol, title, body) { return '<div class="empty-card"><div>' + icon(symbol) + '<strong>' + title + '</strong><p>' + body + '</p></div></div>'; }
  emptyState(symbol, title, body, actionText, action) { return '<section class="empty-card"><div>' + icon(symbol) + '<strong>' + escapeHtml(title) + '</strong><p>' + escapeHtml(body) + '</p><button class="button button-sm" type="button" data-action="' + escapeHtml(action) + '">' + escapeHtml(actionText) + '</button></div></section>'; }

  renderOverlays() {
    let output = '';
    if (this.state.notificationsOpen) output += this.renderNotifications();
    if (this.state.modal) output += this.renderModal();
    if (this.state.paletteOpen) output += this.renderPalette();
    if (output === this.state.lastOverlayHtml) return;
    this.state.lastOverlayHtml = output;
    this.swapHtml(this.overlayRoot, output);
  }

  renderNotifications() {
    const notices = this.state.notifications;
    return '<aside class="notification-drawer" aria-label="Notifications"><header class="drawer-head"><h2>Notifications</h2><span class="badge">' + notices.length + '</span><button class="icon-button" type="button" data-action="toggle-notifications" aria-label="Close notifications">' + icon('x') + '</button></header><div class="drawer-list">' + (notices.length ? notices.map(function (notice) { const style = ['success', 'warning', 'error'].includes(notice.kind) ? notice.kind : ''; const symbol = notice.kind === 'success' ? 'check' : notice.kind === 'warning' ? 'alert' : notice.kind === 'error' ? 'alert' : 'info'; return '<article class="notice"><span class="notice-kind ' + style + '">' + icon(symbol) + '</span><strong>' + escapeHtml(notice.title) + '</strong><p>' + escapeHtml(notice.body) + '</p><time>' + relativeTime(notice.at) + '</time><button class="icon-button" type="button" data-action="dismiss-notification" data-id="' + escapeHtml(notice.id) + '" aria-label="Dismiss notification">' + icon('x') + '</button></article>'; }).join('') : '<div class="empty-notices">' + icon('bell') + '<p>You are all caught up.</p></div>') + '</div></aside>';
  }

  renderModal() {
    const modal = this.state.modal;
    let body = '';
    let title = '';
    let sub = '';
    if (modal.kind === 'compatibility') {
      const report = modal.report || { checks: [] };
      title = 'Roblox feature compatibility';
      sub = report.roblox_version ? 'Detected ' + report.roblox_version : 'Roblox version was not detected.';
      const rows = asArray(report.checks).map(function (check) { return '<div class="health-row"><span class="health-symbol">' + icon(check.state === 'ready' ? 'check' : check.state === 'unknown' ? 'info' : 'alert') + '</span><span class="health-copy"><strong>' + escapeHtml(check.label) + '</strong><span>' + escapeHtml(check.detail) + '</span></span><span class="badge ' + (check.state === 'ready' ? 'success' : 'warning') + '">' + escapeHtml(check.state) + '</span></div>'; }).join('');
      body = '<div class="modal-body"><p class="restore-warning">Compatibility ' + escapeHtml(report.compatibility_percent === null || report.compatibility_percent === undefined ? 'unknown' : report.compatibility_percent + '%') + '. ' + escapeHtml(report.note || '') + '</p>' + (report.version_changed ? '<p class="form-error">Roblox changed from ' + escapeHtml(report.previous_roblox_version) + ' to ' + escapeHtml(report.roblox_version) + '. Re-test unknown features before acknowledging it.</p>' : '') + '<div class="health-list">' + rows + '</div></div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Close</button><button class="button button-primary" type="button" data-action="acknowledge-roblox-version"' + (report.roblox_version ? '' : ' disabled') + '>Record tested version</button></footer>';
    } else if (modal.kind === 'roblox-background') {
      const status = modal.status || { count: 0, processes: [] };
      title = 'Roblox is already running';
      sub = status.count + ' client' + (status.count === 1 ? ' was' : 's were') + ' detected before Multi Roblox setup.';
      body = '<form data-form="roblox-background"><div class="modal-body"><p class="restore-warning">An already-running Roblox client may own the singleton state before Astro can enable Multi Roblox. You may keep playing and close this notice, or explicitly close the listed Roblox clients first.</p><p class="form-error" hidden></p><div class="activity-list">' + asArray(status.processes).map(function (item) { return '<div class="activity-row"><div class="activity-copy"><strong>Roblox PID ' + escapeHtml(item.pid) + '</strong><small>Detected local client</small></div></div>'; }).join('') + '</div><label class="form-check restore-confirm-check"><input type="checkbox" name="confirm" required /> I confirm Astro may gracefully close these exact Roblox clients.</label></div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Keep Roblox open</button><button class="button button-danger" type="submit">' + icon('x') + ' Close Roblox clients</button></footer></form>';
    } else if (modal.kind === 'private-link') {
      const accountOptions = this.state.accounts.map(function (account) { return '<option value="' + escapeHtml(account.id) + '">' + escapeHtml(account.display_name || account.username) + ' (@' + escapeHtml(account.username) + ')</option>'; }).join('');
      title = 'Join a private server link';
      sub = 'Launch the selected stored account into one Roblox private server.';
      body = '<form data-form="private-link"><div class="modal-body"><p class="form-error" hidden></p><div class="form-grid"><div class="field full"><label>Account</label><select name="account_id" required><option value="">Choose an account…</option>' + accountOptions + '</select></div><div class="field full"><label>Roblox private server link</label><input name="link" type="url" required autocomplete="off" placeholder="https://www.roblox.com/games/…?privateServerLinkCode=…" /></div></div><p class="oauth-help">The link code is used only for this launch. The selected account session remains encrypted in the local vault.</p></div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Cancel</button><button class="button button-primary" type="submit">' + icon('play') + ' Join private server</button></footer></form>';
    } else if (modal.kind === 'settings-reset') {
      title = 'Reset settings?';
      sub = 'Restore one canonical category or the entire workspace configuration.';
      body = '<form data-form="settings-reset"><div class="modal-body"><p class="restore-warning">This changes local preferences only. Accounts, sessions, groups, games and backups are preserved. Resetting General also disables Astro Windows startup if it is enabled.</p><p class="form-error" hidden></p><div class="field full"><label for="settings-reset-scope">Scope</label><select id="settings-reset-scope" name="category"><option value="">All settings</option><option value="general">General</option><option value="appearance">Appearance</option><option value="accounts">Accounts</option><option value="instances">Instances</option><option value="watcher">Watcher</option><option value="performance">Performance & FPS</option><option value="network">Network</option><option value="oauth">OAuth</option><option value="api">Local API</option><option value="nexus">Nexus</option><option value="notifications">Notifications</option><option value="developer">Developer</option></select></div><label class="form-check restore-confirm-check"><input type="checkbox" name="confirm" required /> I confirm these local preferences should return to their defaults.</label></div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Cancel</button><button class="button button-danger" type="submit">' + icon('refresh') + ' Reset selected settings</button></footer></form>';
    } else if (modal.kind === 'windows-startup') {
      const enabled = Boolean(modal.enabled);
      title = enabled ? 'Enable Windows startup?' : 'Disable Windows startup?';
      sub = enabled ? 'Register the packaged Astro Account Manager application for the current Windows user.' : 'Remove only Astro Account Manager\'s current-user Windows startup entry.';
      const detail = enabled
        ? 'This adds only Astro Account Manager to your current-user Windows startup list after Windows confirms the change. It never registers a Python development runtime or changes other applications.'
        : 'This removes only Astro Account Manager\'s current-user Windows startup entry. It does not affect other applications or your Windows account.';
      body = '<form data-form="windows-startup" data-enabled="' + enabled + '"><div class="modal-body"><p class="restore-warning">' + detail + '</p><p class="form-error" hidden></p><label class="form-check restore-confirm-check"><input type="checkbox" name="confirm" required /> I understand this changes Astro Account Manager\'s Windows startup registration.</label></div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Cancel</button><button class="button ' + (enabled ? 'button-primary' : 'button-danger') + '" type="submit">' + icon(enabled ? 'check' : 'x') + ' ' + (enabled ? 'Enable startup' : 'Disable startup') + '</button></footer></form>';
    } else if (modal.kind === 'account') {
      const account = modal.account || {};
      title = account.id ? 'Edit Account' : 'Add Accounts / Sign In';
      sub = account.id ? 'Update profile information, Game ID, and per-instance launch options.' : 'Select your preferred method to add or connect Roblox accounts.';
      const groupOptions = '<option value="">No group (Ungrouped)</option>' + this.state.groups.map(function (group) { return '<option value="' + escapeHtml(group.id) + '"' + (String(account.group_id || '') === String(group.id) ? ' selected' : '') + '>' + escapeHtml(group.name) + '</option>'; }).join('');
      const userId = account.user_id === undefined || account.user_id === null ? '' : String(account.user_id);
      const placeId = account.saved_place_id === undefined || account.saved_place_id === null ? '' : String(account.saved_place_id);
      const launchOpts = (account.metadata && account.metadata.launch_options) || {};
      const maxFps = Number(launchOpts.max_fps || 0);
      const potatoChecked = Boolean(launchOpts.potato_graphics);
      const accountWatcher = Object.assign({ enabled: true, auto_relaunch: false, relaunch_delay_seconds: 15, relaunch_max_attempts: 2, relaunch_on_crash: true, relaunch_on_exit: false }, (account.metadata && account.metadata.watcher) || {}, account.watcher || {});
      const watcherChecked = accountWatcher.enabled === undefined ? true : Boolean(accountWatcher.enabled);
      const relaunchChecked = Boolean(accountWatcher.auto_relaunch);
      const relaunchOnExit = Boolean(accountWatcher.relaunch_on_exit);
      
      if (account.id) {
        body = '<form data-form="account" data-id="' + escapeHtml(account.id || '') + '"><div class="modal-body"><p class="form-error" hidden></p><div class="form-grid">' +
          '<div class="field"><label for="account-username">Username</label><input id="account-username" name="username" required maxlength="60" value="' + escapeHtml(account.username || '') + '" placeholder="e.g. AriaNebula" /></div>' +
          '<div class="field"><label for="account-user-id">Roblox User ID (optional)</label><input id="account-user-id" name="user_id" inputmode="numeric" pattern="[1-9][0-9]*" maxlength="20" autocomplete="off" value="' + escapeHtml(userId) + '" placeholder="e.g. 123456789" /></div>' +
          '<div class="field"><label for="account-display">Display name</label><input id="account-display" name="display_name" maxlength="80" value="' + escapeHtml(account.display_name || '') + '" placeholder="Display name" /></div>' +
          '<div class="field"><label for="account-group">Group</label><select id="account-group" name="group_id">' + groupOptions + '</select></div>' +
          '<div class="field"><label for="account-place-id">Default Game ID (Place ID)</label><input id="account-place-id" name="saved_place_id" type="number" min="1" step="1" value="' + escapeHtml(placeId) + '" placeholder="e.g. 2753915549" /></div>' +
          '<div class="field"><label for="account-fps">Instance FPS Cap</label><select id="account-fps" name="max_fps"><option value="0"' + (maxFps === 0 ? ' selected' : '') + '>Default (App Setting)</option><option value="30"' + (maxFps === 30 ? ' selected' : '') + '>30 FPS</option><option value="60"' + (maxFps === 60 ? ' selected' : '') + '>60 FPS</option><option value="120"' + (maxFps === 120 ? ' selected' : '') + '>120 FPS</option><option value="144"' + (maxFps === 144 ? ' selected' : '') + '>144 FPS</option><option value="240"' + (maxFps === 240 ? ' selected' : '') + '>240 FPS</option><option value="360"' + (maxFps === 360 ? ' selected' : '') + '>360 FPS</option></select></div>' +
          '<div class="field"><label for="account-color">Avatar color</label><select id="account-color" name="avatar_color"><option value="violet"' + (account.avatar_color === 'violet' ? ' selected' : '') + '>Violet</option><option value="mint"' + (account.avatar_color === 'mint' ? ' selected' : '') + '>Mint</option><option value="coral"' + (account.avatar_color === 'coral' ? ' selected' : '') + '>Coral</option><option value="blue"' + (account.avatar_color === 'blue' ? ' selected' : '') + '>Blue</option><option value="amber"' + (account.avatar_color === 'amber' ? ' selected' : '') + '>Amber</option></select></div>' +
          '<label class="form-check field"><input type="checkbox" name="potato_graphics"' + (potatoChecked ? ' checked' : '') + ' /> Enable Potato Mode (Minimum Graphics FastFlags)</label>' +
          '<label class="form-check field"><input type="checkbox" name="watcher_enabled"' + (watcherChecked ? ' checked' : '') + ' /> Watch this account (local Roblox process monitoring)</label>' +
          '<label class="form-check field"><input type="checkbox" name="watcher_auto_relaunch"' + (relaunchChecked ? ' checked' : '') + ' /> Auto-relaunch this account if it stops (arms the global watchdog too)</label>' +
          '<div class="field"><label for="account-relaunch-delay">Relaunch delay (seconds)</label><input id="account-relaunch-delay" name="watcher_relaunch_delay_seconds" type="number" min="1" max="3600" step="1" value="' + escapeHtml(accountWatcher.relaunch_delay_seconds) + '" /></div>' +
          '<div class="field"><label for="account-relaunch-attempts">Maximum relaunch attempts</label><input id="account-relaunch-attempts" name="watcher_relaunch_max_attempts" type="number" min="0" max="20" step="1" value="' + escapeHtml(accountWatcher.relaunch_max_attempts) + '" /></div>' +
          '<label class="form-check field full"><input type="checkbox" name="watcher_relaunch_on_exit"' + (relaunchOnExit ? ' checked' : '') + ' /> Relaunch even when the client closes without crashing (Windows never tells Astro why a client stopped)</label>' +
          '<div class="field full"><label for="account-notes">Private note</label><textarea id="account-notes" name="notes" maxlength="280" placeholder="Notes about this account">' + escapeHtml(account.notes || '') + '</textarea></div>' +
          '<label class="form-check field full"><input type="checkbox" name="favorite"' + (account.favorite ? ' checked' : '') + ' /> Keep in favorites</label></div>' +
          (account.has_saved_password ? '<div class="quick-login-banner"><div><strong>Imported password available</strong><p>The credential stays in DPAPI and is sent only to the isolated Roblox login page.</p></div><button class="button" type="button" data-action="start-saved-password-login" data-id="' + escapeHtml(account.id) + '">' + icon('key') + ' Sign in with saved password</button></div>' : '') + '</div>' +
          '<footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Cancel</button><button class="button button-primary" type="submit">' + icon('check') + ' Save changes</button></footer></form>';
      } else {
        body = '<div class="modal-body">' +
          '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:16px">' +
            '<button class="button button-primary" type="button" data-action="start-browser-login" style="flex-direction:column;gap:6px;padding:14px 10px;min-height:75px;text-align:center">' +
              icon('globe') + '<strong>Browser Sign-In</strong><small style="opacity:.85;font-weight:normal">Edge CDP (Auto-Close)</small>' +
            '</button>' +
            '<button class="button" type="button" data-action="open-cookie-login" style="flex-direction:column;gap:6px;padding:14px 10px;min-height:75px;text-align:center">' +
              icon('key') + '<strong>Paste Cookie</strong><small style="opacity:.7;font-weight:normal">.ROBLOSECURITY</small>' +
            '</button>' +
            '<button class="button" type="button" data-action="open-bulk-import" style="flex-direction:column;gap:6px;padding:14px 10px;min-height:75px;text-align:center">' +
              icon('upload') + '<strong>Bulk Import</strong><small style="opacity:.7;font-weight:normal">User:Pass / Multi</small>' +
            '</button>' +
          '</div>' +
          '<hr style="border:0;border-top:1px solid var(--line);margin:16px 0" />' +
          '<form data-form="account"><p class="form-error" hidden></p>' +
            '<strong style="display:block;font-size:0.85rem;margin-bottom:8px">Or manual profile creation:</strong>' +
            '<div class="form-grid">' +
              '<div class="field"><label for="account-username">Roblox Username *</label><input id="account-username" name="username" required maxlength="60" placeholder="e.g. AriaNebula" /></div>' +
              '<div class="field"><label for="account-group">Destination Group</label><select id="account-group" name="group_id">' + groupOptions + '</select></div>' +
              '<div class="field full"><label for="account-cookie-input">Cookie .ROBLOSECURITY (Optional)</label><textarea id="account-cookie-input" name="session" rows="2" placeholder="|_WARNING:-DO-NOT-SHARE-THIS..."></textarea></div>' +
            '</div>' +
            '<footer class="modal-foot" style="margin-top:16px;padding:0;border:0">' +
              '<button class="button" type="button" data-action="close-modal">Close</button>' +
              '<button class="button button-primary" type="submit">' + icon('plus') + ' Add Account</button>' +
            '</footer>' +
          '</form>' +
        '</div>';
      }
    } else if (modal.kind === 'server-launch') {
      const server = modal.server || {};
      const candidates = this.state.accounts.filter(function (account) { return account.has_session && account.status !== 'launching'; });
      const options = candidates.map(function (account) {
        const active = ['in_game', 'running'].includes(account.status);
        const label = (account.display_name || account.username) + ' (@' + account.username + ')' + (active ? ' - already running' : '');
        return '<option value="' + escapeHtml(account.id) + '"' + (active ? ' disabled' : '') + '>' + escapeHtml(label) + '</option>';
      }).join('');
      title = 'Choose the account to join';
      sub = 'This public server launch uses exactly the account selected below.';
      body = '<form data-form="server-launch" data-server="' + escapeHtml(server.id || '') + '"><div class="modal-body"><p class="form-error" hidden></p><p class="oauth-help">Place <strong>' + escapeHtml(this.state.gameId || '') + '</strong> · Job <span class="mono">' + escapeHtml(server.job_id || '') + '</span></p><div class="field full"><label for="server-launch-account">Roblox account</label><select id="server-launch-account" name="account_id" required' + (candidates.length ? '' : ' disabled') + '><option value="">Choose an account…</option>' + options + '</select><span class="mono">Astro will not silently choose the first account anymore.</span></div></div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Cancel</button><button class="button button-primary" type="submit"' + (candidates.some(function (account) { return !['in_game', 'running'].includes(account.status); }) ? '' : ' disabled') + '>' + icon('play') + ' Join with this account</button></footer></form>';
    } else if (modal.kind === 'server-distribution') {
      const candidates = this.state.accounts.filter(function (account) { return account.has_session && !['in_game', 'running', 'launching'].includes(account.status); });
      const options = candidates.map(function (account) { return '<option value="' + escapeHtml(account.id) + '">' + escapeHtml(account.display_name || account.username) + ' (@' + escapeHtml(account.username) + ')</option>'; }).join('');
      title = 'Smart server distribution';
      sub = 'Assign each selected account to the best eligible live servers without destination bleed.';
      body = '<form data-form="server-distribution"><div class="modal-body"><p class="form-error" hidden></p><div class="field full"><label>Accounts</label><select name="account_ids" multiple size="8" required>' + options + '</select></div><div class="field"><label>Maximum accounts per server</label><input name="max_per_server" type="number" min="1" max="20" value="1" required /></div><label class="form-check restore-confirm-check"><input type="checkbox" name="confirm" required /> I confirm these accounts may be queued using the displayed live server filters.</label></div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Cancel</button><button class="button button-primary" type="submit"' + (candidates.length ? '' : ' disabled') + '>Distribute & launch</button></footer></form>';
    } else if (modal.kind === 'region-probe') {
      const candidates = this.state.accounts.filter(function (account) { return account.has_session; });
      const options = candidates.map(function (account) { return '<option value="' + escapeHtml(account.id) + '">' + escapeHtml(account.display_name || account.username) + ' (@' + escapeHtml(account.username) + ')</option>'; }).join('');
      const serverCount = Math.min(16, this.state.servers.length);
      title = 'Load authenticated server regions';
      sub = 'RAM-compatible lookup for the first ' + serverCount + ' visible public servers.';
      body = '<form data-form="region-probe"><div class="modal-body"><p class="restore-warning">Roblox does not publish machine addresses in the normal server list. This sends the historical authenticated join-game-instance probe for each selected Job ID, then sends only public IPs to your configured region provider. It does not launch the Roblox client.</p><p class="form-error" hidden></p><div class="field full"><label for="region-account">Roblox account session</label><select id="region-account" name="account_id" required' + (options ? '' : ' disabled') + '><option value="">Choose a signed-in account…</option>' + options + '</select></div><label class="form-check restore-confirm-check"><input type="checkbox" name="confirm" required /> I confirm these authenticated Roblox and configured geolocation requests.</label></div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Cancel</button><button class="button button-primary" type="submit"' + (serverCount && options ? '' : ' disabled') + '>' + icon('globe') + ' Load up to 16 regions</button></footer></form>';
    } else if (modal.kind === 'uwp-manager') {
      const inventory = modal.inventory || { available: false, packages: [] };
      const packages = inventory.packages || [];
      const accountOptions = this.state.accounts.map(function (account) { return '<option value="' + escapeHtml(account.id) + '">' + escapeHtml(account.display_name || account.username) + ' (@' + escapeHtml(account.username) + ')</option>'; }).join('');
      const packageRows = packages.length ? packages.map(function (pkg) {
        const account = this.state.accounts.find(function (candidate) {
          return String(pkg.package_name || '').toLowerCase() === ('robloxcorporation.roblox.' + String(candidate.username || '').replace(/_/g, '-')).toLowerCase();
        });
        return '<div class="activity-row"><div class="activity-copy"><strong>' + escapeHtml(pkg.display_name || pkg.package_name) + '</strong><small>' + escapeHtml(pkg.status || 'Unknown') + (pkg.launchable ? ' · launchable' : ' · no launch point') + '</small></div><button class="button button-sm" type="button" data-action="launch-uwp-package" data-package="' + escapeHtml(pkg.package_full_name || '') + '"' + (pkg.launchable ? '' : ' disabled') + '>' + icon('play') + ' Launch</button>' + (account ? '<button class="button button-sm button-danger" type="button" data-action="open-uwp-unregister" data-id="' + escapeHtml(account.id) + '">' + icon('trash') + ' Unregister</button>' : '') + '</div>';
      }, this).join('') : '<div class="empty-notices">' + icon('monitor') + '<p>No registered Roblox UWP package was found for this Windows user.</p></div>';
      title = 'Roblox UWP Instance Manager';
      sub = inventory.available ? 'Discover, launch, create, or unregister per-account Microsoft Store clones.' : escapeHtml(inventory.reason || 'Windows UWP support is unavailable.');
      body = '<div class="modal-body"><p class="restore-warning">Clone creation copies the installed Store package, removes only its copied signature, edits the copied manifest, and registers it for the current user. Windows Developer Mode and the Store version of Roblox are required.</p><div class="activity-list">' + packageRows + '</div><form data-form="uwp-clone"><p class="form-error" hidden></p><div class="form-grid"><div class="field full"><label for="uwp-account">Account clone</label><select id="uwp-account" name="account_id" required' + (accountOptions ? '' : ' disabled') + '><option value="">Choose an account…</option>' + accountOptions + '</select></div><label class="form-check field full"><input type="checkbox" name="supports_multiple_instances" checked /> Write the historical SupportsMultipleInstances manifest flag</label><label class="form-check field full restore-confirm-check"><input type="checkbox" name="confirm" required /> I confirm this copies and registers a Windows AppX package for this account.</label></div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Close</button><button class="button button-primary" type="submit"' + (inventory.available && accountOptions ? '' : ' disabled') + '>' + icon('plus') + ' Create / update clone</button></footer></form></div>';
    } else if (modal.kind === 'uwp-unregister') {
      const account = modal.account || {};
      title = 'Unregister UWP clone?';
      sub = 'Remove the current-user AppX registration for ' + escapeHtml(account.display_name || account.username || 'this account') + '.';
      body = '<form data-form="uwp-unregister" data-id="' + escapeHtml(account.id || '') + '"><div class="modal-body"><p class="restore-warning">The registered clone stops appearing in Windows, while its copied files stay in Astro\'s UWP_Instances folder for recovery.</p><p class="form-error" hidden></p><label class="form-check restore-confirm-check"><input type="checkbox" name="confirm" required /> I confirm the exact per-account UWP clone should be unregistered.</label></div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Cancel</button><button class="button button-danger" type="submit">' + icon('trash') + ' Unregister clone</button></footer></form>';
    } else if (modal.kind === 'cookie-login') {
      title = 'Add via .ROBLOSECURITY Cookie';
      sub = 'Paste your Roblox session cookie directly to authenticate.';
      const groupOptions = '<option value="">No group (Ungrouped)</option>' + this.state.groups.map(function (group) { return '<option value="' + escapeHtml(group.id) + '">' + escapeHtml(group.name) + '</option>'; }).join('');
      body = '<form data-form="cookie-login"><div class="modal-body"><p class="form-error" hidden></p><div class="field full"><label for="cookie-str">Cookie .ROBLOSECURITY *</label><textarea id="cookie-str" name="cookie" rows="4" required placeholder="|_WARNING:-DO-NOT-SHARE-THIS..."></textarea></div><div class="field full" style="margin-top:10px"><label for="cookie-group">Destination Group</label><select id="cookie-group" name="group_id">' + groupOptions + '</select></div></div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Cancel</button><button class="button button-primary" type="submit">' + icon('key') + ' Add Account</button></footer></form>';
    } else if (modal.kind === 'oauth-login') {
      const operation = modal.operation || {};
      const status = String(operation.status || 'waiting');
      const state = {
        waiting: { title: 'Waiting for Roblox authorization', icon: 'refresh', detail: 'Continue in the system browser. This window checks only the public connection status.' },
        completed: { title: 'Roblox account connected', icon: 'check', detail: 'The public account profile is now linked to this workspace.' },
        cancelled: { title: 'Roblox authorization cancelled', icon: 'info', detail: 'No OAuth grant was added to this workspace.' },
        expired: { title: 'Roblox authorization expired', icon: 'alert', detail: 'Start a new official connection when you are ready.' },
        failed: { title: 'Roblox authorization could not finish', icon: 'alert', detail: 'No OAuth grant was added to this workspace.' }
      }[status] || { title: 'Roblox authorization status', icon: 'info', detail: 'The desktop bridge returned an unknown status.' };
      const hasExpiry = operation.expires_at && !Number.isNaN(Date.parse(operation.expires_at));
      const expiry = hasExpiry ? '<p class="oauth-flow-expiry">This request expires ' + escapeHtml(new Date(operation.expires_at).toLocaleString()) + '.</p>' : '';
      const message = operation.message ? '<p class="oauth-flow-message">' + escapeHtml(operation.message) + '</p>' : '';
      const cancelling = Boolean(operation.cancellation_requested);
      title = 'Connect Roblox account';
      sub = 'Official Open Cloud OAuth through the system browser.';
      body = '<div class="modal-body"><div class="oauth-flow-state ' + escapeHtml(status) + '" role="status" aria-live="polite"><span class="oauth-flow-icon">' + icon(state.icon) + '</span><div><strong>' + escapeHtml(state.title) + '</strong><p>' + escapeHtml(state.detail) + '</p>' + expiry + message + '</div></div><p class="oauth-help">The desktop bridge keeps the Open Cloud grant in the local protected vault. This does not create, expose, or change a Roblox game-client session.</p></div><footer class="modal-foot">' + (status === 'waiting' ? '<button class="button button-danger" type="button" data-action="cancel-oauth-login"' + (cancelling ? ' disabled' : '') + '>' + icon('x') + (cancelling ? ' Cancelling...' : ' Cancel') + '</button>' : '<button class="button" type="button" data-action="close-modal">Close</button><button class="button button-primary" type="button" data-action="retry-oauth-login">' + icon('refresh') + ' Try again</button>') + '</footer>';
    } else if (modal.kind === 'oauth-disconnect') {
      const account = modal.account || {};
      title = 'Disconnect Roblox OAuth?';
      sub = 'Keep the local profile and remove its protected Open Cloud grant.';
      body = '<form data-form="oauth-disconnect" data-id="' + escapeHtml(account.id || '') + '"><div class="modal-body"><p class="restore-warning">This removes the locally protected OAuth grant for <strong>' + escapeHtml(account.display_name || account.username || 'this account') + '</strong>. It does not sign out a Roblox browser or game client.</p><p class="form-error" hidden></p><label class="form-check restore-confirm-check"><input type="checkbox" name="confirm" required /> I understand this removes the local Open Cloud OAuth link.</label></div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Cancel</button><button class="button button-danger" type="submit">' + icon('logout') + ' Disconnect OAuth</button></footer></form>';
    } else if (modal.kind === 'watcher-rule') {
      const account = modal.account || {};
      const watcher = Object.assign({ enabled: true, auto_relaunch: false, relaunch_delay_seconds: 15, relaunch_max_attempts: 2, relaunch_on_crash: true, relaunch_on_exit: false }, account.watcher || {});
      const globalEnabled = Boolean(this.state.settings.watcher_auto_relaunch_enabled);
      title = 'Watcher rule for ' + (account.display_name || account.username || 'account');
      sub = globalEnabled ? 'This rule is opt-in and bounded for this one account.' : 'Save the rule here, then enable account relaunch rules in Settings > Instances before it can run.';
      body = '<form data-form="watcher-rule" data-id="' + escapeHtml(account.id || '') + '"><div class="modal-body"><p class="form-error" hidden></p><p class="oauth-help">A relaunch rule observes local process exits only. It does not authenticate an account, read browser data, or run remote scripts.</p><div class="form-grid"><label class="form-check field full"><input type="checkbox" name="watcher_enabled"' + (watcher.enabled === false ? '' : ' checked') + ' /> Watch this account with the local process monitor</label><label class="form-check field full"><input type="checkbox" name="auto_relaunch"' + (watcher.auto_relaunch ? ' checked' : '') + ' /> Enable a bounded automatic relaunch for this account</label><div class="field"><label for="watcher-delay">Delay before relaunch (seconds)</label><input id="watcher-delay" name="relaunch_delay_seconds" type="number" min="1" max="3600" step="1" required value="' + escapeHtml(watcher.relaunch_delay_seconds) + '" /></div><div class="field"><label for="watcher-attempts">Maximum attempts</label><input id="watcher-attempts" name="relaunch_max_attempts" type="number" min="0" max="20" step="1" required value="' + escapeHtml(watcher.relaunch_max_attempts) + '" /></div><label class="form-check field"><input type="checkbox" name="relaunch_on_crash"' + (watcher.relaunch_on_crash ? ' checked' : '') + ' /> Relaunch after a crash</label><label class="form-check field"><input type="checkbox" name="relaunch_on_exit"' + (watcher.relaunch_on_exit ? ' checked' : '') + ' /> Relaunch after a normal exit</label></div></div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Cancel</button><button class="button button-primary" type="submit">' + icon('check') + ' Save watcher rule</button></footer></form>';
    } else if (modal.kind === 'bind-instance') {
      const instance = modal.instance || {};
      const accounts = this.state.accounts;
      const options = accounts.map(function (account) { return '<option value="' + escapeHtml(account.id) + '">' + escapeHtml(account.display_name || account.username) + ' (@' + escapeHtml(account.username) + ')</option>'; }).join('');
      title = 'Associate observed instance';
      sub = 'Explicitly associate PID ' + (instance.pid || 'unknown') + ' with one local account and a Roblox Place ID.';
      body = '<form data-form="bind-instance" data-pid="' + escapeHtml(instance.pid || '') + '"><div class="modal-body"><p class="restore-warning">Only continue if you recognize this local Roblox process. The desktop bridge will record your explicit association; it does not infer browser or account login state.</p><p class="form-error" hidden></p><div class="form-grid"><div class="field full"><label for="bind-account">Local account</label><select id="bind-account" name="account_id" required' + (accounts.length ? '' : ' disabled') + '>' + options + '</select></div><div class="field"><label for="bind-place-id">Roblox Place ID</label><input id="bind-place-id" name="place_id" type="number" min="1" step="1" required value="' + escapeHtml(this.state.gameId || '') + '" placeholder="e.g. 2753915549" /></div><div class="field"><label for="bind-job-id">Server Job ID (optional)</label><input id="bind-job-id" name="job_id" maxlength="200" autocomplete="off" /></div></div><label class="form-check restore-confirm-check"><input type="checkbox" name="confirm" required /> I confirm this is the local Roblox process I want to associate.</label></div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Cancel</button><button class="button button-primary" type="submit"' + (accounts.length ? '' : ' disabled') + '>' + icon('users') + ' Associate instance</button></footer></form>';
    } else if (modal.kind === 'close-instance') {
      const instance = modal.instance || {};
      title = 'Close Roblox process ' + (instance.pid || '');
      sub = 'Request a confirmed local close through the instance monitor.';
      body = '<form data-form="close-instance" data-pid="' + escapeHtml(instance.pid || '') + '"><div class="modal-body"><p class="restore-warning">This asks the desktop bridge to close the observed local process. It does not delete an account or change browser data. The final process result is shown after the monitor refreshes.</p><p class="form-error" hidden></p><label class="form-check restore-confirm-check"><input type="checkbox" name="confirm" required /> I want to close this local Roblox process.</label></div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Cancel</button><button class="button button-danger" type="submit">' + icon('x') + ' Close instance</button></footer></form>';
    } else if (modal.kind === 'group') {
      const group = modal.group || {};
      const editing = Boolean(group.id);
      title = editing ? 'Edit group' : 'Create group'; sub = editing ? 'Update this group without changing its account members.' : 'Use a clear name and color to organize related accounts.';
      body = '<form data-form="group" data-id="' + escapeHtml(group.id || '') + '"><div class="modal-body"><p class="form-error" hidden></p><div class="form-grid"><div class="field full"><label for="group-name">Group name</label><input id="group-name" name="name" required maxlength="50" placeholder="e.g. Weekend squad" autofocus value="' + escapeHtml(group.name || '') + '" /></div><div class="field"><label for="group-color">Color</label><select id="group-color" name="color"><option value="violet"' + (group.color === 'violet' ? ' selected' : '') + '>Violet</option><option value="mint"' + (group.color === 'mint' ? ' selected' : '') + '>Mint</option><option value="coral"' + (group.color === 'coral' ? ' selected' : '') + '>Coral</option><option value="blue"' + (group.color === 'blue' ? ' selected' : '') + '>Blue</option><option value="amber"' + (group.color === 'amber' ? ' selected' : '') + '>Amber</option></select></div><div class="field"><label for="group-icon">Icon</label><select id="group-icon" name="icon"><option value="folder"' + (group.icon === 'folder' ? ' selected' : '') + '>Folder</option><option value="star"' + (group.icon === 'star' ? ' selected' : '') + '>Star</option><option value="cube"' + (group.icon === 'cube' ? ' selected' : '') + '>Cube</option></select></div></div></div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Cancel</button><button class="button button-primary" type="submit">' + icon(editing ? 'check' : 'plus') + (editing ? ' Save changes' : ' Create group') + '</button></footer></form>';
    } else if (modal.kind === 'move') {
      title = 'Move selected accounts'; sub = this.state.selected.size + ' account' + (this.state.selected.size === 1 ? '' : 's') + ' will be moved together.';
      body = '<form data-form="move"><div class="modal-body"><div class="field"><label for="move-group">Move to</label><select id="move-group" name="group_id"><option value="">Ungrouped</option>' + this.state.groups.map(function (group) { return '<option value="' + escapeHtml(group.id) + '">' + escapeHtml(group.name) + '</option>'; }).join('') + '</select></div></div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Cancel</button><button class="button button-primary" type="submit">' + icon('folder') + ' Move accounts</button></footer></form>';
    } else if (modal.kind === 'remove-game') {
      const game = modal.game || {};
      title = 'Remove ' + (game.title || 'this game') + '?';
      sub = 'Remove this local recent or favorite game record.';
      body = '<form data-form="remove-game" data-id="' + escapeHtml(game.place_id || '') + '"><div class="modal-body"><p class="restore-warning">This removes only the local game record and favorite marker. It does not alter anything on Roblox.</p><p class="form-error" hidden></p><label class="form-check restore-confirm-check"><input type="checkbox" name="confirm" required /> I understand this removes the game from this local workspace.</label></div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Cancel</button><button class="button button-danger" type="submit">' + icon('trash') + ' Remove game</button></footer></form>';
    } else if (modal.kind === 'delete') {
      const count = modal.ids.length;
      title = 'Remove ' + count + ' account' + (count === 1 ? '' : 's') + '?'; sub = 'This removes local account profiles and any matching tracked instances.';
      body = '<form data-form="delete"><div class="modal-body"><p class="form-error">This action cannot be undone from this workspace. Create a backup first if you may need these profiles again.</p></div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Cancel</button><button class="button button-danger" type="submit">' + icon('trash') + ' Remove account' + (count === 1 ? '' : 's') + '</button></footer></form>';
    } else if (modal.kind === 'bulk-edit') {
      const count = modal.ids.length;
      title = 'Bulk Edit (' + count + ' account' + (count === 1 ? '' : 's') + ' selected)';
      sub = 'Update Place ID, FPS Cap, Potato Mode, or Group for all selected accounts. Choose "Keep existing" for any field you do not wish to change.';
      const groupOptions = '<option value="keep">-- Keep existing group --</option><option value="">No group (Ungrouped)</option>' + this.state.groups.map(function (group) { return '<option value="' + escapeHtml(group.id) + '">' + escapeHtml(group.name) + '</option>'; }).join('');
      body = '<form data-form="bulk-edit"><div class="modal-body"><p class="form-error" hidden></p><div class="form-grid">' +
        '<div class="field"><label for="bulk-place-id">Default Game ID (Place ID)</label><input id="bulk-place-id" name="saved_place_id" value="keep" placeholder="Keep existing or enter Place ID..." /></div>' +
        '<div class="field"><label for="bulk-fps">Instance FPS Cap</label><select id="bulk-fps" name="max_fps"><option value="keep">-- Keep existing FPS --</option><option value="0">Default (App Setting)</option><option value="30">30 FPS</option><option value="60">60 FPS</option><option value="120">120 FPS</option><option value="144">144 FPS</option><option value="240">240 FPS</option><option value="360">360 FPS</option></select></div>' +
        '<div class="field"><label for="bulk-potato">Potato Mode (FastFlags)</label><select id="bulk-potato" name="potato_graphics"><option value="keep">-- Keep existing Potato Mode --</option><option value="true">Enable Potato Mode</option><option value="false">Disable Potato Mode</option></select></div>' +
        '<div class="field"><label for="bulk-group">Destination Group</label><select id="bulk-group" name="group_id">' + groupOptions + '</select></div>' +
        '</div></div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Cancel</button><button class="button button-primary" type="submit">' + icon('check') + ' Apply to ' + count + ' account' + (count === 1 ? '' : 's') + '</button></footer></form>';
    } else if (modal.kind === 'delete-group') {
      const group = modal.group || {};
      const memberCount = this.state.accounts.filter(function (account) { return String(account.group_id || '') === String(group.id || ''); }).length;
      title = 'Remove ' + (group.name || 'this group') + '?'; sub = 'The group is removed, but its accounts stay in the local workspace.';
      body = '<form data-form="delete-group"><div class="modal-body"><p class="form-error">' + memberCount + ' account' + (memberCount === 1 ? ' is' : 's are') + ' moved to Ungrouped. This cannot be undone without a backup.</p></div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Cancel</button><button class="button button-danger" type="submit">' + icon('trash') + ' Remove group</button></footer></form>';
    } else if (modal.kind === 'migrate') {
      title = 'Migrate legacy data'; sub = 'Choose the legacy data folder or file to inspect before importing.';
      body = '<form data-form="migrate"><div class="modal-body"><p class="form-error" hidden></p><div class="field"><label for="legacy-path">Legacy path</label><input id="legacy-path" name="path" required placeholder="C:\\Users\\you\\AppData\\Local\\Roblox Account Manager" /><span class="mono">The backend validates and migrates only supported data.</span></div></div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Cancel</button><button class="button button-primary" type="submit">' + icon('upload') + ' Inspect & migrate</button></footer></form>';
    } else if (modal.kind === 'restore') {
      const backups = (modal.backups || []).filter(function (backup) { return backup.verified; });
      title = 'Restore a backup'; sub = 'Only verified backups are shown. You will confirm the chosen backup before anything changes.';
      const rows = backups.map(function (backup, index) {
        return '<label class="restore-option"><input type="radio" name="backup_id" value="' + escapeHtml(backup.id) + '"' + (index === 0 ? ' checked' : '') + ' /><span class="restore-option-mark">' + icon('database') + '</span><span class="restore-option-copy"><strong>' + escapeHtml(backup.label || 'Backup') + '</strong><small>' + relativeTime(backup.created_at) + ' · ' + formatBytes(backup.size) + ' · verified</small></span></label>';
      }).join('');
      body = '<form data-form="restore-select"><div class="modal-body"><p class="restore-warning">Restoring replaces the current local workspace data. A safety backup is created automatically before the restore starts.</p><p class="form-error" hidden></p>' + (backups.length ? '<div class="restore-backup-list">' + rows + '</div>' : '<div class="empty-card"><div>' + icon('database') + '<strong>No verified backups available</strong><p>Create a backup first, then return here to restore it.</p></div></div>') + '</div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Cancel</button><button class="button button-primary" type="submit"' + (backups.length ? '' : ' disabled') + '>' + icon('chevronRight') + ' Continue</button></footer></form>';
    } else if (modal.kind === 'restore-confirm') {
      const backup = modal.backup || {};
      title = 'Confirm backup restore'; sub = 'This is the final confirmation before local data is replaced.';
      body = '<form data-form="restore-confirm" data-id="' + escapeHtml(backup.id || '') + '"><div class="modal-body"><p class="restore-warning">You are restoring <strong>' + escapeHtml(backup.label || 'the selected backup') + '</strong> from ' + relativeTime(backup.created_at) + '. Current accounts, groups, settings, and history will be replaced.</p><p class="form-error" hidden></p><label class="form-check restore-confirm-check"><input type="checkbox" name="confirm" required /> I understand this replaces my current local workspace data.</label></div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Cancel</button><button class="button button-danger" type="submit">' + icon('upload') + ' Restore this backup</button></footer></form>';
    } else if (modal.kind === 'import-metadata') {
      title = 'Import public metadata'; sub = 'Add compatible account, group, and game metadata from an Astro Account Manager export.';
      body = '<form data-form="import-metadata"><div class="modal-body"><p class="restore-warning">This import never transfers sessions, vault entries, cookies, tokens, or saved credentials. A safety backup is created before compatible public metadata is added.</p><p class="form-error" hidden></p><div class="field"><label for="metadata-path">Metadata JSON path</label><input id="metadata-path" name="path" autocomplete="off" required placeholder="C:\\Users\\you\\Documents\\astro-metadata-20260810.json" /><span class="mono">Choose a checksummed metadata export created by Astro Account Manager.</span></div><label class="form-check restore-confirm-check"><input type="checkbox" name="confirm" required /> I understand this adds public metadata and creates a pre-import backup.</label></div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Cancel</button><button class="button button-primary" type="submit">' + icon('download') + ' Import metadata</button></footer></form>';
    } else if (modal.kind === 'send-nexus') {
      const target = modal.target || 'all';
      title = 'Send Nexus Command';
      sub = 'Transmit a JSON command to Roblox client ' + escapeHtml(target);
      body = '<form data-form="send-nexus"><div class="modal-body"><p class="form-error" hidden></p><div class="field"><label for="nexus-target">Target</label><input id="nexus-target" name="target" required value="' + escapeHtml(target) + '" /></div><div class="field"><label for="nexus-command">Command</label><select id="nexus-command" name="command"><option value="execute">execute (Lua Script)</option><option value="teleport">teleport (Place/JobId)</option><option value="mute">mute</option><option value="unmute">unmute</option></select></div><div class="field"><label for="nexus-payload">Payload (Lua code or parameters)</label><textarea id="nexus-payload" name="payload" rows="4" placeholder="print(\'Hello Nexus!\')"></textarea></div></div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Cancel</button><button class="button button-primary" type="submit">' + icon('rocket') + ' Send</button></footer></form>';
    } else if (modal.kind === 'bulk-import') {
      title = 'Add Accounts / Bulk Import';
      sub = 'Choose your method: browser login, direct cookie paste, or bulk account import.';
      body = '<form data-form="bulk-import"><div class="modal-body"><p class="form-error" hidden></p><div class="quick-login-banner" style="background: var(--surface-card); border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 16px; display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap;"><div><strong>Quick Add Options:</strong><p style="margin: 4px 0 0 0; opacity: 0.8; font-size: 0.85rem;">Use the built-in browser or paste a raw session cookie.</p></div><div style="display: flex; gap: 8px;"><button class="button button-primary" type="button" data-action="start-manual-browser-login">' + icon('globe') + ' Roblox Browser</button><button class="button button-secondary" type="button" data-action="open-add-cookie">🍪 Paste Cookie</button></div></div><div class="field"><label for="bulk-text">Or paste multiple accounts / cookies (multi-format)</label><textarea id="bulk-text" name="raw_text" rows="8" required placeholder="User1:Pass123\nUser2,Pass456\nUser3:Pass789:_|WARNING...\n_|WARNING:-..."></textarea></div></div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Cancel</button><button class="button button-primary" type="submit">' + icon('upload') + ' Import Accounts</button></footer></form>';
    } else if (modal.kind === 'cookie-add') {
      title = '🍪 Sign in via Cookie (.ROBLOSECURITY)';
      sub = 'Paste your .ROBLOSECURITY cookie below to add and authenticate the account immediately.';
      body = '<form data-form="cookie-add"><div class="modal-body"><p class="form-error" hidden></p><div class="field"><label for="raw-cookie-input">Cookie .ROBLOSECURITY</label><textarea id="raw-cookie-input" name="cookie" rows="6" required placeholder="_|WARNING:-DO-NOT-SHARE-THIS..."></textarea><span class="mono">The cookie will be validated with Roblox APIs and stored in the Windows DPAPI Vault.</span></div></div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Cancel</button><button class="button button-primary" type="submit">' + icon('check') + ' Add with this Cookie</button></footer></form>';
    } else if (modal.kind === 'account-utilities') {
      const accounts = this.state.accounts;
      const options = accounts.length ? accounts.map(function (acc) {
        return '<option value="' + escapeHtml(acc.id) + '">' + escapeHtml(acc.display_name || acc.username) + ' (@' + escapeHtml(acc.username) + ')</option>';
      }).join('') : '<option value="">No accounts available</option>';
      title = '⚙️ Account Utilities';
      sub = 'Advanced authenticated Roblox account management options.';
      body = '<form data-form="account-utilities"><div class="modal-body"><p class="form-error" hidden></p>' +
        '<div class="field"><label for="util-account">Target account</label><select id="util-account" name="account_id" required>' + options + '</select></div>' +
        '<div class="field"><label for="util-action">Action to run</label><select id="util-action" name="action_kind">' +
        '<option value="quick_login">Quick Log In code (6 digits)</option>' +
        '<option value="get_cookie">Extract/Copy .ROBLOSECURITY cookie</option>' +
        '<option value="refresh_session">Validate and refresh stored session</option>' +
        '<option value="export_cookie">Export raw .ROBLOSECURITY cookie to file</option>' +
        '<option value="auth_ticket">Generate/copy authentication ticket</option>' +
        '<option value="rbx_link">Generate/copy rbx-player link (PlaceId[:JobId])</option>' +
        '<option value="logout_all">Logout all other sessions</option>' +
        '<option value="display_name">Change display name</option>' +
        '<option value="friend">Send friend request</option>' +
        '<option value="block">Block user</option>' +
        '<option value="unblock">Unblock user</option>' +
        '<option value="unblock_all">Unblock ALL users</option>' +
        '<option value="privacy">Follow privacy (All / Followers / Following / Friends / NoOne)</option>' +
        '<option value="unlock_pin">Legacy PIN unlock (retired by Roblox)</option>' +
        '<option value="avatar">Wear avatar assets (comma-separated IDs)</option>' +
        '<option value="outfits">List user outfits (User ID)</option>' +
        '<option value="wear_outfit">Wear saved outfit (Outfit ID)</option>' +
        '<option value="universe">List universe places (Universe ID)</option>' +
        '<option value="open_browser">Open authenticated Roblox browser (URL optional)</option>' +
        '<option value="join_group">Join Roblox group (ID or link)</option>' +
        '<option value="saved_password">Copy saved password from vault</option>' +
        '<option value="password">Change password</option>' +
        '<option value="email">Change email address</option>' +
        '</select></div>' +
        '<div class="field"><label for="util-payload">Parameter / Payload</label><input id="util-payload" name="payload" placeholder="Code, ID/username, privacy, assets, password or email..." /></div>' +
        '</div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Cancel</button><button class="button button-primary" type="submit">' + icon('check') + ' Execute action</button></footer></form>';
    }
    return '<div class="modal-backdrop" data-action="close-modal-backdrop"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title"><header class="modal-head"><div><h2 id="modal-title">' + escapeHtml(title) + '</h2><p>' + escapeHtml(sub) + '</p></div><button class="icon-button" type="button" data-action="close-modal" aria-label="Close dialog">' + icon('x') + '</button></header>' + body + '</section></div>';
  }

  paletteItems() {
    const q = this.state.paletteQuery.trim().toLowerCase();
    const matches = function (text) { return !q || String(text).toLowerCase().includes(q); };
    const actions = [
      { kind: 'action', action: 'create-account', icon: 'plus', title: 'Add account', detail: 'Create a profile for a Roblox identity', shortcut: 'A' },
      { kind: 'action', action: 'create-group', icon: 'folder', title: 'Create group', detail: 'Organize a set of accounts' },
      { kind: 'route', route: 'accounts', icon: 'users', title: 'Open accounts', detail: 'Manage account profiles', shortcut: 'G A' },
      { kind: 'route', route: 'games', icon: 'gamepad', title: 'Browse games & servers', detail: 'Choose a game and server', shortcut: 'G G' },
      { kind: 'route', route: 'instances', icon: 'monitor', title: 'Open instances', detail: 'Monitor active sessions', shortcut: 'G I' },
      { kind: 'route', route: 'settings', icon: 'settings', title: 'Open settings', detail: 'Appearance, watcher, backups', shortcut: 'G S' },
      { kind: 'action', action: 'refresh-instances', icon: 'refresh', title: 'Refresh instances', detail: 'Run a process scan', shortcut: 'Ctrl R' }
    ].concat(this.nexusEnabled()
      ? [{ kind: 'route', route: 'nexus', icon: 'command', title: 'Open Nexus executor', detail: 'Execute Lua scripts on clients', shortcut: 'G N' }]
      : []).filter(function (item) { return matches(item.title + ' ' + item.detail); });
    const accounts = this.state.accounts.filter(function (account) { return matches(account.username + ' ' + account.display_name); }).slice(0, 5).map(function (account) { return { kind: 'account', id: account.id, icon: 'users', title: account.display_name || account.username, detail: '@' + account.username + ' · ' + statusText(account.status) }; });
    const games = this.state.games.filter(function (game) { return matches(game.title + ' ' + game.creator); }).slice(0, 4).map(function (game) { return { kind: 'game', id: game.place_id, icon: 'gamepad', title: game.title, detail: game.creator || 'Game' }; });
    return { actions: actions, accounts: accounts, games: games };
  }

  paletteSection(label, items) {
    if (!items.length) return '';
    return '<p class="palette-label">' + label + '</p>' + items.map(function (item) { return '<button class="palette-item" type="button" data-action="palette-item" data-kind="' + item.kind + '" data-id="' + escapeHtml(item.id || '') + '" data-route="' + escapeHtml(item.route || '') + '" data-next-action="' + escapeHtml(item.action || '') + '"><span class="palette-item-icon">' + icon(item.icon) + '</span><span class="palette-item-copy"><strong>' + escapeHtml(item.title) + '</strong><span>' + escapeHtml(item.detail) + '</span></span>' + (item.shortcut ? '<kbd>' + escapeHtml(item.shortcut) + '</kbd>' : '') + '</button>'; }).join('');
  }

  renderPalette() {
    const items = this.paletteItems();
    const results = this.paletteSection('Quick actions', items.actions) + this.paletteSection('Accounts', items.accounts) + this.paletteSection('Games', items.games) || '<div class="empty-notices">' + icon('search') + '<p>No results for this search.</p></div>';
    return '<div class="palette-backdrop" data-action="close-palette-backdrop"><section class="palette" role="dialog" aria-modal="true" aria-label="Command palette"><div class="palette-search">' + icon('search') + '<input id="palette-input" autocomplete="off" placeholder="Search accounts, games, settings, actions…" value="' + escapeHtml(this.state.paletteQuery) + '" /><kbd>Esc</kbd></div><div class="palette-results">' + results + '</div><footer class="palette-foot"><span><kbd>↑↓</kbd> navigate</span><span><kbd>Enter</kbd> choose</span><span><kbd>Esc</kbd> close</span></footer></section></div>';
  }

  async handleClick(event) {
    const button = event.target.closest('[data-action]');
    if (!button) return;
    const action = button.dataset.action;
    if (action === 'close-modal-backdrop' && event.target === button) { await this.dismissOAuthModal(); return; }
    if (action === 'close-palette-backdrop' && event.target === button) { this.closePalette(); return; }
    if (action === 'navigate') { this.navigate(button.dataset.route); return; }
    if (await this.handleFleetAction(action, button)) return;
    if (action === 'navigate-accounts') { this.navigate('accounts'); return; }
    if (action === 'open-palette') { this.openPalette(); return; }
    if (action === 'close-modal') { await this.dismissOAuthModal(); return; }
    if (action === 'open-windows-startup') { this.openWindowsStartupModal(button.dataset.enabled === 'true'); return; }
    if (action === 'open-settings-reset') { this.openModal({ kind: 'settings-reset' }); return; }
    if (action === 'refresh-windows-startup') { await this.loadWindowsStartupStatus(true); return; }
    if (action === 'toggle-notifications') { this.state.notificationsOpen = !this.state.notificationsOpen; this.renderOverlays(); return; }
    if (action === 'toggle-theme') { await this.updateSettings({ theme: this.state.settings.theme === 'light' ? 'dark' : 'light' }, false); return; }
    if (action === 'set-accent') { await this.updateSettings({ accent: button.dataset.accent }, false); return; }
    if (action === 'create-account') { this.openModal({ kind: 'account', account: {} }); return; }
    if (action === 'open-private-link') { this.openModal({ kind: 'private-link' }); return; }
    if (action === 'add-macro-block') {
      const defaults = { wait: { type: 'wait', milliseconds: 1000 }, key_press: { type: 'key_press', key: 'W', milliseconds: 80 }, mouse_click: { type: 'mouse_click', x: 0.5, y: 0.5, button: 'left' }, text: { type: 'text', value: 'hello' }, condition: { type: 'condition', check: 'runtime_above', value: '300', then: 'stop' }, launch: { type: 'launch' }, teleport: { type: 'teleport', place_id: '', job_id: '' }, restart: { type: 'restart' } };
      this.state.macroDraftBlocks.push(defaults[button.dataset.kind] || defaults.wait); this.render(); return;
    }
    if (action === 'set-macro-editor-mode') { this.state.macroEditorMode = button.dataset.mode === 'dsl' ? 'dsl' : 'blocks'; this.render(); return; }
    if (action === 'move-macro-block') {
      const from = Number(button.dataset.index);
      const to = from + Number(button.dataset.direction || 0);
      if (Number.isInteger(from) && Number.isInteger(to) && from >= 0 && from < this.state.macroDraftBlocks.length && to >= 0 && to < this.state.macroDraftBlocks.length) {
        const moved = this.state.macroDraftBlocks.splice(from, 1)[0];
        this.state.macroDraftBlocks.splice(to, 0, moved);
        this.render();
      }
      return;
    }
    if (action === 'remove-macro-block') { this.state.macroDraftBlocks.splice(Number(button.dataset.index), 1); this.render(); return; }
    if (action === 'refresh-macros') { this.state.macros = asArray(await this.bridge.call('list_macros')); this.state.macroRuns = asArray(await this.bridge.call('list_macro_runs')); this.render(); return; }
    if (action === 'start-macro') {
      const input = document.getElementById('macro-target-' + button.dataset.id);
      const targetPid = input && input.value ? input.value : (this.state.instances.length === 1 ? String(this.state.instances[0].pid) : '');
      if (!targetPid) { this.toast('warning', 'Choose an instance', 'Select a verified Roblox PID for this macro.'); return; }
      try { const started = unwrap(await this.bridge.call('start_macro', button.dataset.id, Number(targetPid))) || {}; this.state.macroRuns = asArray(await this.bridge.call('list_macro_runs')); this.render(); const delivery = started.delivery_mode === 'minimized_input' ? 'while minimized and invisible' : 'with foreground Windows input'; this.toast('success', 'Macro started', 'PID ' + targetPid + ' is running ' + delivery + '.'); } catch (error) { this.toast('error', 'Macro failed', error.message); }
      return;
    }
    if (action === 'stop-macro') { try { await this.bridge.call('stop_macro', button.dataset.id); this.state.macroRuns = asArray(await this.bridge.call('list_macro_runs')); this.render(); } catch (error) { this.toast('error', 'Could not stop macro', error.message); } return; }
    if (action === 'delete-macro') { if (!window.confirm('Delete this local macro?')) return; try { await this.bridge.call('delete_macro', button.dataset.id, true); this.state.macros = asArray(await this.bridge.call('list_macros')); this.render(); } catch (error) { this.toast('error', 'Could not delete macro', error.message); } return; }
    if (action === 'export-support-bundle') { try { const result = unwrap(await this.bridge.call('export_support_bundle')) || {}; this.toast('success', 'Support ZIP created', result.filename || result.path || 'The redacted support bundle is ready.'); } catch (error) { this.toast('error', 'Support ZIP failed', error.message); } return; }
    if (action === 'check-updates') { try { const result = unwrap(await this.bridge.call('check_for_updates')) || {}; this.toast('info', result.update_available ? 'Update available' : 'Astro is current', result.update_available ? ('Version ' + result.latest_version + ' is available.') : ('Current version ' + result.current_version + '.')); } catch (error) { this.toast('error', 'Update check failed', error.message); } return; }
    if (action === 'download-update') { try { const result = unwrap(await this.bridge.call('download_update', true)) || {}; this.state.updater = unwrap(await this.bridge.call('get_update_status')) || {}; this.render(); this.toast('success', 'Update downloaded', result.filename || 'Validated update staged.'); } catch (error) { this.toast('error', 'Update download failed', error.message); } return; }
    if (action === 'install-update') { try { await this.bridge.call('schedule_update_install', true); this.state.updater = unwrap(await this.bridge.call('get_update_status')) || {}; this.render(); this.toast('success', 'Install scheduled', 'The validated EXE will replace Astro after exit.'); } catch (error) { this.toast('error', 'Install scheduling failed', error.message); } return; }
    if (action === 'cancel-update') { try { this.state.updater = unwrap(await this.bridge.call('cancel_update', true)) || {}; this.render(); this.toast('info', 'Staged update removed'); } catch (error) { this.toast('error', 'Could not cancel update', error.message); } return; }
    if (action === 'open-bulk-import') { this.openModal({ kind: 'bulk-import' }); return; }
    if (action === 'open-add-cookie') { this.openModal({ kind: 'cookie-add' }); return; }
    if (action === 'start-manual-browser-login' || action === 'start-browser-login' || action === 'start-saved-password-login') {
      try {
        const usingSavedPassword = action === 'start-saved-password-login';
        const res = usingSavedPassword
          ? await this.bridge.call('start_saved_password_browser_login', button.dataset.id)
          : await this.bridge.call('start_manual_browser_login');
        this.toast('info', 'Roblox Login Browser Opened', usingSavedPassword ? 'Astro filled the imported credential in the isolated browser. Complete any verification Roblox requests.' : 'Sign in on Roblox in the dedicated browser window. Your session cookie will be captured automatically!');
        const operationId = res && res.operation_id;
        if (!operationId) throw new Error('The desktop bridge did not return a browser sign-in operation.');
        // Keep the rest of the account interface usable while the isolated
        // browser performs its sign-in and this lightweight poll continues.
        this.closeModal();
        this.render();
        let finished = false;
        for (let attempt = 0; attempt < 200; attempt += 1) {
          await new Promise(function (resolve) { window.setTimeout(resolve, 1500); });
          const status = await this.bridge.call('poll_manual_browser_login', operationId);
          if (status.status === 'completed') {
            await this.resync();
            this.closeModal();
            this.render();
            this.toast('success', 'Account Added', (status.account && status.account.username ? status.account.username : 'The Roblox account') + ' is now stored in the local vault.');
            finished = true;
            break;
          }
          if (status.status === 'failed') throw new Error(status.message || 'Roblox sign-in failed.');
        }
        if (!finished) throw new Error('Roblox sign-in timed out before a session was captured.');
      } catch (err) {
        this.toast('error', 'Browser Error', err.message || 'Could not open login browser.');
      }
      return;
    }
    if (action === 'open-region-probe') {
      this.openModal({ kind: 'region-probe' });
      return;
    }
    if (action === 'open-server-distribution') {
      this.openModal({ kind: 'server-distribution' });
      return;
    }
    if (action === 'toggle-hide-usernames') {
      const previous = this.state.hideUsernames;
      const requested = !previous;
      this.state.hideUsernames = requested;
      this.applyTheme();
      this.render();
      const saved = await this.updateSettings({ privacy_mode: requested }, false);
      if (!saved) {
        this.state.hideUsernames = previous;
        this.applyTheme();
        this.render();
      }
      return;
    }
    if (action === 'toggle-uwp') {
      try {
        const inventory = unwrap(await this.bridge.call('list_uwp_packages')) || { available: false, packages: [] };
        this.openModal({ kind: 'uwp-manager', inventory: inventory });
      } catch (error) {
        this.toast('error', 'UWP Manager', error.message || 'Could not inspect Windows UWP packages.');
      }
      return;
    }
    if (action === 'launch-uwp-package') {
      try {
        await this.bridge.call('launch_uwp_package', button.dataset.package);
        this.toast('success', 'UWP Launch Requested', 'Windows is opening the selected registered Roblox package.');
      } catch (error) {
        this.toast('error', 'UWP Launch Failed', error.message);
      }
      return;
    }
    if (action === 'open-uwp-unregister') {
      const account = this.findAccount(button.dataset.id);
      if (account) this.openModal({ kind: 'uwp-unregister', account: account });
      return;
    }
    if (action === 'shuffle-job-id') {
      const placeInput = $('#ram-place-id');
      const placeId = placeInput ? Number(placeInput.value) : null;
      if (!placeId) { this.toast('error', 'Place ID Required', 'Please enter a valid Place ID.'); return; }
      try {
        const res = unwrap(await this.bridge.call('get_random_server', placeId));
        if (res && res.job_id) {
          this.state.ramJobId = res.job_id;
          const jobInput = $('#ram-job-id');
          if (jobInput) jobInput.value = res.job_id;
          this.toast('success', 'Random Job ID Selected', res.job_id);
        } else {
          this.toast('info', 'No Server Found', 'Could not fetch a Job ID for this place.');
        }
      } catch (err) {
        this.toast('error', 'Job ID Error', err.message);
      }
      return;
    }
    if (action === 'save-place-id') {
      const placeInput = $('#ram-place-id');
      const jobInput = $('#ram-job-id');
      const placeId = placeInput ? Number(placeInput.value) : null;
      const jobId = jobInput ? jobInput.value.trim() : '';
      const selectedIds = Array.from(this.state.selected);
      if (!selectedIds.length && this.state.accounts.length === 1) selectedIds.push(this.state.accounts[0].id);
      if (!selectedIds.length) { this.toast('info', 'Select Accounts', 'Select at least one account.'); return; }
      if (!Number.isSafeInteger(placeId) || placeId <= 0) { this.toast('error', 'Invalid Place ID', 'Enter a positive Roblox Place ID before saving.'); return; }
      try {
        for (const id of selectedIds) {
          await this.bridge.call('update_account', id, { saved_place_id: placeId, saved_job_id: jobId });
        }
        await this.refreshAccountsState();
        this.toast('success', 'Place ID Saved', 'Saved for ' + selectedIds.length + ' account(s).');
      } catch (error) {
        this.toast('error', 'Could not save Place ID', error.message);
      }
      return;
    }
    if (action === 'ram-join-server') {
      const placeInput = $('#ram-place-id');
      const jobInput = $('#ram-job-id');
      const placeId = placeInput ? Number(placeInput.value) : null;
      const jobId = jobInput ? jobInput.value.trim() : '';
      const selectedIds = Array.from(this.state.selected);
      if (!selectedIds.length && this.state.accounts.length === 1) selectedIds.push(this.state.accounts[0].id);
      if (!selectedIds.length) { this.toast('info', 'Select an account', 'Check the account or accounts you want to launch.'); return; }
      const target = {};
      if (placeId) target.place_id = placeId;
      if (jobId) target.job_id = jobId;
      try {
        if (selectedIds.length === 1) {
          await this.launch(selectedIds[0], Object.keys(target).length ? target : null);
        } else {
          const delayMs = Number((((this.state.settings || {}).categories || {}).general || {}).launch_delay_ms || 2500);
          await this.bridge.call('start_batch_launch', selectedIds, Object.keys(target).length ? target : null, Math.max(0.5, delayMs / 1000));
          this.toast('success', 'Server Launch Requested', selectedIds.length + ' account launches were queued.');
          this.trackBatchLaunch();
        }
      } catch (error) {
        this.toast('error', 'Could not launch server', error.message);
      }
      return;
    }
    if (action === 'ram-follow-user') {
      const userInput = $('#ram-follow-user');
      const targetUser = userInput ? userInput.value.trim() : '';
      if (!targetUser) { this.toast('error', 'Username Required', 'Enter the player username to follow.'); return; }
      const selectedIds = Array.from(this.state.selected);
      const accId = selectedIds[0] || (this.state.accounts[0] && this.state.accounts[0].id);
      if (!accId) { this.toast('error', 'Account Required', 'Select at least one local account.'); return; }
      try {
        const searched = unwrap(await this.bridge.call('search_players', targetUser, 1)) || [];
        if (!searched.length) throw new Error('Player not found.');
        const presence = unwrap(await this.bridge.call('get_player_presence', searched[0].user_id)) || {};
        const placeInput = $('#ram-place-id');
        const placeId = Number(presence.place_id || (placeInput && placeInput.value));
        if (!placeId) throw new Error('This player is not currently in a known game. Select a Place ID to scan it.');
        let jobId = presence.job_id || null;
        if (!jobId) {
          this.toast('info', 'Scanning public servers', 'Astro is comparing bounded public player thumbnails, as RAM 3.7.2 did.');
          const matched = unwrap(await this.bridge.call('find_player_server', placeId, searched[0].user_id, 10));
          if (!matched || !matched.job_id) throw new Error('The player was not found in the scanned public servers.');
          jobId = matched.job_id;
        }
        await this.bridge.call('launch_account', accId, { place_id: placeId, job_id: jobId });
        this.toast('success', 'Player Follow', 'Launching into ' + searched[0].name + '\'s server!');
      } catch (err) {
        this.toast('error', 'Follow Error', err.message);
      }
      return;
    }
    if (action === 'ram-set-alias') {
      const aliasInput = $('#ram-alias-input');
      const newAlias = aliasInput ? aliasInput.value.trim() : '';
      const selectedIds = Array.from(this.state.selected);
      if (!selectedIds.length) { this.toast('info', 'Select an Account', 'Check at least one account.'); return; }
      try {
        for (const id of selectedIds) await this.bridge.call('update_account', id, { alias: newAlias });
        await this.refreshAccountsState();
        this.toast('success', 'Alias Updated', 'The local account alias was saved.');
      } catch (error) {
        this.toast('error', 'Could not update alias', error.message);
      }
      return;
    }
    if (action === 'ram-set-description') {
      const descInput = $('#ram-desc-input');
      const newDesc = descInput ? descInput.value.trim() : '';
      const selectedIds = Array.from(this.state.selected);
      if (!selectedIds.length) { this.toast('info', 'Select an Account', 'Check at least one account.'); return; }
      try {
        for (const id of selectedIds) await this.bridge.call('update_account', id, { description: newDesc, notes: newDesc });
        await this.refreshAccountsState();
        this.toast('success', 'Description Updated', 'Description saved successfully.');
      } catch (error) {
        this.toast('error', 'Could not update description', error.message);
      }
      return;
    }
    if (!this.nexusEnabled() && NEXUS_ACTIONS.has(action)) return;
    if (action === 'open-account-utilities') { this.openModal({ kind: 'account-utilities' }); return; }
    if (action === 'open-cookie-login') { this.openModal({ kind: 'cookie-login' }); return; }
    if (action === 'open-nexus-panel') { this.openModal({ kind: 'send-nexus' }); return; }
    if (action === 'edit-account') { const account = this.findAccount(button.dataset.id); if (account) this.openModal({ kind: 'account', account: account }); return; }
    if (action === 'open-oauth-settings') { this.state.settingsTab = 'oauth'; this.navigate('settings'); return; }
    if (action === 'start-oauth-login') { await this.startOAuthLogin(); return; }
    if (action === 'retry-oauth-login') { await this.startOAuthLogin(); return; }
    if (action === 'cancel-oauth-login') { await this.cancelOAuthLogin(); return; }
    if (action === 'refresh-oauth-account') { await this.refreshOAuthAccount(button.dataset.id); return; }
    if (action === 'open-disconnect-oauth') { const account = this.findAccount(button.dataset.id); if (account) this.openModal({ kind: 'oauth-disconnect', account: account }); return; }
    if (action === 'refresh-public-profile') { await this.refreshPublicProfile(button.dataset.id); return; }
    if (action === 'refresh-public-presence') { await this.refreshPublicPresence(button.dataset.id); return; }
    if (action === 'open-account-watcher') { const account = this.findAccount(button.dataset.id); if (account) this.openModal({ kind: 'watcher-rule', account: account }); return; }
    if (action === 'open-bind-instance') { const instance = this.findInstance(button.dataset.pid); if (instance) this.openModal({ kind: 'bind-instance', instance: instance }); return; }
    if (action === 'open-close-instance') { const instance = this.findInstance(button.dataset.pid); if (instance) this.openModal({ kind: 'close-instance', instance: instance }); return; }
    if (action === 'save-window-layout') {
      if (!window.confirm('Save this verified Roblox window position for its bound account?')) return;
      try {
        await this.bridge.call('capture_instance_window', Number(button.dataset.pid), true);
        this.toast('success', 'Window position saved', 'The bound account will reuse this geometry when window memory is enabled.');
      } catch (error) { this.toast('error', 'Could not save window position', error.message); }
      return;
    }
    if (action === 'restore-window-layout') {
      if (!window.confirm('Restore the saved Roblox window position for this bound account?')) return;
      try {
        await this.bridge.call('restore_instance_window', Number(button.dataset.pid), true);
        this.toast('success', 'Window position restored', 'The verified Roblox window was moved to its saved geometry.');
      } catch (error) { this.toast('error', 'Could not restore window position', error.message); }
      return;
    }
    if (action === 'set-instance-visibility') {
      try {
        await this.bridge.call('set_instance_visibility', Number(button.dataset.pid), button.dataset.visible === 'true');
        await this.refreshInstances();
      } catch (error) { this.toast('error', 'Could not change window visibility', error.message); }
      return;
    }
    if (action === 'show-all-instances') {
      const targets = this.state.instances.filter(function (instance) { return instance.visibility && instance.visibility.window_found && instance.visibility.hidden; });
      try {
        await Promise.all(targets.map(function (instance) { return this.bridge.call('set_instance_visibility', Number(instance.pid), true); }.bind(this)));
        await this.refreshInstances();
        this.toast('success', 'Roblox windows shown', targets.length + ' hidden window(s) restored without activation.');
      } catch (error) { this.toast('error', 'Could not show every window', error.message); }
      return;
    }
    if (action === 'create-group') { this.openModal({ kind: 'group' }); return; }
    if (action === 'edit-group') { const group = this.groupFor(button.dataset.id); if (group) this.openModal({ kind: 'group', group: group }); return; }
    if (action === 'delete-group') { const group = this.groupFor(button.dataset.id); if (group) this.openModal({ kind: 'delete-group', group: group }); return; }
    if (action === 'account-select') { this.toggleSelection(button.dataset.id); return; }
    if (action === 'clear-selection') { this.state.selected.clear(); this.render(); return; }
    if (action === 'account-view') { this.state.accountView = button.dataset.view; this.render(); return; }
    if (action === 'toggle-group') {
      const group = this.groupFor(button.dataset.id);
      if (!group) return;
      const previous = Boolean(group.collapsed);
      group.collapsed = !previous;
      this.render();
      try {
        const saved = unwrap(await this.bridge.call('update_group', group.id, { collapsed: group.collapsed }));
        if (saved && typeof saved === 'object') Object.assign(group, saved);
        this.render();
      } catch (error) {
        group.collapsed = previous;
        this.render();
        this.toast('error', 'Could not update group', error.message || 'The previous group state was restored.');
      }
      return;
    }
    if (action === 'launch') { await this.launch(button.dataset.id); return; }
    if (action === 'bulk-launch') { await this.bulkLaunch(); return; }
    if (action === 'toggle-favorite') { await this.toggleFavorite(button.dataset.id); return; }
    if (action === 'bulk-move') { this.openModal({ kind: 'move' }); return; }
    if (action === 'bulk-edit') { this.openModal({ kind: 'bulk-edit', ids: Array.from(this.state.selected) }); return; }
    if (action === 'bulk-delete') { this.openModal({ kind: 'delete', ids: Array.from(this.state.selected) }); return; }
    if (action === 'select-game') { await this.loadGame(button.dataset.id, true); return; }
    if (action === 'toggle-game-favorite') { await this.toggleGameFavorite(button.dataset.id); return; }
    if (action === 'open-remove-game') { const game = this.state.games.find(function (item) { return String(item.place_id) === String(button.dataset.id); }); if (game) this.openModal({ kind: 'remove-game', game: game }); return; }
    if (action === 'refresh-servers') { await this.loadGame(this.state.gameId, true); return; }
    if (action === 'join-server') { await this.joinServer(button.dataset.server); return; }
    if (action === 'start-nexus-server') { await this.startNexusServer(); return; }
    if (action === 'stop-nexus-server') { await this.stopNexusServer(); return; }
    if (action === 'copy-nexus-script') { await this.copyNexusLuaScript(); return; }
    if (action === 'open-send-nexus') { this.openModal({ kind: 'send-nexus', target: button.dataset.target }); return; }
    /* --- Nexus Executor actions --- */
    if (action === 'nexus-execute') { await this.nexusExecute(); return; }
    if (action === 'nexus-clear-editor') { this.state.nexusExecutorCode = "-- Write your Lua script here\nprint('Hello from Nexus!')\n"; this.render(); this.nexusSyncLineNumbers(); return; }
    if (action === 'nexus-clear-log') { this.state.nexusExecutorLog = []; this.render(); return; }
    if (action === 'nexus-target-client') { this.state.nexusExecutorTarget = button.dataset.target || 'all'; this.render(); this.nexusSyncLineNumbers(); return; }
    if (action === 'nexus-quick') { this.state.nexusExecutorCode = button.dataset.script || ''; await this.nexusExecute(); return; }
    if (action === 'refresh-nexus-status') { await this.refreshNexusStatus(); return; }
    if (action === 'smart-launch-preview' || action === 'smart-launch-group') {
      const select = document.getElementById('fleet-group');
      const groupId = select && select.value ? select.value : '';
      if (!groupId) { this.toast('warning', 'Choose a group', 'Pick a group before launching a wave.'); return; }
      this.state.fleet = Object.assign({}, this.state.fleet, { groupId: groupId });
      try {
        if (action === 'smart-launch-preview') {
          const preview = unwrap(await this.bridge.call('plan_smart_launch', null, groupId)) || {};
          this.state.fleet = Object.assign({}, this.state.fleet, { plan: preview, resources: preview.resources || null });
          this.render();
          this.toast('info', 'Launch preview', 'Planned ' + (preview.planned || 0) + ' account(s) in ' + (preview.waves || 0) + ' wave(s). Nothing was launched.');
          return;
        }
        const started = unwrap(await this.bridge.call('start_smart_launch', null, groupId, null)) || {};
        const plan = started.plan || {};
        this.state.fleet = Object.assign({}, this.state.fleet, { plan: plan, resources: started.resources || null });
        this.render();
        this.toast('success', 'Smart launch queued', 'Queued ' + (plan.planned || 0) + ' account(s), ' + (plan.delay_seconds || 0) + 's apart.');
      } catch (error) { this.toast('error', 'Smart launch failed', error && error.message ? error.message : String(error)); }
      return;
    }
    if (action === 'stop-all-macros') {
      try {
        const result = unwrap(await this.bridge.call('stop_all_macros')) || {};
        this.state.macroRuns = asArray(await this.bridge.call('list_macro_runs'));
        this.render();
        this.toast('success', 'Macros stopped', 'Stopped ' + (result.count || 0) + ' run(s).');
      } catch (error) { this.toast('error', 'Stop failed', error && error.message ? error.message : String(error)); }
      return;
    }
    if (action === 'apply-resource-plan') {
      try {
        const result = unwrap(await this.bridge.call('apply_resource_plan', null)) || {};
        this.state.fleet = Object.assign({}, this.state.fleet, { resources: result.plan || null });
        this.render();
        if (result.applied) this.toast('success', 'Frame rates applied', 'Global cap set to ' + result.fps + ' FPS. Roblox applies one cap to every window.');
        else this.toast('warning', 'Nothing applied', result.reason || 'The plan had nothing to apply.');
      } catch (error) { this.toast('error', 'Frame rates failed', error && error.message ? error.message : String(error)); }
      return;
    }
    if (action === 'refresh-instances') { await this.refreshInstances(); return; }
    if (action === 'refresh-diagnostics') { await this.refreshDiagnostics(); return; }
    if (action === 'open-compatibility-check') {
      try { this.openModal({ kind: 'compatibility', report: unwrap(await this.bridge.call('get_compatibility_report')) || {} }); } catch (error) { this.toast('error', 'Compatibility check failed', error.message); }
      return;
    }
    if (action === 'acknowledge-roblox-version') {
      if (!window.confirm('Record this Roblox version only after reviewing the compatibility checks?')) return;
      try { const report = unwrap(await this.bridge.call('acknowledge_roblox_version', true)) || {}; this.openModal({ kind: 'compatibility', report: report }); this.toast('success', 'Roblox baseline recorded', report.roblox_version || 'Current version'); } catch (error) { this.toast('error', 'Could not record Roblox version', error.message); }
      return;
    }
    if (action === 'open-restore') { await this.openRestoreModal(); return; }
    if (action === 'export-metadata') { await this.exportMetadata(); return; }
    if (action === 'open-import-metadata') { this.openModal({ kind: 'import-metadata' }); return; }
    if (action === 'backup') { await this.backup(); return; }
    if (action === 'migrate') { this.openModal({ kind: 'migrate' }); return; }
    if (action === 'settings-tab') { this.state.settingsTab = button.dataset.tab; this.render(); if (this.state.settingsTab === 'general') void this.loadWindowsStartupStatus(false); if (this.state.settingsTab === 'roblox') void this.loadRobloxSettings(false); return; }
    if (action === 'refresh-roblox-settings') { await this.loadRobloxSettings(true); return; }
    if (action === 'apply-roblox-profile') {
      if (!window.confirm('Apply this profile to Roblox global settings now?')) return;
      try { this.state.robloxSettings = unwrap(await this.bridge.call('apply_roblox_settings_profile', button.dataset.id, true)) || this.state.robloxSettings; this.state.robloxSettings.loaded = true; this.render(); this.toast('success', 'Roblox profile applied', 'The XML and FPS settings were written and read back.'); } catch (error) { this.toast('error', 'Could not apply Roblox profile', error.message); }
      return;
    }
    if (action === 'delete-roblox-profile') {
      if (!window.confirm('Delete this saved Roblox settings profile?')) return;
      try { this.state.robloxSettings = unwrap(await this.bridge.call('delete_roblox_settings_profile', button.dataset.id)) || this.state.robloxSettings; this.state.robloxSettings.loaded = true; this.render(); this.toast('success', 'Roblox profile deleted', 'The active Roblox settings were not changed.'); } catch (error) { this.toast('error', 'Could not delete Roblox profile', error.message); }
      return;
    }
    if (action === 'copy-place') { await this.copyText(button.dataset.value, 'Place ID'); return; }
    if (action === 'dismiss-notification') { await this.dismissNotification(button.dataset.id); return; }
    if (action === 'clear-account-filter') { this.state.accountQuery = ''; this.state.accountStatus = 'all'; this.render(); return; }
    if (action === 'clear-game-filter') { this.state.gameQuery = ''; this.render(); void this.loadGames(); return; }
    if (action === 'palette-item') { await this.executePalette(button.dataset); return; }
  }

  async handleSubmit(event) {
    const form = event.target.closest('form[data-form]');
    if (!form) return;
    event.preventDefault();
    const values = Object.fromEntries(new FormData(form).entries());
    if (form.dataset.form === 'account') values.favorite = new FormData(form).get('favorite') === 'on';
    const errorTarget = $('.form-error', form);
    try {
      const submit = $('button[type="submit"]', form);
      if (submit) submit.disabled = true;
      if (form.dataset.form === 'account-utilities') {
        const accountId = values.account_id;
        const actionKind = values.action_kind;
        const payload = (values.payload || '').trim();
        if (!accountId) throw new Error('Please select an account.');

        if (actionKind === 'quick_login') {
          if (!/^\d{6}$/.test(payload)) throw new Error('Please enter exactly 6 digits for Quick Log In.');
          await this.bridge.call('quick_log_in_account', accountId, payload);
          this.toast('success', 'Quick Log In', 'Code validated successfully!');
        } else if (actionKind === 'password') {
          const separator = payload.indexOf(':');
          if (separator < 1 || separator === payload.length - 1) throw new Error('Payload format required: CurrentPassword:NewPassword');
          await this.bridge.call('change_account_password', accountId, payload.slice(0, separator), payload.slice(separator + 1));
          this.toast('success', 'Password Changed', 'Password updated successfully!');
        } else if (actionKind === 'email') {
          const separator = payload.indexOf(':');
          if (separator < 1 || separator === payload.length - 1) throw new Error('Payload format required: CurrentPassword:NewEmail');
          await this.bridge.call('change_account_email', accountId, payload.slice(0, separator), payload.slice(separator + 1));
          this.toast('success', 'Email Change', 'Email change initiated!');
        } else if (actionKind === 'logout_all') {
          await this.bridge.call('logout_all_account_sessions', accountId);
          this.toast('success', 'Sessions Logged Out', 'All other sessions have been logged out!');
        } else if (actionKind === 'block') {
          if (!payload) throw new Error('Target User ID or Username is required.');
          await this.bridge.call('block_account_user', accountId, payload);
          this.toast('success', 'User Blocked', 'User blocked successfully!');
        } else if (actionKind === 'unblock') {
          if (!payload) throw new Error('Target User ID or Username is required.');
          await this.bridge.call('unblock_account_user', accountId, payload);
          this.toast('success', 'User Unblocked', 'User unblocked successfully!');
        } else if (actionKind === 'unblock_all') {
          const res = await this.bridge.call('unblock_all_account_users', accountId);
          this.toast('success', 'Bulk Unblock', (res.unblocked_count || 0) + ' user(s) unblocked!');
        } else if (actionKind === 'display_name') {
          if (!payload || payload.length > 20) throw new Error('Display name must contain between 1 and 20 characters.');
          await this.bridge.call('set_account_display_name', accountId, payload);
          this.toast('success', 'Display Name', 'Display name updated successfully!');
        } else if (actionKind === 'friend') {
          if (!payload) throw new Error('Target User ID or Username is required.');
          await this.bridge.call('send_account_friend_request', accountId, payload);
          this.toast('success', 'Friend Request', 'Friend request sent successfully!');
        } else if (actionKind === 'privacy') {
          const privacy = payload.toLowerCase().replace(/\s+/g, '');
          if (!['all', 'followers', 'following', 'friends', 'noone', 'no_one'].includes(privacy)) throw new Error('Use All, Followers, Following, Friends, or NoOne.');
          await this.bridge.call('set_account_follow_privacy', accountId, privacy);
          this.toast('success', 'Follow Privacy', 'Follow privacy updated successfully!');
        } else if (actionKind === 'unlock_pin') {
          if (!/^\d{4}$/.test(payload)) throw new Error('Account PIN must contain exactly 4 digits.');
          await this.bridge.call('unlock_account_pin', accountId, payload);
          this.toast('success', 'Account PIN', 'Account PIN unlock accepted.');
        } else if (actionKind === 'avatar') {
          const assetIds = payload.split(',').map(function (value) { return value.trim(); }).filter(Boolean);
          if (!assetIds.length || assetIds.length > 100 || assetIds.some(function (value) { return !/^[1-9][0-9]*$/.test(value); })) throw new Error('Provide 1 to 100 positive asset IDs separated by commas.');
          await this.bridge.call('set_account_avatar', accountId, assetIds.map(Number));
          this.toast('success', 'Avatar', 'Avatar assets updated successfully!');
        } else if (actionKind === 'outfits') {
          if (!/^[1-9][0-9]*$/.test(payload)) throw new Error('Enter a positive Roblox User ID.');
          const rows = await this.bridge.call('list_user_outfits', payload);
          await this.writeClipboard(JSON.stringify(rows, null, 2));
          this.toast('success', 'Outfits copied', asArray(rows).length + ' outfit record(s) copied as JSON.');
        } else if (actionKind === 'wear_outfit') {
          if (!/^[1-9][0-9]*$/.test(payload)) throw new Error('Enter a positive Outfit ID.');
          await this.bridge.call('wear_account_outfit', accountId, payload);
          this.toast('success', 'Outfit applied', 'The historical outfit assets were applied to this account.');
        } else if (actionKind === 'universe') {
          if (!/^[1-9][0-9]*$/.test(payload)) throw new Error('Enter a positive Universe ID.');
          const rows = await this.bridge.call('list_universe_places', payload);
          await this.writeClipboard(JSON.stringify(rows, null, 2));
          this.toast('success', 'Universe places copied', asArray(rows).length + ' place record(s) copied as JSON.');
        } else if (actionKind === 'open_browser') {
          await this.bridge.call('open_account_browser', accountId, payload || 'https://www.roblox.com/home');
          this.toast('success', 'Authenticated browser opened', 'The isolated browser received this account session and opened Roblox.');
        } else if (actionKind === 'join_group') {
          if (!payload) throw new Error('Enter a Roblox Group ID or group link.');
          await this.bridge.call('join_account_group', accountId, payload);
          this.toast('success', 'Group joined', 'Roblox accepted the join request.');
        } else if (actionKind === 'saved_password') {
          const result = await this.bridge.call('get_account_saved_password', accountId);
          await this.writeClipboard(result.password || '');
          this.toast('warning', 'Saved password copied', 'The plaintext value is now in the Windows clipboard.');
        } else if (actionKind === 'get_cookie') {
          const res = await this.bridge.call('get_account_cookie', accountId);
          await this.writeClipboard(res.cookie || '');
          this.toast('success', 'Cookie Copied', '.ROBLOSECURITY cookie copied to clipboard!');
        } else if (actionKind === 'refresh_session') {
          await this.bridge.call('refresh_account_session', accountId);
          await this.resync();
          this.toast('success', 'Session Validated', 'The stored Roblox session and account identity were refreshed.');
        } else if (actionKind === 'export_cookie') {
          const confirmed = window.confirm('Export this raw Roblox session as plaintext? Anyone with the file can use the account session.');
          if (!confirmed) throw new Error('Raw session export was cancelled.');
          const res = await this.bridge.call('export_account_sessions', [accountId], true);
          this.toast('warning', 'Raw Session Exported', (res.filename || res.path || 'Export created') + ' contains a plaintext session.');
        } else if (actionKind === 'auth_ticket') {
          const res = await this.bridge.call('generate_auth_ticket', accountId);
          await this.writeClipboard(res.ticket || '');
          this.toast('success', 'Authentication Ticket Copied', 'The short-lived Roblox authentication ticket was copied.');
        } else if (actionKind === 'rbx_link') {
          const parts = payload.split(':');
          if (!/^[1-9][0-9]*$/.test(parts[0] || '') || parts.length > 2) throw new Error('Use PlaceId or PlaceId:JobId.');
          const res = await this.bridge.call('generate_rbx_player_link', accountId, Number(parts[0]), parts[1] || null);
          await this.writeClipboard(res.link || '');
          this.toast('success', 'rbx-player Link Copied', 'The authenticated local launch link was copied.');
        }
        this.closeModal();
        this.render();
      } else if (form.dataset.form === 'macro') {
        const mode = String(values.mode || 'blocks');
        const actions = [];
        if (mode === 'blocks') {
          $$('.macro-block', form).forEach(function (row) {
            const block = { type: row.dataset.blockType };
            $$('[data-block-field]', row).forEach(function (input) {
              const key = input.dataset.blockField;
              block[key] = input.type === 'number' ? Number(input.value) : input.value;
            });
            if (block.type === 'mouse_click') block.button = 'left';
            if (block.type === 'condition') {
              // A visual condition holds exactly one action. The DSL editor is
              // there when a deeper IF tree is needed.
              block.actions = [{ type: String(block.then || 'stop') }];
              delete block.then;
            }
            if (block.type === 'teleport' && !String(block.job_id || '').trim()) delete block.job_id;
            actions.push(block);
          });
          if (!actions.length) throw new Error('Add at least one macro block.');
        }
        await this.bridge.call('save_macro', { name: values.name, description: values.description || '', account_id: values.account_id || null, mode: mode, source: values.source || '', actions: actions });
        this.state.macros = asArray(await this.bridge.call('list_macros'));
        this.state.macroDraftName = '';
        this.state.macroDraftDescription = '';
        this.render(); this.toast('success', 'Macro saved', values.name + ' is ready for a verified instance.');
      } else if (form.dataset.form === 'roblox-global-settings' || form.dataset.form === 'roblox-settings-profile') {
        const advancedText = String(values.advanced_json || '').trim();
        let advanced = {};
        if (advancedText) {
          try { advanced = JSON.parse(advancedText); } catch (_) { throw new Error('Advanced overrides must be a valid JSON object.'); }
          if (!advanced || Array.isArray(advanced) || typeof advanced !== 'object') throw new Error('Advanced overrides must be a JSON object.');
        }
        const settingsValues = {
          fps: Number(values.fps),
          volume_percent: Number(values.volume_percent),
          graphics_quality: Number(values.graphics_quality),
          camera_mode: Number(values.camera_mode),
          fullscreen: new FormData(form).get('fullscreen') === 'on',
          advanced: advanced
        };
        if (!Number.isInteger(settingsValues.fps) || (settingsValues.fps !== -1 && (settingsValues.fps < 1 || settingsValues.fps > 1000))) throw new Error('FPS must be -1 or a whole number from 1 to 1000.');
        if (!Number.isInteger(settingsValues.volume_percent) || settingsValues.volume_percent < 0 || settingsValues.volume_percent > 100) throw new Error('Volume must be a whole number from 0 to 100.');
        if (!Number.isInteger(settingsValues.graphics_quality) || settingsValues.graphics_quality < 0 || settingsValues.graphics_quality > 10) throw new Error('Graphics quality must be a whole number from 0 to 10.');
        if (!Number.isInteger(settingsValues.camera_mode) || settingsValues.camera_mode < 0 || settingsValues.camera_mode > 10) throw new Error('Camera mode must be a whole number from 0 to 10.');
        if (form.dataset.form === 'roblox-global-settings') {
          if (new FormData(form).get('confirm') !== 'on') throw new Error('Confirm the Roblox global settings change.');
          this.state.robloxSettings = unwrap(await this.bridge.call('apply_roblox_settings', settingsValues, true)) || this.state.robloxSettings;
          this.toast('success', 'Roblox settings applied', 'GlobalBasicSettings_13.xml and the FPS configuration were written and verified.');
        } else {
          this.state.robloxSettings = unwrap(await this.bridge.call('save_roblox_settings_profile', { name: values.name, group_id: values.group_id || null, values: settingsValues })) || this.state.robloxSettings;
          this.toast('success', 'Roblox profile saved', String(values.name || '') + ' is ready to apply.');
          form.reset();
        }
        this.state.robloxSettings.loaded = true;
        this.render();
      } else if (form.dataset.form === 'discord-settings') {
        let gameOverrides;
        try { gameOverrides = JSON.parse(String(values.game_overrides || '[]')); } catch (_) { throw new Error('Discord per-game overrides must be valid JSON.'); }
        if (!Array.isArray(gameOverrides)) throw new Error('Discord per-game overrides must be a JSON array.');
        const payload = { categories: { discord: {
          enabled: new FormData(form).get('enabled') === 'on',
          client_id: String(values.client_id || '').trim(),
          strategy: values.strategy || 'latest',
          show_account: new FormData(form).get('show_account') === 'on',
          details_template: String(values.details_template || '{game}'),
          state_template: String(values.state_template || '{instances} active · {account}'),
          large_image: String(values.large_image || '').trim(),
          large_text: String(values.large_text || 'Astro Account Manager'),
          game_overrides: gameOverrides
        } } };
        const result = unwrap(await this.bridge.call('update_settings', payload)) || {};
        this.state.settings = Object.assign({}, this.state.settings, result);
        if (payload.categories.discord.enabled) this.state.discordPresence = unwrap(await this.bridge.call('refresh_discord_presence')) || {};
        this.render(); this.toast('success', 'Discord settings saved', payload.categories.discord.enabled ? 'Rich Presence was refreshed.' : 'Rich Presence is disabled.');
      } else if (form.dataset.form === 'private-link') {
        await this.bridge.call('launch_account_from_private_link', values.account_id, values.link);
        this.closeModal(); await this.resync(); this.render(); this.toast('success', 'Private server launch requested', 'Windows is opening Roblox with the selected stored account.');
      } else if (form.dataset.form === 'roblox-background') {
        if (values.confirm !== 'on') throw new Error('Explicit confirmation is required.');
        const result = unwrap(await this.bridge.call('close_running_roblox', true)) || {};
        this.closeModal(); this.state.robloxBackground = unwrap(await this.bridge.call('get_roblox_background_status')) || {};
        this.render(); this.toast('success', 'Roblox close requested', Number(result.closed || 0) + ' client(s) closed. Multi Roblox can now acquire its state before the next launch.');
      } else if (form.dataset.form === 'region-probe') {
        if (values.confirm !== 'on') throw new Error('Confirm the authenticated region probe before continuing.');
        const account = this.findAccount(values.account_id);
        if (!account || !account.has_session) throw new Error('Choose a signed-in Roblox account.');
        const jobIds = this.state.servers.slice(0, 16).map(function (server) { return server.job_id; }).filter(Boolean);
        if (!this.state.gameId || !jobIds.length) throw new Error('Select a game with visible public servers first.');
        const result = unwrap(await this.bridge.call('probe_server_regions', account.id, Number(this.state.gameId), jobIds)) || {};
        const byJob = new Map(asArray(result.servers).map(function (server) { return [String(server.job_id), server]; }));
        this.state.servers = this.state.servers.map(function (server) {
          const probed = byJob.get(String(server.job_id));
          return probed ? Object.assign({}, server, { region: probed.region || server.region, ping: probed.ping === null || probed.ping === undefined ? server.ping : probed.ping, region_probe_reason: probed.reason || null }) : server;
        });
        this.closeModal();
        this.render();
        this.toast(result.resolved ? 'success' : 'warning', 'Server region probe finished', (result.resolved || 0) + ' of ' + jobIds.length + ' region(s) resolved.');
      } else if (form.dataset.form === 'server-distribution') {
        if (values.confirm !== 'on') throw new Error('Confirm the server distribution before launching.');
        if (!this.state.gameId) throw new Error('Select a Roblox game first.');
        const accountIds = new FormData(form).getAll('account_ids').map(String);
        const maxPerServer = Number(values.max_per_server);
        if (!accountIds.length) throw new Error('Select at least one account.');
        if (!Number.isInteger(maxPerServer) || maxPerServer < 1 || maxPerServer > 20) throw new Error('Maximum accounts per server must be between 1 and 20.');
        const result = unwrap(await this.bridge.call('run_server_distribution', accountIds, this.state.gameId, maxPerServer, this.state.serverFilters)) || {};
        this.closeModal();
        this.trackBatchLaunch();
        this.toast('success', 'Server distribution queued', asArray(result.plan && result.plan.steps).length + ' account(s) received isolated server destinations.');
      } else if (form.dataset.form === 'server-launch') {
        const modal = this.state.modal;
        const server = modal && modal.kind === 'server-launch' ? modal.server : null;
        const account = this.findAccount(values.account_id);
        if (!server) throw new Error('The selected public server is no longer available.');
        if (!account || !account.has_session) throw new Error('Choose an available signed-in account.');
        if (['in_game', 'running', 'launching'].includes(account.status)) throw new Error('This account already has an active or pending Roblox launch.');
        this.closeModal();
        await this.launch(account.id, { place_id: this.state.gameId, job_id: server.job_id, region: server.region });
      } else if (form.dataset.form === 'uwp-clone') {
        const formData = new FormData(form);
        if (values.confirm !== 'on') throw new Error('Confirm the Windows AppX clone registration before continuing.');
        const account = this.findAccount(values.account_id);
        if (!account) throw new Error('Choose the local account for this UWP clone.');
        await this.bridge.call(
          'create_uwp_account_clone',
          account.id,
          true,
          formData.get('supports_multiple_instances') === 'on'
        );
        const inventory = unwrap(await this.bridge.call('list_uwp_packages')) || { available: false, packages: [] };
        this.openModal({ kind: 'uwp-manager', inventory: inventory });
        this.toast('success', 'UWP Clone Registered', 'Windows registered the per-account clone for ' + (account.display_name || account.username) + '.');
      } else if (form.dataset.form === 'uwp-unregister') {
        if (values.confirm !== 'on') throw new Error('Confirm the exact UWP clone unregister operation.');
        const account = this.findAccount(form.dataset.id) || (this.state.modal && this.state.modal.account);
        if (!account) throw new Error('The local account for this UWP clone no longer exists.');
        await this.bridge.call('unregister_uwp_account_clone', account.id, true);
        const inventory = unwrap(await this.bridge.call('list_uwp_packages')) || { available: false, packages: [] };
        this.openModal({ kind: 'uwp-manager', inventory: inventory });
        this.toast('success', 'UWP Clone Unregistered', 'The registration was removed and Astro preserved the copied files.');
      } else if (form.dataset.form === 'cookie-add') {
        const rawCookie = (values.cookie || '').trim();
        if (!rawCookie) throw new Error('Please paste a valid .ROBLOSECURITY cookie.');
        const res = await this.bridge.call('add_account_from_cookie', rawCookie);
        await this.resync();
        this.closeModal();
        this.render();
        this.toast('success', 'Account Added', 'Account @' + (res.username || 'Roblox') + ' connected!');
      } else if (form.dataset.form === 'cookie-login') {
        const cookie = (values.cookie || '').trim();
        const groupId = values.group_id || null;
        if (!cookie) throw new Error('Please paste a valid .ROBLOSECURITY cookie.');
        const res = unwrap(await this.bridge.call('add_account_from_cookie', cookie, groupId)) || {};
        await this.resync();
        this.closeModal();
        this.render();
        this.toast('success', 'Account Added', 'Account @' + (res.username || 'Roblox') + ' connected successfully!');
      } else if (form.dataset.form === 'send-nexus') {
        const target = String(values.target || 'all').trim();
        const command = String(values.command || 'execute').trim();
        const payload = values.payload || '';
        await this.sendNexusCommand(target, command, payload);
        this.closeModal();
        this.render();
      } else if (form.dataset.form === 'bulk-import') {
        const rawText = values.raw_text || '';
        const res = await this.bridge.call('import_bulk_accounts', rawText);
        await this.resync();
        this.closeModal();
        this.render();
        this.toast(res.failed ? 'warning' : 'success', 'Bulk Import Completed', res.imported + ' account(s) imported out of ' + res.total_parsed + (res.failed ? '; ' + res.failed + ' failed.' : '.'));
        (res.warnings || []).slice(0, 3).forEach(function (message) { this.toast('warning', 'Bulk import warning', message); }, this);
      } else if (form.dataset.form === 'settings-reset') {
        if (values.confirm !== 'on') throw new Error('Confirm the settings reset before continuing.');
        const output = unwrap(await this.bridge.call('reset_settings', values.category || null, true)) || {};
        this.state.settings = Object.assign({}, this.state.settings, output);
        this.state.settings.accent_raw = this.state.settings.accent;
        this.state.settings.accent = accentToken(this.state.settings.accent);
        this.closeModal();
        this.applyTheme();
        this.render();
        this.toast('success', 'Settings reset', values.category ? 'The selected category now uses its defaults.' : 'All local preferences now use their defaults.');
      } else if (form.dataset.form === 'windows-startup') {
        if (values.confirm !== 'on') throw new Error('Confirm the Windows startup change before continuing.');
        if (form.dataset.enabled !== 'true' && form.dataset.enabled !== 'false') throw new Error('The requested Windows startup state is invalid.');
        const enabled = form.dataset.enabled === 'true';
        const status = await this.setWindowsStartup(enabled);
        this.closeModal(); this.render();
        this.toast('success', enabled ? 'Windows startup enabled' : 'Windows startup disabled', enabled ? 'Astro Account Manager will start for the current Windows user.' : 'Astro Account Manager will no longer start automatically.');
        if (status.needs_repair) this.toast('info', 'Windows startup needs attention', 'Windows accepted the change, but the startup registration still reports that it needs repair.');
      } else if (form.dataset.form === 'region-settings') {
        const formData = new FormData(form);
        const timeout = Number(values.region_lookup_timeout_seconds);
        const cacheTtl = Number(values.region_cache_ttl_seconds);
        const provider = String(values.region_lookup_provider || '').trim();
        const format = String(values.region_lookup_format || '').trim();
        if (provider && (!/^https?:\/\//i.test(provider) || !provider.includes('{ip}'))) throw new Error('The region provider must be an HTTP(S) URL containing {ip}.');
        if (!format || format.length > 120) throw new Error('The region display format is required.');
        if (!Number.isFinite(timeout) || timeout < 0.5 || timeout > 30) throw new Error('Region timeout must be between 0.5 and 30 seconds.');
        if (!Number.isFinite(cacheTtl) || cacheTtl < 30 || cacheTtl > 86400) throw new Error('Region cache lifetime must be between 30 and 86400 seconds.');
        const network = {
          region_lookup_enabled: formData.get('region_lookup_enabled') === 'on',
          region_lookup_provider: provider,
          region_lookup_format: format,
          region_lookup_timeout_seconds: timeout,
          region_cache_ttl_seconds: cacheTtl
        };
        const output = unwrap(await this.bridge.call('update_settings', { categories: { network: network } })) || {};
        this.state.settings = Object.assign({}, this.state.settings, output);
        this.render();
        this.toast('success', 'Region settings saved', 'Server addresses will be resolved only when lookup is enabled and an address is available.');
      } else if (form.dataset.form === 'api-settings') {
        const formData = new FormData(form);
        const port = Number(values.port);
        if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('The local API port must be between 1 and 65535.');
        const api = {
          enabled: formData.get('enabled') === 'on',
          host: formData.get('allow_external') === 'on' ? '0.0.0.0' : '127.0.0.1',
          port: port,
          allow_external: formData.get('allow_external') === 'on',
          allow_get_cookie: formData.get('allow_get_cookie') === 'on',
          allow_launch_account: formData.get('allow_launch_account') === 'on',
          allow_account_editing: formData.get('allow_account_editing') === 'on',
          allow_import_cookie: formData.get('allow_import_cookie') === 'on',
          allow_get_accounts: formData.get('allow_get_accounts') === 'on',
          legacy_password_auth_enabled: formData.get('legacy_password_auth_enabled') === 'on'
        };
        const output = unwrap(await this.bridge.call('update_settings', { categories: { api: api } })) || {};
        this.state.settings = Object.assign({}, this.state.settings, output);
        this.render();
        this.toast('success', 'Local API settings saved', 'Restart Astro Account Manager to apply the listener state.');
      } else if (form.dataset.form === 'watcher-health') {
        const memory = Number(values.memory_low_mb);
        const grace = Number(values.health_grace_seconds);
        const timeout = Number(values.unconnected_timeout_seconds);
        const title = String(values.expected_window_title || '').trim();
        if (!Number.isInteger(memory) || memory < 50 || memory > 4096) throw new Error('Low-memory threshold must be between 50 and 4096 MB.');
        if (!Number.isFinite(grace) || grace < 5 || grace > 600) throw new Error('Watcher health grace must be between 5 and 600 seconds.');
        if (!Number.isFinite(timeout) || timeout < 5 || timeout > 3600) throw new Error('Unconnected timeout must be between 5 and 3600 seconds.');
        if (!title || title.length > 128) throw new Error('Expected Roblox window title is required.');
        const output = unwrap(await this.bridge.call('update_settings', { categories: { watcher: { memory_low_mb: memory, health_grace_seconds: grace, unconnected_timeout_seconds: timeout, expected_window_title: title } } })) || {};
        this.state.settings = Object.assign({}, this.state.settings, output);
        this.render();
        this.toast('success', 'Watcher thresholds saved', 'Automatic rules remain gated by instance closing and their individual toggles.');
      } else if (form.dataset.form === 'account') {
        const userId = String(values.user_id || '').trim();
        if (userId && !/^[1-9][0-9]*$/.test(userId)) throw new Error('Roblox User ID must be a positive whole number.');
        values.user_id = userId;
        const placeIdRaw = String(values.saved_place_id || '').trim();
        if (placeIdRaw && (!/^[1-9][0-9]*$/.test(placeIdRaw) || Number(placeIdRaw) <= 0)) throw new Error('Roblox Place ID must be a valid positive whole number.');
        values.saved_place_id = placeIdRaw ? Number(placeIdRaw) : null;
        
        const existingAccount = this.findAccount(form.dataset.id);
        const metadata = Object.assign({}, (existingAccount && existingAccount.metadata) || {});
        const launchOpts = Object.assign({}, metadata.launch_options || {}, {
          max_fps: Number(values.max_fps || 0),
          potato_graphics: new FormData(form).get('potato_graphics') === 'on'
        });
        metadata.launch_options = launchOpts;
        values.metadata = metadata;

        if (form.dataset.id) {
          await this.bridge.call('update_account', form.dataset.id, values);
          const watcherForm = new FormData(form);
          const existingRule = Object.assign({}, (existingAccount && existingAccount.metadata && existingAccount.metadata.watcher) || {}, (existingAccount && existingAccount.watcher) || {});
          const rawAttempts = values.watcher_relaunch_max_attempts;
          const watcherRule = {
            enabled: watcherForm.get('watcher_enabled') === 'on',
            auto_relaunch: watcherForm.get('watcher_auto_relaunch') === 'on',
            relaunch_delay_seconds: Number(values.watcher_relaunch_delay_seconds || existingRule.relaunch_delay_seconds || 15),
            relaunch_max_attempts: Number(rawAttempts === undefined || rawAttempts === '' ? (existingRule.relaunch_max_attempts === undefined ? 2 : existingRule.relaunch_max_attempts) : rawAttempts),
            relaunch_on_crash: existingRule.relaunch_on_crash === undefined ? true : Boolean(existingRule.relaunch_on_crash),
            relaunch_on_exit: watcherForm.get('watcher_relaunch_on_exit') === 'on'
          };
          if (!Number.isFinite(watcherRule.relaunch_delay_seconds) || watcherRule.relaunch_delay_seconds < 1 || watcherRule.relaunch_delay_seconds > 3600) throw new Error('The relaunch delay must be between 1 and 3600 seconds.');
          if (!Number.isInteger(watcherRule.relaunch_max_attempts) || watcherRule.relaunch_max_attempts < 0 || watcherRule.relaunch_max_attempts > 20) throw new Error('Maximum relaunch attempts must be between 0 and 20.');
          if (watcherRule.auto_relaunch && !(this.state.settings.watcher_enabled && this.state.settings.watcher_auto_relaunch_enabled)) await this.bridge.call('update_settings', { categories: { watcher: { enabled: true, auto_relaunch_enabled: true } } });
          const savedWatcherRule = await this.bridge.call('configure_account_watcher', form.dataset.id, watcherRule);
          if (watcherRule.auto_relaunch && savedWatcherRule && savedWatcherRule.effective && !savedWatcherRule.effective.armed) this.toast('warning', 'Watchdog saved but not armed', 'Astro stored the rule, but the relaunch stays inactive because ' + savedWatcherRule.effective.reason + '.');
        }
        else if (String(values.session || '').trim()) await this.bridge.call('add_account_from_cookie', String(values.session).trim(), values.group_id || null);
        else await this.bridge.call('create_account', values);
        await this.resync(); this.closeModal(); this.toast('success', form.dataset.id ? 'Account updated' : 'Account added', values.username + ' is ready in your workspace.'); this.render();
      } else if (form.dataset.form === 'oauth-settings') {
        if (this.state.mode !== 'desktop') throw new Error('Roblox OAuth can only be configured through the desktop bridge. Preview mode does not simulate sign-in.');
        const enabled = new FormData(form).get('enabled') === 'on';
        const clientId = String(values.client_id || '').trim();
        const redirectUri = String(values.redirect_uri || '').trim();
        const timeout = Number(values.callback_timeout_seconds);
        if (enabled && !/^\d+$/.test(clientId)) throw new Error('Enter the numeric Roblox OAuth client ID before enabling sign-in.');
        if (!redirectUri) throw new Error('Enter the loopback redirect URI registered with Roblox.');
        if (!Number.isInteger(timeout) || timeout < 60 || timeout > 900) throw new Error('The browser callback timeout must be between 60 and 900 seconds.');
        await this.bridge.call('update_settings', { categories: { oauth: { enabled: enabled, client_id: clientId, redirect_uri: redirectUri, callback_timeout_seconds: timeout } } });
        await this.resync(); this.render(); this.toast('success', 'Roblox sign-in settings saved', enabled ? 'Official OAuth is ready to connect an account.' : 'Official OAuth remains disabled for this workspace.');
      } else if (form.dataset.form === 'oauth-disconnect') {
        if (values.confirm !== 'on') throw new Error('Confirm the local OAuth disconnect before continuing.');
        const account = this.findAccount(form.dataset.id) || (this.state.modal && this.state.modal.account);
        if (!account || !account.id) throw new Error('The Roblox account to disconnect is no longer available.');
        await this.bridge.call('disconnect_oauth_account', account.id);
        await this.resync(); this.closeModal(); this.render(); this.toast('success', 'Roblox OAuth disconnected', (account.display_name || account.username) + ' remains as a local profile.');
      } else if (form.dataset.form === 'watcher-rule') {
        const account = this.findAccount(form.dataset.id) || (this.state.modal && this.state.modal.account);
        if (!account || !account.id) throw new Error('The account for this watcher rule is no longer available.');
        const rule = {
          enabled: new FormData(form).get('watcher_enabled') === 'on',
          auto_relaunch: new FormData(form).get('auto_relaunch') === 'on',
          relaunch_delay_seconds: Number(values.relaunch_delay_seconds),
          relaunch_max_attempts: Number(values.relaunch_max_attempts),
          relaunch_on_crash: new FormData(form).get('relaunch_on_crash') === 'on',
          relaunch_on_exit: new FormData(form).get('relaunch_on_exit') === 'on'
        };
        if (!Number.isFinite(rule.relaunch_delay_seconds) || rule.relaunch_delay_seconds < 1 || rule.relaunch_delay_seconds > 3600) throw new Error('The relaunch delay must be between 1 and 3600 seconds.');
        if (!Number.isInteger(rule.relaunch_max_attempts) || rule.relaunch_max_attempts < 0 || rule.relaunch_max_attempts > 20) throw new Error('Maximum relaunch attempts must be between 0 and 20.');
        await this.bridge.call('configure_account_watcher', account.id, rule);
        await this.resync(); this.closeModal(); this.render(); this.toast('success', 'Watcher rule saved', (account.display_name || account.username) + ' now has an explicit local watcher rule.');
      } else if (form.dataset.form === 'bind-instance') {
        if (values.confirm !== 'on') throw new Error('Confirm the instance association before continuing.');
        const instance = this.findInstance(form.dataset.pid) || (this.state.modal && this.state.modal.instance);
        const account = this.findAccount(values.account_id);
        const placeId = Number(values.place_id);
        if (!instance || !Number.isInteger(Number(instance.pid)) || Number(instance.pid) <= 0) throw new Error('The observed Roblox process is no longer available.');
        if (!account) throw new Error('Choose the local account to associate.');
        if (!Number.isInteger(placeId) || placeId <= 0) throw new Error('Enter a valid positive Roblox Place ID.');
        const target = { place_id: placeId };
        if (String(values.job_id || '').trim()) target.job_id = String(values.job_id).trim();
        await this.bridge.call('bind_instance', Number(instance.pid), account.id, target, true);
        await this.resync(); await this.loadInstanceMonitor(false); this.closeModal(); this.render(); this.toast('success', 'Instance associated', 'PID ' + instance.pid + ' is now associated with ' + (account.display_name || account.username) + '.');
      } else if (form.dataset.form === 'close-instance') {
        if (values.confirm !== 'on') throw new Error('Confirm the local process close before continuing.');
        const instance = this.findInstance(form.dataset.pid) || (this.state.modal && this.state.modal.instance);
        if (!instance || !Number.isInteger(Number(instance.pid)) || Number(instance.pid) <= 0) throw new Error('The observed Roblox process is no longer available.');
        const result = unwrap(await this.bridge.call('close_instance', Number(instance.pid), true)) || {};
        await this.resync(); await this.loadInstanceMonitor(false); this.closeModal(); this.render();
        this.toast(result.status === 'terminated' ? 'success' : 'info', result.status === 'terminated' ? 'Instance closed' : 'Instance close result', result.message || ('PID ' + instance.pid + ' returned status ' + (result.status || 'unknown') + '.'));
      } else if (form.dataset.form === 'group') {
        const editing = Boolean(form.dataset.id);
        if (editing) await this.bridge.call('update_group', form.dataset.id, values);
        else await this.bridge.call('create_group', values);
        await this.resync(); this.closeModal(); this.toast('success', editing ? 'Group updated' : 'Group created', values.name + (editing ? ' was updated.' : ' is ready for accounts.')); this.render();
      } else if (form.dataset.form === 'move') {
        await this.bridge.call('move_accounts', Array.from(this.state.selected), values.group_id || null); await this.resync(); this.state.selected.clear(); this.closeModal(); this.toast('success', 'Accounts moved', 'Your workspace was reorganized.'); this.render();
      } else if (form.dataset.form === 'bulk-edit') {
        const ids = Array.from(this.state.selected);
        if (!ids.length) throw new Error('No accounts selected.');
        const maxFpsVal = values.max_fps;
        const potatoVal = values.potato_graphics;
        const placeIdRaw = String(values.saved_place_id || '').trim();
        const groupIdVal = values.group_id;

        let count = 0;
        for (const id of ids) {
          const account = this.findAccount(id);
          if (!account) continue;
          const patch = {};
          if (groupIdVal !== 'keep') patch.group_id = groupIdVal || null;
          if (placeIdRaw !== 'keep') {
            if (placeIdRaw && (!/^[1-9][0-9]*$/.test(placeIdRaw) || Number(placeIdRaw) <= 0)) {
              throw new Error('Roblox Place ID must be a valid positive whole number or "keep".');
            }
            patch.saved_place_id = placeIdRaw ? Number(placeIdRaw) : null;
          }
          const metadata = Object.assign({}, account.metadata || {});
          const launchOpts = Object.assign({}, metadata.launch_options || {});
          let metaChanged = false;
          if (maxFpsVal !== 'keep') {
            launchOpts.max_fps = Number(maxFpsVal || 0);
            metaChanged = true;
          }
          if (potatoVal !== 'keep') {
            launchOpts.potato_graphics = potatoVal === 'true';
            metaChanged = true;
          }
          if (metaChanged) {
            metadata.launch_options = launchOpts;
            patch.metadata = metadata;
          }
          if (Object.keys(patch).length) {
            await this.bridge.call('update_account', id, patch);
            count++;
          }
        }
        await this.resync();
        this.closeModal();
        this.render();
        this.toast('success', 'Bulk Edit Applied', count + ' account(s) updated successfully.');
      } else if (form.dataset.form === 'remove-game') {
        if (values.confirm !== 'on') throw new Error('Confirm the local game removal before continuing.');
        const game = this.state.games.find(function (item) { return String(item.place_id) === String(form.dataset.id); });
        if (!game) throw new Error('The local game record is no longer available.');
        await this.bridge.call('remove_game', game.place_id);
        await this.resync();
        if (String(this.state.gameId) === String(game.place_id)) {
          this.state.gameId = this.state.games[0] ? String(this.state.games[0].place_id) : null;
          this.state.gameDetail = null;
          this.state.servers = [];
          if (this.state.gameId) await this.loadGame(this.state.gameId, false);
        }
        this.closeModal(); this.render(); this.toast('success', 'Local game removed', game.title + ' was removed from this workspace.');
      } else if (form.dataset.form === 'delete') {
        const ids = this.state.modal.ids; await this.bridge.call('delete_accounts', ids); await this.resync(); this.state.selected.clear(); this.closeModal(); this.toast('success', 'Accounts removed', ids.length + ' profile' + (ids.length === 1 ? ' was' : 's were') + ' removed.'); this.render();
      } else if (form.dataset.form === 'delete-group') {
        const group = this.state.modal.group;
        await this.bridge.call('delete_group', group.id); await this.resync(); this.closeModal(); this.toast('success', 'Group removed', group.name + ' was removed; its accounts are now ungrouped.'); this.render();
      } else if (form.dataset.form === 'migrate') {
        const result = unwrap(await this.bridge.call('migrate_legacy', values.path)) || {};
        await this.resync(); this.closeModal();
        const accountsImported = Number(result.accounts_imported || 0);
        const groupsImported = Number(result.groups_imported || 0);
        const gamesImported = Number(result.games_imported || 0);
        const warnings = asArray(result.warnings);
        const summary = accountsImported + ' accounts, ' + groupsImported + ' groups, and ' + gamesImported + ' games imported' + (warnings.length ? '; review the migration notes for ' + warnings.length + ' warning' + (warnings.length === 1 ? '.' : 's.') : '.');
        this.toast(warnings.length ? 'info' : 'success', warnings.length ? 'Migration completed with notes' : 'Migration completed', summary); this.render();
      } else if (form.dataset.form === 'restore-select') {
        const backup = (this.state.modal.backups || []).find(function (item) { return String(item.id) === String(values.backup_id); });
        if (!backup || !backup.verified) throw new Error('Select a verified backup to continue.');
        this.state.modal = { kind: 'restore-confirm', backup: backup };
        this.renderOverlays();
      } else if (form.dataset.form === 'restore-confirm') {
        if (values.confirm !== 'on') throw new Error('Explicit confirmation is required before restoring a backup.');
        const result = unwrap(await this.bridge.call('restore_backup', form.dataset.id, true)) || {};
        await this.resync(); this.closeModal(); this.render();
        this.toast('success', 'Backup restored', result.pre_restore_backup ? 'Your previous workspace was saved as a safety backup.' : 'Your workspace was restored.');
      } else if (form.dataset.form === 'import-metadata') {
        if (values.confirm !== 'on') throw new Error('Explicit confirmation is required before importing metadata.');
        const result = unwrap(await this.bridge.call('import_metadata', values.path, true)) || {};
        await this.resync(); this.closeModal(); this.render();
        const count = Number(result.accounts_imported || 0) + Number(result.groups_imported || 0) + Number(result.games_imported || 0);
        this.toast('success', 'Metadata imported', count + ' public record' + (count === 1 ? ' was' : 's were') + ' added; no secrets were imported.');
      }
    } catch (error) {
      if (errorTarget) { errorTarget.hidden = false; errorTarget.textContent = error.message || 'Something went wrong.'; }
      this.toast('error', 'Action failed', error.message);
    } finally {
      const submit = $('button[type="submit"]', form);
      if (submit) submit.disabled = false;
    }
  }

  handleInput(event) {
    const input = event.target;
    if (input.id === 'account-filter') { this.state.accountQuery = input.value; this.filterAccountRows(); return; }
    if (input.id === 'game-filter') { this.state.gameQuery = input.value; this.filterGameRows(); this.scheduleGameSearch(); return; }
    if (input.id === 'palette-input') { this.state.paletteQuery = input.value; this.renderOverlays(); const next = $('#palette-input'); if (next) { next.focus(); next.setSelectionRange(next.value.length, next.value.length); } }
    if (input.id === 'nexus-code-editor') { this.state.nexusExecutorCode = input.value; this.nexusSyncLineNumbers(); }
    if (input.id === 'macro-source') { this.state.macroDraftSource = input.value; return; }
    if (input.id === 'macro-draft-name') { this.state.macroDraftName = input.value; return; }
    if (input.id === 'macro-draft-description') { this.state.macroDraftDescription = input.value; return; }
    const macroBlock = input.closest && input.closest('.macro-block');
    if (macroBlock && input.dataset.blockField) {
      const index = Number(macroBlock.dataset.blockIndex);
      if (this.state.macroDraftBlocks[index]) this.state.macroDraftBlocks[index][input.dataset.blockField] = input.type === 'number' ? Number(input.value) : input.value;
    }
  }

  async handleChange(event) {
    const target = event.target;
    if (target.id === 'account-status') { this.state.accountStatus = target.value; this.render(); return; }
    if (target.id === 'nexus-exec-target') { this.state.nexusExecutorTarget = target.value; return; }
    if (target.id === 'macro-editor-mode') { this.state.macroEditorMode = target.value === 'dsl' ? 'dsl' : 'blocks'; this.render(); return; }
    if (target.id === 'macro-draft-account') { this.state.macroDraftAccountId = target.value; return; }
    if (target.id === 'server-sort' || target.id === 'server-min-slots' || target.id === 'server-avoid-previous') {
      this.state.serverFilters = {
        sort: target.id === 'server-sort' ? target.value : this.state.serverFilters.sort,
        min_free_slots: target.id === 'server-min-slots' ? Math.max(0, Math.min(100, Number(target.value) || 0)) : this.state.serverFilters.min_free_slots,
        avoid_previous: target.id === 'server-avoid-previous' ? Boolean(target.checked) : this.state.serverFilters.avoid_previous
      };
      await this.loadGame(this.state.gameId, false);
      return;
    }
    if (target.dataset.setting) {
      const value = target.type === 'checkbox' ? target.checked : target.value;
      if (target.dataset.setting === 'allow_multiple_launches') {
        await this.setMultiInstance(Boolean(value));
        return;
      }
      await this.updateSettings({ [target.dataset.setting]: value }, false);
    }
  }

  handleKeydown(event) {
    const modifier = event.ctrlKey || event.metaKey;
    /* Nexus code editor: Tab inserts spaces, Ctrl+Enter executes */
    if (event.target.id === 'nexus-code-editor') {
      if (event.key === 'Tab') {
        event.preventDefault();
        const ta = event.target;
        const start = ta.selectionStart;
        const end = ta.selectionEnd;
        ta.value = ta.value.substring(0, start) + '  ' + ta.value.substring(end);
        ta.selectionStart = ta.selectionEnd = start + 2;
        this.state.nexusExecutorCode = ta.value;
        this.nexusSyncLineNumbers();
        return;
      }
      if (modifier && event.key === 'Enter') { event.preventDefault(); this.nexusExecute(); return; }
    }
    if (modifier && event.key.toLowerCase() === 'k') { event.preventDefault(); this.openPalette(); return; }
    if (modifier && event.key.toLowerCase() === 'f') { event.preventDefault(); this.openPalette(); return; }
    if (modifier && event.key.toLowerCase() === 'r') { event.preventDefault(); this.refreshInstances(); return; }
    if (event.key === 'Escape') { if (this.state.paletteOpen) this.closePalette(); else if (this.state.modal) void this.dismissOAuthModal(); else if (this.state.notificationsOpen) { this.state.notificationsOpen = false; this.renderOverlays(); } }
  }

  handleDragStart(event) {
    const card = event.target.closest('[data-account-id]');
    if (!card) return;
    const id = card.dataset.accountId;
    this.state.draggedAccountId = id;
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', id);
    }
    card.classList.add('is-dragging');
    window.setTimeout(function () { card.classList.remove('is-dragging'); }, 250);
  }

  clearAccountDragTargets() {
    $$('.group-section.is-drop-target, .account-card.is-reorder-target').forEach(function (element) { element.classList.remove('is-drop-target', 'is-reorder-target'); });
  }

  handleDragEnd() {
    this.state.draggedAccountId = null;
    this.clearAccountDragTargets();
  }

  handleDragOver(event) {
    const draggedId = this.state.draggedAccountId || event.dataTransfer && event.dataTransfer.getData('text/plain');
    const source = this.findAccount(draggedId);
    const card = event.target.closest('[data-account-id]');
    const targetAccount = card && this.findAccount(card.dataset.accountId);
    if (source && targetAccount && source.id !== targetAccount.id && String(source.group_id || '') === String(targetAccount.group_id || '')) {
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
      this.clearAccountDragTargets();
      card.classList.add('is-reorder-target');
      return;
    }
    const target = event.target.closest('[data-group-target]');
    if (!target) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
    this.clearAccountDragTargets();
    target.classList.add('is-drop-target');
  }

  async reorderAccountDrop(draggedId, targetId) {
    const previous = this.state.accounts.slice();
    const sourceIndex = previous.findIndex(function (account) { return String(account.id) === String(draggedId); });
    const targetIndex = previous.findIndex(function (account) { return String(account.id) === String(targetId); });
    if (sourceIndex < 0 || targetIndex < 0 || sourceIndex === targetIndex) return;
    const next = previous.slice();
    const moved = next.splice(sourceIndex, 1)[0];
    const destination = next.findIndex(function (account) { return String(account.id) === String(targetId); });
    next.splice(destination, 0, moved);
    const order = next.map(function (account) { return account.id; });
    this.state.accounts = next;
    this.render();
    try {
      const saved = asArray(await this.bridge.call('reorder_accounts', order));
      if (saved.length === order.length) this.state.accounts = saved;
      await this.resync(); this.render();
      this.toast('success', 'Account order saved', 'The local account order was updated.');
    } catch (error) {
      this.state.accounts = previous;
      this.render();
      this.toast('error', 'Could not save account order', error.message || 'The previous account order was restored.');
    }
  }

  async handleDrop(event) {
    const card = event.target.closest('[data-account-id]');
    const target = event.target.closest('[data-group-target]');
    if (!card && !target) return;
    event.preventDefault();
    this.clearAccountDragTargets();
    const id = this.state.draggedAccountId || event.dataTransfer && event.dataTransfer.getData('text/plain');
    this.state.draggedAccountId = null;
    if (!id) return;
    const source = this.findAccount(id);
    const targetAccount = card && this.findAccount(card.dataset.accountId);
    if (source && targetAccount && source.id !== targetAccount.id && String(source.group_id || '') === String(targetAccount.group_id || '')) {
      await this.reorderAccountDrop(source.id, targetAccount.id);
      return;
    }
    if (!target) return;
    const ids = this.state.selected.has(id) ? Array.from(this.state.selected) : [id];
    try {
      await this.bridge.call('move_accounts', ids, target.dataset.groupTarget || null);
      await this.resync(); this.state.selected.clear(); this.render(); this.toast('success', 'Accounts moved', ids.length + ' account' + (ids.length === 1 ? '' : 's') + ' reorganized.');
    } catch (error) { this.toast('error', 'Could not move accounts', error.message); }
  }

  filterAccountRows() {
    const phrase = this.state.accountQuery.trim().toLowerCase();
    $$('.account-card, .data-table tbody tr').forEach(function (element) {
      const id = element.dataset.accountId || (element.querySelector('[data-id]') || {}).dataset && (element.querySelector('[data-id]') || {}).dataset.id;
      const account = this.findAccount(id);
      if (!account) return;
      const visible = !phrase || [account.username, account.display_name, account.notes].join(' ').toLowerCase().includes(phrase);
      element.hidden = !visible;
    }.bind(this));
  }

  scheduleGameSearch() {
    if (this.gameSearchTimer) window.clearTimeout(this.gameSearchTimer);
    const phrase = this.state.gameQuery;
    this.gameSearchTimer = window.setTimeout(function () { void this.searchGames(phrase); }.bind(this), 350);
  }

  restoreGameFilterFocus() {
    const input = $('#game-filter');
    if (!input) return;
    input.focus();
    const end = input.value.length;
    try { input.setSelectionRange(end, end); } catch (error) { /* search inputs may refuse a caret */ }
  }

  async searchGames(phrase) {
    const query = String(phrase === undefined ? this.state.gameQuery : phrase).trim();
    // A slower response for an abandoned phrase must never replace the list.
    if (String(this.state.gameQuery).trim() !== query) return;
    this.state.gamesLoading = true;
    if (this.state.route === 'games') { this.render(); this.restoreGameFilterFocus(); }
    try {
      const rows = asArray(await this.bridge.call('search_games', query, 20));
      if (String(this.state.gameQuery).trim() !== query) return;
      this.state.games = rows;
      this.state.gamesLoading = false;
      if (this.state.route === 'games') { this.render(); this.restoreGameFilterFocus(); }
    } catch (error) {
      if (String(this.state.gameQuery).trim() !== query) return;
      this.state.gamesLoading = false;
      if (this.state.route === 'games') { this.render(); this.restoreGameFilterFocus(); }
      this.toast('error', 'Could not search games', error.message);
    }
  }

  async loadGames() {
    try {
      const rows = asArray(await this.bridge.call('list_games'));
      this.state.games = rows;
      if (this.state.route === 'games') this.render();
    } catch (error) {
      // Keep whatever the bootstrap already provided.
    }
  }

  filterGameRows() {
    const phrase = this.state.gameQuery.trim().toLowerCase();
    $$('.game-card').forEach(function (element) {
      const game = this.state.games.find(function (item) { return String(item.place_id) === String(element.dataset.id); });
      if (!game) return;
      element.hidden = Boolean(phrase && ![game.title, game.creator, game.category].join(' ').toLowerCase().includes(phrase));
    }.bind(this));
  }

  navigate(route) {
    if (route === 'nexus' && !this.nexusEnabled()) route = 'dashboard';
    this.state.route = route;
    this.state.notificationsOpen = false;
    this.state.selected.clear();
    this.render();
    if (route === 'instances') void this.loadInstanceMonitor(false);
    if (route === 'fleet') void this.loadFleet(this.state.fleetTab);
    if (route === 'games') {
      // The page used to render an empty list forever: nothing ever asked the
      // backend for the saved games, and the search box only filtered that
      // empty array locally.
      if (String(this.state.gameQuery).trim()) void this.searchGames(this.state.gameQuery);
      else void this.loadGames();
      if (this.state.gameId && !this.state.gameDetail) void this.loadGame(this.state.gameId, false);
    }
    if (route === 'settings' && this.state.settingsTab === 'general') void this.loadWindowsStartupStatus(false);
    if (route === 'settings' && this.state.settingsTab === 'roblox') void this.loadRobloxSettings(false);
  }

  openModal(value) { if (value && value.kind === 'send-nexus' && !this.nexusEnabled()) return; this.state.modal = value; this.renderOverlays(); window.setTimeout(function () { const autofocus = $('[autofocus], .modal input'); if (autofocus) autofocus.focus(); }, 10); }
  clearOAuthPolling() {
    if (this.oauthPollTimer !== null) window.clearInterval(this.oauthPollTimer);
    this.oauthPollTimer = null;
  }

  isOAuthWaiting(operation) {
    return Boolean(operation && operation.operation_id && operation.status === 'waiting' && !operation.cancellation_requested);
  }

  closeModal() { this.clearOAuthPolling(); this.state.modal = null; this.renderOverlays(); }

  async startOAuthLogin() {
    if (!this.isOAuthConfigured()) {
      this.state.settingsTab = 'oauth';
      this.navigate('settings');
      this.toast('info', 'Configure Roblox sign-in first', this.state.mode === 'desktop' ? 'Add a registered client ID and loopback callback before starting OAuth.' : 'Preview mode never simulates Roblox sign-in.');
      return;
    }
    this.clearOAuthPolling();
    try {
      const operation = unwrap(await this.bridge.call('start_oauth_login')) || {};
      if (!operation.operation_id || typeof operation.operation_id !== 'string') throw new Error('The desktop bridge did not return a valid OAuth operation.');
      this.openModal({ kind: 'oauth-login', operation: operation });
      if (operation.status === 'waiting') this.beginOAuthPolling(operation.operation_id);
    } catch (error) {
      this.toast('error', 'Could not start Roblox sign-in', error.message || 'The official OAuth flow could not be started.');
    }
  }

  beginOAuthPolling(operationId) {
    this.clearOAuthPolling();
    void this.pollOAuthLogin(operationId);
    this.oauthPollTimer = window.setInterval(function () { void this.pollOAuthLogin(operationId); }.bind(this), 1500);
  }

  async pollOAuthLogin(operationId) {
    const initial = this.state.modal;
    if (!initial || initial.kind !== 'oauth-login' || !this.isOAuthWaiting(initial.operation) || initial.operation.operation_id !== operationId || this.oauthPollInFlight) return;
    this.oauthPollInFlight = true;
    try {
      const operation = unwrap(await this.bridge.call('poll_oauth_login', operationId)) || {};
      const current = this.state.modal;
      if (!current || current.kind !== 'oauth-login' || !current.operation || current.operation.operation_id !== operationId || current.operation.cancellation_requested) return;
      current.operation = Object.assign({}, current.operation, operation, { operation_id: operationId });
      if (current.operation.status === 'completed') {
        this.clearOAuthPolling();
        let refreshError = null;
        try { await this.resync(); } catch (error) { refreshError = error; }
        const account = current.operation.account || {};
        this.closeModal();
        this.render();
        const name = account.display_name || account.username || 'The Roblox account';
        this.toast(refreshError ? 'info' : 'success', refreshError ? 'Roblox account connected' : 'Roblox account connected', refreshError ? name + ' was linked, but refresh the workspace to show the latest account card.' : name + ' is now linked through official Open Cloud OAuth.');
        return;
      }
      if (current.operation.status !== 'waiting') this.clearOAuthPolling();
      this.renderOverlays();
    } catch (error) {
      const current = this.state.modal;
      if (current && current.kind === 'oauth-login' && current.operation && current.operation.operation_id === operationId && !current.operation.cancellation_requested) {
        this.clearOAuthPolling();
        current.operation = Object.assign({}, current.operation, { status: 'failed', message: error.message || 'The desktop bridge could not check Roblox OAuth.' });
        this.renderOverlays();
      }
    } finally {
      this.oauthPollInFlight = false;
    }
  }

  async cancelOAuthLogin(silent) {
    const modal = this.state.modal;
    if (!modal || modal.kind !== 'oauth-login' || !modal.operation || !modal.operation.operation_id) { this.closeModal(); return; }
    if (!this.isOAuthWaiting(modal.operation)) { this.closeModal(); return; }
    const operationId = modal.operation.operation_id;
    this.clearOAuthPolling();
    modal.operation = Object.assign({}, modal.operation, { cancellation_requested: true });
    this.renderOverlays();
    try {
      const operation = unwrap(await this.bridge.call('cancel_oauth_login', operationId)) || {};
      if (operation.status === 'completed') {
        let refreshError = null;
        try { await this.resync(); } catch (error) { refreshError = error; }
        const account = operation.account || {};
        this.closeModal();
        this.render();
        this.toast(refreshError ? 'info' : 'success', 'Roblox account connected', refreshError ? 'The authorization completed before cancellation, but the workspace could not refresh automatically.' : (account.display_name || account.username || 'The Roblox account') + ' completed authorization before cancellation.');
        return;
      }
      this.closeModal();
      if (!silent) this.toast('info', 'Roblox authorization cancelled', 'No OAuth grant was added to this workspace.');
    } catch (error) {
      const current = this.state.modal;
      if (current && current.kind === 'oauth-login' && current.operation && current.operation.operation_id === operationId) {
        current.operation = Object.assign({}, current.operation, { cancellation_requested: false, status: 'waiting', message: error.message || 'The desktop bridge could not cancel Roblox OAuth.' });
        this.renderOverlays();
        this.beginOAuthPolling(operationId);
      }
      if (!silent) this.toast('error', 'Could not cancel Roblox sign-in', error.message || 'The authorization may still be waiting in the system browser.');
    }
  }

  async dismissOAuthModal() {
    const modal = this.state.modal;
    if (modal && modal.kind === 'oauth-login' && this.isOAuthWaiting(modal.operation)) { await this.cancelOAuthLogin(true); return; }
    this.closeModal();
  }

  async refreshOAuthAccount(id) {
    const account = this.findAccount(id);
    if (!account || !account.oauth_connected) return;
    if (!this.isOAuthConfigured()) {
      this.state.settingsTab = 'oauth';
      this.navigate('settings');
      this.toast('info', 'Configure Roblox sign-in first', 'Reconnecting an Open Cloud grant requires the registered desktop OAuth configuration.');
      return;
    }
    try {
      const refreshed = unwrap(await this.bridge.call('refresh_oauth_account', account.id)) || account;
      await this.resync();
      this.render();
      this.toast('success', 'Roblox OAuth refreshed', (refreshed.display_name || refreshed.username || account.username) + ' was refreshed through the desktop bridge.');
    } catch (error) {
      this.toast('error', 'Could not refresh Roblox OAuth', error.message || 'The local OAuth grant could not be refreshed.');
    }
  }

  setPublicRefreshError(accountId, kind, message) {
    const all = Object.assign({}, this.state.publicRefreshErrors || {});
    const entry = Object.assign({}, all[accountId] || {});
    if (message) entry[kind] = String(message);
    else delete entry[kind];
    if (Object.keys(entry).length) all[accountId] = entry;
    else delete all[accountId];
    this.state.publicRefreshErrors = all;
  }

  async refreshPublicProfile(id) {
    const account = this.findAccount(id);
    if (!account || !this.publicUserId(account)) return;
    if (this.state.mode !== 'desktop') {
      const message = 'Preview mode never simulates public Roblox profile data.';
      this.setPublicRefreshError(account.id, 'profile', message); this.render();
      this.toast('info', 'Public Roblox profile unavailable', message);
      return;
    }
    try {
      const result = unwrap(await this.bridge.call('refresh_account_public_profile', account.id)) || {};
      await this.resync(); this.setPublicRefreshError(account.id, 'profile', ''); this.render();
      const profile = result.profile || {};
      this.toast('success', 'Public Roblox profile refreshed', (profile.display_name || profile.username || account.username) + ' was refreshed from public Roblox data.');
    } catch (error) {
      const message = error.message || 'The public profile could not be retrieved.';
      this.setPublicRefreshError(account.id, 'profile', message); this.render();
      this.toast('error', 'Could not refresh public Roblox profile', message);
    }
  }

  async refreshPublicPresence(id) {
    const account = this.findAccount(id);
    if (!account || !this.publicUserId(account)) return;
    if (this.state.mode !== 'desktop') {
      const message = 'Preview mode never simulates public Roblox presence data.';
      this.setPublicRefreshError(account.id, 'presence', message); this.render();
      this.toast('info', 'Public Roblox presence unavailable', message);
      return;
    }
    try {
      const rows = asArray(await this.bridge.call('refresh_account_presence', [account.id]));
      await this.resync(); this.setPublicRefreshError(account.id, 'presence', ''); this.render();
      const presence = rows[0] && rows[0].presence;
      const label = this.publicPresenceLabel(presence);
      this.toast('success', 'Public Roblox presence refreshed', (account.display_name || account.username) + ' is reported as ' + label + '. This does not change local process monitoring.');
    } catch (error) {
      const message = error.message || 'The public presence snapshot could not be retrieved.';
      this.setPublicRefreshError(account.id, 'presence', message); this.render();
      this.toast('error', 'Could not refresh public Roblox presence', message);
    }
  }

  async openRestoreModal() {
    try {
      const backups = asArray(await this.bridge.call('list_backups')).filter(function (backup) { return backup.verified; });
      this.openModal({ kind: 'restore', backups: backups });
    } catch (error) {
      this.toast('error', 'Could not load backups', error.message);
    }
  }
  openPalette() { this.state.paletteOpen = true; this.state.notificationsOpen = false; this.renderOverlays(); window.setTimeout(function () { const input = $('#palette-input'); if (input) input.focus(); }, 10); }
  closePalette() { this.state.paletteOpen = false; this.state.paletteQuery = ''; this.renderOverlays(); }
  findAccount(id) { return this.state.accounts.find(function (account) { return String(account.id) === String(id); }) || null; }
  findInstance(pid) { return this.state.instances.find(function (instance) { return String(instance.pid) === String(pid); }) || null; }

  toggleSelection(id) {
    if (!id) return;
    if (this.state.selected.has(id)) this.state.selected.delete(id); else this.state.selected.add(id);
    this.render();
  }

  async updateSettings(values, announce) {
    try {
      const bridgeValues = Object.assign({}, values);
      if (bridgeValues.accent && ACCENT_HEX[bridgeValues.accent]) bridgeValues.accent = ACCENT_HEX[bridgeValues.accent];
      const output = unwrap(await this.bridge.call('update_settings', bridgeValues));
      const next = Object.assign({}, this.state.settings, output || values);
       if (values.accent) { next.accent = values.accent; next.accent_raw = bridgeValues.accent; }
       else { next.accent_raw = next.accent; next.accent = accentToken(next.accent); }
       this.state.settings = next;
       if (Object.prototype.hasOwnProperty.call(values, 'privacy_mode')) this.state.hideUsernames = Boolean(values.privacy_mode);
       if (Object.prototype.hasOwnProperty.call(values, 'watcher_termination_enabled')) {
         this.state.instanceMonitor = Object.assign({}, this.state.instanceMonitor, { termination_enabled: Boolean(values.watcher_termination_enabled) });
       }
       this.applyTheme(); this.render();
      if (announce !== false) this.toast('success', 'Settings saved', 'Your preference was applied.');
      return true;
    } catch (error) {
      this.toast('error', 'Could not save settings', error.message);
      return false;
    }
  }

  async setMultiInstance(enabled) {
    try {
      const status = unwrap(await this.bridge.call('set_multi_instance', Boolean(enabled))) || {};
      this.state.multiInstance = Object.assign({}, this.state.multiInstance, status);
      this.state.settings.allow_multiple_launches = Boolean(status.configured);
      const categories = this.state.settings.categories || (this.state.settings.categories = {});
      const instances = categories.instances || (categories.instances = {});
      instances.allow_multiple_launches = Boolean(status.configured);
      this.render();
      if (status.enabled) {
        this.toast('success', 'Multi Roblox active', 'Astro owns the Roblox singleton mutex. You can now launch several accounts.');
      } else if (status.restart_required) {
        this.toast('info', 'Multi Roblox saved', 'Close Roblox, restart Astro, then launch your accounts from Astro.');
      } else {
        this.toast('success', 'Multi Roblox disabled', 'Future Roblox launches will use the normal single-instance behavior.');
      }
    } catch (error) {
      this.render();
      this.toast('error', 'Could not change Multi Roblox', error.message);
    }
  }

  async launch(id, target) {
    const account = this.findAccount(id);
    if (!account || this.state.launchingAccounts.has(String(id))) return;
    const accountDefault = account.saved_place_id ? { place_id: String(account.saved_place_id) } : null;
    const launchTarget = target || accountDefault || (this.state.gameId ? { place_id: this.state.gameId } : null);
    const previousStatus = account.status;
    this.state.launchingAccounts.add(String(id));
    account.status = 'launching';
    this.render();
    try {
      const result = unwrap(await this.bridge.call('launch_account', id, launchTarget)) || {};
      if (result.accepted === false) throw new Error('Windows did not accept the Roblox launch request.');
      await this.refreshLaunchState();
      this.toast('success', 'Launch requested', (account.display_name || account.username) + ' is being opened in Place ' + String(result.target && result.target.place_id || launchTarget && launchTarget.place_id || '') + '.');
    } catch (error) {
      account.status = previousStatus;
      try { await this.refreshLaunchState(); } catch (_) { this.render(); }
      this.toast('error', 'Could not launch account', error.message);
    } finally {
      this.state.launchingAccounts.delete(String(id));
      this.render();
    }
  }

  async bulkLaunch() {
    const ids = Array.from(this.state.selected);
    if (!ids.length) return;
    const missingDefaults = ids.map(this.findAccount.bind(this)).filter(function (account) { return !account || !account.saved_place_id; });
    if (missingDefaults.length) {
      this.toast('error', 'Default Place ID required', missingDefaults.length + ' selected account' + (missingDefaults.length === 1 ? ' has' : 's have') + ' no default Place ID. Edit each account before bulk launching.');
      return;
    }
    try {
      const delayMs = Number((((this.state.settings || {}).categories || {}).general || {}).launch_delay_ms || 2500);
      await this.bridge.call('start_batch_launch', ids, null, Math.max(0.5, delayMs / 1000));
      this.state.selected.clear(); this.render(); this.toast('success', 'Launches queued', ids.length + ' account launches are queued with the configured delay.');
      this.trackBatchLaunch();
    } catch (error) { this.toast('error', 'Could not launch selected accounts', error.message); }
  }

  async refreshLaunchState() {
    this.applyInstanceMonitor(unwrap(await this.bridge.call('get_instance_monitor')) || {});
    this.render();
  }

  startRuntimePolling() {
    if (this.state.mode !== 'desktop' || this.state.runtimePollTimer) return;
    this.state.runtimePollTimer = window.setInterval(function () { void this.refreshRuntimeSilently(); }.bind(this), 3000);
  }

  async refreshRuntimeSilently() {
    if (this.state.runtimePollInFlight || this.state.loading || this.state.modal || this.state.paletteOpen || this.state.draggedAccountId) return;
    if (typeof document.visibilityState === 'string' && document.visibilityState === 'hidden') return;
    this.state.runtimePollInFlight = true;
    try {
      if (this.state.route === 'dashboard') {
        // One joined snapshot instead of three polls that could disagree.
        this.applyDashboard(unwrap(await this.bridge.call('get_dashboard')) || {});
      } else {
        if (this.state.route === 'macros') {
          const runtimePayloads = await Promise.all([this.bridge.call('get_instance_monitor'), this.bridge.call('list_macro_runs')]);
          this.applyInstanceMonitor(unwrap(runtimePayloads[0]) || {});
          this.state.macroRuns = asArray(runtimePayloads[1]);
        } else {
          this.applyInstanceMonitor(unwrap(await this.bridge.call('get_instance_monitor')) || {});
        }
      }
      if (['dashboard', 'accounts', 'instances', 'macros'].includes(this.state.route)) this.render();
    } catch (_) {
      // Explicit refreshes keep their visible error; background polling stays quiet.
    } finally {
      this.state.runtimePollInFlight = false;
    }
  }

  async refreshAccountsState() {
    this.state.accounts = asArray(await this.bridge.call('list_accounts'));
    this.render();
  }

  async trackBatchLaunch() {
    if (this.state.batchPollTimer) window.clearTimeout(this.state.batchPollTimer);
    try {
      const status = unwrap(await this.bridge.call('get_batch_launch_status')) || {};
      if (status.in_progress) {
        this.state.batchPollTimer = window.setTimeout(function () { void this.trackBatchLaunch(); }.bind(this), 500);
        return;
      }
      this.state.batchPollTimer = null;
      await this.refreshLaunchState();
      const failed = Number(status.failed || 0);
      this.toast(failed ? 'error' : 'success', 'Batch launch finished', Number(status.launched || 0) + ' launched, ' + failed + ' failed.');
    } catch (error) {
      this.state.batchPollTimer = null;
      this.toast('error', 'Could not refresh batch launch', error.message);
    }
  }

  async toggleFavorite(id) {
    const account = this.findAccount(id);
    if (!account) return;
    try {
      await this.bridge.call('update_account', id, { favorite: !account.favorite });
      await this.resync(); this.render(); this.toast('success', account.favorite ? 'Favorite removed' : 'Added to favorites', account.username + ' was updated.');
    } catch (error) { this.toast('error', 'Could not update favorite', error.message); }
  }

  async toggleGameFavorite(placeId) {
    const game = this.state.games.find(function (item) { return String(item.place_id) === String(placeId); });
    if (!game) return;
    try {
      const saved = unwrap(await this.bridge.call('set_game_favorite', game.place_id, !game.favorite)) || {};
      await this.resync();
      if (this.state.gameDetail && String(this.state.gameDetail.place_id) === String(game.place_id)) this.state.gameDetail = Object.assign({}, this.state.gameDetail, saved);
      this.render();
      this.toast('success', saved.favorite ? 'Game added to favorites' : 'Game removed from favorites', game.title + ' was updated in this local workspace.');
    } catch (error) { this.toast('error', 'Could not update game favorite', error.message); }
  }

  async loadGame(id, announce) {
    if (!id) return;
    const targetId = String(id);
    this.state.gameId = targetId;
    this.state.serversLoading = true;
    if (this.state.route === 'games') this.render();
    try {
      const result = await Promise.all([this.bridge.call('get_game', targetId), this.bridge.call('list_servers', targetId, this.state.serverFilters)]);
      // Discard stale response if user selected a different game while loading
      if (String(this.state.gameId) !== targetId) return;
      this.state.gameDetail = unwrap(result[0]);
      this.state.servers = asArray(result[1]);
      this.state.serversLoading = false;
      if (this.state.route === 'games') this.render();
      if (announce) this.toast('success', 'Server list updated', this.state.servers.length + ' servers found.');
    } catch (error) {
      if (String(this.state.gameId) !== targetId) return;
      this.state.serversLoading = false;
      if (this.state.route === 'games') this.render();
      this.toast('error', 'Could not load servers', error.message);
    }
  }

  async joinServer(id) {
    const server = this.state.servers.find(function (item) { return String(item.id) === String(id); });
    if (!server) return;
    const available = this.state.accounts.filter(function (item) { return item.has_session && !['in_game', 'running', 'launching'].includes(item.status); });
    if (!available.length) { this.toast('error', 'No available signed-in account', 'Add a session or wait for an active account to become ready.'); return; }
    this.openModal({ kind: 'server-launch', server: server });
  }

  async refreshInstances() {
    try {
      await this.bridge.call('refresh_instances');
      const monitor = unwrap(await this.bridge.call('get_instance_monitor')) || {};
      this.applyInstanceMonitor(monitor);
      this.render();
      const scan = monitor.last_scan_complete === false ? ' The scan was partial.' : '';
      this.toast('success', 'Instances refreshed', this.state.instances.length + ' observed process' + (this.state.instances.length === 1 ? '.' : 'es.') + scan);
    } catch (error) { this.toast('error', 'Could not refresh instances', error.message); }
  }

  async refreshDiagnostics() {
    try {
      this.state.diagnostics = unwrap(await this.bridge.call('get_diagnostics')) || this.state.diagnostics;
      this.render(); this.toast('success', 'Diagnostics updated', 'Service health is current.');
    } catch (error) { this.toast('error', 'Could not refresh diagnostics', error.message); }
  }

  async backup() {
    try {
      const result = unwrap(await this.bridge.call('backup_data')) || {};
      await this.resync(); this.render(); this.toast('success', 'Backup completed', result.path ? 'Saved to ' + result.path : 'Your workspace data was backed up.');
    } catch (error) { this.toast('error', 'Could not create backup', error.message); }
  }

  async exportMetadata() {
    try {
      const result = unwrap(await this.bridge.call('export_metadata')) || {};
      const filename = result.filename || 'Metadata export';
      const destination = result.path || 'Astro Account Manager exports folder';
      this.toast('success', 'Metadata exported', filename + ' · ' + destination);
    } catch (error) { this.toast('error', 'Could not export metadata', error.message); }
  }

  async dismissNotification(id) {
    try {
      await this.bridge.call('dismiss_notification', id);
      this.state.notifications = this.state.notifications.filter(function (item) { return String(item.id) !== String(id); });
      this.render();
    } catch (error) { this.toast('error', 'Could not dismiss notification', error.message); }
  }

  async writeClipboard(value) {
    if (!navigator.clipboard || typeof navigator.clipboard.writeText !== 'function') {
      throw new Error('Clipboard access is unavailable.');
    }
    await navigator.clipboard.writeText(String(value));
  }

  async copyText(value, label) {
    try {
      await this.writeClipboard(value);
      this.toast('success', String(label || 'Value') + ' copied', 'Copied to the clipboard.');
      return true;
    } catch (_) {
      this.toast('error', 'Clipboard unavailable', 'Copy the value manually.');
      return false;
    }
  }

  async executePalette(data) {
    this.closePalette();
    if (data.kind === 'route') { this.navigate(data.route); return; }
    if (data.kind === 'action') {
      if (data.nextAction === 'create-account') this.openModal({ kind: 'account', account: {} });
      else if (data.nextAction === 'create-group') this.openModal({ kind: 'group' });
      else if (data.nextAction === 'refresh-instances') await this.refreshInstances();
      return;
    }
    if (data.kind === 'account') { this.navigate('accounts'); window.setTimeout(function () { this.openModal({ kind: 'account', account: this.findAccount(data.id) }); }.bind(this), 20); return; }
    if (data.kind === 'game') { this.navigate('games'); await this.loadGame(data.id, false); }
  }

  toast(kind, title, body) {
    const toast = document.createElement('article');
    toast.className = 'toast ' + (kind || '');
    const symbol = kind === 'error' ? 'alert' : kind === 'success' ? 'check' : 'info';
    toast.innerHTML = '<span class="toast-icon">' + icon(symbol) + '</span><div class="toast-copy"><strong>' + escapeHtml(title) + '</strong><p>' + escapeHtml(body || '') + '</p></div><button class="icon-button" type="button" aria-label="Dismiss">' + icon('x') + '</button>';
    const close = function () { if (toast.parentNode) toast.remove(); };
    $('button', toast).addEventListener('click', close);
    this.toastRoot.appendChild(toast);
    window.setTimeout(close, 5000);
  }
}

const app = new OrbitApp();
app.init();
