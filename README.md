# Environmental Assessment Studio for QGIS 4

Environmental Assessment Studio is a QGIS 4 plugin scaffold for running environmental assessments from Google Earth Engine and bringing the outputs back into QGIS.

## Included assessments

- Land Use Land Cover
- Change Detection
- Land Surface Temperature
- Flood Analysis
- NDVI
- Land Degradation
- Drought Assessment
- Soil Assessment
- Wind Direction Assessment
- Carbon Emission (Biomass)
- Anthropogenic Emission
- Carbon Sequestration
- Solar Radiation Assessment
- NDWI
- Rainfall / Precipitation Anomaly
- Soil Moisture
- Erosion Risk
- Slope / Terrain Susceptibility
- Wildfire Risk / Burn Severity
- Air Quality / NO2
- Habitat Fragmentation / Biodiversity Pressure
- Groundwater Recharge / Runoff Potential

## Current workflow

1. Open the plugin from the QGIS toolbar or Plugins menu.
2. In the `Settings And Dependencies` section, click `Install Or Upgrade Earth Engine` if the dependency is missing.
3. Enter and save the Google Cloud project ID that is registered for Earth Engine.
4. Click `Authenticate Earth Engine` and then `Initialize Earth Engine`.
5. Select a polygon AOI layer from the current project or browse to a vector file.
6. Choose the assessment type.
7. Select either a single period output or a trend analysis.
8. Set the start and end dates.
9. Choose an output folder.
10. Run the assessment.

## Outputs

- Snapshot mode exports one GeoTIFF and adds it to the current QGIS project.
- Every raster export also produces class-area summary tables in `.csv` and `.xlsx`, including the size of each class in square meters and hectares.
- When `Convert To Vector` is enabled, the plugin polygonizes the raster output and adds attribute fields such as class label, class/value range, and polygon area.
- Trend mode exports:
  - An annual trend table in both `.csv` and `.xlsx`.
  - An `.svg` graph that does not depend on optional plotting libraries.
  - A raster trend surface where the analysis supports one.
  - Annual supporting analytics such as class coverage, percentages, and year-specific summary statistics when applicable.
- Raster outputs are automatically styled in QGIS with standardized colors and labeled classes or ramps so the layer legend is readable immediately after loading.

## Earth Engine requirements

This plugin expects the QGIS Python environment to include the Google Earth Engine API:

```python
import ee
```

The plugin includes an in-app settings section that can download `earthengine-api` from the official Python package source and install it into a persistent QGIS profile dependency folder. This folder is outside the plugin install directory, so Earth Engine can remain available after the plugin is uninstalled and reinstalled.

Earth Engine now requires a Google Cloud project for API routing. In the plugin settings, save the project ID for a Cloud project that:

- has the Earth Engine API enabled,
- is registered for commercial or noncommercial Earth Engine use,
- and grants your Google account the needed access.

## Notes on methods

- Land Use Land Cover uses `GOOGLE/DYNAMICWORLD/V1`.
- Change Detection compares dominant Dynamic World classes between the first and last year in the selected period.
- Land Surface Temperature uses Landsat Collection 2 Level 2 thermal products.
- Flood Analysis uses a Sentinel-1 VV threshold as a rapid water extent proxy.
- NDVI uses Landsat Collection 2 Level 2 surface reflectance.
- Land Degradation uses NDVI decline relative to the starting year as a simple screening indicator.
- Drought Assessment uses the SPEI 12-month product from `CSIC/SPEI/2_10`.
- Soil Assessment uses soil organic carbon from `OpenLandMap/SOL/SOL_ORGANIC-CARBON_USDA-6A1C_M/v02`.
- Wind Direction Assessment uses 10 m wind components from `ECMWF/ERA5_LAND/HOURLY`.
- Carbon Emission (Biomass) uses a biomass-loss carbon proxy based on `NASA/ORNL/biomass_carbon_density/v1` and `UMD/hansen/global_forest_change_2024_v1_12`.
- Anthropogenic Emission uses annual VIIRS nighttime lights from `NOAA/VIIRS/DNB/ANNUAL_V22` as a settlement and combustion proxy.
- Carbon Sequestration uses annual Net Primary Productivity from `MODIS/061/MOD17A3HGF` as a sequestration proxy.
- Solar Radiation Assessment uses MODIS MCD18C2 PAR.
- NDWI uses Landsat surface reflectance.
- Rainfall / Precipitation Anomaly uses `UCSB-CHG/CHIRPS/DAILY`.
- Soil Moisture uses `NASA/SMAP/SPL4SMGP/008`.
- Erosion Risk uses a terrain, vegetation cover, and rainfall proxy derived from SRTM, Landsat NDVI, and CHIRPS.
- Slope / Terrain Susceptibility uses `USGS/SRTMGL1_003`.
- Wildfire Risk / Burn Severity uses `MODIS/061/MCD64A1`.
- Air Quality / NO2 uses `COPERNICUS/S5P/OFFL/L3_NO2`.
- Habitat Fragmentation / Biodiversity Pressure uses `UMD/hansen/global_forest_change_2024_v1_12`.
- Groundwater Recharge / Runoff Potential uses `WWF/HydroSHEDS/15ACC`, `USGS/SRTMGL1_003`, and `UCSB-CHG/CHIRPS/DAILY`.

## Data availability messaging

If the selected date range has no data for the chosen AOI, the plugin now reports that clearly and also returns the available AOI date span that Earth Engine does have for the relevant dataset. This helps users adjust the requested years without trial-and-error.

## Earth Engine onboarding

The plugin now includes a dedicated `Earth Engine Setup` tab with direct links to:

- Earth Engine access guidance
- Earth Engine project registration
- Google Cloud project creation

This helps new users sign in, create a Cloud project, register it for Earth Engine, and paste the resulting project ID back into the plugin.

These implementations are a solid working foundation, but they are still a starting point. For production-grade environmental reporting, you will likely want to refine thresholds, legends, class summaries, metadata capture, and validation rules for your study area.
