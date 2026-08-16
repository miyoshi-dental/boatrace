#!/usr/bin/env python3
"""
joshi_teisu3.py - 女子戦エンジンの定数（力の指標を画面と揃えた版）

★前版の誤り(§4c同型): 力に fan.cN_win_rate（勝率＝着順点）を使い、
  それを1着率の全国平均(12.5%等)で割っていた。画面(DB.racers)は
  コース別「1着率(%)」を使うので、学習と画面で別物だった。
  結果、女子戦エンジンは最重要変数がほぼ効かない状態で学習されていた。
  この版は 100*cN_rank1/cN_entries（1着率）＋画面と同じ shrink に統一。

teisu.py と同じ役割: 定数の単一の出どころ。joshi2 で学習した専用エンジン
（全24場・風潮なし・物差し47.1%/回収85.1%）の係数と切片を
joshi_teisu.js として書き出す。GitHubに置き、女子戦モードのHTMLが読む。

書き出すもの:
  1着 係数16 + 切片144（コース×24会場）
  2着 係数13 + 切片30（1着コース×対象コース）
  3着 係数13 + 切片120（1着×2着×対象）
  標準化の基準 CM/CS（力）, CST（2着3着の力）, SD, NATR/NATA

★自己検証（§4jの教訓）
  書き出したJSを読み直してPython側で再現し、joshi2 と同じテストで
  同じ的中率が出るかを確認する。**一致しなければ何も出力しない。**
  許容: 的中率の差 0.05pt 以内（浮動小数の丸めぶん）

★学習範囲の注意
  joshi2 と同じくホールドアウト（テスト期間を除く）で学習した定数を出す。
  実運用ではテスト期間も含めて学習し直すべきだが、まずは物差しと同じ
  条件のものを載せて画面と突き合わせる（§4h: kirokuの回収が1〜3pt高く
  出るのと同じ構図。実運用版への切替は突き合わせ合格後に）。

使い方:
    python joshi_teisu3.py            joshi_teisu.js を書き出す(5分程度)
    python joshi_teisu3.py --quick    配管確認（数値は無効・出力もしない）
"""
import math
import random
import sqlite3
import statistics
import sys
import time
from datetime import date as ddate, timedelta

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass


def arg(k, d=None):
    return sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d


DB = arg('--db', 'boatrace.sqlite3')
SINCE = arg('--since')
BUFFER = int(arg('--buffer', 7))
QUICK = '--quick' in sys.argv
EPOCHS = 2 if QUICK else 14
NBOOT = 100 if QUICK else 1000
NPT = int(arg('--points', 8))
SHRINK, SHRINKA, SPREAD = 40.0, 60.0, 0.25
NATW = [55.4, 14.0, 12.5, 10.7, 5.9, 1.9]

con = sqlite3.connect(DB)
con.execute('PRAGMA temp_store=MEMORY')
con.execute('PRAGMA cache_size=-300000')
rows = lambda s, *a: con.execute(s, *a).fetchall()
bar = lambda c='=': print(c * 78)
sig = lambda z: 1.0 / (1.0 + math.exp(-max(-30, min(30, z))))
T0 = time.time()
def lap(m):
    print(f'  [{(time.time()-T0)/60:5.1f}分] {m}', flush=True)


bar()
print('  joshi_teisu3.py  力の指標を画面と揃えた版')
if QUICK:
    print('  ★★ --quick: 数値は無効 ★★')
bar()
try:
    rows('SELECT 1 FROM lag LIMIT 1')
except Exception:
    sys.exit('先に  python lagfix.py  を実行してください')

maxd = rows('SELECT MAX(date) FROM races')[0][0]
if SINCE is None:
    y, m, d = map(int, maxd.split('-'))
    SINCE = str(ddate(y, m, d) - timedelta(days=365))
y, m, d = map(int, SINCE.split('-'))
TRAIN_END = str(ddate(y, m, d) - timedelta(days=BUFFER))
print(f'''
  データの最新日     {maxd}
  学習               {TRAIN_END} より前
  捨てる（節またぎ） {TRAIN_END} 〜 {SINCE} の手前
  テスト             {SINCE} 以降
  ★風・潮は使わない（24場ぶんの対応表が無いため。joshi3/4で追加）
''')

