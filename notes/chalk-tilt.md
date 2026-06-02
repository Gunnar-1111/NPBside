# NPB chalk-tilt — analysis & fixes

The model ran structurally **chalkier than the book on favorites**. Tracked via
`data/chalk-tilt-ledger.json` (built by `scripts/build-chalk-ledger.py` from
graded slates). Two large-sample corpus fixes addressed most of it; two pieces
remain open.

## SHIPPED — HCA recalibration (5/29, commit 84da93e)
`HCA_RUNS` was a 0.30 plan-number; empirical home−away run diff over the 2024-25
corpus (n=1753) is **+0.113**. Lowered 0.30 → **0.11**. A/B over 5/24-30: home-fav
chalk gap vs book **+3.5pp → +0.9pp**, side flips unchanged. Large-sample
derivation, so no n≥20 forward-ledger gate needed.

## SHIPPED — WIN_DIVISOR recalibration (6/2, commit 175680c)
`WIN_DIVISOR` was **2.9** — a "calibrate later" placeholder, never derived. It was
**~2× too steep** and the DOMINANT cause of the chalk-tilt.

Derived **5.4** via logistic fit of team-season run-margin vs win% over the
2024-26 corpus (24 team-seasons): grid-search 5.4, logit-regression 5.38.
Re-derive any time:
```
python3 - <<'PY'
import json, glob, math, os
from collections import defaultdict
agg=defaultdict(lambda:{'g':0,'w':0,'rs':0,'ra':0})
for f in glob.glob('data/boxscores/*.json'):
    s=os.path.basename(f)[:4]; d=json.load(open(f))
    for g in d.get('games',[]):
        if g.get('status')!='final': continue
        ar=g['away'].get('runs'); hr=g['home'].get('runs')
        if ar is None or hr is None: continue
        for t,rs,ra in [(g['away']['team'],ar,hr),(g['home']['team'],hr,ar)]:
            k=(t,s); agg[k]['g']+=1; agg[k]['rs']+=rs; agg[k]['ra']+=ra
            if rs>ra: agg[k]['w']+=1
pts=[((v['rs']-v['ra'])/v['g'], v['w']/v['g']) for v in agg.values()
     if v['g']>=40 and 0.02<v['w']/v['g']<0.98]
sx2=sum(m*m for m,w in pts); sxy=sum(m*math.log10(w/(1-w)) for m,w in pts)
print('WIN_DIVISOR ≈', round(1/(sxy/sx2),2))
PY
```
On 6/3 the fix dropped heavy-favorite gaps vs the book from **+12-16pp → +4-7pp**
(H@D went to an exact match). A divisor change is MONOTONIC — it cannot flip
favorites or change side picks, only flatten over-heavy magnitudes (zero
side-accuracy risk).

NOTE: an earlier HCA-only "calibration check" (run-diff 0.11 → ~52%) wrongly
concluded 2.9 was fine — that run-diff is far too small to discriminate the
divisor. The team-season fit (a full margin range) is the correct method.

## STILL OPEN
1. **Residual chalk (~+4-7pp on heavy favorites)** = run-diff / SP-spread
   inflation (elite-vs-weak SP matchups producing too-large expected run-diffs).
   The divisor can't fix this. Candidate: an SP-spread dampener — backtest first.
2. **Road-favorite flips** (e.g. 6/3 B@G, M@S) — model flips a road team to
   favorite over the book's home favorite. Separate from the divisor (sign, not
   magnitude). Same leak family as DugoutSide/KBOSide.

## Cross-engine note
KBOSide derived its WIN_DIVISOR correctly from the start (7.0; re-verified 6.9-6.92
on the current corpus). NPB was the only engine left with an un-derived divisor.
