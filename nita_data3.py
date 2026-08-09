#!/usr/bin/env python3
"""
似たレース検索のデータを会場別に書き出す

nita.py と同じ計算をブラウザでやるためのデータを作る。
8.7万レースを全部スマホに置くのは重いので、会場ごとに分ける。
使うのは1会場だけなので、実際に読むのは1.5万レース分だけで済む。

1レースの中身（36進数の固定長）:
  力6個    各2文字   0.00〜1.99 を100倍して整数に
  隊形     1文字     0=枠なり 1=前づけ1つ 2=前づけ2つ以上
  風速     1文字     0〜35m
  風向     1文字     0=無風 1〜8=方位
  着順     3文字     1〜6のコース番号
                     計 18文字 = 18バイト

  1.5万レース × 18バイト ≒ 270KB。gzipで100KB前後に落ちる。

力の作り方は nita.py と同じ:
  平均着順を、出走の少ないぶんだけ選手の実力へ寄せ、
  さらに全国平均へ寄せる。標準偏差で割って幅を揃える。
  1着率ではなく平均着順を使うので、同じ出走回数でも情報量が6倍ある。

必要:
  python lagfix.py

使い方:
    python nita_data.py                 docs/nita/ に書き出す
    python nita_data.py --out ./out
"""
import os
import sqlite3
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass


def arg(k, d=None):
    return sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d


DB = arg('--db', 'boatrace.sqlite3')
OUT = arg('--out', 'docs/nita')
VENUES = {'戸田': 'toda', '江戸川': 'edogawa', '鳴門': 'naruto',
          '唐津': 'karatsu', '桐生': 'kiryu', '丸亀': 'marugame'}
SHRINK, SHRINKA, SPREAD = 40.0, 60.0, 0.25

# 風向を1文字に（DBの表記→番号）
WD = {'': 0, '無風': 0, '北': 1, '北東': 2, '東': 3, '南東': 4,
      '南': 5, '南西': 6, '西': 7, '北西': 8}

