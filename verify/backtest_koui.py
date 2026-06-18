"""
好位補正 バックテスト v2（入口条件60%以上）
KOUI_MAX_BONUS = 0/3/5/8 の4パターン比較

指標:
  ① 予想1〜5位の複勝的中率（各位が3着以内に入る率）
  ② 5〜8人気穴馬の予想top5拾得率
  ③ ROI（単勝/複勝/馬連1×2/5BOX）
  ④ 好位補正で順位上昇した馬の成績（ベースライン比較）
"""
import sys, re, json
sys.path.insert(0, '/Users/du/Documents/競馬予想システム')

import scorer_turf
from pathlib import Path
from cache_store import cache_get, cache_get_before
from jra_scraper import HorseEntry, RaceInfo
from scorer_dart import score_all as score_dart

BASE         = Path('/Users/du/Documents/競馬予想システム')
CACHE_RACE   = BASE / 'cache' / 'race_result'
TRAINING_DIR = BASE / 'cache' / 'netkeiba_training'
TARGET       = {"3勝クラス", "OP"}

def _pa(s): return [int(m.replace(',','')) for m in re.findall(r'[\d,]+(?=円)', s)]
def _pn(s):
    nums,i=[],0
    while i<len(s):
        if i+2<=len(s) and int(s[i:i+2])<=18: nums.append(int(s[i:i+2]));i+=2
        else: nums.append(int(s[i:i+1]));i+=1
    return nums

def get_pay(rid, bet):
    p=cache_get('payouts',rid)
    if not p: return [],[]
    v=p.get(bet,{}); raw=v.get('raw',[])
    if len(raw)<3: return [],[]
    return _pn(raw[1]) if raw[1] else [], _pa(raw[2]) if raw[2] else []

def load_tr(rid):
    p=TRAINING_DIR/f"{rid}.json"
    if not p.exists(): return None
    try:
        from netkeiba_scraper import TrainingData as TD
        raw=json.loads(p.read_text())
        return {n:TD(horse_name=n,rank=v["rank"],comment=v.get("comment",""),score=v["score"])
                for n,v in raw.items()} if raw else None
    except: return None


