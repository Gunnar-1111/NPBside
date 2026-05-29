import Link from "next/link";
import { readdirSync, readFileSync } from "fs";
import path from "path";
import teamsData from "../../data/teams.json";

type TeamInfo = {
  abbr: string;
  name: string;
  city: string;
  parkAbbr: string;
};

type GameLine = {
  away: string;
  home: string;
  venue: string | null;
  startTime: string | null;
  weather: string | null;
  parkRunsFactor: number;
  awaySP: string;
  awaySPFound: boolean;
  awaySPRating: number;
  awayOffense: number;
  homeSP: string;
  homeSPFound: boolean;
  homeSPRating: number;
  homeOffense: number;
  lines: {
    awayMl: number;
    homeMl: number;
    awayWinPct: number;
    homeWinPct: number;
    total: number;
    awayExpectedRuns: number;
    homeExpectedRuns: number;
    awayRl15Price: number;
    awayRl15Pct: number;
    homeRl15Price: number;
    homeRl15Pct: number;
  };
};

type LinesFile = {
  date: string;
  games: GameLine[];
  constants: {
    LEAGUE_AVG_TOTAL: number;
    LEAGUE_AVG_PER_TEAM: number;
    HCA_RUNS: number;
    WIN_DIVISOR: number;
    VIG: number;
  };
};

// Build-time: pick the newest data/lines-YYYY-MM-DD.json. Filenames are
// zero-padded ISO dates, so a lexical sort is chronological. Adding a new
// slate file and pushing is enough to update the board — no code change.
function loadLatestLines(): LinesFile {
  const dir = path.join(process.cwd(), "data");
  const files = readdirSync(dir)
    .filter((f) => /^lines-\d{4}-\d{2}-\d{2}\.json$/.test(f))
    .sort();
  if (files.length === 0) throw new Error("no data/lines-*.json files found");
  const latest = files[files.length - 1];
  return JSON.parse(readFileSync(path.join(dir, latest), "utf-8")) as LinesFile;
}

const lines = loadLatestLines();

const allTeams: TeamInfo[] = [
  ...(teamsData as { central: TeamInfo[] }).central,
  ...(teamsData as { pacific: TeamInfo[] }).pacific,
];

function teamName(abbr: string): string {
  const t = allTeams.find((x) => x.abbr === abbr);
  return t ? t.name.replace(/^(Yomiuri|Hanshin|Yokohama DeNA|Hiroshima Toyo|Tokyo Yakult|Chunichi|Fukuoka SoftBank|Chiba Lotte|Saitama Seibu|Tohoku Rakuten|Hokkaido Nippon-Ham|Orix)\s?/, "") : abbr;
}

function teamCity(abbr: string): string {
  const t = allTeams.find((x) => x.abbr === abbr);
  return t ? t.city : abbr;
}

function fmtML(ml: number): string {
  return ml > 0 ? `+${ml}` : `${ml}`;
}

function ratingClass(r: number): string {
  if (r > 0.3) return "text-green-500";
  if (r < -0.3) return "text-red-400";
  return "text-white/60";
}

