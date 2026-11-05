# CONUS Monthly Atlas

Explore a typical January through December in the contiguous 48 U.S. states and Washington, DC. Each calendar month is summarized separately over **2006–2025**. The map combines monthly outdoor climate and historical streamgage records, independent seasonal snow/ice overlays and dated landscape snapshots. It also includes a regional guide to published recreational 4×4 trail grades at Badin Lake in North Carolina.

Select a month above the map. Click a location to inspect its gridded climate, select a gauge under **River flow** to inspect its monthly discharge record, or open **4×4 trails** to see a published trail grade alongside the selected month's climate at one mapped trail point. Switching months does not change a 2025 land-cover class or a published trail grade. These historical summaries do not forecast a particular day.

## Run or publish

To view the atlas locally, run `python -m http.server 8000 --directory docs` from the repository root and open <http://localhost:8000/>. To publish the same files on GitHub Pages under your own account, follow [Publishing the atlas](PUBLISHING.md). There is no build step.

## v0.8: snow, surface ice, slope and river flow

In **Overview**, the **Snow on land** and **Great Lakes ice** checkboxes control independent overlays. Their legends and point readouts follow the calendar-month selector. The underlying 2025 land-cover class is still available; NLCD class 12 (“Perennial Ice/Snow”) stays visible on the land-cover base. A seasonal overlay is not a change of land type. Zero, insufficient coverage and source failure are distinguished.

Select **Slope** in the base-map controls for regional mean slope in degrees. **River flow** opens the existing USGS gauge view, whose monthly measurements, full/partial flags and interpretation are unchanged.

## What changes with the month?

