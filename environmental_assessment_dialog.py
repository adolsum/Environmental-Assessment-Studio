"""Popup dialog UI for Earth Engine powered environmental assessments."""

from __future__ import annotations

import os
from datetime import date

from qgis.PyQt.QtCore import QCoreApplication, QDate, Qt, QTimer, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from qgis.core import (
    Qgis,
    QgsApplication,
    QgsDistanceArea,
    QgsMapLayerProxyModel,
    QgsProject,
    QgsTask,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgsMapLayerComboBox

from .dependency_manager import DependencyManager
from .gee_service import ANALYSIS_DEFINITIONS, AssessmentRequest, EarthEngineAssessmentService


class EnvironmentalAssessmentDialog(QDialog):
    """Popup dialog that drives Earth Engine environmental assessments."""

    SENTINEL_TREND_STACK_MAX_SQ_KM = 2500.0
    LANDSAT_TREND_STACK_MAX_SQ_KM = 12000.0

    ANALYSIS_ITEMS = [
        ("Land Use Land Cover (Sentinel)", "lulc"),
        ("Land Use Land Cover (Landsat 8)", "lulc_landsat"),
        ("Change Detection", "change_detection"),
        ("Land Surface Temperature", "lst"),
        ("Urban Heat Island", "urban_heat_island"),
        ("Flood Analysis", "flood"),
        ("NDVI", "ndvi"),
        ("Land Degradation", "land_degradation"),
        ("Drought Assessment", "drought"),
        ("Soil Organic Carbon", "soil"),
        ("Wind Direction Assessment", "wind_direction"),
        ("Carbon Emission", "carbon_emission"),
        ("Anthropogenic Emission", "anthropogenic_emission"),
        ("Carbon Sequestration", "carbon_sequestration"),
        ("Solar Radiation", "solar_radiation"),
        ("NDWI", "ndwi"),
        ("Rainfall / Precipitation Anomaly", "precipitation_anomaly"),
        ("Soil Moisture", "soil_moisture"),
        ("Erosion Risk", "erosion_risk"),
        ("Terrain Susceptibility to Erosion / Instability", "terrain_susceptibility"),
        ("Wildfire Risk / Burn Severity", "wildfire_risk"),
        ("PM2.5 Air Quality", "air_quality"),
        ("Habitat Fragmentation / Biodiversity Pressure", "habitat_fragmentation"),
        ("Groundwater Recharge / Runoff Potential", "runoff_potential"),
    ]

    ASSESSMENT_DETAILS = {
        "lulc": {
            "summary": "Land Use Land Cover classifies the selected area into standard surface categories such as water, trees, crops, shrub and scrub, built area, and bare ground. This helps users build a baseline environmental map and understand which land-cover classes occupy the most space within the AOI.",
            "source": "Google Dynamic World (Sentinel-2 derived, 10 m)",
            "method": "The plugin looks at Dynamic World land-cover labels derived from Sentinel-2 imagery, picks the most common class for each pixel, and then colors the map by class. For yearly trend and change outputs, it uses complete Dynamic World years only so partial current-year coverage does not distort the class areas.",
            "output": "A styled categorical raster, class-area summary tables in square meters and hectares, and optional vector polygons with class fields.",
        },
        "lulc_landsat": {
            "summary": "Land Use Land Cover (Landsat 8) gives users a Landsat-based land-cover comparison option from 2013 onward. It uses a simplified class system so the outputs remain more stable and interpretable at 30 meter resolution.",
            "source": "USGS Landsat 8 Collection 2 Level 2 (30 m)",
            "method": "The plugin gathers Landsat 8 images for the selected period, removes cloudy pixels, builds an annual composite, and then groups the land into a simplified set of classes using vegetation, water, built-up, and bare-ground spectral patterns. Trend outputs use complete years only. Landsat 8 LULC is a comparative interpretation layer rather than a strict year-by-year land-accounting product.",
            "output": "A styled categorical raster for snapshot mode, first-year and last-year rasters for trend mode, class-area trend tables in square meters, summary tables, and optional vector polygons with class fields. Year-to-year class areas may reflect differences in class detail and class separation, not only true land-cover change.",
        },
        "change_detection": {
            "summary": "Change Detection compares the land-cover condition at the beginning of the selected period with the land-cover condition at the end of the selected period. It highlights where change happened and what the transition was, such as shrub and scrub to built area.",
            "source": "Google Dynamic World (Sentinel-2 derived, 10 m)",
            "method": "The plugin makes one land-cover map for the start year and one for the end year, then checks which pixels stayed the same and which ones changed. If the requested end year is incomplete in Dynamic World, the plugin uses the latest complete year available for the AOI so the comparison remains trustworthy.",
            "output": "Start-year LULC, end-year LULC, changed-versus-unchanged raster, detailed transition raster, CSV/XLSX transition tables, and optional vector outputs.",
        },
        "lst": {
            "summary": "Land Surface Temperature estimates the temperature of the Earth's surface from thermal satellite observations. It is useful for heat screening, urban heat analysis, and identifying hot exposed surfaces.",
            "source": "Landsat Collection 2 Level 2",
            "method": "The plugin reads the thermal band from Landsat, converts it to degrees Celsius, and then paints the coolest places in one color and the hottest places in another.",
            "output": "A styled heat raster, summary tables, mean temperature statistics, and a trend surface plus annual change table in trend mode.",
        },
        "urban_heat_island": {
            "summary": "Urban Heat Island maps where land surfaces are hotter or cooler than the average land-surface temperature inside the selected AOI. It helps identify heat-stress pockets around built-up, bare, paved, or sparsely vegetated surfaces.",
            "source": "Landsat Collection 2 Level 2 thermal surface temperature. Atmospheric temperature from ERA5-Land may be used as interpretation context, but the default raster is LST-based.",
            "method": "The plugin calculates Landsat land-surface temperature in Celsius, estimates the AOI mean LST for the selected period, and subtracts that mean from each pixel. Positive values show hotter-than-local-average surfaces; negative values show cooler areas. Atmospheric 2 m air-temperature data is much coarser than Landsat and is therefore documented as context rather than blended into the default raster.",
            "output": "A continuous LST-based heat-intensity raster, class-area summary tables, and annual trend outputs showing whether surface heat intensity is increasing or decreasing.",
        },
        "flood": {
            "summary": "Flood Analysis uses radar backscatter behavior to screen for likely water extent during the selected period. It is especially useful where clouds affect optical imagery.",
            "source": "Sentinel-1 GRD",
            "method": "The plugin checks radar images for very dark water-like pixels, maps where water likely spread, and can also attach a flood-hazard depth reference value to the vector output.",
            "output": "A styled flood-extent raster, area summary tables, and optional vector polygons for mapping and reporting.",
        },
        "ndvi": {
            "summary": "NDVI measures vegetation vigor by comparing red and near-infrared reflectance. It helps identify healthy vegetation, stressed vegetation, sparse cover, and non-vegetated surfaces.",
            "source": "Landsat Collection 2 Level 2",
            "method": "The plugin uses Landsat surface reflectance to calculate NDVI. A water safeguard uses Landsat water indices so likely open water is assigned to the water class rather than the bare/stressed class. At 30 m resolution, one pixel can mix roofs, bare soil, trees, grass and shadow, so low positive NDVI should be read as sparse or mixed cover rather than definite vegetation.",
            "output": "A vegetation-condition raster with a clear legend, summary tables, and annual trend outputs.",
        },
        "land_degradation": {
            "summary": "Land Degradation is a screening assessment that flags areas where vegetation response has declined relative to earlier conditions. It is meant to identify areas that may require closer field checks or deeper ecological review.",
            "source": "Landsat NDVI-derived proxy",
            "method": "The plugin compares vegetation strength in the selected period against an earlier baseline and flags places where the vegetation signal dropped.",
            "output": "A styled degradation screening raster, degraded-versus-non-degraded summary tables, and optional vector outputs.",
        },
        "drought": {
            "summary": "Drought Assessment now uses a Landsat-based drought proxy to show relative surface dryness and wetness at a finer spatial resolution. It supports environmental stress screening where a coarse climate grid would hide local patterns.",
            "source": "Landsat NDDI drought proxy",
            "method": "The plugin combines vegetation greenness and surface wetness from Landsat to estimate whether each place looks wetter or drier than its surroundings.",
            "output": "A drought-proxy raster with a clear class legend, summary tables, and annual trend outputs.",
        },
        "soil": {
            "summary": "Soil Organic Carbon maps soil carbon concentration in grams per kilogram (g/kg) as a general indicator of soil quality and ecological condition. It helps users identify relatively low and high soil organic carbon zones and compare their intensity classes directly.",
            "source": "OpenLandMap soil organic carbon",
            "method": "The plugin reads a soil carbon layer and shows how much carbon is estimated in the soil, from low values to high values, using g/kg units.",
            "output": "A styled soil-condition raster, summary tables, and annual trend outputs.",
        },
        "wind_direction": {
            "summary": "Wind Direction Assessment summarizes the prevailing wind direction for the selected period and also samples the associated wind speed. It supports wind movement screening and directional interpretation.",
            "source": "ECMWF ERA5-Land Hourly",
            "output": "A directional raster with cardinal legend classes, summary tables, optional vector outputs with wind speed and intensity fields, and annual trend tables.",
        },
        "carbon_emission": {
            "summary": "Carbon Emission (Biomass) maps a biomass-loss carbon-emission proxy by combining biomass carbon density with forest-loss information. It highlights where vegetation or forest loss may be associated with carbon release.",
            "source": "NASA ORNL biomass carbon density + Hansen forest change",
            "method": "The plugin finds where tree cover was lost and then uses biomass carbon data to estimate how much carbon may have been released in those places.",
            "output": "A classified emission raster, summary tables with range values and pounds conversions, and annual trend outputs.",
        },
        "anthropogenic_emission": {
            "summary": "Anthropogenic Emission uses annual nighttime lights as a proxy for human settlement intensity, infrastructure concentration, and combustion-related pressure. It provides a broad human-activity-based emission indicator.",
            "source": "NOAA VIIRS annual nighttime lights",
            "output": "A classified anthropogenic-emission proxy raster, summary tables, and annual trend outputs.",
        },
        "carbon_sequestration": {
            "summary": "Carbon Sequestration uses annual net primary productivity as a proxy for carbon uptake and sequestration potential. It helps identify areas likely contributing more or less biological carbon capture.",
            "source": "MODIS MOD17A3HGF",
            "method": "The plugin uses plant productivity data to estimate where plants are likely storing more carbon and where they are storing less.",
            "output": "A classified sequestration raster, summary tables with pounds conversions, and annual trend outputs.",
        },
        "solar_radiation": {
            "summary": "Solar Radiation Assessment shows the relative intensity of solar radiation using MODIS photosynthetically active radiation observations for the selected period. It supports site suitability review, solar exposure interpretation, and environmental screening with a detailed radiation surface.",
            "source": "MODIS MCD18C2 PAR",
            "method": "The plugin averages the available MODIS solar-radiation measurements for your date range and then colors lower and higher radiation values across the area.",
            "output": "A solar-radiation raster clipped to the AOI boundary, summary tables, and trend outputs.",
        },
        "ndwi": {
            "summary": "NDWI highlights surface wetness and open-water response using optical reflectance behavior. It is useful for screening wetlands, surface moisture distribution, and general water-related landscape conditions.",
            "source": "Landsat Collection 2 Level 2",
            "method": "The plugin uses Landsat surface reflectance to calculate a water/moisture response based on modified NDWI, NDMI, and a built-up suppression term from NDBI. Values are clamped to the standard -1 to 1 index range. This reduces false wetness over roofs, paved surfaces, and bare built-up areas. Small, shallow, turbid or vegetated dams can still fall into wet or mixed-water classes because 30 m pixels may include water, banks, sediment and vegetation together.",
            "output": "A moisture and water-response raster, summary tables, and annual trend outputs.",
        },
        "precipitation_anomaly": {
            "summary": "Rainfall / Precipitation Anomaly compares rainfall during the selected period against a climatological baseline so users can see whether conditions are drier than normal, near normal, or wetter than normal.",
            "source": "CHIRPS Daily",
            "method": "The plugin measures current rainfall, compares it to a long-term baseline, and maps where rainfall is lower or higher than normal.",
            "output": "A classified anomaly raster, summary tables, and annual trend outputs that quantify rainfall departures and year-to-year change.",
        },
        "soil_moisture": {
            "summary": "Soil Moisture uses a Landsat-derived NDMI moisture proxy to map relative surface wetness at a finer spatial resolution. It helps identify dry zones, moist zones, and areas of stronger surface moisture response for hydrological, agricultural, and drought-related screening.",
            "source": "Landsat Collection 2 NDMI moisture proxy",
            "method": "The plugin compares infrared bands in Landsat to estimate whether the ground looks drier or wetter, then colors the result from dry to moist.",
            "output": "A classified soil-moisture proxy raster, summary tables, and annual trend outputs.",
        },
        "erosion_risk": {
            "summary": "Erosion Risk combines terrain steepness, vegetation cover, and rainfall pressure into a screening index for likely erosion susceptibility. It is a practical screening layer rather than a full erosion model.",
            "source": "SRTM + Landsat NDVI + CHIRPS rainfall proxy",
            "output": "A classified erosion-risk raster, summary tables, and annual trend outputs.",
        },
        "terrain_susceptibility": {
            "summary": "Terrain Susceptibility to Erosion / Instability uses terrain steepness as a fast indicator of ground that may be more prone to erosion, shallow instability, and difficult surface conditions. It is useful for identifying steep ground and areas that may deserve added caution in environmental review.",
            "source": "USGS SRTM 30m",
            "method": "The plugin measures slope from elevation data and assumes steeper ground is more likely to be unstable or erode more easily than flatter ground.",
            "output": "A classified terrain-susceptibility raster clipped to the AOI and summary tables that quantify the area under each slope class.",
        },
        "wildfire_risk": {
            "summary": "Wildfire Risk / Burn Severity summarizes burn frequency from burned-area observations to indicate recurring wildfire pressure or fire-affected zones within the selected area.",
            "source": "MODIS Burned Area",
            "output": "A classified wildfire-pressure raster, summary tables, and annual trend outputs.",
        },
        "air_quality": {
            "summary": "PM2.5 Air Quality maps estimated fine particulate matter concentration in micrograms per cubic meter. It supports regional air-quality screening and exposure interpretation.",
            "source": "Global satellite-derived ground-level PM2.5, ACAG / SatPM-style open Earth Engine collection",
            "method": "The plugin reads annual satellite-derived PM2.5 concentration surfaces, clips them to the AOI, and summarizes the mean concentration in ug/m3. If the selected period extends beyond the available PM2.5 archive, the nearest available annual data are used and documented in the metadata.",
            "output": "A classified PM2.5 concentration raster in ug/m3, summary tables, metadata, and annual trend outputs where available.",
        },
        "habitat_fragmentation": {
            "summary": "Habitat Fragmentation / Biodiversity Pressure screens ecological pressure by mapping fragmented forest structure and nearby forest loss. It helps identify landscapes where habitat continuity may be breaking down.",
            "source": "Hansen Global Forest Change",
            "output": "A classified fragmentation-pressure raster, summary tables, and annual trend outputs.",
        },
        "runoff_potential": {
            "summary": "Groundwater Recharge / Runoff Potential combines flow accumulation, slope, and rainfall pressure to indicate where runoff concentration may be stronger and where hydrological response may differ across the landscape.",
            "source": "HydroSHEDS + SRTM + CHIRPS rainfall proxy",
            "output": "A classified runoff-potential raster, summary tables, and annual trend outputs.",
        },
    }

    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.service = EarthEngineAssessmentService()
        self.dependency_manager = DependencyManager()
        self.current_task = None
        self.dependency_task = None
        self._displayed_progress = 0
        self._progress_pulse_index = 0
        self._progress_stage_message = self.tr("Ready")
        self._progress_pulse_timer = QTimer(self)
        self._progress_pulse_timer.setInterval(700)
        self._progress_pulse_timer.timeout.connect(self._advance_progress_pulse)
        self.setObjectName("EnvironmentalAssessmentDialog")
        self.setWindowTitle(self.tr("Environmental Assessment Studio"))
        self.setWindowFlags(self.windowFlags() | self._minimize_button_flag())
        self.setWindowModality(self._non_modal_value())
        self.resize(980, 620)
        self.setMinimumSize(760, 540)
        self.setLayout(self._build_ui())
        self._sync_mode_state()
        self._update_guidance()

    @staticmethod
    def tr(text):
        return QCoreApplication.translate("EnvironmentalAssessmentDialog", text)

    @staticmethod
    def _non_modal_value():
        window_modality = getattr(Qt, "WindowModality", None)
        if window_modality is not None:
            return window_modality.NonModal
        return Qt.NonModal

    @staticmethod
    def _widget_width_wrap_mode():
        line_wrap_mode = getattr(QTextBrowser, "LineWrapMode", None)
        if line_wrap_mode is not None:
            return line_wrap_mode.WidgetWidth
        return QTextBrowser.WidgetWidth

    @staticmethod
    def _align_left_value():
        alignment = getattr(Qt, "AlignmentFlag", None)
        if alignment is not None:
            return alignment.AlignLeft
        return Qt.AlignLeft

    @staticmethod
    def _minimize_button_flag():
        window_type = getattr(Qt, "WindowType", None)
        if window_type is not None:
            return window_type.WindowMinimizeButtonHint
        return Qt.WindowMinimizeButtonHint

    @staticmethod
    def _align_top_value():
        alignment = getattr(Qt, "AlignmentFlag", None)
        if alignment is not None:
            return alignment.AlignTop
        return Qt.AlignTop

    def _build_ui(self):
        root_layout = QVBoxLayout()
        content_layout = QHBoxLayout()
        content_layout.setSpacing(12)

        params_group = QGroupBox(self.tr("Assessment Inputs"), self)
        params_layout = QVBoxLayout(params_group)
        params_layout.setContentsMargins(10, 10, 10, 10)

        form_layout = QFormLayout()
        form_layout.setLabelAlignment(self._align_left_value())
        form_layout.setFormAlignment(self._align_top_value())
        form_layout.setSpacing(8)

        self.aoi_combo = QgsMapLayerComboBox(params_group)
        self.aoi_combo.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        form_layout.addRow(self._field_label(self.tr("Area of Interest")), self._layer_selector_row())

        self.analysis_combo = QComboBox(params_group)
        for label, analysis_id in self.ANALYSIS_ITEMS:
            self.analysis_combo.addItem(label, analysis_id)
        self.analysis_combo.currentIndexChanged.connect(self._update_guidance)
        self.analysis_combo.currentIndexChanged.connect(self._sync_mode_state)
        form_layout.addRow(self._field_label(self.tr("Assessment Type")), self.analysis_combo)

        self.mode_combo = QComboBox(params_group)
        self.mode_combo.addItem(self.tr("Single period output"), "snapshot")
        self.mode_combo.addItem(self.tr("Trend analysis"), "trend")
        self.mode_combo.currentIndexChanged.connect(self._sync_mode_state)
        form_layout.addRow(self._field_label(self.tr("Analysis Mode")), self.mode_combo)

        self.interval_combo = QComboBox(params_group)
        self.interval_combo.addItem(self.tr("Every year"), 1)
        self.interval_combo.addItem(self.tr("Every 2 years"), 2)
        self.interval_combo.addItem(self.tr("Every 3 years"), 3)
        self.interval_combo.addItem(self.tr("Every 5 years"), 5)
        form_layout.addRow(self._field_label(self.tr("Trend Interval")), self.interval_combo)

        self.start_date = QDateEdit(params_group)
        self.start_date.setCalendarPopup(True)
        self.start_date.setDate(QDate.currentDate().addYears(-1))
        form_layout.addRow(self._field_label(self.tr("Start Date")), self.start_date)

        self.end_date = QDateEdit(params_group)
        self.end_date.setCalendarPopup(True)
        self.end_date.setDate(QDate.currentDate())
        form_layout.addRow(self._field_label(self.tr("End Date")), self.end_date)

        self.output_name = QLineEdit(params_group)
        self.output_name.setPlaceholderText(self.tr("Optional custom name for saved outputs"))
        form_layout.addRow(self._field_label(self.tr("Output Name")), self.output_name)

        form_layout.addRow(self._field_label(self.tr("Output Folder")), self._output_folder_row())

        self.convert_to_vector_checkbox = QCheckBox(
            self.tr("Convert raster output to vector polygons with attribute fields"),
            params_group,
        )
        self.convert_to_vector_checkbox.setChecked(False)
        form_layout.addRow(self._field_label(self.tr("Convert To Vector")), self.convert_to_vector_checkbox)

        self.generate_reports_checkbox = QCheckBox(
            self.tr("Generate CSV and XLSX report tables"),
            params_group,
        )
        self.generate_reports_checkbox.setChecked(True)
        form_layout.addRow(self._field_label(self.tr("Generate Reports")), self.generate_reports_checkbox)

        self.export_landsat_stack_checkbox = QCheckBox(
            self.tr("Export Processed Satellite Band Stacks for custom sample training/classification"),
            params_group,
        )
        self.export_landsat_stack_checkbox.setChecked(False)
        form_layout.addRow("", self.export_landsat_stack_checkbox)
        self.export_landsat_stack_hint = QLabel(
            self.tr("Band stack exports are large and may significantly increase runtime."),
            params_group,
        )
        self.export_landsat_stack_hint.setWordWrap(True)
        self.export_landsat_stack_hint.setContentsMargins(0, -6, 0, 0)
        self.export_landsat_stack_hint.setStyleSheet("color:#64748b; font-size:11px; margin-top:-6px;")
        form_layout.addRow("", self.export_landsat_stack_hint)

        params_layout.addLayout(form_layout)

        self.mode_hint = QLabel(params_group)
        self.mode_hint.setWordWrap(True)
        self.mode_hint.setStyleSheet("color:#4d5b6a;")
        params_layout.addWidget(self.mode_hint)

        self.progress_bar = QProgressBar(params_group)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(self.tr("Ready"))
        params_layout.addWidget(self.progress_bar)

        settings_tabs = QTabWidget(params_group)

        settings_group = QGroupBox(self.tr("Settings And Dependencies"), params_group)
        settings_layout = QVBoxLayout(settings_group)
        settings_layout.setContentsMargins(10, 10, 10, 10)
        settings_layout.setSpacing(8)

        self.dependency_status = QLabel(settings_group)
        self.dependency_status.setWordWrap(True)
        self.dependency_status.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        settings_layout.addWidget(self.dependency_status)

        project_row = QHBoxLayout()
        project_row.setContentsMargins(0, 0, 0, 0)
        project_row.setSpacing(6)
        self.project_id_edit = QLineEdit(settings_group)
        self.project_id_edit.setPlaceholderText(self.tr("Google Cloud project ID registered for Earth Engine"))
        self.project_id_edit.setText(self.dependency_manager.project_id())
        project_row.addWidget(self.project_id_edit, 1)
        self.save_project_button = QPushButton(self.tr("Save Project ID"), settings_group)
        self.save_project_button.clicked.connect(self.save_project_id)
        project_row.addWidget(self.save_project_button)
        settings_layout.addLayout(project_row)

        dependency_buttons = QHBoxLayout()
        self.refresh_status_button = QPushButton(self.tr("Refresh Status"), settings_group)
        self.install_dependency_button = QPushButton(self.tr("Install Or Upgrade Earth Engine"), settings_group)
        self.authenticate_button = QPushButton(self.tr("Authenticate Earth Engine"), settings_group)
        self.initialize_button = QPushButton(self.tr("Initialize Earth Engine"), settings_group)
        self.refresh_status_button.clicked.connect(self.update_dependency_status)
        self.install_dependency_button.clicked.connect(self.install_earth_engine_dependency)
        self.authenticate_button.clicked.connect(self.authenticate_earth_engine)
        self.initialize_button.clicked.connect(self.initialize_earth_engine)
        dependency_buttons.addWidget(self.refresh_status_button)
        dependency_buttons.addWidget(self.install_dependency_button)
        dependency_buttons.addWidget(self.authenticate_button)
        dependency_buttons.addWidget(self.initialize_button)
        settings_layout.addLayout(dependency_buttons)

        self.settings_help = QLabel(
            self.tr(
                "The plugin already runs inside QGIS Python. If Earth Engine is missing, use these buttons to "
                "download it into a persistent QGIS profile folder, then authenticate and initialize it with your "
                "registered Google Cloud project."
            ),
            settings_group,
        )
        self.settings_help.setWordWrap(True)
        self.settings_help.setStyleSheet("color:#4d5b6a;")
        settings_layout.addWidget(self.settings_help)

        settings_page = QWidget(params_group)
        settings_page_layout = QVBoxLayout(settings_page)
        settings_page_layout.setContentsMargins(0, 0, 0, 0)
        settings_page_layout.addWidget(settings_group)
        settings_tabs.addTab(settings_page, self.tr("Plugin Settings"))

        signup_page = QWidget(params_group)
        signup_layout = QVBoxLayout(signup_page)
        signup_layout.setContentsMargins(10, 10, 10, 10)
        signup_intro = QLabel(
            self.tr(
                "If you do not yet have a Google Earth Engine account or Google Cloud project, "
                "use the links below to sign in, request access, create a project, register it, "
                "and then paste the project ID into this plugin."
            ),
            signup_page,
        )
        signup_intro.setWordWrap(True)
        signup_intro.setStyleSheet("color:#4d5b6a;")
        signup_layout.addWidget(signup_intro)

        signup_browser = QTextBrowser(signup_page)
        signup_browser.setReadOnly(True)
        signup_browser.setOpenExternalLinks(True)
        signup_browser.setLineWrapMode(self._widget_width_wrap_mode())
        signup_browser.setHtml(self._account_setup_html())
        signup_layout.addWidget(signup_browser)

        signup_buttons = QHBoxLayout()
        ee_access_button = QPushButton(self.tr("Open Earth Engine Access"), signup_page)
        ee_register_button = QPushButton(self.tr("Open Project Registration"), signup_page)
        gcp_projects_button = QPushButton(self.tr("Open Cloud Projects"), signup_page)
        setup_video_button = QPushButton(self.tr("Watch Setup Tutorial"), signup_page)
        run_video_button = QPushButton(self.tr("Watch Assessment Tutorial"), signup_page)
        ee_access_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://developers.google.com/earth-engine/guides/access"))
        )
        ee_register_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://code.earthengine.google.com/register"))
        )
        gcp_projects_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://console.cloud.google.com/projectcreate"))
        )
        setup_video_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://youtu.be/pnkM7dhcORw"))
        )
        run_video_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://youtu.be/2sYAkivyf5M"))
        )
        signup_buttons.addWidget(ee_access_button)
        signup_buttons.addWidget(ee_register_button)
        signup_buttons.addWidget(gcp_projects_button)
        signup_buttons.addWidget(setup_video_button)
        signup_buttons.addWidget(run_video_button)
        signup_layout.addLayout(signup_buttons)
        settings_tabs.addTab(signup_page, self.tr("Earth Engine Setup"))

        guide_page = QWidget(params_group)
        guide_layout = QVBoxLayout(guide_page)
        guide_layout.setContentsMargins(0, 0, 0, 0)
        guide_browser = QTextBrowser(guide_page)
        guide_browser.setReadOnly(True)
        guide_browser.setLineWrapMode(self._widget_width_wrap_mode())
        guide_browser.setHtml(self._help_html())
        guide_layout.addWidget(guide_browser)
        settings_tabs.addTab(guide_page, self.tr("Assessment Guide"))
        settings_tabs.setStyleSheet(
            """
            QTabBar::tab {
                background-color: #4a4a4a;
                color: #f2f2f2;
                border: 1px solid #5b5b5b;
                padding: 6px 10px;
            }
            QTabBar::tab:selected {
                background-color: #5a5a5a;
                color: #ffffff;
            }
            QTabWidget::pane {
                background-color: #111111;
                border: 1px solid #3a3a3a;
                top: -1px;
            }
            QTextBrowser {
                background-color: #111111;
            }
            """
        )

        params_layout.addWidget(settings_tabs)

        buttons_layout = QHBoxLayout()
        self.run_button = QPushButton(self.tr("Run Assessment"), params_group)
        self.close_button = QPushButton(self.tr("Close"), params_group)
        self.cancel_button = QPushButton(self.tr("Cancel Running Task"), params_group)
        self.run_button.clicked.connect(self.run_assessment)
        self.close_button.clicked.connect(self.close)
        self.cancel_button.clicked.connect(self.cancel_current_task)
        self.cancel_button.setEnabled(False)
        buttons_layout.addWidget(self.run_button)
        buttons_layout.addWidget(self.cancel_button)
        buttons_layout.addWidget(self.close_button)
        params_layout.addLayout(buttons_layout)

        help_group = QGroupBox(self.tr("Assessment Guidance"), self)
        help_layout = QVBoxLayout(help_group)
        self.help_browser = QTextBrowser(help_group)
        self.help_browser.setReadOnly(True)
        self.help_browser.setOpenExternalLinks(True)
        self.help_browser.setLineWrapMode(self._widget_width_wrap_mode())
        help_layout.addWidget(self.help_browser)

        content_layout.addWidget(params_group, 3)
        content_layout.addWidget(help_group, 2)

        content_widget = QWidget(self)
        content_widget.setLayout(content_layout)

        scroll_area = QScrollArea(self)
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(content_widget)
        root_layout.addWidget(scroll_area)
        self.update_dependency_status()
        return root_layout

    def _layer_selector_row(self):
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(self.aoi_combo, 1)

        browse_button = QPushButton(self.tr("Browse..."), self)
        browse_button.clicked.connect(self._browse_for_aoi)
        row.addWidget(browse_button)
        return row

    def _output_folder_row(self):
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self.output_dir_edit = QLineEdit(self)
        self.output_dir_edit.setPlaceholderText(self.tr("Choose a folder for rasters, XLSX, and graphs"))
        row.addWidget(self.output_dir_edit, 1)

        browse_button = QPushButton(self.tr("Browse..."), self)
        browse_button.clicked.connect(self._browse_for_output_dir)
        row.addWidget(browse_button)
        return row

    def _browse_for_aoi(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Select AOI Layer"),
            "",
            self.tr("Vector Files (*.gpkg *.shp *.geojson *.json);;All Files (*.*)"),
        )
        if not file_path:
            return

        layer_name = os.path.basename(file_path)
        layer = QgsVectorLayer(file_path, layer_name, "ogr")
        if not layer.isValid():
            self._show_warning(self.tr("The selected file could not be loaded as a vector layer."))
            return

        if layer.geometryType() != QgsWkbTypes.PolygonGeometry:
            self._show_warning(self.tr("The AOI layer must be a polygon layer."))
            return

        QgsProject.instance().addMapLayer(layer)
        self.aoi_combo.setLayer(layer)

    def _browse_for_output_dir(self):
        directory = QFileDialog.getExistingDirectory(
            self,
            self.tr("Select Output Folder"),
            self.output_dir_edit.text().strip() or "",
        )
        if directory:
            self.output_dir_edit.setText(directory)

    def _field_label(self, text):
        label = QLabel(text, self)
        label.setStyleSheet("font-weight: 600;")
        return label

    def _sync_mode_state(self):
        mode = self.mode_combo.currentData()
        if mode == "trend":
            self.mode_hint.setText(
                self.tr(
                    "Trend analysis creates annual CSV and XLSX tables, an SVG graph, "
                    "a trend raster for supported assessments, annual change columns, and class-area summary tables."
                )
            )
            self.interval_combo.setEnabled(True)
            self.generate_reports_checkbox.setEnabled(True)
        else:
            self.mode_hint.setText(
                self.tr(
                    "Single period output creates one styled raster plus summary tables that report "
                    "the area of each class in square meters and hectares."
                )
            )
            self.interval_combo.setEnabled(False)
            self.generate_reports_checkbox.setEnabled(True)

        analysis_id = self.analysis_combo.currentData()
        can_export_stack = analysis_id in {"lulc", "lulc_landsat"}
        self.export_landsat_stack_checkbox.setEnabled(can_export_stack)
        if analysis_id == "lulc_landsat":
            self.export_landsat_stack_checkbox.setToolTip(
                self.tr(
                    "Exports an analysis-ready Landsat stack with radiometrically corrected surface reflectance, "
                    "thermal band, and derived indices so users can create their own training samples."
                )
            )
        elif analysis_id == "lulc":
            self.export_landsat_stack_checkbox.setToolTip(
                self.tr(
                    "Exports an analysis-ready Sentinel-2 surface reflectance stack with key spectral bands "
                    "and derived indices so users can create their own training samples."
                )
            )
        else:
            self.export_landsat_stack_checkbox.setChecked(False)
            self.export_landsat_stack_checkbox.setToolTip(
                self.tr("This option is available for Sentinel and Landsat land-cover assessments.")
            )

    def _update_guidance(self):
        analysis_id = self.analysis_combo.currentData()
        detail = self.ASSESSMENT_DETAILS.get(analysis_id, {})
        analysis = ANALYSIS_DEFINITIONS.get(analysis_id, {})
        title = analysis.get("label", self.analysis_combo.currentText())
        stats = analysis.get("stat_label", self.tr("Summary statistic"))
        trend = analysis.get("trend_label", self.tr("Annual trend output"))
        self.help_browser.setHtml(
            f"""
            <div style="font-family:'Segoe UI'; font-size:10pt; line-height:1.38;">
              <h3 style="margin:0 0 10px 0;">{title}</h3>
              <p style="margin:0 0 10px 0;">{detail.get('summary', '')}</p>
              <p style="margin:0 0 8px 0;"><b>Data source:</b> {detail.get('source', 'Earth Engine')}</p>
              <p style="margin:0 0 8px 0;"><b>How it works:</b> {detail.get('method', 'The plugin reads the selected Earth Engine dataset for your date range, clips it to your area of interest, summarizes the values, and prepares map outputs and tables.')}</p>
              <p style="margin:0 0 8px 0;"><b>Primary metric:</b> {stats}</p>
              <p style="margin:0 0 8px 0;"><b>Trend output:</b> {trend}</p>
              <p style="margin:0 0 10px 0;"><b>Expected outputs:</b> {detail.get('output', '')}</p>
            </div>
            """
        )

    def _help_html(self):
        return """
        <div style="font-family:'Segoe UI'; font-size:10pt; line-height:1.38;">
          <h3 style="margin:0 0 10px 0;">Assessment Guide</h3>
          <p style="margin:0 0 10px 0;">
            Environmental Assessment Studio connects QGIS to Google Earth Engine so you can run
            environmental analyses over your own area of interest and bring the outputs back into QGIS.
          </p>
          <h4 style="margin:10px 0 4px 0;">Current Assessment Families</h4>
          <ul style="margin:0 0 8px 18px; padding:0;">
            <li>Land cover and land-change assessments such as LULC and Change Detection</li>
            <li>Surface condition assessments such as NDVI, NDWI, LST, Drought, and Soil Organic Carbon</li>
            <li>Risk and pressure assessments such as Flood, Erosion Risk, Wildfire Risk, and Air Quality</li>
            <li>Climate and energy assessments such as Wind Direction, Solar Radiation, and Precipitation Anomaly</li>
            <li>Carbon and ecosystem assessments such as Carbon Emission, Carbon Sequestration, and Habitat Fragmentation</li>
          </ul>
          <h4 style="margin:10px 0 4px 0;">Trend Analysis</h4>
          <p style="margin:0;">
            Trend analysis creates yearly outputs, summary statistics, annual change columns, and graphs where supported,
            while snapshot mode focuses on a single-period mapped output plus summary tables.
          </p>
        </div>
        """

    def _account_setup_html(self):
        return """
        <div style="font-family:'Segoe UI'; font-size:10pt; line-height:1.4;">
          <h3 style="margin:0 0 10px 0;">Google Earth Engine Signup And Project Setup</h3>
          <ol style="margin:0 0 8px 18px; padding:0;">
            <li>Sign in with your Google account on the Earth Engine access page.</li>
            <li>Create a new Google Cloud project or choose an existing one.</li>
            <li>Register the project for Earth Engine use and enable the Earth Engine API.</li>
            <li>Copy the project ID and paste it into the plugin's Project ID field.</li>
            <li>Use the plugin buttons to authenticate and initialize Earth Engine inside QGIS.</li>
          </ol>
          <p style="margin:8px 0 0 0;">
            Useful links:
            <a href="https://developers.google.com/earth-engine/guides/access">Earth Engine access guide</a>,
            <a href="https://code.earthengine.google.com/register">project registration</a>,
            <a href="https://console.cloud.google.com/projectcreate">create Cloud project</a>.
          </p>
          <p style="margin:8px 0 0 0;">
            Video tutorials:
            <a href="https://youtu.be/pnkM7dhcORw">How to setup the plugin and generate a GEE Project ID</a>,
            <a href="https://youtu.be/2sYAkivyf5M">How to run an assessment</a>.
          </p>
        </div>
        """

    def run_assessment(self):
        aoi_layer = self.aoi_combo.currentLayer()
        if aoi_layer is None:
            self._show_warning(self.tr("Choose an Area of Interest polygon layer."))
            return

        if self.start_date.date() > self.end_date.date():
            self._show_warning(self.tr("The start date must be on or before the end date."))
            return

        output_dir = self.output_dir_edit.text().strip()
        if not output_dir:
            self._show_warning(self.tr("Choose an output folder for the assessment outputs."))
            return

        if not self.dependency_manager.earth_engine_available():
            self.update_dependency_status()
            self._show_warning(
                self.tr(
                    "Google Earth Engine is not installed yet in the QGIS Python environment. "
                    "Use the Settings And Dependencies section to install it first."
                )
            )
            return

        try:
            aoi_geometry_jsons = self.service.extract_aoi_geometry_jsons(aoi_layer)
        except Exception as exc:
            self._show_warning(self.tr("AOI preparation failed: {0}").format(str(exc)))
            return

        if not self._validate_processed_stack_request(aoi_layer):
            return

        request = AssessmentRequest(
            analysis_id=self.analysis_combo.currentData(),
            mode=self.mode_combo.currentData(),
            start_date=self._qdate_to_date(self.start_date.date()),
            end_date=self._qdate_to_date(self.end_date.date()),
            output_dir=output_dir,
            output_name=self.output_name.text().strip(),
            aoi_name=aoi_layer.name(),
            interval_years=int(self.interval_combo.currentData() or 1),
            generate_reports=self.generate_reports_checkbox.isChecked(),
            convert_to_vector=self.convert_to_vector_checkbox.isChecked(),
            export_processed_stack=self.export_landsat_stack_checkbox.isChecked(),
            export_landsat_stack=self.export_landsat_stack_checkbox.isChecked(),
            aoi_geometry_jsons=aoi_geometry_jsons,
        )

        self._set_run_busy(True)
        self.iface.messageBar().pushMessage(
            self.tr("Environmental Assessment Studio"),
            self.tr("Assessment started in the background. You can continue working in QGIS."),
            level=Qgis.Info,
            duration=5,
        )

        task_title = self.tr("{0} ({1})").format(
            self.analysis_combo.currentText(),
            self.mode_combo.currentText(),
        )
        task = QgsTask.fromFunction(
            task_title,
            self._run_assessment_task,
            request=request,
            on_finished=self._on_assessment_task_finished,
        )
        self.current_task = task
        task.progressChanged.connect(self._on_task_progress_changed)
        QgsApplication.taskManager().addTask(task)

    def _set_run_busy(self, is_busy):
        self.run_button.setEnabled(not is_busy)
        self.close_button.setEnabled(True)
        self.cancel_button.setEnabled(is_busy)
        if is_busy:
            self._displayed_progress = 0
            self._progress_pulse_index = 0
            self._progress_stage_message = self.tr("Starting assessment")
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat(self.tr("Starting assessment (0%)"))
            self._progress_pulse_timer.start()
        else:
            self._progress_pulse_timer.stop()
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat(self.tr("Completed"))

    def _run_assessment_task(self, task, request):
        setattr(task, "stage_message", self.tr("Starting assessment..."))
        setattr(task, "last_progress_value", 0)
        task.setProgress(5)
        result = self.service.run(request, task=task)
        task.setProgress(100)
        return {"request": request, "result": result}

    def _on_task_progress_changed(self, value):
        self._displayed_progress = max(self._displayed_progress, int(value))
        self.progress_bar.setValue(self._displayed_progress)
        stage_message = self.tr("Working...")
        if self.current_task is not None:
            stage_message = getattr(self.current_task, "stage_message", stage_message) or stage_message
        self._progress_stage_message = stage_message.rstrip(". ")
        pulse = "." * ((self._progress_pulse_index % 3) + 1)
        self.progress_bar.setFormat(self.tr("{0}{1} ({2}%)").format(self._progress_stage_message, pulse, self._displayed_progress))

    def _on_assessment_task_finished(self, exception, task_result=None):
        self._set_run_busy(False)
        self.current_task = None

        if exception is not None:
            self._progress_pulse_timer.stop()
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat(self.tr("Failed"))
            message = self.tr("Assessment failed: {0}").format(str(exception))
            if "cancelled by user" in str(exception).lower():
                self.progress_bar.setFormat(self.tr("Cancelled"))
                message = self.tr("Assessment cancelled.")
            self.iface.messageBar().pushMessage(
                self.tr("Environmental Assessment Studio"),
                message,
                level=Qgis.Warning,
                duration=8,
            )
            self._show_warning(message)
            return

        if not task_result:
            return

        request = task_result["request"]
        result = task_result["result"]
        loaded_layers = self._load_outputs(request, result)
        message = self._success_message(result, loaded_layers)
        self.iface.messageBar().pushMessage(
            self.tr("Environmental Assessment Studio"),
            message,
            level=Qgis.Success,
            duration=8,
        )
        QMessageBox.information(self, self.tr("Environmental Assessment Studio"), message)

    def _advance_progress_pulse(self):
        if self.current_task is None:
            self._progress_pulse_timer.stop()
            return
        self._progress_pulse_index = (self._progress_pulse_index + 1) % 3
        pulse = "." * (self._progress_pulse_index + 1)
        self.progress_bar.setFormat(
            self.tr("{0}{1} ({2}%)").format(
                self._progress_stage_message or self.tr("Working"),
                pulse,
                self._displayed_progress,
            )
        )

    def update_dependency_status(self):
        available = self.dependency_manager.earth_engine_available()
        python_path = self.dependency_manager.qgis_python_path()
        dependency_path = str(self.dependency_manager.plugin_dependency_path())

        if available:
            self.dependency_status.setText(
                self.tr(
                    "Earth Engine status: Installed and available.\n"
                    "QGIS Python: {0}\n"
                    "Persistent dependency folder: {1}\n"
                    "Earth Engine project: {2}"
                ).format(
                    python_path,
                    dependency_path,
                    self.dependency_manager.project_id() or self.tr("Not set"),
                )
            )
            self.dependency_status.setStyleSheet("color:#166534; font-weight:600;")
            self.run_button.setEnabled(True)
        else:
            import_error = self.dependency_manager.earth_engine_import_error()
            import_error_text = (
                self.tr("\nDetected issue: {0}").format(import_error)
                if import_error
                else ""
            )
            self.dependency_status.setText(
                self.tr(
                    "Earth Engine status: Not installed in the persistent dependency folder yet.\n"
                    "QGIS Python: {0}\n"
                    "Persistent dependency folder: {1}\n"
                    "Earth Engine project: {2}\n"
                    "Use 'Install Or Upgrade Earth Engine' below to download it from the official Python package source.{3}"
                ).format(
                    python_path,
                    dependency_path,
                    self.dependency_manager.project_id() or self.tr("Not set"),
                    import_error_text,
                )
            )
            self.dependency_status.setStyleSheet("color:#9a3412; font-weight:600;")
            self.run_button.setEnabled(False)

    def install_earth_engine_dependency(self):
        if self.dependency_task is not None:
            self.iface.messageBar().pushMessage(
                self.tr("Environmental Assessment Studio"),
                self.tr("Earth Engine dependency installation is already running in the background."),
                level=Qgis.Info,
                duration=5,
            )
            return
        self._set_settings_busy(True)
        self.iface.messageBar().pushMessage(
            self.tr("Environmental Assessment Studio"),
            self.tr("Downloading and installing Earth Engine in the background. QGIS will remain usable."),
            level=Qgis.Info,
            duration=4,
        )
        task = QgsTask.fromFunction(
            self.tr("Install Earth Engine dependencies"),
            self._install_earth_engine_dependency_task,
            on_finished=self._on_dependency_install_finished,
        )
        self.dependency_task = task
        QgsApplication.taskManager().addTask(task)

    def _install_earth_engine_dependency_task(self, task):  # noqa: ARG002
        return self.dependency_manager.install_earth_engine()

    def _on_dependency_install_finished(self, exception, task_result=None):
        self.dependency_task = None
        self._set_settings_busy(False)
        try:
            self.update_dependency_status()
        except Exception:
            pass
        if exception is not None:
            self._show_warning(self.tr("Dependency installation failed: {0}").format(str(exception)))
            return
        if not task_result:
            self._show_warning(self.tr("Dependency installation failed: no result was returned by the background task."))
            return

        success, stdout_text, stderr_text = task_result
        if success:
            QMessageBox.information(
                self,
                self.tr("Environmental Assessment Studio"),
                self.tr(
                    "Earth Engine was downloaded and installed successfully into the persistent QGIS profile dependency folder.\n\n"
                    "Next: click 'Authenticate Earth Engine' and 'Initialize Earth Engine' if needed. "
                    "A restart is only recommended after an upgrade if QGIS still reports an old or incompatible dependency."
                ),
            )
            return

        details = stderr_text or stdout_text or self.tr("No additional output was returned by pip.")
        self._show_warning(self.tr("Earth Engine installation failed.\n\n{0}").format(details))

    def authenticate_earth_engine(self):
        if self.dependency_task is not None:
            self.iface.messageBar().pushMessage(
                self.tr("Environmental Assessment Studio"),
                self.tr("Another Earth Engine setup task is already running."),
                level=Qgis.Info,
                duration=5,
            )
            return
        self._set_settings_busy(True)
        self.iface.messageBar().pushMessage(
            self.tr("Environmental Assessment Studio"),
            self.tr("Earth Engine authentication is running in the background."),
            level=Qgis.Info,
            duration=4,
        )
        task = QgsTask.fromFunction(
            self.tr("Authenticate Earth Engine"),
            self._authenticate_earth_engine_task,
            on_finished=self._on_authenticate_earth_engine_finished,
        )
        self.dependency_task = task
        QgsApplication.taskManager().addTask(task)

    def _authenticate_earth_engine_task(self, task):  # noqa: ARG002
        self.dependency_manager.authenticate_earth_engine()
        return True

    def _on_authenticate_earth_engine_finished(self, exception, task_result=None):  # noqa: ARG002
        self.dependency_task = None
        self._set_settings_busy(False)
        self.update_dependency_status()
        if exception is not None:
            self._show_warning(
                self.tr(
                    "Earth Engine authentication failed: {0}\n\n"
                    "Make sure your Google account has access to Earth Engine and that your Google Cloud project "
                    "is registered and enabled for Earth Engine."
                ).format(str(exception))
            )
            return
        QMessageBox.information(
            self,
            self.tr("Environmental Assessment Studio"),
            self.tr("Earth Engine authentication completed successfully."),
        )

    def initialize_earth_engine(self):
        if self.dependency_task is not None:
            self.iface.messageBar().pushMessage(
                self.tr("Environmental Assessment Studio"),
                self.tr("Another Earth Engine setup task is already running."),
                level=Qgis.Info,
                duration=5,
            )
            return
        self._set_settings_busy(True)
        self.iface.messageBar().pushMessage(
            self.tr("Environmental Assessment Studio"),
            self.tr("Earth Engine initialization is running in the background."),
            level=Qgis.Info,
            duration=4,
        )
        task = QgsTask.fromFunction(
            self.tr("Initialize Earth Engine"),
            self._initialize_earth_engine_task,
            on_finished=self._on_initialize_earth_engine_finished,
        )
        self.dependency_task = task
        QgsApplication.taskManager().addTask(task)

    def _initialize_earth_engine_task(self, task):  # noqa: ARG002
        self.dependency_manager.initialize_earth_engine()
        return True

    def _on_initialize_earth_engine_finished(self, exception, task_result=None):  # noqa: ARG002
        self.dependency_task = None
        self._set_settings_busy(False)
        self.update_dependency_status()
        if exception is not None:
            self._show_warning(self.tr("Earth Engine initialization failed: {0}").format(str(exception)))
            return
        QMessageBox.information(
            self,
            self.tr("Environmental Assessment Studio"),
            self.tr("Earth Engine initialized successfully for this QGIS session."),
        )

    def save_project_id(self):
        try:
            normalized_project_id = self.dependency_manager.set_project_id(self.project_id_edit.text())
        except ValueError as exc:
            self._show_warning(self.tr("Invalid Earth Engine project ID: {0}").format(str(exc)))
            return
        self.project_id_edit.setText(normalized_project_id)
        self.update_dependency_status()
        QMessageBox.information(
            self,
            self.tr("Environmental Assessment Studio"),
            self.tr("Earth Engine project ID saved for this QGIS profile: {0}").format(normalized_project_id),
        )

    def _set_settings_busy(self, is_busy):
        self.refresh_status_button.setEnabled(not is_busy)
        self.install_dependency_button.setEnabled(not is_busy)
        self.authenticate_button.setEnabled(not is_busy)
        self.initialize_button.setEnabled(not is_busy)
        self.save_project_button.setEnabled(not is_busy)

    def cancel_current_task(self):
        if self.current_task is not None:
            self.current_task.cancel()
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat(self.tr("Cancelling..."))
            self.iface.messageBar().pushMessage(
                self.tr("Environmental Assessment Studio"),
                self.tr("Cancellation requested. The task will stop at the next safe point."),
                level=Qgis.Warning,
                duration=5,
            )

    def closeEvent(self, event):
        if self.current_task is not None:
            self.cancel_current_task()
            event.ignore()
            return
        super().closeEvent(event)

    def _load_outputs(self, request, result):
        loaded_layers = []
        raster_outputs = result.get("raster_outputs", [])
        if not raster_outputs and result.get("raster_path"):
            raster_outputs = [
                {
                    "path": result.get("raster_path"),
                    "label": self.analysis_combo.currentText(),
                    "analysis_id": request.analysis_id,
                    "mode": request.mode,
                }
            ]

        vector_paths = []
        for raster_output in raster_outputs:
            loaded_layers.append(
                self.service.add_raster_to_project(
                    raster_output["path"],
                    raster_output.get("label", self.analysis_combo.currentText()),
                    raster_output.get("analysis_id", request.analysis_id),
                    raster_output.get("mode", request.mode),
                    custom_classes=raster_output.get("custom_classes"),
                    custom_range_classes=raster_output.get("custom_range_classes"),
                    skip_style=raster_output.get("skip_style", False),
                    value_scale=raster_output.get("value_scale", 1.0),
                )
            )
            if self.convert_to_vector_checkbox.isChecked() and raster_output.get("allow_vector", True):
                vector_result = self.service.convert_raster_to_vector(
                    raster_output["path"],
                    result.get("output_dir", request.output_dir),
                    request.output_name or raster_output.get("label", request.analysis_id),
                    raster_output.get("analysis_id", request.analysis_id),
                    raster_output.get("mode", request.mode),
                    custom_classes=raster_output.get("custom_classes"),
                    vector_context=raster_output.get("vector_context"),
                )
                loaded_layers.append(vector_result["layer"])
                vector_paths.append(vector_result["vector_path"])

        if vector_paths:
            result["vector_paths"] = vector_paths

        return loaded_layers

    def _success_message(self, result, loaded_layers):
        lines = []
        if result["mode"] == "snapshot":
            summary = result.get("summary", {})
            lines.append(
                self.tr("Snapshot completed. Loaded {0} raster layer(s) into QGIS.").format(len(loaded_layers))
            )
            if result.get("output_date_label"):
                lines.append(self.tr("Source period: {0}").format(result.get("output_date_label")))
            if summary:
                lines.append(f"{summary.get('label')}: {summary.get('value')}")
            if result.get("detail_lines"):
                lines.extend(result.get("detail_lines"))
            if result.get("summary_table_xlsx_path"):
                lines.append(self.tr("Summary table (XLSX): {0}").format(result.get("summary_table_xlsx_path")))
            if result.get("summary_table_csv_path"):
                lines.append(self.tr("Summary table (CSV): {0}").format(result.get("summary_table_csv_path")))
            for raw_stack_path in result.get("raw_stack_paths", []):
                lines.append(self.tr("Processed stack: {0}").format(raw_stack_path))
            for vector_path in result.get("vector_paths", []):
                lines.append(self.tr("Vector output: {0}").format(vector_path))
        else:
            lines.append(
                self.tr("Trend analysis completed. Loaded {0} raster layer(s) into QGIS.").format(len(loaded_layers))
            )
            if result.get("output_date_label"):
                lines.append(self.tr("Source period: {0}").format(result.get("output_date_label")))
            if result.get("trend_table_xlsx_path"):
                lines.append(self.tr("Trend table (XLSX): {0}").format(result.get("trend_table_xlsx_path")))
            if result.get("trend_table_csv_path"):
                lines.append(self.tr("Trend table (CSV): {0}").format(result.get("trend_table_csv_path")))
            if not result.get("trend_table_xlsx_path") and not result.get("trend_table_csv_path"):
                lines.append(self.tr("Trend report tables were skipped by user choice."))
            if result.get("graph_path"):
                lines.append(self.tr("Trend graph: {0}").format(result.get("graph_path")))
            if result.get("summary_table_xlsx_path"):
                lines.append(self.tr("Summary table (XLSX): {0}").format(result.get("summary_table_xlsx_path")))
            if result.get("summary_table_csv_path"):
                lines.append(self.tr("Summary table (CSV): {0}").format(result.get("summary_table_csv_path")))
            for raw_stack_path in result.get("raw_stack_paths", []):
                lines.append(self.tr("Processed stack: {0}").format(raw_stack_path))
            for vector_path in result.get("vector_paths", []):
                lines.append(self.tr("Vector output: {0}").format(vector_path))

        return "\n".join(lines)

    @staticmethod
    def _qdate_to_date(value):
        return date(value.year(), value.month(), value.day())

    def _show_warning(self, message):
        QMessageBox.warning(self, self.tr("Environmental Assessment Studio"), message)

    def _validate_processed_stack_request(self, aoi_layer):
        if not self.export_landsat_stack_checkbox.isChecked():
            return True
        if self.mode_combo.currentData() != "trend":
            return True

        analysis_id = self.analysis_combo.currentData()
        if analysis_id not in {"lulc", "lulc_landsat"}:
            return True

        area_sq_km = self._aoi_area_sq_km(aoi_layer)
        if area_sq_km is None:
            return True

        if analysis_id == "lulc":
            max_sq_km = self.SENTINEL_TREND_STACK_MAX_SQ_KM
            dataset_name = self.tr("Sentinel-2")
        else:
            max_sq_km = self.LANDSAT_TREND_STACK_MAX_SQ_KM
            dataset_name = self.tr("Landsat")

        if area_sq_km <= max_sq_km:
            return True

        self._show_warning(
            self.tr(
                "The selected AOI is about {0:,.0f} sq km, which is too large for a combined {1} trend analysis "
                "with processed satellite band stacks enabled.\n\n"
                "Please run the trend assessment without processed band stacks, then export the processed band stacks "
                "as single-period outputs for the specific years you want to use for custom sample training/classification."
            ).format(area_sq_km, dataset_name)
        )
        return False

    def _aoi_area_sq_km(self, layer):
        try:
            distance = QgsDistanceArea()
            distance.setSourceCrs(layer.crs(), QgsProject.instance().transformContext())
            distance.setEllipsoid(QgsProject.instance().ellipsoid() or "WGS84")
            area_sq_m = 0.0
            for feature in layer.getFeatures():
                geometry = feature.geometry()
                if geometry and not geometry.isEmpty():
                    area_sq_m += distance.measureArea(geometry)
            return area_sq_m / 1_000_000.0
        except Exception:
            return None
