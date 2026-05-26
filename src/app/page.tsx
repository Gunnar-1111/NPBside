import parkFactors from "../../data/park-factors.json";
import teams from "../../data/teams.json";

type ParkInfo = {
  runs: number;
  hr: number;
  name: string;
  team: string;
  league: string;
  roof: string;
  lat: number;
  lon: number;
  altitudeFt: number;
  cfBearingDeg: number | null;
  notes?: string;
  _runsCalibration?: string;
  _hrCalibration?: string;
};

type TeamInfo = {
  abbr: string;
  name: string;
  city: string;
  parkAbbr: string;
  founded: number;
};

export default function Home() {
  const parks = Object.entries(parkFactors)
    .filter(([k]) => !k.startsWith("_"))
    .map(([k, v]) => [k, v as ParkInfo] as const)
    .sort((a, b) => b[1].runs - a[1].runs);

  const central = (teams as { central: TeamInfo[] }).central;
  const pacific = (teams as { pacific: TeamInfo[] }).pacific;

  return (
    <main className="max-w-5xl mx-auto p-8">
      <header className="mb-8">
        <h1 className="text-3xl font-semibold tracking-tight">NPBSide</h1>
        <p className="text-sm text-white/60 mt-1 font-mono">
          NPB lines engine. Data layer live; engine in progress.
        </p>
      </header>

      <section className="mb-10">
        <h2 className="text-lg font-medium mb-3">Teams</h2>
        <div className="grid grid-cols-2 gap-6 text-sm">
          <div>
            <div className="text-white/50 mb-2 font-mono text-xs uppercase">Central League</div>
            <ul className="space-y-1">
              {central.map((t) => (
                <li key={t.abbr} className="flex justify-between">
                  <span>
                    <span className="font-mono text-amber-500 mr-2">{t.abbr}</span>
                    {t.name}
                  </span>
                  <span className="text-white/40 font-mono text-xs">{t.parkAbbr}</span>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <div className="text-white/50 mb-2 font-mono text-xs uppercase">Pacific League</div>
            <ul className="space-y-1">
              {pacific.map((t) => (
                <li key={t.abbr} className="flex justify-between">
                  <span>
                    <span className="font-mono text-amber-500 mr-2">{t.abbr}</span>
                    {t.name}
                  </span>
                  <span className="text-white/40 font-mono text-xs">{t.parkAbbr}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <section>
        <h2 className="text-lg font-medium mb-3">Park factors</h2>
        <p className="text-xs text-white/40 mb-3 font-mono">
          Derived from 2024-2025 boxscore corpus (n=1697). Sorted by runs factor.
        </p>
        <table className="w-full text-sm font-mono">
          <thead>
            <tr className="text-white/50 border-b border-white/10">
              <th className="text-left pb-2">Park</th>
              <th className="text-left pb-2">Team</th>
              <th className="text-right pb-2">Runs PF</th>
              <th className="text-right pb-2">HR PF</th>
              <th className="text-left pb-2 pl-4">Roof</th>
            </tr>
          </thead>
          <tbody>
            {parks.map(([key, p]) => {
              const runsClass =
                p.runs > 1.05 ? "text-green-500" : p.runs < 0.95 ? "text-red-400" : "text-white/70";
              return (
                <tr key={key} className="border-b border-white/5">
                  <td className="py-1.5">{p.name}</td>
                  <td className="py-1.5 text-amber-500">{p.team}</td>
                  <td className={`py-1.5 text-right ${runsClass}`}>{p.runs.toFixed(3)}</td>
                  <td className="py-1.5 text-right text-white/60">{p.hr.toFixed(2)}</td>
                  <td className="py-1.5 pl-4 text-white/40">{p.roof}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </main>
  );
}
