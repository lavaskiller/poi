# Dataset upload template

Keep this folder layout, then ZIP and upload it in the dashboard.

## Required inputs

- `photos/`: evaluation images
- `manifest.csv`: mapping from image to the user-chosen raw GT text

## Minimum `manifest.csv` columns

| column | required | meaning |
|---|---|---|
| `photo` | yes | Image path relative to the ZIP root, e.g. `photos/IMG_0001.jpg` |
| `gt_input_raw` | yes | Raw ground-truth text from the user (place name, map share URL, provider place id, name+address, …) |
| `notes` | optional | Human notes |

## Optional columns (EXIF fallback)

By default you do **not** fill `capture_lat`, `capture_lon`, `timestamp`, `country`, or `city`. The tool extracts them from EXIF and coordinate lookups; only failed rows need manual correction.

If an export stripped location/capture metadata (for example re-encoded map-app photos with empty EXIF GPS), you may fill the columns below in the manifest. Non-empty values are kept as-is; empty cells still fall back to EXIF.

| column | meaning |
|---|---|
| `capture_lat` / `capture_lon` | Capture latitude/longitude (decimal). Aliases `lat`/`lon` accepted |
| `timestamp` | Capture time (ISO 8601, e.g. `2026-07-05T00:25:23Z`) |

## Example `manifest.csv`

```csv
photo,gt_input_raw,notes
photos/IMG_0001.jpg,Safeway,
photos/IMG_0002.jpg,Capilano Suspension Bridge,plaque readable
```

When EXIF is empty but you still know coordinates and time:

```csv
photo,gt_input_raw,capture_lat,capture_lon,timestamp,notes
photos/IMG_0003.jpg,Example Cafe,37.7749,-122.4194,2026-07-05T12:00:00Z,no EXIF GPS
```
