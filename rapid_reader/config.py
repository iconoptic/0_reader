# Rapid Reader configuration.
# Pins are BCM numbers for the 1.3" SH1106 OLED HAT (SPI0 CE0).

# --- OLED (SPI0 CE0) ------------------------------------------------
OLED_SPI = (0, 0)          # (bus, device) for spidev.SpiDev().open(*OLED_SPI)
OLED_DC = 24
OLED_RST = 25
OLED_SPEED_HZ = 4_000_000  # SH1106 spec max
OLED_W, OLED_H = 128, 64
OLED_COL_OFFSET = 2        # SH1106 has 132-col RAM, 128 visible columns
GPIO_CHIP = 0

# Single flag flips the panel 180 degrees *and* swaps the joystick's
# up/down/left/right mapping to match, so the physical "up" on the board
# is always logical "up" regardless of mounting orientation.
ROTATE_180 = True

# --- Keys (BCM, active low, pull-ups) -------------------------------
# K1/K3 and UP/PRESS swapped vs Waveshare docs: this HAT wires them reversed.
PIN_KEY1, PIN_KEY2, PIN_KEY3 = 16, 20, 21
PIN_JOY_UP, PIN_JOY_DOWN = 13, 19
PIN_JOY_LEFT, PIN_JOY_RIGHT = 5, 26
PIN_JOY_PRESS = 6

# name -> BCM pin; single source of truth for buttons.Input. Names are the
# canonical event names used everywhere else (see event tuple below).
PINS = {
    "up": PIN_JOY_UP, "down": PIN_JOY_DOWN,
    "left": PIN_JOY_LEFT, "right": PIN_JOY_RIGHT, "press": PIN_JOY_PRESS,
    "k1": PIN_KEY1, "k2": PIN_KEY2, "k3": PIN_KEY3,
}
# Keys that auto-repeat while held (list navigation); the rest fire "hold"
# once and do not repeat.
REPEATING_KEYS = ("up", "down", "left", "right")

# --- Input timing (seconds) -----------------------------------------
HOLD_DELAY = 0.5     # how long a key must be held before "hold" (or the
                      # first "repeat") fires
REPEAT_SECS = 0.12   # interval between "repeat" events while still held

# --- Paths (unchanged from the LCD build) ---------------------------
VERSION = "1.0.0-sh1106"
BOOKS_DIR = "/home/reader/ebooks"
STATE_DIR = "/var/lib/rapid-reader"
STATE_FILE = STATE_DIR + "/state.json"
SPLASH_DIR = "/opt/rapid-reader/splash"
HW_RETRY_SECS = 40.0

# --- OTA (host sync stages under STATE_DIR/ota/) ---------------------
# See docs/plan_1/phase-0-ota-contracts.md for the full state machine.
OTA_DIR = STATE_DIR + "/ota"
OTA_INCOMING = OTA_DIR + "/incoming"
OTA_PENDING = OTA_DIR + "/pending"
# Written by the app when an apply attempt fails; read by _check_ota so a
# failed attempt is never auto-retried. Cleared by host sync when it arms
# the next update, not by the app itself.
OTA_FAILED = OTA_DIR + "/failed"
# "<current>/<total> <stage>", rewritten atomically by the helper as it
# progresses (phase-0-ota-contracts.md §5); OtaScreen polls it instead of
# animating a synthetic percentage.
OTA_PROGRESS = OTA_DIR + "/progress"
OTA_APPLY = "/usr/local/sbin/rapid-reader-ota-apply"
# Hard cap from helper spawn to a forced kill; see §5 "helper never
# returns". Generous for a whole-tree copy on a Pi Zero W's local
# storage, but finite so a wedged helper cannot hold the non-dismissible
# in-progress screen forever.
OTA_TIMEOUT_SECS = 120.0

# --- Reading ---------------------------------------------------------
DEFAULT_WPM = 250
MIN_WPM = 60
MAX_WPM = 900
WPM_STEP = 25
SAVE_EVERY_WORDS = 100
PANEL_REFRESH_SECS = 0.02   # SH1106 full frame ~5ms @ 4MHz; seed low

# --- Idle / burn-in protection ---------------------------------------
IDLE_DIM_SECS = 60      # no input for this long outside READING -> dim
IDLE_OFF_SECS = 300     # no input for this long -> display off (sleep)
IDLE_DIM_CONTRAST = 0x20
IDLE_ACTIVE_CONTRAST = 0xCF

# --- Fonts -------------------------------------------------------------
FONT_DIRS = ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/TTF",
             "/usr/share/fonts/dejavu")
# Bundled font faces theme.py maps to font_key: "sans" | "serif" | "mono".
# Sans reuses DejaVu (already required); serif/mono need a package added in
# Phase 3 — see that phase doc for the exact package name/paths.
FONT_FACES = {
    "sans": ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
    "serif": ("DejaVuSerif.ttf", "DejaVuSerif-Bold.ttf"),
    "mono": ("DejaVuSansMono.ttf", "DejaVuSansMono-Bold.ttf"),
}

# --- Settings (state v2 defaults; state.py imports this) --------------
SETTINGS_DEFAULTS = {
    "wpm": DEFAULT_WPM,
    "theme": "night",          # key into theme.THEMES
    "pivot_style": "ticks",    # ticks | underline | box | bold
    "word_size": "medium",     # small | medium | large
}
