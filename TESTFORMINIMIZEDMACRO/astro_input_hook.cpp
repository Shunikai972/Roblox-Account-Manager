// ============================================================================
// AstroInput Native Hook DLL (C++ Source)
// Hooking GetAsyncKeyState, GetKeyState, GetKeyboardState, GetCursorPos, WM_INPUT
// ============================================================================

#include <windows.h>
#include <iostream>

// Virtual Key state table for this target instance (256 keys)
static BYTE g_VirtualKeyState[256] = { 0 };
static POINT g_VirtualCursorPos = { 960, 540 }; // Default client center

// Original API Function Pointers
typedef SHORT(WINAPI* pfnGetAsyncKeyState)(int vKey);
typedef SHORT(WINAPI* pfnGetKeyState)(int nVirtKey);
typedef BOOL(WINAPI* pfnGetKeyboardState)(PBYTE lpKeyState);
typedef BOOL(WINAPI* pfnGetCursorPos)(LPPOINT lpPoint);

static pfnGetAsyncKeyState g_OriginalGetAsyncKeyState = NULL;
static pfnGetKeyState g_OriginalGetKeyState = NULL;
static pfnGetKeyboardState g_OriginalGetKeyboardState = NULL;
static pfnGetCursorPos g_OriginalGetCursorPos = NULL;

// Detour Functions
SHORT WINAPI HookedGetAsyncKeyState(int vKey) {
    if (vKey >= 0 && vKey < 256) {
        if (g_VirtualKeyState[vKey] & 0x80) {
            return (SHORT)0x8001; // Key is DOWN + pressed since last call
        }
    }
    if (g_OriginalGetAsyncKeyState) {
        return g_OriginalGetAsyncKeyState(vKey);
    }
    return 0;
}

SHORT WINAPI HookedGetKeyState(int nVirtKey) {
    if (nVirtKey >= 0 && nVirtKey < 256) {
        if (g_VirtualKeyState[nVirtKey] & 0x80) {
            return (SHORT)0x8000;
        }
    }
    if (g_OriginalGetKeyState) {
        return g_OriginalGetKeyState(nVirtKey);
    }
    return 0;
}

BOOL WINAPI HookedGetKeyboardState(PBYTE lpKeyState) {
    if (!lpKeyState) return FALSE;
    if (g_OriginalGetKeyboardState) {
        g_OriginalGetKeyboardState(lpKeyState);
    }
    // Overlay virtual key state table for this instance
    for (int i = 0; i < 256; i++) {
        if (g_VirtualKeyState[i] & 0x80) {
            lpKeyState[i] |= 0x80;
        }
    }
    return TRUE;
}

BOOL WINAPI HookedGetCursorPos(LPPOINT lpPoint) {
    if (!lpPoint) return FALSE;
    lpPoint->x = g_VirtualCursorPos.x;
    lpPoint->y = g_VirtualCursorPos.y;
    return TRUE;
}

// IPC Interface for AstroInput Broker Commands
extern "C" __declspec(dllexport) void SetVirtualKey(int vk, bool isDown) {
    if (vk >= 0 && vk < 256) {
        if (isDown) {
            g_VirtualKeyState[vk] = 0x80;
        } else {
            g_VirtualKeyState[vk] = 0x00;
        }
    }
}

extern "C" __declspec(dllexport) void SetVirtualCursor(int x, int y) {
    g_VirtualCursorPos.x = x;
    g_VirtualCursorPos.y = y;
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD ul_reason_for_call, LPVOID lpReserved) {
    switch (ul_reason_for_call) {
    case DLL_PROCESS_ATTACH:
        DisableThreadLibraryCalls(hModule);
        // Setup original pointers
        g_OriginalGetAsyncKeyState = (pfnGetAsyncKeyState)GetProcAddress(GetModuleHandleA("user32.dll"), "GetAsyncKeyState");
        g_OriginalGetKeyState = (pfnGetKeyState)GetProcAddress(GetModuleHandleA("user32.dll"), "GetKeyState");
        g_OriginalGetKeyboardState = (pfnGetKeyboardState)GetProcAddress(GetModuleHandleA("user32.dll"), "GetKeyboardState");
        g_OriginalGetCursorPos = (pfnGetCursorPos)GetProcAddress(GetModuleHandleA("user32.dll"), "GetCursorPos");
        break;
    case DLL_PROCESS_DETACH:
        break;
    }
    return TRUE;
}
