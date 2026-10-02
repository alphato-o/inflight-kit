# Attribution

## Included in this repository

| What | Where | License |
|---|---|---|
| [three.js](https://threejs.org) r169 and OrbitControls | `tracker/static/3d/vendor/` | MIT |
| [D3](https://d3js.org) v7 | `tracker/static/vendor/d3.min.js` | ISC |
| [topojson-client](https://github.com/topojson/topojson-client) | `tracker/static/vendor/topojson-client.min.js` | ISC |
| [world-atlas](https://github.com/topojson/world-atlas) countries-50m, built from [Natural Earth](https://www.naturalearthdata.com) | `tracker/static/vendor/countries-50m.json` | ISC; Natural Earth is public domain |
| Earth textures from [three-globe](https://github.com/vasturiano/three-globe) (Blue Marble imagery by NASA) | `tracker/static/3d/tex/earth-*.{jpg,png}`, `night-sky.png` | MIT; NASA imagery is public domain |
| Airport table built from [OurAirports](https://ourairports.com/data/) | `tracker/static/airports.json` | Public domain |
| Photos of B-1135 by **N509FZ** on Wikimedia Commons: [1](https://commons.wikimedia.org/wiki/File:B-1135@PEK_(20190101150920).jpg), [2](https://commons.wikimedia.org/wiki/File:B-1135@PEK_(20190101150921).jpg) | `tracker/static/photos/commons-*.jpg` | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) |
| B-1135 cutout, derived from N509FZ's photo above with `tracker/tools/make_cutout.py` | `tracker/static/photos/b1135-cutout.png` | CC BY-SA 4.0 (same as the source) |

## Fetched on your machine, not included

| What | Used by | Terms |
|---|---|---|
| [Esri World Imagery](https://www.arcgis.com/home/item.html?id=10df2279f9684e4a9f6a7f08febac2a9) | `tools/prefetch_tiles.py`, 3D terrain colours | Attribution required: "Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community". Shown in the 3D view. Not redistributed here. |
| [AWS Terrain Tiles](https://registry.opendata.aws/terrain-tiles/) (Terrarium format) | `tools/prefetch_tiles.py`, 3D terrain heights | Open data; [source attribution](https://github.com/tilezen/joerd/blob/master/docs/attribution.md) (SRTM, GMTED2010, ETOPO1 and others) |
| [gnirehtet](https://github.com/Genymobile/gnirehtet) | `share/`, reverse tethering over USB | Apache 2.0, installed separately |

## Not affiliated

Minecraft is a trademark of Mojang Studios; the 3D view is a homage, not affiliated.
Hainan Airlines, Panasonic Avionics (eXConnect) and Boeing are named only to describe
what the code talks to or draws. No affiliation or endorsement.

The pages use fonts already on macOS (DIN, Avenir Next, Silom); none are distributed.
