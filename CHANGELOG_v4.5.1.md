# Changelog

## v4.5.1

Release focus: stability, QGIS repository readiness, large-AOI reliability, clearer outputs, and final assessment quality fixes after full assessment testing.

### Added

- Added Air Quality / PM2.5 assessment using satellite-derived ground-level PM2.5 concentration estimates.
- Added Urban Heat Island assessment guidance clarifying that the operational output is LST-based, with atmospheric temperature retained as interpretation context where relevant.
- Added processed Sentinel and Landsat satellite band-stack export option for custom sample training and classification workflows.
- Added clearer tutorial links in the Earth Engine setup area for plugin setup and running assessments.
- Added metadata sidecar outputs that document source periods, source image counts, methodology notes, and output field descriptions.
- Added per-assessment subfolders so raster, vector, raw stack, table, graph, and metadata outputs are easier to trace.

### Changed

- Renamed and clarified selected assessments and descriptions, including Soil Organic Carbon, Landsat 8 LULC, Terrain Susceptibility to Erosion and Instability, and Urban Heat Island.
- Restored Solar Radiation behavior to the detailed MODIS MCD18C2 PAR workflow used in v4.5.0 while preserving the newer large-AOI download safeguards.
- Updated Solar Radiation to export as classified/dynamic radiation classes instead of a uniform continuous ERA5-only surface.
- Updated Carbon Emission so areas with no detected biomass-loss emissions are written as zero-value pixels rather than fully masked NoData.
- Improved Land Surface Temperature styling so displayed ramps are based on actual raster values rather than broad fixed placeholder ranges.
- Improved NDVI and NDWI handling for water, bare ground, built-up surfaces, and wetness interpretation.
- Reduced Landsat LULC to a stable 5-class scheme and documented that Landsat LULC is a comparative interpretation layer.
- Improved Landsat and Sentinel trend-report behavior so reports are skipped when report generation is disabled, reducing long waits on larger AOIs.
- Shortened output folder names to use readable assessment and AOI names.
- Updated plugin metadata tags to include `EAS` for easier QGIS plugin search discovery.
- Removed the experimental flag for repository publication.

### Fixed

- Fixed large-AOI raster request failures by improving tiled download and mosaicing behavior.
- Fixed misleading progress behavior by making progress more cumulative and clearer during compute, download, and post-processing stages.
- Fixed output clutter where vector and raw-stack outputs were saved outside assessment subfolders.
- Fixed Earth Engine dependency persistence issues after plugin reinstall/update by using a persistent QGIS profile dependency folder.
- Fixed QGIS UI theme contrast issues in plugin settings for light and dark themes.
- Fixed QGIS 3 / QGIS 4 package structure, ZIP path separators, missing license, and blocked `.pyc` files for repository compliance.
- Fixed URL download security checks by validating Earth Engine download URL schemes and hosts before `urlopen`.
- Fixed several Python style and scanner issues reported by repository/security checks.
- Fixed Change Detection outputs and legends, including binary and transition map behavior.
- Fixed Land Degradation trend reporting so summary categories are clearer and less misleading.
- Fixed Carbon Emission empty-canvas output when no biomass-loss pixels existed in the AOI/date range.
- Fixed Solar Radiation blank/uniform outputs by restoring the v4.5.0 MODIS PAR logic and dynamic classified display.

### Notes

- Landsat LULC remains useful as a comparative 30 m interpretation layer, but class-area changes may reflect differences in class separation as well as real land-cover change.
- Large AOI workflows are more reliable, but Earth Engine memory, network timeouts, and local file locks can still affect very large requests or files currently loaded in QGIS/OneDrive.
- If an existing raster is locked by QGIS or Windows, remove the old layer or choose a fresh output name/folder before rerunning the same assessment.
