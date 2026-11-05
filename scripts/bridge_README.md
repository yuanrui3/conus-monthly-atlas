# Public bridge-location layer

This extract contains **617,431 FHWA National Bridge Inventory (NBI) highway-bridge location records** for the contiguous 48 states and Washington, DC. It preserves reported facility, crossed-feature and location descriptions. It does not assess a bridge, identify an available crossing, infer that a bridge spans water, or supply a route.

## Source and snapshot

- Official 2025 download page: https://www.fhwa.dot.gov/bridge/nbi/ascii2025.cfm
- Downloaded highway-only ZIP: https://www.fhwa.dot.gov/bridge/nbi/2025hwybronefiledel.zip
- Record layout: https://www.fhwa.dot.gov/bridge/nbi/format.cfm
- Coordinate coding (items 16 and 17): https://www.fhwa.dot.gov/bridge/mtguide.pdf
- General NBI documentation and limitations: https://www.fhwa.dot.gov/bridge/nbi/nbi_data.cfm

The national ZIP is 53,277,475 bytes, with SHA-256 `bee3b363a1f51095d0f9fb731f01a83bc30fb35243e1176955057c016e5f656e`. It contains 624,193 source rows. The 2025 inventory snapshot is separate from the atlas's 2006–2025 November climate baseline. The upstream ZIP's Last-Modified header is June 16, 2025; `2025-06-15` identifies FHWA's annual inventory snapshot, not an inspection date or a claim of present availability.

The 53 MB comma-delimited archive was chosen instead of the equivalent 1.285 GB converted national GeoJSON. Its comma-separated text uses a **single quote** as the text qualifier. Only location and descriptive fields are retained in the web assets.

## Reproduce

From the repository root, using Python 3 and its standard library:

```sh
python3 scripts/bridge_build.py --cache-dir /tmp/conus-bridge-cache
```

Raw files stay in the external cache. The script checks the audited source hash and published state counts before publishing processed JSON. A changed upstream archive requires review rather than silently accepting a different snapshot.

## Browser data contract

`docs/data/bridge_points.json` is approximately 12.8 MB. It contains `pointCount`, `stateCounts`, a source object, and `pointsByState`. Each state has a flat array of alternating longitude and latitude numbers:

```json
{"pointsByState":{"DC":[-77.116972,38.929444,-77.062756,38.904311]}}
```

The pair beginning at array offset `2 * i` corresponds to detail row `i` in `docs/data/bridge_DC.json`. Every state detail file has the same fields:

```json
{
  "state":"DC",
  "stateFips":"11",
  "snapshotDate":"2025-06-15",
  "fields":["id","lon","lat","carried","below","location"],
  "records":[["0001",-77.116972,38.929444,"CHAIN BRIDGE","POTOMAC R. & C&O","OVER POTOMAC RIVER, N.W."]]
}
```

The abbreviated field `below` retains the legacy `FEATURES_DESC_006A` text and should be labeled **“Feature crossed (reported)”** in the interface. The source calls this “Features Intersected.” It is descriptive text, not a verified hydrological relationship. Empty source descriptions remain empty. IDs remain strings, preserving leading zeros.

State files are loaded only when local details are needed. The largest is Texas at approximately 5.2 MB. National rendering should bin or draw coordinate points using Canvas rather than creating a DOM element for every record. Use **state + detail row index** as the display key: the source repeats one ID in Massachusetts and one in Virginia at different locations.

`bridge_metadata.json` records full provenance, output hashes, processing, state counts, exclusions, and limitations. `bridge_exclusions.json` retains IDs, raw coordinates and reasons for every omitted location.

## Validation and unknown locations

All 49 published state/DC source counts reconcile exactly, totaling **618,895 records**. Of these, **1,464 records are omitted from the mapped extract**:

| Coordinate check | Omitted records |
|---|---:|
| Impossible DMS minutes or seconds | 961 |
| Invalid coordinate format | 364 |
| Missing coordinate | 23 |
| Outside broad contiguous-US coordinate bounds | 94 |
| Far outside the reported state's bounding box | 22 |

State envelopes use the bundled Census state geometry's bounding rectangle with a conservative 0.25-degree buffer. This catches gross source errors such as a Florida record placed in Texas without enforcing exact boundary membership or discarding bridges just beyond a state line. It is a coarse sanity check, not geolocation validation.

All **251 retained DC records** were compared against the independently downloaded official 2025 DC GeoJSON. Decimal positions agree within 0.0000005 degrees. The comparison verifies the DMS conversion; it does not establish survey accuracy. The converted GeoJSON rolls malformed DMS components into numeric positions, so those malformed source records are rejected here even if they have numeric GeoJSON coordinates.

Two repeated source IDs with different positions are retained, not merged: Massachusetts `N100108PDDOTNBI` and Virginia `000000000001826`. Consequently, counts describe inventory records rather than a deduplicated count of physical structures.

Coordinates can refer to a beginning or another consistent reference point on a structure; they are not bridge footprints. Six decimal places is an output precision choice, not an accuracy claim. Positions inside the coarse envelopes may still be wrong. The public highway inventory is not a complete census of all private, railway or pedestrian structures. The layer contains no load ratings, clearance, condition scores, vehicle suitability, approach connectivity or recommendations. FHWA specifically cautions that NBI data should not be used for route clearance.