D36 = '0123456789abcdefghijklmnopqrstuvwxyz'
enc1 = lambda n: D36[max(0, min(35, int(n)))]
enc2 = lambda n: D36[max(0, min(1295, int(n))) // 36] + D36[max(0, min(1295, int(n))) % 36]

con = sqlite3.connect(DB)
con.execute('PRAGMA temp_store=MEMORY')
con.execute('PRAGMA cache_size=-300000')
rows = lambda s, *a: con.execute(s, *a).fetchall()
bar = lambda c='=': print(c * 70)

bar()
print('  似たレース検索のデータを書き出す')
bar()
try:
    rows('SELECT 1 FROM lag LIMIT 1')
except Exception:
    sys.exit('先に  python lagfix.py  を実行してください')

con.execute('CREATE INDEX IF NOT EXISTS ix_fyt ON fan(year,term,toban)')
NAT = [rows("""SELECT SUM(c{0}_rank1*1.0+c{0}_rank2*2.0+c{0}_rank3*3.0+c{0}_rank4*4.0
     +c{0}_rank5*5.0+c{0}_rank6*6.0)*1.0
  /NULLIF(SUM(c{0}_rank1+c{0}_rank2+c{0}_rank3+c{0}_rank4+c{0}_rank5+c{0}_rank6),0)
  FROM fan""".format(c))[0][0] for c in range(1, 7)]
NATA = rows("""SELECT SUM(""" + '+'.join(
    f'c{c}_rank{r}*{r}.0' for c in range(1, 7) for r in range(1, 7)) + """)*1.0
  /NULLIF(SUM(""" + '+'.join(
    f'c{c}_rank{r}' for c in range(1, 7) for r in range(1, 7)) + """),0) FROM fan""")[0][0]
print(f'  ※ 1つ前の期のデータを使用（先読みなし）')
print(f'  全国の平均着順 ' + ' '.join(f'{c+1}ｺ{NAT[c]:.2f}' for c in range(6)))
print('集計中...\n')

VL = ','.join(f"'{v}'" for v in VENUES)
sql = """DROP TABLE IF EXISTS z_e;
CREATE TEMP TABLE z_e AS
SELECT r.venue, r.jcd, r.date, r.race_no, r.wind_spd, r.wind_dir,
  e.course, e.lane, e.rank,
"""
for r_ in range(1, 7):
    sql += ('  CASE e.course ' + ' '.join(
        f'WHEN {c} THEN f.c{c}_rank{r_}' for c in range(1, 7)) + f' END k{r_},\n')
sql += ('  ' + '+'.join(f'f.c{c}_rank{r_}*{r_}.0'
                        for c in range(1, 7) for r_ in range(1, 7)) + ' asum,\n')
sql += ('  ' + '+'.join(f'f.c{c}_rank{r_}'
                        for c in range(1, 7) for r_ in range(1, 7)) + ' acnt\n')
sql += f"""FROM races r
JOIN lag l ON l.date=r.date
JOIN entries e ON e.jcd=r.jcd AND e.date=r.date AND e.race_no=r.race_no
JOIN fan f ON f.year=l.year AND f.term=l.term AND f.toban=e.toban
WHERE e.course IS NOT NULL AND e.lane IS NOT NULL AND r.venue IN ({VL});

DROP TABLE IF EXISTS z_r;
CREATE TEMP TABLE z_r AS
SELECT venue, date, race_no, MAX(wind_spd) ws, MAX(wind_dir) wd,
  MAX(CASE WHEN rank=1 THEN course END) r1,
  MAX(CASE WHEN rank=2 THEN course END) r2,
  MAX(CASE WHEN rank=3 THEN course END) r3,
"""
for c in range(1, 7):
    sql += (f"  MAX(CASE WHEN course={c} THEN k1*1.0+k2*2.0+k3*3.0+k4*4.0+k5*5.0+k6*6.0 END) s{c},\n"
            f"  MAX(CASE WHEN course={c} THEN k1+k2+k3+k4+k5+k6 END) n{c},\n"
            f"  MAX(CASE WHEN course={c} THEN asum END) as{c},\n"
            f"  MAX(CASE WHEN course={c} THEN acnt END) an{c},\n")
sql += """  SUM(CASE WHEN lane<>course THEN 1 ELSE 0 END) mv,
  MAX(ABS(course-lane)) mx, COUNT(*) nb, MAX(jcd) jcd0, MAX(date) date0
FROM z_e GROUP BY jcd,date,race_no
HAVING r1 IS NOT NULL AND r2 IS NOT NULL AND r3 IS NOT NULL AND nb=6;
"""
con.executescript(sql)

cols = ','.join(f's{c},n{c},as{c},an{c}' for c in range(1, 7))
SRC = rows(f'''SELECT z.venue,z.date,z.race_no,z.ws,z.wd,z.r1,z.r2,z.r3,{cols},z.mv,z.mx,
  COALESCE(MIN(p.payout),0)
  FROM z_r z LEFT JOIN payouts p
    ON p.jcd=z.jcd0 AND p.date=z.date0 AND p.race_no=z.race_no AND p.bet='trifecta'
  GROUP BY z.jcd0,z.date0,z.race_no''')
print(f'対象 {len(SRC):,} レース')

# ---- 平均着順を寄せる ----
AVG = []
for d in SRC:
    a = []
    for c in range(6):
        s6, n6 = d[8 + c * 4], (d[9 + c * 4] or 0)
        sa, na = d[10 + c * 4], (d[11 + c * 4] or 0)
        ka = na / (na + SHRINKA)
        aavg = ka * ((sa or 0) / na if na else NATA) + (1 - ka) * NATA
        base = aavg + (NAT[c] - NATA)
        k = n6 / (n6 + SHRINK)
        a.append(k * ((s6 or 0) / n6 if n6 else base) + (1 - k) * base)
    AVG.append((d, a))

# ---- 標準偏差で幅を揃える ----
SD = []
for c in range(6):
    xs = [t[1][c] for t in AVG]
    m = sum(xs) / len(xs)
    SD.append((sum((x - m) ** 2 for x in xs) / len(xs)) ** 0.5)
print('  平均着順の散らばり ' + ' '.join(f'{c+1}ｺ{SD[c]:.2f}' for c in range(6)))

os.makedirs(OUT, exist_ok=True)
BY = {}
for d, a in AVG:
    p = [1.0 + (NAT[c] - a[c]) / SD[c] * SPREAD for c in range(6)]
    t = 0 if d[32] == 0 else (1 if d[33] == 1 else 2)
    ws = min(35, int(d[3] or 0))
    wd = WD.get((d[4] or '').strip(), 0)
    buf = ''.join(enc2(round(max(0.0, min(1.99, x)) * 100)) for x in p)
    buf += enc1(t) + enc1(ws) + enc1(wd)
    buf += str(d[5]) + str(d[6]) + str(d[7])
    # 配当を100円単位で2文字に。最大129,500円まで表せる
    buf += enc2(min(1295, (d[34] or 0) // 100))
    BY.setdefault(d[0], []).append(buf)

print()
print(f'  {"会場":<8}{"ﾚｰｽ数":>9}{"サイズ":>10}   ファイル')
total = 0
for v, en in VENUES.items():
    g = BY.get(v, [])
    if not g:
        continue
    # 先頭に基準値を書いておく（ブラウザ側で同じ物差しを使うため）
    head = ('#' + ','.join(f'{x:.4f}' for x in NAT) + '|'
            + ','.join(f'{x:.4f}' for x in SD) + f'|{SPREAD}\n')
    path = os.path.join(OUT, f'{en}.txt')
    with open(path, 'w', encoding='ascii', newline='\n') as f:
        f.write(head + '\n'.join(g))
    sz = os.path.getsize(path)
    total += sz
    print(f'  {v:<8}{len(g):>9,}{sz/1024:>9.0f}KB   {path}')
print(f'  {"合計":<8}{sum(len(v) for v in BY.values()):>9,}{total/1024:>9.0f}KB')

# ---- 選手ごとの力の表 ----
# ツールの DB.racers はコース別1着率しか持っていない。
# 似たレース検索は平均着順ベースなので、同じ物差しの力を別ファイルで配る。
# ここで作れば、レースデータと必ず同じ NAT / SD / SPREAD になる。
per = rows('SELECT MAX(year),MAX(term) FROM fan WHERE (year,term)='
           '(SELECT year,term FROM fan ORDER BY year DESC,term DESC LIMIT 1)')[0]
cols2 = ','.join(f'c{c}_rank{r}' for c in range(1, 7) for r in range(1, 7))
P = []
for row in rows(f'SELECT toban,{cols2} FROM fan WHERE year=? AND term=?', per):
    tb, v = row[0], row[1:]
    asum = sum(v[c * 6 + r] * (r + 1) for c in range(6) for r in range(6))
    acnt = sum(v)
    ka = acnt / (acnt + SHRINKA) if acnt else 0.0
    aavg = ka * (asum / acnt if acnt else NATA) + (1 - ka) * NATA
    buf = ''
    for c in range(6):
        s6 = sum(v[c * 6 + r] * (r + 1) for r in range(6))
        n6 = sum(v[c * 6 + r] for r in range(6))
        base = aavg + (NAT[c] - NATA)
        k = n6 / (n6 + SHRINK)
        a = k * (s6 / n6 if n6 else base) + (1 - k) * base
        pw = 1.0 + (NAT[c] - a) / SD[c] * SPREAD
        buf += enc2(round(max(0.0, min(12.9, pw)) * 100))
    P.append(f'{tb}{buf}')

ppath = os.path.join(OUT, 'power.txt')
with open(ppath, 'w', encoding='ascii', newline='\n') as f:
    f.write(f'#{per[0]}-{per[1]}\n' + '\n'.join(P))
print(f'\n  選手の力  {per[0]}年{per[1]}期  {len(P):,}人  '
      f'{os.path.getsize(ppath)/1024:.0f}KB   {ppath}')
print(f'  ※ ツールの選手データと同じ期か確認すること'
      f'（画面下に「選手データ 20xx年x期」と出ている）')

# ---- 検算 ----
pay = sorted((d[34] or 0) for d in SRC if (d[34] or 0) > 0)
if pay:
    n = len(pay)
    man = sum(1 for x in pay if x >= 10000)
    print(f'\n  3連単の配当  {n:,}件  中央{pay[n//2]:,}円  '
          f'上位10%{pay[n*9//10]:,}円  最高{pay[-1]:,}円')
    print(f'  万舟（1万円以上） {man:,}件（{100*man/n:.1f}%）')

print()
bar('-')
print('  検算（書き出したものを読み直す）')
bar('-')
dec1 = lambda c: D36.index(c)
dec2 = lambda c: D36.index(c[0]) * 36 + D36.index(c[1])
ng = 0
for v, en in list(VENUES.items())[:2]:
    if v not in BY:
        continue
    lines = open(os.path.join(OUT, f'{en}.txt'), encoding='ascii').read().split('\n')
    for ln in lines[1:6]:
        if len(ln) != 20:
            ng += 1
            print(f'    長さが違う: {len(ln)}文字  {ln}')
            continue
        p = [dec2(ln[i*2:i*2+2]) / 100 for i in range(6)]
        t, ws, wd = dec1(ln[12]), dec1(ln[13]), dec1(ln[14])
        r = ln[15:18]
        if not all(ch in '123456' for ch in r) or t > 2:
            ng += 1
            print(f'    中身が変: {ln}')
print(f'  1行20文字・着順1〜6・隊形0〜2   ' + ('★ 問題なし' if ng == 0 else f'← {ng}件おかしい'))

print()
bar()
print(f"""  次にやること

    {OUT}/ の6ファイルを GitHub Pages のリポジトリに置く。
    番組表と同じ場所でよい。

    ブラウザ側は、選ばれた会場のファイルだけを読みに行く。
    1会場150KB程度なので、初回だけ待てば以後はキャッシュが効く。

    1行の中身
      0-11文字  力6個（100倍した整数を36進数2文字ずつ）
      12文字目  隊形 0=枠なり 1=前づけ1つ 2=前づけ2つ以上
      13文字目  風速 0〜35m
      14文字目  風向 0=無風 1北 2北東 3東 4南東 5南 6南西 7西 8北西
      15-17     着順（1着・2着・3着のコース番号）
      18-19     3連単の配当（100円単位・36進数2文字）

    先頭行の # から始まる行は基準値。
    ブラウザ側で同じ物差しを作るために使う。""")
bar()
