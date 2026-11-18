# AgentDeck financial model v2 (2026-11-17, per strategy-core.md section 二点六 D1-D9).
# Single SKU, hybrid structure (strip IPS + 6 low-profile keys + 3 big keys + wheel + mic), USB-C wired.
# Monthly engine 2027-01..2029-12, aggregated to quarters for the CSV. All CNY.
# Usage: D:/conda/miniconda3/python.exe research/08-model.py  -> prints all scenarios + use of funds, writes 08-财务模型.csv (base)
# 2030 is an extension year used only to check that breakeven holds; the '3-year' figures are 2027-2029.
import csv, math, os, sys

FX = 7.1        # 【假设】USD->CNY
VAT = 1.13      # domestic hardware VAT
VAT_SW = 1.06   # domestic software/service VAT

# ---------------- BOM (CNY per unit) at 1k / 10k ----------------
BOM = [  # (item, 1k, 10k, source tag)
    ('ESP32-S3-WROOM-1 模组（N8R8，带 PSRAM 做屏缓冲）', 28, 23, '【估算】raw-tech：LCSC/DigiKey 阶梯价 $4.0 / $3.2'),
    ('3.2–3.5 寸长条 IPS 屏（如 3.49 寸 172×640）+ FPC + 亚克力视窗', 50, 30, '【假设】无报价；淘宝同类长条屏模组零售几十元量级，待询价'),
    ('6 个矮轴会话键（轴 + 热插拔座 + 键帽）', 27, 17, '【估算】佳达隆轴零售约 ¥1.4/颗 [china §6]，矮轴、座、键帽按经验加价'),
    ('3 个大号机械键 ✓ / ✗ / 按住说话（轴 + 大键帽 + 卫星轴）', 24, 15, '【假设】无来源'),
    ('Ctrl + 截图 两个键', 8, 5, '【假设】无来源'),
    ('9 颗 RGB 灯（6 会话键 + 3 大键）', 5, 3, '【假设】无来源'),
    ('金属滚轮 + 编码器', 43, 28, '【估算】raw-tech：$6 / $4，无来源'),
    ('MEMS 麦克风', 11, 7, '【估算】raw-tech：$1.5 / $1，无来源'),
    ('PCB + SMT + 被动件 + USB-C 座', 57, 36, '【估算】raw-tech：$8 / $5，无来源'),
    ('注塑外壳（上下壳）', 32, 21, '【估算】raw-tech：$3–6 / $2–4 取中值'),
    ('定位板 / 配重钢板 + 脚垫', 10, 6, '【假设】机械轴需要定位板；配重让机器不滑'),
]
RESERVE = 0.15                 # 【假设】no quote yet -> 15% reserve
ASM = (20, 12)                 # assembly + test 【假设】
PACK = (28, 21)                # box + USB-C cable + manual 【假设】
TOOLING = 120_000              # injection molds + jigs 【假设】(raw-tech $8k–30k, low-mid)
CERT = 60_000                  # FCC/CE/RoHS for wired USB device 【假设】(RF on ESP32 disabled; lab must confirm)

BOM_SCALE = 1.0   # scenario knob: 0.9 = design-to-cost target reached

def bom_raw(i):
    return sum(r[1 + i] for r in BOM) * BOM_SCALE

def landed_at(pos):
    """pos 0 = 1k-tier cost, 1 = 10k-tier cost (linear in between)."""
    a = bom_raw(0) * (1 + RESERVE) + ASM[0] + PACK[0]
    b = bom_raw(1) * (1 + RESERVE) + ASM[1] + PACK[1]
    return a + (b - a) * pos

def bom_res_at(pos):
    return (bom_raw(0) + (bom_raw(1) - bom_raw(0)) * pos) * (1 + RESERVE)

