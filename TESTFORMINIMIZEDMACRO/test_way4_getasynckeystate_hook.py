import os
import time
import ctypes
from ctypes import wintypes
from pathlib import Path

import psutil
import vgamepad as vg


# ============================================================
# CONFIG
# ============================================================

ROBLOX_EXE = "RobloxPlayerBeta.exe"

# 1 = première manette XInput
CONTROLLER_INDEX = 1

# Durée du test de déplacement
MOVE_DURATION = 5

# Si tu connais directement le dossier contenant
# ProtoInputLoader64.dll et ProtoInputHooks64.dll,
# mets-le ici.
#
# Exemple :
# MANUAL_PROTO_DIR = r"C:\NucleusCoop\utils"
#
# Sinon laisse None pour recherche automatique.
MANUAL_PROTO_DIR = None


# ============================================================
# IDs DES HOOKS PROTOINPUT
# ============================================================

REGISTER_RAW_INPUT_HOOK = 0
GET_RAW_INPUT_DATA_HOOK = 1
MESSAGE_FILTER_HOOK = 2
GET_CURSOR_POS_HOOK = 3
SET_CURSOR_POS_HOOK = 4
GET_KEY_STATE_HOOK = 5
GET_ASYNC_KEY_STATE_HOOK = 6
GET_KEYBOARD_STATE_HOOK = 7
CURSOR_VISIBILITY_HOOK = 8
CLIP_CURSOR_HOOK = 9
FOCUS_HOOKS_HOOK = 10
RENAME_HANDLES_HOOK = 11
XINPUT_HOOK = 12
DINPUT_ORDER_HOOK = 13
SET_WINDOW_POS_HOOK = 14
BLOCK_RAW_INPUT_HOOK = 15
FIND_WINDOW_HOOK = 16
CREATE_SINGLE_HID_HOOK = 17
WINDOW_STYLE_HOOK = 18


# ============================================================
# TROUVER PROTOINPUT
# ============================================================

def find_protoinput():
    loader_name = "ProtoInputLoader64.dll"
    hooks_name = "ProtoInputHooks64.dll"

    if MANUAL_PROTO_DIR:
        directory = Path(MANUAL_PROTO_DIR)

        loader = directory / loader_name
        hooks = directory / hooks_name

        if not loader.exists():
            raise FileNotFoundError(
                f"{loader_name} introuvable dans :\n{directory}"
            )

        if not hooks.exists():
            raise FileNotFoundError(
                f"{hooks_name} introuvable dans :\n{directory}"
            )

        return str(directory)

    print("[*] Recherche de ProtoInput...")

    home = Path.home()

    possible_roots = [
        Path(r"C:\NucleusCoop"),
        Path(r"C:\Nucleus-Coop"),
        Path(r"C:\Nucleus"),
        Path(r"D:\NucleusCoop"),
        Path(r"D:\Nucleus-Coop"),
        Path(r"D:\Nucleus"),
        home / "Downloads",
        home / "Desktop",
    ]

    for root in possible_roots:

        if not root.exists():
            continue

        print(f"    Recherche dans {root}")

        try:
            for loader_path in root.rglob(loader_name):

                directory = loader_path.parent
                hooks_path = directory / hooks_name

                if hooks_path.exists():

                    print()
                    print("[+] ProtoInput trouvé !")
                    print(f"    Loader : {loader_path}")
                    print(f"    Hooks  : {hooks_path}")
                    print()

                    return str(directory)

        except (PermissionError, OSError):
            pass

    raise FileNotFoundError(
        "\nImpossible de trouver ProtoInput.\n\n"
        "Il faut un dossier contenant ENSEMBLE :\n"
        "  ProtoInputLoader64.dll\n"
        "  ProtoInputHooks64.dll\n\n"
        "Tu peux aussi indiquer manuellement le dossier avec :\n"
        'MANUAL_PROTO_DIR = r"C:\\chemin\\vers\\ProtoInput"'
    )


# ============================================================
# TROUVER ROBLOX
# ============================================================

def find_roblox_pid():

    roblox_processes = []

    for proc in psutil.process_iter(["pid", "name"]):

        try:

            name = proc.info["name"]

            if not name:
                continue

            if name.lower() == ROBLOX_EXE.lower():

                roblox_processes.append(
                    (
                        proc.info["pid"],
                        name
                    )
                )

        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied
        ):
            pass

    if not roblox_processes:
        raise RuntimeError(
            f"{ROBLOX_EXE} introuvable.\n"
            "Lance Roblox et entre dans une partie avant le script."
        )

    print("[+] Processus Roblox détecté(s) :")

    for pid, name in roblox_processes:
        print(f"    PID {pid} | {name}")

    # Si plusieurs Roblox tournent,
    # prend le premier pour ce test.
    return roblox_processes[0][0]


# ============================================================
# CHARGEMENT PROTOINPUT
# ============================================================