NATR = [rows("""SELECT SUM(c{0}_rank1*1.0+c{0}_rank2*2.0+c{0}_rank3*3.0+c{0}_rank4*4.0
     +c{0}_rank5*5.0+c{0}_rank6*6.0)*1.0
  /NULLIF(SUM(c{0}_rank1+c{0}_rank2+c{0}_rank3+c{0}_rank4+c{0}_rank5+c{0}_rank6),0)
  FROM fan""".format(c))[0][0] for c in range(1, 7)]
NATA = rows("""SELECT SUM(""" + '+'.join(
    f'c{c}_rank{r}*{r}.0' for c in range(1, 7) for r in range(1, 7)) + """)*1.0
  /NULLIF(SUM(""" + '+'.join(
    f'c{c}_rank{r}' for c in range(1, 7) for r in range(1, 7)) + """),0) FROM fan""")[0][0]

lap('データを読み込み中（全24場）...')
con.execute('CREATE INDEX IF NOT EXISTS ix_fyt ON fan(year,term,toban)')
sql = """DROP TABLE IF EXISTS t_all;
CREATE TEMP TABLE t_all AS
SELECT r.venue, r.jcd, r.date, r.race_no, r.wind_spd ws, r.title,
  e.course, e.lane, e.rank, e.tenji, f.sex,
  b.motor2, b.local, b.grade, b.recent, f.avg_st,
  /* ★力の指標を画面(DB.racers)と揃える: コース別「1着率(%)」。
     以前は f.cN_win_rate(勝率=着順点)を使っており、1着率の全国平均(12.5等)で
     割っていたため、力がほぼ機能していなかった（§4cと同型の取り違え）。 */
  CASE e.course
    WHEN 1 THEN 100.0*f.c1_rank1/NULLIF(f.c1_entries,0)
    WHEN 2 THEN 100.0*f.c2_rank1/NULLIF(f.c2_entries,0)
    WHEN 3 THEN 100.0*f.c3_rank1/NULLIF(f.c3_entries,0)
    WHEN 4 THEN 100.0*f.c4_rank1/NULLIF(f.c4_entries,0)
    WHEN 5 THEN 100.0*f.c5_rank1/NULLIF(f.c5_entries,0)
    ELSE 100.0*f.c6_rank1/NULLIF(f.c6_entries,0) END cr,
  CASE e.course WHEN 1 THEN f.c1_entries WHEN 2 THEN f.c2_entries
    WHEN 3 THEN f.c3_entries WHEN 4 THEN f.c4_entries
    WHEN 5 THEN f.c5_entries ELSE f.c6_entries END ce,
"""
sql += ('  ' + '+'.join(f'f.c{c}_rank{r_}*{r_}.0' for c in range(1, 7)
                        for r_ in range(1, 7)) + ' asum,\n')
sql += ('  ' + '+'.join(f'f.c{c}_rank{r_}' for c in range(1, 7)
                        for r_ in range(1, 7)) + ' acnt,\n')
sql += ('  CASE e.course ' + ' '.join(
    'WHEN {0} THEN '.format(c) + '+'.join(f'f.c{c}_rank{r_}*{r_}.0'
                                          for r_ in range(1, 7))
    for c in range(1, 7)) + ' END s6,\n')
sql += ('  CASE e.course ' + ' '.join(
    'WHEN {0} THEN '.format(c) + '+'.join(f'f.c{c}_rank{r_}'
                                          for r_ in range(1, 7))
    for c in range(1, 7)) + ' END n6\n')
sql += """FROM races r
JOIN lag l ON l.date=r.date
JOIN entries e ON e.jcd=r.jcd AND e.date=r.date AND e.race_no=r.race_no
JOIN entries_b b ON b.jcd=r.jcd AND b.date=r.date AND b.race_no=r.race_no
                AND b.lane=e.lane
JOIN fan f ON f.year=l.year AND f.term=l.term AND f.toban=e.toban
WHERE e.course IS NOT NULL AND e.lane IS NOT NULL;"""
con.executescript(sql)
D = rows("""SELECT venue,jcd,date,race_no,ws,title,course,lane,rank,tenji,sex,
  motor2,local,grade,recent,avg_st,cr,ce,asum,acnt,s6,n6 FROM t_all""")
