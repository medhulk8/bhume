import { COLORS } from "../lib/style.js";

// Left rail: village switch, before/after toggle, filters, live counts, legend.
export default function Sidebar({ villages, village, setVillage, meta, filter, setFilter, showOriginal, setShowOriginal, onOpenMetrics }) {
  const counts = meta?.counts ?? {};
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="logo">BhuMe</div>
        <div className="subtitle">Boundary Review Console</div>
      </div>

      <Section title="Village">
        <div className="seg">
          {villages.map((v) => (
            <button key={v.slug} className={v.slug === village ? "on" : ""} onClick={() => setVillage(v.slug)}>
              {v.slug}
            </button>
          ))}
        </div>
        {meta && (
          <div className="counts">
            <Count label="Corrected" n={counts.corrected} color={COLORS.highConf} />
            <Count label="Flagged" n={counts.flagged} color={COLORS.flagged} />
            <Count label="Total" n={meta.n_plots} color="#8b949e" />
          </div>
        )}
      </Section>

      <Section title="Layers">
        <label className="check">
          <input type="checkbox" checked={showOriginal} onChange={(e) => setShowOriginal(e.target.checked)} />
          Show official position (dashed blue)
        </label>
      </Section>

      <Section title="Filter">
        <div className="seg small">
          {["all", "corrected", "flagged"].map((s) => (
            <button key={s} className={filter.status === s ? "on" : ""} onClick={() => setFilter({ ...filter, status: s })}>
              {s}
            </button>
          ))}
        </div>
        <label className="slider">
          <span>Min confidence: <strong>{filter.minConf.toFixed(2)}</strong></span>
          <input type="range" min="0" max="1" step="0.05" value={filter.minConf}
            onChange={(e) => setFilter({ ...filter, minConf: parseFloat(e.target.value) })} />
        </label>
      </Section>

      <Section title="Legend">
        <Legend color={COLORS.highConf} text="Corrected · conf ≥ 0.75" />
        <Legend color={COLORS.midConf} text="Corrected · 0.5–0.75" />
        <Legend color={COLORS.flagged} text="Flagged" />
        <Legend color={COLORS.original} text="Official position" dashed />
      </Section>

      <button className="metrics-btn" onClick={onOpenMetrics}>📊 Method & metrics</button>
      <div className="foot">Imagery, geometry & confidence are the pipeline's real output.</div>
    </aside>
  );
}

const Section = ({ title, children }) => (
  <div className="section"><h3>{title}</h3>{children}</div>
);
const Count = ({ label, n, color }) => (
  <div className="count"><span className="dot" style={{ background: color }} />{label}<b>{n?.toLocaleString() ?? "—"}</b></div>
);
const Legend = ({ color, text, dashed }) => (
  <div className="lg"><span className={"swatch" + (dashed ? " dashed" : "")} style={{ borderColor: color, background: dashed ? "transparent" : color }} />{text}</div>
);