def load_protoinput(proto_dir):

    loader_path = os.path.join(
        proto_dir,
        "ProtoInputLoader64.dll"
    )

    hooks_path = os.path.join(
        proto_dir,
        "ProtoInputHooks64.dll"
    )

    if not os.path.isfile(loader_path):
        raise FileNotFoundError(loader_path)

    if not os.path.isfile(hooks_path):
        raise FileNotFoundError(hooks_path)

    # Permet à Windows de charger les DLL dépendantes.
    os.add_dll_directory(proto_dir)

    print("[+] Chargement de ProtoInputLoader64.dll")

    loader = ctypes.WinDLL(loader_path)

    # --------------------------------------------------------
    # EasyHookInjectRuntime
    # --------------------------------------------------------

    loader.EasyHookInjectRuntime.argtypes = [
        wintypes.DWORD,
        ctypes.c_wchar_p
    ]

    loader.EasyHookInjectRuntime.restype = ctypes.c_uint

    # --------------------------------------------------------
    # InstallHook
    # --------------------------------------------------------

    loader.InstallHook.argtypes = [
        ctypes.c_uint,
        ctypes.c_uint
    ]

    loader.InstallHook.restype = None

    # --------------------------------------------------------
    # SetupState
    # --------------------------------------------------------

    loader.SetupState.argtypes = [
        ctypes.c_uint,
        ctypes.c_int
    ]

    loader.SetupState.restype = None

    # --------------------------------------------------------
    # UpdateMainWindowHandle
    # --------------------------------------------------------

    loader.UpdateMainWindowHandle.argtypes = [
        ctypes.c_uint,
        ctypes.c_uint64
    ]

    loader.UpdateMainWindowHandle.restype = None

    # --------------------------------------------------------
    # SetControllerIndex
    # --------------------------------------------------------

    loader.SetControllerIndex.argtypes = [
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.c_uint
    ]

    loader.SetControllerIndex.restype = None

    # --------------------------------------------------------
    # StartFocusMessageLoop
    # --------------------------------------------------------

    loader.StartFocusMessageLoop.argtypes = [
        ctypes.c_uint,    # instance
        ctypes.c_int,     # ms
        ctypes.c_bool,    # WM_ACTIVATE
        ctypes.c_bool,    # WM_ACTIVATEAPP
        ctypes.c_bool,    # WM_NCACTIVATE
        ctypes.c_bool,    # WM_SETFOCUS
        ctypes.c_bool     # WM_MOUSEACTIVATE
    ]

    loader.StartFocusMessageLoop.restype = None

    # --------------------------------------------------------
    # StopFocusMessageLoop
    # --------------------------------------------------------

    loader.StopFocusMessageLoop.argtypes = [
        ctypes.c_uint
    ]

    loader.StopFocusMessageLoop.restype = None

    # --------------------------------------------------------
    # WakeUpProcess
    # --------------------------------------------------------

    loader.WakeUpProcess.argtypes = [
        ctypes.c_uint
    ]

    loader.WakeUpProcess.restype = None

    return loader


# ============================================================
# INJECTION DANS ROBLOX
# ============================================================

def setup_protoinput(loader, proto_dir, pid):

    print()
    print(
        f"[+] Injection ProtoInput dans Roblox "
        f"(PID {pid})..."
    )

    proto_handle = loader.EasyHookInjectRuntime(
        pid,
        proto_dir
    )

    if proto_handle == 0:
        raise RuntimeError(
            "EasyHookInjectRuntime a renvoyé 0.\n"
            "L'injection ProtoInput a échoué."
        )

    print(
        f"[+] Injection réussie, handle ProtoInput = "
        f"{proto_handle}"
    )

    time.sleep(1)

    # Instance #1
    loader.SetupState(
        proto_handle,
        1
    )

    # Roblox doit utiliser la première manette XInput.
    #
    # IMPORTANT :
    # ProtoInput veut que SetControllerIndex soit appelé
    # AVANT InstallHook(XINPUT_HOOK).
    loader.SetControllerIndex(
        proto_handle,
        CONTROLLER_INDEX,
        0,
        0,
        0
    )

    print(
        f"[+] Contrôleur XInput "
        f"{CONTROLLER_INDEX} assigné"
    )

    # Hook XInput
    loader.InstallHook(
        proto_handle,
        XINPUT_HOOK
    )

    print("[+] Hook XInput installé")

    # Hook permettant de falsifier certaines informations
    # concernant le focus.
    loader.InstallHook(
        proto_handle,
        FOCUS_HOOKS_HOOK
    )

    print("[+] Hook de focus installé")

    # Recherche automatique de la fenêtre principale Roblox.
    loader.UpdateMainWindowHandle(
        proto_handle,
        0
    )

    # Envoie continuellement les messages donnant l'impression
    # que Roblox conserve son focus.
    loader.StartFocusMessageLoop(
        proto_handle,
        5,
        True,   # WM_ACTIVATE
        True,   # WM_ACTIVATEAPP
        True,   # WM_NCACTIVATE
        True,   # WM_SETFOCUS
        True    # WM_MOUSEACTIVATE
    )

    print("[+] Faux focus démarré")

    # Au cas où certains threads seraient suspendus
    # pendant l'injection.
    loader.WakeUpProcess(
        proto_handle
    )

    return proto_handle