lap(f'{len(D):,} 出走')


def recent_avg(s):
    v = [int(x) for x in (s or '') if x in '123456']
    return sum(v) / len(v) if len(v) >= 3 else None


def norm_title(t):
    t = (t or '').replace(' ', '').replace('　', '')
    if '優勝戦' in t and '準' not in t:
        return '優勝戦'
    if '準優' in t:
        return '準優勝戦'
    if '選抜' in t or '特選' in t or '特賞' in t:
        return '選抜'
    return 'その他'


R = {}
for (v, jcd, dt, rn, ws, ti, c, ln, rk, tj, sex, m2, lo, gr, rec, ast,
     cr, ce, asum, acnt, s6, n6) in D:
    g = R.setdefault((jcd, dt, rn), {'v': v, 'dt': dt, 'ws': ws or 0,
                                     'ti': ti, 'b': []})
    n6_, na_ = (n6 or 0), (acnt or 0)
    ka = na_ / (na_ + SHRINKA)
    aavg = ka * ((asum or 0) / na_ if na_ else NATA) + (1 - ka) * NATA
    base = aavg + (NATR[c - 1] - NATA)
    kk = n6_ / (n6_ + SHRINK)
    avg = kk * ((s6 or 0) / n6_ if n6_ else base) + (1 - kk) * base
    g['b'].append({'c': c, 'ln': ln, 'rk': rk, 'tj': tj, 'sex': sex,
                   'm2': m2, 'lo': lo, 'gr': gr, 'rec': recent_avg(rec),
                   'ast': ast, 'cr': cr, 'ce': ce, 'avg': avg})

for k, g in R.items():
    ok = [x for x in g['b'] if x['tj'] and x['tj'] > 0]
    if len(ok) == 6 and len(g['b']) == 6:
        so = sorted(g['b'], key=lambda z: z['tj'])
        for i, x in enumerate(so):
            x['tp'] = i + 1
    else:
        for x in g['b']:
            x['tp'] = None

JO, MX = {}, {}
for k, g in R.items():
    if len(g['b']) != 6 or len({x['c'] for x in g['b']}) != 6:
        continue
    if not all(x['rk'] is not None for x in g['b']):
        continue
    if all(x['sex'] == 2 for x in g['b']):
        JO[k] = g
    elif all(x['sex'] == 1 for x in g['b']):
        MX[k] = g

JTR = {k: g for k, g in JO.items() if g['dt'] < TRAIN_END}
JTE = {k: g for k, g in JO.items() if g['dt'] >= SINCE}
MTR = {k: g for k, g in MX.items() if g['dt'] < TRAIN_END}
lap(f'女子戦 学習{len(JTR):,} / テスト{len(JTE):,}　男子のみ 学習{len(MTR):,}')
if len(JTR) < 5000 or len(JTE) < 500:
    sys.exit('女子戦のレース数が足りません。--since を確認してください。')

# ---- 特徴量 ----
FEAT1 = ['力', '当地', 'モーター', 'ﾓｰﾀ欠損', '平均ST', '今節', 'A1', 'A2', 'B1',
         '押出', '展示T順位', '展示T欠損', '準優勝戦', '優勝戦', '選抜', '風強い']
K1 = len(FEAT1)
FEAT23 = ['力', '当地', 'モーター', 'ﾓｰﾀ欠損', '平均ST', '今節', 'A1', 'A2', 'B1',
          '展示T順位', '展示T欠損', '押出', '風強い']
K23 = len(FEAT23)


