"""Reference Lua script template for Nexus client integration."""

import json
import re

NEXUS_LUA_SCRIPT = r"""-- Nexus Account Control Client Script for Astro Account Manager
-- Place this script in your executor auto-execute folder or run it on client launch.

local HttpService = game:GetService("HttpService")
local Players = game:GetService("Players")
local LocalPlayer = Players.LocalPlayer

local SERVER_HOST = "127.0.0.1"
local SERVER_PORT = 5242
local SERVER_TOKEN = ""
local RECONNECT_DELAY = 5

local function getWebSocket()
    if syn and syn.websocket then
        return syn.websocket
    elseif WebSocket and WebSocket.connect then
        return WebSocket
    elseif ws and ws.connect then
        return ws
    end
    return nil
end

local wsModule = getWebSocket()
if not wsModule then
    warn("[Nexus] No compatible WebSocket library found on executor.")
    return
end

local url = string.format("ws://%s:%d/Nexus?name=%s&id=%d&jobId=%s&token=%s",
    SERVER_HOST,
    SERVER_PORT,
    HttpService:UrlEncode(LocalPlayer.Name),
    LocalPlayer.UserId,
    HttpService:UrlEncode(game.JobId or ""),
    HttpService:UrlEncode(SERVER_TOKEN)
)

local socket = nil

local function sendPayload(name, payload)
    if socket then
        pcall(function()
            socket:Send(HttpService:JSONEncode({
                Name = name,
                Payload = payload
            }))
        end)
    end
end

local function connect()
    local success, err = pcall(function()
        socket = wsModule.connect(url)
    end)

    if not success or not socket then
        warn("[Nexus] Connection failed: " .. tostring(err))
        task.wait(RECONNECT_DELAY)
        return connect()
    end

    print("[Nexus] Connected to Astro Account Manager!")
    sendPayload("Log", "Connected from " .. LocalPlayer.Name)

    socket.OnMessage:Connect(function(msg)
        local ok, data = pcall(function() return HttpService:JSONDecode(msg) end)
        if ok and data and data.Name then
            local cmd = data.Name
            local payload = data.Payload

            if cmd == "execute" and type(payload) == "string" then
                print("[Nexus] Executing remote script...")
                local fn, loadErr = loadstring(payload)
                if fn then
                    task.spawn(fn)
                    sendPayload("Log", "Executed script successfully")
                else
                    sendPayload("Log", "Script error: " .. tostring(loadErr))
                end
            elseif cmd == "teleport" then
                print("[Nexus] Teleport command received: " .. tostring(payload))
                -- Handle teleport payload (PlaceId / JobId)
            elseif cmd == "mute" then
                game:GetService("SoundService").MainAudioGroup.Volume = 0
                sendPayload("Log", "Audio muted")
            elseif cmd == "unmute" then
                game:GetService("SoundService").MainAudioGroup.Volume = 1
                sendPayload("Log", "Audio unmuted")
            end
        end
    end)

    socket.OnClose:Connect(function()
        warn("[Nexus] Connection closed. Reconnecting...")
        task.wait(RECONNECT_DELAY)
        connect()
    end)

    -- Heartbeat loop
    task.spawn(function()
        while socket do
            task.wait(15)
            sendPayload("ping", {
                name = LocalPlayer.Name,
                id = LocalPlayer.UserId,
                jobId = game.JobId or "",
                placeId = game.PlaceId or 0
            })
        end
    end)
end

task.spawn(connect)
"""


def get_nexus_lua_script(host: str = "127.0.0.1", port: int = 5242, token: str = "") -> str:
    """Returns the customized Lua client script with host and port injected."""
    if not isinstance(host, str) or not re.fullmatch(r"[A-Za-z0-9.:-]{1,253}", host):
        raise ValueError("Nexus host is invalid.")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("Nexus port is invalid.")
    if not isinstance(token, str) or len(token) > 512 or any(ord(character) < 33 for character in token):
        if token:
            raise ValueError("Nexus token is invalid.")
    return (
        NEXUS_LUA_SCRIPT
        .replace('SERVER_HOST = "127.0.0.1"', f"SERVER_HOST = {json.dumps(host)}")
        .replace("SERVER_PORT = 5242", f"SERVER_PORT = {port}")
        .replace('SERVER_TOKEN = ""', f"SERVER_TOKEN = {json.dumps(token)}")
    )
