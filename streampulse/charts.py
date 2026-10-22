import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

COUNTRIES = ["IN", "US", "GB"]
COUNTRY_NAMES = {"IN": "India", "US": "United States", "GB": "United Kingdom"}
# Colorblind-checked order. A country keeps its color in every chart.
COUNTRY_COLORS = {"IN": "#2a78d6", "US": "#eb6834", "GB": "#1baf7a"}
SINGLE_SERIES_COLOR = "#2a78d6"
TYPE_COLORS = {"Movie": "#2a78d6", "TV Show": "#eb6834"}
BLUE_RAMP = LinearSegmentedColormap.from_list("blue_ramp", ["#fcfcfb", "#cde2fb", "#6da7ec", "#2a78d6", "#104281"])
SURFACE = "#fcfcfb"
SECONDARY_INK = "#52514e"


def apply_chart_style():
    """Set the shared matplotlib style: light surface, hairline grid behind the data, no top or right spines."""
    plt.rcParams.update({
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "axes.edgecolor": "#c3c2b7",
        "axes.labelcolor": SECONDARY_INK,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "axes.titlelocation": "left",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": "#e1e0d9",
        "grid.linewidth": 0.6,
        "xtick.color": "#898781",
        "ytick.color": "#898781",
        "legend.frameon": False,
        "lines.linewidth": 2,
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "DejaVu Sans"],
    })
