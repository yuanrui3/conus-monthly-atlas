# Overview rivers and lakes

`docs/data/hydro_overview.geojson` adds real public river lines and lake/reservoir polygons to the national overview. It is a **3.99 MB** GeoJSON FeatureCollection in WGS84 longitude/latitude (EPSG:4326), clipped to `[-125, 24, -66, 50]`.

The extent includes nearby parts of Canada and Mexico for geographic context and retains all five Great Lakes. It is separate from the more detailed local-water layer and from the November climate/streamflow measurements.

## Contents and browser contract

| Source class | Features |
|---|---:|
| River | 1,500 |
| River (Intermittent) | 83 |
| Lake | 418 |
| Reservoir | 108 |
| Alkaline Lake | 7 |
| **Total** | **2,116** |

These are source feature/part counts, not counts of distinct named rivers. River parts can share a source identifier or name. Every top-level `feature.id` is unique because it includes the source layer, source ID and source record index.

Each feature has these properties:

```js
{
  kind: "river" | "lake",
  name: "Lake Superior", // or null if absent upstream
  featureClass: "Lake", // original class; intermittent rivers are explicit
  sourceLayer: "ne_10m_lakes",
  sourceId: "...",
  scaleRank: 0, // source cartographic importance rank, not a measurement
  labelPoint: [longitude, latitude]
}
```

River geometry is `LineString` or `MultiLineString`. Lake geometry is `Polygon` or `MultiPolygon`, with interior rings retained. Draw lake fills and outlines before river lines; use the existing map projection. Polygon holes need correct ring handling (for example, Canvas's `evenodd` fill rule). `labelPoint` is an optional derived display anchor, not a surveyed center. Labels should be filtered by importance and repeated names deduplicated to avoid clutter. The Great Lakes and Mississippi, Missouri, Ohio, Columbia and Colorado are present by name.

Use different styling for the explicit `River (Intermittent)` class if desired. A river's drawn stroke is a map symbol, **not its actual width**. The intermittent class does not state whether water is present in November.

## Source and temporal meaning

The extract combines four **Natural Earth version 5.0.0** layers:

- `ne_10m_rivers_lake_centerlines`
- `ne_10m_rivers_north_america`
- `ne_10m_lakes`
- `ne_10m_lakes_north_america`

These are public-domain, **1:10,000,000-scale** cartographic datasets. The North America supplements derive from the North American Environmental Atlas / Commission for Environmental Cooperation. Natural Earth documents manual adjustment, smoothing and generalization. Source observation dates are mixed or unspecified. All four downloaded ZIPs have server modification dates of **December 8, 2021**; those dates describe the files, not observations of water extent.

Primary documentation:

- Rivers and North America supplement: https://www.naturalearthdata.com/downloads/10m-physical-vectors/10m-rivers-lake-centerlines/
- Lakes and North America supplement: https://www.naturalearthdata.com/downloads/10m-physical-vectors/10m-lakes/
- Public-domain terms: https://www.naturalearthdata.com/about/terms-of-use/

The actual ZIP URLs, hashes, file dates, source projection WKT, feature counts and processing are recorded in `docs/data/hydro_overview_metadata.json`. “Made with Natural Earth” is the source's suggested short credit.

## Processing and validation

The builder reads source shapefiles, clips real geometry to the map extent, and retains original names, classes and map ranks. It omits 293 lake-centerline connectors and seven canal records from the river layer. Nineteen null geometries in the entire North America river source cannot be located and are skipped. No historic or pluvial-lake dataset is included.

No additional line simplification is applied. Coordinates are normally rounded to six decimal places; two river features retain original precision because rounding would collapse very short source parts. Six decimal places does not imply equivalent positional accuracy. All 2,116 output geometries and their display anchors were checked after reloading the written GeoJSON. All geometries are valid, finite and within the extent; all four ZIP checksums and archive CRCs and the final output hash were verified.

The dataset is a geographically generalized and incomplete map reference. It does not establish current shorelines, channel widths or depths, flow, flooding, ice, November wetness, potable-water availability, water blockages, crossing conditions, or vehicle suitability. Absence from the layer is not evidence that water is absent. No bridge joins, route network or mobility scoring is created.

## Reproduce

From the repository root, install the dependencies in an isolated environment and choose an external raw-data cache:

```sh
python3 -m pip install -r scripts/hydro_overview_requirements.txt
python3 scripts/hydro_overview_build.py --cache-dir /tmp/conus-hydro-overview-cache
```

The script verifies pinned source ZIP hashes. A changed upstream archive requires review before regenerating the published layer. Output is limited to the `hydro_overview` data files; raw sources remain in the cache.
