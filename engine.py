"""VELTON v0.4: per-save, persistent football fixtures, game-scored matches and transfers.

Facts (clubs and names) come from sourced catalog rows; ratings, games, prices and
results are entirely fictional simulation values. None of the game results are real fixtures.
"""
from __future__ import annotations
import hashlib, json, math, random
from collections import defaultdict
from datetime import datetime, timezone


def init_engine_db(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS world_players (
      user_id INTEGER NOT NULL, slot INTEGER NOT NULL, player_id TEXT NOT NULL,
      club_id TEXT NOT NULL, rating INTEGER NOT NULL, value_eur INTEGER NOT NULL,
      wage_eur INTEGER NOT NULL, appearances INTEGER NOT NULL DEFAULT 0,
      goals INTEGER NOT NULL DEFAULT 0, assists INTEGER NOT NULL DEFAULT 0,
      contract_until_season INTEGER NOT NULL DEFAULT 4,
      PRIMARY KEY(user_id,slot,player_id),
      FOREIGN KEY(user_id,slot) REFERENCES careers(user_id,slot) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_world_players_club ON world_players(user_id,slot,club_id);
    CREATE TABLE IF NOT EXISTS game_fixtures (
      user_id INTEGER NOT NULL, slot INTEGER NOT NULL, season INTEGER NOT NULL,
      league_id TEXT NOT NULL, round INTEGER NOT NULL, match_number INTEGER NOT NULL,
      home_id TEXT NOT NULL, away_id TEXT NOT NULL, home_goals INTEGER, away_goals INTEGER,
      scorers_json TEXT NOT NULL DEFAULT '[]',
      PRIMARY KEY(user_id,slot,season,league_id,round,match_number),
      FOREIGN KEY(user_id,slot) REFERENCES careers(user_id,slot) ON DELETE CASCADE,
      CHECK (home_id!=away_id)
    );
    CREATE INDEX IF NOT EXISTS idx_game_fixtures_progress ON game_fixtures(user_id,slot,season,league_id,round);
    CREATE TABLE IF NOT EXISTS game_group_memberships (
      user_id INTEGER NOT NULL, slot INTEGER NOT NULL, season INTEGER NOT NULL,
      league_id TEXT NOT NULL, club_id TEXT NOT NULL, group_no INTEGER NOT NULL,
      PRIMARY KEY(user_id,slot,season,club_id),
      FOREIGN KEY(user_id,slot) REFERENCES careers(user_id,slot) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_game_groups ON game_group_memberships(user_id,slot,season,league_id,group_no);
    CREATE TABLE IF NOT EXISTS game_player_seasons (
      user_id INTEGER NOT NULL, slot INTEGER NOT NULL, season INTEGER NOT NULL,
      player_id TEXT NOT NULL, goals INTEGER NOT NULL DEFAULT 0,
      appearances INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(user_id,slot,season,player_id),
      FOREIGN KEY(user_id,slot) REFERENCES careers(user_id,slot) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS game_tactics (
      user_id INTEGER NOT NULL, slot INTEGER NOT NULL, club_id TEXT NOT NULL,
      tactic TEXT NOT NULL DEFAULT 'balanced',
      PRIMARY KEY(user_id,slot,club_id),
      FOREIGN KEY(user_id,slot) REFERENCES careers(user_id,slot) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS game_transfers (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL, slot INTEGER NOT NULL, season INTEGER NOT NULL,
      player_id TEXT NOT NULL, player_name TEXT NOT NULL,
      from_club TEXT NOT NULL, to_club TEXT NOT NULL,
      fee_eur INTEGER NOT NULL, agent_fee_eur INTEGER NOT NULL DEFAULT 0,
      kind TEXT NOT NULL DEFAULT 'user',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY(user_id,slot) REFERENCES careers(user_id,slot) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_transfers_save ON game_transfers(user_id,slot,season);
    ''')
    if 'group_no' not in {r['name'] for r in c.execute('PRAGMA table_info(game_fixtures)')}:
        c.execute('ALTER TABLE game_fixtures ADD COLUMN group_no INTEGER NOT NULL DEFAULT 1')
    if 'contract_until_season' not in {r['name'] for r in c.execute('PRAGMA table_info(world_players)')}:
        c.execute('ALTER TABLE world_players ADD COLUMN contract_until_season INTEGER NOT NULL DEFAULT 4')
    if 'kind' not in {r['name'] for r in c.execute('PRAGMA table_info(game_transfers)')}:
        c.execute("ALTER TABLE game_transfers ADD COLUMN kind TEXT NOT NULL DEFAULT 'user'")


def game_player_values(club_id, player_id, team_strength):
    """Generated gameplay parameters, not real wages/market valuations."""
    seed=int.from_bytes(hashlib.sha256(f'{club_id}|{player_id}'.encode()).digest()[:8], 'big')
    rating=max(45,min(92,team_strength-10+(seed%21)))
    value=int((.35+((rating-44)/46)**2*32)*1_000_000//100_000)*100_000
    wage=int((15_000+value/1000)//1_000)*1_000
    return rating,value,wage


def _fixture_pairs(ids, seed):
    teams=sorted(ids)
    rng=random.Random(seed)
    rng.shuffle(teams)
    if len(teams)%2: teams.append(None)
    if len(teams)<2:return []
    pivot=teams[0];rot=teams[1:];base=[]
    for round_idx in range(len(teams)-1):
        lineup=[pivot]+rot
        matchups=[]
        for i in range(len(teams)//2):
            a,b=lineup[i],lineup[-1-i]
            if a is None or b is None:continue
            if (round_idx+i)%2==0:matchups.append((a,b))
            else:matchups.append((b,a))
        base.append(matchups)
        rot=[rot[-1]]+rot[:-1]
    return base + [[(b,a) for a,b in round_games] for round_games in base]


def ensure_game_world(c,uid,slot,season):
    """Idempotent. Global catalog imports are cloned; existing save transfers persist."""
    # Seed only ONCE per save; later catalog imports must not alter an ongoing career.
    if not c.execute('SELECT 1 FROM world_players WHERE user_id=? AND slot=? LIMIT 1',(uid,slot)).fetchone():
        rows=c.execute('''SELECT pc.id,pc.club_id,cl.strength FROM player_catalog pc
          JOIN club_catalog cl ON cl.id=pc.club_id
          JOIN world_clubs wc ON wc.club_id=pc.club_id AND wc.user_id=? AND wc.slot=?
          WHERE NOT EXISTS (SELECT 1 FROM roster_verified_clubs vr WHERE vr.club_id=pc.club_id) OR pc.confirmed_2627=1''',(uid,slot)).fetchall()
        for p in rows:
            rating,value,wage=game_player_values(p['club_id'],p['id'],p['strength'])
            contract=2+int.from_bytes(hashlib.sha256(p['id'].encode()).digest()[:1],'big')%5
            c.execute('''INSERT OR IGNORE INTO world_players(user_id,slot,player_id,club_id,rating,value_eur,wage_eur,contract_until_season)
              VALUES(?,?,?,?,?,?,?,?)''',(uid,slot,p['id'],p['club_id'],rating,value,wage,contract))
    # Career-created footballer exists in the save only, NOT in official player catalog.
    career=c.execute('SELECT * FROM careers WHERE user_id=? AND slot=?',(uid,slot)).fetchone()
    if career and career['role']=='player' and career['club_id']:
        key=f'career:{uid}:{slot}'
        skill=json.loads(career['metrics_json'])['skill']
        rating=max(40,min(92,int(skill)))
        c.execute('''INSERT OR IGNORE INTO world_players(user_id,slot,player_id,club_id,rating,value_eur,wage_eur)
            VALUES(?,?,?,?,?,?,?)''',(uid,slot,key,career['club_id'],rating,3_000_000,25_000))
    # Multi-group tournaments play home/away WITHIN their groups, not a fictitious
    # 40- or 60-team single round robin. Group assignments are a saved game draw;
    # historical official geographical assignments are not asserted.
    from world import LEAGUES
    current_leagues=c.execute('''SELECT league_id,COUNT(*) n
       FROM world_clubs WHERE user_id=? AND slot=? GROUP BY league_id''',(uid,slot)).fetchall()
    for league in current_leagues:
        lid=league['league_id']
        existing=c.execute('''SELECT 1 FROM game_fixtures WHERE user_id=? AND slot=? AND season=? AND league_id=? LIMIT 1''',
                           (uid,slot,season,lid)).fetchone()
        if existing:continue
        club_rows=c.execute('''SELECT club_id FROM world_clubs WHERE user_id=? AND slot=? AND league_id=? ORDER BY club_id''',
                            (uid,slot,lid)).fetchall()
        if len(club_rows)<2:continue
        ids=[r['club_id'] for r in club_rows]
        seed=int.from_bytes(hashlib.sha256(f'{uid}:{slot}:{season}:{lid}'.encode()).digest()[:8],'big')
        declared=LEAGUES[lid].get('groups') or []
        if len(declared)>1 and len(ids)>=2*len(declared):
            ordered=sorted(ids)
            random.Random(seed).shuffle(ordered)
            if len(ordered)==sum(declared):
                groups=[];offset=0
                for size in declared:
                    groups.append(ordered[offset:offset+size]);offset+=size
            else:
                # Partial historic league; keep group sizes balanced without inventing entrants.
                groups=[ordered[i::len(declared)] for i in range(len(declared))]
        else:
            groups=[ids]
        by_round=defaultdict(list)
        for group_no, group in enumerate(groups,1):
            c.executemany('''INSERT OR IGNORE INTO game_group_memberships
              (user_id,slot,season,league_id,club_id,group_no) VALUES(?,?,?,?,?,?)''',
              [(uid,slot,season,lid,cid,group_no) for cid in group])
            for round_no,matches in enumerate(_fixture_pairs(group,seed+group_no),1):
                for a,b in matches:by_round[round_no].append((group_no,a,b))
        for round_no in sorted(by_round):
            c.executemany('''INSERT OR IGNORE INTO game_fixtures
              (user_id,slot,season,league_id,round,match_number,home_id,away_id,group_no)
              VALUES(?,?,?,?,?,?,?,?,?)''',
              [(uid,slot,season,lid,round_no,i+1,a,b,group_no)
               for i,(group_no,a,b) in enumerate(by_round[round_no])])


def _score_game(rng, h_strength,a_strength,h_tactic,a_tactic):
    # Allow meaningful tactical trade-offs, plus default home advantage.
    modifiers={'balanced':(0.,0.),'attack':(.35,.25),'defend':(-.18,-.32)}
    h_att,h_con=modifiers.get(h_tactic,(0.,0.))
    a_att,a_con=modifiers.get(a_tactic,(0.,0.))
    delta=max(-1.15,min(1.15,(h_strength-a_strength)/26))
    def goals(expect):
        # Low-scoring bounded distribution via Bernoulli sum.
        p=max(.055,min(.88,expect/5))
        return min(7,sum(rng.random()<p for _ in range(5)))
    return goals(1.65+delta+h_att+a_con),goals(1.22-delta+a_att+h_con)


def _team_power(c,uid,slot,club_id):
    row=c.execute('SELECT strength FROM world_clubs WHERE user_id=? AND slot=? AND club_id=?',
                  (uid,slot,club_id)).fetchone()
    if not row:return 60
    vals=[r['rating'] for r in c.execute('''SELECT rating FROM world_players
      WHERE user_id=? AND slot=? AND club_id=? ORDER BY rating DESC LIMIT 11''',(uid,slot,club_id))]
    # Less than 6 verified players -> rely mainly on known club strength; never invent squad entries.
    bonus=(sum(vals)/len(vals)-68)*.2 if len(vals)>=6 else 0
    return row['strength']+bonus


def goal_scoring_weight(position: str | None) -> float:
    """Game-only goal probability factor for both older VELTON and FIFA/CSV positions.

    A GK should not be as likely to score as a forward. This is a gameplay
    heuristic and is unrelated to real-world player attributes or results.
    """
    pos=str(position or '').upper().strip()
    if pos in {'GK','G','GOALKEEPER','KEEPER'}:
        return .015
    if pos in {'DF','D','DEF','DEFENDER','DEFENCE','DEFENSE'}:
        return .35
    if pos in {'MF','M','MID','MIDFIELDER','MIDFIELD'}:
        return 1.10
    if pos in {'FW','F','FWD','ATT','ATTACKER','FORWARD','STRIKER','ST'}:
        return 2.70
    # Unspecified position is genuinely unknown; don't assert a striker.
    return .65


def _scorers(c,uid,slot,season,club_id,number,rng):
    candidates=c.execute('''SELECT wp.player_id,wp.rating,coalesce(pc.name,cr.name,'Футболист') name,coalesce(pc.position,'') position
      FROM world_players wp LEFT JOIN player_catalog pc ON pc.id=wp.player_id
      LEFT JOIN careers cr ON wp.player_id=('career:'||cr.user_id||':'||cr.slot) AND cr.user_id=wp.user_id AND cr.slot=wp.slot
      WHERE wp.user_id=? AND wp.slot=? AND wp.club_id=? ORDER BY wp.rating DESC LIMIT 18''',
      (uid,slot,club_id)).fetchall()
    result=[]
    # The player character may be below the top 18 professionals in a star club.
    # Include them explicitly, then guarantee a place among the eleven starters.
    avatar=f'career:{uid}:{slot}'
    own=next((p for p in candidates if p['player_id']==avatar),None)
    if own is None:
        avatar_player=c.execute('SELECT rating,club_id FROM world_players WHERE user_id=? AND slot=? AND player_id=?',
                                (uid,slot,avatar)).fetchone()
        if avatar_player and avatar_player['club_id']==club_id:
            career=c.execute('SELECT name FROM careers WHERE user_id=? AND slot=?',(uid,slot)).fetchone()
            own={'player_id':avatar,'rating':avatar_player['rating'],'name':career['name'], 'position':'ATT'}
            candidates=list(candidates)+[own]
    if own and own not in candidates[:11]:
        candidates=list(candidates[:10])+[own]+list(candidates[11:])
    if candidates:
        # Only known names or player character are eligible for recorded scorer; otherwise goals remain unattributed.
        weighted=[]
        for row in candidates:
            weighted.append(max(.01,goal_scoring_weight(row['position'])*row['rating']/65))
        for _ in range(number):
            scorer=rng.choices(candidates,weights=weighted,k=1)[0]
            c.execute('''UPDATE world_players SET goals=goals+1 WHERE user_id=? AND slot=? AND player_id=?''',
                      (uid,slot,scorer['player_id']))
            c.execute('''INSERT INTO game_player_seasons(user_id,slot,season,player_id,goals)
                 VALUES(?,?,?,?,1) ON CONFLICT(user_id,slot,season,player_id) DO UPDATE SET goals=goals+1''',
                 (uid,slot,season,scorer['player_id']))
            result.append({'player_id':scorer['player_id'],'name':scorer['name'],'club_id':club_id})
        for row in candidates[:11]:
            c.execute('''UPDATE world_players SET appearances=appearances+1 WHERE user_id=? AND slot=? AND player_id=?''',
                      (uid,slot,row['player_id']))
            c.execute('''INSERT INTO game_player_seasons(user_id,slot,season,player_id,appearances)
                 VALUES(?,?,?,?,1) ON CONFLICT(user_id,slot,season,player_id) DO UPDATE SET appearances=appearances+1''',
                 (uid,slot,season,row['player_id']))
    return result


def _apply_result(c,fixture,h,a,goals):
    uid,slot,season=fixture['user_id'],fixture['slot'],fixture['season']
    for club_id,gf,ga in ((fixture['home_id'],h,a),(fixture['away_id'],a,h)):
        c.execute('''UPDATE standings SET played=played+1,gf=gf+?,ga=ga+?,
          wins=wins+?, draws=draws+?, losses=losses+?,points=points+?
          WHERE user_id=? AND slot=? AND season=? AND club_id=?''',
          (gf,ga,int(gf>ga),int(gf==ga),int(gf<ga),3 if gf>ga else 1 if gf==ga else 0,uid,slot,season,club_id))
    c.execute('''UPDATE game_fixtures SET home_goals=?,away_goals=?,scorers_json=?
      WHERE user_id=? AND slot=? AND season=? AND league_id=? AND round=? AND match_number=?''',
      (h,a,json.dumps(goals,ensure_ascii=False),uid,slot,season,fixture['league_id'],fixture['round'],fixture['match_number']))


def play_until(c,uid,slot,season,turn=12,force=False):
    """Play all scheduled matches up to the given season milestone, once and only once."""
    ensure_game_world(c,uid,slot,season)
    if not 1<=turn<=12:raise ValueError('Season turn out of range')
    progress=c.execute('''SELECT league_id,MAX(round) AS total FROM game_fixtures
       WHERE user_id=? AND slot=? AND season=? GROUP BY league_id''',(uid,slot,season)).fetchall()
    output=[]
    for lg in progress:
        maximum=int(lg['total']); cut=maximum if force else math.ceil(maximum*turn/12)
        pending=c.execute('''SELECT * FROM game_fixtures WHERE user_id=? AND slot=? AND season=? AND league_id=?
            AND round<=? AND home_goals IS NULL ORDER BY round,match_number''',(uid,slot,season,lg['league_id'],cut)).fetchall()
        for f in pending:
            key=f"{uid}:{slot}:{season}:{lg['league_id']}:{f['round']}:{f['match_number']}"
            seed=int.from_bytes(hashlib.sha256(key.encode()).digest()[:8],'big')
            rng=random.Random(seed)
            tactics={r['club_id']:r['tactic'] for r in c.execute('SELECT club_id,tactic FROM game_tactics WHERE user_id=? AND slot=?',(uid,slot))}
            h,a=_score_game(rng,_team_power(c,uid,slot,f['home_id']),_team_power(c,uid,slot,f['away_id']),tactics.get(f['home_id'],'balanced'),tactics.get(f['away_id'],'balanced'))
            scorers=_scorers(c,uid,slot,season,f['home_id'],h,rng)+_scorers(c,uid,slot,season,f['away_id'],a,rng)
            _apply_result(c,f,h,a,scorers)
            output.append({'league_id':lg['league_id'],'round':f['round'],'home_id':f['home_id'],'away_id':f['away_id'],'home_goals':h,'away_goals':a})
    return output


def fixture_list(c,uid,slot,season,league_id=None,club_id=None,limit=40):
    conditions=['f.user_id=?','f.slot=?','f.season=?'];params=[uid,slot,season]
    if league_id:conditions.append('f.league_id=?');params.append(league_id)
    if club_id:conditions.append('(f.home_id=? OR f.away_id=?)');params.extend((club_id,club_id))
    where=' AND '.join(conditions)
    rows=c.execute(f'''SELECT f.*,h.name home,a.name away FROM game_fixtures f
        JOIN club_catalog h ON h.id=f.home_id JOIN club_catalog a ON a.id=f.away_id
        WHERE {where} ORDER BY f.round,f.match_number LIMIT ?''',(*params,limit)).fetchall()
    return [{**dict(r),'scorers':json.loads(r['scorers_json'])} for r in rows]


def club_roster(c,uid,slot,club_id):
    return [dict(r) for r in c.execute('''SELECT wp.player_id,wp.club_id,wp.rating,wp.value_eur,wp.wage_eur,
      wp.goals,wp.appearances,wp.contract_until_season,coalesce(pc.name,cr.name,'Футболист') name,
      pc.position,pc.age,pc.source
      FROM world_players wp LEFT JOIN player_catalog pc ON pc.id=wp.player_id
      LEFT JOIN careers cr ON wp.player_id=('career:'||cr.user_id||':'||cr.slot) AND cr.user_id=wp.user_id AND cr.slot=wp.slot
      WHERE wp.user_id=? AND wp.slot=? AND wp.club_id=? ORDER BY wp.rating DESC,wp.player_id''',
      (uid,slot,club_id))]


def transfer(c,uid,slot,season,role,player_id,target_club_id,offer_eur):
    player=c.execute('''SELECT wp.*,coalesce(pc.name,cr.name,'Футболист') name
      FROM world_players wp LEFT JOIN player_catalog pc ON pc.id=wp.player_id
      LEFT JOIN careers cr ON wp.player_id=('career:'||cr.user_id||':'||cr.slot) AND cr.user_id=wp.user_id AND cr.slot=wp.slot
      WHERE wp.user_id=? AND wp.slot=? AND wp.player_id=?''',(uid,slot,player_id)).fetchone()
    if not player:raise ValueError('Игрок не найден в этом сохранении')
    if player_id.startswith('career:'):raise ValueError('Перевод главного героя оформляется отдельно')
    origin=player['club_id']
    if origin==target_club_id:raise ValueError('Игрок уже выступает за этот клуб')
    buyer=c.execute('SELECT * FROM world_clubs WHERE user_id=? AND slot=? AND club_id=?',(uid,slot,target_club_id)).fetchone()
    seller=c.execute('SELECT * FROM world_clubs WHERE user_id=? AND slot=? AND club_id=?',(uid,slot,origin)).fetchone()
    if not buyer or not seller:raise ValueError('Неизвестный покупатель или продавец')
    if not 100_000 <= offer_eur <= 2_000_000_000 or offer_eur%100_000:
        raise ValueError('Предложение должно быть от €100 тыс. до €2 млрд с шагом €100 тыс.')
    if offer_eur < int(math.ceil(player['value_eur']*1.15/100000))*100000:
        raise ValueError('Клуб отклонил предложение: предложи не менее 115% игровой стоимости')
    if buyer['transfer_eur']<offer_eur or buyer['budget_eur']<offer_eur:
        raise ValueError('Недостаточный баланс или трансферный бюджет клуба')
    commission=offer_eur//20 if role=='agent' else 0
    c.execute('''UPDATE world_clubs SET budget_eur=budget_eur-?,transfer_eur=transfer_eur-?
      WHERE user_id=? AND slot=? AND club_id=?''',(offer_eur,offer_eur,uid,slot,target_club_id))
    c.execute('''UPDATE world_clubs SET budget_eur=budget_eur+?,transfer_eur=transfer_eur+?
      WHERE user_id=? AND slot=? AND club_id=?''',(offer_eur-commission,offer_eur-commission,uid,slot,origin))
    c.execute('''UPDATE world_players SET club_id=?,contract_until_season=? WHERE user_id=? AND slot=? AND player_id=?''',
              (target_club_id,season+3,uid,slot,player_id))
    # A transfer has a lasting effect on competitive power, not just the UI.
    boost=max(1,int((player['rating']-48)/12))
    c.execute('''UPDATE world_clubs SET strength=MIN(95,strength+?) WHERE user_id=? AND slot=? AND club_id=?''',
              (boost,uid,slot,target_club_id))
    c.execute('''UPDATE world_clubs SET strength=MAX(32,strength-?) WHERE user_id=? AND slot=? AND club_id=?''',
              (boost,uid,slot,origin))
    c.execute('''INSERT INTO game_transfers(user_id,slot,season,player_id,player_name,from_club,to_club,fee_eur,agent_fee_eur)
      VALUES(?,?,?,?,?,?,?,?,?)''',(uid,slot,season,player_id,player['name'],origin,target_club_id,offer_eur,commission))
    return {'player':player['name'],'fee_eur':offer_eur,'commission_eur':commission,'from':origin,'to':target_club_id,'rating':player['rating']}



def ai_transfer_window(c,uid,slot,season,locked_club=None):
    '''Simulate finite AI transfers using ONLY real named players already in this save.

    Deterministic, guarded by season transition in server. The user's club is not
    controlled by AI. No external service and no invented players.
    '''
    if season <= 1:return []
    if c.execute("SELECT 1 FROM game_transfers WHERE user_id=? AND slot=? AND season=? AND kind='ai' LIMIT 1",(uid,slot,season)).fetchone():
        return []
    seed=int.from_bytes(hashlib.sha256(f'AI:{uid}:{slot}:{season}'.encode()).digest()[:8],'big')
    rng=random.Random(seed)
    clubs=[dict(r) for r in c.execute('''SELECT wc.club_id,wc.budget_eur,wc.transfer_eur,COUNT(wp.player_id) roster_count
        FROM world_clubs wc JOIN world_players wp
          ON wp.user_id=wc.user_id AND wp.slot=wc.slot AND wp.club_id=wc.club_id
        WHERE wc.user_id=? AND wc.slot=? AND wp.player_id NOT LIKE 'career:%'
        GROUP BY wc.club_id HAVING COUNT(wp.player_id)>=8''',(uid,slot))]
    rng.shuffle(clubs)
    moves=[]
    for buyer in clubs:
        if len(moves)>=min(6,max(1,len(clubs)//3)):break
        if buyer['club_id']==locked_club:continue
        sellers=[x for x in clubs if x['club_id'] not in (buyer['club_id'],locked_club) and x['roster_count']>=11]
        rng.shuffle(sellers)
        for seller in sellers:
            players=[dict(r) for r in c.execute('''SELECT wp.player_id,wp.value_eur FROM world_players wp
                JOIN player_catalog pc ON pc.id=wp.player_id
                WHERE wp.user_id=? AND wp.slot=? AND wp.club_id=? AND wp.rating BETWEEN 55 AND 90
                ORDER BY wp.player_id''',(uid,slot,seller['club_id']))]
            rng.shuffle(players)
            completed=False
            for p in players:
                fee=((p['value_eur']*12//10+99_999)//100_000)*100_000
                buyer_now=c.execute('''SELECT budget_eur,transfer_eur FROM world_clubs WHERE user_id=? AND slot=? AND club_id=?''',(uid,slot,buyer['club_id'])).fetchone()
                if fee>buyer_now['transfer_eur'] or fee>buyer_now['budget_eur']//3:continue
                try:deal=transfer(c,uid,slot,season,'ai',p['player_id'],buyer['club_id'],fee)
                except ValueError:continue
                c.execute("UPDATE game_transfers SET kind='ai' WHERE id=last_insert_rowid()")
                moves.append(deal)
                seller['roster_count']-=1
                completed=True
                break
            if completed:break
    return moves


def market_players(c,uid,slot,club_id=None,query='',limit=24):
    conditions=['wp.user_id=?','wp.slot=?','wp.player_id NOT LIKE ?'];args=[uid,slot,'career:%']
    if club_id:conditions.append('wp.club_id<>?');args.append(club_id)
    if query:conditions.append('pc.name LIKE ?');args.append('%'+query[:60]+'%')
    rows=c.execute('''SELECT wp.player_id,pc.name,pc.position,wp.club_id,cc.name club,
      wp.rating,wp.value_eur,wp.wage_eur,wp.contract_until_season FROM world_players wp
      JOIN player_catalog pc ON pc.id=wp.player_id JOIN club_catalog cc ON cc.id=wp.club_id
      WHERE '''+' AND '.join(conditions)+' ORDER BY wp.rating DESC,pc.name LIMIT ?',(*args,limit)).fetchall()
    return [dict(r) for r in rows]


def season_game_stats(c,uid,slot,season,club_id=None):
    top=[dict(r) for r in c.execute('''SELECT coalesce(pc.name,cr.name,'Футболист') name,ps.goals,ps.appearances,
      cc.name club FROM game_player_seasons ps
      JOIN world_players wp ON wp.user_id=ps.user_id AND wp.slot=ps.slot AND wp.player_id=ps.player_id
      LEFT JOIN player_catalog pc ON pc.id=ps.player_id
      LEFT JOIN careers cr ON ps.player_id=('career:'||cr.user_id||':'||cr.slot) AND cr.user_id=ps.user_id AND cr.slot=ps.slot
      JOIN club_catalog cc ON cc.id=wp.club_id
      WHERE ps.user_id=? AND ps.slot=? AND ps.season=? ORDER BY ps.goals DESC,ps.player_id LIMIT 10''',(uid,slot,season))]
    transfers=[dict(r) for r in c.execute('''SELECT t.*,src.name from_name,dst.name to_name
      FROM game_transfers t JOIN club_catalog src ON src.id=t.from_club JOIN club_catalog dst ON dst.id=t.to_club
      WHERE t.user_id=? AND t.slot=? AND t.season=? ORDER BY t.id DESC''',(uid,slot,season))]
    matchcount=c.execute('''SELECT COUNT(*) FROM game_fixtures WHERE user_id=? AND slot=? AND season=? AND home_goals IS NOT NULL''',
                        (uid,slot,season)).fetchone()[0]
    own=None
    if club_id:
        own=c.execute('''SELECT league_id,played,wins,draws,losses,gf,ga,points FROM standings
        WHERE user_id=? AND slot=? AND season=? AND club_id=?''',(uid,slot,season,club_id)).fetchone()
    return {'matches_played':matchcount,'top_scorers':top,'transfers':transfers,'own_club':dict(own) if own else None}
