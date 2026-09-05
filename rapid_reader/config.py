# Rapid Reader configuration.
# Pins are BCM numbers, wired per the Waveshare Zero LCD HAT (A).
# See datasheets/README.md for the full physical-pin table.

# --- Screens ----------------------------------------------------------
# Screen 0: centre 1.3" 240x240 (ST7789VW) on SPI1 CE0 (needs
# `dtoverlay=spi1-1cs` in config.txt). Screens 1/2: 0.96" 80x160 (ST7735S)
# on SPI0 CE0/CE1, mounted portrait either side of the centre screen.
MAIN = dict(spi=(1, 0), dc=22, rst=27, bl=19, speed_hz=31_250_000)
LEFT = dict(spi=(0, 0), dc=4, rst=24, bl=13, speed_hz=15_625_000)
RIGHT = dict(spi=(0, 1), dc=5, rst=23, bl=12, speed_hz=15_625_000)

MAIN_W, MAIN_H = 240, 240
SIDE_W, SIDE_H = 80, 160

# Flip a screen 180 degrees if it renders upside down on your unit.
MAIN_ROTATE_180 = False
SIDE_ROTATE_180 = False
# Swap if the "left" card shows up on the right-hand screen.
SWAP_SIDES = False

GPIO_CHIP = 0            # /dev/gpiochip0 on a Pi Zero W
BACKLIGHT_PWM_HZ = 1000

# Backlight levels 0.0-1.0
BL_MAIN = 0.85
BL_SIDE = 0.55
BL_SIDE_READING = 0.22   # side cards are peripheral while reading

# Where boot.py finds the pre-rendered splash (see tools/make_splash.py)
SPLASH_DIR = "/opt/rapid-reader/splash"
# How long boot.py keeps retrying if /dev/spidev* or /dev/gpiochip0 are not
# ready yet (the service starts very early in boot).
HW_RETRY_SECS = 40.0

# --- Keys --------------------------------------------------------------
# Both keys sit on the right edge of the HAT, K1 above K2, active low.
PIN_KEY1 = 25   # "A": open / play / faster / forward
PIN_KEY2 = 26   # "B": down / back / slower / hold = library / power

# --- Paths -------------------------------------------------------------
BOOKS_DIR = "/home/reader/ebooks"
STATE_DIR = "/var/lib/rapid-reader"
STATE_FILE = STATE_DIR + "/state.json"

# --- Reading -----------------------------------------------------------
DEFAULT_WPM = 250
MIN_WPM = 60
MAX_WPM = 900
WPM_STEP = 25

# Words between periodic position saves while playing
SAVE_EVERY_WORDS = 100

# Starting estimate (seconds) of how long rendering + pushing a frame takes;
# step_word() recalibrates this at runtime from measurements. Words are only
# batched onto one frame when the requested pace outruns this.
PANEL_REFRESH_SECS = 0.05

# First directory that contains DejaVuSans.ttf wins (Debian, then Arch/others)
FONT_DIRS = ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/TTF",
             "/usr/share/fonts/dejavu")

# Multi-tap / hold timing (seconds)
TAP_WINDOW = 0.45
HOLD_TIME = 1.5
