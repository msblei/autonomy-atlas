// countries.geojson -> countries.topojson (run by `atlas export`, pipeline/export.py): every border
// shared by two countries is stored once, coordinates as integer steps. Quantization 360,000 over
// the world's extent: steps of 0.001° in longitude, as fine as the GeoJSON's three decimals.
// The page decodes it with topojson-client; pipeline/validate.py checks it against the GeoJSON.
import { readFileSync, writeFileSync } from "node:fs";
import { topology } from "topojson-server";

const dir = new URL("../public/data/", import.meta.url);
const geo = JSON.parse(readFileSync(new URL("countries.geojson", dir), "utf8"));
const topo = topology({ countries: geo }, 360000);
writeFileSync(new URL("countries.topojson", dir), JSON.stringify(topo));
console.log(`countries.topojson: ${geo.features.length} countries, ${topo.arcs.length} arcs`);
