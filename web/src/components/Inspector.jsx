import { COLORS, outcomeLabel } from "../lib/style.js";

// Right-hand panel: full decision story for the selected plot.
export default function Inspector({ plot, onClose }) {
  if (!plot) {
    return (
      <aside className="inspector empty">
        <p>Click any parcel to inspect its correction, the signals behind it, and the decision path.</p>
      </aside>
    );
  }
  const corrected = plot.status === "corrected";
  const conf = plot.confidence;
  const color = plot.status === "flagged" ? COLORS.flagged : conf >= 0.75 ? COLORS.highConf : COLORS.midConf;

  return (
    <aside className="inspector">
      <div className="insp-head">
        <div>
          <div className="insp-pn">Plot {plot.plot_number}</div>
          <span className="badge" style={{ background: color }}>{outcomeLabel(plot)}</span>
        </div>
        <button className="close" onClick={onClose}>×</button>
      </div>

      {corrected && (
        <ConfGauge conf={conf} color={color} />
      )}

      <div className="insp-section">
        <h4>Decision</h4>
        <p className="reason">{plot.reason}</p>
      </div>

      {corrected && (
        <div className="insp-section">
          <h4>Signals</h4>
          <table className="signals">
            <tbody>
              <Row k="Source" v={plot.source === "gp" ? "GP drift field" : "Greedy chamfer"} />
              <Row k="Shift" v={`${plot.shift_m} m  (dx ${plot.dx_m}, dy ${plot.dy_m})`} />
              <Row k="agree_m" v={`${plot.agree_m} m`} hint="‖greedy − GP field‖ — low = signals agree = trustworthy" />
              <Row k="Area ratio" v={plot.area_ratio} hint="drawn ÷ recorded; in-band ⇒ placement-fixable" />
            </tbody>
          </table>
        </div>
      )}

      <div className="insp-section legend-inline">
        <h4>On the map</h4>
        <p><span className="dot" style={{ background: COLORS.original }} /> dashed blue = official position (toggle "Show official")</p>
        <p><span className="dot" style={{ background: color }} /> solid = {corrected ? "our corrected boundary" : "kept original (flagged)"}</p>
      </div>
    </aside>
  );
}

function ConfGauge({ conf, color }) {
  const pct = Math.round((conf ?? 0) * 100);
  return (
    <div className="gauge">
      <div className="gauge-label">
        <span>Calibrated confidence</span>
        <strong style={{ color }}>{conf?.toFixed(3)}</strong>
      </div>
      <div className="gauge-bar">
        <div className="gauge-fill" style={{ width: `${pct}%`, background: color }} />
        <div className="gauge-thresh" title="0.5 flag threshold" />
      </div>
      <div className="gauge-sub">P(IoU ≥ 0.5). Below 0.5 ⇒ flagged.</div>
    </div>
  );
}

function Row({ k, v, hint }) {
  return (
    <tr>
      <td className="k">{k}{hint && <span className="hint" title={hint}>?</span>}</td>
      <td className="v">{v}</td>
    </tr>
  );
}