def score_one(data, max_bonus):
    scorer_turf.KOUI_MAX_BONUS = max_bonus

    if data.get("race_class") not in TARGET: return None
    if data.get("surface") not in ("芝","ダ"): return None
    dm=re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日", data["date"])
    if not dm: return None
    cutoff=f"{dm.group(1)}/{int(dm.group(2)):02d}/{int(dm.group(3)):02d}"

    ri=RaceInfo(name=data["race_name"],date=data["date"],venue=data["venue"],
                race_number=f"{data['race_num_int']}R",distance=data["distance"],
                surface=data["surface"],conditions=data.get("conditions",""),
                start_time=data.get("start_time",""),url="",race_num=data["race_num_int"])
    entries=[]; rank_map={}; odds_map={}; pop_map={}; hnum_map={}
    for e in data["entries"]:
        hid=e.get("horse_id","")
        he=HorseEntry(frame_number=e["frame"],horse_number=e["horse_num"],
                      horse_name=e["horse_name"],record="",prize_money="",
                      owner="",trainer="",age_sex=e.get("age_sex",""),
                      weight_carried=e.get("weight_carried",""),jockey=e.get("jockey",""),
                      recent_races=cache_get_before("horse_history",hid,cutoff) or [],
                      sire=cache_get("sire",hid) or "")
        entries.append(he)
        rank_map[e["horse_name"]]=e.get("rank",99)
        odds_map[e["horse_name"]]=e.get("odds")
        pop_map[e["horse_name"]]=e.get("popularity",99)
        try: hnum_map[e["horse_name"]]=int(e.get("horse_num",0))
        except: hnum_map[e["horse_name"]]=None

    if len(entries)<5: return None
    fn=score_dart if data["surface"]=="ダ" else scorer_turf.score_all
    scored=fn(entries,ri,training_data=load_tr(data.get("race_id","")),
              track_condition=data.get("track_condition",""),
              horse_ids={e["horse_name"]:e.get("horse_id","") for e in data["entries"]})
    scored.sort(key=lambda x:x[1].total,reverse=True)
    if len(scored)<2: return None

    gap=round(scored[0][1].total-scored[1][1].total,2)
    n=len(scored)
    if n==18 or 3<=gap<5: return None

    def nm(i): return scored[i][0].horse_name if i<len(scored) else None
    def act(name): return rank_map.get(name,99) if name else 99
    def hn(name): return hnum_map.get(name) if name else None
    def pop(name): return pop_map.get(name,99) if name else 99

    rid=data.get("race_id","")
    p1n,p1=hn(nm(0)),nm(0)

    # 馬連ペイアウトテーブル
    bar_hs,bar_ams=get_pay(rid,'馬連') if rid else ([],[])
    bar_pmap={}
    for i in range(len(bar_ams)):
        a=bar_hs[i*2] if i*2<len(bar_hs) else None
        b=bar_hs[i*2+1] if i*2+1<len(bar_hs) else None
        if a and b: bar_pmap[frozenset([a,b])]=bar_ams[i]
    p2n=hn(nm(1))
    baren_pay=bar_pmap.get(frozenset([p1n,p2n]),0) if p1n and p2n else 0

    # 5BOX
    top5_names=[nm(i) for i in range(min(5,n))]
    top5_nums=[hn(x) for x in top5_names if hn(x)]
    top5_in3=sum(1 for x in top5_names if act(x)<=3)
    trio_pay=0
    if rid and top5_in3==3 and len(top5_nums)>=3:
        hs,ams=get_pay(rid,'3連複')
        if hs and ams and frozenset(hs[:3]).issubset(set(top5_nums)):
            trio_pay=ams[0]

    # 複勝
    fuku_pay=0
    if rid and act(p1)<=3:
        hs,ams=get_pay(rid,'複勝')
        if hs and ams and p1n in hs:
            idx=hs.index(p1n)
            if idx<len(ams): fuku_pay=ams[idx]

    # 単勝
    tan_pay=odds_map.get(p1,0)*100 if act(p1)==1 and odds_map.get(p1) else 0

    # 5〜8人気穴馬拾得
    ana_hit=[]
    for e_nm,rk in rank_map.items():
        if rk<=3 and 5<=pop(e_nm)<=8:
            pred_rank=next((i+1 for i,(he,_) in enumerate(scored) if he.horse_name==e_nm),99)
            ana_hit.append(pred_rank<=5)

    # 全馬データ（①④用）
    horses=[
        {
            "rank_pred": i+1,
            "name": he.horse_name,
            "total": bd.total,
            "koui_bonus": bd.koui_bonus,
            "act": rank_map.get(he.horse_name,99),
            "pop": pop_map.get(he.horse_name,99),
        }
        for i,(he,bd) in enumerate(scored)
    ]

    return {
        "rid":rid,"n":n,"gap":gap,"odds1":odds_map.get(p1),
        "p1_act":act(p1),"top5_in3":top5_in3,
        "tan_pay":tan_pay,"fuku_pay":fuku_pay,
        "baren_pay":baren_pay,"trio_pay":trio_pay,
        "ana_hit":ana_hit,"horses":horses,
    }


def run_all(max_bonus):
    scorer_turf.KOUI_MAX_BONUS=max_bonus
    races=[]
    for i,f in enumerate(sorted(CACHE_RACE.glob("*.json"))):
        if i%200==0: print(f"  {i}件...",flush=True)
        try: data=json.loads(f.read_text())
        except: continue
        r=score_one(data,max_bonus)
        if r: races.append(r)
    return races


