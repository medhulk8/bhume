import { useEffect, useState } from "react";
import MapView from "./components/MapView.jsx";
import Sidebar from "./components/Sidebar.jsx";
import Inspector from "./components/Inspector.jsx";
import MetricsModal from "./components/MetricsModal.jsx";

export default function App() {
  const [villages, setVillages] = useState(null);
  const [village, setVillage] = useState(null);
  const [metaByVillage, setMetaByVillage] = useState({});
  const [filter, setFilter] = useState({ status: "all", minConf: 0 });
  const [showOriginal, setShowOriginal] = useState(false);
  const [selected, setSelected] = useState(null);
  const [showMetrics, setShowMetrics] = useState(false);

  useEffect(() => {
    fetch("./data/villages.json").then((r) => r.json()).then((vs) => {
      setVillages(vs);
      setVillage(vs[0].slug);
      setMetaByVillage(Object.fromEntries(vs.map((v) => [v.slug, v])));
    });
  }, []);

  // Clear selection when switching village.
  useEffect(() => { setSelected(null); }, [village]);

  if (!villages || !village) return <div className="loading">Loading review console…</div>;
  const meta = metaByVillage[village];

  return (
    <div className="app">
      <Sidebar
        villages={villages} village={village} setVillage={setVillage} meta={meta}
        filter={filter} setFilter={setFilter}
        showOriginal={showOriginal} setShowOriginal={setShowOriginal}
        onOpenMetrics={() => setShowMetrics(true)}
      />
      <main className="stage">
        <MapView
          village={village} meta={meta} filter={filter}
          showOriginal={showOriginal} selected={selected} onSelect={setSelected}
        />
      </main>
      <Inspector plot={selected} onClose={() => setSelected(null)} />
      {showMetrics && <MetricsModal onClose={() => setShowMetrics(false)} />}
    </div>
  );
}
