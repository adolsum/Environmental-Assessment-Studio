"""Earth Engine analysis and export helpers for the plugin."""

from __future__ import annotations

import importlib
import hashlib
import json
import math
import re
import site
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import processing
from qgis.PyQt.QtGui import QColor
from qgis.core import (
    Qgis,
    QgsColorRampShader,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsDistanceArea,
    QgsField,
    QgsFeatureRequest,
    QgsGeometry,
    QgsPalettedRasterRenderer,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
    QgsRasterRange,
    QgsRasterShader,
    QgsSingleBandPseudoColorRenderer,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant

from .dependency_manager import DependencyManager
from .export_utils import create_trend_plot, write_table_bundle

try:
    import ee
except Exception:  # pragma: no cover - optional dependency in QGIS env
    ee = None


LULC_CLASS_NAMES = {
    0: "Water",
    1: "Trees",
    2: "Grass",
    3: "Flooded vegetation",
    4: "Crops",
    5: "Shrub and scrub",
    6: "Built area",
    7: "Bare ground",
    8: "Snow and ice",
}

LULC_CLASS_COLORS = {
    0: "#419bdf",
    1: "#397d49",
    2: "#88b053",
    3: "#7a87c6",
    4: "#e49635",
    5: "#dfc35a",
    6: "#c4281b",
    7: "#a59b8f",
    8: "#b39fe1",
}

DYNAMIC_WORLD_PROBABILITY_BANDS = [
    "water",
    "trees",
    "grass",
    "flooded_vegetation",
    "crops",
    "shrub_and_scrub",
    "built",
    "bare",
    "snow_and_ice",
]

LULC_LANDSAT_CLASS_NAMES = {
    0: "Water",
    1: "Dense vegetation",
    2: "Open vegetation / agriculture",
    3: "Built-up",
    4: "Bare ground",
}

LULC_LANDSAT_CLASS_COLORS = {
    0: "#2b6cb0",
    1: "#166534",
    2: "#eab308",
    3: "#dc2626",
    4: "#caa472",
}

LANDSAT_HISTORICAL_MIN_YEAR = 2013
LANDSAT_LULC_FEATURE_BANDS = [
    "green",
    "red",
    "nir",
    "swir1",
    "NDVI",
    "NDMI",
    "NDBI",
]

LANDSAT_RAW_STACK_BANDS = [
    "blue",
    "green",
    "red",
    "nir",
    "swir1",
    "thermal",
    "NDVI",
    "NDWI",
    "NDMI",
    "NDBI",
    "LST_C",
]

SENTINEL_PROCESSED_STACK_BANDS = [
    "blue",
    "green",
    "red",
    "red_edge1",
    "red_edge2",
    "red_edge3",
    "nir",
    "nir_narrow",
    "swir1",
    "swir2",
    "NDVI",
    "NDWI",
    "NDBI",
]

SENTINEL_PROCESSED_STACK_SCALE = 20

MODIS_LULC_CLASS_NAMES = {
    1: "Evergreen needleleaf forest",
    2: "Evergreen broadleaf forest",
    3: "Deciduous needleleaf forest",
    4: "Deciduous broadleaf forest",
    5: "Mixed forests",
    6: "Closed shrublands",
    7: "Open shrublands",
    8: "Woody savannas",
    9: "Savannas",
    10: "Grasslands",
    11: "Permanent wetlands",
    12: "Croplands",
    13: "Urban and built-up",
    14: "Cropland / natural vegetation mosaic",
    15: "Permanent snow and ice",
    16: "Barren",
    17: "Water bodies",
}

MODIS_LULC_CLASS_COLORS = {
    1: "#05450a",
    2: "#086a10",
    3: "#54a708",
    4: "#78d203",
    5: "#009900",
    6: "#c6b044",
    7: "#dcd159",
    8: "#dade48",
    9: "#fbff13",
    10: "#b6ff05",
    11: "#27ff87",
    12: "#c24f44",
    13: "#a5a5a5",
    14: "#ff6d4c",
    15: "#69fff8",
    16: "#f9ffa4",
    17: "#1c0dff",
}

MODIS_LULC_MIN_YEAR = 2001
MODIS_LULC_MAX_YEAR = 2024

CHANGE_CLASSES = [
    {"value": 0, "label": "No detected change", "color": "#d1d5db"},
    {"value": 1, "label": "Changed area", "color": "#7c3aed"},
]

CHANGE_RENDER_COLORS = [
    "#9ca3af",
    "#ef4444",
    "#f97316",
    "#eab308",
    "#84cc16",
    "#22c55e",
    "#10b981",
    "#14b8a6",
    "#06b6d4",
    "#0ea5e9",
    "#3b82f6",
    "#6366f1",
    "#8b5cf6",
    "#a855f7",
    "#d946ef",
    "#ec4899",
]

FLOOD_CLASSES = [
    {"value": 0, "label": "No flood signature", "color": "#dbeafe"},
    {"value": 1, "label": "Water extent", "color": "#2563eb"},
]

LAND_DEGRADATION_CLASSES = [
    {"value": 0, "label": "No degradation flag", "color": "#dcfce7"},
    {"value": 1, "label": "Potentially degraded", "color": "#b91c1c"},
]

NDVI_CLASSES = [
    {"min": -1.0, "max": -0.2, "label": "Water / open water", "color": "#1d4ed8"},
    {"min": -0.2, "max": 0.0, "label": "Bare, non-vegetated, or severely stressed", "color": "#ef4444"},
    {"min": 0.0, "max": 0.2, "label": "Sparse vegetation / mixed built-up or bare surface", "color": "#f59e0b"},
    {"min": 0.2, "max": 0.4, "label": "Low vegetation vigor", "color": "#fde68a"},
    {"min": 0.4, "max": 0.6, "label": "Moderate vegetation vigor", "color": "#86efac"},
    {"min": 0.6, "max": 0.8, "label": "Healthy vegetation", "color": "#22c55e"},
    {"min": 0.8, "max": 1.0, "label": "Very dense vegetation", "color": "#166534"},
]

LST_CLASSES = [
    {"min": -10.0, "max": 10.0, "label": "Cool (-10 to 10 C)", "color": "#1d4ed8"},
    {"min": 10.0, "max": 20.0, "label": "Mild (10 to 20 C)", "color": "#38bdf8"},
    {"min": 20.0, "max": 30.0, "label": "Warm (20 to 30 C)", "color": "#facc15"},
    {"min": 30.0, "max": 40.0, "label": "Hot (30 to 40 C)", "color": "#f97316"},
    {"min": 40.0, "max": 70.0, "label": "Very hot (40 to 70 C)", "color": "#b91c1c"},
]

DROUGHT_CLASSES = [
    {"min": -1.0, "max": 0.0, "label": "Very wet drought proxy (NDDI)", "color": "#1d4ed8"},
    {"min": 0.0, "max": 0.1, "label": "Wet drought proxy (NDDI)", "color": "#60a5fa"},
    {"min": 0.1, "max": 0.2, "label": "Near normal drought proxy (NDDI)", "color": "#e5e7eb"},
    {"min": 0.2, "max": 0.3, "label": "Mild drought proxy (NDDI)", "color": "#f59e0b"},
    {"min": 0.3, "max": 0.4, "label": "Moderate drought proxy (NDDI)", "color": "#ef4444"},
    {"min": 0.4, "max": 0.5, "label": "Severe drought proxy (NDDI)", "color": "#b91c1c"},
    {"min": 0.5, "max": 1.1, "label": "Extreme drought proxy (NDDI)", "color": "#7f1d1d"},
]

SOLAR_RADIATION_CLASSES = [
    {"min": 0.0, "max": 5.0, "label": "Very low solar radiation", "color": "#dbeafe"},
    {"min": 5.0, "max": 10.0, "label": "Low solar radiation", "color": "#93c5fd"},
    {"min": 10.0, "max": 15.0, "label": "Moderate solar radiation", "color": "#fde68a"},
    {"min": 15.0, "max": 20.0, "label": "High solar radiation", "color": "#f59e0b"},
    {"min": 20.0, "max": 40.0, "label": "Very high solar radiation", "color": "#b45309"},
]

SOLAR_TREND_CLASSES = [
    {"min": -2.0, "max": -0.5, "label": "Declining radiation", "color": "#1d4ed8"},
    {"min": -0.5, "max": -0.1, "label": "Slight decline", "color": "#93c5fd"},
    {"min": -0.1, "max": 0.1, "label": "Stable", "color": "#f8fafc"},
    {"min": 0.1, "max": 0.5, "label": "Slight increase", "color": "#f59e0b"},
    {"min": 0.5, "max": 2.0, "label": "Increasing radiation", "color": "#b45309"},
]

NDWI_CLASSES = [
    {"min": -1.0, "max": -0.5, "label": "Very dry surface", "color": "#7f1d1d"},
    {"min": -0.5, "max": -0.3, "label": "Dry surface", "color": "#b45309"},
    {"min": -0.3, "max": -0.1, "label": "Low moisture", "color": "#f97316"},
    {"min": -0.1, "max": 0.1, "label": "Moderate moisture / mixed surface", "color": "#fde68a"},
    {"min": 0.1, "max": 0.3, "label": "Wet surface / shallow or mixed water", "color": "#86efac"},
    {"min": 0.3, "max": 1.0, "label": "Open water / very wet", "color": "#2563eb"},
]

NDWI_TREND_CLASSES = [
    {"min": -0.2, "max": -0.05, "label": "Drying", "color": "#991b1b"},
    {"min": -0.05, "max": -0.01, "label": "Slight drying", "color": "#fb923c"},
    {"min": -0.01, "max": 0.01, "label": "Stable", "color": "#f8fafc"},
    {"min": 0.01, "max": 0.05, "label": "Slight wetting", "color": "#60a5fa"},
    {"min": 0.05, "max": 0.2, "label": "Wetting", "color": "#1d4ed8"},
]

PRECIPITATION_CLASSES = [
    {"min": -200.0, "max": -50.0, "label": "Much drier than baseline", "color": "#991b1b"},
    {"min": -50.0, "max": -10.0, "label": "Drier than baseline", "color": "#fb923c"},
    {"min": -10.0, "max": 10.0, "label": "Near baseline", "color": "#f8fafc"},
    {"min": 10.0, "max": 50.0, "label": "Wetter than baseline", "color": "#60a5fa"},
    {"min": 50.0, "max": 500.0, "label": "Much wetter than baseline", "color": "#1d4ed8"},
]

PRECIPITATION_TREND_CLASSES = [
    {"min": -50.0, "max": -10.0, "label": "Strong rainfall decline", "color": "#991b1b"},
    {"min": -10.0, "max": -2.0, "label": "Rainfall decline", "color": "#fb923c"},
    {"min": -2.0, "max": 2.0, "label": "Stable", "color": "#f8fafc"},
    {"min": 2.0, "max": 10.0, "label": "Rainfall increase", "color": "#60a5fa"},
    {"min": 10.0, "max": 50.0, "label": "Strong rainfall increase", "color": "#1d4ed8"},
]

SOIL_MOISTURE_CLASSES = [
    {"min": -1.0, "max": -0.2, "label": "Very dry soil moisture proxy (NDMI)", "color": "#7f1d1d"},
    {"min": -0.2, "max": 0.0, "label": "Dry soil moisture proxy (NDMI)", "color": "#ea580c"},
    {"min": 0.0, "max": 0.15, "label": "Moderate soil moisture proxy (NDMI)", "color": "#fde68a"},
    {"min": 0.15, "max": 0.3, "label": "Moist soil moisture proxy (NDMI)", "color": "#60a5fa"},
    {"min": 0.3, "max": 1.0, "label": "Very moist soil moisture proxy (NDMI)", "color": "#1d4ed8"},
]

SOIL_MOISTURE_TREND_CLASSES = [
    {"min": -0.2, "max": -0.05, "label": "Strong drying", "color": "#991b1b"},
    {"min": -0.05, "max": -0.01, "label": "Drying", "color": "#fb923c"},
    {"min": -0.01, "max": 0.01, "label": "Stable", "color": "#f8fafc"},
    {"min": 0.01, "max": 0.05, "label": "Wetting", "color": "#60a5fa"},
    {"min": 0.05, "max": 0.2, "label": "Strong wetting", "color": "#1d4ed8"},
]

EROSION_RISK_CLASSES = [
    {"min": 0.0, "max": 20.0, "label": "Very low erosion risk", "color": "#dcfce7"},
    {"min": 20.0, "max": 40.0, "label": "Low erosion risk", "color": "#a3e635"},
    {"min": 40.0, "max": 60.0, "label": "Moderate erosion risk", "color": "#facc15"},
    {"min": 60.0, "max": 80.0, "label": "High erosion risk", "color": "#fb923c"},
    {"min": 80.0, "max": 100.1, "label": "Very high erosion risk", "color": "#991b1b"},
]

EROSION_RISK_TREND_CLASSES = [
    {"min": -20.0, "max": -5.0, "label": "Risk decreasing strongly", "color": "#166534"},
    {"min": -5.0, "max": -1.0, "label": "Risk decreasing", "color": "#4ade80"},
    {"min": -1.0, "max": 1.0, "label": "Stable", "color": "#f8fafc"},
    {"min": 1.0, "max": 5.0, "label": "Risk increasing", "color": "#fb923c"},
    {"min": 5.0, "max": 20.0, "label": "Risk increasing strongly", "color": "#991b1b"},
]

TERRAIN_SUSCEPTIBILITY_CLASSES = [
    {"min": 0.0, "max": 10.0, "label": "Very low terrain susceptibility", "color": "#dcfce7"},
    {"min": 10.0, "max": 20.0, "label": "Low terrain susceptibility", "color": "#86efac"},
    {"min": 20.0, "max": 30.0, "label": "Moderate terrain susceptibility", "color": "#fde68a"},
    {"min": 30.0, "max": 45.0, "label": "High terrain susceptibility", "color": "#fb923c"},
    {"min": 45.0, "max": 90.1, "label": "Very high terrain susceptibility", "color": "#991b1b"},
]

WILDFIRE_CLASSES = [
    {"min": 0.0, "max": 1.0, "label": "No detected burn", "color": "#e5e7eb"},
    {"min": 1.0, "max": 10.0, "label": "Low burn frequency", "color": "#fde68a"},
    {"min": 10.0, "max": 25.0, "label": "Moderate burn frequency", "color": "#fb923c"},
    {"min": 25.0, "max": 50.0, "label": "High burn frequency", "color": "#ef4444"},
    {"min": 50.0, "max": 100.1, "label": "Very high burn frequency", "color": "#7f1d1d"},
]

WILDFIRE_TREND_CLASSES = [
    {"min": -20.0, "max": -5.0, "label": "Burning declining", "color": "#166534"},
    {"min": -5.0, "max": -1.0, "label": "Slight decline", "color": "#4ade80"},
    {"min": -1.0, "max": 1.0, "label": "Stable", "color": "#f8fafc"},
    {"min": 1.0, "max": 5.0, "label": "Increasing burning", "color": "#fb923c"},
    {"min": 5.0, "max": 20.0, "label": "Strong increase in burning", "color": "#991b1b"},
]

PM25_AVAILABLE_START_YEAR = 2000
PM25_AVAILABLE_END_YEAR = 2022
PM25_COLLECTION_ID = "projects/sat-io/open-datasets/GLOBAL-SATELLITE-PM25/ANNUAL"

AIR_QUALITY_CLASSES = [
    {"min": 0.0, "max": 5.0, "label": "Low PM2.5 (0 to 5 ug/m3)", "color": "#dcfce7"},
    {"min": 5.0, "max": 10.0, "label": "Moderate PM2.5 (5 to 10 ug/m3)", "color": "#86efac"},
    {"min": 10.0, "max": 15.0, "label": "Elevated PM2.5 (10 to 15 ug/m3)", "color": "#fde68a"},
    {"min": 15.0, "max": 25.0, "label": "High PM2.5 (15 to 25 ug/m3)", "color": "#fb923c"},
    {"min": 25.0, "max": 100.0, "label": "Very high PM2.5 (>25 ug/m3)", "color": "#991b1b"},
]

AIR_QUALITY_TREND_CLASSES = [
    {"min": -5.0, "max": -1.0, "label": "PM2.5 improving strongly", "color": "#166534"},
    {"min": -1.0, "max": -0.2, "label": "PM2.5 improving slightly", "color": "#4ade80"},
    {"min": -0.2, "max": 0.2, "label": "PM2.5 stable", "color": "#f8fafc"},
    {"min": 0.2, "max": 1.0, "label": "PM2.5 increasing slightly", "color": "#fb923c"},
    {"min": 1.0, "max": 5.0, "label": "PM2.5 increasing strongly", "color": "#991b1b"},
]

HABITAT_FRAGMENTATION_CLASSES = [
    {"min": 0.0, "max": 20.0, "label": "Low fragmentation pressure", "color": "#166534"},
    {"min": 20.0, "max": 40.0, "label": "Moderate-low fragmentation pressure", "color": "#4ade80"},
    {"min": 40.0, "max": 60.0, "label": "Moderate fragmentation pressure", "color": "#fde68a"},
    {"min": 60.0, "max": 80.0, "label": "High fragmentation pressure", "color": "#fb923c"},
    {"min": 80.0, "max": 100.1, "label": "Very high fragmentation pressure", "color": "#991b1b"},
]

HABITAT_FRAGMENTATION_TREND_CLASSES = [
    {"min": -20.0, "max": -5.0, "label": "Fragmentation easing", "color": "#166534"},
    {"min": -5.0, "max": -1.0, "label": "Slight easing", "color": "#4ade80"},
    {"min": -1.0, "max": 1.0, "label": "Stable", "color": "#f8fafc"},
    {"min": 1.0, "max": 5.0, "label": "Fragmentation increasing", "color": "#fb923c"},
    {"min": 5.0, "max": 20.0, "label": "Fragmentation increasing strongly", "color": "#991b1b"},
]

RUNOFF_POTENTIAL_CLASSES = [
    {"min": 0.0, "max": 20.0, "label": "Very low runoff potential", "color": "#dcfce7"},
    {"min": 20.0, "max": 40.0, "label": "Low runoff potential", "color": "#86efac"},
    {"min": 40.0, "max": 60.0, "label": "Moderate runoff potential", "color": "#fde68a"},
    {"min": 60.0, "max": 80.0, "label": "High runoff potential", "color": "#60a5fa"},
    {"min": 80.0, "max": 100.1, "label": "Very high runoff potential", "color": "#1d4ed8"},
]

RUNOFF_POTENTIAL_TREND_CLASSES = [
    {"min": -20.0, "max": -5.0, "label": "Runoff pressure decreasing", "color": "#166534"},
    {"min": -5.0, "max": -1.0, "label": "Slight decrease", "color": "#4ade80"},
    {"min": -1.0, "max": 1.0, "label": "Stable", "color": "#f8fafc"},
    {"min": 1.0, "max": 5.0, "label": "Runoff pressure increasing", "color": "#60a5fa"},
    {"min": 5.0, "max": 20.0, "label": "Runoff pressure increasing strongly", "color": "#1d4ed8"},
]

SOIL_CLASSES = [
    {"min": 0.0, "max": 10.0, "label": "Very low soil carbon (0 to 10 g/kg)", "color": "#fef3c7"},
    {"min": 10.0, "max": 20.0, "label": "Low soil carbon (10 to 20 g/kg)", "color": "#fcd34d"},
    {"min": 20.0, "max": 35.0, "label": "Moderate soil carbon (20 to 35 g/kg)", "color": "#a3e635"},
    {"min": 35.0, "max": 50.0, "label": "High soil carbon (35 to 50 g/kg)", "color": "#65a30d"},
    {"min": 50.0, "max": 200.0, "label": "Very high soil carbon (50 to 200 g/kg)", "color": "#365314"},
]

WIND_DIRECTION_CLASSES = [
    {"value": 0, "label": "North", "color": "#1d4ed8"},
    {"value": 1, "label": "North-East", "color": "#38bdf8"},
    {"value": 2, "label": "East", "color": "#22c55e"},
    {"value": 3, "label": "South-East", "color": "#facc15"},
    {"value": 4, "label": "South", "color": "#f97316"},
    {"value": 5, "label": "South-West", "color": "#ef4444"},
    {"value": 6, "label": "West", "color": "#a855f7"},
    {"value": 7, "label": "North-West", "color": "#6366f1"},
]

WIND_DIRECTION_RENDER_CLASSES = [
    {"min": 0.0, "max": 45.0, "label": "North", "color": "#1d4ed8"},
    {"min": 45.0, "max": 90.0, "label": "North-East", "color": "#38bdf8"},
    {"min": 90.0, "max": 135.0, "label": "East", "color": "#22c55e"},
    {"min": 135.0, "max": 180.0, "label": "South-East", "color": "#facc15"},
    {"min": 180.0, "max": 225.0, "label": "South", "color": "#f97316"},
    {"min": 225.0, "max": 270.0, "label": "South-West", "color": "#ef4444"},
    {"min": 270.0, "max": 315.0, "label": "West", "color": "#a855f7"},
    {"min": 315.0, "max": 360.1, "label": "North-West", "color": "#6366f1"},
]

NDVI_TREND_CLASSES = [
    {"min": -0.05, "max": -0.01, "label": "Strong decline", "color": "#7f1d1d"},
    {"min": -0.01, "max": -0.002, "label": "Decline", "color": "#f97316"},
    {"min": -0.002, "max": 0.002, "label": "Stable", "color": "#f8fafc"},
    {"min": 0.002, "max": 0.01, "label": "Increase", "color": "#4ade80"},
    {"min": 0.01, "max": 0.05, "label": "Strong increase", "color": "#166534"},
]

LST_TREND_CLASSES = [
    {"min": -1.0, "max": -0.2, "label": "Cooling", "color": "#1d4ed8"},
    {"min": -0.2, "max": -0.05, "label": "Slight cooling", "color": "#93c5fd"},
    {"min": -0.05, "max": 0.05, "label": "Stable", "color": "#f8fafc"},
    {"min": 0.05, "max": 0.2, "label": "Slight warming", "color": "#fb923c"},
    {"min": 0.2, "max": 1.0, "label": "Warming", "color": "#991b1b"},
]

UHI_CLASSES = [
    {"min": -20.0, "max": -5.0, "label": "Much cooler than non-urban background", "color": "#1d4ed8"},
    {"min": -5.0, "max": -1.0, "label": "Cooler than non-urban background", "color": "#38bdf8"},
    {"min": -1.0, "max": 1.0, "label": "Near non-urban background temperature", "color": "#f8fafc"},
    {"min": 1.0, "max": 5.0, "label": "Urban heat intensity", "color": "#f97316"},
    {"min": 5.0, "max": 30.0, "label": "Strong urban heat intensity", "color": "#991b1b"},
]

UHI_TREND_CLASSES = [
    {"min": -1.0, "max": -0.2, "label": "Heat intensity decreasing", "color": "#1d4ed8"},
    {"min": -0.2, "max": -0.05, "label": "Slight decrease in heat intensity", "color": "#93c5fd"},
    {"min": -0.05, "max": 0.05, "label": "Stable heat intensity", "color": "#f8fafc"},
    {"min": 0.05, "max": 0.2, "label": "Slight increase in heat intensity", "color": "#fb923c"},
    {"min": 0.2, "max": 1.0, "label": "Heat intensity increasing", "color": "#991b1b"},
]

DROUGHT_TREND_CLASSES = [
    {"min": -0.2, "max": -0.05, "label": "Becoming wetter", "color": "#1d4ed8"},
    {"min": -0.05, "max": -0.01, "label": "Slight wetting", "color": "#60a5fa"},
    {"min": -0.01, "max": 0.01, "label": "Stable", "color": "#f8fafc"},
    {"min": 0.01, "max": 0.05, "label": "Slight drying", "color": "#fb923c"},
    {"min": 0.05, "max": 0.2, "label": "Becoming drier", "color": "#991b1b"},
]

SOIL_TREND_CLASSES = [
    {"min": -0.5, "max": -0.1, "label": "Declining soil quality", "color": "#991b1b"},
    {"min": -0.1, "max": -0.02, "label": "Slight decline", "color": "#fb923c"},
    {"min": -0.02, "max": 0.02, "label": "Stable", "color": "#f8fafc"},
    {"min": 0.02, "max": 0.1, "label": "Slight improvement", "color": "#4ade80"},
    {"min": 0.1, "max": 0.5, "label": "Improving soil quality", "color": "#166534"},
]

WIND_TREND_CLASSES = [
    {"min": -1.0, "max": -0.2, "label": "Weakening winds", "color": "#1d4ed8"},
    {"min": -0.2, "max": -0.05, "label": "Slight weakening", "color": "#93c5fd"},
    {"min": -0.05, "max": 0.05, "label": "Stable", "color": "#f8fafc"},
    {"min": 0.05, "max": 0.2, "label": "Slight strengthening", "color": "#fb923c"},
    {"min": 0.2, "max": 1.0, "label": "Strengthening winds", "color": "#991b1b"},
]

CARBON_EMISSION_CLASSES = [
    {"min": 0.0, "max": 0.05, "label": "Very low emissions", "color": "#dcfce7"},
    {"min": 0.05, "max": 0.2, "label": "Low emissions", "color": "#86efac"},
    {"min": 0.2, "max": 0.5, "label": "Moderate emissions", "color": "#facc15"},
    {"min": 0.5, "max": 1.0, "label": "High emissions", "color": "#fb923c"},
    {"min": 1.0, "max": 10.0, "label": "Very high emissions", "color": "#991b1b"},
]

CARBON_EMISSION_ZERO_CLASS = [
    {"value": 0, "label": "No biomass emission detected", "color": "#d1fae5", "min": 0.0, "max": 0.0},
]

CARBON_SEQUESTRATION_CLASSES = [
    {"min": -1.0, "max": 0.1, "label": "Very low sequestration", "color": "#fef2f2"},
    {"min": 0.1, "max": 0.4, "label": "Low sequestration", "color": "#fde68a"},
    {"min": 0.4, "max": 0.8, "label": "Moderate sequestration", "color": "#86efac"},
    {"min": 0.8, "max": 1.2, "label": "High sequestration", "color": "#22c55e"},
    {"min": 1.2, "max": 4.0, "label": "Very high sequestration", "color": "#166534"},
]

CARBON_SEQUESTRATION_ZERO_CLASS = [
    {"value": 0, "label": "No sequestration detected", "color": "#e5e7eb", "min": 0.0, "max": 0.0},
]

ANTHRO_EMISSION_CLASSES = [
    {"min": 0.0, "max": 1.0, "label": "Very low anthropogenic emission proxy", "color": "#e5e7eb"},
    {"min": 1.0, "max": 5.0, "label": "Low anthropogenic emission proxy", "color": "#bae6fd"},
    {"min": 5.0, "max": 15.0, "label": "Moderate anthropogenic emission proxy", "color": "#facc15"},
    {"min": 15.0, "max": 40.0, "label": "High anthropogenic emission proxy", "color": "#f97316"},
    {"min": 40.0, "max": 200.0, "label": "Very high anthropogenic emission proxy", "color": "#991b1b"},
]

ANTHRO_EMISSION_TREND_CLASSES = [
    {"min": -10.0, "max": -2.0, "label": "Strong decline", "color": "#1d4ed8"},
    {"min": -2.0, "max": -0.5, "label": "Decline", "color": "#93c5fd"},
    {"min": -0.5, "max": 0.5, "label": "Stable", "color": "#f8fafc"},
    {"min": 0.5, "max": 2.0, "label": "Increase", "color": "#fb923c"},
    {"min": 2.0, "max": 10.0, "label": "Strong increase", "color": "#991b1b"},
]

CARBON_EMISSION_TREND_CLASSES = [
    {"min": -0.5, "max": -0.05, "label": "Strong emission decline", "color": "#166534"},
    {"min": -0.05, "max": -0.01, "label": "Declining emissions", "color": "#4ade80"},
    {"min": -0.01, "max": 0.01, "label": "Stable", "color": "#f8fafc"},
    {"min": 0.01, "max": 0.05, "label": "Rising emissions", "color": "#fb923c"},
    {"min": 0.05, "max": 0.5, "label": "Strong emission rise", "color": "#991b1b"},
]

CARBON_SEQUESTRATION_TREND_CLASSES = [
    {"min": -0.1, "max": -0.02, "label": "Declining sequestration", "color": "#991b1b"},
    {"min": -0.02, "max": -0.005, "label": "Slight decline", "color": "#fb923c"},
    {"min": -0.005, "max": 0.005, "label": "Stable", "color": "#f8fafc"},
    {"min": 0.005, "max": 0.02, "label": "Improving sequestration", "color": "#4ade80"},
    {"min": 0.02, "max": 0.1, "label": "Strong sequestration gain", "color": "#166534"},
]

ANALYSIS_DEFINITIONS = {
    "lulc": {
        "label": "Land Use Land Cover (Sentinel)",
        "band_name": "classification",
        "stat_label": "Dominant class area (ha)",
        "scale": 10,
        "summary_mode": "discrete",
        "summary_classes": [{"value": key, "label": value, "color": LULC_CLASS_COLORS[key]} for key, value in LULC_CLASS_NAMES.items()],
        "trend_label": "Dominant class area (ha)",
    },
    "lulc_landsat": {
        "label": "Land Use Land Cover (Landsat 8)",
        "band_name": "classification",
        "stat_label": "Dominant class area (ha)",
        "scale": 30,
        "summary_mode": "discrete",
        "summary_classes": [{"value": key, "label": value, "color": LULC_LANDSAT_CLASS_COLORS[key]} for key, value in LULC_LANDSAT_CLASS_NAMES.items()],
        "trend_label": "Dominant class area (ha)",
    },
    "change_detection": {
        "label": "Change Detection",
        "band_name": "change",
        "stat_label": "Changed area (ha)",
        "scale": 10,
        "summary_mode": "discrete",
        "summary_classes": CHANGE_CLASSES,
        "trend_label": "Changed area (ha)",
    },
    "lst": {
        "label": "Land Surface Temperature",
        "band_name": "LST_C",
        "stat_label": "Mean LST (C)",
        "scale": 30,
        "summary_mode": "range",
        "summary_classes": LST_CLASSES,
        "trend_classes": LST_TREND_CLASSES,
        "trend_label": "Annual mean LST (C)",
    },
    "urban_heat_island": {
        "label": "Urban Heat Island",
        "band_name": "uhi_intensity_c",
        "stat_label": "Mean LST heat intensity relative to AOI (C)",
        "scale": 30,
        "summary_mode": "range",
        "summary_classes": UHI_CLASSES,
        "trend_classes": UHI_TREND_CLASSES,
        "trend_label": "Annual LST heat-intensity trend (C/year)",
    },
    "flood": {
        "label": "Flood Analysis",
        "band_name": "flood",
        "stat_label": "Water extent (ha)",
        "scale": 10,
        "summary_mode": "discrete",
        "summary_classes": FLOOD_CLASSES,
        "trend_label": "Water extent (ha)",
    },
    "ndvi": {
        "label": "NDVI",
        "band_name": "NDVI",
        "stat_label": "Mean NDVI",
        "scale": 30,
        "summary_mode": "range",
        "summary_classes": NDVI_CLASSES,
        "trend_classes": NDVI_TREND_CLASSES,
        "trend_label": "Annual mean NDVI",
    },
    "land_degradation": {
        "label": "Land Degradation",
        "band_name": "degradation",
        "stat_label": "Degraded area (ha)",
        "scale": 30,
        "summary_mode": "discrete",
        "summary_classes": LAND_DEGRADATION_CLASSES,
        "trend_classes": NDVI_TREND_CLASSES,
        "trend_label": "Potentially degraded area (ha)",
    },
    "drought": {
        "label": "Drought Assessment",
        "band_name": "drought_proxy",
        "stat_label": "Mean drought proxy (NDDI)",
        "scale": 30,
        "summary_mode": "range",
        "summary_classes": DROUGHT_CLASSES,
        "trend_classes": DROUGHT_TREND_CLASSES,
        "trend_label": "Annual mean drought proxy (NDDI)",
    },
    "soil": {
        "label": "Soil Organic Carbon",
        "band_name": "soil_carbon",
        "stat_label": "Mean soil organic carbon (g/kg)",
        "scale": 250,
        "summary_mode": "range",
        "summary_classes": SOIL_CLASSES,
        "trend_classes": SOIL_TREND_CLASSES,
        "trend_label": "Annual soil condition index",
    },
    "wind_direction": {
        "label": "Wind Direction Assessment",
        "band_name": "wind_direction",
        "stat_label": "Prevailing wind direction (degrees)",
        "scale": 27830,
        "summary_mode": "discrete",
        "summary_classes": WIND_DIRECTION_CLASSES,
        "trend_classes": WIND_TREND_CLASSES,
        "trend_label": "Annual mean wind speed (m/s)",
    },
    "carbon_emission": {
        "label": "Carbon Emission (Biomass)",
        "band_name": "carbon_emission",
        "stat_label": "Mean biomass-loss carbon proxy (Mg C/ha)",
        "scale": 300,
        "summary_mode": "range",
        "summary_classes": CARBON_EMISSION_CLASSES,
        "trend_classes": CARBON_EMISSION_TREND_CLASSES,
        "trend_label": "Annual mean biomass-loss carbon proxy (Mg C/ha)",
    },
    "anthropogenic_emission": {
        "label": "Anthropogenic Emission (Nighttime Lights Proxy)",
        "band_name": "anthropogenic_emission",
        "stat_label": "Mean anthropogenic emission proxy (nW/sr/cm^2)",
        "scale": 464,
        "summary_mode": "range",
        "summary_classes": ANTHRO_EMISSION_CLASSES,
        "trend_classes": ANTHRO_EMISSION_TREND_CLASSES,
        "trend_label": "Annual mean anthropogenic emission proxy (nW/sr/cm^2)",
    },
    "carbon_sequestration": {
        "label": "Carbon Sequestration",
        "band_name": "carbon_sequestration",
        "stat_label": "Mean carbon sequestration proxy (kg C/m²)",
        "scale": 500,
        "summary_mode": "range",
        "summary_classes": CARBON_SEQUESTRATION_CLASSES,
        "trend_classes": CARBON_SEQUESTRATION_TREND_CLASSES,
        "trend_label": "Annual mean NPP (kg C/m²)",
    },
    "solar_radiation": {
        "label": "Solar Radiation Assessment",
        "band_name": "solar_radiation",
        "stat_label": "Mean solar radiation proxy (MODIS PAR)",
        "scale": 500,
        "summary_mode": "range",
        "summary_classes": SOLAR_RADIATION_CLASSES,
        "trend_classes": SOLAR_TREND_CLASSES,
        "trend_label": "Annual mean solar radiation proxy (MODIS PAR)",
    },
    "ndwi": {
        "label": "NDWI",
        "band_name": "NDWI",
        "stat_label": "Mean NDWI",
        "scale": 30,
        "summary_mode": "range",
        "summary_classes": NDWI_CLASSES,
        "trend_classes": NDWI_TREND_CLASSES,
        "trend_label": "Annual mean NDWI",
    },
    "precipitation_anomaly": {
        "label": "Rainfall / Precipitation Anomaly",
        "band_name": "precipitation_anomaly",
        "stat_label": "Mean precipitation anomaly (mm/day)",
        "scale": 5566,
        "summary_mode": "range",
        "summary_classes": PRECIPITATION_CLASSES,
        "trend_classes": PRECIPITATION_TREND_CLASSES,
        "trend_label": "Annual mean precipitation anomaly (mm/day)",
    },
    "soil_moisture": {
        "label": "Soil Moisture",
        "band_name": "soil_moisture",
        "stat_label": "Mean soil moisture proxy (NDMI)",
        "scale": 30,
        "summary_mode": "range",
        "summary_classes": SOIL_MOISTURE_CLASSES,
        "trend_classes": SOIL_MOISTURE_TREND_CLASSES,
        "trend_label": "Annual mean soil moisture proxy (NDMI)",
    },
    "erosion_risk": {
        "label": "Erosion Risk",
        "band_name": "erosion_risk",
        "stat_label": "Mean erosion risk index",
        "scale": 30,
        "summary_mode": "range",
        "summary_classes": EROSION_RISK_CLASSES,
        "trend_classes": EROSION_RISK_TREND_CLASSES,
        "trend_label": "Annual mean erosion risk index",
    },
    "terrain_susceptibility": {
        "label": "Terrain Susceptibility to Erosion / Instability",
        "band_name": "terrain_susceptibility",
        "stat_label": "Mean terrain susceptibility to erosion / instability (degrees)",
        "scale": 30,
        "summary_mode": "range",
        "summary_classes": TERRAIN_SUSCEPTIBILITY_CLASSES,
        "trend_classes": TERRAIN_SUSCEPTIBILITY_CLASSES,
        "trend_label": "Annual terrain susceptibility to erosion / instability (degrees)",
    },
    "wildfire_risk": {
        "label": "Wildfire Risk / Burn Severity",
        "band_name": "wildfire_risk",
        "stat_label": "Mean burned frequency (%)",
        "scale": 500,
        "summary_mode": "range",
        "summary_classes": WILDFIRE_CLASSES,
        "trend_classes": WILDFIRE_TREND_CLASSES,
        "trend_label": "Annual burned frequency (%)",
    },
    "air_quality": {
        "label": "PM2.5 Air Quality",
        "band_name": "air_quality",
        "stat_label": "Mean PM2.5 concentration (ug/m3)",
        "scale": 1000,
        "summary_mode": "range",
        "summary_classes": AIR_QUALITY_CLASSES,
        "trend_classes": AIR_QUALITY_TREND_CLASSES,
        "trend_label": "Annual mean PM2.5 concentration (ug/m3)",
    },
    "habitat_fragmentation": {
        "label": "Habitat Fragmentation / Biodiversity Pressure",
        "band_name": "habitat_fragmentation",
        "stat_label": "Mean fragmentation pressure index",
        "scale": 120,
        "summary_mode": "range",
        "summary_classes": HABITAT_FRAGMENTATION_CLASSES,
        "trend_classes": HABITAT_FRAGMENTATION_TREND_CLASSES,
        "trend_label": "Annual fragmentation pressure index",
    },
    "runoff_potential": {
        "label": "Groundwater Recharge / Runoff Potential",
        "band_name": "runoff_potential",
        "stat_label": "Mean runoff potential index",
        "scale": 463,
        "summary_mode": "range",
        "summary_classes": RUNOFF_POTENTIAL_CLASSES,
        "trend_classes": RUNOFF_POTENTIAL_TREND_CLASSES,
        "trend_label": "Annual runoff potential index",
    },
}


class EarthEngineUnavailableError(RuntimeError):
    """Raised when the Earth Engine Python API is unavailable."""


@dataclass
class AssessmentRequest:
    """Parameters coming from the UI."""

    analysis_id: str
    mode: str
    start_date: date
    end_date: date
    output_dir: str
    output_name: str
    aoi_name: str = ""
    interval_years: int = 1
    generate_reports: bool = True
    convert_to_vector: bool = False
    export_processed_stack: bool = False
    export_landsat_stack: bool = False
    aoi_layer: object = None
    aoi_geometry_jsons: list | None = None


class EarthEngineAssessmentService:
    """Runs environmental assessments in Google Earth Engine."""

    def __init__(self):
        self.dependency_manager = DependencyManager()
        self._active_task = None

    def ensure_initialized(self):
        """Initialize Earth Engine and trigger auth when required."""
        earth_engine = self._load_earth_engine_module()
        if earth_engine is None:
            raise EarthEngineUnavailableError(
                "The Earth Engine Python API is not installed in this QGIS environment. "
                "Use the Settings section in the plugin to install or upgrade the dependency."
            )

        try:
            project_id = self.dependency_manager.project_id()
            if project_id:
                earth_engine.Initialize(project=project_id)
            else:
                earth_engine.Initialize()
        except Exception as init_exc:
            if self._is_dns_resolution_error(init_exc):
                raise RuntimeError(self._dns_resolution_error_message(init_exc)) from init_exc
            try:
                earth_engine.Authenticate()
                project_id = self.dependency_manager.project_id()
                if project_id:
                    earth_engine.Initialize(project=project_id)
                else:
                    earth_engine.Initialize()
            except Exception as exc:  # pragma: no cover - interactive auth
                if self._is_dns_resolution_error(exc):
                    raise RuntimeError(self._dns_resolution_error_message(exc)) from exc
                raise RuntimeError(f"Earth Engine initialization failed: {exc}") from exc

    def run(self, request: AssessmentRequest, task=None):
        """Execute snapshot or trend workflow and return local output paths."""
        self._active_task = task
        try:
            self._update_task_progress(task, 2, "Initializing Earth Engine workflow")
            self.ensure_initialized()
            self._raise_if_canceled(task)
            self._update_task_progress(task, 4, "Checking dataset availability")
            self.ensure_data_available(request)
            self._raise_if_canceled(task)
            self._update_task_progress(task, 6, "Preparing area of interest")
            geometry = self._layer_to_ee_geometry(request.aoi_geometry_jsons or request.aoi_layer)
            analysis = ANALYSIS_DEFINITIONS[request.analysis_id]
            safe_name = self._sanitize_name(request.output_name or analysis["label"])
            output_dir = self._assessment_output_dir(
                request.output_dir,
                request.analysis_id,
                request.mode,
                safe_name,
                request.aoi_name,
            )
            output_dir.mkdir(parents=True, exist_ok=True)

            if request.mode == "trend":
                result = self._run_trend(request, geometry, analysis, output_dir, safe_name, task=task)
            else:
                result = self._run_snapshot(request, geometry, analysis, output_dir, safe_name, task=task)

            if isinstance(result, dict):
                result.setdefault("output_dir", str(output_dir))
            return result
        except Exception as exc:
            message = str(exc)
            if self._is_dns_resolution_error(exc):
                raise RuntimeError(self._dns_resolution_error_message(exc)) from exc
            if request.analysis_id == "lulc_landsat" and "User memory limit exceeded" in message:
                raise RuntimeError(
                    "Landsat 8 LULC exceeded the Earth Engine memory limit for this request. "
                    "This assessment is much heavier than the Sentinel LULC workflow because it builds annual "
                    "Landsat composites and applies a trained classifier. Try a smaller AOI or use the "
                    "Sentinel-based LULC assessment for the same period."
                ) from exc
            raise
        finally:
            if self._active_task is task:
                self._active_task = None

    @staticmethod
    def _is_dns_resolution_error(error):
        text = str(error).lower()
        return (
            "getaddrinfo failed" in text
            or "name or service not known" in text
            or "failed to resolve" in text
            or "nameresolutionerror" in text
            or "temporary failure in name resolution" in text
        )

    @staticmethod
    def _dns_resolution_error_message(error):
        return (
            "Earth Engine could not be reached because QGIS/Python could not resolve a Google service hostname. "
            "This is a DNS/network connectivity problem, not a completed assessment result. "
            "Check internet connectivity, DNS/VPN/proxy/firewall settings, and try again after the connection is stable. "
            f"System detail: {error}"
        )

    def ensure_data_available(self, request: AssessmentRequest):
        """Raise a friendly error if the selected period has no source data."""
        geometry = self._layer_to_ee_geometry(request.aoi_geometry_jsons or request.aoi_layer)
        analysis_id = request.analysis_id

        if analysis_id in {"lulc", "change_detection"}:
            self._ensure_collection_has_data(
                "GOOGLE/DYNAMICWORLD/V1",
                geometry,
                date(request.start_date.year, 1, 1),
                date(request.start_date.year, 12, 31),
                f"No Dynamic World LULC data is available for {request.start_date.year}.",
                dataset_label="Dynamic World LULC",
            )
            if request.mode == "trend" or analysis_id == "change_detection":
                self._ensure_collection_has_data(
                    "GOOGLE/DYNAMICWORLD/V1",
                    geometry,
                    date(request.end_date.year, 1, 1),
                    date(request.end_date.year, 12, 31),
                    f"No Dynamic World LULC data is available for {request.end_date.year}.",
                    dataset_label="Dynamic World LULC",
                )
            return

        if analysis_id == "lulc_landsat":
            resolved_years, _ = self._resolve_landsat_lulc_complete_years(
                request.start_date.year,
                request.end_date.year,
                interval_years=max(1, int(request.interval_years or 1)),
            )
            if not resolved_years:
                raise RuntimeError(
                    "Landsat 8 LULC is available for complete years from 2013 onward. "
                    "Adjust the selected period to intersect that range."
                )
            return

        if analysis_id == "lulc_modis":
            available_years = self._resolve_modis_lulc_years(
                request.start_date,
                request.end_date,
                interval_years=max(1, int(request.interval_years or 1)),
            )
            if not available_years:
                raise RuntimeError(
                    "MODIS historical land cover is available from 2001 to 2024 in Earth Engine. "
                    "Adjust the selected period to intersect 2001 to 2024."
                )
            return

        if analysis_id in {"lst", "urban_heat_island", "ndvi", "land_degradation", "erosion_risk"}:
            self._ensure_collection_has_data(
                ["LANDSAT/LC08/C02/T1_L2", "LANDSAT/LC09/C02/T1_L2"],
                geometry,
                request.start_date,
                request.end_date,
                "No Landsat data is available for the selected period.",
                dataset_label="Landsat Collection 2",
            )
            if analysis_id == "erosion_risk":
                self._ensure_collection_has_data(
                    "UCSB-CHG/CHIRPS/DAILY",
                    geometry,
                    request.start_date,
                    request.end_date,
                    "No CHIRPS precipitation data is available for the selected period.",
                    dataset_label="CHIRPS precipitation",
                )
            return
        if analysis_id in {"ndwi", "soil_moisture"}:
            self._ensure_collection_has_data(
                ["LANDSAT/LC08/C02/T1_L2", "LANDSAT/LC09/C02/T1_L2"],
                geometry,
                request.start_date,
                request.end_date,
                "No Landsat data is available for the selected period.",
                dataset_label="Landsat Collection 2",
            )
            return
        if analysis_id == "habitat_fragmentation":
            if request.start_date.year < 2001 or request.end_date.year > 2024:
                raise RuntimeError(
                    "Habitat fragmentation data is only available for years 2001 to 2024. "
                    "Available years for this assessment are 2001 to 2024."
                )
            return

        if analysis_id == "flood":
            if (request.end_date - request.start_date).days > 730:
                raise RuntimeError(
                    "Flood Analysis works best with shorter date ranges. "
                    "Please reduce the selected period to about 24 months or less and run it again."
                )
            self._ensure_collection_has_data(
                "COPERNICUS/S1_GRD",
                geometry,
                request.start_date,
                request.end_date,
                "No Sentinel-1 flood data is available for the selected period.",
                dataset_label="Sentinel-1 GRD",
            )
            return

        if analysis_id == "drought":
            self._ensure_collection_has_data(
                ["LANDSAT/LC08/C02/T1_L2", "LANDSAT/LC09/C02/T1_L2"],
                geometry,
                request.start_date,
                request.end_date,
                "No Landsat data is available for the selected drought assessment period.",
                dataset_label="Landsat Collection 2",
            )
            return

        if analysis_id == "soil":
            return

        if analysis_id == "precipitation_anomaly":
            self._ensure_collection_has_data(
                "UCSB-CHG/CHIRPS/DAILY",
                geometry,
                request.start_date,
                request.end_date,
                "No CHIRPS precipitation data is available for the selected period.",
                dataset_label="CHIRPS precipitation",
            )
            return

        if analysis_id == "wind_direction":
            self._ensure_collection_has_data(
                "ECMWF/ERA5_LAND/HOURLY",
                geometry,
                request.start_date,
                request.end_date,
                "No ERA5-Land wind data is available for the selected period.",
                dataset_label="ERA5-Land wind",
            )
            return
        if analysis_id == "solar_radiation":
            self._ensure_collection_has_data(
                "MODIS/062/MCD18C2",
                geometry,
                request.start_date,
                request.end_date,
                "No solar radiation data is available for the selected period.",
                dataset_label="MODIS PAR solar radiation",
            )
            return

        if analysis_id == "carbon_emission":
            if request.start_date.year < 2001 or request.end_date.year > 2024:
                raise RuntimeError(
                    "Carbon emission proxy data is only available for years 2001 to 2024. "
                    "Available years for this assessment are 2001 to 2024."
                )
            return
        if analysis_id == "anthropogenic_emission":
            if request.start_date.year < 2012 or request.end_date.year > 2024:
                raise RuntimeError(
                    "Anthropogenic emission proxy data is only available for years 2012 to 2024. "
                    "Available years for this assessment are 2012 to 2024."
                )
            return

        if analysis_id == "carbon_sequestration":
            if request.start_date.year < 2001 or request.end_date.year > 2024:
                raise RuntimeError(
                    "Carbon sequestration data is only available for years 2001 to 2024. "
                    "Available years for this assessment are 2001 to 2024."
                )
            self._ensure_collection_has_data(
                "MODIS/061/MOD17A3HGF",
                geometry,
                request.start_date,
                request.end_date,
                "No carbon sequestration data is available for the selected year or date range.",
                dataset_label="MODIS NPP",
            )
            return

        if analysis_id == "wildfire_risk":
            self._ensure_collection_has_data(
                "MODIS/061/MCD64A1",
                geometry,
                request.start_date,
                request.end_date,
                "No MODIS burned area data is available for the selected period.",
                dataset_label="MODIS burned area",
            )
            return

        if analysis_id == "air_quality":
            if request.end_date.year < PM25_AVAILABLE_START_YEAR:
                raise RuntimeError(
                    f"PM2.5 data is available from {PM25_AVAILABLE_START_YEAR} to {PM25_AVAILABLE_END_YEAR}. "
                    "Select a period that overlaps the available PM2.5 archive."
                )
            effective_start, effective_end = self._pm25_effective_date_range(request.start_date, request.end_date)
            self._ensure_collection_has_data(
                PM25_COLLECTION_ID,
                geometry,
                effective_start,
                effective_end,
                "No satellite-derived PM2.5 data is available for the selected period.",
                dataset_label="Satellite-derived PM2.5",
            )
            return

        if analysis_id in {"terrain_susceptibility", "runoff_potential"}:
            if analysis_id == "runoff_potential":
                self._ensure_collection_has_data(
                    "UCSB-CHG/CHIRPS/DAILY",
                    geometry,
                    request.start_date,
                    request.end_date,
                    "No CHIRPS precipitation data is available for the selected period.",
                    dataset_label="CHIRPS precipitation",
                )
            return

    def _ensure_collection_has_data(self, dataset_ids, geometry, start_date, end_date, message, dataset_label=None):
        collection = None
        if isinstance(dataset_ids, list):
            for dataset_id in dataset_ids:
                dataset_collection = ee.ImageCollection(dataset_id)
                collection = dataset_collection if collection is None else collection.merge(dataset_collection)
        else:
            collection = ee.ImageCollection(dataset_ids)

        size = (
            collection.filterBounds(geometry)
            .filterDate(start_date.isoformat(), end_date.isoformat())
            .size()
            .getInfo()
        )
        if int(size or 0) <= 0:
            availability = self._collection_availability_message(collection, geometry, dataset_label or "Dataset")
            raise RuntimeError(f"{message} {availability}".strip())

    def _collection_availability_message(self, collection, geometry, dataset_label):
        bounded = collection.filterBounds(geometry)
        bounded_size = int(bounded.size().getInfo() or 0)
        if bounded_size <= 0:
            return f"No {dataset_label} records intersect the selected AOI."

        try:
            min_ts = bounded.aggregate_min("system:time_start").getInfo()
            max_ts = bounded.aggregate_max("system:time_start").getInfo()
        except Exception:
            min_ts = None
            max_ts = None

        if min_ts is None or max_ts is None:
            return f"{dataset_label} records intersect the selected AOI, but Earth Engine did not return a valid date range."

        min_date = ee.Date(min_ts).format("YYYY-MM-dd").getInfo()
        max_date = ee.Date(max_ts).format("YYYY-MM-dd").getInfo()
        min_year = ee.Date(min_ts).format("YYYY").getInfo()
        max_year = ee.Date(max_ts).format("YYYY").getInfo()
        if min_year == max_year:
            return f"Available AOI dates span {min_date} to {max_date}."
        return f"Available AOI dates span {min_date} to {max_date} (years {min_year} to {max_year})."

    def extract_aoi_geometry_jsons(self, layer):
        """Extract AOI geometries on the UI thread for later background use."""
        destination_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        transformer = QgsCoordinateTransform(layer.crs(), destination_crs, QgsProject.instance())
        geometries = []
        for feature in layer.getFeatures(QgsFeatureRequest()):
            geometry = QgsGeometry(feature.geometry())
            geometry.transform(transformer)
            geometries.append(json.loads(geometry.asJson()))

        if not geometries:
            raise RuntimeError("The AOI layer does not contain any polygon features.")
        return geometries

    def add_raster_to_project(
        self,
        raster_path,
        layer_name,
        analysis_id,
        mode,
        custom_classes=None,
        custom_range_classes=None,
        skip_style=False,
        value_scale=1.0,
    ):
        """Load the exported raster into the current QGIS project."""
        layer = QgsRasterLayer(raster_path, layer_name)
        if not layer.isValid():
            raise RuntimeError(f"Failed to load raster output: {raster_path}")
        provider = layer.dataProvider()
        if hasattr(provider, "setUserNoDataValue"):
            provider.setUserNoDataValue(1, [QgsRasterRange(-9999, -9999)])
        if custom_classes:
            layer.setRenderer(self.build_custom_paletted_renderer(layer, custom_classes))
            layer.triggerRepaint()
        elif custom_range_classes:
            if analysis_id in {"lst", "urban_heat_island"}:
                custom_range_classes = self._local_continuous_ramp_classes(
                    layer,
                    custom_range_classes,
                    value_scale=value_scale,
                )
            layer.setRenderer(self._build_range_renderer(layer, custom_range_classes))
            layer.triggerRepaint()
        elif not skip_style:
            self._apply_standard_style(layer, analysis_id, mode)
        QgsProject.instance().addMapLayer(layer)
        return layer

    def convert_raster_to_vector(
        self,
        raster_path,
        output_dir,
        output_name,
        analysis_id,
        mode,
        custom_classes=None,
        vector_context=None,
    ):
        """Polygonize raster output and enrich the vector with readable class metadata."""
        source_raster_path = (
            vector_context.get("vector_source_path")
            if vector_context and vector_context.get("vector_source_path")
            else raster_path
        )
        source_custom_classes = (
            vector_context.get("vector_custom_classes")
            if vector_context and vector_context.get("vector_custom_classes")
            else custom_classes
        )
        vector_path = Path(output_dir) / f"{self._sanitize_name(output_name)}_{analysis_id}_{mode}_vector.gpkg"
        result = processing.run(
            "gdal:polygonize",
            {
                "INPUT": source_raster_path,
                "BAND": 1,
                "FIELD": "pixel_value",
                "EIGHT_CONNECTEDNESS": False,
                "EXTRA": "",
                "OUTPUT": str(vector_path),
            },
        )
        created_path = result.get("OUTPUT", str(vector_path))
        layer = QgsVectorLayer(created_path, f"{output_name} Vector", "ogr")
        if not layer.isValid():
            raise RuntimeError(f"Failed to create vector output from raster: {created_path}")

        self._add_vector_metadata_fields(
            layer,
            analysis_id,
            mode,
            custom_classes=source_custom_classes,
            vector_context=vector_context,
        )
        QgsProject.instance().addMapLayer(layer)
        return {"vector_path": created_path, "layer": layer}

    def _run_snapshot(self, request, geometry, analysis, output_dir, safe_name, task=None):
        self._update_task_progress(task, 10, f"Computing {analysis['label']} imagery")
        if request.analysis_id == "change_detection":
            return self._run_change_detection_snapshot(request, geometry, analysis, output_dir, safe_name)
        if request.analysis_id == "lulc_landsat":
            return self._run_landsat_lulc_snapshot(request, geometry, analysis, output_dir, safe_name)
        if request.analysis_id == "lulc_modis":
            return self._run_worldcover_snapshot(request, geometry, analysis, output_dir, safe_name)

        image = self._build_snapshot_image(request.analysis_id, geometry, request.start_date, request.end_date)
        display_image = image
        custom_classes = None
        vector_context = None
        needs_class_products = bool(request.generate_reports or request.convert_to_vector)
        raster_path = self._available_raster_output_path(output_dir / f"{safe_name}_{request.analysis_id}.tif")

        if request.analysis_id == "flood" and request.convert_to_vector:
            depth_raster_path = output_dir / f"{safe_name}_{request.analysis_id}_depth.tif"
            self._download_image(
                self._build_flood_hazard_depth_image(geometry),
                geometry,
                depth_raster_path,
                90,
                data_type="float",
                fill_nodata=False,
            )
            vector_context = {
                "flood_depth_raster_path": str(depth_raster_path),
            }

        if request.analysis_id == "wind_direction":
            custom_classes = ANALYSIS_DEFINITIONS["wind_direction"]["summary_classes"]
            display_image = self._build_wind_direction_sector_image(geometry, request.start_date, request.end_date)
            classified_raster_path = output_dir / f"{safe_name}_{request.analysis_id}_classes.tif"
            self._download_image(
                display_image,
                geometry,
                classified_raster_path,
                analysis["scale"],
                data_type="int",
                fill_nodata=True,
            )
            wind_speed_raster_path = output_dir / f"{safe_name}_{request.analysis_id}_speed.tif"
            self._download_image(
                self._build_wind_speed_image(geometry, request.start_date, request.end_date),
                geometry,
                wind_speed_raster_path,
                analysis["scale"],
                data_type="float",
                fill_nodata=True,
            )
            vector_context = {
                "wind_speed_raster_path": str(wind_speed_raster_path),
                "vector_source_path": str(classified_raster_path),
                "vector_custom_classes": custom_classes,
            }

        continuous_display_ids = {"lst", "urban_heat_island", "ndwi"}
        if request.analysis_id in {
            "carbon_emission",
            "anthropogenic_emission",
            "carbon_sequestration",
            "ndvi",
            "lst",
            "urban_heat_island",
            "soil",
            "drought",
            "solar_radiation",
            "ndwi",
            "precipitation_anomaly",
            "soil_moisture",
            "erosion_risk",
            "terrain_susceptibility",
            "wildfire_risk",
            "air_quality",
            "habitat_fragmentation",
            "runoff_potential",
        }:
            if request.analysis_id in {
                "lst",
                "urban_heat_island",
                "soil",
                "soil_moisture",
                "ndvi",
                "ndwi",
            }:
                custom_classes = self._normalize_range_classes(analysis["summary_classes"])
            else:
                custom_classes = self._build_dynamic_range_classes(
                    image,
                    geometry,
                    analysis["scale"],
                    analysis["summary_classes"],
                )
            classified_raster_path = None
            if needs_class_products or request.analysis_id not in continuous_display_ids:
                classified_display_image = self._reclassify_range_image(image, custom_classes)
                classified_raster_path = self._available_raster_output_path(
                    output_dir / f"{safe_name}_{request.analysis_id}_classes.tif"
                )
                self._download_image(
                    classified_display_image,
                    geometry,
                    classified_raster_path,
                    analysis["scale"],
                    data_type="int",
                    fill_nodata=True,
                )
                if request.analysis_id in continuous_display_ids:
                    display_image = image
                else:
                    display_image = classified_display_image
            elif request.analysis_id in continuous_display_ids:
                display_image = image
            continuous_source_path = str(raster_path)
            if request.analysis_id in {"carbon_emission", "carbon_sequestration"}:
                continuous_raster_path = self._available_raster_output_path(
                    output_dir / f"{safe_name}_{request.analysis_id}_continuous.tif"
                )
                self._download_image(
                    image,
                    geometry,
                    continuous_raster_path,
                    analysis["scale"],
                    data_type="float",
                    fill_nodata=False,
                )
                continuous_source_path = str(continuous_raster_path)
            vector_context = {
                "vector_source_path": str(classified_raster_path) if classified_raster_path else continuous_source_path,
                "vector_custom_classes": custom_classes,
                "continuous_source_path": continuous_source_path,
            }

        raster_export_image = display_image
        raster_export_data_type = (
            "float" if request.analysis_id in continuous_display_ids else ("int" if custom_classes else "float")
        )
        raster_value_scale = 1.0
        self._update_task_progress(task, 72, f"Downloading {analysis['label']} raster")
        self._download_image(
            raster_export_image,
            geometry,
            raster_path,
            analysis["scale"],
            data_type=raster_export_data_type,
            fill_nodata=False,
            task=task,
            progress_value=78,
            stage_message=f"Downloading {analysis['label']} raster",
            download_timeout=180 if request.analysis_id in {"lst", "urban_heat_island"} else 60,
            tile_on_timeout=False if request.analysis_id in {"lst", "urban_heat_island"} else True,
        )

        summary_value = (
            self._compute_summary_stat(
                request.analysis_id,
                geometry,
                request.start_date,
                request.end_date,
                analysis["scale"],
            )
            if request.generate_reports
            else None
        )

        summary_rows = (
            self._build_class_area_summary_rows(
                request.analysis_id,
                request.mode,
                geometry,
                request.start_date,
                request.end_date,
                analysis["scale"],
            )
            if needs_class_products
            else []
        )
        detail_lines = []
        if request.analysis_id == "precipitation_anomaly" and request.generate_reports:
            current_mean, baseline_mean = self._compute_precipitation_current_and_baseline(geometry, request.start_date, request.end_date)
            detail_lines.extend(
                [
                    f"Current rainfall mean (mm/day): {current_mean}",
                    f"Baseline rainfall mean (mm/day): {baseline_mean}",
                ]
            )
            for row in summary_rows:
                row["current_mean_mm_day"] = current_mean
                row["baseline_mean_mm_day"] = baseline_mean
        self._update_task_progress(task, 82, "Building summary tables")
        summary_bundle = write_table_bundle(
            summary_rows,
            output_dir / f"{safe_name}_{request.analysis_id}_summary",
            sheet_name="RasterSummary",
        ) if request.generate_reports else {"csv_path": None, "xlsx_path": None}
        output_date_label = self._output_date_label(request.analysis_id, request.start_date, request.end_date)
        source_details = self._build_source_details(
            request.analysis_id,
            geometry,
            request.start_date,
            request.end_date,
            request.mode,
        )
        stack_outputs = []
        stack_paths = []
        if request.analysis_id == "lulc" and self._export_processed_stack_enabled(request):
            period_label = (
                str(request.start_date.year)
                if request.start_date.year == request.end_date.year
                else f"{request.start_date.year}-{request.end_date.year}"
            )
            stack_path = output_dir / f"Processed Data_sentinel Stack_{period_label}.tif"
            self._download_image(
                self._sentinel_processed_stack_image(geometry, request.start_date, request.end_date),
                geometry,
                stack_path,
                SENTINEL_PROCESSED_STACK_SCALE,
                data_type="float",
                fill_nodata=False,
                task=task,
                progress_value=80,
                stage_message="Downloading Sentinel processed stack",
            )
            stack_paths.append(str(stack_path))
            stack_outputs.append(
                {
                    "path": str(stack_path),
                    "label": f"Processed Data_sentinel Stack_{period_label}",
                    "analysis_id": request.analysis_id,
                    "mode": request.mode,
                    "skip_style": True,
                    "allow_vector": False,
                }
            )
            source_details.append(
                "Processed Sentinel stack: cloud-masked Sentinel-2 surface reflectance and derived indices "
                "(NDVI, NDWI, NDBI) for custom classification."
            )
        metadata_path = self._write_output_metadata(
            output_dir,
            safe_name,
            request.analysis_id,
            request.mode,
            analysis["label"],
            output_date_label=output_date_label,
            source_details=source_details,
        )

        return {
            "mode": "snapshot",
            "raster_path": str(raster_path),
            "raster_outputs": [
                {
                    "path": str(raster_path),
                    "label": analysis["label"],
                    "analysis_id": request.analysis_id,
                    "mode": request.mode,
                    "custom_classes": None if request.analysis_id in continuous_display_ids else custom_classes,
                    "custom_range_classes": (
                        analysis["summary_classes"]
                        if request.analysis_id in continuous_display_ids and request.analysis_id != "ndwi"
                        else None
                    ),
                    "value_scale": raster_value_scale,
                    "vector_context": vector_context,
                }
            ] + stack_outputs,
            "summary": {
                "label": analysis["stat_label"],
                "value": summary_value,
            },
            "output_date_label": output_date_label,
            "summary_table_csv_path": summary_bundle["csv_path"],
            "summary_table_xlsx_path": summary_bundle["xlsx_path"],
            "summary_rows": summary_rows,
            "detail_lines": detail_lines + source_details,
            "raw_stack_paths": stack_paths,
            "metadata_path": metadata_path,
        }

    def _run_trend(self, request, geometry, analysis, output_dir, safe_name, task=None):
        if request.analysis_id == "lulc":
            return self._run_lulc_trend(request, geometry, analysis, output_dir, safe_name, task=task)
        if request.analysis_id == "lulc_landsat":
            return self._run_landsat_lulc_trend(request, geometry, analysis, output_dir, safe_name, task=task)
        if request.analysis_id == "lulc_modis":
            return self._run_worldcover_trend(request, geometry, analysis, output_dir, safe_name, task=task)
        if request.analysis_id == "change_detection":
            return self._run_change_detection_snapshot(request, geometry, analysis, output_dir, safe_name)

        if request.generate_reports:
            rows = self._compute_trend_rows(
                request.analysis_id,
                geometry,
                request.start_date,
                request.end_date,
                analysis["scale"],
                interval_years=max(1, int(request.interval_years or 1)),
                task=task,
            )
            report_rows = self._build_interval_summary_report_rows(
                request.analysis_id,
                geometry,
                request.start_date,
                request.end_date,
                analysis["scale"],
                interval_years=max(1, int(request.interval_years or 1)),
                task=task,
            )
            if request.analysis_id == "land_degradation":
                report_rows = self._with_area_units_report_rows(report_rows, unit_label="sq m")
        else:
            rows = []
            report_rows = []
        trend_bundle = (
            write_table_bundle(
                report_rows,
                output_dir / f"{safe_name}_{request.analysis_id}_trend",
                sheet_name="Trend",
            )
            if request.generate_reports
            else {"csv_path": None, "xlsx_path": None}
        )
        graph_path = (
            create_trend_plot(
                rows,
                output_dir / f"{safe_name}_{request.analysis_id}_trend.svg",
                f"{analysis['label']} Trend",
                analysis["trend_label"],
            )
            if request.generate_reports
            else None
        )

        trend_image = self._build_trend_image(request.analysis_id, geometry, request.start_date, request.end_date)
        raster_path = None
        raster_output_classes = None
        raster_output_label = f"{analysis['label']} Trend Surface"
        if trend_image is not None:
            raster_path = output_dir / f"{safe_name}_{request.analysis_id}_trend_surface.tif"
            export_image = trend_image
            export_data_type = "float"
            raster_value_scale = 1.0
            if request.analysis_id == "land_degradation" and analysis.get("trend_classes"):
                raster_output_classes = self._normalize_range_classes(analysis["trend_classes"])
                export_image = self._reclassify_range_image(trend_image, raster_output_classes)
                export_data_type = "int"
                raster_output_label = f"{analysis['label']} Trend Classes"
            self._update_task_progress(task, 72, f"Downloading {analysis['label']} trend raster")
            self._download_image(
                export_image,
                geometry,
                raster_path,
                analysis["scale"],
                data_type=export_data_type,
                fill_nodata=False,
                task=task,
                progress_value=78,
                stage_message=f"Downloading {analysis['label']} trend raster",
                download_timeout=180 if request.analysis_id in {"lst", "urban_heat_island"} else 60,
                tile_on_timeout=False if request.analysis_id in {"lst", "urban_heat_island"} else True,
            )

        summary_rows = (
            self._build_class_area_summary_rows(
                request.analysis_id,
                request.mode,
                geometry,
                request.start_date,
                request.end_date,
                analysis["scale"],
            )
            if request.generate_reports
            else []
        )
        summary_bundle = (
            write_table_bundle(
                summary_rows,
                output_dir / f"{safe_name}_{request.analysis_id}_trend_summary",
                sheet_name="RasterSummary",
            )
            if request.generate_reports
            else {"csv_path": None, "xlsx_path": None}
        )
        output_date_label = self._output_date_label(request.analysis_id, request.start_date, request.end_date)
        source_details = self._build_source_details(
            request.analysis_id,
            geometry,
            request.start_date,
            request.end_date,
            request.mode,
        )
        metadata_path = self._write_output_metadata(
            output_dir,
            safe_name,
            request.analysis_id,
            request.mode,
            analysis["label"],
            output_date_label=output_date_label,
            source_details=source_details,
        )

        return {
            "mode": "trend",
            "trend_table_csv_path": trend_bundle["csv_path"],
            "trend_table_xlsx_path": trend_bundle["xlsx_path"],
            "graph_path": str(graph_path) if graph_path else None,
            "raster_path": str(raster_path) if raster_path else None,
            "raster_outputs": (
                [
                    {
                        "path": str(raster_path),
                        "label": raster_output_label,
                        "analysis_id": request.analysis_id,
                        "mode": request.mode,
                        "custom_classes": raster_output_classes,
                        "value_scale": raster_value_scale,
                    }
                ]
                if raster_path
                else []
            ),
            "rows": rows,
            "report_rows": report_rows,
            "output_date_label": output_date_label,
            "summary_table_csv_path": summary_bundle["csv_path"],
            "summary_table_xlsx_path": summary_bundle["xlsx_path"],
            "summary_rows": summary_rows,
            "detail_lines": source_details,
            "metadata_path": metadata_path,
        }

    def _run_lulc_trend(self, request, geometry, analysis, output_dir, safe_name, task=None):
        resolved_years, year_notes = self._resolve_lulc_complete_years(
            geometry,
            request.start_date.year,
            request.end_date.year,
            interval_years=max(1, int(request.interval_years or 1)),
        )
        start_year = resolved_years[0]
        end_year = resolved_years[-1]
        start_image = self._build_lulc_image(geometry, date(start_year, 1, 1), date(start_year, 12, 31))
        end_image = self._build_lulc_image(geometry, date(end_year, 1, 1), date(end_year, 12, 31))

        start_raster_path = output_dir / f"{safe_name}_lulc_{start_year}.tif"
        end_raster_path = output_dir / f"{safe_name}_lulc_{end_year}.tif"
        self._download_image(start_image, geometry, start_raster_path, analysis["scale"], data_type="int", fill_nodata=False)
        self._download_image(end_image, geometry, end_raster_path, analysis["scale"], data_type="int", fill_nodata=False)

        if request.generate_reports:
            year_class_rows = self._class_area_rows_by_year(
                resolved_years,
                lambda year: self._compute_lulc_class_area_rows_for_year(geometry, year, analysis["scale"]),
                task=task,
                progress_start=12,
                progress_span=58,
                message_template="Computing Sentinel class areas for {year}",
            )
            rows = self._dominant_trend_rows_from_class_area_rows(year_class_rows, resolved_years)
            report_rows = self._interval_report_rows_from_class_area_rows(year_class_rows, resolved_years)
            summary_rows = self._summary_rows_from_class_area_rows(
                year_class_rows,
                [start_year, end_year],
                period_labels={start_year: "start_year", end_year: "end_year"},
            )
        else:
            year_class_rows = []
            rows = []
            report_rows = []
            summary_rows = []
        trend_bundle = (
            write_table_bundle(
                report_rows,
                output_dir / f"{safe_name}_{request.analysis_id}_trend",
                sheet_name="Trend",
            )
            if request.generate_reports
            else {"csv_path": None, "xlsx_path": None}
        )
        graph_rows = [
            {"year": row["year"], "value": row["dominant_class_area_ha"]}
            for row in rows
        ]
        graph_path = (
            create_trend_plot(
                graph_rows,
                output_dir / f"{safe_name}_{request.analysis_id}_trend.svg",
                f"{analysis['label']} Dominant Class Trend",
                "Dominant class area (ha)",
            )
            if request.generate_reports
            else None
        )
        summary_bundle = (
            write_table_bundle(
                summary_rows,
                output_dir / f"{safe_name}_{request.analysis_id}_trend_summary",
                sheet_name="RasterSummary",
            )
            if request.generate_reports
            else {"csv_path": None, "xlsx_path": None}
        )
        output_date_label = self._output_date_label(request.analysis_id, request.start_date, request.end_date)
        source_details = self._build_source_details(
            request.analysis_id,
            geometry,
            request.start_date,
            request.end_date,
            request.mode,
        )
        stack_paths = []
        stack_outputs = []
        if self._export_processed_stack_enabled(request):
            start_stack_path = output_dir / f"Processed Data_sentinel Stack_{start_year}.tif"
            end_stack_path = output_dir / f"Processed Data_sentinel Stack_{end_year}.tif"
            self._download_image(
                self._sentinel_processed_stack_image(geometry, date(start_year, 1, 1), date(start_year, 12, 31)),
                geometry,
                start_stack_path,
                SENTINEL_PROCESSED_STACK_SCALE,
                data_type="float",
                fill_nodata=False,
                task=task,
                progress_value=80,
                stage_message=f"Downloading {start_year} Sentinel processed stack",
            )
            self._download_image(
                self._sentinel_processed_stack_image(geometry, date(end_year, 1, 1), date(end_year, 12, 31)),
                geometry,
                end_stack_path,
                SENTINEL_PROCESSED_STACK_SCALE,
                data_type="float",
                fill_nodata=False,
                task=task,
                progress_value=81,
                stage_message=f"Downloading {end_year} Sentinel processed stack",
            )
            stack_paths.extend([str(start_stack_path), str(end_stack_path)])
            stack_outputs.extend(
                [
                    {
                        "path": str(start_stack_path),
                        "label": f"Processed Data_sentinel Stack_{start_year}",
                        "analysis_id": request.analysis_id,
                        "mode": request.mode,
                        "skip_style": True,
                        "allow_vector": False,
                    },
                    {
                        "path": str(end_stack_path),
                        "label": f"Processed Data_sentinel Stack_{end_year}",
                        "analysis_id": request.analysis_id,
                        "mode": request.mode,
                        "skip_style": True,
                        "allow_vector": False,
                    },
                ]
            )
            source_details.append(
                "Processed Sentinel stack: cloud-masked Sentinel-2 surface reflectance and derived indices "
                "(NDVI, NDWI, NDBI) for custom classification."
            )
        source_details.extend(year_notes)
        metadata_path = self._write_output_metadata(
            output_dir,
            safe_name,
            request.analysis_id,
            request.mode,
            analysis["label"],
            output_date_label=output_date_label,
            source_details=source_details,
        )

        return {
            "mode": "trend",
            "trend_table_csv_path": trend_bundle["csv_path"],
            "trend_table_xlsx_path": trend_bundle["xlsx_path"],
            "graph_path": str(graph_path) if graph_path else None,
            "raster_outputs": [
                {
                    "path": str(start_raster_path),
                    "label": f"LULC {start_year}",
                    "analysis_id": request.analysis_id,
                    "mode": "snapshot",
                },
                {
                    "path": str(end_raster_path),
                    "label": f"LULC {end_year}",
                    "analysis_id": request.analysis_id,
                    "mode": "snapshot",
                },
            ] + stack_outputs,
            "output_date_label": output_date_label,
            "summary_table_csv_path": summary_bundle["csv_path"],
            "summary_table_xlsx_path": summary_bundle["xlsx_path"],
            "summary_rows": summary_rows,
            "rows": rows,
            "report_rows": report_rows,
            "detail_lines": source_details,
            "raw_stack_paths": stack_paths,
            "metadata_path": metadata_path,
        }

    def _run_landsat_lulc_snapshot(self, request, geometry, analysis, output_dir, safe_name):
        classifier = self._train_landsat_lulc_classifier(geometry)
        image = self._build_landsat_lulc_image(geometry, request.start_date, request.end_date, classifier=classifier)
        raster_path = output_dir / f"{safe_name}_{request.analysis_id}.tif"
        self._download_image(
            image,
            geometry,
            raster_path,
            analysis["scale"],
            data_type="int",
            fill_nodata=False,
            download_timeout=180,
            tile_on_timeout=False,
        )
        self._cleanup_local_categorical_raster(raster_path, threshold=8)
        raw_stack_paths = []
        raw_stack_outputs = []
        if self._export_processed_stack_enabled(request):
            period_label = (
                str(request.start_date.year)
                if request.start_date.year == request.end_date.year
                else f"{request.start_date.year}-{request.end_date.year}"
            )
            raw_stack_path = output_dir / f"Raw Data_landsat Stack_{period_label}.tif"
            self._download_image(
                self._landsat_raw_stack_image(geometry, request.start_date, request.end_date),
                geometry,
                raw_stack_path,
                analysis["scale"],
                data_type="float",
                fill_nodata=False,
                download_timeout=180,
                tile_on_timeout=False,
            )
            raw_stack_paths.append(str(raw_stack_path))
            raw_stack_outputs.append(
                {
                    "path": str(raw_stack_path),
                    "label": f"Raw Data_landsat Stack_{period_label}",
                    "analysis_id": request.analysis_id,
                    "mode": request.mode,
                    "skip_style": True,
                    "allow_vector": False,
                }
            )

        summary_rows = (
            self._compute_landsat_lulc_class_area_rows_for_period(
                geometry,
                request.start_date,
                request.end_date,
                analysis["scale"],
                classifier=classifier,
            )
            if request.generate_reports
            else []
        )
        summary_bundle = (
            write_table_bundle(
                summary_rows,
                output_dir / f"{safe_name}_{request.analysis_id}_summary",
                sheet_name="RasterSummary",
            )
            if request.generate_reports
            else {"csv_path": None, "xlsx_path": None}
        )
        dominant_row = max(summary_rows, key=lambda row: row["area_hectares"]) if summary_rows else None
        summary_value = round(float(dominant_row["area_hectares"]) if dominant_row else 0.0, 2)
        output_date_label = self._output_date_label(request.analysis_id, request.start_date, request.end_date)
        source_details = self._build_source_details(
            request.analysis_id,
            geometry,
            request.start_date,
            request.end_date,
            request.mode,
        )
        metadata_path = self._write_output_metadata(
            output_dir,
            safe_name,
            request.analysis_id,
            request.mode,
            analysis["label"],
            output_date_label=output_date_label,
            source_details=source_details,
        )
        return {
            "mode": "snapshot",
            "raster_path": str(raster_path),
            "raster_outputs": [
                {
                    "path": str(raster_path),
                    "label": analysis["label"],
                    "analysis_id": request.analysis_id,
                    "mode": request.mode,
                    "custom_classes": analysis["summary_classes"],
                }
            ] + raw_stack_outputs,
            "summary": {
                "label": analysis["stat_label"],
                "value": summary_value,
            },
            "output_date_label": output_date_label,
            "summary_table_csv_path": summary_bundle["csv_path"],
            "summary_table_xlsx_path": summary_bundle["xlsx_path"],
            "summary_rows": summary_rows,
            "detail_lines": source_details,
            "raw_stack_paths": raw_stack_paths,
            "metadata_path": metadata_path,
        }

    def _run_landsat_lulc_trend(self, request, geometry, analysis, output_dir, safe_name, task=None):
        self._update_task_progress(task, 8, "Training Landsat 8 comparison classifier")
        classifier = self._train_landsat_lulc_classifier(geometry)
        resolved_years, year_notes = self._resolve_landsat_lulc_complete_years(
            request.start_date.year,
            request.end_date.year,
            interval_years=max(1, int(request.interval_years or 1)),
        )
        start_year = resolved_years[0]
        end_year = resolved_years[-1]
        start_image = self._annual_landsat_lulc_image(geometry, start_year, classifier=classifier)
        end_image = self._annual_landsat_lulc_image(geometry, end_year, classifier=classifier)

        start_raster_path = output_dir / f"{safe_name}_{request.analysis_id}_{start_year}.tif"
        end_raster_path = output_dir / f"{safe_name}_{request.analysis_id}_{end_year}.tif"
        self._download_image(
            start_image,
            geometry,
            start_raster_path,
            analysis["scale"],
            data_type="int",
            fill_nodata=False,
            task=task,
            progress_value=74,
            stage_message=f"Downloading {start_year} Landsat raster",
            download_timeout=180,
            tile_on_timeout=False,
        )
        self._download_image(
            end_image,
            geometry,
            end_raster_path,
            analysis["scale"],
            data_type="int",
            fill_nodata=False,
            task=task,
            progress_value=78,
            stage_message=f"Downloading {end_year} Landsat raster",
            download_timeout=180,
            tile_on_timeout=False,
        )
        self._update_task_progress(task, 80, "Cleaning Landsat classification speckles")
        self._cleanup_local_categorical_raster(start_raster_path, threshold=8)
        self._cleanup_local_categorical_raster(end_raster_path, threshold=8)
        raw_stack_paths = []
        raw_stack_outputs = []
        if self._export_processed_stack_enabled(request):
            start_stack_path = output_dir / f"Raw Data_landsat Stack_{start_year}.tif"
            end_stack_path = output_dir / f"Raw Data_landsat Stack_{end_year}.tif"
            self._download_image(
                self._landsat_raw_stack_image(geometry, date(start_year, 1, 1), date(start_year, 12, 31)),
                geometry,
                start_stack_path,
                analysis["scale"],
                data_type="float",
                fill_nodata=False,
                task=task,
                progress_value=79,
                stage_message=f"Downloading {start_year} raw Landsat stack",
                download_timeout=180,
                tile_on_timeout=False,
            )
            self._download_image(
                self._landsat_raw_stack_image(geometry, date(end_year, 1, 1), date(end_year, 12, 31)),
                geometry,
                end_stack_path,
                analysis["scale"],
                data_type="float",
                fill_nodata=False,
                task=task,
                progress_value=80,
                stage_message=f"Downloading {end_year} raw Landsat stack",
                download_timeout=180,
                tile_on_timeout=False,
            )
            raw_stack_paths.extend([str(start_stack_path), str(end_stack_path)])
            raw_stack_outputs.extend(
                [
                    {
                        "path": str(start_stack_path),
                        "label": f"Raw Data_landsat Stack_{start_year}",
                        "analysis_id": request.analysis_id,
                        "mode": request.mode,
                        "skip_style": True,
                        "allow_vector": False,
                    },
                    {
                        "path": str(end_stack_path),
                        "label": f"Raw Data_landsat Stack_{end_year}",
                        "analysis_id": request.analysis_id,
                        "mode": request.mode,
                        "skip_style": True,
                        "allow_vector": False,
                    },
                ]
            )

        if request.generate_reports:
            self._update_task_progress(task, 82, "Computing annual Landsat class areas")
            year_class_rows = self._class_area_rows_by_year(
                resolved_years,
                lambda year: self._compute_landsat_lulc_class_area_rows_for_year(
                    geometry,
                    year,
                    analysis["scale"],
                    classifier=classifier,
                ),
                task=task,
                progress_start=82,
                progress_span=7,
                message_template="Computing Landsat class areas for {year}",
            )
            rows = self._dominant_trend_rows_from_class_area_rows(year_class_rows, resolved_years)
            self._update_task_progress(task, 90, "Building Landsat interval trend table")
            report_rows = self._interval_report_rows_from_class_area_rows(year_class_rows, resolved_years)
            summary_rows = self._summary_rows_from_class_area_rows(
                year_class_rows,
                resolved_years,
                period_labels={year: str(year) for year in resolved_years},
            )
        else:
            year_class_rows = []
            rows = []
            report_rows = []
            summary_rows = []
        trend_bundle = (
            write_table_bundle(
                report_rows,
                output_dir / f"{safe_name}_{request.analysis_id}_trend",
                sheet_name="Trend",
                xlsx_options={"extra_sheets": self._landsat_trend_workbook_sheets()},
            )
            if request.generate_reports
            else {"csv_path": None, "xlsx_path": None}
        )
        graph_rows = [{"year": row["year"], "value": row["dominant_class_area_ha"]} for row in rows]
        graph_path = (
            create_trend_plot(
                graph_rows,
                output_dir / f"{safe_name}_{request.analysis_id}_trend.svg",
                f"{analysis['label']} Dominant Class Trend",
                "Dominant class area (ha)",
            )
            if request.generate_reports
            else None
        )
        summary_bundle = (
            write_table_bundle(
                summary_rows,
                output_dir / f"{safe_name}_{request.analysis_id}_trend_summary",
                sheet_name="RasterSummary",
                xlsx_options={"extra_sheets": self._landsat_trend_workbook_sheets()},
            )
            if request.generate_reports
            else {"csv_path": None, "xlsx_path": None}
        )
        output_date_label = f"{start_year}-01-01 to {end_year}-12-31 (complete Landsat years used)"
        source_details = self._build_source_details(
            request.analysis_id,
            geometry,
            date(start_year, 1, 1),
            date(end_year, 12, 31),
            request.mode,
        )
        if self._export_processed_stack_enabled(request):
            source_details.append(
                "Raw Landsat stack: radiometrically corrected surface reflectance, thermal band, and derived indices "
                "(NDVI, NDWI, NDMI, NDBI, LST_C) for custom analysis."
            )
        source_details.extend(year_notes)
        metadata_path = self._write_output_metadata(
            output_dir,
            safe_name,
            request.analysis_id,
            request.mode,
            analysis["label"],
            output_date_label=output_date_label,
            source_details=source_details,
        )
        return {
            "mode": "trend",
            "trend_table_csv_path": trend_bundle["csv_path"],
            "trend_table_xlsx_path": trend_bundle["xlsx_path"],
            "graph_path": str(graph_path) if graph_path else None,
            "raster_outputs": [
                {
                    "path": str(start_raster_path),
                    "label": f"{analysis['label']} {start_year}",
                    "analysis_id": request.analysis_id,
                    "mode": "snapshot",
                    "custom_classes": analysis["summary_classes"],
                },
                {
                    "path": str(end_raster_path),
                    "label": f"{analysis['label']} {end_year}",
                    "analysis_id": request.analysis_id,
                    "mode": "snapshot",
                    "custom_classes": analysis["summary_classes"],
                },
            ] + raw_stack_outputs,
            "output_date_label": output_date_label,
            "summary_table_csv_path": summary_bundle["csv_path"],
            "summary_table_xlsx_path": summary_bundle["xlsx_path"],
            "summary_rows": summary_rows,
            "rows": rows,
            "report_rows": report_rows,
            "detail_lines": source_details,
            "raw_stack_paths": raw_stack_paths,
            "metadata_path": metadata_path,
        }

    def _run_worldcover_snapshot(self, request, geometry, analysis, output_dir, safe_name):
        resolved_years = self._resolve_modis_lulc_years(request.start_date, request.end_date)
        selected_year = resolved_years[-1]
        image = self._build_worldcover_image_for_year(geometry, selected_year)
        raster_path = output_dir / f"{safe_name}_{request.analysis_id}_{selected_year}.tif"
        self._download_image(image, geometry, raster_path, analysis["scale"], data_type="int", fill_nodata=False)

        summary_rows = (
            self._compute_worldcover_class_area_rows_for_year(geometry, selected_year, analysis["scale"])
            if request.generate_reports
            else []
        )
        summary_bundle = write_table_bundle(
            summary_rows,
            output_dir / f"{safe_name}_{request.analysis_id}_summary",
            sheet_name="RasterSummary",
        ) if request.generate_reports else {"csv_path": None, "xlsx_path": None}

        output_date_label = f"{selected_year}-01-01 to {selected_year}-12-31 (MODIS land-cover year used)"
        source_details = [
            f"MODIS yearly land-cover product was used for {selected_year}.",
            "This historical comparison product is available from 2001 to 2024 in Earth Engine.",
        ]
        metadata_path = self._write_output_metadata(
            output_dir,
            safe_name,
            request.analysis_id,
            request.mode,
            analysis["label"],
            output_date_label=output_date_label,
            source_details=source_details,
        )
        dominant_row = max(summary_rows, key=lambda row: row["area_hectares"]) if summary_rows else None

        return {
            "mode": "snapshot",
            "raster_path": str(raster_path),
            "raster_outputs": [
                {
                    "path": str(raster_path),
                    "label": f"{analysis['label']} {selected_year}",
                    "analysis_id": request.analysis_id,
                    "mode": request.mode,
                    "custom_classes": analysis["summary_classes"],
                }
            ],
            "summary": {
                "label": analysis["stat_label"],
                "value": dominant_row["area_hectares"] if dominant_row else 0.0,
            },
            "output_date_label": output_date_label,
            "summary_table_csv_path": summary_bundle["csv_path"],
            "summary_table_xlsx_path": summary_bundle["xlsx_path"],
            "summary_rows": summary_rows,
            "detail_lines": source_details,
            "metadata_path": metadata_path,
        }

    def _run_worldcover_trend(self, request, geometry, analysis, output_dir, safe_name, task=None):
        years = self._resolve_modis_lulc_years(
            request.start_date,
            request.end_date,
            interval_years=max(1, int(request.interval_years or 1)),
        )
        if not years:
            raise RuntimeError(
                "MODIS historical land cover is available from 2001 to 2024 in Earth Engine. "
                "Adjust the selected period to intersect 2001 to 2024."
            )

        start_year = years[0]
        end_year = years[-1]
        start_image = self._build_worldcover_image_for_year(geometry, start_year)
        end_image = self._build_worldcover_image_for_year(geometry, end_year)
        start_raster_path = output_dir / f"{safe_name}_{request.analysis_id}_{start_year}.tif"
        end_raster_path = output_dir / f"{safe_name}_{request.analysis_id}_{end_year}.tif"
        self._download_image(start_image, geometry, start_raster_path, analysis["scale"], data_type="int", fill_nodata=False)
        self._download_image(end_image, geometry, end_raster_path, analysis["scale"], data_type="int", fill_nodata=False)

        if request.generate_reports:
            rows = []
            for year in years:
                class_rows = self._compute_worldcover_class_area_rows_for_year(geometry, year, analysis["scale"])
                dominant_row = max(class_rows, key=lambda row: row["area_hectares"]) if class_rows else None
                rows.append(
                    {
                        "year": year,
                        "dominant_class": dominant_row["class_label"] if dominant_row else "No data",
                        "dominant_class_area_ha": dominant_row["area_hectares"] if dominant_row else 0.0,
                    }
                )
            rows = self._append_annual_change_metrics(rows, include_text_flags=True)
            report_rows = self._build_interval_summary_report_rows(
                request.analysis_id,
                geometry,
                request.start_date,
                request.end_date,
                analysis["scale"],
                resolved_years=years,
                task=task,
            )
        else:
            rows = []
            report_rows = []
        trend_bundle = (
            write_table_bundle(
                report_rows,
                output_dir / f"{safe_name}_{request.analysis_id}_trend",
                sheet_name="Trend",
            )
            if request.generate_reports
            else {"csv_path": None, "xlsx_path": None}
        )
        graph_path = (
            create_trend_plot(
                [{"year": row["year"], "value": row["dominant_class_area_ha"]} for row in rows],
                output_dir / f"{safe_name}_{request.analysis_id}_trend.svg",
                f"{analysis['label']} Dominant Class Trend",
                "Dominant class area (ha)",
            )
            if request.generate_reports
            else None
        )

        summary_rows = []
        if request.generate_reports:
            for year in years:
                summary_rows.extend(
                    self._compute_worldcover_class_area_rows_for_year(
                        geometry,
                        year,
                        analysis["scale"],
                        period_label=str(year),
                    )
                )
        summary_bundle = (
            write_table_bundle(
                summary_rows,
                output_dir / f"{safe_name}_{request.analysis_id}_trend_summary",
                sheet_name="RasterSummary",
            )
            if request.generate_reports
            else {"csv_path": None, "xlsx_path": None}
        )
        output_date_label = f"{start_year}-01-01 to {end_year}-12-31 (MODIS land-cover years used)"
        source_details = [
            "MODIS historical land cover is available from 2001 to 2024 in Earth Engine.",
            f"The selected output used these available MODIS land-cover year(s): {', '.join(str(year) for year in years)}.",
        ]
        metadata_path = self._write_output_metadata(
            output_dir,
            safe_name,
            request.analysis_id,
            request.mode,
            analysis["label"],
            output_date_label=output_date_label,
            source_details=source_details,
        )

        return {
            "mode": "trend",
            "trend_table_csv_path": trend_bundle["csv_path"],
            "trend_table_xlsx_path": trend_bundle["xlsx_path"],
            "graph_path": str(graph_path) if graph_path else None,
            "raster_outputs": [
                {
                    "path": str(start_raster_path),
                    "label": f"{analysis['label']} {start_year}",
                    "analysis_id": request.analysis_id,
                    "mode": "snapshot",
                    "custom_classes": analysis["summary_classes"],
                },
                {
                    "path": str(end_raster_path),
                    "label": f"{analysis['label']} {end_year}",
                    "analysis_id": request.analysis_id,
                    "mode": "snapshot",
                    "custom_classes": analysis["summary_classes"],
                },
            ],
            "output_date_label": output_date_label,
            "summary_table_csv_path": summary_bundle["csv_path"],
            "summary_table_xlsx_path": summary_bundle["xlsx_path"],
            "summary_rows": summary_rows,
            "rows": rows,
            "report_rows": report_rows,
            "detail_lines": source_details,
            "metadata_path": metadata_path,
        }

    def _run_change_detection_snapshot(self, request, geometry, analysis, output_dir, safe_name):
        self._raise_if_canceled(None)
        resolved_years, year_notes = self._resolve_lulc_complete_years(
            geometry,
            request.start_date.year,
            request.end_date.year,
            interval_years=max(1, int(request.interval_years or 1)),
        )
        start_year = resolved_years[0]
        end_year = resolved_years[-1]
        start_year_date = date(start_year, 1, 1)
        end_year_date = date(end_year, 12, 31)
        start_lulc_image = self._build_lulc_modal_label_image(geometry, start_year_date, date(start_year, 12, 31))
        end_lulc_image = self._build_lulc_modal_label_image(geometry, date(end_year, 1, 1), end_year_date)
        binary_change_image = self._build_change_detection_from_lulc(start_lulc_image, end_lulc_image, geometry)
        transition_image = self._build_change_transition_from_lulc(start_lulc_image, end_lulc_image, geometry)
        transition_rows = (
            self._compute_change_transition_rows_from_image(transition_image, geometry, analysis["scale"])
            if request.generate_reports
            else []
        )
        start_raster_path = output_dir / f"{safe_name}_{request.analysis_id}_lulc_{start_year}.tif"
        end_raster_path = output_dir / f"{safe_name}_{request.analysis_id}_lulc_{end_year}.tif"
        binary_raster_path = output_dir / f"{safe_name}_{request.analysis_id}_changed_areas.tif"
        transition_raster_path = output_dir / f"{safe_name}_{request.analysis_id}_transitions.tif"
        self._download_image(start_lulc_image, geometry, start_raster_path, analysis["scale"], data_type="int", fill_nodata=False)
        self._download_image(end_lulc_image, geometry, end_raster_path, analysis["scale"], data_type="int", fill_nodata=False)
        self._download_image(binary_change_image, geometry, binary_raster_path, analysis["scale"], data_type="int", fill_nodata=False)
        self._download_image(transition_image, geometry, transition_raster_path, analysis["scale"], data_type="int", fill_nodata=False)

        transition_bundle = (
            write_table_bundle(
                transition_rows,
                output_dir / f"{safe_name}_{request.analysis_id}_transitions",
                sheet_name="Transitions",
            )
            if request.generate_reports
            else {"csv_path": None, "xlsx_path": None}
        )

        changed_area = (
            round(
                sum(row["area_hectares"] for row in transition_rows if row["transition_code"] != 0),
                2,
            )
            if request.generate_reports
            else None
        )

        return {
            "mode": "snapshot",
            "raster_path": str(binary_raster_path),
            "raster_outputs": [
                {
                    "path": str(start_raster_path),
                    "label": f"LULC {start_year}",
                    "analysis_id": "lulc",
                    "mode": "snapshot",
                },
                {
                    "path": str(end_raster_path),
                    "label": f"LULC {end_year}",
                    "analysis_id": "lulc",
                    "mode": "snapshot",
                },
                {
                    "path": str(binary_raster_path),
                    "label": "Change Detection Binary",
                    "analysis_id": request.analysis_id,
                    "mode": request.mode,
                    "custom_classes": CHANGE_CLASSES,
                },
                {
                    "path": str(transition_raster_path),
                    "label": "Change Detection Transitions",
                    "analysis_id": request.analysis_id,
                    "mode": request.mode,
                    "custom_classes": (
                        self._transition_classes_from_rows(transition_rows)
                        if transition_rows
                        else self._all_transition_classes()
                    ),
                }
            ],
            "summary": {
                "label": analysis["stat_label"],
                "value": changed_area,
            },
            "output_date_label": self._output_date_label(request.analysis_id, start_year_date, end_year_date),
            "summary_table_csv_path": transition_bundle["csv_path"],
            "summary_table_xlsx_path": transition_bundle["xlsx_path"],
            "summary_rows": transition_rows,
            "metadata_path": self._write_output_metadata(
                output_dir,
                safe_name,
                request.analysis_id,
                request.mode,
                analysis["label"],
                output_date_label=self._output_date_label(request.analysis_id, start_year_date, end_year_date),
                source_details=self._build_source_details(
                    request.analysis_id,
                    geometry,
                    start_year_date,
                    end_year_date,
                    request.mode,
                )
                + year_notes,
            ),
            "detail_lines": self._build_source_details(
                request.analysis_id,
                geometry,
                start_year_date,
                end_year_date,
                request.mode,
            )
            + year_notes,
        }

    def _compute_trend_rows(self, analysis_id, geometry, start_date, end_date, scale, interval_years=1, task=None):
        rows = []
        years = list(range(start_date.year, end_date.year + 1, max(1, interval_years)))
        if years and years[-1] != end_date.year:
            years.append(end_date.year)

        total_years = len(years) or 1
        for index, year in enumerate(years):
            self._raise_if_canceled(task)
            year_start = date(year, 1, 1)
            year_end = date(year, 12, 31)
            if analysis_id == "wind_direction":
                value = self._compute_wind_speed_stat(geometry, year_start, year_end)
                direction = self._compute_wind_direction_stat(geometry, year_start, year_end)
                row = {"year": year, "value": value}
                row["direction_degrees"] = round(direction, 2)
                row["direction_label"] = self._direction_label_for_degrees(direction)
            elif analysis_id == "land_degradation":
                summary_rows = self._compute_land_degradation_class_area_rows_for_year(
                    geometry,
                    start_date.year,
                    year,
                    scale,
                )
                degraded_row = next(
                    (
                        summary_row
                        for summary_row in summary_rows
                        if summary_row.get("class_label") == "Potentially degraded"
                    ),
                    None,
                )
                value = round(float(degraded_row["area_hectares"]) if degraded_row else 0.0, 2)
                row = {"year": year, "value": value}
                self._append_summary_rows_metrics(row, summary_rows)
            else:
                value = self._compute_summary_stat(analysis_id, geometry, year_start, year_end, scale)
                row = {"year": year, "value": value}
            if analysis_id != "land_degradation":
                self._append_yearly_summary_metrics(row, analysis_id, geometry, year_start, year_end, scale)
            rows.append(row)
            self._update_task_progress(task, 10 + int(((index + 1) / total_years) * 70))
        return self._append_annual_change_metrics(rows)

    def _append_yearly_summary_metrics(self, row, analysis_id, geometry, start_date, end_date, scale):
        analysis = ANALYSIS_DEFINITIONS[analysis_id]
        if analysis["summary_mode"] == "discrete":
            summary_rows = self._build_class_area_summary_rows(analysis_id, "snapshot", geometry, start_date, end_date, scale)
            self._append_summary_rows_metrics(row, summary_rows)
        else:
            image = self._build_snapshot_image(analysis_id, geometry, start_date, end_date)
            band_name = analysis["band_name"]
            stats = image.reduceRegion(
                reducer=ee.Reducer.minMax().combine(ee.Reducer.stdDev(), sharedInputs=True),
                geometry=geometry,
                scale=scale,
                maxPixels=1_000_000_000,
                bestEffort=True,
            ).getInfo() or {}
            row["min_value"] = round(float(stats.get(f"{band_name}_min", 0.0)), 5)
            row["max_value"] = round(float(stats.get(f"{band_name}_max", 0.0)), 5)
            row["std_dev"] = round(float(stats.get(f"{band_name}_stdDev", 0.0)), 5)
            summary_rows = self._build_class_area_summary_rows(analysis_id, "snapshot", geometry, start_date, end_date, scale)
            self._append_summary_rows_metrics(row, summary_rows)

    def _append_summary_rows_metrics(self, row, summary_rows):
        for summary_row in summary_rows:
            label = summary_row.get("class_label") or summary_row.get("transition_label") or summary_row.get("from_class") or "class"
            key = self._safe_metric_key(label)
            row[f"{key}_area_sq_m"] = summary_row.get("area_sq_m")
            row[f"{key}_area_ha"] = summary_row.get("area_hectares")
            row[f"{key}_percent"] = summary_row.get("percent_of_aoi")

    def _safe_metric_key(self, text):
        return "".join(ch.lower() if ch.isalnum() else "_" for ch in text).strip("_")

    def _compute_summary_stat(self, analysis_id, geometry, start_date, end_date, scale):
        if analysis_id == "lulc":
            histogram_info = self._frequency_histogram(
                self._build_lulc_image(geometry, start_date, end_date),
                "classification",
                geometry,
                scale,
            )
            if not histogram_info:
                return 0.0
            dominant_count = max(float(count) for count in histogram_info.values())
            return round((dominant_count * (scale * scale)) / 10000.0, 2)
        if analysis_id == "lulc_landsat":
            class_rows = self._compute_landsat_lulc_class_area_rows_for_period(
                geometry,
                start_date,
                end_date,
                scale,
            )
            dominant_row = max(class_rows, key=lambda row: row["area_hectares"]) if class_rows else None
            return round(float(dominant_row["area_hectares"]) if dominant_row else 0.0, 2)
        if analysis_id == "lulc_modis":
            selected_years = self._resolve_modis_lulc_years(start_date, end_date)
            selected_year = selected_years[-1]
            class_rows = self._compute_worldcover_class_area_rows_for_year(geometry, selected_year, scale)
            dominant_row = max(class_rows, key=lambda row: row["area_hectares"]) if class_rows else None
            return round(float(dominant_row["area_hectares"]) if dominant_row else 0.0, 2)

        if analysis_id in {"change_detection", "flood", "land_degradation"}:
            image = self._build_snapshot_image(analysis_id, geometry, start_date, end_date)
            area = self._sum_binary_area(image, ANALYSIS_DEFINITIONS[analysis_id]["band_name"], geometry, scale)
            return round(area / 10000.0, 2)

        if analysis_id == "wind_direction":
            return round(self._compute_wind_direction_stat(geometry, start_date, end_date), 2)

        image = self._build_snapshot_image(analysis_id, geometry, start_date, end_date)
        band_name = ANALYSIS_DEFINITIONS[analysis_id]["band_name"]
        value = image.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geometry,
            scale=scale,
            maxPixels=1_000_000_000,
            bestEffort=True,
        ).get(band_name)
        return round(float(value.getInfo() or 0.0), 4)

    def _build_class_area_summary_rows(self, analysis_id, mode, geometry, start_date, end_date, scale):
        if analysis_id == "change_detection":
            return self._compute_change_transition_rows(geometry, start_date, end_date, scale)

        if analysis_id == "lulc" and mode == "trend":
            start_rows = self._compute_lulc_class_area_rows_for_year(geometry, start_date.year, scale, "start_year")
            end_rows = self._compute_lulc_class_area_rows_for_year(geometry, end_date.year, scale, "end_year")
            return start_rows + end_rows
        if analysis_id == "lulc_landsat" and mode == "trend":
            start_rows = self._compute_landsat_lulc_class_area_rows_for_year(
                geometry,
                start_date.year,
                scale,
                "start_year",
            )
            end_rows = self._compute_landsat_lulc_class_area_rows_for_year(
                geometry,
                end_date.year,
                scale,
                "end_year",
            )
            return start_rows + end_rows
        if analysis_id == "lulc_modis" and mode == "trend":
            start_rows = self._compute_worldcover_class_area_rows_for_year(
                geometry,
                start_date.year,
                scale,
                "start_year",
            )
            end_rows = self._compute_worldcover_class_area_rows_for_year(
                geometry,
                end_date.year,
                scale,
                "end_year",
            )
            return start_rows + end_rows

        summary_image, classes = self._build_summary_image_and_classes(
            analysis_id,
            mode,
            geometry,
            start_date,
            end_date,
        )
        histogram_info = self._frequency_histogram(summary_image, "summary_class", geometry, scale)
        rows = []
        total_area = 0.0
        for item in classes:
            class_value = item["value"]
            pixel_count = float(histogram_info.get(str(class_value), histogram_info.get(class_value, 0.0)))
            area_sq_m = pixel_count * (scale * scale)
            total_area += area_sq_m
            rows.append(
                {
                    "class_code": class_value,
                    "class_label": item["label"],
                    "area_sq_m": round(area_sq_m, 2),
                    "area_hectares": round(area_sq_m / 10000.0, 4),
                    "value_min": item.get("min"),
                    "value_max": item.get("max"),
                }
            )

        for row in rows:
            row["percent_of_aoi"] = round((row["area_sq_m"] / total_area * 100.0), 2) if total_area else 0.0
        return rows

    def _class_area_rows_by_year(
        self,
        years,
        compute_rows_for_year,
        task=None,
        progress_start=10,
        progress_span=70,
        message_template="Computing class areas for {year}",
    ):
        year_rows = {}
        total_years = len(years) or 1
        for index, year in enumerate(years):
            self._raise_if_canceled(task)
            self._update_task_progress(
                task,
                progress_start + int((index / total_years) * progress_span),
                message_template.format(year=year),
            )
            year_rows[year] = compute_rows_for_year(year)
            self._update_task_progress(
                task,
                progress_start + int(((index + 1) / total_years) * progress_span),
                f"Finished class areas for {year}",
            )
        return year_rows

    def _dominant_trend_rows_from_class_area_rows(self, year_class_rows, years):
        rows = []
        for year in years:
            class_rows = year_class_rows.get(year, [])
            dominant_row = max(class_rows, key=lambda row: row["area_hectares"]) if class_rows else None
            rows.append(
                {
                    "year": year,
                    "dominant_class": dominant_row["class_label"] if dominant_row else "No data",
                    "dominant_class_area_ha": dominant_row["area_hectares"] if dominant_row else 0.0,
                }
            )
        return self._append_annual_change_metrics(rows, include_text_flags=True)

    def _interval_report_rows_from_class_area_rows(self, year_class_rows, years):
        labels_in_order = []
        seen_labels = set()
        year_summaries = {}
        for year in years:
            summary_map = {}
            for row in year_class_rows.get(year, []):
                label = row.get("class_label") or row.get("transition_label") or row.get("from_class") or "class"
                summary_map[label] = round(float(row.get("area_sq_m", 0.0)), 5)
                if label not in seen_labels:
                    seen_labels.add(label)
                    labels_in_order.append(label)
            year_summaries[str(year)] = summary_map

        report_rows = []
        for label in labels_in_order:
            row = {"class_label": label}
            for year in years:
                row[str(year)] = year_summaries.get(str(year), {}).get(label, 0.0)
            report_rows.append(row)
        return report_rows

    @staticmethod
    def _summary_rows_from_class_area_rows(year_class_rows, years, period_labels=None):
        rows = []
        period_labels = period_labels or {}
        for year in years:
            for row in year_class_rows.get(year, []):
                summary_row = dict(row)
                if year in period_labels:
                    summary_row["period"] = period_labels[year]
                rows.append(summary_row)
        return rows

    def _compute_lulc_trend_rows(self, geometry, years, scale, task=None):
        rows = []
        total_years = len(years) or 1
        for index, year in enumerate(years):
            self._raise_if_canceled(task)
            class_rows = self._compute_lulc_class_area_rows_for_year(geometry, year, scale)
            dominant_row = max(class_rows, key=lambda row: row["area_hectares"]) if class_rows else None
            rows.append(
                {
                    "year": year,
                    "dominant_class": dominant_row["class_label"] if dominant_row else "No data",
                    "dominant_class_area_ha": dominant_row["area_hectares"] if dominant_row else 0.0,
                }
            )
            self._update_task_progress(task, 10 + int(((index + 1) / total_years) * 70))
        return self._append_annual_change_metrics(rows, include_text_flags=True)

    def _compute_landsat_lulc_trend_rows(self, geometry, years, scale, classifier=None, task=None):
        rows = []
        total_years = len(years) or 1
        for index, year in enumerate(years):
            self._raise_if_canceled(task)
            self._update_task_progress(
                task,
                82 + int((index / total_years) * 7),
                f"Computing Landsat class areas for {year}",
            )
            class_rows = self._compute_landsat_lulc_class_area_rows_for_year(geometry, year, scale, classifier=classifier)
            dominant_row = max(class_rows, key=lambda row: row["area_hectares"]) if class_rows else None
            rows.append(
                {
                    "year": year,
                    "dominant_class": dominant_row["class_label"] if dominant_row else "No data",
                    "dominant_class_area_ha": dominant_row["area_hectares"] if dominant_row else 0.0,
                }
            )
            self._update_task_progress(
                task,
                82 + int(((index + 1) / total_years) * 7),
                f"Finished Landsat class areas for {year}",
            )
        return self._append_annual_change_metrics(rows, include_text_flags=True)

    def _build_interval_summary_report_rows(
        self,
        analysis_id,
        geometry,
        start_date,
        end_date,
        scale,
        interval_years=1,
        resolved_years=None,
        task=None,
    ):
        years = resolved_years or self._year_sequence(start_date.year, end_date.year, interval_years)
        if not years:
            return []

        year_summaries = {}
        labels_in_order = []
        seen_labels = set()
        total_years = len(years) or 1

        for index, year in enumerate(years):
            self._raise_if_canceled(task)
            year_start = date(year, 1, 1)
            year_end = date(year, 12, 31)
            if analysis_id == "lulc":
                summary_rows = self._compute_lulc_class_area_rows_for_year(geometry, year, scale)
            elif analysis_id == "lulc_landsat":
                summary_rows = self._compute_landsat_lulc_class_area_rows_for_year(geometry, year, scale)
            elif analysis_id == "land_degradation":
                summary_rows = self._compute_land_degradation_class_area_rows_for_year(
                    geometry,
                    start_date.year,
                    year,
                    scale,
                )
            else:
                summary_rows = self._build_class_area_summary_rows(analysis_id, "snapshot", geometry, year_start, year_end, scale)

            summary_map = {}
            for row in summary_rows:
                label = row.get("class_label") or row.get("transition_label") or row.get("from_class") or "class"
                summary_map[label] = round(float(row.get("area_sq_m", 0.0)), 5)
                if label not in seen_labels:
                    seen_labels.add(label)
                    labels_in_order.append(label)
            year_summaries[str(year)] = summary_map
            self._update_task_progress(task, 10 + int(((index + 1) / total_years) * 70))

        report_rows = []
        for label in labels_in_order:
            row = {"class_label": label}
            for year in years:
                row[str(year)] = year_summaries.get(str(year), {}).get(label, 0.0)
            report_rows.append(row)
        return report_rows

    def _with_area_units_report_rows(self, report_rows, unit_label="sq m"):
        if not report_rows:
            return report_rows
        transformed_rows = []
        for row in report_rows:
            transformed = {}
            for key, value in row.items():
                if key == "class_label":
                    transformed[f"class_label ({unit_label})"] = value
                elif str(key).isdigit():
                    transformed[f"{key} ({unit_label})"] = value
                else:
                    transformed[key] = value
            transformed_rows.append(transformed)
        return transformed_rows

    def _compute_lulc_class_area_rows_for_year(self, geometry, year, scale, period_label=None):
        image = self._build_lulc_image(geometry, date(year, 1, 1), date(year, 12, 31))
        histogram_info = self._frequency_histogram(image, "classification", geometry, scale)
        rows = []
        total_area = 0.0
        for class_value, class_label in LULC_CLASS_NAMES.items():
            pixel_count = float(histogram_info.get(str(class_value), histogram_info.get(class_value, 0.0)))
            area_sq_m = pixel_count * (scale * scale)
            total_area += area_sq_m
            row = {
                "year": year,
                "class_code": class_value,
                "class_label": class_label,
                "area_sq_m": round(area_sq_m, 5),
                "area_hectares": round(area_sq_m / 10000.0, 5),
            }
            if period_label:
                row["period"] = period_label
            rows.append(row)

        for row in rows:
            row["percent_of_aoi"] = round((row["area_sq_m"] / total_area * 100.0), 5) if total_area else 0.0
        return rows

    def _compute_landsat_lulc_class_area_rows_for_period(
        self,
        geometry,
        start_date,
        end_date,
        scale,
        period_label=None,
        year=None,
        classifier=None,
    ):
        image = self._build_landsat_lulc_image(geometry, start_date, end_date, classifier=classifier)
        histogram_info = self._frequency_histogram(image, "classification", geometry, scale)
        rows = []
        total_area = 0.0
        for class_value, class_label in LULC_LANDSAT_CLASS_NAMES.items():
            pixel_count = float(histogram_info.get(str(class_value), histogram_info.get(class_value, 0.0)))
            area_sq_m = pixel_count * (scale * scale)
            total_area += area_sq_m
            row = {
                "class_code": class_value,
                "class_label": class_label,
                "area_sq_m": round(area_sq_m, 5),
                "area_hectares": round(area_sq_m / 10000.0, 5),
            }
            if year is not None:
                row["year"] = year
            if period_label:
                row["period"] = period_label
            rows.append(row)

        for row in rows:
            row["percent_of_aoi"] = round((row["area_sq_m"] / total_area * 100.0), 5) if total_area else 0.0
        return rows

    def _compute_landsat_lulc_class_area_rows_for_year(self, geometry, year, scale, period_label=None, classifier=None):
        return self._compute_landsat_lulc_class_area_rows_for_period(
            geometry,
            date(year, 1, 1),
            date(year, 12, 31),
            scale,
            period_label=period_label,
            year=year,
            classifier=classifier,
        )

    def _compute_worldcover_class_area_rows_for_year(self, geometry, year, scale, period_label=None):
        image = self._build_worldcover_image_for_year(geometry, year)
        histogram_info = self._frequency_histogram(image, "classification", geometry, scale)
        rows = []
        total_area = 0.0
        for class_value, class_label in MODIS_LULC_CLASS_NAMES.items():
            pixel_count = float(histogram_info.get(str(class_value), histogram_info.get(class_value, 0.0)))
            area_sq_m = pixel_count * (scale * scale)
            total_area += area_sq_m
            row = {
                "year": year,
                "class_code": class_value,
                "class_label": class_label,
                "area_sq_m": round(area_sq_m, 5),
                "area_hectares": round(area_sq_m / 10000.0, 5),
            }
            if period_label:
                row["period"] = period_label
            rows.append(row)

        for row in rows:
            row["percent_of_aoi"] = round((row["area_sq_m"] / total_area * 100.0), 5) if total_area else 0.0
        return rows

    def _append_annual_change_metrics(self, rows, include_text_flags=False):
        previous_row = None
        for row in rows:
            if previous_row is None:
                row["annual_change"] = None
                if include_text_flags and "dominant_class" in row:
                    row["dominant_class_changed"] = False
                previous_row = row
                continue

            if isinstance(row.get("value"), (int, float)) and isinstance(previous_row.get("value"), (int, float)):
                row["annual_change"] = round(float(row["value"]) - float(previous_row["value"]), 5)
            else:
                row["annual_change"] = None

            if include_text_flags and "dominant_class" in row:
                row["dominant_class_changed"] = row.get("dominant_class") != previous_row.get("dominant_class")

            for key, value in list(row.items()):
                if key in {"year", "annual_change"}:
                    continue
                current_is_numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
                previous_value = previous_row.get(key)
                previous_is_numeric = isinstance(previous_value, (int, float)) and not isinstance(
                    previous_value, bool
                )
                if current_is_numeric and previous_is_numeric:
                    row[f"{key}_annual_change"] = round(float(value) - float(previous_row[key]), 5)
            previous_row = row
        return rows

    @staticmethod
    def _raise_if_canceled(task):
        if task is not None and task.isCanceled():
            raise RuntimeError("Assessment cancelled by user.")

    @staticmethod
    def _update_task_progress(task, value, message=None):
        if task is not None:
            EarthEngineAssessmentService._raise_if_canceled(task)
            if message:
                setattr(task, "stage_message", str(message))
            task.setProgress(max(0, min(100, int(value))))

    def _build_summary_image_and_classes(self, analysis_id, mode, geometry, start_date, end_date):
        analysis = ANALYSIS_DEFINITIONS[analysis_id]
        if mode == "trend" and analysis.get("trend_classes"):
            image = self._build_trend_image(analysis_id, geometry, start_date, end_date)
            classes = self._normalize_range_classes(analysis["trend_classes"])
            return self._reclassify_range_image(image, classes), classes

        if analysis["summary_mode"] == "discrete":
            image = self._build_snapshot_image(analysis_id, geometry, start_date, end_date)
            classes = analysis["summary_classes"]
            if analysis_id == "wind_direction":
                image = self._build_wind_direction_sector_image(geometry, start_date, end_date)
            return image.rename("summary_class"), classes

        image = self._build_snapshot_image(analysis_id, geometry, start_date, end_date)
        classes = self._normalize_range_classes(analysis["summary_classes"])
        return self._reclassify_range_image(image, classes), classes

    def _build_snapshot_image(self, analysis_id, geometry, start_date, end_date):
        if analysis_id == "lulc":
            return self._build_lulc_image(geometry, start_date, end_date)
        if analysis_id == "lulc_landsat":
            return self._build_landsat_lulc_image(geometry, start_date, end_date)
        if analysis_id == "lulc_modis":
            selected_years = self._resolve_modis_lulc_years(start_date, end_date)
            return self._build_worldcover_image_for_year(geometry, selected_years[-1])
        if analysis_id == "change_detection":
            return self._build_change_detection_image(geometry, start_date, end_date)
        if analysis_id == "lst":
            return self._build_lst_image(geometry, start_date, end_date)
        if analysis_id == "urban_heat_island":
            return self._build_urban_heat_island_image(geometry, start_date, end_date)
        if analysis_id == "flood":
            return self._build_flood_image(geometry, start_date, end_date)
        if analysis_id == "ndvi":
            return self._build_ndvi_image(geometry, start_date, end_date)
        if analysis_id == "ndwi":
            return self._build_ndwi_image(geometry, start_date, end_date)
        if analysis_id == "land_degradation":
            return self._build_land_degradation_image(geometry, start_date, end_date)
        if analysis_id == "drought":
            return self._build_drought_image(geometry, start_date, end_date)
        if analysis_id == "soil":
            return self._build_soil_image(geometry, start_date, end_date)
        if analysis_id == "wind_direction":
            return self._build_wind_direction_image(geometry, start_date, end_date)
        if analysis_id == "carbon_emission":
            return self._build_carbon_emission_image(geometry, start_date, end_date)
        if analysis_id == "anthropogenic_emission":
            return self._build_anthropogenic_emission_image(geometry, start_date, end_date)
        if analysis_id == "carbon_sequestration":
            return self._build_carbon_sequestration_image(geometry, start_date, end_date)
        if analysis_id == "solar_radiation":
            return self._build_solar_radiation_image(geometry, start_date, end_date)
        if analysis_id == "precipitation_anomaly":
            return self._build_precipitation_anomaly_image(geometry, start_date, end_date)
        if analysis_id == "soil_moisture":
            return self._build_soil_moisture_image(geometry, start_date, end_date)
        if analysis_id == "erosion_risk":
            return self._build_erosion_risk_image(geometry, start_date, end_date)
        if analysis_id == "terrain_susceptibility":
            return self._build_terrain_susceptibility_image(geometry, start_date, end_date)
        if analysis_id == "wildfire_risk":
            return self._build_wildfire_risk_image(geometry, start_date, end_date)
        if analysis_id == "air_quality":
            return self._build_air_quality_image(geometry, start_date, end_date)
        if analysis_id == "habitat_fragmentation":
            return self._build_habitat_fragmentation_image(geometry, end_date.year)
        if analysis_id == "runoff_potential":
            return self._build_runoff_potential_image(geometry, start_date, end_date)
        raise ValueError(f"Unsupported analysis: {analysis_id}")

    def _build_trend_image(self, analysis_id, geometry, start_date, end_date):
        if analysis_id == "lst":
            return self._build_linear_trend_image(geometry, start_date, end_date, self._annual_lst_image, "LST_C")
        if analysis_id == "urban_heat_island":
            return self._build_linear_trend_image(
                geometry,
                start_date,
                end_date,
                self._annual_urban_heat_island_image,
                "uhi_intensity_c",
            )
        if analysis_id == "ndvi":
            return self._build_linear_trend_image(geometry, start_date, end_date, self._annual_ndvi_image, "NDVI")
        if analysis_id == "ndwi":
            return self._build_linear_trend_image(geometry, start_date, end_date, self._annual_ndwi_image, "NDWI")
        if analysis_id == "land_degradation":
            return self._build_land_degradation_trend_image(geometry, start_date, end_date)
        if analysis_id == "drought":
            return self._build_linear_trend_image(
                geometry, start_date, end_date, self._annual_drought_image, "drought_proxy"
            )
        if analysis_id == "soil":
            return self._build_linear_trend_image(geometry, start_date, end_date, self._annual_soil_index_image, "soil_index")
        if analysis_id == "wind_direction":
            return self._build_linear_trend_image(geometry, start_date, end_date, self._annual_wind_speed_image, "wind_speed")
        if analysis_id == "carbon_emission":
            return self._build_linear_trend_image(
                geometry,
                start_date,
                end_date,
                self._annual_carbon_emission_image,
                "carbon_emission",
            )
        if analysis_id == "anthropogenic_emission":
            return self._build_linear_trend_image(
                geometry,
                start_date,
                end_date,
                self._annual_anthropogenic_emission_image,
                "anthropogenic_emission",
            )
        if analysis_id == "carbon_sequestration":
            return self._build_linear_trend_image(
                geometry,
                start_date,
                end_date,
                self._annual_carbon_sequestration_image,
                "carbon_sequestration",
            )
        if analysis_id == "solar_radiation":
            return self._build_linear_trend_image(
                geometry,
                start_date,
                end_date,
                self._annual_solar_radiation_image,
                "solar_radiation",
            )
        if analysis_id == "precipitation_anomaly":
            return self._build_linear_trend_image(
                geometry,
                start_date,
                end_date,
                self._annual_precipitation_anomaly_image,
                "precipitation_anomaly",
            )
        if analysis_id == "soil_moisture":
            return self._build_linear_trend_image(
                geometry,
                start_date,
                end_date,
                self._annual_soil_moisture_image,
                "soil_moisture",
            )
        if analysis_id == "erosion_risk":
            return self._build_linear_trend_image(
                geometry,
                start_date,
                end_date,
                self._annual_erosion_risk_image,
                "erosion_risk",
            )
        if analysis_id == "terrain_susceptibility":
            return self._build_linear_trend_image(
                geometry,
                start_date,
                end_date,
                self._annual_terrain_susceptibility_image,
                "terrain_susceptibility",
            )
        if analysis_id == "wildfire_risk":
            return self._build_linear_trend_image(
                geometry,
                start_date,
                end_date,
                self._annual_wildfire_risk_image,
                "wildfire_risk",
            )
        if analysis_id == "air_quality":
            return self._build_linear_trend_image(
                geometry,
                start_date,
                end_date,
                self._annual_air_quality_image,
                "air_quality",
            )
        if analysis_id == "habitat_fragmentation":
            return self._build_linear_trend_image(
                geometry,
                start_date,
                end_date,
                self._annual_habitat_fragmentation_image,
                "habitat_fragmentation",
            )
        if analysis_id == "runoff_potential":
            return self._build_linear_trend_image(
                geometry,
                start_date,
                end_date,
                self._annual_runoff_potential_image,
                "runoff_potential",
            )
        return self._build_snapshot_image(analysis_id, geometry, start_date, end_date)

    def _build_linear_trend_image(self, geometry, start_date, end_date, image_builder, band_name):
        annual_images = []
        for year in range(start_date.year, end_date.year + 1):
            value_image = image_builder(geometry, year).rename(band_name)
            annual_images.append(value_image.addBands(ee.Image.constant(year).rename("year")).float())

        collection = ee.ImageCollection.fromImages(annual_images)
        fit = collection.select(["year", band_name]).reduce(ee.Reducer.linearFit())
        return fit.select("scale").rename(f"{band_name}_trend")

    def _build_lulc_image(self, geometry, start_date, end_date):
        return self._build_lulc_modal_label_image(geometry, start_date, end_date)

    def _build_lulc_probability_image(self, geometry, start_date, end_date):
        collection = (
            ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
            .filterBounds(geometry)
            .filterDate(start_date.isoformat(), end_date.isoformat())
        )
        probabilities = collection.select(DYNAMIC_WORLD_PROBABILITY_BANDS).mean()
        valid_observations = collection.select("label").count()
        classification = (
            probabilities.toArray()
            .arrayArgmax()
            .arrayGet([0])
            .toInt()
            .rename("classification")
            .updateMask(valid_observations.gt(0))
        )
        return classification.clip(geometry)

    def _build_lulc_modal_label_image(self, geometry, start_date, end_date):
        collection = (
            ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
            .filterBounds(geometry)
            .filterDate(start_date.isoformat(), end_date.isoformat())
            .select("label")
        )
        return collection.mode().toInt().rename("classification").clip(geometry)

    def _build_landsat_lulc_image(self, geometry, start_date, end_date, classifier=None):
        composite = self._landsat_feature_image(geometry, start_date, end_date)
        classifier = classifier or self._train_landsat_lulc_classifier(geometry)
        classified = composite.select(LANDSAT_LULC_FEATURE_BANDS).classify(classifier).rename("classification")
        return self._refine_landsat_lulc_classes(classified, composite).clip(geometry)

    def _annual_landsat_lulc_image(self, geometry, year, classifier=None):
        return self._build_landsat_lulc_image(geometry, date(year, 1, 1), date(year, 12, 31), classifier=classifier)

    def _landsat_feature_image(self, geometry, start_date, end_date):
        return self._landsat8_collection(geometry, start_date, end_date).median().clip(geometry)

    def _landsat_raw_stack_image(self, geometry, start_date, end_date):
        return self._landsat_feature_image(geometry, start_date, end_date).select(LANDSAT_RAW_STACK_BANDS)

    def _sentinel_processed_stack_image(self, geometry, start_date, end_date):
        composite = (
            self._sentinel2_surface_reflectance_collection(geometry, start_date, end_date)
            .median()
            .clip(geometry)
        )
        return self._add_sentinel2_indices(composite).select(SENTINEL_PROCESSED_STACK_BANDS)

    def _train_landsat_lulc_classifier(self, geometry):
        training_geometry = geometry.simplify(120)
        training_years = self._landsat_lulc_training_years()
        training_samples = []
        for year in training_years:
            feature_image = self._landsat_feature_image(training_geometry, date(year, 1, 1), date(year, 12, 31))
            label_image = self._dynamic_world_landsat_training_label_image(training_geometry, year)
            sample = feature_image.select(LANDSAT_LULC_FEATURE_BANDS).addBands(label_image).stratifiedSample(
                numPoints=40,
                classBand="classification",
                region=training_geometry,
                scale=60,
                seed=year,
                geometries=False,
                dropNulls=True,
                tileScale=4,
            )
            training_samples.append(sample)

        if not training_samples:
            raise RuntimeError("Unable to build Landsat 8 LULC training samples.")

        training_fc = ee.FeatureCollection(training_samples[0])
        for sample in training_samples[1:]:
            training_fc = training_fc.merge(sample)

        return ee.Classifier.smileRandomForest(
            numberOfTrees=40,
            variablesPerSplit=3,
            minLeafPopulation=5,
            bagFraction=0.6,
            seed=42,
        ).train(
            features=training_fc,
            classProperty="classification",
            inputProperties=LANDSAT_LULC_FEATURE_BANDS,
        )

    @staticmethod
    def _landsat_lulc_training_years():
        return [2016, 2019, 2022]

    def _dynamic_world_landsat_training_label_image(self, geometry, year):
        dw_image = self._build_lulc_image(geometry, date(year, 1, 1), date(year, 12, 31))
        simplified = ee.Image.constant(2).rename("classification")
        simplified = simplified.where(dw_image.eq(0), 0)
        simplified = simplified.where(dw_image.eq(1).Or(dw_image.eq(3)), 1)
        simplified = simplified.where(dw_image.eq(2).Or(dw_image.eq(4)).Or(dw_image.eq(5)), 2)
        simplified = simplified.where(dw_image.eq(6), 3)
        simplified = simplified.where(dw_image.eq(7).Or(dw_image.eq(8)), 4)
        return simplified.updateMask(dw_image.mask()).toInt16().clip(geometry)

    def _refine_landsat_lulc_classes(self, classified, composite):
        ndvi = composite.select("NDVI")
        ndwi = composite.select("NDWI")
        ndbi = composite.select("NDBI")

        water_mask = ndwi.gt(0.12).And(ndvi.lt(0.2)).And(ndbi.lt(0.05))
        dense_veg_mask = ndvi.gt(0.45).And(ndwi.lt(0.05))
        open_veg_mask = ndvi.gt(0.22).And(ndwi.lt(0.1))
        built_mask = ndbi.gt(0.08).And(ndvi.lt(0.22))
        urban_false_water_mask = ndbi.gt(0.02).And(ndwi.lt(0.18)).And(ndvi.lt(0.22))
        strong_water_mask = ndwi.gt(0.22).And(ndvi.lt(0.12)).And(ndbi.lt(0.0))
        urban_water_allowed = water_mask.And(urban_false_water_mask.Not().Or(strong_water_mask))

        refined = classified
        refined = refined.where(classified.eq(0).And(water_mask.Not()).And(dense_veg_mask), 1)
        refined = refined.where(
            classified.eq(0).And(water_mask.Not()).And(dense_veg_mask.Not()).And(open_veg_mask),
            2,
        )
        refined = refined.where(urban_water_allowed, 0)
        refined = refined.where(classified.eq(0).And(urban_false_water_mask).And(urban_water_allowed.Not()), 3)
        small_water = refined.eq(0).selfMask().connectedPixelCount(8, True).lt(5)
        refined = refined.where(small_water.And(urban_false_water_mask.Or(built_mask)), 3)
        refined = refined.where(small_water.And(urban_false_water_mask.Not()).And(dense_veg_mask), 1)
        refined = refined.where(
            small_water.And(urban_false_water_mask.Not()).And(dense_veg_mask.Not()).And(open_veg_mask),
            2,
        )
        return refined.toInt16().rename("classification")

    @staticmethod
    def _resolve_modis_lulc_years(start_date, end_date, interval_years=1):
        effective_start = max(start_date.year, MODIS_LULC_MIN_YEAR)
        effective_end = min(end_date.year, MODIS_LULC_MAX_YEAR)
        if effective_start > effective_end:
            return []
        years = list(range(effective_start, effective_end + 1, max(1, interval_years)))
        if years and years[-1] != effective_end:
            years.append(effective_end)
        return years

    @staticmethod
    def _resolve_landsat_lulc_complete_years(requested_start_year, requested_end_year, interval_years=1):
        latest_complete_year = date.today().year - 1
        effective_start = max(requested_start_year, LANDSAT_HISTORICAL_MIN_YEAR)
        effective_end = min(requested_end_year, latest_complete_year)
        if effective_start > effective_end:
            raise RuntimeError(
                "Landsat 8 LULC uses complete years only. "
                f"The available complete-year range is {LANDSAT_HISTORICAL_MIN_YEAR} to {latest_complete_year}."
            )

        notes = []
        if effective_start != requested_start_year:
            notes.append(
                f"Requested start year {requested_start_year} was adjusted to {effective_start}, "
                f"because Landsat 8 LULC starts in {LANDSAT_HISTORICAL_MIN_YEAR}."
            )
        if effective_end != requested_end_year:
            notes.append(
                f"Requested end year {requested_end_year} was adjusted to {effective_end}, "
                "because Landsat 8 annual outputs use complete years only."
            )
        years = list(range(effective_start, effective_end + 1, max(1, interval_years)))
        if years and years[-1] != effective_end:
            years.append(effective_end)
        return years, notes

    def _build_worldcover_image_for_year(self, geometry, year):
        if year < MODIS_LULC_MIN_YEAR or year > MODIS_LULC_MAX_YEAR:
            raise RuntimeError(
                "MODIS historical land cover is available from 2001 to 2024 in Earth Engine."
            )
        collection = (
            ee.ImageCollection("MODIS/061/MCD12Q1")
            .filterBounds(geometry)
            .filterDate(date(year, 1, 1).isoformat(), date(year + 1, 1, 1).isoformat())
            .select("LC_Type1")
        )
        return collection.first().rename("classification").clip(geometry)

    @staticmethod
    def _year_sequence(start_year, end_year, interval_years=1):
        years = list(range(start_year, end_year + 1, max(1, interval_years)))
        if years and years[-1] != end_year:
            years.append(end_year)
        return years

    def _resolve_lulc_complete_years(self, geometry, requested_start_year, requested_end_year, interval_years=1):
        availability = self._dynamic_world_availability(geometry)
        if availability["count"] <= 0:
            raise RuntimeError("No Dynamic World LULC records intersect the selected AOI.")

        min_year = availability["min_date"].year
        max_date = availability["max_date"]
        latest_complete_year = max_date.year if max_date >= date(max_date.year, 12, 31) else max_date.year - 1
        effective_start_year = max(requested_start_year, min_year)
        effective_end_year = min(requested_end_year, latest_complete_year)

        if effective_start_year > effective_end_year:
            raise RuntimeError(
                f"Dynamic World annual comparisons require complete years. "
                f"The latest complete year available for this AOI is {latest_complete_year}."
            )

        notes = []
        if effective_start_year != requested_start_year:
            notes.append(
                f"Requested start year {requested_start_year} was adjusted to {effective_start_year}, "
                f"because Dynamic World AOI coverage starts in {min_year}."
            )
        if effective_end_year != requested_end_year:
            notes.append(
                f"Requested end year {requested_end_year} was adjusted to {effective_end_year}, "
                "because Dynamic World annual trend and change outputs use complete years only."
            )

        years = self._year_sequence(effective_start_year, effective_end_year, interval_years)
        return years, notes

    def _dynamic_world_availability(self, geometry):
        collection = ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1").filterBounds(geometry)
        count = int(collection.size().getInfo() or 0)
        if count <= 0:
            return {"count": 0, "min_date": None, "max_date": None}

        min_ts = collection.aggregate_min("system:time_start").getInfo()
        max_ts = collection.aggregate_max("system:time_start").getInfo()
        min_date = date.fromisoformat(ee.Date(min_ts).format("YYYY-MM-dd").getInfo())
        max_date = date.fromisoformat(ee.Date(max_ts).format("YYYY-MM-dd").getInfo())
        return {"count": count, "min_date": min_date, "max_date": max_date}

    def _build_change_detection_image(self, geometry, start_date, end_date):
        start_year = date(start_date.year, 1, 1)
        start_year_end = date(start_date.year, 12, 31)
        end_year_start = date(end_date.year, 1, 1)
        end_year_end = date(end_date.year, 12, 31)
        start_image = self._build_lulc_modal_label_image(geometry, start_year, start_year_end)
        end_image = self._build_lulc_modal_label_image(geometry, end_year_start, end_year_end)
        return self._build_change_detection_from_lulc(start_image, end_image, geometry)

    @staticmethod
    def _build_change_detection_from_lulc(start_image, end_image, geometry):
        return start_image.neq(end_image).rename("change").clip(geometry)

    def _build_change_transition_image(self, geometry, start_date, end_date):
        start_image = self._build_lulc_modal_label_image(
            geometry,
            date(start_date.year, 1, 1),
            date(start_date.year, 12, 31),
        )
        end_image = self._build_lulc_modal_label_image(
            geometry,
            date(end_date.year, 1, 1),
            date(end_date.year, 12, 31),
        )
        return self._build_change_transition_from_lulc(start_image, end_image, geometry)

    @staticmethod
    def _build_change_transition_from_lulc(start_image, end_image, geometry):
        transition = start_image.multiply(100).add(end_image).rename("change").clip(geometry)
        no_change = start_image.eq(end_image)
        return transition.where(no_change, 0).rename("change")

    def _compute_change_transition_rows(self, geometry, start_date, end_date, scale):
        transition_image = self._build_change_transition_image(geometry, start_date, end_date)
        return self._compute_change_transition_rows_from_image(transition_image, geometry, scale)

    def _compute_change_transition_rows_from_image(self, transition_image, geometry, scale):
        histogram_info = self._frequency_histogram(transition_image, "change", geometry, scale)
        rows = []
        total_area = 0.0
        for code_key, count in histogram_info.items():
            transition_code = int(float(code_key))
            area_sq_m = float(count) * (scale * scale)
            total_area += area_sq_m
            if transition_code == 0:
                from_label = "No change"
                to_label = "No change"
                transition_label = "No change"
            else:
                from_code = transition_code // 100
                to_code = transition_code % 100
                from_label = LULC_CLASS_NAMES.get(from_code, f"Class {from_code}")
                to_label = LULC_CLASS_NAMES.get(to_code, f"Class {to_code}")
                transition_label = f"{from_label} -> {to_label}"
            rows.append(
                {
                    "transition_code": transition_code,
                    "from_class": from_label,
                    "to_class": to_label,
                    "transition_label": transition_label,
                    "area_sq_m": round(area_sq_m, 5),
                    "area_hectares": round(area_sq_m / 10000.0, 5),
                }
            )

        rows.sort(key=lambda row: row["transition_code"])
        for row in rows:
            row["percent_of_aoi"] = round((row["area_sq_m"] / total_area * 100.0), 5) if total_area else 0.0
        return rows

    def _transition_classes_from_rows(self, rows):
        classes = [{"value": 0, "label": "No change", "color": "#d1d5db"}]
        color_index = 0
        for row in rows:
            if row["transition_code"] == 0:
                continue
            classes.append(
                {
                    "value": row["transition_code"],
                    "label": row["transition_label"],
                    "color": CHANGE_RENDER_COLORS[color_index % len(CHANGE_RENDER_COLORS)],
                }
            )
            color_index += 1
        return classes

    @staticmethod
    def _all_transition_classes():
        classes = [{"value": 0, "label": "No change", "color": "#d1d5db"}]
        for from_code, from_label in LULC_CLASS_NAMES.items():
            for to_code, to_label in LULC_CLASS_NAMES.items():
                if from_code == to_code:
                    continue
                transition_code = (from_code * 100) + to_code
                color_index = (from_code + to_code) % len(CHANGE_RENDER_COLORS)
                classes.append(
                    {
                        "value": transition_code,
                        "label": f"{from_label} -> {to_label}",
                        "color": CHANGE_RENDER_COLORS[color_index],
                    }
                )
        return classes

    def _build_lst_image(self, geometry, start_date, end_date):
        return self._landsat_collection(geometry, start_date, end_date).select("LST_C").median().rename("LST_C").clip(geometry)

    def _build_urban_heat_island_image(self, geometry, start_date, end_date):
        lst = self._build_lst_image(geometry, start_date, end_date)
        stats = lst.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geometry,
            scale=ANALYSIS_DEFINITIONS["urban_heat_island"]["scale"],
            maxPixels=1_000_000_000,
            bestEffort=True,
        )
        mean_lst = ee.Number(stats.get("LST_C"))
        return lst.subtract(mean_lst).rename("uhi_intensity_c").clip(geometry)

    def _build_flood_image(self, geometry, start_date, end_date):
        collection = (
            ee.ImageCollection("COPERNICUS/S1_GRD")
            .filterBounds(geometry)
            .filterDate(start_date.isoformat(), end_date.isoformat())
            .filter(ee.Filter.eq("instrumentMode", "IW"))
            .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
            .select("VV")
        )
        return collection.median().lt(-16).rename("flood").clip(geometry)

    def _build_flood_hazard_depth_image(self, geometry):
        image = ee.ImageCollection("JRC/CEMS_GLOFAS/FloodHazard/v2_1").first().select("RP100_depth")
        return image.rename("flood_depth_m").clip(geometry)

    def _build_ndvi_image(self, geometry, start_date, end_date):
        composite = self._landsat_collection(geometry, start_date, end_date).median()
        ndvi = composite.select("NDVI").rename("NDVI")
        mndwi = composite.normalizedDifference(["green", "swir1"]).rename("MNDWI")
        ndbi = composite.select("NDBI")
        likely_water = mndwi.gt(0.15).And(ndvi.lt(0.2)).And(ndbi.lt(0.05))
        return ndvi.where(likely_water, -0.95).clamp(-1.0, 1.0).rename("NDVI").clip(geometry)

    def _build_ndwi_image(self, geometry, start_date, end_date):
        composite = self._landsat_collection(geometry, start_date, end_date).median()
        mndwi = composite.normalizedDifference(["green", "swir1"]).rename("MNDWI")
        ndmi = composite.select("NDMI")
        ndbi = composite.select("NDBI")
        wetness = (
            mndwi.multiply(0.7)
            .add(ndmi.multiply(0.3))
            .subtract(ndbi.max(0).multiply(0.25))
            .rename("NDWI")
        )
        return wetness.clamp(-1.0, 1.0).clip(geometry)

    def _build_land_degradation_image(self, geometry, start_date, end_date):
        return self._build_land_degradation_image_with_baseline(
            geometry,
            start_date.year,
            start_date,
            end_date,
        )

    def _build_land_degradation_image_with_baseline(self, geometry, baseline_year, start_date, end_date):
        current_ndvi = self._build_ndvi_image(geometry, start_date, end_date)
        baseline_ndvi = self._annual_ndvi_image(geometry, baseline_year)
        return current_ndvi.lt(baseline_ndvi.subtract(0.1)).rename("degradation").clip(geometry)

    def _compute_land_degradation_class_area_rows_for_year(self, geometry, baseline_year, year, scale):
        image = self._build_land_degradation_image_with_baseline(
            geometry,
            baseline_year,
            date(year, 1, 1),
            date(year, 12, 31),
        )
        histogram_info = self._frequency_histogram(image, "degradation", geometry, scale)
        rows = []
        total_area = 0.0
        for item in LAND_DEGRADATION_CLASSES:
            class_value = item["value"]
            pixel_count = float(histogram_info.get(str(class_value), histogram_info.get(class_value, 0.0)))
            area_sq_m = pixel_count * (scale * scale)
            total_area += area_sq_m
            rows.append(
                {
                    "class_code": class_value,
                    "class_label": item["label"],
                    "area_sq_m": round(area_sq_m, 2),
                    "area_hectares": round(area_sq_m / 10000.0, 4),
                    "value_min": item.get("min"),
                    "value_max": item.get("max"),
                }
            )

        for row in rows:
            row["percent_of_aoi"] = round((row["area_sq_m"] / total_area * 100.0), 2) if total_area else 0.0
        return rows

    def _build_drought_image(self, geometry, start_date, end_date):
        ndvi = self._build_ndvi_image(geometry, start_date, end_date)
        ndwi = self._build_ndwi_image(geometry, start_date, end_date)
        denominator = ndvi.add(ndwi)
        nddi = ndvi.subtract(ndwi).divide(denominator.where(denominator.eq(0), 0.0001))
        return nddi.rename("drought_proxy").clip(geometry)

    def _build_soil_image(self, geometry, start_date, end_date):  # noqa: ARG002
        image = ee.Image("OpenLandMap/SOL/SOL_ORGANIC-CARBON_USDA-6A1C_M/v02").select("b0")
        return image.multiply(5).rename("soil_carbon").clip(geometry)

    def _build_wind_direction_image(self, geometry, start_date, end_date):
        wind = self._wind_components_image(geometry, start_date, end_date)
        direction = wind.expression(
            "(atan2(u, v) * 180 / pi + 360) % 360",
            {"u": wind.select("u"), "v": wind.select("v"), "pi": math.pi},
        )
        return direction.rename("wind_direction").clip(geometry)

    def _build_wind_speed_image(self, geometry, start_date, end_date):
        wind = self._wind_components_image(geometry, start_date, end_date)
        return wind.expression("sqrt((u*u) + (v*v))", {"u": wind.select("u"), "v": wind.select("v")}).rename("wind_speed").clip(geometry)

    def _build_carbon_emission_image(self, geometry, start_date, end_date):
        biomass = ee.ImageCollection("NASA/ORNL/biomass_carbon_density/v1").first().select("agb")
        loss = ee.Image("UMD/hansen/global_forest_change_2024_v1_12").select("lossyear")
        start_year = max(start_date.year, 2001)
        end_year = min(end_date.year, 2024)
        start_loss_year = start_year - 2000
        end_loss_year = end_year - 2000
        loss_mask = loss.gte(start_loss_year).And(loss.lte(end_loss_year))
        return biomass.updateMask(loss_mask).unmask(0).rename("carbon_emission").clip(geometry)

    def _build_carbon_sequestration_image(self, geometry, start_date, end_date):
        filtered = (
            ee.ImageCollection("MODIS/061/MOD17A3HGF")
            .filterBounds(geometry)
            .filterDate(start_date.isoformat(), end_date.isoformat())
            .select("Npp")
        )
        fallback = ee.ImageCollection("MODIS/061/MOD17A3HGF").filterBounds(geometry).filterDate("2024-01-01", "2025-01-01").select("Npp")
        collection = ee.ImageCollection(ee.Algorithms.If(filtered.size().gt(0), filtered, fallback))
        return collection.mean().multiply(0.0001).rename("carbon_sequestration").clip(geometry)

    def _build_anthropogenic_emission_image(self, geometry, start_date, end_date):
        filtered = (
            ee.ImageCollection("NOAA/VIIRS/DNB/ANNUAL_V22")
            .filterBounds(geometry)
            .filterDate(start_date.isoformat(), end_date.isoformat())
            .select("average_masked")
        )
        fallback = ee.ImageCollection("NOAA/VIIRS/DNB/ANNUAL_V22").filterBounds(geometry).filterDate("2024-01-01", "2025-01-01").select("average_masked")
        collection = ee.ImageCollection(ee.Algorithms.If(filtered.size().gt(0), filtered, fallback))
        return collection.mean().rename("anthropogenic_emission").clip(geometry)

    def _build_solar_radiation_image(self, geometry, start_date, end_date):
        collection = (
            ee.ImageCollection("MODIS/062/MCD18C2")
            .filterBounds(geometry)
            .filterDate(start_date.isoformat(), end_date.isoformat())
            .select(
                [
                    "GMT_0000_PAR",
                    "GMT_0300_PAR",
                    "GMT_0600_PAR",
                    "GMT_0900_PAR",
                    "GMT_1200_PAR",
                    "GMT_1500_PAR",
                    "GMT_1800_PAR",
                    "GMT_2100_PAR",
                ]
            )
        )
        par_mean = collection.mean().reduce(ee.Reducer.mean()).rename("solar_radiation")
        return par_mean.clip(geometry)

    def _build_precipitation_anomaly_image(self, geometry, start_date, end_date):
        current = self._chirps_collection(geometry, start_date, end_date).mean().rename("precipitation")
        climatology = self._chirps_climatology(geometry, start_date, end_date)
        return current.subtract(climatology).rename("precipitation_anomaly").clip(geometry)

    def _compute_precipitation_current_and_baseline(self, geometry, start_date, end_date):
        current = self._chirps_collection(geometry, start_date, end_date).mean()
        baseline = self._chirps_climatology(geometry, start_date, end_date)
        current_value = current.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geometry,
            scale=ANALYSIS_DEFINITIONS["precipitation_anomaly"]["scale"],
            maxPixels=1_000_000_000,
            bestEffort=True,
        ).get("precipitation")
        baseline_value = baseline.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geometry,
            scale=ANALYSIS_DEFINITIONS["precipitation_anomaly"]["scale"],
            maxPixels=1_000_000_000,
            bestEffort=True,
        ).get("precipitation")
        return (
            round(float(current_value.getInfo() or 0.0), 5),
            round(float(baseline_value.getInfo() or 0.0), 5),
        )

    def _build_soil_moisture_image(self, geometry, start_date, end_date):
        collection = self._landsat_collection(geometry, start_date, end_date)
        return collection.select("NDMI").median().rename("soil_moisture").clip(geometry)

    def _build_erosion_risk_image(self, geometry, start_date, end_date):
        slope = ee.Terrain.slope(self._srtm_image()).rename("slope")
        ndvi = self._build_ndvi_image(geometry, start_date, end_date).clamp(-1.0, 1.0)
        bare_factor = ee.Image.constant(1.0).subtract(ndvi.add(1.0).divide(2.0)).clamp(0.0, 1.0)
        precip = self._chirps_collection(geometry, start_date, end_date).mean().rename("precipitation")
        precip_factor = precip.divide(20.0).clamp(0.0, 1.0)
        slope_factor = slope.divide(45.0).clamp(0.0, 1.0)
        risk = slope_factor.multiply(0.5).add(bare_factor.multiply(0.3)).add(precip_factor.multiply(0.2)).multiply(100.0)
        return risk.rename("erosion_risk").clip(geometry)

    def _build_terrain_susceptibility_image(self, geometry, start_date, end_date):  # noqa: ARG002
        slope = ee.Terrain.slope(self._srtm_image())
        return slope.rename("terrain_susceptibility").clip(geometry)

    def _build_wildfire_risk_image(self, geometry, start_date, end_date):
        collection = (
            ee.ImageCollection("MODIS/061/MCD64A1")
            .filterBounds(geometry)
            .filterDate(start_date.isoformat(), end_date.isoformat())
            .select("BurnDate")
        )
        total_images = ee.Number(collection.size())
        burned_count = collection.map(lambda image: image.gt(0).unmask(0).rename("burned")).sum()
        burn_frequency = burned_count.divide(total_images.max(1)).multiply(100.0)
        return burn_frequency.rename("wildfire_risk").clip(geometry)

    def _build_air_quality_image(self, geometry, start_date, end_date):
        effective_start, effective_end = self._pm25_effective_date_range(start_date, end_date)
        collection = (
            ee.ImageCollection(PM25_COLLECTION_ID)
            .filterBounds(geometry)
            .filterDate(effective_start.isoformat(), effective_end.isoformat())
        )
        return collection.mean().select([0]).rename("air_quality").clip(geometry)

    @staticmethod
    def _pm25_effective_date_range(start_date, end_date):
        start_year = max(PM25_AVAILABLE_START_YEAR, min(start_date.year, PM25_AVAILABLE_END_YEAR))
        end_year = max(PM25_AVAILABLE_START_YEAR, min(end_date.year, PM25_AVAILABLE_END_YEAR))
        if end_year < start_year:
            start_year = end_year
        return date(start_year, 1, 1), date(end_year, 12, 31)

    def _build_habitat_fragmentation_image(self, geometry, year):
        tree_cover = ee.Image("UMD/hansen/global_forest_change_2024_v1_12").select("treecover2000")
        loss = ee.Image("UMD/hansen/global_forest_change_2024_v1_12").select("lossyear")
        capped_year = min(max(year, 2001), 2024)
        clipped_tree_cover = tree_cover.clip(geometry)
        clipped_loss = loss.clip(geometry)
        active_forest = clipped_tree_cover.gte(30).And(
            clipped_loss.eq(0).Or(clipped_loss.gt(capped_year - 2000))
        )
        forest_density = (
            active_forest.unmask(0)
            .focalMean(radius=3, units="pixels")
            .reproject(crs=clipped_tree_cover.projection(), scale=120)
        )
        fragmentation = ee.Image.constant(1.0).subtract(forest_density).multiply(100.0)
        recent_loss = clipped_loss.gt(0).And(clipped_loss.lte(capped_year - 2000)).multiply(25.0)
        pressure = fragmentation.add(recent_loss).clamp(0, 100)
        pressure = pressure.where(active_forest.Not(), 90)
        return pressure.rename("habitat_fragmentation").clip(geometry)

    def _build_runoff_potential_image(self, geometry, start_date, end_date):
        flow_acc = ee.Image("WWF/HydroSHEDS/15ACC").select("b1").log10().divide(7.0).clamp(0.0, 1.0)
        slope = ee.Terrain.slope(self._srtm_image()).divide(45.0).clamp(0.0, 1.0)
        precip = self._chirps_collection(geometry, start_date, end_date).mean().divide(20.0).clamp(0.0, 1.0)
        runoff = flow_acc.multiply(0.45).add(slope.multiply(0.3)).add(precip.multiply(0.25)).multiply(100.0)
        return runoff.rename("runoff_potential").clip(geometry)

    def _build_wind_direction_sector_image(self, geometry, start_date, end_date):
        direction = self._build_wind_direction_image(geometry, start_date, end_date)
        sectors = direction.add(22.5).divide(45).floor().mod(8).toInt16().rename("summary_class")
        return sectors.clip(geometry)

    def _annual_ndvi_image(self, geometry, year):
        return self._build_ndvi_image(geometry, date(year, 1, 1), date(year, 12, 31))

    def _annual_ndwi_image(self, geometry, year):
        return self._build_ndwi_image(geometry, date(year, 1, 1), date(year, 12, 31))

    def _annual_lst_image(self, geometry, year):
        return self._build_lst_image(geometry, date(year, 1, 1), date(year, 12, 31))

    def _annual_urban_heat_island_image(self, geometry, year):
        return self._build_urban_heat_island_image(geometry, date(year, 1, 1), date(year, 12, 31))

    def _annual_drought_image(self, geometry, year):
        return self._build_drought_image(geometry, date(year, 1, 1), date(year, 12, 31))

    def _annual_soil_index_image(self, geometry, year):
        soil = self._build_soil_image(geometry, date(year, 1, 1), date(year, 12, 31))
        drought = self._annual_drought_image(geometry, year)
        return soil.divide(10).add(drought).rename("soil_index")

    def _annual_land_degradation_index_image(self, geometry, year):
        ndvi = self._annual_ndvi_image(geometry, year)
        prior_year = year - 1
        if prior_year < 1985:
            prior_year = year
        baseline = self._annual_ndvi_image(geometry, prior_year)
        return ndvi.subtract(baseline).rename("degradation_index")

    def _build_land_degradation_trend_image(self, geometry, start_date, end_date):
        baseline_ndvi = self._annual_ndvi_image(geometry, start_date.year)
        target_ndvi = self._annual_ndvi_image(geometry, end_date.year)
        return target_ndvi.subtract(baseline_ndvi).rename("degradation_index").clip(geometry)

    def _annual_wind_speed_image(self, geometry, year):
        return self._build_wind_speed_image(geometry, date(year, 1, 1), date(year, 12, 31))

    def _annual_carbon_emission_image(self, geometry, year):
        target_year = min(max(year, 2001), 2024)
        return self._build_carbon_emission_image(geometry, date(target_year, 1, 1), date(target_year, 12, 31))

    def _annual_carbon_sequestration_image(self, geometry, year):
        target_year = min(max(year, 2001), 2024)
        return self._build_carbon_sequestration_image(geometry, date(target_year, 1, 1), date(target_year, 12, 31))

    def _annual_anthropogenic_emission_image(self, geometry, year):
        target_year = min(max(year, 2012), 2024)
        return self._build_anthropogenic_emission_image(geometry, date(target_year, 1, 1), date(target_year, 12, 31))

    def _annual_solar_radiation_image(self, geometry, year):
        return self._build_solar_radiation_image(geometry, date(year, 1, 1), date(year, 12, 31))

    def _annual_precipitation_anomaly_image(self, geometry, year):
        return self._build_precipitation_anomaly_image(geometry, date(year, 1, 1), date(year, 12, 31))

    def _annual_soil_moisture_image(self, geometry, year):
        return self._build_soil_moisture_image(geometry, date(year, 1, 1), date(year, 12, 31))

    def _annual_erosion_risk_image(self, geometry, year):
        return self._build_erosion_risk_image(geometry, date(year, 1, 1), date(year, 12, 31))

    def _annual_terrain_susceptibility_image(self, geometry, year):  # noqa: ARG002
        return self._build_terrain_susceptibility_image(geometry, date(2000, 1, 1), date(2000, 12, 31))

    def _annual_wildfire_risk_image(self, geometry, year):
        target_year = min(max(year, 2001), 2025)
        return self._build_wildfire_risk_image(geometry, date(target_year, 1, 1), date(target_year, 12, 31))

    def _annual_air_quality_image(self, geometry, year):
        target_year = min(max(year, PM25_AVAILABLE_START_YEAR), PM25_AVAILABLE_END_YEAR)
        return self._build_air_quality_image(geometry, date(target_year, 1, 1), date(target_year, 12, 31))

    def _annual_habitat_fragmentation_image(self, geometry, year):
        return self._build_habitat_fragmentation_image(geometry, year)

    def _annual_runoff_potential_image(self, geometry, year):
        return self._build_runoff_potential_image(geometry, date(year, 1, 1), date(year, 12, 31))

    def _landsat_collection(self, geometry, start_date, end_date):
        tm_collection = (
            ee.ImageCollection("LANDSAT/LT05/C02/T1_L2")
            .merge(ee.ImageCollection("LANDSAT/LE07/C02/T1_L2"))
            .filterBounds(geometry)
            .filterDate(start_date.isoformat(), end_date.isoformat())
            .map(self._prepare_landsat_tm_etm)
        )
        oli_collection = (
            ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
            .merge(ee.ImageCollection("LANDSAT/LC09/C02/T1_L2"))
            .filterBounds(geometry)
            .filterDate(start_date.isoformat(), end_date.isoformat())
            .map(self._prepare_landsat_oli)
        )
        return tm_collection.merge(oli_collection).map(self._add_landsat_indices)

    def _landsat8_collection(self, geometry, start_date, end_date):
        return (
            ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
            .filterBounds(geometry)
            .filterDate(start_date.isoformat(), end_date.isoformat())
            .map(self._prepare_landsat_oli)
            .map(self._add_landsat_indices)
        )

    def _sentinel2_collection(self, geometry, start_date, end_date):
        return self._sentinel2_surface_reflectance_collection(geometry, start_date, end_date).map(
            self._add_sentinel2_indices
        )

    def _sentinel2_surface_reflectance_collection(self, geometry, start_date, end_date):
        return (
            ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
            .filterBounds(geometry)
            .filterDate(start_date.isoformat(), end_date.isoformat())
            .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 80))
            .map(self._prepare_sentinel2_sr)
        )

    def _wind_components_image(self, geometry, start_date, end_date):
        collection = (
            ee.ImageCollection("ECMWF/ERA5_LAND/HOURLY")
            .filterBounds(geometry)
            .filterDate(start_date.isoformat(), end_date.isoformat())
            .select(["u_component_of_wind_10m", "v_component_of_wind_10m"])
        )
        mean = collection.mean().rename(["u", "v"])
        return mean.clip(geometry)

    def _chirps_collection(self, geometry, start_date, end_date):
        return (
            ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY")
            .filterBounds(geometry)
            .filterDate(start_date.isoformat(), end_date.isoformat())
            .select("precipitation")
        )

    def _chirps_climatology(self, geometry, start_date, end_date):
        collection = ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY").filterBounds(geometry)
        month_filters = self._month_filter(start_date.month, end_date.month)
        return collection.filter(month_filters).select("precipitation").mean().rename("precipitation")

    def _month_filter(self, start_month, end_month):
        if start_month <= end_month:
            return ee.Filter.calendarRange(start_month, end_month, "month")
        return ee.Filter.Or(
            ee.Filter.calendarRange(start_month, 12, "month"),
            ee.Filter.calendarRange(1, end_month, "month"),
        )

    def _srtm_image(self):
        return ee.Image("USGS/SRTMGL1_003").select("elevation")

    @staticmethod
    def _landsat_qa_mask(image):
        qa = image.select("QA_PIXEL")
        return (
            qa.bitwiseAnd(1 << 1).eq(0)
            .And(qa.bitwiseAnd(1 << 2).eq(0))
            .And(qa.bitwiseAnd(1 << 3).eq(0))
            .And(qa.bitwiseAnd(1 << 4).eq(0))
            .And(qa.bitwiseAnd(1 << 5).eq(0))
        )

    @staticmethod
    def _prepare_landsat_tm_etm(image):
        mask = EarthEngineAssessmentService._landsat_qa_mask(image)
        optical = (
            image.select(["SR_B1", "SR_B2", "SR_B3", "SR_B4", "SR_B5"], ["blue", "green", "red", "nir", "swir1"])
            .multiply(0.0000275)
            .add(-0.2)
        )
        thermal = image.select("ST_B6").multiply(0.00341802).add(149.0).rename("thermal")
        prepared = ee.Image.cat([optical, thermal])
        prepared = ee.Image(prepared.copyProperties(image, image.propertyNames()))
        return prepared.updateMask(mask)

    @staticmethod
    def _prepare_landsat_oli(image):
        mask = EarthEngineAssessmentService._landsat_qa_mask(image)
        optical = (
            image.select(["SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6"], ["blue", "green", "red", "nir", "swir1"])
            .multiply(0.0000275)
            .add(-0.2)
        )
        thermal = image.select("ST_B10").multiply(0.00341802).add(149.0).rename("thermal")
        prepared = ee.Image.cat([optical, thermal])
        prepared = ee.Image(prepared.copyProperties(image, image.propertyNames()))
        return prepared.updateMask(mask)

    @staticmethod
    def _prepare_sentinel2_sr(image):
        scl = image.select("SCL")
        mask = (
            scl.neq(0)
            .And(scl.neq(1))
            .And(scl.neq(3))
            .And(scl.neq(8))
            .And(scl.neq(9))
            .And(scl.neq(10))
            .And(scl.neq(11))
        )
        reflectance = (
            image.select(
                ["B2", "B3", "B4", "B5", "B6", "B7", "B8", "B8A", "B11", "B12"],
                ["blue", "green", "red", "red_edge1", "red_edge2", "red_edge3", "nir", "nir_narrow", "swir1", "swir2"],
            )
            .multiply(0.0001)
        )
        prepared = ee.Image(reflectance.copyProperties(image, image.propertyNames()))
        return prepared.updateMask(mask)

    @staticmethod
    def _add_sentinel2_indices(image):
        ndvi = image.normalizedDifference(["nir", "red"]).rename("NDVI")
        ndwi = image.normalizedDifference(["green", "swir1"]).rename("NDWI")
        ndbi = image.normalizedDifference(["swir1", "nir"]).rename("NDBI")
        return image.addBands([ndvi, ndwi, ndbi], overwrite=True)

    @staticmethod
    def _add_landsat_indices(image):
        ndvi = image.normalizedDifference(["nir", "red"]).rename("NDVI")
        ndwi = image.normalizedDifference(["green", "swir1"]).rename("NDWI")
        ndmi = image.normalizedDifference(["nir", "swir1"]).rename("NDMI")
        ndbi = image.normalizedDifference(["swir1", "nir"]).rename("NDBI")
        lst_c = image.select("thermal").subtract(273.15).rename("LST_C")
        return image.addBands([ndvi, ndwi, ndmi, ndbi, lst_c], overwrite=True)

    def _download_image(
        self,
        image,
        geometry,
        output_path,
        scale,
        data_type="float",
        fill_nodata=False,
        task=None,
        progress_value=None,
        stage_message=None,
        download_timeout=60,
        tile_on_timeout=True,
    ):
        task = task or self._active_task
        self._raise_if_canceled(task)
        prepared_image = image.clip(geometry)
        if fill_nodata:
            prepared_image = prepared_image.unmask(-9999)
        if data_type == "int":
            prepared_image = prepared_image.toInt16()
        else:
            prepared_image = prepared_image.float()
        params = {
            "scale": scale,
            "crs": "EPSG:4326",
            "region": self._download_region_info(geometry, scale),
            "format": "GEO_TIFF",
        }
        if task is not None and progress_value is not None:
            self._update_task_progress(task, progress_value, stage_message or "Preparing raster download")
        try:
            self._download_image_with_fallback(
                prepared_image,
                geometry,
                output_path,
                scale,
                params,
                task=task,
                progress_value=progress_value,
                stage_message=stage_message,
                download_timeout=download_timeout,
            )
        except HTTPError as exc:
            error_detail = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")
                parsed = json.loads(body)
                error_detail = (
                    parsed.get("error", {}).get("message")
                    or parsed.get("message")
                    or body
                )
            except Exception:
                error_detail = ""
            if exc.code == 400 and self._should_tile_download(error_detail):
                self._download_image_tiled(
                    prepared_image,
                    geometry,
                    output_path,
                    scale,
                    params,
                    error_detail,
                    task=task,
                    progress_value=progress_value,
                    stage_message=stage_message,
                )
                return
            detail_text = f" Earth Engine says: {error_detail}" if error_detail else ""
            raise RuntimeError(
                f"Earth Engine raster download failed with HTTP {exc.code}.{detail_text} "
                "This can happen when the request is too large, the pixel grid is too dense, "
                "or the Earth Engine export request is otherwise invalid for the selected analysis."
            ) from exc
        except URLError as exc:
            reason = getattr(exc, "reason", exc)
            if tile_on_timeout and self._is_timeout_error(reason):
                self._download_image_tiled(
                    prepared_image,
                    geometry,
                    output_path,
                    scale,
                    params,
                    str(reason),
                    task=task,
                    progress_value=progress_value,
                    stage_message=stage_message or "Download timed out; retrying with smaller tiles",
                    download_timeout=download_timeout,
                )
                return
            raise RuntimeError(
                "Earth Engine raster download could not reach the remote server. "
                f"Connection error: {reason}. "
                "Please confirm that internet access is available in QGIS and that DNS/network access is working."
            ) from exc
        except OSError as exc:
            if tile_on_timeout and self._is_timeout_error(exc):
                self._download_image_tiled(
                    prepared_image,
                    geometry,
                    output_path,
                    scale,
                    params,
                    str(exc),
                    task=task,
                    progress_value=progress_value,
                    stage_message=stage_message or "Download timed out; retrying with smaller tiles",
                    download_timeout=download_timeout,
                )
                return
            if self._is_local_file_error(exc):
                raise RuntimeError(
                    "Earth Engine raster download reached the local save step, but the output file could not be "
                    f"created or replaced. Local file error: {exc}. If this output already exists, remove the old "
                    "layer from QGIS, close any program using the file, pause OneDrive sync if needed, or choose a "
                    "new output name/folder. For very long paths, also try a shorter output folder."
                ) from exc
            raise RuntimeError(
                "Earth Engine raster download failed because the network connection could not be established. "
                f"System error: {exc}. "
                "Please check internet connectivity and DNS resolution, then try again."
            ) from exc

    def _download_image_with_fallback(
        self,
        prepared_image,
        geometry,
        output_path,
        scale,
        params,
        tile_depth=0,
        tile_workspace=None,
        task=None,
        progress_value=None,
        stage_message=None,
        download_timeout=60,
    ):
        try:
            self._raise_if_canceled(task or self._active_task)
            if task is not None and progress_value is not None:
                self._update_task_progress(task, progress_value, stage_message or "Downloading raster")
            self._download_image_request(prepared_image, params, output_path, task=task, timeout_seconds=download_timeout)
        except Exception as exc:
            if isinstance(exc, (HTTPError, URLError, OSError, RuntimeError)):
                raise
            error_detail = str(exc)
            if self._should_tile_download(error_detail) and tile_depth < 3:
                self._download_image_tiled(
                    prepared_image,
                    geometry,
                    output_path,
                    scale,
                    params,
                    error_detail,
                    tile_depth=tile_depth + 1,
                    tile_workspace=tile_workspace,
                    task=task,
                    progress_value=progress_value,
                    stage_message=stage_message,
                    download_timeout=download_timeout,
                )
                return
            raise

    def _download_image_request(self, prepared_image, params, output_path, task=None, timeout_seconds=60):
        task = task or self._active_task
        self._raise_if_canceled(task)
        download_url = prepared_image.getDownloadURL(params)
        self._raise_if_canceled(task)
        parsed_url = urlparse(download_url)
        if parsed_url.scheme.lower() != "https":
            raise RuntimeError(
                f"Earth Engine returned an unsupported download URL scheme: {parsed_url.scheme or 'unknown'}."
            )
        host = (parsed_url.hostname or "").lower()
        allowed_hosts = {
            "earthengine.googleapis.com",
            "storage.googleapis.com",
            "googleapis.com",
        }
        if not host or not any(host == allowed or host.endswith(f".{allowed}") for allowed in allowed_hosts):
            raise RuntimeError(
                f"Earth Engine returned an unsupported download host: {host or 'unknown'}."
            )
        request = Request(
            download_url,
            headers={
                "User-Agent": "EnvironmentalAssessmentStudio/4.5",
                "Accept": "image/tiff, application/octet-stream",
            },
        )
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_output_target_writable(output_path)
        temporary_path = self._temporary_raster_path(output_path)
        # The request is restricted to validated Earth Engine / Google HTTPS hosts above.
        try:
            with urlopen(request, timeout=timeout_seconds) as response, open(temporary_path, "wb") as handle:  # nosec B310
                if getattr(response, "status", 200) != 200:
                    raise RuntimeError(
                        f"Earth Engine raster download returned HTTP {getattr(response, 'status', 'unknown')}."
                    )
                while True:
                    self._raise_if_canceled(task)
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
            self._raise_if_canceled(task)
            self._finalize_raster_download(temporary_path, output_path)
        except Exception:
            self._remove_partial_file(temporary_path)
            raise

    @staticmethod
    def _temporary_raster_path(output_path):
        output_path = Path(output_path)
        return output_path.with_name(f".{output_path.stem}.download{output_path.suffix or '.tif'}")

    @staticmethod
    def _remove_partial_file(path):
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass

    @staticmethod
    def _available_raster_output_path(output_path):
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            EarthEngineAssessmentService._ensure_output_target_writable(output_path)
            return output_path
        except PermissionError:
            pass

        for index in range(1, 100):
            candidate = output_path.with_name(f"{output_path.stem}_{index}{output_path.suffix or '.tif'}")
            try:
                EarthEngineAssessmentService._ensure_output_target_writable(candidate)
                return candidate
            except PermissionError:
                continue

        raise PermissionError(
            f"Could not find an unlocked output filename near {output_path}. Remove existing layers from QGIS, "
            "pause OneDrive sync if needed, or choose a new output name/folder."
        )

    @staticmethod
    def _finalize_raster_download(temporary_path, output_path):
        temporary_path = Path(temporary_path)
        output_path = Path(output_path)
        if not temporary_path.exists() or temporary_path.stat().st_size <= 0:
            EarthEngineAssessmentService._remove_partial_file(temporary_path)
            raise RuntimeError(
                "Earth Engine returned an empty raster download. The final GeoTIFF was not written."
            )
        with open(temporary_path, "rb") as handle:
            header = handle.read(4)
        if header not in (b"II*\x00", b"MM\x00*"):
            EarthEngineAssessmentService._remove_partial_file(temporary_path)
            raise RuntimeError(
                "Earth Engine returned a response that is not a valid GeoTIFF. "
                "The final raster was not written; please retry the assessment."
            )
        try:
            temporary_path.replace(output_path)
        except OSError as exc:
            raise PermissionError(
                f"The final raster could not be replaced because the output file is locked or access was denied: "
                f"{output_path}. Remove the existing layer from QGIS, close any program using the file, pause "
                "OneDrive sync if needed, or choose a new output name/folder."
            ) from exc

    @staticmethod
    def _ensure_output_target_writable(output_path):
        output_path = Path(output_path)
        if not output_path.exists():
            return
        try:
            if output_path.stat().st_size == 0:
                output_path.unlink()
                return
        except OSError as exc:
            raise PermissionError(
                f"A zero-byte output raster already exists but could not be removed: {output_path}. "
                "Remove it manually or choose a new output name/folder."
            ) from exc
        try:
            with open(output_path, "ab"):
                pass
        except OSError as exc:
            raise PermissionError(
                f"The output raster already exists and appears to be locked or read-only: {output_path}. "
                "Remove the old layer from QGIS, close any program using it, pause OneDrive sync if needed, "
                "or choose a new output name/folder before rerunning."
            ) from exc
        lock_check_path = output_path.with_name(f".{output_path.stem}.lockcheck{output_path.suffix or '.tif'}")
        try:
            output_path.replace(lock_check_path)
            lock_check_path.replace(output_path)
        except OSError as exc:
            try:
                if lock_check_path.exists() and not output_path.exists():
                    lock_check_path.replace(output_path)
            except OSError:
                pass
            raise PermissionError(
                f"The output raster already exists and cannot be safely replaced: {output_path}. "
                "Remove the old layer from QGIS, close any program using it, pause OneDrive sync if needed, "
                "or choose a new output name/folder before rerunning."
            ) from exc

    @staticmethod
    def _should_tile_download(error_detail):
        detail = (error_detail or "").lower()
        return (
            "total request size" in detail
            or "must be less than or equal to" in detail
            or "user memory limit exceeded" in detail
            or "timed out" in detail
            or "timeout" in detail
        )

    @staticmethod
    def _is_timeout_error(error):
        return "timed out" in str(error).lower() or "timeout" in str(error).lower()

    @staticmethod
    def _is_local_file_error(error):
        text = str(error).lower()
        return (
            isinstance(error, FileNotFoundError)
            or isinstance(error, PermissionError)
            or "access is denied" in text
            or "permission denied" in text
            or "being used by another process" in text
            or "locked" in text
            or "no such file or directory" in text
            or "path too long" in text
            or "filename or extension is too long" in text
            or getattr(error, "winerror", None) in {3, 5, 32, 33, 123, 206}
        )

    def _download_image_tiled(
        self,
        prepared_image,
        geometry,
        output_path,
        scale,
        params,
        error_detail,
        tile_depth=1,
        tile_workspace=None,
        task=None,
        progress_value=None,
        stage_message=None,
        download_timeout=60,
    ):
        task = task or self._active_task
        self._raise_if_canceled(task)
        output_path = Path(output_path)
        tile_factor = self._tile_factor_from_error(error_detail)
        tile_regions = self._tile_regions_for_download(geometry, tile_factor, scale)
        if len(tile_regions) <= 1:
            raise RuntimeError(
                "Earth Engine download tiling was requested, but the AOI could not be split into valid tiles."
            )

        workspace_root = Path(tile_workspace) if tile_workspace else self._tile_workspace_root(output_path)
        tiles_dir = workspace_root / self._tile_directory_name(output_path, tile_depth)
        tiles_dir.mkdir(parents=True, exist_ok=True)
        tile_paths = []
        if task is not None and progress_value is not None:
            self._update_task_progress(
                task,
                progress_value,
                stage_message or f"Downloading raster in {len(tile_regions)} tiles",
            )
        for index, tile_region in enumerate(tile_regions):
            self._raise_if_canceled(task)
            tile_path = tiles_dir / self._tile_output_name(output_path, tile_depth, index)
            tile_params = dict(params)
            tile_params["region"] = tile_region
            tile_geometry = self._region_to_geometry(tile_region)
            if task is not None and progress_value is not None:
                self._update_task_progress(
                    task,
                    progress_value,
                    f"Downloading tile {index + 1} of {len(tile_regions)}",
                )
            try:
                self._download_image_request(
                    prepared_image,
                    tile_params,
                    tile_path,
                    task=task,
                    timeout_seconds=download_timeout,
                )
            except HTTPError as exc:
                tile_error_detail = ""
                try:
                    body = exc.read().decode("utf-8", errors="replace")
                    parsed = json.loads(body)
                    tile_error_detail = (
                        parsed.get("error", {}).get("message")
                        or parsed.get("message")
                        or body
                    )
                except Exception:
                    tile_error_detail = str(exc)
                if exc.code == 400 and self._should_tile_download(tile_error_detail) and tile_depth < 3:
                    self._download_image_tiled(
                        prepared_image,
                        tile_geometry,
                        tile_path,
                        scale,
                        tile_params,
                        tile_error_detail,
                        tile_depth=tile_depth + 1,
                        tile_workspace=workspace_root,
                        task=task,
                        progress_value=progress_value,
                        stage_message=f"Subdividing tile {index + 1} of {len(tile_regions)}",
                        download_timeout=download_timeout,
                    )
                else:
                    raise RuntimeError(
                        f"Earth Engine tiled raster download failed with HTTP {exc.code}. "
                        f"Tile detail: {tile_error_detail or exc}."
                    ) from exc
            except Exception as exc:
                tile_error_detail = str(exc)
                if self._should_tile_download(tile_error_detail) and tile_depth < 3:
                    self._download_image_tiled(
                        prepared_image,
                        tile_geometry,
                        tile_path,
                        scale,
                        tile_params,
                        tile_error_detail,
                        tile_depth=tile_depth + 1,
                        tile_workspace=workspace_root,
                        task=task,
                        progress_value=progress_value,
                        stage_message=f"Subdividing tile {index + 1} of {len(tile_regions)}",
                        download_timeout=download_timeout,
                    )
                else:
                    raise
            tile_paths.append(tile_path)

        if task is not None and progress_value is not None:
            self._update_task_progress(task, progress_value, "Mosaicing downloaded tiles")
        self._raise_if_canceled(task)
        self._mosaic_raster_tiles(tile_paths, output_path)
        for tile_path in tile_paths:
            try:
                tile_path.unlink(missing_ok=True)
            except Exception:
                pass
        self._cleanup_tile_workspace(tiles_dir, workspace_root)

    @staticmethod
    def _tile_factor_from_error(error_detail):
        numbers = [int(value) for value in re.findall(r"\d+", error_detail or "")]
        if len(numbers) >= 2 and numbers[0] > 0 and numbers[1] > 0:
            ratio = numbers[0] / float(numbers[1])
            return max(2, min(6, int(math.ceil(math.sqrt(ratio)))))
        return 2

    @staticmethod
    def _tile_workspace_root(output_path):
        output_path = Path(output_path)
        digest = hashlib.sha1(str(output_path).encode("utf-8")).hexdigest()[:8]
        workspace_root = output_path.parent / "_eas_tile_cache" / digest
        workspace_root.mkdir(parents=True, exist_ok=True)
        return workspace_root

    @staticmethod
    def _tile_directory_name(output_path, tile_depth):
        output_path = Path(output_path)
        safe_stem = re.sub(r"[^A-Za-z0-9]+", "_", output_path.stem).strip("_") or "tile"
        return f"d{tile_depth}_{safe_stem[:12]}"

    @staticmethod
    def _tile_output_name(output_path, tile_depth, index):
        suffix = Path(output_path).suffix or ".tif"
        return f"t{tile_depth}_{index:02d}{suffix}"

    def _tile_regions_for_download(self, geometry, tile_factor, scale):
        region = self._download_region_info(geometry, scale)
        coordinates = (region or {}).get("coordinates") or []
        if not coordinates or not coordinates[0]:
            return [region] if region else []
        ring = coordinates[0]
        xs = [point[0] for point in ring]
        ys = [point[1] for point in ring]
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        x_step = (xmax - xmin) / float(tile_factor)
        y_step = (ymax - ymin) / float(tile_factor)
        if x_step <= 0 or y_step <= 0:
            return [region]

        regions = []
        for row in range(tile_factor):
            for col in range(tile_factor):
                tile_xmin = xmin + (col * x_step)
                tile_xmax = xmax if col == tile_factor - 1 else xmin + ((col + 1) * x_step)
                tile_ymin = ymin + (row * y_step)
                tile_ymax = ymax if row == tile_factor - 1 else ymin + ((row + 1) * y_step)
                regions.append(
                    {
                        "type": "Polygon",
                        "coordinates": [[
                            [tile_xmin, tile_ymin],
                            [tile_xmax, tile_ymin],
                            [tile_xmax, tile_ymax],
                            [tile_xmin, tile_ymax],
                            [tile_xmin, tile_ymin],
                        ]],
                    }
                )
        return regions

    @staticmethod
    def _region_to_geometry(region):
        coordinates = (region or {}).get("coordinates") or []
        if not coordinates or not coordinates[0]:
            raise RuntimeError("Tile region is missing polygon coordinates.")
        ring = coordinates[0]
        xs = [point[0] for point in ring]
        ys = [point[1] for point in ring]
        return ee.Geometry.Rectangle([min(xs), min(ys), max(xs), max(ys)], proj="EPSG:4326", geodesic=False)

    @staticmethod
    def _mosaic_raster_tiles(tile_paths, output_path):
        try:
            from osgeo import gdal
        except Exception as exc:
            raise RuntimeError(
                "Raster tiling succeeded, but GDAL is unavailable for mosaicing the tiles locally."
            ) from exc

        tile_paths = [str(Path(path)) for path in tile_paths if Path(path).exists()]
        if not tile_paths:
            raise RuntimeError("Raster tiling did not produce any tile files to mosaic.")

        output_path = Path(output_path)
        temporary_path = EarthEngineAssessmentService._temporary_raster_path(output_path)
        vrt_path = output_path.with_suffix(".vrt")
        vrt = gdal.BuildVRT(str(vrt_path), tile_paths)
        if vrt is None:
            raise RuntimeError("GDAL could not build a virtual raster from the downloaded tiles.")
        vrt = None
        try:
            translated = gdal.Translate(str(temporary_path), str(vrt_path))
            if translated is None:
                raise RuntimeError("GDAL could not translate the tiled virtual raster into the final GeoTIFF.")
            translated = None
            EarthEngineAssessmentService._finalize_raster_download(temporary_path, output_path)
        except Exception:
            EarthEngineAssessmentService._remove_partial_file(temporary_path)
            raise
        try:
            vrt_path.unlink(missing_ok=True)
        except Exception:
            pass

    @staticmethod
    def _cleanup_tile_workspace(current_dir, workspace_root):
        try:
            current_dir = Path(current_dir)
            workspace_root = Path(workspace_root)
            if current_dir.exists():
                current_dir.rmdir()
            if workspace_root.exists() and workspace_root != current_dir:
                try:
                    workspace_root.rmdir()
                except Exception:
                    pass
        except Exception:
            pass

    def _download_region_info(self, geometry, scale):
        try:
            return geometry.bounds(max(1, int(scale))).getInfo()
        except Exception:
            return geometry.bounds().getInfo()

    def _cleanup_local_categorical_raster(self, raster_path, threshold=4):
        try:
            input_path = Path(raster_path)
            cleaned_path = input_path.with_name(f"{input_path.stem}_cleaned{input_path.suffix}")
            processing.run(
                "gdal:sieve",
                {
                    "INPUT": str(input_path),
                    "THRESHOLD": int(threshold),
                    "EIGHT_CONNECTEDNESS": True,
                    "NO_MASK": True,
                    "MASK_LAYER": None,
                    "EXTRA": "",
                    "OUTPUT": str(cleaned_path),
                },
            )
            if cleaned_path.exists():
                cleaned_path.replace(input_path)
        except Exception:
            return

    def _frequency_histogram(self, image, band_name, geometry, scale):
        histogram_info = image.reduceRegion(
            reducer=ee.Reducer.frequencyHistogram(),
            geometry=geometry,
            scale=scale,
            maxPixels=1_000_000_000,
            bestEffort=True,
        ).getInfo() or {}
        return histogram_info.get(band_name, {})

    def _sum_binary_area(self, image, band_name, geometry, scale):
        area = image.multiply(ee.Image.pixelArea()).reduceRegion(
            reducer=ee.Reducer.sum(),
            geometry=geometry,
            scale=scale,
            maxPixels=1_000_000_000,
            bestEffort=True,
        ).get(band_name)
        return float(area.getInfo() or 0.0)

    def _reclassify_range_image(self, image, classes):
        classified = ee.Image.constant(-9999).rename("summary_class")
        for item in classes:
            min_value = item["min"]
            max_value = item["max"]
            if math.isclose(float(min_value), float(max_value)):
                mask = image.eq(min_value)
            else:
                mask = image.gte(min_value).And(image.lt(max_value))
            classified = classified.where(mask, item["value"])
        return classified.updateMask(image.mask()).toInt16().rename("summary_class")

    def _build_dynamic_range_classes(self, image, geometry, scale, template_classes):
        stats = image.reduceRegion(
            reducer=ee.Reducer.minMax(),
            geometry=geometry,
            scale=scale,
            maxPixels=1_000_000_000,
            bestEffort=True,
        ).getInfo() or {}
        values = [float(value) for value in stats.values() if value is not None]
        if not values:
            return self._normalize_range_classes(template_classes)

        min_value = min(values)
        max_value = max(values)
        if math.isclose(min_value, 0.0) and math.isclose(max_value, 0.0):
            first_label = template_classes[0]["label"].lower()
            if "emission" in first_label:
                return CARBON_EMISSION_ZERO_CLASS
            if "sequestration" in first_label:
                return CARBON_SEQUESTRATION_ZERO_CLASS
        if math.isclose(min_value, max_value):
            max_value = min_value + 1.0

        class_count = len(template_classes)
        interval = (max_value - min_value) / float(class_count)
        classes = []
        for index, template in enumerate(template_classes):
            lower = min_value + (interval * index)
            upper = max_value if index == class_count - 1 else min_value + (interval * (index + 1))
            label = template["label"]
            if any(key in label.lower() for key in ("emission", "sequestration", "carbon")):
                label = f"{label} ({round(lower, 3)} to {round(upper, 3)})"
            classes.append(
                {
                    "value": index,
                    "label": label,
                    "color": template["color"],
                    "min": round(lower, 5),
                    "max": round(upper + (0.00001 if index == class_count - 1 else 0.0), 5),
                }
            )
        return classes

    def _build_continuous_ramp_classes(self, image, geometry, scale, template_classes):
        stats = image.reduceRegion(
            reducer=ee.Reducer.minMax(),
            geometry=geometry,
            scale=scale,
            maxPixels=1_000_000_000,
            bestEffort=True,
        ).getInfo() or {}
        values = [float(value) for value in stats.values() if value is not None]
        if not values:
            return self._normalize_range_classes(template_classes)
        min_value = min(values)
        max_value = max(values)
        if math.isclose(min_value, max_value):
            max_value = min_value + 1.0
        color_templates = template_classes
        class_count = max(2, len(color_templates))
        interval = (max_value - min_value) / float(class_count - 1)
        ramp = []
        for index, template in enumerate(color_templates):
            value = min_value + (interval * index)
            ramp.append(
                {
                    "min": round(value, 5),
                    "max": round(value, 5),
                    "label": f"{round(value, 2)}",
                    "color": template["color"],
                }
            )
        ramp[-1]["min"] = round(max_value, 5)
        ramp[-1]["max"] = round(max_value, 5)
        ramp[-1]["label"] = f"{round(max_value, 2)}"
        return ramp

    @staticmethod
    def _local_continuous_ramp_classes(layer, template_classes, value_scale=1.0):
        provider = layer.dataProvider()
        try:
            stats = provider.bandStatistics(1)
            min_value = float(stats.minimumValue)
            max_value = float(stats.maximumValue)
        except Exception:
            return template_classes
        if not math.isfinite(min_value) or not math.isfinite(max_value):
            return template_classes
        if min_value <= -9999 and max_value <= -9999:
            return template_classes
        if math.isclose(min_value, max_value):
            max_value = min_value + 1.0
        class_count = max(2, len(template_classes))
        interval = (max_value - min_value) / float(class_count - 1)
        ramp = []
        for index, template in enumerate(template_classes):
            value = min_value + (interval * index)
            label_value = value * value_scale
            ramp.append(
                {
                    "min": round(value, 5),
                    "max": round(value, 5),
                    "label": f"{round(label_value, 2)}",
                    "color": template["color"],
                }
            )
        ramp[-1]["min"] = round(max_value, 5)
        ramp[-1]["max"] = round(max_value, 5)
        ramp[-1]["label"] = f"{round(max_value * value_scale, 2)}"
        return ramp

    def _output_date_label(self, analysis_id, start_date, end_date):
        if analysis_id == "carbon_emission":
            actual_start = max(start_date.year, 2001)
            actual_end = min(end_date.year, 2024)
            return f"{actual_start}-01-01 to {actual_end}-12-31 (NASA/ORNL biomass + Hansen forest loss range used)"
        if analysis_id == "anthropogenic_emission":
            actual_start = max(start_date.year, 2012)
            actual_end = min(end_date.year, 2024)
            return f"{actual_start}-01-01 to {actual_end}-12-31 (VIIRS annual nighttime lights range used)"
        if analysis_id == "carbon_sequestration":
            actual_start = max(start_date.year, 2001)
            actual_end = min(end_date.year, 2024)
            return f"{actual_start}-01-01 to {actual_end}-12-31 (MODIS annual NPP range used)"
        if analysis_id == "soil_moisture":
            return f"{start_date.isoformat()} to {end_date.isoformat()} (Landsat NDMI soil moisture proxy range used)"
        if analysis_id == "solar_radiation":
            actual_start = max(start_date.year, 2000)
            actual_end = min(end_date.year, 2025)
            return f"{actual_start}-01-01 to {actual_end}-12-31 (MODIS PAR range used)"
        if analysis_id == "wildfire_risk":
            actual_start = max(start_date.year, 2001)
            actual_end = min(end_date.year, 2025)
            return f"{actual_start}-01-01 to {actual_end}-12-31 (MODIS burned area range used)"
        if analysis_id == "air_quality":
            actual_start, actual_end = self._pm25_effective_date_range(start_date, end_date)
            return f"{actual_start.isoformat()} to {actual_end.isoformat()} (satellite-derived PM2.5 range used)"
        if analysis_id == "terrain_susceptibility":
            return "2000-02-11 to 2000-02-22 (SRTM terrain surface used)"
        if analysis_id == "habitat_fragmentation":
            actual_start = max(start_date.year, 2001)
            actual_end = min(end_date.year, 2024)
            return f"{actual_start}-01-01 to {actual_end}-12-31 (Hansen forest-change range used)"
        if start_date == end_date:
            return start_date.isoformat()
        return f"{start_date.isoformat()} to {end_date.isoformat()} (range aggregate)"

    def _normalize_range_classes(self, classes):
        normalized = []
        for index, item in enumerate(classes):
            normalized.append(
                {
                    "value": index,
                    "label": item["label"],
                    "color": item["color"],
                    "min": item["min"],
                    "max": item["max"],
                }
            )
        return normalized

    def _compute_wind_direction_stat(self, geometry, start_date, end_date):
        wind = self._wind_components_image(geometry, start_date, end_date)
        stats = wind.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geometry,
            scale=ANALYSIS_DEFINITIONS["wind_direction"]["scale"],
            maxPixels=1_000_000_000,
            bestEffort=True,
        ).getInfo() or {}
        u = float(stats.get("u", 0.0))
        v = float(stats.get("v", 0.0))
        return (math.degrees(math.atan2(u, v)) + 360.0) % 360.0

    def _compute_wind_speed_stat(self, geometry, start_date, end_date):
        wind = self._wind_components_image(geometry, start_date, end_date)
        speed_image = wind.expression("sqrt((u*u) + (v*v))", {"u": wind.select("u"), "v": wind.select("v")}).rename("wind_speed")
        stats = speed_image.reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geometry,
            scale=ANALYSIS_DEFINITIONS["wind_direction"]["scale"],
            maxPixels=1_000_000_000,
            bestEffort=True,
        ).getInfo() or {}
        return round(float(stats.get("wind_speed", 0.0)), 4)

    def _direction_label_for_degrees(self, degrees_value):
        sector = int(((degrees_value + 22.5) % 360) // 45)
        return WIND_DIRECTION_CLASSES[sector]["label"]

    def _layer_to_ee_geometry(self, layer):
        if isinstance(layer, list):
            geometries = [ee.Geometry(item) for item in layer]
            if len(geometries) == 1:
                return geometries[0]
            return ee.FeatureCollection([ee.Feature(geometry=item) for item in geometries]).geometry().dissolve()

        destination_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        transformer = QgsCoordinateTransform(layer.crs(), destination_crs, QgsProject.instance())
        geometries = []

        for feature in layer.getFeatures(QgsFeatureRequest()):
            geometry = QgsGeometry(feature.geometry())
            geometry.transform(transformer)
            geometry_json = json.loads(geometry.asJson())
            geometries.append(ee.Geometry(geometry_json))

        if not geometries:
            raise RuntimeError("The AOI layer does not contain any polygon features.")

        if len(geometries) == 1:
            return geometries[0]

        return ee.FeatureCollection([ee.Feature(geometry=item) for item in geometries]).geometry().dissolve()

    @staticmethod
    def _sanitize_name(name):
        cleaned = "".join(char if char.isalnum() or char in ("_", "-") else "_" for char in name.strip())
        cleaned = cleaned[:48].strip("_-")
        return cleaned or "environmental_assessment"

    def _assessment_output_dir(self, base_output_dir, analysis_id, mode, safe_name, aoi_name=None):  # noqa: ARG002
        aoi_safe_name = self._sanitize_name(aoi_name) if aoi_name else ""
        parts = [safe_name[:36].strip("_-") or "Assessment"]
        if aoi_safe_name:
            parts.append(aoi_safe_name[:32].strip("_-"))
        folder_name = "_".join(part for part in parts if part)
        return Path(base_output_dir) / folder_name

    @staticmethod
    def _export_processed_stack_enabled(request):
        return bool(
            getattr(request, "export_processed_stack", False)
            or getattr(request, "export_landsat_stack", False)
        )

    @staticmethod
    def _landsat_trend_workbook_sheets():
        return [
            {
                "sheet_name": "ReadMe",
                "rows": [
                    ["Environmental Assessment Studio", "Landsat 8 LULC trend note"],
                    [
                        "Warning",
                        (
                            "Landsat 8 LULC is a comparative interpretation layer. "
                            "Year-to-year class areas may reflect differences in class detail and separation, "
                            "not only true land-cover change."
                        ),
                    ],
                    [
                        "How to read the trend sheet",
                        (
                            "Use the workbook to compare broad spatial patterns and relative class behavior. "
                            "Treat apparent year-to-year swings in Built-up, Open vegetation / agriculture, Bare ground, and Dense vegetation "
                            "with caution, especially in mixed dry urban-edge landscapes."
                        ),
                    ],
                ],
            },
            {
                "sheet_name": "Justification",
                "rows": [
                    ["Item", "Explanation"],
                    [
                        "Assessment type",
                        "Landsat 8 LULC is best used as a comparison layer alongside Sentinel-based LULC.",
                    ],
                    [
                        "Why year-to-year values can vary",
                        (
                            "A 30 m Landsat pixel can mix roofs, roads, bare soil, shrubs, and cropland. "
                            "One year may separate these classes more clearly than another."
                        ),
                    ],
                    [
                        "What the class areas represent",
                        (
                            "The class areas summarize the classified raster for each year. "
                            "They are useful for broad interpretation, but they should not be treated as a precise "
                            "urban-growth inventory on their own."
                        ),
                    ],
                ],
            },
        ]

    def _write_output_metadata(
        self,
        output_dir,
        safe_name,
        analysis_id,
        mode,
        label,
        output_date_label=None,
        source_details=None,
    ):
        metadata_path = Path(output_dir) / f"{safe_name}_{analysis_id}_{mode}_metadata.txt"
        lines = [
            f"Assessment: {label}",
            f"Analysis ID: {analysis_id}",
            f"Mode: {mode}",
        ]
        if output_date_label:
            lines.append(f"Source period: {output_date_label}")
        if source_details:
            lines.append("")
            lines.append("Source details:")
            for item in source_details:
                lines.append(f"- {item}")
        lines.extend(
            [
                "",
                "Attribute field descriptions:",
            ]
        )
        for field_name, description in self._field_metadata_for_analysis(analysis_id):
            lines.append(f"- {field_name}: {description}")
        metadata_path.write_text("\n".join(lines), encoding="utf-8")
        return str(metadata_path)

    def _build_source_details(self, analysis_id, geometry, start_date, end_date, mode):
        details = []
        collection_count = self._source_image_count(analysis_id, geometry, start_date, end_date)
        if collection_count is not None:
            if mode == "trend":
                details.append(
                    f"The selected period contains {collection_count} source image(s) in the underlying collection. "
                    "Trend outputs summarize that collection year by year or by the chosen interval."
                )
            else:
                details.append(f"{collection_count} source image(s) were combined to create this output.")
        elif analysis_id in {"soil", "terrain_susceptibility", "habitat_fragmentation", "carbon_emission"}:
            details.append(
                "This output comes from a fixed source layer or a model derived from fixed source layers, "
                "so it is not created by averaging a large time stack of images."
            )
        if analysis_id == "lulc_landsat":
            details.append(
                "This assessment builds a simplified land-cover map from annual Landsat 8 composites using water, vegetation, built-up, and bare-ground spectral cues."
            )
            details.append("Landsat 8 LULC is a comparative interpretation layer.")
            details.append(
                "Year-to-year class areas may reflect differences in class detail and separation, not only true land-cover change."
            )
        if analysis_id == "urban_heat_island":
            details.append(
                "Urban Heat Island is calculated from Landsat land-surface temperature as each pixel minus the AOI mean LST for the selected period."
            )
            details.append(
                "Positive values are hotter-than-local-average surfaces; negative values are cooler-than-local-average surfaces."
            )
        if analysis_id == "lulc_modis":
            details.append(
                "MODIS historical land cover is a yearly comparison product available from 2001 to 2024 in Earth Engine."
            )
        if analysis_id == "air_quality":
            actual_start, actual_end = self._pm25_effective_date_range(start_date, end_date)
            details.append(
                "PM2.5 is reported in micrograms per cubic meter (ug/m3) using satellite-derived ground-level concentration estimates."
            )
            details.append(
                f"The PM2.5 archive is currently treated as available from {PM25_AVAILABLE_START_YEAR} to "
                f"{PM25_AVAILABLE_END_YEAR}; this output used {actual_start.isoformat()} to {actual_end.isoformat()}."
            )
        return details

    def _source_image_count(self, analysis_id, geometry, start_date, end_date):
        try:
            if analysis_id in {"lulc", "change_detection"}:
                collection_size = (
                    ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
                    .filterBounds(geometry)
                    .filterDate(start_date.isoformat(), end_date.isoformat())
                    .size()
                    .getInfo()
                )
                return int(collection_size or 0)
            if analysis_id == "lulc_landsat":
                return int(self._landsat8_collection(geometry, start_date, end_date).size().getInfo() or 0)
            if analysis_id == "lulc_modis":
                collection_size = (
                    ee.ImageCollection("MODIS/061/MCD12Q1")
                    .filterBounds(geometry)
                    .filterDate(start_date.isoformat(), end_date.isoformat())
                    .size()
                    .getInfo()
                )
                return int(collection_size or 0)
            if analysis_id in {"lst", "urban_heat_island", "ndvi", "ndwi", "land_degradation", "drought", "soil_moisture", "erosion_risk"}:
                return int(self._landsat_collection(geometry, start_date, end_date).size().getInfo() or 0)
            if analysis_id == "flood":
                collection_size = (
                    ee.ImageCollection("COPERNICUS/S1_GRD")
                    .filterBounds(geometry)
                    .filterDate(start_date.isoformat(), end_date.isoformat())
                    .size()
                    .getInfo()
                )
                return int(collection_size or 0)
            if analysis_id == "solar_radiation":
                collection_size = (
                    ee.ImageCollection("MODIS/062/MCD18C2")
                    .filterBounds(geometry)
                    .filterDate(start_date.isoformat(), end_date.isoformat())
                    .size()
                    .getInfo()
                )
                return int(collection_size or 0)
            if analysis_id == "precipitation_anomaly":
                return int(self._chirps_collection(geometry, start_date, end_date).size().getInfo() or 0)
            if analysis_id == "wind_direction":
                collection_size = (
                    ee.ImageCollection("ECMWF/ERA5_LAND/HOURLY")
                    .filterBounds(geometry)
                    .filterDate(start_date.isoformat(), end_date.isoformat())
                    .size()
                    .getInfo()
                )
                return int(collection_size or 0)
            if analysis_id == "carbon_sequestration":
                collection_size = (
                    ee.ImageCollection("MODIS/061/MOD17A3HGF")
                    .filterBounds(geometry)
                    .filterDate(start_date.isoformat(), end_date.isoformat())
                    .size()
                    .getInfo()
                )
                return int(collection_size or 0)
            if analysis_id == "anthropogenic_emission":
                collection_size = (
                    ee.ImageCollection("NOAA/VIIRS/DNB/ANNUAL_V22")
                    .filterBounds(geometry)
                    .filterDate(start_date.isoformat(), end_date.isoformat())
                    .size()
                    .getInfo()
                )
                return int(collection_size or 0)
            if analysis_id == "wildfire_risk":
                collection_size = (
                    ee.ImageCollection("MODIS/061/MCD64A1")
                    .filterBounds(geometry)
                    .filterDate(start_date.isoformat(), end_date.isoformat())
                    .size()
                    .getInfo()
                )
                return int(collection_size or 0)
            if analysis_id == "air_quality":
                effective_start, effective_end = self._pm25_effective_date_range(start_date, end_date)
                collection_size = (
                    ee.ImageCollection(PM25_COLLECTION_ID)
                    .filterBounds(geometry)
                    .filterDate(effective_start.isoformat(), effective_end.isoformat())
                    .size()
                    .getInfo()
                )
                return int(collection_size or 0)
        except Exception:
            return None
        return None

    def _field_metadata_for_analysis(self, analysis_id):
        fields = [
            ("pixel_value", "Original raster pixel or class value used during polygon conversion."),
            ("class_label", "Human-readable class name assigned to the polygon or class."),
            ("class_code", "Stored class code or raster value."),
            ("value_min", "Lower bound of the class range for this polygon."),
            ("value_max", "Upper bound of the class range for this polygon."),
            ("area_sqm", "Polygon area in square meters."),
        ]
        if analysis_id in {"carbon_emission", "carbon_sequestration"}:
            fields.extend(
                [
                    ("value_min_lb", "Lower bound converted to pounds where applicable."),
                    ("value_max_lb", "Upper bound converted to pounds where applicable."),
                ]
            )
        if analysis_id == "carbon_emission":
            fields.append(("emission_val", "Sampled continuous biomass-emission proxy value at the polygon centroid."))
        if analysis_id == "carbon_sequestration":
            fields.append(("seques_val", "Sampled continuous carbon-sequestration proxy value at the polygon centroid."))
        if analysis_id == "wind_direction":
            fields.extend(
                [
                    ("wind_spd_mps", "Sampled wind speed in meters per second at the polygon centroid."),
                    ("wind_intens", "Wind intensity label derived from sampled wind speed."),
                ]
            )
        if analysis_id == "flood":
            fields.append(("flood_dep_m", "Reference flood-hazard depth in meters sampled at the polygon centroid."))
        if analysis_id == "air_quality":
            fields.append(("pm25_ugm3", "Satellite-derived PM2.5 concentration in micrograms per cubic meter where sampled or classified."))
        return fields

    @staticmethod
    def class_name(class_value):
        return LULC_CLASS_NAMES.get(int(class_value), f"Class {class_value}")

    def _apply_standard_style(self, layer, analysis_id, mode):
        if analysis_id in {"lulc", "lulc_landsat"}:
            renderer = self._build_paletted_renderer(layer, ANALYSIS_DEFINITIONS[analysis_id]["summary_classes"])
        elif analysis_id in {"change_detection", "flood", "land_degradation"} and mode != "trend":
            renderer = self._build_paletted_renderer(layer, ANALYSIS_DEFINITIONS[analysis_id]["summary_classes"])
        elif analysis_id == "wind_direction" and mode != "trend":
            renderer = self._build_range_renderer(layer, WIND_DIRECTION_RENDER_CLASSES)
        elif analysis_id in {
            "ndvi",
            "ndwi",
            "lst",
            "urban_heat_island",
            "drought",
            "soil",
            "carbon_emission",
            "anthropogenic_emission",
            "carbon_sequestration",
            "solar_radiation",
            "precipitation_anomaly",
            "soil_moisture",
            "erosion_risk",
            "terrain_susceptibility",
            "wildfire_risk",
            "air_quality",
            "habitat_fragmentation",
            "runoff_potential",
        } and mode != "trend":
            renderer = self._build_range_renderer(layer, ANALYSIS_DEFINITIONS[analysis_id]["summary_classes"])
        else:
            trend_classes = ANALYSIS_DEFINITIONS.get(analysis_id, {}).get("trend_classes")
            renderer = self._build_range_renderer(layer, trend_classes) if trend_classes else None

        if renderer is not None:
            layer.setRenderer(renderer)
            layer.triggerRepaint()

    def build_custom_paletted_renderer(self, layer, classes):
        return self._build_paletted_renderer(layer, classes)

    def _build_paletted_renderer(self, layer, classes):
        raster_classes = [QgsPalettedRasterRenderer.Class(-9999, QColor(0, 0, 0, 0), "No data")]
        for item in classes:
            raster_classes.append(
                QgsPalettedRasterRenderer.Class(item["value"], QColor(item["color"]), item["label"])
            )
        return QgsPalettedRasterRenderer(layer.dataProvider(), 1, raster_classes)

    def _build_range_renderer(self, layer, classes):
        if not classes:
            return None
        items = []
        for item in classes:
            items.append(
                QgsColorRampShader.ColorRampItem(item["min"], QColor(item["color"]), item["label"])
            )
        last_item = classes[-1]
        items.append(
            QgsColorRampShader.ColorRampItem(last_item["max"], QColor(last_item["color"]), last_item["label"])
        )
        return self._build_pseudocolor_renderer(layer, items)

    def _build_pseudocolor_renderer(self, layer, items):
        shader = QgsRasterShader()
        color_ramp = QgsColorRampShader()
        interpolation = getattr(Qgis, "ShaderInterpolationMethod", None)
        if interpolation is not None:
            color_ramp.setColorRampType(interpolation.Linear)
        else:
            color_ramp.setColorRampType(QgsColorRampShader.Interpolated)
        color_ramp.setColorRampItemList(items)
        color_ramp.setClip(True)
        shader.setRasterShaderFunction(color_ramp)
        renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)
        if items:
            min_value = min(item.value for item in items)
            max_value = max(item.value for item in items)
            if hasattr(renderer, "setClassificationMin"):
                renderer.setClassificationMin(min_value)
            if hasattr(renderer, "setClassificationMax"):
                renderer.setClassificationMax(max_value)
        return renderer

    def _add_vector_metadata_fields(self, layer, analysis_id, mode, custom_classes=None, vector_context=None):
        provider = layer.dataProvider()
        new_fields = [
            QgsField("class_label", QVariant.String),
            QgsField("class_code", QVariant.String),
            QgsField("value_min", QVariant.Double, "double", 20, 5),
            QgsField("value_max", QVariant.Double, "double", 20, 5),
            QgsField("area_sqm", QVariant.Double, "double", 20, 5),
        ]
        if analysis_id in {"carbon_emission", "carbon_sequestration"}:
            new_fields.extend(
                [
                    QgsField("value_min_lb", QVariant.Double, "double", 20, 5),
                    QgsField("value_max_lb", QVariant.Double, "double", 20, 5),
                ]
            )
        if analysis_id == "carbon_emission":
            new_fields.append(QgsField("emission_val", QVariant.Double, "double", 20, 5))
        if analysis_id == "carbon_sequestration":
            new_fields.append(QgsField("seques_val", QVariant.Double, "double", 20, 5))
        if analysis_id == "wind_direction":
            new_fields.extend(
                [
                    QgsField("wind_spd_mps", QVariant.Double, "double", 20, 5),
                    QgsField("wind_intens", QVariant.String),
                ]
            )
        if analysis_id == "flood":
            new_fields.append(QgsField("flood_dep_m", QVariant.Double, "double", 20, 5))
        provider.addAttributes(new_fields)
        layer.updateFields()

        pixel_index = layer.fields().indexFromName("pixel_value")
        label_index = layer.fields().indexFromName("class_label")
        code_index = layer.fields().indexFromName("class_code")
        min_index = layer.fields().indexFromName("value_min")
        max_index = layer.fields().indexFromName("value_max")
        min_lb_index = layer.fields().indexFromName("value_min_lb")
        max_lb_index = layer.fields().indexFromName("value_max_lb")
        wind_speed_index = layer.fields().indexFromName("wind_spd_mps")
        wind_intensity_index = layer.fields().indexFromName("wind_intens")
        emission_index = layer.fields().indexFromName("emission_val")
        sequestration_index = layer.fields().indexFromName("seques_val")
        flood_depth_index = layer.fields().indexFromName("flood_dep_m")
        area_index = layer.fields().indexFromName("area_sqm")

        distance_area = QgsDistanceArea()
        distance_area.setSourceCrs(layer.crs(), QgsProject.instance().transformContext())
        distance_area.setEllipsoid(QgsProject.instance().ellipsoid() or "WGS84")
        wind_speed_layer = None
        wind_speed_provider = None
        continuous_layer = None
        continuous_provider = None
        flood_depth_layer = None
        flood_depth_provider = None
        if vector_context and vector_context.get("wind_speed_raster_path"):
            wind_speed_layer = QgsRasterLayer(vector_context["wind_speed_raster_path"], "Wind Speed Sample")
            if wind_speed_layer.isValid():
                wind_speed_provider = wind_speed_layer.dataProvider()
        if vector_context and vector_context.get("continuous_source_path"):
            continuous_layer = QgsRasterLayer(vector_context["continuous_source_path"], "Continuous Sample")
            if continuous_layer.isValid():
                continuous_provider = continuous_layer.dataProvider()
        if vector_context and vector_context.get("flood_depth_raster_path"):
            flood_depth_layer = QgsRasterLayer(vector_context["flood_depth_raster_path"], "Flood Depth Sample")
            if flood_depth_layer.isValid():
                flood_depth_provider = flood_depth_layer.dataProvider()

        layer.startEditing()
        delete_feature_ids = []
        for feature in layer.getFeatures():
            pixel_value = feature[pixel_index]
            if pixel_value is not None and int(float(pixel_value)) == -9999:
                delete_feature_ids.append(feature.id())
                continue
            class_info = self._class_info_for_value(
                analysis_id,
                mode,
                pixel_value,
                custom_classes=custom_classes,
            )
            area_square_meters = distance_area.measureArea(feature.geometry())
            layer.changeAttributeValue(feature.id(), label_index, class_info.get("label"))
            layer.changeAttributeValue(feature.id(), code_index, str(pixel_value))
            layer.changeAttributeValue(feature.id(), min_index, class_info.get("min"))
            layer.changeAttributeValue(feature.id(), max_index, class_info.get("max"))
            if min_lb_index >= 0:
                layer.changeAttributeValue(
                    feature.id(),
                    min_lb_index,
                    self._convert_carbon_value_to_pounds(analysis_id, class_info.get("min")),
                )
            if max_lb_index >= 0:
                layer.changeAttributeValue(
                    feature.id(),
                    max_lb_index,
                    self._convert_carbon_value_to_pounds(
                        analysis_id,
                        class_info.get("max"),
                    ),
                )
            if analysis_id == "wind_direction" and wind_speed_provider is not None:
                centroid = feature.geometry().centroid().asPoint()
                wind_speed, ok = wind_speed_provider.sample(QgsPointXY(centroid), 1)
                if ok and wind_speed_index >= 0 and wind_intensity_index >= 0:
                    layer.changeAttributeValue(feature.id(), wind_speed_index, round(float(wind_speed), 5))
                    layer.changeAttributeValue(
                        feature.id(),
                        wind_intensity_index,
                        self._wind_intensity_label(float(wind_speed)),
                    )
            centroid = feature.geometry().centroid().asPoint()
            if analysis_id == "carbon_emission" and continuous_provider is not None and emission_index >= 0:
                emission_value, ok = continuous_provider.sample(QgsPointXY(centroid), 1)
                if ok:
                    layer.changeAttributeValue(feature.id(), emission_index, round(float(emission_value), 5))
            if analysis_id == "carbon_sequestration" and continuous_provider is not None and sequestration_index >= 0:
                sequestration_value, ok = continuous_provider.sample(QgsPointXY(centroid), 1)
                if ok:
                    layer.changeAttributeValue(feature.id(), sequestration_index, round(float(sequestration_value), 5))
            if analysis_id == "flood" and flood_depth_provider is not None and flood_depth_index >= 0:
                flood_depth, ok = flood_depth_provider.sample(QgsPointXY(centroid), 1)
                if ok:
                    layer.changeAttributeValue(feature.id(), flood_depth_index, round(float(flood_depth), 5))
            layer.changeAttributeValue(feature.id(), area_index, round(area_square_meters, 5))

        if delete_feature_ids:
            layer.deleteFeatures(delete_feature_ids)
        layer.commitChanges()

    def _convert_carbon_value_to_pounds(self, analysis_id, value):
        if value is None:
            return None
        if analysis_id == "carbon_emission":
            return round(float(value) * 2204622.62185, 5)
        if analysis_id == "carbon_sequestration":
            return round(float(value) * 2.20462262185, 5)
        return None

    def _wind_intensity_label(self, wind_speed):
        if wind_speed < 1.5:
            return "Calm"
        if wind_speed < 3.3:
            return "Light"
        if wind_speed < 5.5:
            return "Gentle"
        if wind_speed < 7.9:
            return "Moderate"
        if wind_speed < 10.7:
            return "Fresh"
        return "Strong"

    def _class_info_for_value(self, analysis_id, mode, pixel_value, custom_classes=None):
        analysis = ANALYSIS_DEFINITIONS[analysis_id]
        numeric_value = float(pixel_value) if pixel_value is not None else None
        int_value = int(float(pixel_value)) if pixel_value is not None else None
        if int_value == -9999:
            return {"label": "No data", "min": None, "max": None}
        if custom_classes:
            for item in custom_classes:
                if item["value"] == int_value:
                    return {"label": item["label"], "min": item.get("min"), "max": item.get("max")}
        if mode == "trend" and analysis.get("trend_classes"):
            if analysis["summary_mode"] == "discrete":
                classes = self._normalize_range_classes(analysis["trend_classes"])
                for item in classes:
                    if item["value"] == int_value:
                        return item
            else:
                for item in analysis["trend_classes"]:
                    if numeric_value is not None and item["min"] <= numeric_value < item["max"]:
                        return item
        if analysis["summary_mode"] == "discrete":
            if analysis_id == "wind_direction":
                classes = analysis["summary_classes"]
            else:
                classes = analysis["summary_classes"]
            for item in classes:
                if item["value"] == int_value:
                    return {"label": item["label"], "min": item.get("value"), "max": item.get("value")}
        else:
            for item in analysis["summary_classes"]:
                if numeric_value is not None and item["min"] <= numeric_value < item["max"]:
                    return item
        return {"label": "Unknown", "min": None, "max": None}

    @staticmethod
    def _load_earth_engine_module():
        global ee
        if ee is not None:
            return ee

        dependency_manager = DependencyManager()
        dependency_manager._refresh_dependency_paths()
        dependency_manager._clear_dependency_import_cache()
        dependency_path = DependencyManager.plugin_dependency_path()
        if dependency_path.exists() and str(dependency_path) not in sys.path:
            sys.path.insert(0, str(dependency_path))

        try:
            user_site = site.getusersitepackages()
        except Exception:
            user_site = None

        if user_site and user_site not in sys.path:
            site.addsitedir(user_site)

        importlib.invalidate_caches()
        try:
            ee = importlib.import_module("ee")
            if not hasattr(ee, "Initialize"):
                ee = None
        except Exception:
            ee = None
        return ee
