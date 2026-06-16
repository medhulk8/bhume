// Method + metrics overlay: ablation ladder, calibration AUC, reliability diagrams.
const ABLATION = [
  ["Identity (no move)", "—", "—", "baseline"],
  ["Global median shift", "0.713", "0.588", "kit baseline"],
  ["Greedy chamfer (adaptive)", "0.912", "0.030", "best per-plot solo"],
  ["Two-pass: anchors + GP field", "0.872", "0.678", "field unlocks dense village"],
  ["+ calibration (final)", "0.872", "0.739", "decision-theory flag at 0.5"],
];
const AUC = [
  ["vadnerbhairav", "0.721", "298 (65% acc.)"],
  ["malatavadi", "0.804", "277 (57% acc.)"],
];

export default function MetricsModal({ onClose }) {
  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>Method & metrics</h2>
          <button className="close" onClick={onClose}>×</button>
        </div>

        <p className="lead">
          Drift from sparse-control georeferencing is <b>spatially coherent</b>. We estimate a smooth
          per-sheet drift field (affine + GP) from RANSAC-purified anchors, apply it vertex-by-vertex so
          the parcel fabric never tears, then calibrate confidence on a synthetic displacement-recovery
          set — never tuning to the 9 public truths.
        </p>

        <h3>Ablation ladder</h3>
        <table className="m-table">
          <thead><tr><th>Method</th><th>Vadner. IoU</th><th>Malata. IoU</th><th>Note</th></tr></thead>
          <tbody>{ABLATION.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className={j === 0 ? "l" : ""}>{c}</td>)}</tr>)}</tbody>
        </table>

        <h3>Confidence calibration — cross-validated AUC</h3>
        <table className="m-table">
          <thead><tr><th>Village</th><th>Synth AUC</th><th>Samples</th></tr></thead>
          <tbody>{AUC.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className={j === 0 ? "l" : ""}>{c}</td>)}</tr>)}</tbody>
        </table>

        <h3>Reliability diagrams</h3>
        <div className="reliab">
          <figure><img src="./metrics/reliability_vadnerbhairav.png" alt="vadnerbhairav reliability" /><figcaption>vadnerbhairav</figcaption></figure>
          <figure><img src="./metrics/reliability_malatavadi.png" alt="malatavadi reliability" /><figcaption>malatavadi</figcaption></figure>
        </div>
      </div>
    </div>
  );
}
