// Outcome colors, shared by the map layers and the legend/inspector.
export const COLORS = {
  highConf: "#27ae60", // corrected, confidence >= 0.75
  midConf: "#f39c12",  // corrected, 0.5 <= confidence < 0.75
  flagged: "#e74c3c",  // flagged
  original: "#3498db", // official (pre-correction) outline
  selected: "#ffffff",
};

// Native imagery zoom per village (tiles baked no deeper than this).
export const NATIVE_ZOOM = { vadnerbhairav: 17, malatavadi: 18 };

// MapLibre data-driven fill color: flagged red, else conf-banded green/amber.
export const fillColorExpr = [
  "case",
  ["==", ["get", "status"], "flagged"], COLORS.flagged,
  [">=", ["coalesce", ["get", "confidence"], 0], 0.75], COLORS.highConf,
  COLORS.midConf,
];

// Opacity rises with confidence for corrected plots; flagged sits flat.
export const fillOpacityExpr = [
  "case",
  ["==", ["get", "status"], "flagged"], 0.20,
  ["interpolate", ["linear"], ["coalesce", ["get", "confidence"], 0], 0.5, 0.15, 1.0, 0.35],
];

export function outcomeLabel(f) {
  if (f.status === "flagged") return "Flagged";
  if ((f.confidence ?? 0) >= 0.75) return "Corrected · high confidence";
  return "Corrected · medium confidence";
}