# ---------------- prices (D2) ----------------
LIST_CN, EARLY_CN = 499, 399
LIST_US, EARLY_US = 99, 79
REAL_CN = 469        # 【假设】avg realized retail (618/双11 at ¥449, else ¥499)
REAL_US = 95         # 【假设】avg realized retail (BF/Prime Day at $89, else $99)
CF_CN_AVG = 434      # 【假设】摩点 tiers: 30% at ¥399 超早鸟, 70% at ¥449 早鸟
CF_US_AVG = 85       # 【假设】KS tiers: 40% at $79, 60% at $89
TARIFF = 0.25        # 【假设】US tariff on declared value (~landed cost); must confirm with broker

def unit(ch, pos):
    """Per-unit economics for a retail sale. ch: 'cn' or 'us'. Returns dict (CNY)."""
    landed = landed_at(pos); bres = bom_res_at(pos)
    if ch == 'cn':
        net = REAL_CN / VAT
        logistics = 12
        duty = 0
        # 【假设】channel mix 50% Tmall/JD (fees 7%, ads 12%) / 50% own site + community (fees 1%, CAC 5%)
        platform = net * (0.5 * 0.07 + 0.5 * 0.01)
        returns = net * 0.03
        cac = net * (0.5 * 0.12 + 0.5 * 0.05)
    else:
        net = REAL_US * FX
        # 【假设】mix 60% own DTC (sea freight to US 3PL ¥10 + last mile $8; payment 3.5%) / 40% Amazon (headhaul ¥20 + FBA $7; referral 15%)
        logistics = 0.6 * (10 + 8 * FX) + 0.4 * (20 + 7 * FX)
        duty = landed * TARIFF
        platform = net * (0.6 * 0.035 + 0.4 * 0.15)
        returns = net * 0.05
        cac = net * 0.12   # DTC ads / Amazon ACoS
    warranty = bres * 0.03
    cogs = landed + logistics + duty + platform + returns + warranty
    gm = net - cogs
    # "product margin" = before channel/fulfilment (net - landed - duty - warranty); common hardware KPI
    prod_gm = net - landed - duty - warranty
    return dict(net=net, bom=bres, asmpack=landed - bres, logistics=logistics, duty=duty, platform=platform,
                returns=returns, warranty=warranty, cogs=cogs, gm=gm, gm_pct=gm / net, prod_gm_pct=prod_gm / net,
                cac=cac, contrib=gm - cac, contrib_pct=(gm - cac) / net)

def unit_cf(ch, pos):
    """Crowdfunding unit: backers pay shipping separately (campaign norm); no CAC here (campaign ads are in opex)."""
    landed = landed_at(pos); bres = bom_res_at(pos)
    if ch == 'cn':
        net = CF_CN_AVG / VAT
        fees = net * 0.05          # 【假设】摩点 service fee + payment
        cogs = landed + 12 + fees + bres * 0.03
    else:
        net = CF_US_AVG * FX
        fees = net * 0.09          # 【假设】KS 5% + payment 3–5%
        cogs = landed + landed * TARIFF + fees + bres * 0.03
    return dict(net=net, cogs=cogs, gm=net - cogs, gm_pct=(net - cogs) / net)

# ---------------- subscriptions (D4) ----------------
HIRE_PAY = 25_000    # 【假设】fully loaded monthly cost per non-founder hire
PRO_CN, PRO_US = 19, 3.99
PRO_NET = 0.6 * (PRO_CN / VAT_SW * 0.98) + 0.4 * (PRO_US * FX * 0.95)  # 【假设】40% overseas payers; payment fees
PRO_COST = 4.0        # 【假设】ASR + LLM correction + relay per paying user per month
TEAM_NET = 49 / VAT_SW   # 【假设】blended ¥39–59 list -> ¥49 mid, ex VAT
TEAM_COST_PCT = 0.15     # 【假设】support/hosting share