# ============================================================
# MANETTE VIRTUELLE
# ============================================================

def create_virtual_gamepad():

    print()
    print("[+] Création de la manette Xbox 360 virtuelle...")

    gamepad = vg.VX360Gamepad()

    gamepad.reset()
    gamepad.update()

    time.sleep(0.5)

    # Petit appui sur A afin que le jeu voie immédiatement
    # une activité provenant du contrôleur.
    gamepad.press_button(
        button=vg.XUSB_BUTTON.XUSB_GAMEPAD_A
    )

    gamepad.update()

    time.sleep(0.1)

    gamepad.release_button(
        button=vg.XUSB_BUTTON.XUSB_GAMEPAD_A
    )

    gamepad.update()

    print("[+] Manette virtuelle prête")

    return gamepad


# ============================================================
# COMMANDES ROBLOX
# ============================================================

def stop_movement(gamepad):

    gamepad.left_joystick_float(
        x_value_float=0.0,
        y_value_float=0.0
    )

    gamepad.update()


def move_forward(gamepad, duration=5):

    print()
    print(
        f"[TEST] Marche AVANT pendant "
        f"{duration} secondes..."
    )

    gamepad.left_joystick_float(
        x_value_float=0.0,
        y_value_float=1.0
    )

    gamepad.update()

    time.sleep(duration)

    stop_movement(gamepad)

    print("[TEST] Stick relâché")


def move_backward(gamepad, duration=1):

    gamepad.left_joystick_float(
        x_value_float=0.0,
        y_value_float=-1.0
    )

    gamepad.update()

    time.sleep(duration)

    stop_movement(gamepad)


def move_left(gamepad, duration=1):

    gamepad.left_joystick_float(
        x_value_float=-1.0,
        y_value_float=0.0
    )

    gamepad.update()

    time.sleep(duration)

    stop_movement(gamepad)


def move_right(gamepad, duration=1):

    gamepad.left_joystick_float(
        x_value_float=1.0,
        y_value_float=0.0
    )

    gamepad.update()

    time.sleep(duration)

    stop_movement(gamepad)


def jump(gamepad):

    gamepad.press_button(
        button=vg.XUSB_BUTTON.XUSB_GAMEPAD_A
    )

    gamepad.update()

    time.sleep(0.1)

    gamepad.release_button(
        button=vg.XUSB_BUTTON.XUSB_GAMEPAD_A
    )

    gamepad.update()


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print(" ROBLOX BACKGROUND / MINIMIZED INPUT TEST")
    print("=" * 60)
    print()

    # --------------------------------------------------------
    # 1. Trouver ProtoInput
    # --------------------------------------------------------

    proto_dir = find_protoinput()

    print(f"[+] Dossier ProtoInput : {proto_dir}")

    # --------------------------------------------------------
    # 2. Trouver Roblox
    # --------------------------------------------------------

    pid = find_roblox_pid()

    print(f"[+] Roblox choisi : PID {pid}")

    # --------------------------------------------------------
    # 3. Créer la manette AVANT d'installer le hook XInput
    # --------------------------------------------------------

    gamepad = create_virtual_gamepad()

    # --------------------------------------------------------
    # 4. Charger ProtoInput
    # --------------------------------------------------------

    loader = load_protoinput(
        proto_dir
    )

    # --------------------------------------------------------
    # 5. Injection
    # --------------------------------------------------------

    proto_handle = setup_protoinput(
        loader,
        proto_dir,
        pid
    )

    print()
    print("=" * 60)
    print("[+] CONFIGURATION TERMINÉE")
    print("=" * 60)

    print()
    print("Mets maintenant Roblox derrière une autre fenêtre.")
    print("Tu peux ouvrir Chrome/Discord et utiliser ton PC.")
    print()
    print("Le test démarre dans 5 secondes...")
    print()

    time.sleep(5)

    # --------------------------------------------------------
    # TEST
    # --------------------------------------------------------

    move_forward(
        gamepad,
        MOVE_DURATION
    )

    print()
    print("=" * 60)
    print("TEST TERMINÉ")
    print("=" * 60)

    gamepad.reset()
    gamepad.update()

    # Arrête seulement la boucle de faux focus.
    # Les hooks resteront jusqu'à fermeture de Roblox.
    try:
        loader.StopFocusMessageLoop(
            proto_handle
        )
    except Exception:
        pass


# ============================================================
# LANCEMENT
# ============================================================

if __name__ == "__main__":

    gamepad = None

    try:

        main()

    except KeyboardInterrupt:

        print()
        print("[!] Arrêt demandé.")

    except Exception as e:

        print()
        print("=" * 60)
        print("ERREUR")
        print("=" * 60)
        print()
        print(repr(e))
        print()
        print(str(e))

    finally:

        print()
        input("Appuie sur Entrée pour fermer...")