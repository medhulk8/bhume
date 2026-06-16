"""Build frontend data from predictions.geojson + input.geojson.

Does NOT modify the graded predictions.geojson. Emits derived artifacts the
static React/MapLibre app consumes:

  web/public/data/<village>_corrected.geojson  — display geometry + structured
       signals parsed out of method_note (dx, dy, shift_m, agree_m, area_ratio,
       source, decision reason). Keyed by plot_number.
  web/public/data/<village>_original.geojson   — official input geometry, same
       plot_number key, for the before/after swipe.
  web/public/data/<village>_meta.json          — counts + bounds for map init.

Usage (from kit/):
    uv run python ../src/build_web_data.py
"""

from __future__ import annotations
import json
import re
from pathlib import Path
import geopandas as gpd

ROOT = Path(__file__).parent.parent
OUT = ROOT / "web" / "public" / "data"

NUM = r"(-?\d+(?:\.\d+)?)"
RE_CORR = re.compile(
    rf"(?P<src>\w+)\s+dx={NUM}m\s+dy={NUM}m\s+agree={NUM}m\s+ar={NUM}"
)


def parse_note(status: str, note: str) -> dict:
    note = note or ""
    if status == "corrected":
        m = RE_CORR.search(note)
        if m:
            dx, dy, agree, ar = (float(m.group(i)) for i in (2, 3, 4, 5))
            return {
                "source": m.group("src"),
                "dx_m": round(dx, 2), "dy_m": round(dy, 2),
                "shift_m": round((dx * dx + dy * dy) ** 0.5, 2),
                "agree_m": round(agree, 2), "area_ratio": round(ar, 3),
                "reason": "corrected — confidence above 0.5 threshold",
            }
        return {"reason": note}
    # flagged
    return {"reason": note}


def build_village(slug: str) -> dict:
    vdir = ROOT / "data" / slug
    preds = gpd.read_file(vdir / "predictions.geojson")
    inp = gpd.read_file(vdir / "input.geojson")

    inp_pn = "plot_number" if "plot_number" in inp.columns else inp.index.name
    inp = inp.set_index(inp_pn) if inp_pn in inp.columns else inp
    orig_geom = {str(pn): geom for pn, geom in zip(inp.index.astype(str), inp.geometry)}

    corr_features, orig_features = [], []
    counts = {"corrected": 0, "flagged": 0}

    for _, row in preds.iterrows():
        pn = str(row["plot_number"])
        status = row["status"]
        conf = row.get("confidence")
        conf = None if conf is None or (isinstance(conf, float) and conf != conf) else float(conf)
        sig = parse_note(status, row.get("method_note"))
        counts[status] = counts.get(status, 0) + 1

        props = {"plot_number": pn, "status": status, "confidence": conf, **sig}
        corr_features.append({
            "type": "Feature", "properties": props,
            "geometry": json.loads(gpd.GeoSeries([row.geometry]).to_json())["features"][0]["geometry"],
        })
        og = orig_geom.get(pn)
        if og is not None:
            orig_features.append({
                "type": "Feature", "properties": {"plot_number": pn, "status": status},
                "geometry": json.loads(gpd.GeoSeries([og]).to_json())["features"][0]["geometry"],
            })

    OUT.mkdir(parents=True, exist_ok=True)
    _dump(OUT / f"{slug}_corrected.geojson", corr_features)
    _dump(OUT / f"{slug}_original.geojson", orig_features)

    b = preds.total_bounds  # minx,miny,maxx,maxy in 4326
    meta = {
        "slug": slug, "counts": counts, "n_plots": len(preds),
        "bounds": [float(b[0]), float(b[1]), float(b[2]), float(b[3])],
        "center": [float((b[0] + b[2]) / 2), float((b[1] + b[3]) / 2)],
    }
    (OUT / f"{slug}_meta.json").write_text(json.dumps(meta, indent=2))
    print(f"  {slug}: {counts} | bounds {[round(x,4) for x in meta['bounds']]}")
    return meta


def _dump(path: Path, features: list) -> None:
    fc = {"type": "FeatureCollection", "features": features}
    path.write_text(json.dumps(fc, separators=(",", ":")))


def main():
    metas = [build_village(s) for s in ("vadnerbhairav", "malatavadi")]
    (OUT / "villages.json").write_text(json.dumps(metas, indent=2))
    print(f"\nWrote frontend data to {OUT}")


if __name__ == "__main__":
    main()