# ---------------- calendar ----------------
YEARS = (2027, 2028, 2029, 2030)   # 2030 = extension year, only to test that breakeven holds
MONTHS = [(y, m) for y in YEARS for m in range(1, 13)]
def mkey(y, m): return f'{y}-{m:02d}'
def qkey(y, m): return f'{y}Q{(m - 1) // 3 + 1}'
QUARTERS = [f'{y}Q{q}' for y in YEARS for q in (1, 2, 3, 4)]
INTRA = {1: (0.30, 0.25, 0.45), 2: (0.25, 0.30, 0.45), 3: (0.33, 0.33, 0.34), 4: (0.25, 0.50, 0.25)}  # 618 / 双11 / BF

def spread(qplan):
    """quarter dict -> month dict using INTRA weights."""
    out = {}
    for (y, m) in MONTHS:
        q = qkey(y, m); qi = (m - 1) // 3 + 1; w = INTRA[qi][(m - 1) % 3]
        out[mkey(y, m)] = qplan.get(q, 0) * w
    return out

def interp_q(qend):
    """quarter-end values -> monthly linear interpolation (starting from 0 before first value)."""
    out = {}; prev = 0
    for q in QUARTERS:
        v = qend.get(q, prev if q > min(qend) else 0)
        y = int(q[:4]); qi = int(q[-1])
        for j in range(3):
            m = (qi - 1) * 3 + j + 1
            out[mkey(y, m)] = prev + (v - prev) * (j + 1) / 3
        prev = v
    return out

# ---------------- base plan ----------------
def plan(s):
    """s: scenario dict of multipliers."""
    retail_q = {'2028Q1': 300, '2028Q2': 1100, '2028Q3': 1300, '2028Q4': 2300,
                '2029Q1': 2000, '2029Q2': 2800, '2029Q3': 2800, '2029Q4': 4400,
                '2030Q1': 2600, '2030Q2': 3700, '2030Q3': 3700, '2030Q4': 5800}
    retail_q = {k: v * s['retail'] for k, v in retail_q.items()}
    os_share = {'2028Q1': 0.30, '2028Q2': 0.30, '2028Q3': 0.35, '2028Q4': 0.40,
                '2029Q1': 0.40, '2029Q2': 0.45, '2029Q3': 0.45, '2029Q4': 0.45,
                '2030Q1': 0.50, '2030Q2': 0.50, '2030Q3': 0.50, '2030Q4': 0.50}
    # cost tier position by quarter of production (honest: 10k tier only once annual run-rate ~10k)
    pos_q = {'2028Q1': 0.30, '2028Q2': 0.40, '2028Q3': 0.50, '2028Q4': 0.60,
             '2029Q1': 0.70, '2029Q2': 0.80, '2029Q3': 0.90, '2029Q4': 1.00,
             '2030Q1': 1.00, '2030Q2': 1.00, '2030Q3': 1.00, '2030Q4': 1.00}
    pos_q = {k: min(1.0, v * s['cost_speed']) for k, v in pos_q.items()}
    cf_us = round(900 * s['cf']); cf_cn = round(600 * s['cf'])      # backers (units)
    wau = {'2027Q1': 300, '2027Q2': 1000, '2027Q3': 2000, '2027Q4': 3000, '2028Q1': 4000, '2028Q2': 5500,
           '2028Q3': 7000, '2028Q4': 9000, '2029Q1': 11000, '2029Q2': 13000, '2029Q3': 15000, '2029Q4': 18000,
           '2030Q1': 20000, '2030Q2': 22000, '2030Q3': 24000, '2030Q4': 27000}
    wau = {k: v * s['wau'] for k, v in wau.items()}
    seats = {'2028Q3': 50, '2028Q4': 120, '2029Q1': 220, '2029Q2': 350, '2029Q3': 500, '2029Q4': 700,
             '2030Q1': 900, '2030Q2': 1100, '2030Q3': 1300, '2030Q4': 1600}
    seats = {k: v * s['team'] for k, v in seats.items()}
    return retail_q, os_share, pos_q, cf_us, cf_cn, wau, seats