def build_x1(x, g, CM, CS):
    c = x['c']
    t = norm_title(g['ti'])
    mo = 1.0 if (x['m2'] is None or x['m2'] <= 0) else 0.0
    m2v = 34.0 if mo else x['m2']
    lov = 5.3 if (x['lo'] is None or x['lo'] <= 0) else x['lo']
    crv = x['cr'] if x['cr'] is not None else NATW[c - 1]
    # 画面の shrink と同一: 1.0+(1着率/全国平均-1)*min(1,出走/15)
    w = min(1.0, (x['ce'] or 0) / 15.0)
    rel = 1.0 + ((crv / NATW[c - 1]) - 1.0) * w if x['ce'] else 1.0
    return [
        (rel - CM[c]) / CS[c],
        (lov - 5.3) / 1.5,
        (m2v - 34.0) / 12.0,
        mo,
        -((x['ast'] if x['ast'] is not None else 0.166) - 0.166) / 0.020,
        -((x['rec'] if x['rec'] is not None else 3.4) - 3.4) / 1.0,
        1.0 if x['gr'] == 'A1' else 0.0,
        1.0 if x['gr'] == 'A2' else 0.0,
        1.0 if x['gr'] == 'B1' else 0.0,
        1.0 if c > x['ln'] else 0.0,
        0.0 if x['tp'] is None else (3.5 - x['tp']) / 2.5,
        1.0 if x['tp'] is None else 0.0,
        1.0 if t == '準優勝戦' else 0.0,
        1.0 if t == '優勝戦' else 0.0,
        1.0 if t == '選抜' else 0.0,
        1.0 if g['ws'] >= 4 else 0.0,
    ]


def build_x23(x, g, CST):
    c = x['c']
    mo = 1.0 if (x['m2'] is None or x['m2'] <= 0) else 0.0
    m2v = 34.0 if mo else x['m2']
    lov = 5.3 if (x['lo'] is None or x['lo'] <= 0) else x['lo']
    return [
        (x['p'] - CST[c - 1][0]) / CST[c - 1][1],
        (lov - 5.3) / 1.5,
        (m2v - 34.0) / 12.0,
        mo,
        -((x['ast'] if x['ast'] is not None else 0.166) - 0.166) / 0.020,
        -((x['rec'] if x['rec'] is not None else 3.4) - 3.4) / 1.0,
        1.0 if x['gr'] == 'A1' else 0.0,
        1.0 if x['gr'] == 'A2' else 0.0,
        1.0 if x['gr'] == 'B1' else 0.0,
        0.0 if x['tp'] is None else (3.5 - x['tp']) / 2.5,
        1.0 if x['tp'] is None else 0.0,
        1.0 if x['ln'] < x['c'] else 0.0,
        1.0 if g['ws'] >= 4 else 0.0,
    ]


def train_sgd(X, Y, KEY, k, label):
    n = len(X)
    keys = sorted(set(KEY))
    kidx = {kk: i for i, kk in enumerate(keys)}
    w = [0.0] * k
    b = [0.0] * len(keys)
    cnt = [0] * len(keys)
    pos = [0] * len(keys)
    for i in range(n):
        j = kidx[KEY[i]]
        cnt[j] += 1
        pos[j] += Y[i]
    for j in range(len(keys)):
        p = max(0.01, min(0.99, pos[j] / max(1, cnt[j])))
        b[j] = math.log(p / (1 - p))
    print(f'  {label}: {n:,}件 / 変数{k} / 切片{len(keys)} 学習中',
          end='', flush=True)
    lr, BS = 0.35, 8192
    idx = list(range(n))
    rnd = random.Random(42)
    for ep in range(EPOCHS):
        rnd.shuffle(idx)
        for s in range(0, n, BS):
            batch = idx[s:s + BS]
            gw = [0.0] * k
            gb = {}
            for i in batch:
                xi = X[i]
                j = kidx[KEY[i]]
                z = b[j] + sum(w[t] * xi[t] for t in range(k))
                e = sig(z) - Y[i]
                for t in range(k):
                    gw[t] += e * xi[t]
                gb[j] = gb.get(j, 0.0) + e
            m = len(batch)
            for t in range(k):
                w[t] -= lr * gw[t] / m
            for j, gr in gb.items():
                b[j] -= lr * gr / m
        print('.', end='', flush=True)
    ll = ll0 = 0.0
    bp = sum(Y) / n
    for i in range(n):
        z = b[kidx[KEY[i]]] + sum(w[t] * X[i][t] for t in range(k))
        p = max(1e-9, min(1 - 1e-9, sig(z)))
        ll += Y[i] * math.log(p) + (1 - Y[i]) * math.log(1 - p)
        ll0 += Y[i] * math.log(bp) + (1 - Y[i]) * math.log(1 - bp)
    r2 = 1 - ll / ll0
    print(f' 完了 疑似R2 {r2:.4f}')
    return w, b, kidx, r2


