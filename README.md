# Environmental Assessment Studio for QGIS 4

Environmental Assessment Studio is a QGIS 4 plugin for running Google Earth Engine based environmental assessments over a user-defined area of interest and time period, then loading the outputs back into QGIS as styled raster and optional vector layers.

## Main capabilities

- User-defined AOI selection from the current QGIS project or a browsed polygon file
- Single-period analysis and interval-based trend analysis
- Styled raster outputs loaded directly into QGIS
- Optional raster-to-vector conversion with enriched attribute fields
- CSV, XLSX, SVG, and metadata sidecar outputs
- In-plugin Earth Engine setup guidance and dependency management

## Included assessments

- Land Use Land Cover
- Change Detection
- Land Surface Temperature
- Flood Analysis
- NDVI
- NDWI
- Land Degradation
- Drought Assessment
- Soil Organic Carbon
- Wind Direction Assessment
- Carbon Emission (Biomass)
- Anthropogenic Emission
- Carbon Sequestration
- Solar Radiation Assessment
- Rainfall / Precipitation Anomaly
- Soil Moisture
- Erosion Risk
- Terrain Susceptibility to Erosion / Instability
- Wildfire Risk / Burn Severity
- Air Quality / NO2
- Habitat Fragmentation / Biodiversity Pressure
- Groundwater Recharge / Runoff Potential

## Typical workflow

1. Open the plugin from the QGIS toolbar or Plugins menu.
2. Install and initialize Google Earth Engine if needed.
3. Select a polygon AOI layer.
4. Choose the assessment type.
5. Select either a single-period output or a trend analysis.
6. Set the start and end dates.
7. Choose an output folder.
8. Run the assessment.

## Outputs

- Styled raster outputs in GeoTIFF format
- Optional vector polygon outputs in GeoPackage format
- CSV and XLSX summary tables
- SVG trend charts for supported trend analyses
- Metadata sidecar files describing source period, source-image use, and attribute fields

## Earth Engine notes

This plugin uses the Earth Engine Python API inside the QGIS Python environment. A valid Google account, Earth Engine access, and a Google Cloud project registered for Earth Engine are required.

## Repository

- Homepage: https://github.com/adolsum/Environmental-Assessment-Studio
- Issue tracker: https://github.com/adolsum/Environmental-Assessment-Studio/issues

## Upload note

This repository is intended to mirror the QGIS plugin ZIP contents, excluding compiled files and cache folders.