def headcount(y, m, s):
    hc = s['hc']
    for (start, n) in hc:
        if (y, m) >= start: cur = n
    return cur

def build(s):
    global BOM_SCALE
    BOM_SCALE = s.get('bom_scale', 1.0)
    retail_q, os_share, pos_q, cf_us, cf_cn, wau_q, seats_q = plan(s)
    if s.get('no_hw'):   # D7 gate failed: no tooling, no crowdfunding, software only
        retail_q = {}; cf_us = cf_cn = 0
    retail_m = spread(retail_q)
    wau_m = interp_q(wau_q)
    seats_m = interp_q({q: seats_q.get(q, 0) for q in QUARTERS})
    # crowdfunding: campaign 2027-09; cash 2027-10 (KS 100%, 摩点 70%) ; delivery 2028-01 (60%) / 2028-02 (40%)
    cf_pos = 0.18  # log10(1.5k / 1k)
    ucf_us = unit_cf('us', cf_pos); ucf_cn = unit_cf('cn', cf_pos)
    cf_cash_us = cf_us * CF_US_AVG * FX * (1 - 0.09)
    cf_cash_cn = cf_cn * CF_CN_AVG / VAT * (1 - 0.05)
    cf_gross = cf_us * CF_US_AVG * FX + cf_cn * CF_CN_AVG       # pledged amount incl VAT (for trigger check)
    rows = []
    cum_units = 0
    for (y, m) in MONTHS:
        k = mkey(y, m); q = qkey(y, m)
        # ---- units & hardware P&L ----
        units = retail_m[k]; hw = cogs = cac = 0.0; cf_units = 0
        if q in pos_q and units:
            pos = pos_q[q]; osh = os_share[q]
            for ch, sh in (('cn', 1 - osh), ('us', osh)):
                u = unit(ch, pos)
                hw += units * sh * u['net']; cogs += units * sh * u['cogs']; cac += units * sh * u['cac']
        if k in ('2028-01', '2028-02'):
            w = 0.6 if k == '2028-01' else 0.4
            cf_units = (cf_us + cf_cn) * w
            hw += w * (cf_us * ucf_us['net'] + cf_cn * ucf_cn['net'])
            cogs += w * (cf_us * ucf_us['cogs'] + cf_cn * ucf_cn['cogs'])
        cum_units += units + cf_units
        # ---- subscriptions ----
        pro_subs = 0.0
        if (y, m) >= (2028, 1):   # Personal Pro launches with crowdfunding delivery
            active_hw = cum_units * 0.8                       # 【假设】80% of shipped devices still in use
            pro_subs = s['pro_conv'] * wau_m[k] + s['pro_attach'] * active_hw
        seats = seats_m[k]
        pro_rev = pro_subs * PRO_NET; team_rev = seats * TEAM_NET
        sub = pro_rev + team_rev
        sub_cost = pro_subs * PRO_COST + team_rev * TEAM_COST_PCT
        cogs_t = cogs + sub_cost
        gp = hw + sub - cogs_t
        # ---- opex ----
        hc = headcount(y, m, s)
        # 【假设】3 founders at ¥1.2万/月 fully loaded until breakeven (D8 default alive), hires at ¥2.5万/月 fully loaded
        founders = min(hc, 3)
        salary = founders * s['founder_pay'] + (hc - founders) * HIRE_PAY
        rd = {2027: 25_000, 2028: 13_000, 2029: 17_000, 2030: 20_000}[y]     # prototyping / EVT-DVT / v1.1
        if (y, m) in ((2027, 4), (2027, 5)): rd += 25_000      # DVT build
        hw_on = not s.get('no_hw')
        tooling = TOOLING if (y, m) == (2027, 8) and hw_on else 0   # only after ≥1,500 deposits (D7)
        if (y, m) == (2029, 7) and hw_on and not s.get('cut'): tooling += 50_000   # v1.1 mold tweak
        cert = CERT if (y, m) == (2027, 10) and hw_on else 0
        mkt = {2027: 7_000, 2028: 13_000, 2029: 17_000, 2030: 20_000}[y]     # content / community / brand
        if (y, m) in ((2027, 4), (2027, 5), (2027, 6), (2027, 7)): mkt += 16_000   # $1 deposit landing-page ads
        if (y, m) in ((2027, 8), (2027, 9)) and hw_on: mkt += 90_000 * s['cf_mkt']   # campaign ads + KOL + video
        if s.get('cut') and y >= 2029: mkt *= 0.5                                  # cut plan: halve brand spend
        ga = {2027: 13_000, 2028: 17_000, 2029: 20_000, 2030: 22_000}[y]
        if (y, m) == (2027, 1): ga += 30_000                   # rename: trademark search + filings CN/US (D5)
        cloud = {2027: 2_000, 2028: 3_500, 2029: 5_000, 2030: 6_000}[y]
        opex_fixed = salary + rd + tooling + cert + mkt + ga + cloud
        opex = opex_fixed + cac
        rows.append(dict(k=k, q=q, y=y, units=units + cf_units, cf_units=cf_units, hw=hw, sub=sub, pro_rev=pro_rev,
                         team_rev=team_rev, cogs=cogs_t, gp=gp, opex=opex, salary=salary, rd=rd, tooling=tooling,
                         cert=cert, mkt=mkt, ga=ga, cloud=cloud, cac=cac, hc=hc, wau=wau_m[k], pro_subs=pro_subs,
                         seats=seats))
    # ---- cash: inventory paid 50% two months ahead + 50% one month ahead ; crowdfunding prepay ----
    landed_cost = {}
    for r in rows:
        q = r['q']
        retail_landed = (r['units'] - r['cf_units']) * landed_at(pos_q.get(q, 0.3))
        cf_landed = r['cf_units'] * landed_at(cf_pos)
        landed_cost[r['k']] = retail_landed + cf_landed
    keys = [r['k'] for r in rows]
    cash = 0.0; inv_prev = 0.0; deferred = 0.0
    t2_paid = False
    for i, r in enumerate(rows):
        nxt1 = landed_cost[keys[i + 1]] if i + 1 < len(keys) else landed_cost[keys[i]] * 1.1
        nxt2 = landed_cost[keys[i + 2]] if i + 2 < len(keys) else landed_cost[keys[i]] * 1.1
        inv = nxt1 + 0.5 * nxt2
        d_inv = inv - inv_prev; inv_prev = inv
        prepay = 0.0
        if r['k'] == '2027-10':
            prepay = cf_cash_us + cf_cash_cn * 0.7
            deferred = prepay
        if r['k'] in ('2028-01', '2028-02'):
            w = 0.6 if r['k'] == '2028-01' else 0.4
            # gp now contains (pledge - fees) for all CF units; the part already received in 2027-10 is reversed.
            # The 摩点 30% balance is received now, so it stays in gp as cash.
            prepay = -deferred * w
        fin = 0.0
        if r['k'] == '2027-01': fin = s['t1']
        if s['t2'] and r['k'] == s['t2_month']: fin = s['t2']
        if s.get('extra') and r['k'] == s['extra'][0]: fin += s['extra'][1]
        ocf = r['gp'] - r['opex'] - d_inv + prepay
        cash += ocf + fin
        r.update(inv=inv, d_inv=d_inv, prepay=prepay, ocf=ocf, fin=fin, cash=cash)
    return rows, dict(cf_gross=cf_gross, cf_us=cf_us, cf_cn=cf_cn, ucf_us=ucf_us, ucf_cn=ucf_cn)

