"""VELTON career-world simulation: snapshots, league movements and synthetic in-game finances.
No club is invented or misrepresented as a verified 2026/27 participant.
Real club/player facts are loaded from sourced local offline JSON snapshots.
"""
from __future__ import annotations
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path
from engine import init_engine_db, ensure_game_world, play_until

REGISTRY = json.loads((Path(__file__).resolve().parent / 'world_data/league_registry.json').read_text(encoding='utf-8'))
LEAGUES = {d['league_id']: d for d in REGISTRY['leagues']}
NO_PROMOTION = {'USA','MEX'}  # No automatic promotion in US league pyramid / MX model in this release.
START_YEAR = 2026


def init_world_db(c):
    c.executescript('''
      CREATE TABLE IF NOT EXISTS league_catalog (
        id TEXT PRIMARY KEY, country TEXT NOT NULL, association TEXT NOT NULL,
        region TEXT NOT NULL, name TEXT NOT NULL, tier INTEGER NOT NULL,
        intended_clubs INTEGER NOT NULL, groups_json TEXT NOT NULL DEFAULT '[]'
      );
      CREATE TABLE IF NOT EXISTS club_catalog (
        id TEXT PRIMARY KEY, league_id TEXT NOT NULL REFERENCES league_catalog(id),
        name TEXT NOT NULL, provider_id INTEGER UNIQUE,
        strength INTEGER NOT NULL DEFAULT 65, base_budget_eur INTEGER NOT NULL,
        base_transfer_eur INTEGER NOT NULL, source TEXT NOT NULL, synced_at TEXT NOT NULL
      );
      CREATE INDEX IF NOT EXISTS club_catalog_league ON club_catalog(league_id);
      CREATE TABLE IF NOT EXISTS player_catalog (
        id TEXT PRIMARY KEY, club_id TEXT NOT NULL REFERENCES club_catalog(id) ON DELETE CASCADE,
        name TEXT NOT NULL, position TEXT, age INTEGER, nationality TEXT,
        provider_id INTEGER UNIQUE, source TEXT NOT NULL, synced_at TEXT NOT NULL
      );
      CREATE INDEX IF NOT EXISTS player_catalog_club ON player_catalog(club_id);
      CREATE TABLE IF NOT EXISTS world_clubs (
        user_id INTEGER NOT NULL, slot INTEGER NOT NULL, club_id TEXT NOT NULL,
        league_id TEXT NOT NULL, budget_eur INTEGER NOT NULL,
        transfer_eur INTEGER NOT NULL, strength INTEGER NOT NULL,
        PRIMARY KEY(user_id,slot,club_id),
        FOREIGN KEY(user_id,slot) REFERENCES careers(user_id,slot) ON DELETE CASCADE
      );
      CREATE INDEX IF NOT EXISTS world_leagues ON world_clubs(user_id,slot,league_id);
      CREATE TABLE IF NOT EXISTS standings (
        user_id INTEGER NOT NULL, slot INTEGER NOT NULL, season INTEGER NOT NULL,
        league_id TEXT NOT NULL, club_id TEXT NOT NULL,
        played INTEGER NOT NULL DEFAULT 0, wins INTEGER NOT NULL DEFAULT 0,
        draws INTEGER NOT NULL DEFAULT 0, losses INTEGER NOT NULL DEFAULT 0,
        gf INTEGER NOT NULL DEFAULT 0, ga INTEGER NOT NULL DEFAULT 0,
        points INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(user_id,slot,season,club_id),
        FOREIGN KEY(user_id,slot) REFERENCES careers(user_id,slot) ON DELETE CASCADE
      );
      CREATE INDEX IF NOT EXISTS standings_table ON standings(user_id,slot,season,league_id);
      CREATE TABLE IF NOT EXISTS season_reports (
        user_id INTEGER NOT NULL, slot INTEGER NOT NULL, season INTEGER NOT NULL,
        report_json TEXT NOT NULL, PRIMARY KEY(user_id,slot,season),
        FOREIGN KEY(user_id,slot) REFERENCES careers(user_id,slot) ON DELETE CASCADE
      );
    ''')
    init_engine_db(c)
    for item in REGISTRY['leagues']:
        c.execute('''INSERT OR IGNORE INTO league_catalog
         (id,country,association,region,name,tier,intended_clubs,groups_json) VALUES(?,?,?,?,?,?,?,?)''',
         (item['league_id'], item['country_ru'],item['association_code'],item['region'],
          item['competition'],item['tier_order'],item['club_slots'],json.dumps(item.get('groups',[]))))
        c.execute('UPDATE league_catalog SET intended_clubs=? WHERE id=?', (item['club_slots'],item['league_id']))


