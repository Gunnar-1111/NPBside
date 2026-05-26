import Link from "next/link";
import parkFactors from "../../../data/park-factors.json";
import teams from "../../../data/teams.json";
import offense from "../../../data/team-offense-ratings.json";

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

type OffenseRating = {
  league: string;
  games: number;
  avgRuns: number;
  avgNeutralized: number;
  offenseRating: number;
};

function ratingClass(r: number): string {
  if (r > 0.2) return "text-green-500";
  if (r < -0.2) return "text-red-400";
  return "text-white/60";
}

export default function TeamsPage() {
  const parks = Object.entries(parkFactors)
    .filter(([k]) => !k.startsWith("_"))
    .map(([k, v]) => [k, v as ParkInfo] as const)
    .sort((a, b) => b[1].runs - a[1].runs);

  const central = (teams as { central: TeamInfo[] }).central;
  const pacific = (teams as { pacific: TeamInfo[] }).pacific;
  const offMap = (offense as { teams: Record<string, OffenseRating> }).teams;

  const teamRow = (t: TeamInfo) => {
    const o = offMap[t.abbr];
    return (
      <tr key={t.abbr} className="border-b border-white/5">
        <td className="py-1.5 font-mono text-amber-500">{t.abbr}</td>
        <td className="py-1.5">{t.name}</td>
        <td className="py-1.5 text-white/40 text-xs">{t.parkAbbr}</td>
        <td className={`py-1.5 text-right font-mono ${o ? ratingClass(o.offenseRating) : "text-white/30"}`}>
          {o ? `${o.offenseRating >= 0 ? "+" : ""}${o.offenseRating.toFixed(2)}` : "—"}
        </td>
        <td className="py-1.5 text-right font-mono text-white/50 text-xs">
          {o ? `${o.avgRuns.toFixed(2)} r/g` : "—"}
        </td>
      </tr>
    );
  };

  return (
    <main className="max-w-5xl mx-auto p-6 md:p-10">
      <header className="mb-8">
        <div className="flex items-baseline justify-between">
          <h1 className="text-2xl font-semibold tracking-tight">Teams &amp; parks</h1>
          <Link href="/" className="font-mono text-xs text-amber-500/80 hover:text-amber-500">
            ← board
          </Link>
        </div>
        <p className="text-xs text-white/40 mt-1 font-mono">
          Park factors and offense ratings derived from 2024-25 corpus (n=1697).
        </p>
      </header>

      <section className="mb-10">
        <h2 className="text-sm font-mono uppercase text-white/50 mb-3 tracking-wider">Teams</h2>
        <div className="grid md:grid-cols-2 gap-8 text-sm">
          <div>
            <div className="text-white/40 mb-2 font-mono text-xs">Central League</div>
            <table className="w-full">
              <thead>
                <tr className="text-white/40 border-b border-white/10 text-xs font-mono">
                  <th className="text-left pb-2">abbr</th>
                  <th className="text-left pb-2">name</th>
                  <th className="text-left pb-2">park</th>
                  <th className="text-right pb-2">off rtg</th>
                  <th className="text-right pb-2">avg R</th>
                </tr>
              </thead>
              <tbody>{central.map(teamRow)}</tbody>
            </table>
          </div>
          <div>
            <div className="text-white/40 mb-2 font-mono text-xs">Pacific League</div>
            <table className="w-full">
              <thead>
                <tr className="text-white/40 border-b border-white/10 text-xs font-mono">
                  <th className="text-left pb-2">abbr</th>
                  <th className="text-left pb-2">name</th>
                  <th className="text-left pb-2">park</th>
                  <th className="text-right pb-2">off rtg</th>
                  <th className="text-right pb-2">avg R</th>
                </tr>
              </thead>
              <tbody>{pacific.map(teamRow)}</tbody>
            </table>
          </div>
        </div>
      </section>

      <section>
        <h2 className="text-sm font-mono uppercase text-white/50 mb-3 tracking-wider">Park factors</h2>
        <table className="w-full text-sm font-mono">
          <thead>
            <tr className="text-white/40 border-b border-white/10 text-xs">
              <th className="text-left pb-2">Park</th>
              <th className="text-left pb-2">Team</th>
              <th className="text-right pb-2">Runs PF</th>
              <th className="text-right pb-2">HR PF</th>
              <th className="text-left pb-2 pl-4">Roof</th>
              <th className="text-right pb-2">n games</th>
            </tr>
          </thead>
          <tbody>
            {parks.map(([key, p]) => {
              const runsClass = p.runs > 1.05 ? "text-green-500" : p.runs < 0.95 ? "text-red-400" : "text-white/70";
              const hrClass = p.hr > 1.1 ? "text-green-500" : p.hr < 0.9 ? "text-red-400" : "text-white/60";
              const nGames = p._runsCalibration?.match(/n=(\d+)/)?.[1] ?? "—";
              return (
                <tr key={key} className="border-b border-white/5">
                  <td className="py-1.5">{p.name}</td>
                  <td className="py-1.5 text-amber-500">{p.team}</td>
                  <td className={`py-1.5 text-right ${runsClass}`}>{p.runs.toFixed(3)}</td>
                  <td className={`py-1.5 text-right ${hrClass}`}>{p.hr.toFixed(3)}</td>
                  <td className="py-1.5 pl-4 text-white/40">{p.roof}</td>
                  <td className="py-1.5 text-right text-white/40 text-xs">{nGames}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </main>
  );
}
