/* กราฟ SVG ทั้งหมด (ไม่พึ่ง lib ภายนอก) — แยกจาก App.tsx (H02) */
import type { HistoryRow } from "../api/client";
import { scoreVar, verdictSoft, verdictVar } from "../lib/format";

export function Gauge({ score, verdict }: { score: number; verdict: string }) {
  const C = 2 * Math.PI * 64;
  const offset = C * (1 - Math.max(0, Math.min(10, score)) / 10);
  const col = verdictVar[verdict] ?? scoreVar(score);
  return (
    <div style={{ flexShrink: 0, display: "flex", flexDirection: "column", alignItems: "center", gap: 12, paddingLeft: 28, borderLeft: "1px solid var(--border)" }} className="hero-gauge">
      <div style={{ position: "relative", width: 160, height: 160 }}>
        <svg width="160" height="160" viewBox="0 0 160 160" style={{ transform: "rotate(-90deg)" }}>
          <circle cx="80" cy="80" r="64" fill="none" stroke="var(--surface-2)" strokeWidth="14" />
          <circle cx="80" cy="80" r="64" fill="none" stroke={col} strokeWidth="14" strokeLinecap="round" strokeDasharray={C} strokeDashoffset={offset} />
        </svg>
        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
          <div className="num" style={{ fontSize: 42, fontWeight: 800, color: col, lineHeight: 1 }}>{score.toFixed(2)}</div>
          <div style={{ fontSize: 13, color: "var(--text-3)", marginTop: 2 }}>/ 10</div>
        </div>
      </div>
      <span style={{ background: verdictSoft[verdict], color: col, padding: "6px 18px", borderRadius: 999, fontSize: 15, fontWeight: 800 }}>{verdict}</span>
    </div>
  );
}


export function Trend({ history }: { history: HistoryRow[] }) {
  const pts = history.filter((h) => h.overall_score != null).map((h) => ({ v: h.version_no, s: Number(h.overall_score) }));
  const W = 640, x0 = 40, x1 = 620, yTop = 10, yBot = 150;
  const x = (i: number) => (pts.length <= 1 ? (x0 + x1) / 2 : x0 + ((x1 - x0) * i) / (pts.length - 1));
  const y = (s: number) => yBot - (s / 10) * (yBot - yTop);
  const line = pts.map((p, i) => `${x(i)},${y(p.s)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} 180`} style={{ width: "100%", height: 180 }}>
      <line x1="40" y1="10" x2="40" y2="150" stroke="var(--border)" strokeWidth="1" />
      <line x1="40" y1="150" x2="620" y2="150" stroke="var(--border)" strokeWidth="1" />
      <text x="30" y="14" textAnchor="end" fontSize="11" fill="#94a1b5">10</text>
      <text x="30" y="84" textAnchor="end" fontSize="11" fill="#94a1b5">5</text>
      <text x="30" y="154" textAnchor="end" fontSize="11" fill="#94a1b5">0</text>
      <line x1="40" y1="80" x2="620" y2="80" stroke="var(--border)" strokeWidth="1" strokeDasharray="3 4" />
      {pts.length > 1 && <polyline points={line} fill="none" stroke="var(--primary)" strokeWidth="2.5" />}
      {pts.map((p, i) => (
        <g key={i}>
          <circle cx={x(i)} cy={y(p.s)} r="5" fill="var(--primary)" />
          <text x={x(i)} y="172" textAnchor="middle" fontSize="11.5" fill="var(--text-2)">v{p.v} · {p.s.toFixed(2)}</text>
        </g>
      ))}
    </svg>
  );
}


export function DonutVerdict({ data }: { data: Record<string, number> }) {
  const order = ["Strong", "Adequate", "Weak", "Critical"];
  const total = order.reduce((s, k) => s + (data[k] ?? 0), 0);
  const R = 60, C = 2 * Math.PI * R;
  let acc = 0;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
      <svg width="150" height="150" viewBox="0 0 150 150">
        <g transform="rotate(-90 75 75)">
          {total === 0 && <circle cx="75" cy="75" r={R} fill="none" stroke="var(--surface-2)" strokeWidth="20" />}
          {order.map((k) => {
            const v = data[k] ?? 0;
            if (!v) return null;
            const len = (v / total) * C;
            const seg = <circle key={k} cx="75" cy="75" r={R} fill="none" stroke={verdictVar[k]} strokeWidth="20"
              strokeDasharray={`${len} ${C - len}`} strokeDashoffset={-acc} />;
            acc += len;
            return seg;
          })}
        </g>
        <text x="75" y="70" textAnchor="middle" fontSize="26" fontWeight="800" fill="var(--text)">{total}</text>
        <text x="75" y="90" textAnchor="middle" fontSize="11" fill="var(--text-3)">proposals</text>
      </svg>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {order.map((k) => (
          <div key={k} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13.5 }}>
            <span style={{ width: 11, height: 11, borderRadius: 3, background: verdictVar[k], display: "inline-block" }} />
            <span style={{ color: "var(--text-2)", minWidth: 68 }}>{k}</span>
            <b>{data[k] ?? 0}</b>
          </div>
        ))}
      </div>
    </div>
  );
}


