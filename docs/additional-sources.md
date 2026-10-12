# Additional source integration — 8 October 2026

The new `imagery_masks` feed connects reviewed orthophoto polygons to the existing
park-independent reconstruction engine. It does not download commercial imagery,
classify paving from colour, or claim new Alton geometry has been surveyed.

## Source interrogation

* Bluesky: the official aerial photography catalogue supplies GIS/CAD-ready
  orthophotos. No licensed Alton GeoTIFF was acquired in this pass. Capture date,
  permitted derived-world use and local resolution must be established first.
  https://bluesky-world.com/aerial-photography/
* OS NGD Transport Network: official documentation confirms path surface type,
  connectivity, GeoJSON/GeoPackage supply and BNG/ODN reference systems. Existing
  GeoJSON ingestion can consume explicitly normalized exports; native OS field
  mappings and Alton internal coverage are not implemented or verified. Access
  is via OS Data Hub, with licensing appropriate to the account.
  https://docs.os.uk/osngd/data-structure/transport/transport-network
* Historic England: confirmed archive record CC80/00026 (Loggia and Prospect
  Tower, 23–30 June 1926), OP08920 (Flag Tower, 1853–1908), OP08949 (gardens).
  Archive pages explicitly report full-screen/zoom image service unavailable.
  These are historical reference candidates, not georeferenced meshes or present
  day measurements. No dimensions or material colours were inferred.
  https://historicengland.org.uk/images-books/photos/item/CC80/00026
  https://historicengland.org.uk/images-books/photos/item/OP08920
  https://historicengland.org.uk/images-books/photos/item/OP08949
* Master survey 2936: exact-name public search yielded no usable survey. Existing
  retained planning references establish the name but not availability or datum.
  No claim that the survey does not exist; no new council-wide crawl was run.
* Mapillary: official imagery API documentation located. No authorized API
  credential or Alton coverage established; no imagery acquired.
  https://help.mapillary.com/hc/en-us/articles/360010234680-Accessing-imagery-and-data-through-the-Mapillary-API

## Reviewed imagery feed

Declare a Source with `kind: imagery`, `registration_status: accepted`, the image
CRS, a real source URI/licence, and `metadata.capture_date`. Acceptance is a
reviewer's assertion, not an automatic georeferencing accuracy measurement.

Add this feed to a normal `voxel-reconstruct` manifest:

```json
{"adapter":"imagery_masks","source":"licensed-orthophoto","file":"reviewed-masks.json"}
```

The masks file uses the same CRS as the image and source:

```json
{
  "imagery": {"file":"park-orthophoto.tif","sha256":"ACTUAL_IMAGE_SHA256"},
  "features": [{
    "id":"reviewed-entrance-plaza",
    "geometry":{"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
    "properties":{"kind":"plaza","reviewed":true,"reviewer":"REVIEWER",
                  "surface":"brick"}
  }]
}
```

Coordinates above are illustrative only. Geometry needs a reviewed trace;
material should be established from plans or clear imagery, and can instead use
`reconstruction_parameters` to cite a separate material source with measured,
documented or estimated status. Estimated evidence follows engine opt-in rules.

The adapter requires RGB data, accepted registration, a capture date, matching
CRS and a retained image hash. It rejects invalid/3D polygons, out-of-image
geometry, nodata/transparent coverage and unreviewed or material-free masks.
Polygon windows are capped at four million pixels and read in 512-pixel tiles.
Accepted features preserve image hash, date, resolution and reviewer. Projection,
whole-polygon material palettes, holes, terrain elevations and native collision
checks reuse the existing engine. A source failure aborts that feed; invalid
individual masks are reported as withheld without discarding valid neighbours.

This is a tested ingestion route ready for acquired imagery. No new game world is
exported until real imagery and reviewed masks are supplied.