def fit_all(TRAIN, tag):
    """1着/2着/3着の3モデルを学習して返す"""
    POOL = {}
    for g in TRAIN.values():
        for x in g['b']:
            if x['ce'] and x['cr'] is not None:
                w = min(1.0, x['ce'] / 15.0)
                POOL.setdefault(x['c'], []).append(
                    1.0 + ((x['cr'] / NATW[x['c'] - 1]) - 1.0) * w)
    CM = {c: statistics.mean(v) for c, v in POOL.items()}
    CS = {c: (statistics.pstdev(v) or 1.0) for c, v in POOL.items()}
    X1, Y1, KEY1 = [], [], []
    for g in TRAIN.values():
        for x in g['b']:
            X1.append(build_x1(x, g, CM, CS))
            Y1.append(1.0 if x['rk'] == 1 else 0.0)
            KEY1.append((x['c'], g['v']))
    W1, B1, KX1, r2_1 = train_sgd(X1, Y1, KEY1, K1, f'{tag} 1着')
    SD = []
    for c in range(1, 7):
        xs = [x['avg'] for g in TRAIN.values() for x in g['b'] if x['c'] == c]
        m = sum(xs) / len(xs)
        SD.append((sum((y - m) ** 2 for y in xs) / len(xs)) ** 0.5)

    def set_power(g):
        for x in g['b']:
            x['p'] = 1.0 + (NATR[x['c'] - 1] - x['avg']) / SD[x['c'] - 1] * SPREAD

    for g in TRAIN.values():
        set_power(g)
    CST = []
    for c in range(1, 7):
        xs = [x['p'] for g in TRAIN.values() for x in g['b'] if x['c'] == c]
        m = sum(xs) / len(xs)
        sd = (sum((y - m) ** 2 for y in xs) / len(xs)) ** 0.5
        CST.append((m, sd))
    X2, Y2, KEY2, X3, Y3, KEY3 = [], [], [], [], [], []
    for g in TRAIN.values():
        w1 = next((x['c'] for x in g['b'] if x['rk'] == 1), None)
        s1 = next((x['c'] for x in g['b'] if x['rk'] == 2), None)
        if not w1:
            continue
        for x in g['b']:
            if x['c'] == w1:
                continue
            xv = build_x23(x, g, CST)
            X2.append(xv)
            Y2.append(1 if x['rk'] == 2 else 0)
            KEY2.append((w1, x['c']))
            if s1 and x['c'] != s1:
                X3.append(xv)
                Y3.append(1 if x['rk'] == 3 else 0)
                KEY3.append((w1, s1, x['c']))
    W2, B2, KX2, r2_2 = train_sgd(X2, Y2, KEY2, K23, f'{tag} 2着')
    W3, B3, KX3, r2_3 = train_sgd(X3, Y3, KEY3, K23, f'{tag} 3着')
    return dict(CM=CM, CS=CS, SD=SD, CST=CST, W1=W1, B1=B1, KX1=KX1,
                W2=W2, B2=B2, KX2=KX2, W3=W3, B3=B3, KX3=KX3,
                r2=(r2_1, r2_2, r2_3), set_power=set_power)


bar()
print('  学習（テスト期間は一切使わない）')
bar()
MJ = fit_all(JTR, '女子')
lap('女子戦エンジン完了')