def report(label, races, baseline_ranks=None):
    n=len(races)
    if n==0: return

    tan_c=sum(r["tan_pay"] for r in races)
    fuku_c=sum(r["fuku_pay"] for r in races)
    bar_c=sum(r["baren_pay"] for r in races)
    box_c=sum(r["trio_pay"] for r in races)

    tan_roi=tan_c/(n*100)*100
    fuku_roi=fuku_c/(n*100)*100
    bar_roi=bar_c/(n*100)*100
    box_roi=box_c/(n*1000)*100
    tan_pct=sum(1 for r in races if r["p1_act"]==1)/n*100
    box_pct=sum(1 for r in races if r["top5_in3"]==3)/n*100

    # 穴馬拾得率
    ana_all=sum(len(r["ana_hit"]) for r in races)
    ana_ok=sum(sum(1 for h in r["ana_hit"] if h) for r in races)
    ana_pct=ana_ok/ana_all*100 if ana_all else 0

    # 好位補正あり予想1位の割合
    koui_top=sum(1 for r in races if r["horses"] and r["horses"][0]["koui_bonus"]>0)

    print(f"\n  [{label}] n={n}R")

    # ① 予想1〜5位の複勝的中率
    print(f"  ① 予想1〜5位の複勝的中率:")
    for rank in range(1, 6):
        hits=sum(1 for r in races for h in r["horses"] if h["rank_pred"]==rank and h["act"]<=3)
        total=sum(1 for r in races if len(r["horses"])>=rank)
        rate=hits/total*100 if total else 0
        marker=" ←軸" if rank==1 else ""
        print(f"     予想{rank}位: {rate:5.1f}%  ({hits}/{total}R){marker}")

    # ② 穴馬拾得率
    print(f"  ② 5〜8人気穴馬top5拾得率: {ana_pct:.1f}%  ({ana_ok}/{ana_all}頭)")

    # ③ ROI
    print(f"  ③ ROI:")
    print(f"     単勝  {tan_roi:>5.0f}%  命中:{tan_pct:.1f}%")
    print(f"     複勝  {fuku_roi:>5.0f}%")
    print(f"     馬連  {bar_roi:>5.0f}%")
    print(f"     5BOX  {box_roi:>5.0f}%  命中:{box_pct:.1f}%")

    # 好位補正あり予想1位
    print(f"  好位補正あり予想1位: {koui_top}/{n}R ({100*koui_top/n:.1f}%)")

    # ④ 好位補正で順位上昇した馬の成績
    if baseline_ranks:
        moved_up=[]
        for r in races:
            base=baseline_ranks.get(r["rid"],{})
            for h in r["horses"]:
                if h["koui_bonus"]>0:
                    base_rank=base.get(h["name"],999)
                    if h["rank_pred"]<base_rank:
                        moved_up.append({
                            "name":h["name"],
                            "from_rank":base_rank,
                            "to_rank":h["rank_pred"],
                            "koui_bonus":h["koui_bonus"],
                            "act":h["act"],
                        })
        m=len(moved_up)
        if m>0:
            in3=sum(1 for h in moved_up if h["act"]<=3)
            win=sum(1 for h in moved_up if h["act"]==1)
            promoted_to1=[h for h in moved_up if h["to_rank"]==1]
            p1_in3=sum(1 for h in promoted_to1 if h["act"]<=3)
            print(f"  ④ 好位補正で順位上昇: {m}頭  3着以内率:{100*in3/m:.1f}%  1着率:{100*win/m:.1f}%")
            if promoted_to1:
                p1n=len(promoted_to1)
                print(f"     うち予想1位に昇格: {p1n}頭 → 3着以内{p1_in3}頭 ({100*p1_in3/p1n:.1f}%)")
            else:
                print(f"     うち予想1位に昇格: 0頭")
        else:
            print(f"  ④ 好位補正で順位上昇した馬: なし")


if __name__=="__main__":
    results={}
    for bonus in [0.0, 3.0, 5.0, 8.0]:
        label=f"好位補正 max={bonus:.0f}pt" if bonus>0 else "ベースライン（補正なし）"
        print(f"\n{'='*55}")
        print(f"  {label}")
        print(f"{'='*55}")
        print("採点中...",flush=True)
        races=run_all(bonus)
        print(f"対象: {len(races)}R")
        results[bonus]=races

    # ベースラインランキング（④分析用）
    baseline_ranks={
        r["rid"]: {h["name"]:h["rank_pred"] for h in r["horses"]}
        for r in results[0.0]
    }

    # 詳細レポート
    for bonus in [0.0, 3.0, 5.0, 8.0]:
        label=f"好位補正 max={bonus:.0f}pt" if bonus>0 else "ベースライン（補正なし）"
        br=baseline_ranks if bonus>0 else None
        report(label, results[bonus], br)

    # サマリー比較表
    print(f"\n{'='*55}")
    print("  差分サマリー（ベースライン比）")
    print(f"{'='*55}")
    def roi(races,pay_key,cost):
        return sum(r[pay_key] for r in races)/(len(races)*cost)*100 if races else 0
    print(f"  {'':10} {'単勝':>7} {'複勝':>7} {'馬連':>7} {'5BOX':>7} {'穴馬%':>7} {'好位1位R':>9}")
    for bonus in [0.0, 3.0, 5.0, 8.0]:
        races=results[bonus]
        n=len(races)
        tr=roi(races,"tan_pay",100)
        fr=roi(races,"fuku_pay",100)
        br=roi(races,"baren_pay",100)
        xr=roi(races,"trio_pay",1000)
        aa=sum(len(r["ana_hit"]) for r in races)
        ao=sum(sum(1 for h in r["ana_hit"] if h) for r in races)
        ap=ao/aa*100 if aa else 0
        kt=sum(1 for r in races if r["horses"] and r["horses"][0]["koui_bonus"]>0)
        lbl=f"max={bonus:.0f}" if bonus>0 else "ベース"
        print(f"  {lbl:<10} {tr:>6.0f}%  {fr:>6.0f}%  {br:>6.0f}%  {xr:>6.0f}%  {ap:>6.1f}%  {kt:>4}/{n}R")
