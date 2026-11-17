"""The themes a person can pick on the Theme page.

The colors themselves live in tailwind/input.css (compiled into
static/app.css). This file only lists which themes exist, in the order they
are shown, and each one's background color for the browser's toolbar.
"""

# key: (name, description, light background, dark background)
THEMES = {
    "sage": ("Sage", "The original: sage paper and green", "#F3F6F1", "#0D1613"),
    "indigo": ("Indigo", "Blue-purple on near-black", "#F7F8FF", "#06070F"),
    "violet": ("Violet", "Purple on near-black", "#FAF8FF", "#09070F"),
    "neon": ("Electric Purple", "Vivid purple, strongest glow", "#FBF7FF", "#07060B"),
    "orchid": ("Orchid", "Purple-pink", "#FEF8FF", "#0B070D"),
    "ocean": ("Ocean", "Black and cyan", "#F6F8FA", "#0B0B0B"),
    "gold": ("Amethyst Gold", "Purple-black with a warm gold accent", "#FCF9FF", "#0A070D"),
    "synth": ("Synthwave", "Deep violet, hot pink and cyan", "#FEF8FF", "#0B0614"),
    "teal": ("Nightshade", "Cool near-black with teal and a violet dot", "#F6FAFB", "#070910"),
    "ember": ("Ember Violet", "Plum-black with orange and rose", "#FFFAF7", "#0D0810"),
    "mist": ("Lavender Mist", "Soft, low-glare pastel lavender on charcoal", "#F7F5FC", "#131119"),
    "ultra": ("Ultraviolet", "Rich purple backgrounds instead of black", "#F6EFFF", "#12062B"),
    "ink": ("Mono Ink", "Minimal black and white with one violet touch", "#FFFFFF", "#060606"),
    "grape": ("Grape Soda", "Dark grape with a lime accent", "#F8F2FF", "#140A24"),
}
DEFAULT_THEME = "ember"

MODES = {"auto": "Match device", "light": "Light", "dark": "Dark"}
DEFAULT_MODE = "dark"