def game_budgets(league_id:str, strength:int) -> tuple[int,int]:
    """Game economy, explicitly NOT official clubs' financial disclosures."""
    tier = LEAGUES[league_id]['tier_order']
    assoc = LEAGUES[league_id]['association_code']
    elite = {'ENG','ESP','GER','ITA','FRA'}
    premier = 125_000_000 if assoc in elite else 38_000_000
    if assoc in {'BRA','ARG','USA','MEX','KSA'}: premier = 45_000_000
    size = max(4_000_000, premier / (2.8 ** (tier - 1)))
    bonus = max(.55, min(1.7, .65 + strength / 100))
    cash = int(size * bonus / 100_000) * 100_000
    return cash, int(cash * .30 / 100_000) * 100_000


def refresh_world(c, uid:int, slot:int, season:int):
    """Freeze the local offline club catalog into this save; safe to call repeatedly.
    Unknown league participants are never created under fake names.
    """
    # Freeze the catalog membership at save creation. Later catalog updates affect NEW saves only.
    if not c.execute('SELECT 1 FROM world_clubs WHERE user_id=? AND slot=? LIMIT 1',(uid,slot)).fetchone():
        c.execute('''INSERT OR IGNORE INTO world_clubs(user_id,slot,club_id,league_id,budget_eur,transfer_eur,strength)
          SELECT ?,?,id,league_id,base_budget_eur,base_transfer_eur,strength FROM club_catalog''',(uid,slot))
    c.execute('''INSERT OR IGNORE INTO standings(user_id,slot,season,league_id,club_id)
      SELECT user_id,slot,?,league_id,club_id FROM world_clubs WHERE user_id=? AND slot=?''', (season,uid,slot))
    ensure_game_world(c,uid,slot,season)


def league_table(c, uid:int, slot:int, season:int, league_id:str, group_no:int|None=None):
    group_join=(' JOIN game_group_memberships gm ON gm.user_id=s.user_id AND gm.slot=s.slot '
                'AND gm.season=s.season AND gm.club_id=s.club_id AND gm.league_id=s.league_id') if group_no else ''
    extra=' AND gm.group_no=?' if group_no else ''
    args=(uid,slot,season,league_id,group_no) if group_no else (uid,slot,season,league_id)
    rows = c.execute('''SELECT s.*, cc.name, wc.budget_eur,wc.transfer_eur
     FROM standings s JOIN club_catalog cc ON cc.id=s.club_id
     JOIN world_clubs wc ON (wc.user_id=s.user_id AND wc.slot=s.slot AND wc.club_id=s.club_id)'''
     +group_join+''' WHERE s.user_id=? AND s.slot=? AND s.season=? AND s.league_id=?'''
     +extra+''' ORDER BY s.points DESC,(s.gf-s.ga) DESC,s.gf DESC,cc.name ASC''',args).fetchall()
    return [{**dict(r),'rank':i+1,'goal_difference':r['gf']-r['ga']} for i,r in enumerate(rows)]


def _rng(uid:int,slot:int,season:int,league:str):
    key=f'VELTON-{uid}-{slot}-{season}-{league}'.encode()
    return random.Random(int.from_bytes(hashlib.sha256(key).digest()[:8], 'big'))


def _score(rng, a, b):
    # Bounded strength-based goal model. Deterministic per save/season for replay protection.
    difference = (a-b)/30
    def goals(boost):
        avg=max(.3,min(3.1, 1.15 + boost))
        return min(8, sum(rng.random()<min(.88,avg/4) for _ in range(4)) + (rng.random()<max(0,avg-2.5)/3))
    return int(goals(.27+difference)),int(goals(-difference))