# Cash identity: ocf = gp - opex - Δinventory + prepay. Inventory = landed cost already paid to the factory for
# units not yet sold (next month 100% + month after 50%). Crowdfunding: pledge cash net of platform fees arrives
# 2027-10 (KS 100%, 摩点 70%) as prepay; at delivery gp books (pledge - fees) and the prepaid part is reversed.

def quarterly(rows):
    out = []
    for q in QUARTERS:
        rs = [r for r in rows if r['q'] == q]
        agg = {f: sum(r[f] for r in rs) for f in ('units', 'cf_units', 'hw', 'sub', 'pro_rev', 'team_rev', 'cogs', 'gp',
                                                  'opex', 'salary', 'rd', 'tooling', 'cert', 'mkt', 'ga', 'cloud', 'cac',
                                                  'd_inv', 'prepay', 'ocf', 'fin')}
        agg.update(q=q, cash=rs[-1]['cash'], hc=rs[-1]['hc'], wau=rs[-1]['wau'], pro_subs=rs[-1]['pro_subs'],
                   seats=rs[-1]['seats'])
        out.append(agg)
    return out

def breakeven(rows):
    """first month after which trailing-3-month operating cash flow (ex financing) stays >= 0 to end of model."""
    t3 = [sum(r['ocf'] for r in rows[max(0, i - 2):i + 1]) for i in range(len(rows))]
    for i in range(len(rows)):
        if all(v >= 0 for v in t3[i:]):
            return rows[i]['k']
    return None