| Layer | Source and support | Meaning |
|---|---|---|
| Mean outdoor temperature; mean daily high and low | [NOAA nClimGrid-Monthly](https://www.drought.gov/data-maps-tools/gridded-climate-datasets-noaas-nclimgrid-monthly) · nominal 5 km native, about 9 km overview | Each displayed estimate uses 20 instances of the selected calendar month. Highs and lows are means of daily extrema, not records. |
| Average monthly precipitation | Same NOAA grid and years | Average of the 20 monthly **totals**, in mm or inches. Precipitation does not directly measure soil moisture, snowfall depth, inundation or available drinking water. |
| Snow-cover frequency on land | [USNIC IMS, distributed by NSIDC](https://nsidc.org/data/g02156/versions/1) · nominal 24 km source; 0.25° nearest-cell overview | For each month-year, fraction of observed land days classified as snow-covered. Display requires valid observations on at least 80% of that month’s days in every one of 20 years; the 20 resulting percentages are averaged equally. Water and missing flags are not snow-free land. |
| Great Lakes surface ice concentration | [NOAA GLERL](https://www.glerl.noaa.gov/data/ice/) · 1,800 m Mercator grid spacing; nearest source cell in a 0.05° overview, masked by lake | For each month-year, mean chart concentration (0–100%); at least 80% of calendar days must have qualifying observations and at least 10 years must qualify. Cell readouts retain year counts. Covers the five Great Lakes and Lake Saint Clair. |
| Historical discharge | [USGS Statistics Service](https://waterservices.usgs.gov/docs/statistics/statistics-details/) and [Daily Values Service](https://waterservices.usgs.gov/docs/dv-service/) · gauge points | Approved monthly mean streamflow, with missing years and complete/partial baselines identified at each gauge. There is no interpolation across rivers or lakes. |
| Badin Lake seasonal access note | [Forest Service winter closure order](https://www.fs.usda.gov/media/237560) | The recurring closure covers December 15 through March 31: all of January–March and part of December. A month outside that interval does not confirm the trail is currently open. This calendar rule is separate from the trail's grade. |

The snow archive supplies 7,289 daily analyses of 7,305 possible baseline dates. A displayed snow cell has all 20 qualifying month-years; the selected-point readout also reports the actual observation-day count. All 12 snow grids contain 13,013 valid overview cells. These counts describe the coarse grid, not independent fine-resolution observations.

### Climate calculation and verification

The climate build uses **240 individually dated NOAA files**: 12 months × 20 years, each containing the four variables. For each calendar month, only native cells with 20 valid values enter the mean. A 2×2 spatial aggregation weights contributing cells by spherical area and leaves missing cells unfilled. Precipitation and mean temperature also retain the sample standard deviation of the 20 annual monthly estimates. That spread describes interannual variability; it is not a prediction error. The baseline is a custom 20-year climatology, not an official 30-year climate normal.

All 12 months have **118,839** overview cells with complete records. The all-month [climate manifest](docs/data/climate_months/manifest.json) records acquisition dates, source and output hashes, aggregate coverage and validation. For the 11 added months, checks included 2,816 comparisons of 2025 raster values with the separately distributed NOAA point-format values and 55 independently sampled 20-year raster windows, including partial coastal blocks. Expected means and available standard deviations had to agree with the published rounding. November retains its [existing data](docs/data/climate.json) and [original validation report](docs/data/validation.json).

The browser loads one month at a time. The 11 additional climate files total approximately 14.1 MB compressed; November retains the original plain JSON. For an example of the seasonal contrast at one point, the West Lafayette, Indiana sample near 40.42°N, 86.90°W has a January mean of −3.08 °C and 58.27 mm precipitation, compared with 23.29 °C and 110.90 mm in July. These are overview-grid estimates.

### Streamflow and completeness

USGS discharge (parameter 00060) is processed for each station, series, and calendar month. The build uses reported monthly means for the archived November 2006–November 2025 interval. At the ends of the 20-year study period it can form a missing boundary month's mean from approved daily means, requiring every calendar day for the same station and series. The relevant boundary months are January–October 2006 and December 2025.

A station's record has 20 explicit yearly positions. Means use available years with equal weights. Fewer than 20 years is marked partial; conflicting series are omitted for the calendar month. Source zeroes and negative flows can be valid, while missing values remain null. Discharge is a volume per time, not a local measurement of water depth, ice thickness or quality. Consult the water manifest and validation report listed below for the selected month's station counts, series checks, source coverage and comparison with the November release. Do not sum month-specific counts to calculate the number of distinct gauges.

## Landscape snapshots and the regional trail guide

| Source layer | Vintage / scale | How to interpret it |
|---|---|---|
| [USGS Annual NLCD](https://www.mrlc.gov/data-services-page) | 2025 land cover; about 4–7 km overview spacing, separate local imagery from 30 m source cells | Forest, crops, grassland, woody wetlands, herbaceous wetlands and water remain distinct. Zooming does not improve the source resolution. Developed classes are not building footprints or a road network. |
| [NOAA ETOPO1 relief](https://coastwatch.pfeg.noaa.gov/erddap/info/etopo180/index.html) | 2009 model; systematic 0.1° samples (~11 km north–south) | Broad context only. Local slope and surface roughness are unresolved. Some coastal or lake-edge samples represent bathymetry. |
| [USGS 3DEP regional slope](https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer) | Varying source vintages; 500 m elevation samples, 0.05° slope overview | Horn 3×3 slope from projected metre elevation/spacing, averaged over valid slope samples. Values are degrees above horizontal, not percent grade. The roughly 1.5 km operator footprint and roughly 5.6 km north–south display cells do not resolve a particular trail grade. |
| National and local hydrography | Natural Earth v5.0.0 at 1:10 million cartographic scale; independently dated Overture water geometry in local detail | Displayed lines and outlines do not give seasonal water depth or channel width. Local water imagery/geometry services may be unavailable independently of packaged layers. |
| [FHWA bridge inventory](https://www.fhwa.dot.gov/bridge/nbi/nbi_data_2025.cfm) | 2025 snapshot | Individual records can be inspected in local detail. The national overview has no bridge-count circles. Records do not establish current availability or structure capacity. |
| [Badin Lake recreational grades](https://www.fs.usda.gov/media/241208) | U.S. Forest Service publication and separately matched GIS lines | Eleven named full-size recreational trail entries; nine matched lines. The other two entries retain published grades without a line because of a conflicting designation or missing match. |

The trail guide encodes the manager's labels as **1 Easy, 2 Moderate, 3 Difficult and 4 Extremely Difficult**. This is an ordered legend, not an interval scale or all-terrain vehicle model. The 2025 U.S. four-door Ford Bronco Badlands and 2023 Chinese-launch YANGWANG U8 Premium Edition are separate equipment profiles. Changing the vehicle or month does not recalibrate the source grade. A mapped sample's monthly climate represents one overview cell, not a per-trail average or a current access guarantee.

Historical ice charts support gridded estimates in December–April. May, June and November have some source charts but do not clear the coverage criteria. July–October have no source chart dates in this baseline. A hatched area has no supported estimate and is distinct from a recorded **0%**. Ice concentration describes the fraction of the water surface covered by ice, not its thickness at a point.

Seasonal snow **depth**, snow water equivalent, river/lake ice thickness, soil moisture and ground freeze state have not been ingested. The snow overlay measures the frequency of mapped snow cover. [SNODAS](https://nsidc.org/data/g02158/versions/1) remains a possible separate depth/SWE source; it is not the dataset displayed here. The cabin climate-control and occupant drinking-water scenarios remain assumptions, with no calculated cabin temperature or water-supply estimate.

## Files and reproduction

The buildless browser application is in `docs/`. For local use, serve that directory with a static HTTP server. Python is needed only to generate data. Raw inputs and download caches belong outside the repository. GitHub Pages serves the static files from the `main` branch and `/docs` folder.

| File in `docs/data/` | Contents |
|---|---|
| `climate_months/{MM}.json.gz`, `climate.json` | January–October and December gzip climate grids; original November JSON grid |
| `climate_months/manifest.json`, `climate_manifest.json`, `validation.json` | Twelve-month source/validation register and original November provenance |
| `water_months/{MM}.json.gz` | One monthly streamgage collection per calendar month; annual means stored in source ft³/s |
| `water_months_manifest.json`, `water_months_validation.json` | Source requests, coverage and verification per calendar month; original November reports are also retained |
| `landcover_detail_source.json`, `hydro_overview_metadata.json`, `bridge_metadata.json`, `badin_trails.json` | Provenance for local land cover, national hydrography, bridge points and trail ratings |
| `seasonal_snow.json.gz`, `seasonal_snow_sources.json.gz` | IMS monthly snow-cover frequencies, valid observation-day counts, coverage information and acquisition provenance |
| `seasonal_ice.json.gz`, `seasonal_ice_manifest.json`, `seasonal_ice_validation.json` | Gridded Great Lakes ice percentages, actual qualifying years, source coverage and comparison with separately supplied lake-wide summaries |
| `regional_slope.json.gz`, `regional_slope_metadata.json` | Regional mean slope in degrees, source sampling, calculations and validation |
| `project_spec.json`, `source_catalog.json` | Project scope, source vintages and evidence limits |

Run from the repository root, replacing cache paths with writable directories outside the checkout. Use the published November products bundled in the repository when rebuilding additional climate months. The water pipeline also needs the verified raw cache from the November build:

```text
python -m pip install -r scripts/climate_requirements.txt
python scripts/climate_all_months.py --cache ../atlas-cache/climate
python scripts/water_build.py --cache-dir ../atlas-cache/water-november
python scripts/water_months_build.py --legacy-cache ../atlas-cache/water-november --cache ../atlas-cache/water-monthly
```

To reproduce the new environmental layers, see the dependency and cache instructions in [the snow builder](scripts/build_seasonal_snow.py), [the lake-ice builder](scripts/build_seasonal_ice.py) and [the regional-slope builder](scripts/build_regional_slope.py). The snow builder uses `--cache PATH --fetch`; the other two take `--cache PATH`. Recent seasonal input files may be revised; retain the verified source records for the published baseline.

To regenerate and verify the original November climate foundation, run `python scripts/climate_build.py --cache ../atlas-cache/climate` and `python scripts/verify_atlas.py --cache ../atlas-cache/climate` first. Run any of these scripts with `--help` for supported options. Provider revisions can legitimately change rebuilt values and hashes; the shipped manifests identify the exact inputs used for this release.

See [bridge reproduction](scripts/bridge_README.md) and [national hydrography reproduction](scripts/hydro_overview_README.md) for the earlier November pipeline and technical notes.

The **River flow** tab opens at `#river-flow`. Its state/month coverage download, `docs/data/river_flow_coverage_by_state.csv`, is built by `python3 scripts/flow_state_coverage.py` from the twelve published station series and distinguishes full 20-year from partial records.
