import Link from "next/link";
import { readdirSync, readFileSync } from "fs";
import path from "path";

// Results ledger — NPBSide originated lines vs the book's posted lines,
// graded against actuals. Reads every data/grade-{date}.json (written by
// scripts/grade-day.py --write) at build time and aggregates a rolling
// model-vs-book scorecard. Static server component, same as the board.

type GameGrade = {
  matchup: string;
  actual: string;
  actualTotal: number;
  modelFav: string;
  modelFavMl: number;
  modelTotal: number;
  sideResult: "WIN" | "LOSS" | "PUSH";
  totalDiff: number;
  totalSide: string;
  rlOutcome: string;
  bookFav: string | null;
  bookFavMl: number | null;
  bookTotal: number | null;
  bookSideResult: "WIN" | "LOSS" | "PUSH" | null;
};

type HeadToHead = { we_only: number; book_only: number; both_right: number; both_wrong: number };

type Grade = {
  date: string;
  summary: {
    model: { sides: string; totalMaeR: number };
    // Null on days the book didn't post lines (e.g. 5/26) — guard everywhere.
    book: { sides: string } | null;
    headToHead: HeadToHead | null;
  };
  games: GameGrade[];
};

// Parse a "W-L-P" sides string into [w, l, p]; tolerates null/short strings.
function parseSides(s: string | undefined): [number, number, number] {
  if (!s) return [0, 0, 0];
  const [w = 0, l = 0, p = 0] = s.split("-").map(Number);
  return [w, l, p];
}

// Build-time: load every graded day, newest first.
function loadGrades(): Grade[] {
  const dir = path.join(process.cwd(), "data");
  const files = readdirSync(dir)
    .filter((f) => /^grade-\d{4}-\d{2}-\d{2}\.json$/.test(f))
    .sort()
    .reverse();
  return files.map((f) => JSON.parse(readFileSync(path.join(dir, f), "utf-8")) as Grade);
}

function fmtML(ml: number | null): string {
  if (ml == null) return "—";
  return ml > 0 ? `+${ml}` : String(ml);
}

function winPct(w: number, l: number): number {
  const n = w + l;
  return n ? (100 * w) / n : 0;
}

function ResultCell({ r }: { r: GameGrade["sideResult"] | null }) {
  if (r === "WIN") return <span className="text-green-500 font-semibold">W</span>;
  if (r === "LOSS") return <span className="text-red-400 font-semibold">L</span>;
  if (r === "PUSH") return <span className="text-white/40">P</span>;
  return <span className="text-white/20">—</span>;
}

