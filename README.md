# Astro Account Manager 🚀

A modern, high-performance Windows desktop application for managing Roblox accounts, multi-instance gaming sessions, FastFlags optimization (FPS Unlocker & Potato Graphics Mode), and live Lua execution via the Nexus WebSocket RPC Server.

[![Documentation Website](https://img.shields.io/badge/Docs-Live_GitHub_Pages-purple.svg)](https://shunikai972.github.io/Account-Manager-Doc/)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-brightgreen.svg)](https://python.org)

---

## 🌟 Key Features

- **🔐 Windows DPAPI Encrypted Vault**: `.ROBLOSECURITY` session cookies are encrypted locally with native `Win32 DPAPI` (`CurrentUser`). Secrets are never logged or exposed in metadata.
- **🌐 Edge CDP Login Engine**: Automated Chromium DevTools Protocol login (port `9222`) that intercepts 100% of `HttpOnly` cookies and auto-closes on validation.
- **⚡ Potato Mode & FPS Unlocker**: Custom FastFlags engine modifying `ClientAppSettings.json` prior to launch to force minimum graphics, remove shadows/water/grass, and unlock 240+ FPS.
- **🚀 Nexus Lua Executor**: Integrated WebSocket server (port `5242`) for broadcasting scripts, managing teleports, and streaming live client `print()` logs.
- **🔌 Developer REST API (Port 7963)**: Complete REST compatibility layer providing endpoints for launching accounts, getting status, and triggering automation.

---

## 📖 Live Documentation Portal

The full developer guide, architecture overview, and API reference are hosted live on GitHub Pages:

👉 **[Launch Live Documentation Portal (GitHub Pages)](https://shunikai972.github.io/Account-Manager-Doc/)**

- [Architecture & Security Overview](https://shunikai972.github.io/Account-Manager-Doc/#features)
- [FastFlags & Potato Graphics Configuration](https://shunikai972.github.io/Account-Manager-Doc/#potato-mode)
- [Nexus WebSocket RPC Protocol](https://shunikai972.github.io/Account-Manager-Doc/#nexus-executor)
- [Developer REST API Reference](https://shunikai972.github.io/Account-Manager-Doc/#developer-api)
- [Documentation GitHub Repository](https://github.com/Shunikai972/Account-Manager-Doc)

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
The compiled single-file binary will be generated at `dist/AstroAccountManager.exe` and `release/AstroAccountManager.exe`.

---

## 📜 License

Distributed under the **GPL-3.0 License**. See [LICENSE](LICENSE) for details.
