import ctypes
from ctypes import wintypes
import psutil

user32 = ctypes.windll.user32

target_pid = None
for p in psutil.process_iter(['pid', 'name']):
    if (p.info['name'] or '').lower() == 'robloxplayerbeta.exe':
        target_pid = p.info['pid']
        break

print(f"Target Roblox PID: {target_pid}")

def enum_cb(hwnd, lparam):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == target_pid:
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        cls_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls_buf, 256)
        print(f"  Found HWND={hwnd}, Class='{cls_buf.value}', Title='{buf.value}', Visible={user32.IsWindowVisible(hwnd)}, Iconic={user32.IsIconic(hwnd)}")
    return True

CB_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows(CB_PROC(enum_cb), 0)
user32.EnumChildWindows(user32.GetDesktopWindow(), CB_PROC(enum_cb), 0)