def combos120(M, g):
    """1着/2着/3着モデル → 120通りの確率（joshi2と同一）"""
    M['set_power'](g)
    bm = {x['c']: x for x in g['b']}
    p1 = []
    for c in range(1, 7):
        j = M['KX1'].get((c, g['v']))
        xv = build_x1(bm[c], g, M['CM'], M['CS'])
        z = (M['B1'][j] if j is not None else 0.0) + sum(
            M['W1'][t] * xv[t] for t in range(K1))
        p1.append(sig(z))
    tot = sum(p1) or 1.0
    p1 = [x / tot for x in p1]
    z23 = {}
    for c in range(1, 7):
        xv = build_x23(bm[c], g, M['CST'])
        z23[c] = (sum(M['W2'][t] * xv[t] for t in range(K23)),
                  sum(M['W3'][t] * xv[t] for t in range(K23)))
    prob = {}
    for a in range(1, 7):
        rest = [c for c in range(1, 7) if c != a]
        p2 = {}
        for c in rest:
            j = M['KX2'].get((a, c))
            p2[c] = sig((M['B2'][j] if j is not None else 0.0) + z23[c][0])
        t2 = sum(p2.values()) or 1.0
        for b2 in rest:
            r3 = [c for c in rest if c != b2]
            p3 = {}
            for c in r3:
                j = M['KX3'].get((a, b2, c))
                p3[c] = sig((M['B3'][j] if j is not None else 0.0) + z23[c][1])
            t3 = sum(p3.values()) or 1.0
            for c in r3:
                prob[(a, b2, c)] = p1[a - 1] * (p2[b2] / t2) * (p3[c] / t3)
    return p1, prob


def hitrate(M):
    """テスト期間の8点的中率（joshi2のG3と同じ計算）"""
    n = h = 0
    for k, g in JTE.items():
        r1 = next((x['c'] for x in g['b'] if x['rk'] == 1), None)
        r2_ = next((x['c'] for x in g['b'] if x['rk'] == 2), None)
        r3 = next((x['c'] for x in g['b'] if x['rk'] == 3), None)
        if not (r1 and r2_ and r3) or len({r1, r2_, r3}) != 3:
            continue
        _, pb = combos120(M, g)
        buy = {cb for cb, _ in sorted(pb.items(), key=lambda z: -z[1])[:NPT]}
        n += 1
        h += 1 if (r1, r2_, r3) in buy else 0
    return 100 * h / n, n


bar()
print('  1) 学習した定数でのテスト的中率（基準値）')
bar()
base_hit, ntest = hitrate(MJ)
print(f'  {NPT}点の的中率 {base_hit:.2f}%  （テスト {ntest:,} レース）')

# ---- JS を組み立て ----
VJ = sorted({g['v'] for g in JTR.values()})
f = lambda x: f'{x:.6g}'
js = []
js.append('/* joshi_teisu.js  女子戦エンジンの定数')
js.append(f'   出どころ: joshi_teisu.py（joshi2と同一の学習）')
js.append(f'   学習: {TRAIN_END} より前の女子戦 {len(JTR):,} レース（全24場）')
js.append(f'   テスト: {SINCE} 以降 {ntest:,} レース → {NPT}点の的中率 '
          f'{base_hit:.2f}%')
js.append('   風・潮の補正は入っていない（24場ぶんの対応表が無いため）')
js.append('   ★この値を手で書き換えないこと。変えるときは joshi_teisu.py を回す */')
js.append('const JOSHI = {')
js.append(f'  "meta": {{"hit": {base_hit:.2f}, "points": {NPT}, '
          f'"races": {len(JTR)}, "test": {ntest}, "wind": false, "tide": false}},')
js.append(f'  "NATR": [{", ".join(f(x) for x in NATR)}],')
js.append(f'  "NATA": {f(NATA)},')
js.append(f'  "SD": [{", ".join(f(x) for x in MJ["SD"])}],')
js.append('  "CM": {' + ', '.join(f'"{c}": {f(MJ["CM"][c])}'
                                  for c in sorted(MJ['CM'])) + '},')
js.append('  "CS": {' + ', '.join(f'"{c}": {f(MJ["CS"][c])}'
                                  for c in sorted(MJ['CS'])) + '},')