export function ScoreWinTrend({ data }: { data: { month: string; avg_score: number; count: number; won: number; lost: number; win_rate: number | null }[] }) {
  if (data.length === 0) return <div style={{ color: "var(--text-3)", padding: "30px 0", textAlign: "center" }}>No data yet</div>;
  const W = 640, H = 210, x0 = 42, x1 = 596, yTop = 16, yBot = 168;
  const n = data.length;
  const x = (i: number) => (n <= 1 ? (x0 + x1) / 2 : x0 + ((x1 - x0) * i) / (n - 1));
  const yScore = (s: number) => yBot - (s / 10) * (yBot - yTop);
  const yRate = (r: number) => yBot - r * (yBot - yTop); // r = 0..1
  const scorePts = data.map((d, i) => ({ x: x(i), y: yScore(d.avg_score), v: d.avg_score }));
  const ratePts = data.map((d, i) => ({ i, x: x(i), r: d.win_rate })).filter((p) => p.r != null) as { i: number; x: number; r: number }[];
  const scoreLine = scorePts.map((p) => `${p.x},${p.y}`).join(" ");
  const rateLine = ratePts.map((p) => `${p.x},${yRate(p.r)}`).join(" ");
  const hasRate = ratePts.length > 0;
  return (
    <div>
      <div style={{ display: "flex", gap: 18, marginBottom: 6, fontSize: 12.5 }}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}><span style={{ width: 14, height: 3, background: "var(--primary)", display: "inline-block", borderRadius: 2 }} /> Avg Score (left)</span>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}><span style={{ width: 14, height: 3, background: "var(--green)", display: "inline-block", borderRadius: 2 }} /> Win-Rate (right)</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: 210 }}>
        {[0, 5, 10].map((s) => (
          <g key={s}>
            <line x1={x0} y1={yScore(s)} x2={x1} y2={yScore(s)} stroke="var(--border)" strokeWidth="1" strokeDasharray={s === 0 ? "0" : "3 4"} />
            <text x={x0 - 8} y={yScore(s) + 4} textAnchor="end" fontSize="11" fill="var(--primary)">{s}</text>
          </g>
        ))}
        {[0, 0.5, 1].map((r) => (
          <text key={r} x={x1 + 8} y={yRate(r) + 4} textAnchor="start" fontSize="11" fill="var(--green)">{r * 100}%</text>
        ))}
        {/* score */}
        {n > 1 && <polyline points={scoreLine} fill="none" stroke="var(--primary)" strokeWidth="2.5" />}
        {scorePts.map((p, i) => (
          <g key={i}>
            <circle cx={p.x} cy={p.y} r="4.5" fill="var(--primary)" />
            <text x={p.x} y={p.y - 10} textAnchor="middle" fontSize="11" fontWeight="700" fill="var(--primary)">{p.v.toFixed(2)}</text>
          </g>
        ))}
        {/* win-rate */}
        {ratePts.length > 1 && <polyline points={rateLine} fill="none" stroke="var(--green)" strokeWidth="2.5" />}
        {ratePts.map((p, i) => (
          <g key={i}>
            <circle cx={p.x} cy={yRate(p.r)} r="4.5" fill="var(--green)" />
            <text x={p.x} y={yRate(p.r) - 10} textAnchor="middle" fontSize="11" fontWeight="700" fill="var(--green)">{(p.r * 100).toFixed(0)}%</text>
          </g>
        ))}
        {/* x labels */}
        {data.map((d, i) => (
          <text key={d.month} x={x(i)} y={H - 6} textAnchor="middle" fontSize="11.5" fill="var(--text-2)">{d.month} · n={d.count}</text>
        ))}
      </svg>
      {!hasRate && <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 4 }}>Win-Rate จะปรากฏเมื่อมี Deal Outcome (Won/Lost) — ตอนนี้ยังเป็น Pending ทั้งหมด</div>}
    </div>
  );
}