def op_breakeven(rows):
    """first month after which trailing-3-month operating profit (gp - opex) stays >= 0."""
    t3 = [sum(r['gp'] - r['opex'] for r in rows[max(0, i - 2):i + 1]) for i in range(len(rows))]
    for i in range(len(rows)):
        if all(v >= 0 for v in t3[i:]):
            return rows[i]['k']
    return None

BASE = dict(retail=1.0, cf=1.0, wau=1.0, team=1.0, pro_conv=0.03, pro_attach=0.12, cost_speed=1.0, cf_mkt=1.0,
            founder_pay=12_000, t1=2_500_000, t2=2_500_000, t2_month='2027-09',
            hc=[((2027, 1), 4), ((2027, 10), 5), ((2029, 1), 6)])     # D8: 4 until crowdfunding succeeds
MARKET_PAY = dict(BASE, founder_pay=25_000)                          # sensitivity: founders at market pay
DTC = dict(BASE, bom_scale=0.9)                                      # design-to-cost target reached
BULL = dict(BASE, retail=2.0, cf=2.5, wau=1.8, team=2.0, pro_attach=0.15, cost_speed=1.6, cf_mkt=1.5,
            hc=[((2027, 1), 4), ((2027, 10), 6), ((2028, 4), 8), ((2029, 1), 10)])
BEAR = dict(BASE, retail=0.45, cf=0.45, wau=0.5, team=0.4, pro_attach=0.10, cost_speed=0.6, cf_mkt=0.7,
            hc=[((2027, 1), 4), ((2027, 10), 5)])
BEAR_CUT = dict(BEAR, cut=True, hc=[((2027, 1), 4), ((2027, 10), 5), ((2028, 7), 4)])
NO_HW = dict(BASE, no_hw=True, t2=0, wau=0.5, team=0.4, hc=[((2027, 1), 4), ((2027, 10), 3)])   # gate failed
OPT_A = dict(BASE, t1=3_000_000, t2=0)   # seed ¥300万 single close, same operating plan

def wan(x): return x / 1e4