js.append('  "CST": [' + ', '.join(f'[{f(a)}, {f(b)}]'
                                   for a, b in MJ['CST']) + '],')
js.append(f'  "FEAT1": [{", ".join(chr(34)+x+chr(34) for x in FEAT1)}],')
js.append(f'  "W1": [{", ".join(f(x) for x in MJ["W1"])}],')
js.append(f'  "FEAT23": [{", ".join(chr(34)+x+chr(34) for x in FEAT23)}],')
js.append(f'  "W2": [{", ".join(f(x) for x in MJ["W2"])}],')
js.append(f'  "W3": [{", ".join(f(x) for x in MJ["W3"])}],')

# 女子戦の power（平均着順ベースの力・選手×コース）
# ★これが要る理由(§4c): 画面は2着3着の力に power.txt を使うが、それは
#   6会場ぶんの男女混合データ。学習時と意味が違う力を渡すと、rel→p23 の
#   取り違えと同じ事故になる。学習で使ったのと同一定義の値を同梱する。
#     avg = そのコースでの平均着順(縮めて全国平均に寄せたもの)
#     p   = 1.0 + (NATR[c] - avg) / SD[c] * SPREAD
LY, LT = rows('SELECT year, term FROM lag ORDER BY date DESC LIMIT 1')[0]
FEMROWS = rows('''SELECT toban,''' + ','.join(
    '+'.join(f'c{c}_rank{r_}*{r_}.0' for r_ in range(1, 7)) + f' s{c},' +
    '+'.join(f'c{c}_rank{r_}' for r_ in range(1, 7)) + f' n{c}'
    for c in range(1, 7)) + ''',''' + '+'.join(
    f'c{c}_rank{r_}*{r_}.0' for c in range(1, 7) for r_ in range(1, 7)
) + ''' asum,''' + '+'.join(
    f'c{c}_rank{r_}' for c in range(1, 7) for r_ in range(1, 7)
) + ''' acnt
  FROM fan WHERE sex=2 AND year=? AND term=?''', (LY, LT))
POWER = {}
for row in FEMROWS:
    toban = row[0]
    asum, acnt = row[13], row[14]
    na = acnt or 0
    ka = na / (na + SHRINKA)
    aavg = ka * ((asum or 0) / na if na else NATA) + (1 - ka) * NATA
    vals = []
    for c in range(1, 7):
        s6, n6 = row[1 + (c - 1) * 2], row[2 + (c - 1) * 2]
        base = aavg + (NATR[c - 1] - NATA)
        n6_ = n6 or 0
        kk = n6_ / (n6_ + SHRINK)
        avg = kk * ((s6 or 0) / n6_ if n6_ else base) + (1 - kk) * base
        vals.append(round(1.0 + (NATR[c - 1] - avg) / MJ['SD'][c - 1] * SPREAD, 3))
    POWER[toban] = vals
print(f'  女子戦power {len(POWER):,} 人ぶん（学習と同一定義・{LY}年{LT}期）')
js.append(f'  "powerTerm": "{LY}年{LT}期",')
js.append('  "power": {' + ','.join(
    f'"{t}":[' + ','.join(str(x) for x in v) + ']'
    for t, v in sorted(POWER.items())) + '},')

# 女性の登番リスト（画面の自動判定用。最新期のfanから）
FY, FT = LY, LT      # powerと同じ期に揃える（lag基準・先読み防止）
FEM = sorted(r[0] for r in rows(
    'SELECT DISTINCT toban FROM fan WHERE sex=2 AND year=? AND term=?',
    (FY, FT)))
print(f'  女性登番 {len(FEM):,} 人（{FY}年{FT}期・自動判定用）')
js.append(f'  "femaleTerm": "{FY}年{FT}期",')
js.append('  "female": [' + ','.join(str(x) for x in FEM) + '],')

def dump_b(kx, b, key2str, label):
    items = []
    for k, j in sorted(kx.items(), key=lambda z: str(z[0])):
        items.append(f'"{key2str(k)}": {f(b[j])}')
    js.append(f'  "{label}": {{' + ', '.join(items) + '},')

