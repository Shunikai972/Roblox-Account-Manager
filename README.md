# Astro Account Manager 🚀

A modern, high-performance Windows desktop application for managing Roblox accounts, multi-instance gaming sessions, FastFlags optimization (FPS Unlocker & Potato Graphics Mode), and live Lua execution via the Nexus WebSocket RPC Server.

[![Documentation Website](https://img.shields.io/badge/Docs-Interactive_Portal-purple.svg)](astro_docs/index.html)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-brightgreen.svg)](https://python.org)

---

## 🌟 Key Features

- **🔐 Windows DPAPI Encrypted Vault**: `.ROBLOSECURITY` session cookies are encrypted locally with native `Win32 DPAPI` (`CurrentUser`). Secrets are never logged or exposed in metadata.
- **🌐 Edge CDP Login Engine**: Automated Chromium DevTools Protocol login (port `9222`) that intercepts 100% of `HttpOnly` cookies and auto-closes on validation.
- **⚡ Potato Mode & FPS Unlocker**: Custom FastFlags engine modifying `ClientAppSettings.json` prior to launch to force minimum graphics, remove shadows/water/grass, and unlock 240+ FPS.
- **🚀 Nexus Lua Executor**: Integrated WebSocket server (port `5242`) for broadcasting scripts, managing teleports, and streaming live client `print()` logs (not functional yet).
- **🔌 Developer REST API (Port 7963)**: Complete REST compatibility layer providing endpoints for launching accounts, getting status, and triggering automation.

---

## 📖 Interactive Documentation

The full developer guide, architecture overview, and API reference are available on the standalone interactive portal:

👉 **[Launch Interactive Documentation Portal](astro_docs/index.html)**

- [Architecture & Security Overview](astro_docs/index.html#features)
- [FastFlags & Potato Graphics Configuration](astro_docs/index.html#potato-mode)
- [Nexus WebSocket RPC Protocol](astro_docs/index.html#nexus-executor)
- [Developer REST API Reference](astro_docs/index.html#developer-api)

---

## 🚀 Quickstart & Building

### Running from Source

```powershell
# Create & activate virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install dependencies & launch application
pip install -r requirements.txt
python main.py
```

### Running Test Suite

```powershell
python -m pytest
```

### Compiling Standalone Executable

```powershell
python scripts/build_windows.py
```
The compiled single-file binary will be generated at `dist/AstroAccountManager.exe`.

---

## 📜 License

Distributed under the **GPL-3.0 License**. See `LICENSE` for details.