def report(name, s, verbose=False):
    rows, cf = build(s); qs = quarterly(rows)
    low = min(rows, key=lambda r: r['cash'])
    print(f'\n### {name}: crowdfunding {cf["cf_us"]}+{cf["cf_cn"]} units, pledged ¥{wan(cf["cf_gross"]):.1f}万')
    if verbose:
        print('q units hw sub cogs gp gm% opex op_profit d_inv prepay ocf fin cash hc wau pro seats')
        for r in qs:
            rev = r['hw'] + r['sub']
            print(r['q'], round(r['units']), *[f'{wan(r[f]):.1f}' for f in ('hw', 'sub', 'cogs', 'gp')],
                  f'{(r["gp"] / rev if rev else 0):.0%}', f'{wan(r["opex"]):.1f}', f'{wan(r["gp"] - r["opex"]):.1f}',
                  f'{wan(r["d_inv"]):.1f}', f'{wan(r["prepay"]):.1f}', f'{wan(r["ocf"]):.1f}', f'{wan(r["fin"]):.0f}',
                  f'{wan(r["cash"]):.1f}', r['hc'], round(r['wau']), round(r['pro_subs']), round(r['seats']))
    tot_rev = 0
    for y in YEARS:
        rs = [r for r in rows if r['y'] == y]
        u = sum(r['units'] for r in rs); rev = sum(r['hw'] + r['sub'] for r in rs); gp = sum(r['gp'] for r in rs)
        sub = sum(r['sub'] for r in rs); opex = sum(r['opex'] for r in rs); ocf = sum(r['ocf'] for r in rs)
        tot_rev += rev if y <= 2029 else 0
        print(y, f'units {u:.0f} rev {wan(rev):.1f} sub {wan(sub):.1f} gp {wan(gp):.1f} gm {gp / rev if rev else 0:.0%} '
                 f'opex {wan(opex):.1f} op_profit {wan(gp - opex):.1f} ocf {wan(ocf):.1f} cash_end {wan(rs[-1]["cash"]):.1f} '
                 f'hc {rs[-1]["hc"]} pro {rs[-1]["pro_subs"]:.0f} seats {rs[-1]["seats"]:.0f}')
    print(f'3yr revenue {wan(tot_rev):.1f}万  cash low {wan(low["cash"]):.1f}万 at {low["k"]}  '
          f'op-profit breakeven (rolling 3m >= 0 from then on) {op_breakeven(rows)}  end-2030 cash {wan(rows[-1]["cash"]):.1f}')
    return rows, qs, cf

def print_ue():
    print('raw BOM 1k/10k', bom_raw(0), bom_raw(1), ' with reserve', round(bom_raw(0) * 1.15), round(bom_raw(1) * 1.15))
    print('landed 1k/10k', round(landed_at(0)), round(landed_at(1)))
    for pos, lab in ((0, '1k'), (0.5, '~3k'), (1, '10k')):
        for ch in ('cn', 'us'):
            u = unit(ch, pos)
            print(lab, ch, ' '.join(f'{k}={v:.0f}' if 'pct' not in k else f'{k}={v:.0%}' for k, v in u.items()))
    for ch in ('cn', 'us'):
        u = unit_cf(ch, 0.18)
        print('CF', ch, ' '.join(f'{k}={v:.0f}' if 'pct' not in k else f'{k}={v:.0%}' for k, v in u.items()))
    # design-to-cost: max landed for 42% product margin at 10k
    for ch in ('cn', 'us'):
        net = REAL_CN / VAT if ch == 'cn' else REAL_US * FX
        # cn: prod_gm = net - landed - 0.03*bom ; us: net - landed*(1+T) - 0.03*bom ; approx bom ~ landed-33
        k = 1 if ch == 'cn' else 1 + TARIFF
        max_landed = (net * 0.58 + 0.03 * 33) / (k + 0.03)
        print('design-to-cost', ch, 'max landed for 42% product margin', round(max_landed),
              'max BOM incl reserve', round(max_landed - ASM[1] - PACK[1]))
    print('PRO_NET', round(PRO_NET, 1), 'TEAM_NET', round(TEAM_NET, 1))