export default function Results() {
  const grades = loadGrades();

  // ── Rolling aggregate across every graded day ──
  let mW = 0, mL = 0, mP = 0, bW = 0, bL = 0, bP = 0;
  let weOnly = 0, bookOnly = 0, bothRight = 0, bothWrong = 0;
  const modelErrs: number[] = [];
  const bookErrs: number[] = [];

  for (const g of grades) {
    const [w, l, p] = parseSides(g.summary.model.sides);
    mW += w; mL += l; mP += p;
    // Book may be absent for a day (no posted lines) — skip its sides/h2h then.
    const [bw, bl, bp] = parseSides(g.summary.book?.sides);
    bW += bw; bL += bl; bP += bp;
    const h2h = g.summary.headToHead;
    if (h2h) {
      weOnly += h2h.we_only;
      bookOnly += h2h.book_only;
      bothRight += h2h.both_right;
      bothWrong += h2h.both_wrong;
    }
    for (const game of g.games) {
      modelErrs.push(Math.abs(game.modelTotal - game.actualTotal));
      if (game.bookTotal != null) bookErrs.push(Math.abs(game.bookTotal - game.actualTotal));
    }
  }

  const modelMae = modelErrs.length ? modelErrs.reduce((a, b) => a + b, 0) / modelErrs.length : 0;
  const bookMae = bookErrs.length ? bookErrs.reduce((a, b) => a + b, 0) / bookErrs.length : 0;
  const nGames = modelErrs.length;

  return (
    <main className="max-w-6xl mx-auto p-6 md:p-10">
      <header className="mb-8">
        <div className="flex items-baseline justify-between">
          <h1 className="text-3xl font-semibold tracking-tight">
            NPBSide <span className="text-amber-500">/</span> Results
          </h1>
          <Link href="/" className="font-mono text-xs text-amber-500/80 hover:text-amber-500">← Board</Link>
        </div>
        <p className="text-sm text-white/60 mt-1 font-mono">
          Our originated lines vs the book&apos;s posted lines, graded against actuals · {grades.length} day{grades.length === 1 ? "" : "s"} · {nGames} games
        </p>
      </header>

      {/* Rolling scorecard */}
      <section className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-8">
        <div className="rounded-2xl p-5 bg-[#1a2235]/60 border border-white/5">
          <div className="text-[10px] uppercase text-white/40 font-mono tracking-wider">Model — sides</div>
          <div className="font-mono text-2xl text-amber-500 mt-1">{mW}-{mL}{mP ? `-${mP}` : ""}</div>
          <div className="font-mono text-[11px] text-white/40 mt-1">{winPct(mW, mL).toFixed(1)}% win</div>
        </div>
        <div className="rounded-2xl p-5 bg-[#1a2235]/60 border border-white/5">
          <div className="text-[10px] uppercase text-white/40 font-mono tracking-wider">Book — sides</div>
          <div className="font-mono text-2xl text-white/80 mt-1">{bW}-{bL}{bP ? `-${bP}` : ""}</div>
          <div className="font-mono text-[11px] text-white/40 mt-1">{winPct(bW, bL).toFixed(1)}% win</div>
        </div>
        <div className="rounded-2xl p-5 bg-[#1a2235]/60 border border-white/5">
          <div className="text-[10px] uppercase text-white/40 font-mono tracking-wider">Totals MAE (r/g)</div>
          <div className="font-mono text-2xl mt-1">
            <span className={modelMae <= bookMae ? "text-green-500" : "text-amber-500"}>{modelMae.toFixed(2)}</span>
            <span className="text-white/30 text-base"> vs {bookMae.toFixed(2)}</span>
          </div>
          <div className="font-mono text-[11px] text-white/40 mt-1">ours vs book · lower = sharper</div>
        </div>
        <div className="rounded-2xl p-5 bg-[#1a2235]/60 border border-white/5">
          <div className="text-[10px] uppercase text-white/40 font-mono tracking-wider">Head-to-head</div>
          <div className="font-mono text-sm mt-2 leading-relaxed">
            <div><span className="text-green-500">we only {weOnly}</span> · <span className="text-red-400">book only {bookOnly}</span></div>
            <div className="text-white/50">both right {bothRight} · both wrong {bothWrong}</div>
          </div>
        </div>
      </section>

      <p className="text-[11px] text-white/40 font-mono mb-6 leading-relaxed">
        &quot;Sides&quot; = did the picked favorite win. &quot;Head-to-head&quot; counts only games where our favorite differs from the book&apos;s
        — <span className="text-green-500">we only</span> = our side won &amp; book&apos;s lost; <span className="text-red-400">book only</span> = the reverse.
        Disagreement games are the cleanest test of whether the model leads the book.
      </p>

      {/* Per-day breakdown */}
      <section className="space-y-3">
        {grades.map((g) => {
          const [w, l, p] = parseSides(g.summary.model.sides);
          const hasBook = !!g.summary.book;
          const [bw, bl] = parseSides(g.summary.book?.sides);
          const disagreements = g.games.filter((x) => x.bookFav && x.modelFav !== x.bookFav);
          return (
            <details key={g.date} className="rounded-2xl bg-[#1a2235]/60 border border-white/5 overflow-hidden group">
              <summary className="flex items-center justify-between gap-3 p-4 cursor-pointer list-none hover:bg-white/5">
                <div className="flex items-baseline gap-4 flex-wrap font-mono text-sm">
                  <span className="text-white/90">{g.date}</span>
                  <span className="text-white/50">{g.games.length} games</span>
                  <span>sides <span className="text-amber-500">{w}-{l}{p ? `-${p}` : ""}</span> <span className="text-white/30">· book {hasBook ? `${bw}-${bl}` : "n/a"}</span></span>
                  <span className="text-white/50">MAE {g.summary.model.totalMaeR.toFixed(2)}r</span>
                  {disagreements.length > 0 && (
                    <span className="text-amber-400/80">{disagreements.length} disagreement{disagreements.length === 1 ? "" : "s"}</span>
                  )}
                </div>
                <span className="text-white/30 text-xs font-mono group-open:rotate-90 transition">▸</span>
              </summary>
              <div className="px-4 pb-4 overflow-x-auto">
                <table className="w-full text-sm font-mono border-collapse">
                  <thead>
                    <tr className="text-[10px] uppercase text-white/40 tracking-wider text-left border-b border-white/10">
                      <th className="py-2 pr-3 font-normal">Matchup</th>
                      <th className="py-2 px-2 font-normal">Final</th>
                      <th className="py-2 px-2 font-normal">Our fav</th>
                      <th className="py-2 px-2 font-normal text-center">Side</th>
                      <th className="py-2 px-2 font-normal text-right">Our T</th>
                      <th className="py-2 px-2 font-normal">Book fav</th>
                      <th className="py-2 px-2 font-normal text-center">Bk side</th>
                      <th className="py-2 px-2 font-normal text-right">Bk T</th>
                    </tr>
                  </thead>
                  <tbody>
                    {g.games.map((x, i) => {
                      const disagree = x.bookFav && x.modelFav !== x.bookFav;
                      return (
                        <tr key={i} className={`border-b border-white/5 ${disagree ? "bg-amber-500/5" : ""}`}>
                          <td className="py-2 pr-3 text-white/70">{x.matchup}</td>
                          <td className="py-2 px-2 text-white/60">{x.actual}</td>
                          <td className="py-2 px-2">{x.modelFav} <span className="text-white/40">{fmtML(x.modelFavMl)}</span></td>
                          <td className="py-2 px-2 text-center"><ResultCell r={x.sideResult} /></td>
                          <td className="py-2 px-2 text-right text-white/60">{x.modelTotal.toFixed(1)}</td>
                          <td className="py-2 px-2">{x.bookFav ?? "—"} <span className="text-white/40">{fmtML(x.bookFavMl)}</span></td>
                          <td className="py-2 px-2 text-center"><ResultCell r={x.bookSideResult} /></td>
                          <td className="py-2 px-2 text-right text-white/60">{x.bookTotal != null ? x.bookTotal.toFixed(1) : "—"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                <div className="text-[11px] text-white/40 mt-2">Highlighted rows = our favorite differs from the book&apos;s.</div>
              </div>
            </details>
          );
        })}
      </section>
    </main>
  );
}
