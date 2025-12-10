# BioDaemon for Windows – tracks screen-lock breaks and reminds you to rest

import pystray
from PIL import Image
import threading
import time
import tkinter as tk
from tkinter import messagebox
import os
import queue
import ctypes
import sys

# --- SETTINGS ---
DEBUG_MODE = False  # When True, 1 second = 1 minute (useful for testing).

# Time thresholds for different “fatigue states”
LIMIT_ROUND = 45      # 0–45 min: safe
LIMIT_SLOUCH = 60     # 46–60 min: starting to strain
LIMIT_MELT = 70       # 61–70 min: posture degrading
LIMIT_FLAT = 80       # 71–80 min: you're basically a pancake
LIMIT_DEATH = 80      # Hard cap for fatigue counter

# How breaks restore "fatigue"
MIN_BREAK_TIME = 2       # Anything shorter doesn’t count as a break
FULL_RESET_TIME = 15     # Long breaks fully reset fatigue


class BioDaemon:
    def __init__(self):
        # Overall running state
        self.fatigue = 0
        self.state = "round"
        self.running = True

        # System tray interface
        self.icon = None
        self.gui_queue = queue.Queue()

        # Lock/unlock state tracking
        self.is_locked = False
        self.lock_start_time = 0.0

        # Internal WTS event handling details
        self._session_events = False
        self._wndproc = None            # Stored so Python doesn't GC the callback
        self._orig_wndproc = None       # Window procedure before we replaced it
        self._hwnd = None               # Tk window handle

        # Preload icons; use a red square as fallback
        self.images = {
            "round": self.load_image("round.png"),
            "slouch": self.load_image("slouch.png"),
            "melt": self.load_image("melt.png"),
            "flat": self.load_image("flat.png"),
            "tombstone": self.load_image("tombstone.png"),
        }

    # -------------------
    # Helper functions
    # -------------------
    def load_image(self, filename):
        """Load tray icon images; fall back to a red block if not found."""
        if os.path.exists(filename):
            return Image.open(filename)
        return Image.new("RGB", (64, 64), color="red")

    def safe_notify(self, title, body):
        """Send a system-tray notification; ignore backend quirks."""
        if self.icon:
            try:
                self.icon.notify(body, title)
            except Exception:
                pass

    def get_current_state(self):
        """Return the visual state name based on current fatigue level."""
        if self.fatigue < LIMIT_ROUND:
            return "round"
        elif self.fatigue < LIMIT_SLOUCH:
            return "slouch"
        elif self.fatigue < LIMIT_MELT:
            return "melt"
        elif self.fatigue < LIMIT_FLAT:
            return "flat"
        else:
            return "tombstone"

    def update_icon(self):
        """Switch tray icon whenever fatigue crosses state boundaries."""
        new_state = self.get_current_state()
        if new_state != self.state:
            self.state = new_state
            if self.icon:
                self.icon.icon = self.images[new_state]
                self.icon.menu = self.create_menu()
                try:
                    if hasattr(self.icon, "update_menu"):
                        self.icon.update_menu()
                except Exception:
                    pass

                if new_state == "tombstone":
                    self.safe_notify("RIP", " Pixel has died of neglect.")

    # -------------------
    # Fatigue & recovery
    # -------------------
    def calculate_healing(self, minutes_away):
        """
        Decide how much to restore based on break length.
        Short breaks = nothing, medium breaks = partial recovery,
        long breaks = total reset.
        """
        if minutes_away < MIN_BREAK_TIME:
            return 0
        if minutes_away >= FULL_RESET_TIME:
            return "FULL_RESET"
        if minutes_away < 5:
            return minutes_away * 2
        return minutes_away * 4

    def clamp_fatigue(self):
        """Keep fatigue within valid limits."""
        self.fatigue = max(0, min(self.fatigue, LIMIT_DEATH))

    def handle_unlock_heal(self, duration_seconds):
        """Apply recovery after unlocking the screen."""
        minutes_away = int(duration_seconds / (1 if DEBUG_MODE else 60))

        if self.fatigue < LIMIT_DEATH:
            heal_result = self.calculate_healing(minutes_away)

            if heal_result == "FULL_RESET":
                self.fatigue = 0
                self.safe_notify("Perfect Break", f"Fully Rested! You have {LIMIT_ROUND} mins of healthy work.")

            elif isinstance(heal_result, int) and heal_result > 0:
                self.fatigue = max(0, self.fatigue - heal_result)
                safe_minutes_left = max(0, LIMIT_ROUND - self.fatigue)
                self.safe_notify("Welcome Back", f"Recovered {heal_result} HP. You have {safe_minutes_left} mins of healthy work.")

        self.clamp_fatigue()
        self.update_icon()

    # -------------------
    # Windows lock/unlock integration
    # -------------------
    def install_session_notifications(self, root):
        """
        Hook into Windows session events so we know exactly when the screen
        is locked or unlocked. Falls back to polling if the system doesn't support it.
        """
        if sys.platform != "win32":
            return

        user32 = ctypes.windll.user32
        wtsapi32 = ctypes.windll.wtsapi32

        # ctypes aliases that work on both 32-bit and 64-bit Python
        HWND = ctypes.c_void_p
        UINT = ctypes.c_uint
        WPARAM = ctypes.c_size_t
        LPARAM = ctypes.c_ssize_t
        LRESULT = ctypes.c_ssize_t

        # Function prototypes for the Win32 APIs we call
        user32.GetWindowLongPtrW.restype = ctypes.c_void_p
        user32.GetWindowLongPtrW.argtypes = [HWND, ctypes.c_int]

        user32.SetWindowLongPtrW.restype = ctypes.c_void_p
        user32.SetWindowLongPtrW.argtypes = [HWND, ctypes.c_int, ctypes.c_void_p]

        user32.CallWindowProcW.restype = LRESULT
        user32.CallWindowProcW.argtypes = [ctypes.c_void_p, HWND, UINT, WPARAM, LPARAM]

        wtsapi32.WTSRegisterSessionNotification.restype = ctypes.c_bool
        wtsapi32.WTSRegisterSessionNotification.argtypes = [HWND, ctypes.c_uint]
        wtsapi32.WTSUnRegisterSessionNotification.restype = ctypes.c_bool
        wtsapi32.WTSUnRegisterSessionNotification.argtypes = [HWND]

        # Constants for session events
        WM_WTSSESSION_CHANGE = 0x02B1
        WTS_SESSION_LOCK = 0x7
        WTS_SESSION_UNLOCK = 0x8
        NOTIFY_FOR_THIS_SESSION = 0x0
        GWL_WNDPROC = -4

        # Get handle to the Tk window
        try:
            hwnd_int = root.winfo_id()
            self._hwnd = hwnd_int
            hwnd = HWND(hwnd_int)
        except Exception:
            self._hwnd = None
            return

        # Set up our replacement window procedure
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, UINT, WPARAM, LPARAM)

        orig_wndproc_ptr = user32.GetWindowLongPtrW(hwnd, GWL_WNDPROC)
        self._orig_wndproc = orig_wndproc_ptr

        @WNDPROC
        def py_wndproc(hWnd, msg, wParam, lParam):
            if msg == WM_WTSSESSION_CHANGE:
                if wParam == WTS_SESSION_LOCK:
                    self.is_locked = True
                    self.lock_start_time = time.time()
                elif wParam == WTS_SESSION_UNLOCK:
                    unlock_time = time.time()
                    self.is_locked = False
                    duration = unlock_time - self.lock_start_time if self.lock_start_time else 0
                    self.lock_start_time = 0
                    self.handle_unlock_heal(duration)

            if self._orig_wndproc:
                return user32.CallWindowProcW(self._orig_wndproc, hWnd, msg, wParam, lParam)
            return LRESULT(0)

        prev = user32.SetWindowLongPtrW(hwnd, GWL_WNDPROC, ctypes.cast(py_wndproc, ctypes.c_void_p))

        if prev:
            self._wndproc = py_wndproc
        else:
            self._wndproc = None
            self._orig_wndproc = None
            self._session_events = False
            return

        # Register for actual WTS notifications
        ok = wtsapi32.WTSRegisterSessionNotification(hwnd, NOTIFY_FOR_THIS_SESSION)
        if ok:
            self._session_events = True
        else:
            user32.SetWindowLongPtrW(hwnd, GWL_WNDPROC, ctypes.c_void_p(self._orig_wndproc))
            self._wndproc = None
            self._orig_wndproc = None
            self._session_events = False

    def uninstall_session_notifications(self):
        """Undo WTS registration and restore the previous window procedure."""
        if sys.platform != "win32":
            return
        try:
            user32 = ctypes.windll.user32
            wtsapi32 = ctypes.windll.wtsapi32

            HWND = ctypes.c_void_p
            if self._hwnd and self._session_events:
                wtsapi32.WTSUnRegisterSessionNotification(HWND(self._hwnd))

            if self._hwnd and self._orig_wndproc and self._wndproc:
                GWL_WNDPROC = -4
                user32.SetWindowLongPtrW(HWND(self._hwnd), GWL_WNDPROC, ctypes.c_void_p(self._orig_wndproc))
        except Exception:
            pass
        finally:
            self._session_events = False
            self._wndproc = None
            self._orig_wndproc = None
            self._hwnd = None

    # -------------------
    # Backup lock detection (used if WTS events fail)
    # -------------------
    def check_lock_state_fallback(self):
        """
        Check whether the desktop is locked by probing the active desktop
        or, if that fails, falling back to idle-time heuristics.
        """
        if sys.platform != "win32":
            return False

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        DESKTOP_READOBJECTS = 0x0001
        UOI_NAME = 2

        try:
            hDesk = user32.OpenInputDesktop(0, False, DESKTOP_READOBJECTS)
            if not hDesk:
                return True

            buf = (ctypes.c_wchar * 256)()
            size = ctypes.c_uint()
            ok = user32.GetUserObjectInformationW(hDesk, UOI_NAME, buf, ctypes.sizeof(buf), ctypes.byref(size))
            name = buf.value.lower() if ok else ""
            user32.CloseDesktop(hDesk)

            if name == "default":
                return False
            elif name in ("winlogon", "screensaver"):
                return True
            return True
        except Exception:
            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)

            if user32.GetLastInputInfo(ctypes.byref(lii)):
                get_tick = getattr(kernel32, "GetTickCount64", None)
                if get_tick is None:
                    get_tick = kernel32.GetTickCount
                get_tick.restype = ctypes.c_ulonglong

                tick = get_tick()
                idle_ms = tick - lii.dwTime
                threshold = 10_000 if DEBUG_MODE else 60_000
                return idle_ms >= threshold

            return False

    # -------------------
    # Tray menu callbacks
    # -------------------
    def action_resurrect(self, item):
        """Ask the GUI thread to show the “revive” prompt."""
        self.gui_queue.put("SHOW_RESURRECT_DIALOG")

    def on_exit(self, item):
        """Signal all threads to stop and shut down the tray icon."""
        self.running = False
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
        self.gui_queue.put("EXIT")

    def create_menu(self):
        """Build the tray menu depending on current fatigue."""
        if self.fatigue >= LIMIT_DEATH:
            return pystray.Menu(
                pystray.MenuItem(" DIED OF NEGLECT", lambda i: None, enabled=False),
                pystray.MenuItem(" PERFORM RITUAL", self.action_resurrect),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Exit", self.on_exit),
            )

        remaining = max(0, LIMIT_ROUND - self.fatigue)

        if self.fatigue < LIMIT_ROUND:
            status = f"Healthy: {remaining}m left"
        else:
            status = f"Warning: Overdue by {self.fatigue - LIMIT_ROUND}m"

        return pystray.Menu(
            pystray.MenuItem(status, lambda i: None, enabled=False),
            pystray.MenuItem(f"Fatigue: {self.fatigue}/{LIMIT_DEATH}", lambda i: None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Auto-Heal Active (Lock Screen)", lambda i: None, enabled=False),
            pystray.MenuItem("Exit", self.on_exit),
        )

    # -------------------
    # Background threads
    # -------------------
    def run_timer(self):
        """
        Main loop that increments fatigue over time and applies recovery.
        Uses event-driven lock detection when available, otherwise polling mode.
        """
        sleep_interval = 1 if DEBUG_MODE else 60

        while self.running:
            time.sleep(sleep_interval)

            if self._session_events:
                if not self.is_locked:
                    if self.fatigue < LIMIT_DEATH:
                        self.fatigue += 1
                self.update_icon()
            else:
                currently_locked = self.check_lock_state_fallback()

                if currently_locked:
                    if not self.is_locked:
                        self.is_locked = True
                        self.lock_start_time = time.time()
                else:
                    if self.is_locked:
                        self.is_locked = False
                        duration = time.time() - self.lock_start_time if self.lock_start_time else 0
                        self.lock_start_time = 0
                        self.handle_unlock_heal(duration)

                    if self.fatigue < LIMIT_DEATH:
                        self.fatigue += 1

                self.clamp_fatigue()
                self.update_icon()

    def run_tray(self):
        """Launch the tray icon."""
        self.icon = pystray.Icon("BioDaemon", self.images["round"], "Pixel", menu=self.create_menu())
        self.icon.run()

    def run_main_loop(self):
        """
        Spin up worker threads, handle GUI prompts, and initialize
        Windows lock/unlock tracking.
        """
        threading.Thread(target=self.run_timer, daemon=True).start()
        threading.Thread(target=self.run_tray, daemon=True).start()

        root = tk.Tk()
        root.withdraw()

        self.install_session_notifications(root)

        while self.running:
            try:
                msg = self.gui_queue.get(timeout=0.5)
                if msg == "SHOW_RESURRECT_DIALOG":
                    root.attributes("-topmost", True)
                    if messagebox.askokcancel(
                        " RESURRECTION",
                        "Manual Override Required.\nDo 20 Jumping Jacks to revive Pixel.",
                    ):
                        self.fatigue = 0
                        self.clamp_fatigue()
                        self.update_icon()
                    root.attributes("-topmost", False)

                elif msg == "EXIT":
                    self.running = False
                    break

            except queue.Empty:
                try:
                    root.update()
                except Exception:
                    pass

        self.uninstall_session_notifications()
        try:
            root.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    BioDaemon().run_main_loop()