function GameCard({ g }: { g: GameLine }) {
  const L = g.lines;
  return (
    <div
      className="rounded-2xl p-5 bg-[#1a2235]/60 border border-white/5 hover:border-amber-500/30 transition"
      style={{ animation: "fadeUp 0.4s ease-out backwards" }}
    >
      <div className="flex items-baseline justify-between mb-4">
        <div className="font-mono text-xs text-white/40">
          {g.venue ?? "—"}
          {g.startTime ? ` · ${g.startTime}` : ""}
          {g.weather ? ` · ${g.weather}` : ""}
        </div>
        <div className="font-mono text-[10px] text-white/30 uppercase">park {g.parkRunsFactor.toFixed(3)}</div>
      </div>

      <div className="grid grid-cols-[1fr_auto_1fr] gap-3 items-center">
        <div className="text-right">
          <div className="text-xs text-white/40 font-mono">{teamCity(g.away)}</div>
          <div className="text-lg font-semibold leading-tight">{teamName(g.away)}</div>
          <div className="font-mono text-[11px] mt-1">
            <span className="text-white/40">SP </span>
            <span>{g.awaySP}</span>
            {!g.awaySPFound && <span className="text-red-400/80"> (unrated)</span>}
          </div>
          <div className={`font-mono text-[11px] mt-0.5 ${ratingClass(g.awaySPRating)}`}>
            SP rtg {g.awaySPRating >= 0 ? "+" : ""}{g.awaySPRating.toFixed(2)}
          </div>
          <div className={`font-mono text-[11px] ${ratingClass(g.awayOffense)}`}>
            off rtg {g.awayOffense >= 0 ? "+" : ""}{g.awayOffense.toFixed(2)}
          </div>
        </div>

        <div className="font-mono text-xl text-white/30">@</div>

        <div className="text-left">
          <div className="text-xs text-white/40 font-mono">{teamCity(g.home)}</div>
          <div className="text-lg font-semibold leading-tight">{teamName(g.home)}</div>
          <div className="font-mono text-[11px] mt-1">
            <span className="text-white/40">SP </span>
            <span>{g.homeSP}</span>
            {!g.homeSPFound && <span className="text-red-400/80"> (unrated)</span>}
          </div>
          <div className={`font-mono text-[11px] mt-0.5 ${ratingClass(g.homeSPRating)}`}>
            SP rtg {g.homeSPRating >= 0 ? "+" : ""}{g.homeSPRating.toFixed(2)}
          </div>
          <div className={`font-mono text-[11px] ${ratingClass(g.homeOffense)}`}>
            off rtg {g.homeOffense >= 0 ? "+" : ""}{g.homeOffense.toFixed(2)}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2 mt-4 pt-4 border-t border-white/5">
        <div className="text-center">
          <div className="text-[10px] uppercase text-white/40 font-mono tracking-wider">Away ML</div>
          <div className="font-mono text-xl text-amber-500 mt-1">{fmtML(L.awayMl)}</div>
          <div className="font-mono text-[10px] text-white/40">{L.awayWinPct.toFixed(1)}%</div>
        </div>
        <div className="text-center">
          <div className="text-[10px] uppercase text-white/40 font-mono tracking-wider">Total</div>
          <div className="font-mono text-xl text-amber-500 mt-1">{L.total.toFixed(1)}</div>
          <div className="font-mono text-[10px] text-white/40">{L.awayExpectedRuns.toFixed(2)} / {L.homeExpectedRuns.toFixed(2)}</div>
        </div>
        <div className="text-center">
          <div className="text-[10px] uppercase text-white/40 font-mono tracking-wider">Home ML</div>
          <div className="font-mono text-xl text-amber-500 mt-1">{fmtML(L.homeMl)}</div>
          <div className="font-mono text-[10px] text-white/40">{L.homeWinPct.toFixed(1)}%</div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 mt-3 text-center">
        <div>
          <div className="text-[10px] uppercase text-white/40 font-mono tracking-wider">Away RL +1.5</div>
          <div className="font-mono text-sm text-white/80">{fmtML(L.awayRl15Price)} <span className="text-white/40">({L.awayRl15Pct.toFixed(0)}%)</span></div>
        </div>
        <div>
          <div className="text-[10px] uppercase text-white/40 font-mono tracking-wider">Home RL −1.5</div>
          <div className="font-mono text-sm text-white/80">{fmtML(L.homeRl15Price)} <span className="text-white/40">({L.homeRl15Pct.toFixed(0)}%)</span></div>
        </div>
      </div>
    </div>
  );
}

export default function Home() {
  return (
    <main className="max-w-6xl mx-auto p-6 md:p-10">
      <header className="mb-8">
        <div className="flex items-baseline justify-between">
          <h1 className="text-3xl font-semibold tracking-tight">
            NPBSide <span className="text-amber-500">/</span> Board
          </h1>
          <div className="font-mono text-xs text-white/40">
            {lines.date} · {lines.games.length} games · model v0
          </div>
        </div>
        <p className="text-sm text-white/60 mt-1 font-mono">
          Pitcher-driven NPB line origination. SP rating · team offense · park factor.
        </p>
      </header>

      <section className="grid md:grid-cols-2 gap-4">
        {lines.games.map((g, i) => (
          <div key={`${g.away}-${g.home}-${i}`} style={{ animationDelay: `${i * 50}ms` }}>
            <GameCard g={g} />
          </div>
        ))}
      </section>

      <section className="mt-10 pt-6 border-t border-white/5">
        <h2 className="text-sm font-mono uppercase text-white/50 mb-3 tracking-wider">Engine constants</h2>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 font-mono text-xs">
          <div className="bg-white/5 rounded-lg p-3">
            <div className="text-white/40">LEAGUE_AVG_TOTAL</div>
            <div className="text-base text-amber-500 mt-1">{lines.constants.LEAGUE_AVG_TOTAL}</div>
          </div>
          <div className="bg-white/5 rounded-lg p-3">
            <div className="text-white/40">avg / team</div>
            <div className="text-base text-amber-500 mt-1">{lines.constants.LEAGUE_AVG_PER_TEAM}</div>
          </div>
          <div className="bg-white/5 rounded-lg p-3">
            <div className="text-white/40">HCA runs</div>
            <div className="text-base text-amber-500 mt-1">{lines.constants.HCA_RUNS}</div>
          </div>
          <div className="bg-white/5 rounded-lg p-3">
            <div className="text-white/40">win divisor</div>
            <div className="text-base text-amber-500 mt-1">{lines.constants.WIN_DIVISOR}</div>
          </div>
          <div className="bg-white/5 rounded-lg p-3">
            <div className="text-white/40">vig</div>
            <div className="text-base text-amber-500 mt-1">{(lines.constants.VIG * 100).toFixed(1)}%</div>
          </div>
        </div>
        <p className="text-[11px] text-white/40 font-mono mt-3">
          LEAGUE_AVG derived from 2024-25 corpus (n=1697); HCA + win-divisor are plan-numbers pending calibration.{" "}
          <Link href="/teams" className="text-amber-500/80 hover:text-amber-500">Teams &amp; parks →</Link>
        </p>
      </section>
    </main>
  );
}
