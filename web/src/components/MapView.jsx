import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { fillColorExpr, fillOpacityExpr, NATIVE_ZOOM, COLORS } from "../lib/style.js";

const EMPTY = { type: "FeatureCollection", features: [] };

export default function MapView({ village, meta, filter, showOriginal, selected, onSelect }) {
  const ref = useRef(null);
  const map = useRef(null);
  const ready = useRef(false);

  // Build / rebuild the map when the village changes.
  useEffect(() => {
    if (!meta) return;
    ready.current = false;
    if (map.current) { map.current.remove(); map.current = null; }

    const m = new maplibregl.Map({
      container: ref.current,
      style: {
        version: 8,
        sources: {
          imagery: {
            type: "raster",
            tiles: [`./tiles/${village}/{z}/{x}/{y}.png`],
            tileSize: 256,
            minzoom: 13,
            maxzoom: NATIVE_ZOOM[village], // overzoom the deepest real tile client-side
            attribution: "BhuMe imagery.tif",
          },
        },
        layers: [
          { id: "bg", type: "background", paint: { "background-color": "#0d1117" } },
          { id: "imagery", type: "raster", source: "imagery" },
        ],
      },
      bounds: meta.bounds,
      fitBoundsOptions: { padding: 40 },
      maxZoom: 21,
    });
    map.current = m;
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    m.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");

    m.on("load", async () => {
      const [corr, orig] = await Promise.all([
        fetch(`./data/${village}_corrected.geojson`).then((r) => r.json()),
        fetch(`./data/${village}_original.geojson`).then((r) => r.json()),
      ]);
      m.addSource("corrected", { type: "geojson", data: corr });
      m.addSource("original", { type: "geojson", data: orig });
      m.addSource("sel", { type: "geojson", data: EMPTY });

      m.addLayer({ id: "corr-fill", source: "corrected", type: "fill",
        paint: { "fill-color": fillColorExpr, "fill-opacity": fillOpacityExpr } });

      // Official outline goes above fill so it's always visible.
      m.addLayer({
        id: "original-line", source: "original", type: "line",
        layout: { visibility: showOriginal ? "visible" : "none" },
        paint: { "line-color": COLORS.original, "line-width": 1.5, "line-dasharray": [3, 2], "line-opacity": 0.95 },
      });

      m.addLayer({ id: "corr-line", source: "corrected", type: "line",
        paint: { "line-color": fillColorExpr, "line-width": 0.8, "line-opacity": 0.9 } });

      // Selection highlight on top.
      m.addLayer({ id: "sel-line", source: "sel", type: "line",
        paint: { "line-color": COLORS.selected, "line-width": 2.5 } });

      m.on("click", "corr-fill", (e) => {
        if (e.features?.length) onSelect(e.features[0].properties);
      });
      m.on("mouseenter", "corr-fill", () => (m.getCanvas().style.cursor = "pointer"));
      m.on("mouseleave", "corr-fill", () => (m.getCanvas().style.cursor = ""));

      ready.current = true;
      applyFilter(m, filter);
    });

    return () => { if (map.current) { map.current.remove(); map.current = null; } };
  }, [village, meta]);

  // Toggle official outline.
  useEffect(() => {
    const m = map.current;
    if (m && ready.current && m.getLayer("original-line"))
      m.setLayoutProperty("original-line", "visibility", showOriginal ? "visible" : "none");
  }, [showOriginal]);

  // Apply status / confidence filter.
  useEffect(() => {
    if (map.current && ready.current) applyFilter(map.current, filter);
  }, [filter]);

  // Highlight + fly to the selected plot.
  useEffect(() => {
    const m = map.current;
    if (!m || !ready.current) return;
    const src = m.getSource("sel");
    if (!selected) { src?.setData(EMPTY); return; }
    const data = m.querySourceFeatures("corrected", {
      filter: ["==", ["get", "plot_number"], selected.plot_number],
    });
    if (data.length) {
      // querySourceFeatures returns one shard per tile — take only the first
      // to avoid multiple overlapping white outlines on repeated clicks.
      src.setData({ type: "FeatureCollection", features: [data[0]] });
      const b = new maplibregl.LngLatBounds();
      eachCoord(data[0].geometry.coordinates, ([lng, lat]) => b.extend([lng, lat]));
      if (!b.isEmpty()) m.fitBounds(b, { padding: 160, maxZoom: 19, duration: 600 });
    }
  }, [selected]);

  return <div ref={ref} className="map" />;
}

// Walk nested GeoJSON coordinate arrays, calling fn on each [lng,lat] pair.
function eachCoord(c, fn) {
  if (typeof c[0] === "number") fn(c);
  else for (const sub of c) eachCoord(sub, fn);
}

function applyFilter(m, filter) {
  const clauses = ["all"];
  if (filter.status !== "all") clauses.push(["==", ["get", "status"], filter.status]);
  if (filter.minConf > 0)
    clauses.push([">=", ["coalesce", ["get", "confidence"], 0], filter.minConf]);
  const f = clauses.length > 1 ? clauses : null;
  for (const id of ["corr-fill", "corr-line"]) if (m.getLayer(id)) m.setFilter(id, f);
}