dump_b(MJ['KX1'], MJ['B1'], lambda k: f'{k[0]}|{k[1]}', 'B1')
dump_b(MJ['KX2'], MJ['B2'], lambda k: f'{k[0]}-{k[1]}', 'B2')
dump_b(MJ['KX3'], MJ['B3'], lambda k: f'{k[0]}-{k[1]}-{k[2]}', 'B3')
if js[-1].endswith(','):
    js[-1] = js[-1][:-1]          # JSONで読めるよう末尾カンマを外す
js.append('};')
text = '\n'.join(js) + '\n'

# ---- 自己検証: 書いたJSを読み直して再現 ----
bar()
print('  2) 自己検証（書き出した定数を読み直して同じ結果が出るか）')
bar()
import json
import re as _re


def js_to_model(txt):
    """joshi_teisu.js を読み直して MJ 相当の dict を作る"""
    body = txt[txt.index('const JOSHI = {') + len('const JOSHI = '):]
    body = body.rstrip().rstrip(';')
    # JSのキーは全部クォート済み・値は数値/配列/辞書なのでJSONで読める
    obj = json.loads(body)
    CM = {int(k): v for k, v in obj['CM'].items()}
    CS = {int(k): v for k, v in obj['CS'].items()}
    B1d = obj['B1']
    KX1 = {}
    B1 = []
    for i, (k, v) in enumerate(B1d.items()):
        c, ven = k.split('|')
        KX1[(int(c), ven)] = i
        B1.append(v)
    KX2, B2 = {}, []
    for i, (k, v) in enumerate(obj['B2'].items()):
        a, b = k.split('-')
        KX2[(int(a), int(b))] = i
        B2.append(v)
    KX3, B3 = {}, []
    for i, (k, v) in enumerate(obj['B3'].items()):
        a, b, c = k.split('-')
        KX3[(int(a), int(b), int(c))] = i
        B3.append(v)
    SD2 = obj['SD']

    def set_power2(g):
        for x in g['b']:
            x['p'] = 1.0 + (obj['NATR'][x['c'] - 1] - x['avg']) \
                / SD2[x['c'] - 1] * SPREAD

    return dict(CM=CM, CS=CS, SD=SD2, CST=[tuple(x) for x in obj['CST']],
                W1=obj['W1'], B1=B1, KX1=KX1,
                W2=obj['W2'], B2=B2, KX2=KX2,
                W3=obj['W3'], B3=B3, KX3=KX3, set_power=set_power2)


M2 = js_to_model(text)
re_hit, _ = hitrate(M2)
diff = abs(re_hit - base_hit)
print(f'  学習した定数     {base_hit:.4f}%')
print(f'  書き出しを読み直し {re_hit:.4f}%   差 {diff:.4f}pt')
if diff > 0.05:
    bar()
    sys.exit('  ★一致しません。定数を書き出さずに終了します。'
             '（書式か読み直しの不備）')
print('  ★一致（差 0.05pt 以内）')

OUT = 'joshi_teisu.js'
with open(OUT, 'w', encoding='utf-8') as fp:
    fp.write(text)
import os
bar()
print(f'  3) 書き出しました → {OUT}  ({os.path.getsize(OUT):,} バイト)')
bar()
print(f"""
  中身: 1着 係数{K1}+切片{len(MJ['B1'])} / 2着 係数{K23}+切片{len(MJ['B2'])}
        / 3着 係数{K23}+切片{len(MJ['B3'])}
        女性登番 {len(FEM):,} 人（{FY}年{FT}期・画面の自動判定用）
  物差し: {NPT}点の的中率 {base_hit:.2f}%（風・潮なし・ホールドアウト）

  次にやること
    1 joshi_teisu.js を GitHub Pages のリポジトリに置く（nita/ と同じ場所）
    2 女子戦モードのHTMLがこれを読んで120通りを計算する（段階3のUI）
    3 画面ができたら --check 相当で突き合わせる（§4j）。
      定数の出どころはこのファイル1つに保つ（手で書き換えない）

  ※出力ファイル名は joshi_teisu.js のまま（画面が読む名前）
""")
bar()
