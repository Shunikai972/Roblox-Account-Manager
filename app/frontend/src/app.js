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
  return { ready: 'Ready', in_game: 'In game', running: 'Running', starting: 'Launching', launching: 'Launching', offline: 'Offline', orphaned: 'Unassociated', unknown: 'Unknown', terminating: 'Closing', exited: 'Exited', crashed: 'Crashed', terminated: 'Closed', healthy: 'Healthy', degraded: 'Limited', error: 'Issue' }[value] || String(value || 'Unknown');
}

function icon(name, title) {
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
  return open + (paths[name] || paths.info) + '</svg>';
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
      instanceMonitor: { instances: [], events: [], pending_restarts: [], last_scan_complete: null, termination_enabled: false },
      windowsStartup: { loaded: false, error: false, available: false, supported: null, accessible: null, registered: false, enabled: false, needs_repair: false, configured: false, reason: '' },
      accountView: 'cards', accountQuery: '', accountStatus: 'all', selected: new Set(),
      publicRefreshErrors: {}, draggedAccountId: null,
      gameQuery: '', gameId: null, gameDetail: null, servers: [], serversLoading: false,
      settingsTab: 'general', modal: null, notificationsOpen: false, paletteOpen: false, paletteQuery: '',
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
      if (this.state.gameId) this.loadGame(this.state.gameId, false);
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
    this.state.instanceMonitor = {
      instances: this.state.instances,
      events: [],
      pending_restarts: [],
      last_scan_complete: null,
      termination_enabled: Boolean(settings.watcher_termination_enabled)
    };
    this.state.diagnostics = unwrap(boot.diagnostics) || this.state.diagnostics;
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
    const userId = this.publicUserId(account);
    if (!userId) return compact ? '' : '';
    const data = this.publicAccountMetadata(account);
    const profile = data.profile;
    const presence = data.presence;
    const preview = this.state.mode !== 'desktop';
    const errors = (this.state.publicRefreshErrors || {})[account.id] || {};
    const identity = !preview && profile && (profile.display_name || profile.username) || account.display_name || account.username;
    const username = !preview && profile && profile.username || account.username;
    const profileState = preview ? 'Public profile unavailable in Preview' : profile ? (profile.refreshed_at ? 'Public profile · ' + relativeTime(profile.refreshed_at) : 'Public profile saved') : 'Public profile not refreshed';
    const verified = !preview && profile && profile.has_verified_badge ? '<span class="public-verified">' + icon('shield') + ' Verified</span>' : '';
    const presenceState = preview ? 'preview-unavailable' : String(presence && presence.state || 'not-refreshed').toLowerCase();
    const profileError = errors.profile ? '<p class="public-account-error">Profile: ' + escapeHtml(errors.profile) + '</p>' : '';
    const presenceError = errors.presence ? '<p class="public-account-error">Presence: ' + escapeHtml(errors.presence) + '</p>' : '';
    if (compact) return '<div class="public-account-table-snapshot"><strong>' + escapeHtml(identity) + verified + '</strong><small>@' + escapeHtml(username) + ' · ID ' + escapeHtml(userId) + '</small><span class="public-presence-state ' + escapeHtml(presenceState) + '">' + icon('activity') + escapeHtml(preview ? 'Preview unavailable' : this.publicPresenceLabel(presence)) + '</span></div>';
    const previewDetail = preview ? 'Preview never simulates public Roblox profile or presence data.' : this.publicPresenceDetail(presence);
    return '<section class="account-public-snapshot"><div class="public-identity"><span class="public-identity-label">Roblox public identity</span><strong>' + escapeHtml(identity) + verified + '</strong><small>@' + escapeHtml(username) + ' · ID ' + escapeHtml(userId) + '</small><em>' + escapeHtml(profileState) + '</em></div><div class="public-presence-snapshot"><span class="public-presence-state ' + escapeHtml(presenceState) + '">' + icon('activity') + escapeHtml(preview ? 'Preview unavailable' : this.publicPresenceLabel(presence)) + '</span><small>' + escapeHtml(previewDetail) + '</small></div>' + profileError + presenceError + this.renderPublicAccountActions(account, false) + '</section>';
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
      await this.copyText(script);
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
  }

  navItem(route, label, iconName, count) {
    return '<button class="nav-item ' + (this.state.route === route ? 'is-active' : '') + '" data-action="navigate" data-route="' + route + '" type="button">' + icon(iconName) + '<span>' + label + '</span>' + (count !== undefined ? '<small class="nav-count">' + escapeHtml(count) + '</small>' : '') + '</button>';
  }

  pageMeta() {
    const nexusAccts = asArray((this.state.nexus || {}).accounts);
    const metas = {
      dashboard: ['Overview', 'Your account workspace at a glance'],
      accounts: ['Accounts', this.state.accounts.length + ' identities in your workspace'],
      games: ['Games & servers', 'Browse a game and choose where to join'],
      instances: ['Instances', 'Live Roblox process monitoring'],
      nexus: ['Nexus Executor', nexusAccts.length + ' connected client' + (nexusAccts.length === 1 ? '' : 's')],
      diagnostics: ['Diagnostics', 'Service health and recent events'],
      settings: ['Settings', 'Make Astro Account Manager feel like your workspace']
    };
    return metas[this.state.route] || metas.dashboard;
  }

  render() {
    const meta = this.pageMeta();
    const unread = this.state.notifications.filter(function (item) { return !item.read; }).length;
    this.root.innerHTML = '<aside class="sidebar" aria-label="Main navigation">' +
      '<div class="wordmark"><span class="wordmark-mark">' + icon('orbit') + '</span><span class="wordmark-copy"><strong>astro</strong><small>account manager</small></span></div>' +
      '<nav class="nav">' +
      '<p class="nav-label">Workspace</p>' +
      this.navItem('dashboard', 'Dashboard', 'grid') +
      this.navItem('accounts', 'Accounts', 'users', this.state.accounts.length) +
      this.navItem('games', 'Games & servers', 'gamepad') +
      this.navItem('instances', 'Instances', 'monitor', this.state.instances.length) +
      this.navItem('nexus', 'Nexus', 'command', asArray((this.state.nexus || {}).accounts).length) +
      '<p class="nav-label">System</p>' +
      this.navItem('diagnostics', 'Diagnostics', 'activity') +
      this.navItem('settings', 'Settings', 'settings') +
      '</nav><div class="sidebar-spacer"></div>' +
      (this.state.mode === 'preview' ? '<div class="sidebar-preview"><strong><span></span> Preview workspace</strong><p>Native bridge unavailable. Changes are stored only in this browser.</p></div>' : '') +
      '<button type="button" class="profile-button" data-action="navigate" data-route="settings">' + avatar({ username: 'You', avatar_color: 'blue' }, 'sm') + '<span class="profile-copy"><strong>Local workspace</strong><small>' + (this.state.mode === 'desktop' ? 'Desktop bridge connected' : 'Preview mode') + '</small></span>' + icon('chevronRight') + '</button>' +
      '</aside><section class="workspace"><header class="topbar"><div class="page-title"><h1>' + escapeHtml(meta[0]) + '</h1><p>' + escapeHtml(meta[1]) + '</p></div><div class="topbar-spacer"></div>' +
      '<button class="search-button" type="button" data-action="open-palette">' + icon('search') + '<span>Search anything</span><span class="kbd">Ctrl K</span></button>' +
      '<button class="icon-button" type="button" data-action="toggle-theme" aria-label="Toggle color theme">' + icon(this.state.settings.theme === 'light' ? 'moon' : 'sun') + '</button>' +
      '<span class="topbar-divider"></span><button class="icon-button" type="button" data-action="toggle-notifications" aria-label="Notifications">' + icon('bell') + (unread ? '<span class="notification-pip"></span>' : '') + '</button></header>' +
      '<main id="app-main" class="page" tabindex="-1">' + this.renderPage() + '</main></section>';
    this.renderOverlays();
    if (this.state.route === 'nexus') {
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
    if (this.state.route === 'nexus') return this.renderNexusExecutor();
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
      '</section><section class="section-header"><h3>Continue where you left off</h3><span class="section-line"></span><button class="section-link" type="button" data-action="navigate" data-route="accounts">All accounts</button></section>' +
      '<section class="dashboard-grid"><article class="panel launch-feature"><div class="eyebrow"><span class="live-dot"></span> Quick launch</div><h3>' + (primary ? escapeHtml(primary.display_name || primary.username) + ' is ready for the next session.' : 'Add your first account to begin.') + '</h3><p>' + (primary ? escapeHtml(primary.username) + ' can launch into your selected experience in one step.' : 'Keep sessions, groups, and launches organized in one calm workspace.') + '</p><div class="launch-feature-actions">' + (primary ? '<button class="button button-primary" type="button" data-action="launch" data-id="' + escapeHtml(primary.id) + '">' + icon('play') + ' Launch now</button><button class="button" type="button" data-action="edit-account" data-id="' + escapeHtml(primary.id) + '">' + icon('edit') + ' Details</button>' : '<button class="button button-primary" type="button" data-action="create-account">' + icon('plus') + ' Add your first account</button>') + '</div><div class="feature-meta"><span><strong>' + this.state.instances.length + '</strong> tracked instances</span><span><strong>' + this.state.games.length + '</strong> recent games</span></div></article>' +
      '<article class="panel"><div class="panel-head"><h3>' + icon('clock') + ' Recent activity</h3><button class="section-link" data-action="navigate" data-route="diagnostics" type="button">View log</button></div><div class="activity-list">' + this.renderActivity(this.state.activity.slice(0, 4)) + '</div></article></section>' +
      '<section class="section-header"><h3>Recently used accounts</h3><p>Jump right back in</p><span class="section-line"></span></section><section class="recent-accounts">' + (recent.length ? recent.map(this.renderMiniAccount.bind(this)).join('') : this.emptyInline('users', 'No accounts yet', 'Add an account to build a launch history.')) + '</section>';
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
    return '<button class="mini-account" type="button" data-action="edit-account" data-id="' + escapeHtml(account.id) + '">' + avatar(account, 'sm') + '<span class="mini-account-copy"><strong>' + escapeHtml(account.display_name || account.username) + '</strong><span>' + escapeHtml(account.username) + ' · ' + relativeTime(account.last_used) + '</span></span><span class="status ' + escapeHtml(account.status) + '" aria-label="' + statusText(account.status) + '"></span></button>';
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
      '</div>' +
      '<div style="display: flex; gap: 6px; margin-top: 2px;">' +
      '<button class="button button-secondary" style="flex: 1; font-size: 0.8rem; padding: 6px;" type="button" data-action="open-account-utilities">⚙️ Utilities</button>' +
      '<button class="button button-secondary" style="flex: 1; font-size: 0.8rem; padding: 6px;" type="button" data-action="open-nexus-panel">🚀 Nexus Control</button>' +
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
    const hide = Boolean(this.state.hideUsernames);
    const displayUser = hide ? '••••••••' : escapeHtml(account.username);
    const displayAlias = hide ? '••••••••' : escapeHtml(account.display_name || account.username);
    return '<article class="account-card ' + (selected ? 'is-selected' : '') + '" data-account-id="' + escapeHtml(account.id) + '" draggable="true"><button class="account-card-check" type="button" data-action="account-select" data-id="' + escapeHtml(account.id) + '" aria-label="' + (selected ? 'Deselect' : 'Select') + ' ' + displayUser + '">' + icon(selected ? 'check' : 'plus') + '</button><div class="account-card-top">' + avatar(account) + '<div class="account-card-info"><strong>' + displayAlias + '</strong><span>@' + displayUser + '</span></div></div><div class="account-status-row"><span class="status ' + escapeHtml(account.status) + '">' + statusText(account.status) + '</span><span class="last-used">' + relativeTime(account.last_used) + '</span></div><div class="account-oauth-row">' + this.renderOAuthAccountState(account) + '</div>' + this.renderPublicAccountSnapshot(account, false) + '<div class="account-card-bottom"><button class="button button-sm button-primary" type="button" data-action="launch" data-id="' + escapeHtml(account.id) + '">' + icon('play') + ' Launch</button><button class="favorite-star ' + (account.favorite ? 'is-favorite' : '') + '" type="button" data-action="toggle-favorite" data-id="' + escapeHtml(account.id) + '" aria-label="' + (account.favorite ? 'Remove favorite' : 'Add favorite') + '">' + icon('star') + '</button>' + this.renderOAuthAccountActions(account, false) + '<button class="icon-button" type="button" data-action="edit-account" data-id="' + escapeHtml(account.id) + '" aria-label="Edit ' + displayUser + '">' + icon('dots') + '</button></div></article>';
  }

  renderAccountsTable(accounts) {
    if (!accounts.length) return this.emptyState('search', 'No matching accounts', 'Try a different search or clear the filters.', 'Clear filters', 'clear-account-filter');
    const hide = Boolean(this.state.hideUsernames);
    return '<div class="data-table-wrap"><table class="data-table"><thead><tr><th aria-label="Select"></th><th>Account</th><th>Status</th><th>Roblox</th><th>Group</th><th>Last used</th><th aria-label="Actions"></th></tr></thead><tbody>' + accounts.map(function (account) {
      const group = this.groupFor(account.group_id);
      const selected = this.state.selected.has(account.id);
      const displayUser = hide ? '••••••••' : escapeHtml(account.username);
      const displayAlias = hide ? '••••••••' : escapeHtml(account.display_name || account.username);
      return '<tr><td><input type="checkbox" data-action="account-select" data-id="' + escapeHtml(account.id) + '" aria-label="Select ' + displayUser + '"' + (selected ? ' checked' : '') + ' /></td><td><div class="table-account">' + avatar(account, 'sm') + '<span><strong>' + displayAlias + '</strong><small>@' + displayUser + '</small></span></div></td><td><span class="status ' + escapeHtml(account.status) + '">' + statusText(account.status) + '</span></td><td><div class="table-roblox-state">' + this.renderOAuthAccountState(account) + this.renderPublicAccountSnapshot(account, true) + '</div></td><td>' + (group ? '<span class="group-chip"><i class="' + escapeHtml(group.color || '') + '"></i>' + escapeHtml(group.name) + '</span>' : '<span class="mono">Ungrouped</span>') + '</td><td><span class="mono">' + relativeTime(account.last_used) + '</span></td><td><div class="table-actions"><button class="icon-button" type="button" data-action="launch" data-id="' + escapeHtml(account.id) + '" aria-label="Launch ' + displayUser + '">' + icon('play') + '</button>' + this.renderOAuthAccountActions(account, true) + '<button class="icon-button" type="button" data-action="edit-account" data-id="' + escapeHtml(account.id) + '" aria-label="Edit ' + displayUser + '">' + icon('edit') + '</button></div></td></tr>';
    }.bind(this)).join('') + '</tbody></table></div>';
  }

  groupFor(id) { return this.state.groups.find(function (group) { return String(group.id) === String(id); }) || null; }

  renderGames() {
    const games = this.state.games.filter(function (game) { return !this.state.gameQuery || [game.title, game.creator, game.category].join(' ').toLowerCase().includes(this.state.gameQuery.toLowerCase()); }.bind(this));
    const selectedGame = this.state.gameDetail || this.state.games.find(function (game) { return String(game.place_id) === String(this.state.gameId); });
    return '<section class="page-heading"><div class="page-heading-copy"><h2>Find the room, not just the game.</h2><p>Keep your recent worlds close, then choose a server by region, capacity, and latency before launching an account.</p></div><div class="page-heading-actions"><button class="button" type="button" data-action="refresh-servers">' + icon('refresh') + ' Refresh servers</button></div></section><section class="toolbar"><label class="input-shell">' + icon('search') + '<input id="game-filter" type="search" autocomplete="off" placeholder="Search games" value="' + escapeHtml(this.state.gameQuery) + '" /></label><span class="toolbar-spacer"></span><span class="offline-note">' + icon(this.state.mode === 'desktop' ? 'shield' : 'info') + (this.state.mode === 'desktop' ? ' Live bridge connected' : ' Preview data') + '</span></section><section class="games-layout"><div><div class="section-header"><h3>Recent & favorites</h3><span class="section-line"></span><span>' + games.length + ' games</span></div><div class="game-list">' + (games.length ? games.map(this.renderGameCard.bind(this)).join('') : this.emptyState('search', 'No matching games', 'Change your search to see saved games.', 'Clear search', 'clear-game-filter')) + '</div></div><aside class="panel game-detail">' + this.renderGameDetail(selectedGame) + '</aside></section>';
  }

  renderGameCard(game) {
    return '<button class="game-card ' + (String(game.place_id) === String(this.state.gameId) ? 'is-active' : '') + '" type="button" data-action="select-game" data-id="' + escapeHtml(game.place_id) + '"><span class="game-image ' + escapeHtml(game.thumbnail_color || '') + '"><span>' + escapeHtml(initials(game.title).slice(0, 1)) + '</span></span><span class="game-copy"><strong>' + escapeHtml(game.title) + '</strong><span>' + escapeHtml(game.creator || 'Unknown creator') + ' · ' + escapeHtml(game.category || 'Game') + '</span><small><b>●</b> ' + formatNumber(game.players) + ' playing</small></span><span class="game-arrow">' + icon('chevronRight') + '</span></button>';
  }

  renderGameDetail(game) {
    if (!game) return '<div class="empty-notices">' + icon('gamepad') + '<p>Select a game to explore its servers.</p></div>';
    const servers = this.state.servers;
    const placeId = escapeHtml(game.place_id);
    const favorite = Boolean(game.favorite);
    return '<div class="game-detail-hero"><span class="badge accent">' + escapeHtml(game.category || 'Game') + '</span><h3>' + escapeHtml(game.title) + '</h3><p>' + escapeHtml(game.creator || 'Unknown creator') + '</p></div><div class="detail-meta"><div><small>Place ID</small><strong title="' + placeId + '">' + placeId + '</strong></div><div><small>Playing now</small><strong>' + formatNumber(game.players) + '</strong></div><button class="icon-button" type="button" data-action="copy-place" data-value="' + placeId + '" aria-label="Copy Place ID">' + icon('copy') + '</button><button class="favorite-star ' + (favorite ? 'is-favorite' : '') + '" type="button" data-action="toggle-game-favorite" data-id="' + placeId + '" aria-label="' + (favorite ? 'Remove game from favorites' : 'Add game to favorites') + '" title="' + (favorite ? 'Remove from favorites' : 'Add to favorites') + '">' + icon('star') + '</button><button class="icon-button" type="button" data-action="open-remove-game" data-id="' + placeId + '" aria-label="Remove ' + escapeHtml(game.title) + ' from local games" title="Remove local game">' + icon('trash') + '</button></div><div class="panel-head"><h3>' + icon('monitor') + ' Public servers</h3><span>' + (this.state.serversLoading ? 'Refreshing...' : servers.length + ' visible') + '</span></div><div class="server-list">' + (this.state.serversLoading ? '<div class="empty-notices">' + icon('refresh') + '<p>Checking available servers...</p></div>' : servers.length ? servers.slice(0, 7).map(this.renderServer.bind(this)).join('') : '<div class="empty-notices">' + icon('monitor') + '<p>No server list yet.</p></div>') + '</div>';
  }

  renderGameDetailSnapshot(game) {
    if (!game) return '<div class="empty-notices">' + icon('gamepad') + '<p>Select a game to explore its servers.</p></div>';
    const servers = this.state.servers;
    return '<div class="game-detail-hero"><span class="badge accent">' + escapeHtml(game.category || 'Game') + '</span><h3>' + escapeHtml(game.title) + '</h3><p>' + escapeHtml(game.creator || 'Unknown creator') + '</p></div><div class="detail-meta"><div><small>Place ID</small><strong title="' + escapeHtml(game.place_id) + '">' + escapeHtml(game.place_id) + '</strong></div><div><small>Playing now</small><strong>' + formatNumber(game.players) + '</strong></div><button class="icon-button" type="button" data-action="copy-place" data-value="' + escapeHtml(game.place_id) + '" aria-label="Copy Place ID">' + icon('copy') + '</button></div><div class="panel-head"><h3>' + icon('monitor') + ' Public servers</h3><span>' + (this.state.serversLoading ? 'Refreshing…' : servers.length + ' visible') + '</span></div><div class="server-list">' + (this.state.serversLoading ? '<div class="empty-notices">' + icon('refresh') + '<p>Checking available servers…</p></div>' : servers.length ? servers.slice(0, 7).map(this.renderServer.bind(this)).join('') : '<div class="empty-notices">' + icon('monitor') + '<p>No server list yet.</p></div>') + '</div>';
  }

  renderServer(server) {
    const percent = Math.min(100, Math.round(Number(server.players || 0) / Math.max(1, Number(server.capacity || 1)) * 100));
    return '<div class="server-row"><div class="server-copy"><strong>' + escapeHtml(server.region || 'Unknown region') + (server.vip ? ' · VIP' : '') + '</strong><span>' + escapeHtml(server.ping) + ' ms · ' + escapeHtml(server.job_id || 'No JobId') + '</span></div><div class="capacity"><span>' + escapeHtml(server.players) + ' / ' + escapeHtml(server.capacity) + '</span><i><b class="' + (percent > 78 ? 'warn' : '') + '" style="width:' + percent + '%"></b></i></div><button class="button button-sm" type="button" data-action="join-server" data-server="' + escapeHtml(server.id) + '">Join</button></div>';
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
    return '<section class="page-heading"><div class="page-heading-copy"><h2>Every running session, accounted for.</h2><p>Astro Account Manager keeps launch state, process IDs, and lightweight health signals together so active accounts never become guesswork.</p></div><div class="page-heading-actions"><button class="button button-primary" type="button" data-action="refresh-instances">' + icon('refresh') + ' Refresh instances</button></div></section><section class="instance-summary"><article class="panel monitor-card"><h3>Instance watcher</h3><p>Current local process observations from the desktop bridge.</p><div class="pulse-track"><svg class="pulse-svg" preserveAspectRatio="none" viewBox="0 0 400 55"><polyline points="0,33 22,33 32,19 42,42 54,28 67,33 97,33 112,18 123,42 138,25 152,33 193,33 204,21 217,38 231,33 279,33 294,16 305,42 320,27 334,33 400,33"></polyline></svg></div><div class="monitor-footer"><span>' + escapeHtml(scanLabel) + '</span><span>' + this.state.instances.length + ' tracked process' + (this.state.instances.length === 1 ? '' : 'es') + '</span><span class="monitor-mode">' + escapeHtml(closeLabel) + '</span></div></article><article class="panel"><div class="panel-head"><h3>' + icon('shield') + ' Service health</h3><span>' + escapeHtml(this.state.diagnostics.status || 'Healthy') + '</span></div><div class="health-list">' + services.map(function (service) { return '<div class="health-row"><span class="health-symbol">' + icon(service.status === 'degraded' ? 'alert' : 'check') + '</span><span class="health-copy"><strong>' + escapeHtml(service.name) + '</strong><span>' + escapeHtml(service.detail) + '</span></span><span class="status ' + escapeHtml(service.status || 'healthy') + '"></span></div>'; }).join('') + '</div></article></section><section class="section-header"><h3>Observed instances</h3><p>Tracked locally by the desktop bridge</p><span class="section-line"></span></section>' + this.renderInstancesTable() + '<section class="monitor-detail-grid">' + pendingBlock + eventBlock + '</section>' + this.renderNexusSection();
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
            '<select class="nexus-target-select" id="nexus-exec-target" data-action="nexus-change-target">' + targetOptions + '</select>' +
            '<button class="button button-primary button-sm nexus-exec-btn" type="button" data-action="nexus-execute"' + (!running ? ' disabled title="Start Nexus server first"' : '') + '>' + icon('play') + ' Execute</button>' +
            '<button class="button button-sm" type="button" data-action="nexus-clear-editor" title="Clear editor">' + icon('trash') + '</button>' +
          '</div>' +
        '</div>' +
        '<div class="nexus-editor-wrap">' +
          '<div class="nexus-line-numbers" id="nexus-line-numbers"></div>' +
          '<textarea class="nexus-code-editor" id="nexus-code-editor" spellcheck="false" autocomplete="off" autocorrect="off" autocapitalize="off" wrap="off" data-action="nexus-code-input">' + codeValue + '</textarea>' +
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
    return '<div class="data-table-wrap"><table class="data-table"><thead><tr><th>Account</th><th>Experience</th><th>State</th><th>Process</th><th>Memory</th><th>Started</th><th aria-label="Actions"></th></tr></thead><tbody>' + this.state.instances.map(function (instance) {
      const account = this.state.accounts.find(function (item) { return String(item.id) === String(instance.account_id); }) || { username: 'Unknown', avatar_color: 'neutral' };
      return '<tr><td><div class="table-account">' + avatar(account, 'sm') + '<span><strong>' + escapeHtml(account.display_name || account.username) + '</strong><small>@' + escapeHtml(account.username) + '</small></span></div></td><td><span>' + escapeHtml(instance.game || 'Roblox') + '</span><br /><small class="mono">' + escapeHtml(instance.server || '-') + '</small></td><td><span class="status ' + escapeHtml(instance.state || 'running') + '">' + statusText(instance.state || 'running') + '</span></td><td><span class="mono">PID ' + escapeHtml(instance.pid || '-') + '</span></td><td><span class="mono">' + escapeHtml(instance.memory_mb || '-') + ' MB</span></td><td><span class="mono">' + relativeTime(instance.started_at) + '</span></td><td><div class="table-actions">' + this.renderInstanceActions(instance) + '</div></td></tr>';
    }.bind(this)).join('') + '</tbody></table></div>';
  }

  renderInstanceActions(instance) {
    const pid = escapeHtml(instance.pid);
    const canClose = Boolean(this.state.instanceMonitor && this.state.instanceMonitor.termination_enabled);
    const bind = instance.state === 'orphaned' ? '<button class="button button-sm" type="button" data-action="open-bind-instance" data-pid="' + pid + '">' + icon('users') + ' Associate</button>' : '';
    const close = canClose ? '<button class="icon-button" type="button" data-action="open-close-instance" data-pid="' + pid + '" aria-label="Close Roblox process ' + pid + '" title="Close instance">' + icon('x') + '</button>' : '<span class="instance-action-note" title="Enable instance closing in Settings before closing a process">Closing disabled</span>';
    return bind + close;
  }

  renderInstancesTableSnapshot() {
    if (!this.state.instances.length) return this.emptyState('monitor', 'No Roblox instances found', 'Launch an account to start watching it here.', 'Go to accounts', 'navigate-accounts');
    return '<div class="data-table-wrap"><table class="data-table"><thead><tr><th>Account</th><th>Experience</th><th>State</th><th>Process</th><th>Memory</th><th>Started</th></tr></thead><tbody>' + this.state.instances.map(function (instance) {
      const account = this.state.accounts.find(function (item) { return String(item.id) === String(instance.account_id); }) || { username: 'Unknown', avatar_color: 'neutral' };
      return '<tr><td><div class="table-account">' + avatar(account, 'sm') + '<span><strong>' + escapeHtml(account.display_name || account.username) + '</strong><small>@' + escapeHtml(account.username) + '</small></span></div></td><td><span>' + escapeHtml(instance.game || 'Roblox Home') + '</span><br /><small class="mono">' + escapeHtml(instance.server || '—') + '</small></td><td><span class="status ' + escapeHtml(instance.state || 'running') + '">' + statusText(instance.state || 'running') + '</span></td><td><span class="mono">PID ' + escapeHtml(instance.pid || '—') + '</span></td><td><span class="mono">' + escapeHtml(instance.memory_mb || '—') + ' MB</span></td><td><span class="mono">' + relativeTime(instance.started_at) + '</span></td></tr>';
    }.bind(this)).join('') + '</tbody></table></div>';
  }

  renderDiagnostics() {
    const diagnostics = this.state.diagnostics || { services: [], logs: [] };
    return '<section class="page-heading"><div class="page-heading-copy"><h2>Quietly verify the machinery.</h2><p>Health signals are written for people first, with recent technical context available when you need to investigate an issue.</p></div><div class="page-heading-actions"><button class="button" type="button" data-action="refresh-diagnostics">' + icon('refresh') + ' Refresh status</button><button class="button" type="button" data-action="export-metadata">' + icon('upload') + ' Export metadata</button><button class="button" type="button" data-action="open-import-metadata">' + icon('download') + ' Import metadata</button><button class="button" type="button" data-action="open-restore">' + icon('upload') + ' Restore backup</button><button class="button button-primary" type="button" data-action="backup">' + icon('database') + ' Back up data</button></div></section><section class="stats-grid"><article class="stat-card"><span class="stat-card-label">' + icon('shield') + ' Overall health</span><strong>' + escapeHtml(diagnostics.status === 'healthy' ? 'Good' : diagnostics.status || 'Check') + '</strong><small><em>Checked ' + relativeTime(diagnostics.checked_at) + '</em></small></article><article class="stat-card"><span class="stat-card-label">' + icon('monitor') + ' Active instances</span><strong>' + this.state.instances.length + '</strong><small>Processes matched to accounts</small></article><article class="stat-card"><span class="stat-card-label">' + icon('database') + ' Account vault</span><strong>Ready</strong><small>Secure data service available</small></article><article class="stat-card"><span class="stat-card-label">' + icon('activity') + ' Event history</span><strong>' + this.state.activity.length + '</strong><small>Recent workspace events</small></article></section><section class="section-header"><h3>Service checks</h3><span class="section-line"></span></section><section class="data-table-wrap"><table class="data-table"><thead><tr><th>Service</th><th>Status</th><th>Detail</th></tr></thead><tbody>' + (diagnostics.services || []).map(function (service) { return '<tr><td><strong>' + escapeHtml(service.name) + '</strong></td><td><span class="status ' + escapeHtml(service.status || 'healthy') + '">' + statusText(service.status || 'healthy') + '</span></td><td><span class="mono">' + escapeHtml(service.detail || '') + '</span></td></tr>'; }).join('') + '</tbody></table></section><section class="section-header"><h3>Recent diagnostics</h3><p>Technical entries are local to this device.</p><span class="section-line"></span></section><section class="panel"><div class="diagnostic-box"><pre>' + escapeHtml((diagnostics.logs || []).map(function (row) { return '[' + new Date(row.at || Date.now()).toLocaleTimeString() + '] ' + (row.level || 'INFO') + '  ' + (row.message || ''); }).join('\n') || 'No diagnostic entries available.') + '</pre></div></section>';
  }

  renderSettings() {
    const tabs = [['general', 'General'], ['performance', 'Performance & FPS'], ['appearance', 'Appearance'], ['accounts', 'Accounts'], ['oauth', 'Roblox sign-in'], ['instances', 'Instances'], ['notifications', 'Notifications'], ['advanced', 'Advanced']];
    return '<section class="page-heading"><div class="page-heading-copy"><h2>Make the workspace yours.</h2><p>Settings are applied immediately and stay deliberately compact. The desktop bridge persists them securely when it is available.</p></div><div class="page-heading-actions"><button class="button" type="button" data-action="backup">' + icon('database') + ' Create backup</button></div></section><section class="settings-layout"><nav class="panel settings-nav" aria-label="Settings categories">' + tabs.map(function (tab) { return '<button type="button" data-action="settings-tab" data-tab="' + tab[0] + '" class="' + (this.state.settingsTab === tab[0] ? 'is-active' : '') + '">' + tab[1] + '</button>'; }.bind(this)).join('') + '</nav><div class="settings-content">' + this.renderSettingsPanel() + '</div></section>';
  }

  settingRow(title, body, control) {
    return '<div class="setting-row"><div class="setting-copy"><strong>' + title + '</strong><span>' + body + '</span></div><div class="setting-control">' + control + '</div></div>';
  }

  toggleSetting(key, checked) {
    return '<label class="switch"><input type="checkbox" data-setting="' + key + '"' + (checked ? ' checked' : '') + ' /><span></span></label>';
  }

  renderSettingsPanel() {
    const s = this.state.settings;
    if (this.state.settingsTab === 'performance') return '<section class="panel settings-section"><header class="settings-section-head"><div><h3>Performance & FPS</h3><p>FPS Frame Unlocker cap and Potato Graphics mode for low-end hardware.</p></div></header>' +
      this.settingRow('Frame Unlocker (FPS Target)', 'Frame rate cap target for Roblox clients (DFIntTaskSchedulerTargetFps).', '<select class="setting-select" data-setting="global_max_fps"><option value="0"' + (s.global_max_fps == 0 ? ' selected' : '') + '>Roblox Default</option><option value="60"' + (s.global_max_fps == 60 ? ' selected' : '') + '>60 FPS</option><option value="120"' + (s.global_max_fps == 120 ? ' selected' : '') + '>120 FPS</option><option value="144"' + (s.global_max_fps == 144 ? ' selected' : '') + '>144 FPS</option><option value="240"' + (s.global_max_fps == 240 || !s.global_max_fps ? ' selected' : '') + '>240 FPS (Recommended)</option><option value="360"' + (s.global_max_fps == 360 ? ' selected' : '') + '>360 FPS</option></select>') +
      this.settingRow('Potato Graphics Mode 🥔', 'Extreme graphics reduction (textures, shadows, post-fx, materials) via FastFlags for maximum accounts on low-end hardware.', this.toggleSetting('potato_graphics', s.potato_graphics)) + '</section>';
    if (this.state.settingsTab === 'appearance') return '<section class="panel settings-section"><header class="settings-section-head"><div><h3>Appearance</h3><p>Theme, color and comfortable visual density.</p></div></header>' +
      this.settingRow('Color theme', 'Switch between the premium dark and bright light canvas.', '<select class="setting-select" data-setting="theme"><option value="dark"' + (s.theme !== 'light' ? ' selected' : '') + '>Dark</option><option value="light"' + (s.theme === 'light' ? ' selected' : '') + '>Light</option></select>') +
      this.settingRow('Accent color', 'A focused color used for selection, status, and primary actions.', '<div class="color-options"><button class="color-option ' + (s.accent === 'violet' ? 'is-active' : '') + '" type="button" data-action="set-accent" data-accent="violet" aria-label="Violet accent"><i></i></button><button class="color-option mint ' + (s.accent === 'mint' ? 'is-active' : '') + '" type="button" data-action="set-accent" data-accent="mint" aria-label="Mint accent"><i></i></button><button class="color-option coral ' + (s.accent === 'coral' ? 'is-active' : '') + '" type="button" data-action="set-accent" data-accent="coral" aria-label="Coral accent"><i></i></button><button class="color-option blue ' + (s.accent === 'blue' ? 'is-active' : '') + '" type="button" data-action="set-accent" data-accent="blue" aria-label="Blue accent"><i></i></button><button class="color-option amber ' + (s.accent === 'amber' ? 'is-active' : '') + '" type="button" data-action="set-accent" data-accent="amber" aria-label="Amber accent"><i></i></button></div>') +
      this.settingRow('Interface density', 'Use compact spacing when you manage a larger collection.', '<select class="setting-select" data-setting="density"><option value="comfortable"' + (s.density !== 'compact' ? ' selected' : '') + '>Comfortable</option><option value="compact"' + (s.density === 'compact' ? ' selected' : '') + '>Compact</option></select>') +
      this.settingRow('Reduced motion', 'Disable non-essential transitions and animated status details.', this.toggleSetting('reduce_motion', s.reduce_motion)) + '</section>';
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
      this.settingRow('Instance watcher', 'Detect supported Roblox processes and keep their state current.', this.toggleSetting('watcher_enabled', s.watcher_enabled)) +
      this.settingRow('Allow instance closing', 'Enable local process closing. Every close still requires a separate confirmation in Instances.', this.toggleSetting('watcher_termination_enabled', s.watcher_termination_enabled)) +
      this.settingRow('Allow account relaunch rules', 'Enable the opt-in per-account watcher rules that can request a bounded relaunch after an exit or crash.', this.toggleSetting('watcher_auto_relaunch_enabled', s.watcher_auto_relaunch_enabled)) +
      this.settingRow('Refresh now', 'Run an immediate process scan through the desktop bridge.', '<button class="button button-sm" type="button" data-action="refresh-instances">' + icon('refresh') + ' Refresh instances</button>') + '</section>';
    if (this.state.settingsTab === 'notifications') return '<section class="panel settings-section"><header class="settings-section-head"><div><h3>Notifications</h3><p>Control in-app status messages.</p></div></header>' +
      this.settingRow('In-app notifications', 'Surface launch results, backup outcomes, and watcher events.', this.toggleSetting('notifications', s.notifications)) +
      this.settingRow('Notification center', 'Review and dismiss messages from the top bar.', '<button class="button button-sm" type="button" data-action="toggle-notifications">' + icon('bell') + ' Open notifications</button>') + '</section>';
    if (this.state.settingsTab === 'advanced') return '<section class="panel settings-section"><header class="settings-section-head"><div><h3>Data tools</h3><p>Use portable backups before importing data from legacy versions.</p></div></header>' +
      this.settingRow('Create backup', 'Request a verified backup from the local data service.', '<button class="button button-sm" type="button" data-action="backup">' + icon('database') + ' Back up now</button>') +
      this.settingRow('Migrate legacy data', 'Inspect an existing Roblox Account Manager data location.', '<button class="button button-sm" type="button" data-action="migrate">' + icon('upload') + ' Start migration</button>') +
      this.settingRow('Developer diagnostics', 'Show extra technical state inside Diagnostics.', this.toggleSetting('diagnostics', s.diagnostics)) + '</section>';
    return '<section class="panel settings-section"><header class="settings-section-head"><div><h3>General</h3><p>Small choices that make daily use feel smoother.</p></div></header>' +
      this.settingRow('Workspace mode', this.state.mode === 'desktop' ? 'Connected to the local pywebview desktop bridge.' : 'Preview mode runs entirely in your browser with sample data.', '<span class="badge ' + (this.state.mode === 'desktop' ? 'success' : 'warning') + '">' + (this.state.mode === 'desktop' ? 'Connected' : 'Preview') + '</span>') +
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
    this.overlayRoot.innerHTML = output;
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
    if (modal.kind === 'windows-startup') {
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
          '<div class="field full"><label for="account-notes">Private note</label><textarea id="account-notes" name="notes" maxlength="280" placeholder="Notes about this account">' + escapeHtml(account.notes || '') + '</textarea></div>' +
          '<label class="form-check field full"><input type="checkbox" name="favorite"' + (account.favorite ? ' checked' : '') + ' /> Keep in favorites</label></div></div>' +
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
      const watcher = Object.assign({ auto_relaunch: false, relaunch_delay_seconds: 15, relaunch_max_attempts: 2, relaunch_on_crash: true, relaunch_on_exit: false }, account.watcher || {});
      const globalEnabled = Boolean(this.state.settings.watcher_auto_relaunch_enabled);
      title = 'Watcher rule for ' + (account.display_name || account.username || 'account');
      sub = globalEnabled ? 'This rule is opt-in and bounded for this one account.' : 'Save the rule here, then enable account relaunch rules in Settings > Instances before it can run.';
      body = '<form data-form="watcher-rule" data-id="' + escapeHtml(account.id || '') + '"><div class="modal-body"><p class="form-error" hidden></p><p class="oauth-help">A relaunch rule observes local process exits only. It does not authenticate an account, read browser data, or run remote scripts.</p><div class="form-grid"><label class="form-check field full"><input type="checkbox" name="auto_relaunch"' + (watcher.auto_relaunch ? ' checked' : '') + ' /> Enable a bounded automatic relaunch for this account</label><div class="field"><label for="watcher-delay">Delay before relaunch (seconds)</label><input id="watcher-delay" name="relaunch_delay_seconds" type="number" min="1" max="3600" step="1" required value="' + escapeHtml(watcher.relaunch_delay_seconds) + '" /></div><div class="field"><label for="watcher-attempts">Maximum attempts</label><input id="watcher-attempts" name="relaunch_max_attempts" type="number" min="0" max="20" step="1" required value="' + escapeHtml(watcher.relaunch_max_attempts) + '" /></div><label class="form-check field"><input type="checkbox" name="relaunch_on_crash"' + (watcher.relaunch_on_crash ? ' checked' : '') + ' /> Relaunch after a crash</label><label class="form-check field"><input type="checkbox" name="relaunch_on_exit"' + (watcher.relaunch_on_exit ? ' checked' : '') + ' /> Relaunch after a normal exit</label></div></div><footer class="modal-foot"><button class="button" type="button" data-action="close-modal">Cancel</button><button class="button button-primary" type="submit">' + icon('check') + ' Save watcher rule</button></footer></form>';
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
        '<option value="logout_all">Logout all other sessions</option>' +
        '<option value="block">Block user</option>' +
        '<option value="unblock">Unblock user</option>' +
        '<option value="unblock_all">Unblock ALL users</option>' +
        '<option value="password">Change password</option>' +
        '<option value="email">Change email address</option>' +
        '</select></div>' +
        '<div class="field"><label for="util-payload">Parameter / Payload (6-digit code, User ID, Password or Email)</label><input id="util-payload" name="payload" placeholder="Enter value if required..." /></div>' +
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
      { kind: 'route', route: 'nexus', icon: 'command', title: 'Open Nexus executor', detail: 'Execute Lua scripts on clients', shortcut: 'G N' },
      { kind: 'route', route: 'settings', icon: 'settings', title: 'Open settings', detail: 'Appearance, watcher, backups', shortcut: 'G S' },
      { kind: 'action', action: 'refresh-instances', icon: 'refresh', title: 'Refresh instances', detail: 'Run a process scan', shortcut: 'Ctrl R' }
    ].filter(function (item) { return matches(item.title + ' ' + item.detail); });
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
    if (action === 'navigate-accounts') { this.navigate('accounts'); return; }
    if (action === 'open-palette') { this.openPalette(); return; }
    if (action === 'close-modal') { await this.dismissOAuthModal(); return; }
    if (action === 'open-windows-startup') { this.openWindowsStartupModal(button.dataset.enabled === 'true'); return; }
    if (action === 'refresh-windows-startup') { await this.loadWindowsStartupStatus(true); return; }
    if (action === 'toggle-notifications') { this.state.notificationsOpen = !this.state.notificationsOpen; this.renderOverlays(); return; }
    if (action === 'toggle-theme') { await this.updateSettings({ theme: this.state.settings.theme === 'light' ? 'dark' : 'light' }, false); return; }
    if (action === 'set-accent') { await this.updateSettings({ accent: button.dataset.accent }, false); return; }
    if (action === 'create-account') { this.openModal({ kind: 'account', account: {} }); return; }
    if (action === 'open-bulk-import') { this.openModal({ kind: 'bulk-import' }); return; }
    if (action === 'open-add-cookie') { this.openModal({ kind: 'cookie-add' }); return; }
    if (action === 'start-manual-browser-login') {
      try {
        const res = await this.bridge.call('start_manual_browser_login');
        this.toast('info', 'Roblox Login Browser Opened', 'Sign in on Roblox in the dedicated browser window. Your session cookie will be captured automatically!');
      } catch (err) {
        this.toast('error', 'Browser Error', err.message || 'Could not open login browser.');
      }
      return;
    }
    if (action === 'toggle-hide-usernames') { this.state.hideUsernames = !this.state.hideUsernames; this.render(); return; }
    if (action === 'toggle-uwp') { this.state.uwpMode = !this.state.uwpMode; this.toast('info', 'UWP Mode', this.state.uwpMode ? 'UWP Mode Enabled' : 'Standard Web Mode Enabled'); this.render(); return; }
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
      for (const id of selectedIds) {
        await this.bridge.call('update_account', id, { saved_place_id: placeId, saved_job_id: jobId });
      }
      await this.resync(); this.render();
      this.toast('success', 'Place ID Saved', 'Saved for ' + selectedIds.length + ' account(s).');
      return;
    }
    if (action === 'ram-join-server') {
      const placeInput = $('#ram-place-id');
      const jobInput = $('#ram-job-id');
      const placeId = placeInput ? Number(placeInput.value) : null;
      const jobId = jobInput ? jobInput.value.trim() : '';
      const selectedIds = Array.from(this.state.selected);
      if (!selectedIds.length && this.state.accounts.length) selectedIds.push(this.state.accounts[0].id);
      if (!selectedIds.length) { this.toast('info', 'No Account Selected', 'Select an account to launch.'); return; }
      const target = {};
      if (placeId) target.place_id = placeId;
      if (jobId) target.job_id = jobId;
      for (const id of selectedIds) {
        await this.bridge.call('launch_account', id, target);
      }
      this.toast('success', 'Server Launch Requested', 'Launch initiated for ' + selectedIds.length + ' account(s).');
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
        if (!presence.place_id) throw new Error('This player is not currently in a game.');
        await this.bridge.call('launch_account', accId, { place_id: presence.place_id, job_id: presence.job_id });
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
      for (const id of selectedIds) {
        await this.bridge.call('update_account', id, { display_name: newAlias });
      }
      await this.resync(); this.render();
      this.toast('success', 'Alias Updated', 'New display name applied.');
      return;
    }
    if (action === 'ram-set-description') {
      const descInput = $('#ram-desc-input');
      const newDesc = descInput ? descInput.value.trim() : '';
      const selectedIds = Array.from(this.state.selected);
      if (!selectedIds.length) { this.toast('info', 'Select an Account', 'Check at least one account.'); return; }
      for (const id of selectedIds) {
        await this.bridge.call('update_account', id, { description: newDesc, notes: newDesc });
      }
      await this.resync(); this.render();
      this.toast('success', 'Description Updated', 'Description saved successfully.');
      return;
    }
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
    if (action === 'refresh-instances') { await this.refreshInstances(); return; }
    if (action === 'refresh-diagnostics') { await this.refreshDiagnostics(); return; }
    if (action === 'open-restore') { await this.openRestoreModal(); return; }
    if (action === 'export-metadata') { await this.exportMetadata(); return; }
    if (action === 'open-import-metadata') { this.openModal({ kind: 'import-metadata' }); return; }
    if (action === 'backup') { await this.backup(); return; }
    if (action === 'migrate') { this.openModal({ kind: 'migrate' }); return; }
    if (action === 'settings-tab') { this.state.settingsTab = button.dataset.tab; this.render(); if (this.state.settingsTab === 'general') void this.loadWindowsStartupStatus(false); return; }
    if (action === 'copy-place') { await this.copyText(button.dataset.value); return; }
    if (action === 'dismiss-notification') { await this.dismissNotification(button.dataset.id); return; }
    if (action === 'clear-account-filter') { this.state.accountQuery = ''; this.state.accountStatus = 'all'; this.render(); return; }
    if (action === 'clear-game-filter') { this.state.gameQuery = ''; this.render(); return; }
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
          if (!payload) throw new Error('Please enter the 6-digit Quick Log In code.');
          await this.bridge.call('quick_log_in_account', accountId, payload);
          this.toast('success', 'Quick Log In', 'Code validated successfully!');
        } else if (actionKind === 'password') {
          const parts = payload.split(':');
          if (parts.length < 2) throw new Error('Payload format required: CurrentPassword:NewPassword');
          await this.bridge.call('change_account_password', accountId, parts[0], parts[1]);
          this.toast('success', 'Password Changed', 'Password updated successfully!');
        } else if (actionKind === 'email') {
          const parts = payload.split(':');
          if (parts.length < 2) throw new Error('Payload format required: CurrentPassword:NewEmail');
          await this.bridge.call('change_account_email', accountId, parts[0], parts[1]);
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
        } else if (actionKind === 'get_cookie') {
          const res = await this.bridge.call('get_account_cookie', accountId);
          await this.copyText(res.cookie || '');
          this.toast('success', 'Cookie Copied', '.ROBLOSECURITY cookie copied to clipboard!');
        }
        this.closeModal();
        this.render();
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
        this.toast('success', 'Bulk Import Completed', res.imported + ' account(s) imported out of ' + res.total_parsed);
      } else if (form.dataset.form === 'windows-startup') {
        if (values.confirm !== 'on') throw new Error('Confirm the Windows startup change before continuing.');
        if (form.dataset.enabled !== 'true' && form.dataset.enabled !== 'false') throw new Error('The requested Windows startup state is invalid.');
        const enabled = form.dataset.enabled === 'true';
        const status = await this.setWindowsStartup(enabled);
        this.closeModal(); this.render();
        this.toast('success', enabled ? 'Windows startup enabled' : 'Windows startup disabled', enabled ? 'Astro Account Manager will start for the current Windows user.' : 'Astro Account Manager will no longer start automatically.');
        if (status.needs_repair) this.toast('info', 'Windows startup needs attention', 'Windows accepted the change, but the startup registration still reports that it needs repair.');
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

        if (form.dataset.id) await this.bridge.call('update_account', form.dataset.id, values);
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
    if (input.id === 'game-filter') { this.state.gameQuery = input.value; this.filterGameRows(); return; }
    if (input.id === 'palette-input') { this.state.paletteQuery = input.value; this.renderOverlays(); const next = $('#palette-input'); if (next) { next.focus(); next.setSelectionRange(next.value.length, next.value.length); } }
    if (input.id === 'nexus-code-editor') { this.state.nexusExecutorCode = input.value; this.nexusSyncLineNumbers(); }
  }

  async handleChange(event) {
    const target = event.target;
    if (target.id === 'account-status') { this.state.accountStatus = target.value; this.render(); return; }
    if (target.id === 'nexus-exec-target') { this.state.nexusExecutorTarget = target.value; return; }
    if (target.dataset.setting) {
      const value = target.type === 'checkbox' ? target.checked : target.value;
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

  filterGameRows() {
    const phrase = this.state.gameQuery.trim().toLowerCase();
    $$('.game-card').forEach(function (element) {
      const game = this.state.games.find(function (item) { return String(item.place_id) === String(element.dataset.id); });
      if (!game) return;
      element.hidden = Boolean(phrase && ![game.title, game.creator, game.category].join(' ').toLowerCase().includes(phrase));
    }.bind(this));
  }

  navigate(route) {
    this.state.route = route;
    this.state.notificationsOpen = false;
    this.state.selected.clear();
    this.render();
    if (route === 'instances') void this.loadInstanceMonitor(false);
    if (route === 'settings' && this.state.settingsTab === 'general') void this.loadWindowsStartupStatus(false);
  }

  openModal(value) { this.state.modal = value; this.renderOverlays(); window.setTimeout(function () { const autofocus = $('[autofocus], .modal input'); if (autofocus) autofocus.focus(); }, 10); }
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
       if (Object.prototype.hasOwnProperty.call(values, 'watcher_termination_enabled')) {
         this.state.instanceMonitor = Object.assign({}, this.state.instanceMonitor, { termination_enabled: Boolean(values.watcher_termination_enabled) });
       }
       this.applyTheme(); this.render();
      if (announce !== false) this.toast('success', 'Settings saved', 'Your preference was applied.');
    } catch (error) { this.toast('error', 'Could not save settings', error.message); }
  }

  async launch(id, target) {
    const account = this.findAccount(id);
    if (!account) return;
    try {
      const launchTarget = target || (this.state.gameId ? { place_id: this.state.gameId } : null);
      await this.bridge.call('launch_account', id, launchTarget);
      await this.resync(); this.render(); this.toast('success', 'Launch requested', (account.display_name || account.username) + ' is being opened.');
    } catch (error) { this.toast('error', 'Could not launch account', error.message); }
  }

  async bulkLaunch() {
    const ids = Array.from(this.state.selected);
    if (!ids.length) return;
    if (!this.state.gameId) {
      this.toast('error', 'Choose an experience first', 'Open Games & servers, then select a game before launching accounts.');
      this.navigate('games');
      return;
    }
    try {
      for (const id of ids) await this.bridge.call('launch_account', id, { place_id: this.state.gameId });
      await this.resync(); this.state.selected.clear(); this.render(); this.toast('success', 'Launches requested', ids.length + ' accounts are opening.');
    } catch (error) { this.toast('error', 'Could not launch selected accounts', error.message); }
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
      const result = await Promise.all([this.bridge.call('get_game', targetId), this.bridge.call('list_servers', targetId)]);
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
    const account = this.state.accounts.find(function (item) { return item.status === 'ready'; }) || this.state.accounts[0];
    if (!server) return;
    if (!account) { this.toast('error', 'No account available', 'Add an account before joining a server.'); return; }
    await this.launch(account.id, { place_id: this.state.gameId, job_id: server.job_id, region: server.region });
  }

  async refreshInstances() {
    try {
      await this.bridge.call('refresh_instances');
      const monitor = await this.loadInstanceMonitor(false);
      if (!monitor) throw new Error('The local instance monitor did not return a status.');
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

  async copyText(value) {
    try {
      await navigator.clipboard.writeText(String(value)); this.toast('success', 'Copied Place ID', String(value) + ' is on your clipboard.');
    } catch (_) { this.toast('error', 'Clipboard unavailable', 'Select the Place ID manually to copy it.'); }
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
