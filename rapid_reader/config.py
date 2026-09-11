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
ROTATE_180 = False

# --- Keys (BCM, active low, pull-ups) -------------------------------
PIN_KEY1, PIN_KEY2, PIN_KEY3 = 21, 20, 16
PIN_JOY_UP, PIN_JOY_DOWN = 6, 19
PIN_JOY_LEFT, PIN_JOY_RIGHT = 5, 26
PIN_JOY_PRESS = 13

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
BOOKS_DIR = "/home/reader/ebooks"
STATE_DIR = "/var/lib/rapid-reader"
STATE_FILE = STATE_DIR + "/state.json"
SPLASH_DIR = "/opt/rapid-reader/splash"
HW_RETRY_SECS = 40.0

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

# --- Temporary: LCD HAT (remove in Phases 1A / 1B / 2) ----------------
# Kept so current lcd/display/render/buttons/main and their tests keep
# importing until those modules are rewritten. Not part of the SH1106
# contract in docs/plan/phase-0-contracts.md.
MAIN = dict(spi=(1, 0), dc=22, rst=27, bl=19, speed_hz=31_250_000)
LEFT = dict(spi=(0, 0), dc=4, rst=24, bl=13, speed_hz=15_625_000)
RIGHT = dict(spi=(0, 1), dc=5, rst=23, bl=12, speed_hz=15_625_000)
MAIN_W, MAIN_H = 240, 240
SIDE_W, SIDE_H = 80, 160
MAIN_ROTATE_180 = False
SIDE_ROTATE_180 = False
SWAP_SIDES = False
BACKLIGHT_PWM_HZ = 1000
BL_MAIN = 0.85
BL_SIDE = 0.55
BL_SIDE_READING = 0.22
TAP_WINDOW = 0.45
HOLD_TIME = 1.5