def _playoff_winner(qualifiers:list,rng:random.Random):
    """Qualification by league position; simulated knockout matches, ties favor better seed."""
    def match(a,b):
        ga,gb=_score(rng,75-a['rank']*.5,75-b['rank']*.5)
        return a if ga>gb or (ga==gb and a['rank']<b['rank']) else b
    if len(qualifiers)==6:
        # 2026/27 Championship: 5 v 8 and 6 v 7, then 3/4 enter semis.
        won=[match(qualifiers[2],qualifiers[5]),match(qualifiers[3],qualifiers[4])]
        won.sort(key=lambda x:x['rank'])
        finalists=[match(qualifiers[0],won[-1]),match(qualifiers[1],won[0])]
    else:
        finalists=[match(qualifiers[0],qualifiers[3]),match(qualifiers[1],qualifiers[2])]
    return match(*finalists)


def simulate_all(c, uid:int,slot:int,season:int, my_club:str|None=None):
    """Simulate every imported league. Standings remain archived under the old season.
    Membership transfers are computed from original tables before any club moves.
    """
    refresh_world(c,uid,slot,season)
    original = c.execute('SELECT club_id,league_id,strength FROM world_clubs WHERE user_id=? AND slot=?', (uid,slot)).fetchall()
    by_league=defaultdict(list)
    for r in original: by_league[r['league_id']].append(dict(r))
    # Match outcomes already exist in the fixture log; close remaining games only.
    play_until(c,uid,slot,season,12,force=True)
    movements=[]
    memberships={r['club_id']:r['league_id'] for r in original}
    by_association=defaultdict(list)
    for lid in by_league:
        by_association[LEAGUES[lid]['association_code']].append(lid)
    for assoc,lids in by_association.items():
        if assoc in NO_PROMOTION: continue
        levels={LEAGUES[lid]['tier_order']:lid for lid in lids}
        for tier,upper in sorted(levels.items()):
            lower=levels.get(tier+1)
            if not lower:continue
            u=league_table(c,uid,slot,season,upper)
            l=league_table(c,uid,slot,season,lower)
            # Never label promotions as official; no play-offs in this game-rule model.
            if len(u)<4 or len(l)<4:continue
            playoff_ids=set()
            if assoc=='ENG' and len(u)>=10 and len(l)>=10:
                # 2026/27 Championship: top two automatically; 3rd–8th contest six-team play-offs.
                # League One to Championship: top two and 3rd–6th play-off winner.
                rng=_rng(uid,slot,season,lower+'-playoffs')
                bracket=l[2:8] if tier==1 else l[2:6]
                winner=_playoff_winner(bracket,rng) if len(bracket)>=4 else None
                promoted=l[:2]+([winner] if winner else [])
                relegated=u[-len(promoted):]
                if winner:playoff_ids.add(winner['club_id'])
            elif assoc=='GER' and len(u)>=10 and len(l)>=10:
                promoted=l[:2];relegated=u[-2:]
                # 16th in the Bundesliga versus 3rd in Bundesliga 2 (simulated two-legged tie).
                rng=_rng(uid,slot,season,lower+'-playoff')
                a,b=_score(rng,l[2]['points']//6+60,u[-3]['points']//6+60)
                c_,d=_score(rng,u[-3]['points']//6+60,l[2]['points']//6+60)
                if a+d>b+c_ or (a+d==b+c_ and rng.random()<.5):
                    promoted.append(l[2]);relegated.append(u[-3]);playoff_ids.add(l[2]['club_id'])
            else:
                count=min(2,len(u)//4,len(l)//4)
                # In multi-group leagues, promoted teams must represent their
                # groups instead of simply sorting incompatible point totals.
                num_groups=c.execute('''SELECT COUNT(DISTINCT group_no) FROM game_group_memberships
                 WHERE user_id=? AND slot=? AND season=? AND league_id=?''',
                 (uid,slot,season,lower)).fetchone()[0]
                if num_groups>1:
                    group_winners=[league_table(c,uid,slot,season,lower,g)[0]
                        for g in range(1,num_groups+1)
                        if league_table(c,uid,slot,season,lower,g)]
                    promoted=group_winners[:count]
                else:
                    promoted=l[:count]
                relegated=u[-len(promoted):]
            for rec in promoted:
                memberships[rec['club_id']]=upper
                movements.append({'club':rec['name'],'club_id':rec['club_id'],'from':lower,'to':upper,
                                  'type':'promotion','via':'playoff' if rec['club_id'] in playoff_ids else 'table'})
            for rec in relegated:
                memberships[rec['club_id']]=lower
                movements.append({'club':rec['name'],'club_id':rec['club_id'],'from':upper,'to':lower,
                                  'type':'relegation','via':'playoff' if rec in u[-3:-2] and playoff_ids else 'table'})
    league_summaries=[]
    for lid in sorted(by_league):
        table=league_table(c,uid,slot,season,lid)
        if not table: continue
        league_summaries.append({'league_id':lid,'league':LEAGUES[lid]['competition'],
           'clubs':len(table),'champion':table[0]['name'],'top_points':table[0]['points'],
           'matches_played':sum(t['played'] for t in table)//2})
    # Game income and modeled 40-week wages (never real club financial figures).
    finance={}
    position={}
    for lid in sorted(by_league):
        for rec in league_table(c,uid,slot,season,lid):
            position[rec['club_id']]=(rec['rank'],len(by_league[lid]))
    for row in original:
        dest=memberships[row['club_id']]
        game=c.execute('''SELECT wins,draws,played FROM standings WHERE user_id=? AND slot=? AND season=? AND club_id=?''',
                       (uid,slot,season,row['club_id'])).fetchone()
        rank,total=position.get(row['club_id'],(1,1))
        league=LEAGUES[row['league_id']]
        elite=league['association_code'] in {'ENG','ESP','GER','ITA','FRA'}
        base=(58_000_000 if elite else 19_000_000)/(3.4**(league['tier_order']-1))
        prize=round(base*(.28+.72*(total-rank+1)/total)/100_000)*100_000
        match_income=(game['wins']*480_000+game['draws']*160_000) if game else 0
        wages=c.execute('''SELECT COALESCE(SUM(wage_eur),0) weekly FROM world_players
                  WHERE user_id=? AND slot=? AND club_id=?''',(uid,slot,row['club_id'])).fetchone()['weekly']*40
        prev=c.execute('''SELECT budget_eur,transfer_eur FROM world_clubs WHERE user_id=? AND slot=? AND club_id=?''',
                       (uid,slot,row['club_id'])).fetchone()
        balance=max(0,prev['budget_eur']+prize+match_income-wages)
        transfer_budget=min(balance,prev['transfer_eur']+prize//5+match_income//4)
        c.execute('''UPDATE world_clubs SET league_id=?,budget_eur=?,transfer_eur=?
               WHERE user_id=? AND slot=? AND club_id=?''',(dest,balance,transfer_budget,uid,slot,row['club_id']))
        if row['club_id']==my_club:
            finance={'opening_balance':prev['budget_eur'],'prize_eur':prize,'match_income_eur':match_income,
                'wages_eur':wages,'closing_balance':balance,
                'closing_transfer_eur':transfer_budget,'rank':rank,'clubs':total}
    return {'league_summaries':league_summaries,'movements':movements,'my_finance':finance,
            'simulated_leagues':len(league_summaries), 'clubs':len(original),
            'game_rules':'England: two automatic + simulated play-off winner; Germany: two automatic + simulated relegation play-off. Other leagues: simplified top/bottom 2 (group leaders in multi-group lower divisions); groups use a modelled draw, not official geography.'}


def standings_preview(c,uid:int,slot:int,season:int,league_id:str|None=None):
    present=c.execute('''SELECT league_id,COUNT(*) n FROM standings
      WHERE user_id=? AND slot=? AND season=? GROUP BY league_id ORDER BY league_id''', (uid,slot,season)).fetchall()
    if not present:
        return {'leagues':[], 'selected':None, 'rows':[], 'notice':'База клубов пуста. Добавьте локальный JSON-пакет в world_data/packs.'}
    selected = league_id if league_id in {r['league_id'] for r in present} else present[0]['league_id']
    group_n=c.execute('''SELECT MAX(group_no) n FROM game_group_memberships
       WHERE user_id=? AND slot=? AND season=? AND league_id=?''',(uid,slot,season,selected)).fetchone()['n'] or 1
    grouped=[{'number':i,'rows':league_table(c,uid,slot,season,selected,i)}
        for i in range(1,group_n+1)] if group_n>1 else []
    return {'leagues':[{'id':r['league_id'],'name':LEAGUES[r['league_id']]['competition'],'clubs':r['n']} for r in present],
            'selected':selected,'rows':league_table(c,uid,slot,season,selected),'groups':grouped,
            'notice':'Группы распределены игровым жеребьёвочным алгоритмом, не официальной географией.' if grouped else None}


def seed_verified_english_clubs(c):
    """Public 2026/27 published clubs; limited confirmed named PL players.
    This seed is a factual starter set, not all of the 1,499 target clubs/rosters.
    Existing imported/provider-owned records are never overwritten.
    """
    path=Path(__file__).resolve().parent/'world_data/verified_england_2026.json'
    data=json.loads(path.read_text(encoding='utf-8'))
    for lid,teams in data['leagues'].items():
        for index,entry in enumerate(teams):
            club_id=f'official:{lid}:{index:02}'
            strength=66 + (int.from_bytes(hashlib.sha256(entry['name'].encode()).digest()[:2],'big')%19) - LEAGUES[lid]['tier_order']*4
            budget,transfer=game_budgets(lid,strength)
            # An API-provider club may have a slightly different provider name; do not duplicate identical names.
            if c.execute('SELECT 1 FROM club_catalog WHERE league_id=? AND lower(name)=lower(?)',(lid,entry['name'])).fetchone():
                continue
            c.execute('''INSERT OR IGNORE INTO club_catalog(id,league_id,name,provider_id,strength,
                base_budget_eur,base_transfer_eur,source,synced_at) VALUES(?,?,?,?,?,?,?,?,?)''',
                (club_id,lid,entry['name'],None,strength,budget,transfer,
                 'Official 2026/27 league roster' if lid=='ENG_1' else '2026/27 Championship club listing', '2026-11-14'))
            for k,name in enumerate(entry.get('players',[])):
                player_id=f'official:{lid}:{index:02}:{k:03}'
                c.execute('''INSERT OR IGNORE INTO player_catalog(id,club_id,name,position,age,nationality,
                  provider_id,source,synced_at) VALUES(?,?,?,?,?,?,?,?,?)''',
                  (player_id,club_id,name,None,None,None,None,'Premier League 2026/27 squad numbers','2026-11-14'))

def seed_verified_expansion(c):
    """2026/27 club participants and selected first-team squads from league/club sites."""
    data=json.loads((Path(__file__).resolve().parent/'world_data/verified_expansion_2026.json').read_text(encoding='utf-8'))
    for lid,names in data['leagues'].items():
        for index,name in enumerate(names):
            existing=c.execute('SELECT id FROM club_catalog WHERE league_id=? AND lower(name)=lower(?)',(lid,name)).fetchone()
            club_id=existing['id'] if existing else f'verified:{lid}:{index:02}'
            if not existing:
                seed=int.from_bytes(hashlib.sha256(name.encode()).digest()[:2],'big')
                strength=65+seed%20-LEAGUES[lid]['tier_order']*3
                budget,transfer=game_budgets(lid,strength)
                c.execute('''INSERT OR IGNORE INTO club_catalog
                  (id,league_id,name,provider_id,strength,base_budget_eur,base_transfer_eur,source,synced_at)
                  VALUES(?,?,?,?,?,?,?,?,?)''',(club_id,lid,name,None,strength,budget,transfer,data['league_sources'][lid],data['retrieved']))
            for position,players in data['squads'].get(name,{}).items():
                for j,player in enumerate(players):
                    pid=f'verified:{lid}:{index:02}:{position}:{j:02}'
                    c.execute('''INSERT OR IGNORE INTO player_catalog
                     (id,club_id,name,position,age,nationality,provider_id,source,synced_at)
                     VALUES(?,?,?,?,?,?,?,?,?)''',(pid,club_id,player,position,None,None,None,
                         data['player_sources'][name],data['retrieved']))
