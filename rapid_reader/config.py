# Rapid Reader configuration.
# Pins are BCM numbers, wired per the Adafruit 2.13" e-Ink Bonnet (#4687).

PIN_DC = 22
PIN_RST = 27
PIN_BUSY = 17
PIN_BTN_5 = 6   # wired to bonnet's "6" button (unit is mounted upside down)
PIN_BTN_6 = 5   # wired to bonnet's "5" button (unit is mounted upside down)
SPI_BUS = 0
SPI_DEV = 0     # CE0

EPD_WIDTH = 250   # landscape
EPD_HEIGHT = 122
ROTATE_180 = False  # set True if the screen renders upside down

BOOKS_DIR = "/home/reader/ebooks"
STATE_DIR = "/var/lib/rapid-reader"
STATE_FILE = STATE_DIR + "/state.json"

DEFAULT_WPM = 150
MIN_WPM = 60
MAX_WPM = 450
WPM_STEP = 25

# Words between periodic position saves while playing (~40s at 150 wpm)
SAVE_EVERY_WORDS = 100

# Partial refreshes between forced full refreshes (controls ghosting buildup)
FULL_REFRESH_EVERY = 60

# Starting estimate (seconds) of how long a partial refresh takes; step_word()
# recalibrates this at runtime from actual measured refresh times.
PANEL_REFRESH_SECS = 0.35

# First directory that contains DejaVuSans.ttf wins (Debian, then Arch/others)
FONT_DIRS = ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/TTF",
             "/usr/share/fonts/dejavu")

# Multi-tap / hold timing (seconds)
TAP_WINDOW = 0.45
HOLD_TIME = 1.5