if __name__ == '__main__':
    print_ue()
    base_rows, base_q, base_cf = report('BASE (方案 B: ¥250万 + ¥250万, lean team)', BASE, verbose=True)
    report('SENSITIVITY: founders at market pay ¥2.5万', MARKET_PAY)
    report('SENSITIVITY: design-to-cost BOM -10%', DTC)
    report('BULL', BULL)
    report('BEAR (deposits hit 1,500 so T2 paid, but sales 45% of base; no cuts)', BEAR)
    report('BEAR + CUT PLAN (back to 4 people 2028-07, halve 2029 brand, skip v1.1 mold)', BEAR_CUT, verbose=True)
    report('GATE FAILED (<1,500 deposits: no T2, no tooling, software only, 3 people)', NO_HW)
    report('OPTION A (¥300万 single close, base operations)', OPT_A)
    # ---- use of funds: 2027-01 .. 2028-12; the table sums exactly to the raise ----
    # Interim gross profit (and crowdfunding prepay, net 0 by then) is shown separately: it pays retail CAC and
    # inventory first; any excess is credited against the team line ("融资承担部分").
    low = min(base_rows, key=lambda r: r['cash'])
    UOF_END = '2028-12'   # 24-month deployment window; remaining cash carries the company to the 2029-10 low point
    upto = [r for r in base_rows if r['k'] <= UOF_END]
    c = {f: sum(r[f] for r in upto) for f in ('salary', 'rd', 'tooling', 'cert', 'mkt', 'ga', 'cloud', 'cac', 'd_inv', 'gp', 'prepay')}
    raise_total = BASE['t1'] + BASE['t2']
    carried = upto[-1]['cash']
    interim = c['gp'] + c['prepay']
    gp_excess = interim - c['cac'] - c['d_inv']          # >0: GP also paid part of the team
    uof = {'团队（融资承担部分）': c['salary'] - max(0, gp_excess),
           '研发打样（EVT/DVT/PVT）': c['rd'],
           '模具 + 认证': c['tooling'] + c['cert'],
           '品牌、$1 订金测试、众筹投放': c['mkt'],
           '行政、法务、改名商标、云服务': c['ga'] + c['cloud'],
           '备货与营运资金（融资承担部分）': max(0, -gp_excess),
           '2028 年末留存现金（带入 2029，支撑到盈亏平衡）': carried}
    print(f'\nUSE OF FUNDS 2027-01..{UOF_END} (raise ¥{wan(raise_total):.0f}万); base cash low {wan(low["cash"]):.1f}万 at {low["k"]}')
    for k, v in uof.items(): print(f'  {k}: {wan(v):.1f}万 ({v / raise_total:.1%})')
    print(f'  SUM = {wan(sum(uof.values())):.1f}万')
    print(f'  separately: interim gross profit {wan(c["gp"]):.1f}万 (prepay net {wan(c["prepay"]):.1f}) paid retail CAC {wan(c["cac"]):.1f}万 + '
          f'inventory {wan(c["d_inv"]):.1f}万 + team {wan(max(0, gp_excess)):.1f}万; total team cost {wan(c["salary"]):.1f}万')
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '08-财务模型.csv')
    with open(out, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['quarter', 'units_shipped', 'of_which_crowdfunding', 'hw_revenue_cny', 'sub_revenue_cny',
                    'pro_revenue_cny', 'team_revenue_cny', 'cogs_cny', 'gross_profit_cny', 'opex_cny',
                    'operating_profit_cny', 'inventory_change_cny', 'crowdfunding_prepay_cny', 'operating_cash_flow_cny',
                    'financing_in_cny', 'cash_end_cny', 'headcount', 'wau_end', 'pro_subscribers_end', 'team_seats_end'])
        for r in base_q:
            w.writerow([r['q'], round(r['units']), round(r['cf_units']), round(r['hw']), round(r['sub']), round(r['pro_rev']),
                        round(r['team_rev']), round(r['cogs']), round(r['gp']), round(r['opex']), round(r['gp'] - r['opex']),
                        round(r['d_inv']), round(r['prepay']), round(r['ocf']), round(r['fin']), round(r['cash']), r['hc'],
                        round(r['wau']), round(r['pro_subs']), round(r['seats'])])
    print('wrote', os.path.normpath(out))
