"""VELTON API: server authoritative career decisions and Telegram login."""
from __future__ import annotations
import os, json, hmac, hashlib, sqlite3, time, re
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager, asynccontextmanager
from urllib.parse import parse_qsl
from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from game import ROLES, EVENTS, ACHIEVEMENTS, choose_event, event_view, resolve
from world import init_world_db, refresh_world, simulate_all, standings_preview, LEAGUES
from offline_catalog import seed_local_catalog, snapshot_hash
from verified_rosters import update_verified_catalog
from engine import play_until, ensure_game_world, fixture_list, club_roster, market_players, transfer, season_game_stats, ai_transfer_window

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / '.env')
DB_PATH = Path(os.getenv('DB_PATH', str(BASE / 'data' / 'velton.sqlite3')))
DEMO_MODE = os.getenv('DEMO_MODE', '0') == '1'
BOT_TOKEN = os.getenv('BOT_TOKEN', '').strip()
SESSION_MAX_AGE = 24 * 60 * 60


@contextmanager
def connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=15000')
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with connection() as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, display_name TEXT NOT NULL, username TEXT NOT NULL DEFAULT '',
          xp INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS careers (
          user_id INTEGER NOT NULL, slot INTEGER NOT NULL CHECK(slot BETWEEN 1 AND 5),
          role TEXT NOT NULL, name TEXT NOT NULL, place TEXT NOT NULL,
          turns INTEGER NOT NULL DEFAULT 0, metrics_json TEXT NOT NULL,
          event_index INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(user_id,slot), FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS awards (
          user_id INTEGER NOT NULL, award_id TEXT NOT NULL,
          awarded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY(user_id,award_id), FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS history (
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, slot INTEGER NOT NULL,
          role TEXT NOT NULL, title TEXT NOT NULL, choice TEXT NOT NULL,
          success INTEGER NOT NULL, changes_json TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS history_user ON history(user_id,id DESC);
        CREATE TABLE IF NOT EXISTS season_actions (
            user_id INTEGER NOT NULL, slot INTEGER NOT NULL, season INTEGER NOT NULL,
            turn INTEGER NOT NULL, title TEXT NOT NULL, choice TEXT NOT NULL,
            success INTEGER NOT NULL, delta_json TEXT NOT NULL,
            PRIMARY KEY(user_id,slot,season,turn),
            FOREIGN KEY(user_id,slot) REFERENCES careers(user_id,slot) ON DELETE CASCADE
        );
        ''')
        cols={r['name'] for r in conn.execute('PRAGMA table_info(careers)')}
        for name,sql in (
            ('season','ALTER TABLE careers ADD COLUMN season INTEGER NOT NULL DEFAULT 1'),
            ('season_turn','ALTER TABLE careers ADD COLUMN season_turn INTEGER NOT NULL DEFAULT 0'),
            ('phase',"ALTER TABLE careers ADD COLUMN phase TEXT NOT NULL DEFAULT 'playing'"),
            ('start_metrics_json',"ALTER TABLE careers ADD COLUMN start_metrics_json TEXT NOT NULL DEFAULT '{}'"),
            ('club_id','ALTER TABLE careers ADD COLUMN club_id TEXT')):
            if name not in cols:conn.execute(sql)
        if 'season' not in cols:
            conn.execute("""UPDATE careers SET season=CASE WHEN turns>0 AND turns%12=0 THEN turns/12 ELSE turns/12+1 END,
               season_turn=CASE WHEN turns>0 AND turns%12=0 THEN 12 ELSE turns%12 END,
               phase=CASE WHEN turns>0 AND turns%12=0 THEN 'ready' ELSE 'playing' END,
               start_metrics_json=metrics_json""")
        usercols={r['name'] for r in conn.execute('PRAGMA table_info(users)')}
        if 'seasons_completed' not in usercols:
            conn.execute('ALTER TABLE users ADD COLUMN seasons_completed INTEGER NOT NULL DEFAULT 0')
        if 'retired_careers' not in usercols:
            conn.execute('ALTER TABLE users ADD COLUMN retired_careers INTEGER NOT NULL DEFAULT 0')
        init_world_db(conn)
        seed_local_catalog(conn)
        update_verified_catalog(conn)

@asynccontextmanager
async def lifespan(_application):
    if not DEMO_MODE and not BOT_TOKEN:
        raise RuntimeError('Production requires BOT_TOKEN, or explicitly enable DEMO_MODE=1 for local previews')
    init_db()
    yield

app = FastAPI(title='VELTON Mini App API', version='0.9.0', docs_url='/api/docs' if DEMO_MODE else None, redoc_url=None, lifespan=lifespan)
app.mount('/static', StaticFiles(directory=str(BASE / 'static')), name='static')

@app.get('/')
def index():
    return FileResponse(BASE / 'static' / 'index.html')

@app.get('/api/config')
def config():
    return {"demo": DEMO_MODE, "version": "0.9", "max_slots": 5}

# Only Telegram's cryptographically signed raw initData is trusted in production.
def validate_telegram_init_data(data: str, token: str, now: int | None = None) -> dict:
    if not data or len(data) > 16384:
        raise ValueError('initData missing or too long')
    pairs = parse_qsl(data, keep_blank_values=True, strict_parsing=True)
    fields = dict(pairs)
    if len(pairs) != len(fields):
        raise ValueError('Duplicate initData fields')
    received = fields.get('hash', '')
    if not re.fullmatch(r'[a-fA-F0-9]{64}', received):
        raise ValueError('Missing signature')
    check_string = '\n'.join(f'{key}={value}' for key, value in sorted(pairs) if key != 'hash')
    secret = hmac.new(b'WebAppData', token.encode('utf-8'), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode('utf-8'), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(received.lower(), expected):
        raise ValueError('Signature mismatch')
    timestamp = int(fields.get('auth_date', 0))
    time_now = now if now is not None else int(time.time())
    if timestamp > time_now + 60 or time_now - timestamp > SESSION_MAX_AGE:
        raise ValueError('Telegram session is outdated')
    user = json.loads(fields.get('user', 'null'))
    if not isinstance(user, dict) or not isinstance(user.get('id'), int) or user['id'] <= 0:
        raise ValueError('No Telegram user')
    return user

def current_user(x_telegram_init_data: str = Header(default='', alias='X-Telegram-Init-Data')):
    if DEMO_MODE and not x_telegram_init_data:
        return {"id": 1, "first_name": "Демо-игрок", "username": "demo"}
    if not BOT_TOKEN:
        raise HTTPException(status_code=503, detail='BOT_TOKEN not configured')
    try:
        return validate_telegram_init_data(x_telegram_init_data, BOT_TOKEN)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=401, detail='Открой мини-приложение через Telegram, чтобы войти.')

def upsert_user(conn, user: dict):
    full_name = (user.get('first_name', '') + ' ' + user.get('last_name', '')).strip()[:70] or 'Игрок VELTON'
    username = str(user.get('username') or '')[:40]
    conn.execute('''INSERT INTO users(id,display_name,username) VALUES(?,?,?)
        ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name,username=excluded.username''',
        (user['id'], full_name, username))

def career_to_json(row, conn=None) -> dict:
    data = dict(row)
    metrics = json.loads(data['metrics_json'])
    phase=data.get('phase','playing')
    result={"slot": data['slot'], "role": data['role'], "name": data['name'], "place": data['place'],
            "turns": data['turns'], "week": min(12,data.get('season_turn',0)+1),
            "season": data.get('season',1), "phase":phase,
            "metrics": metrics, "club_id":data.get("club_id"),
            "event": event_view(data['role'], data['event_index']) if phase=='playing' else None}
    if conn is not None:
        if data.get('club_id'):
            budget=conn.execute('''SELECT wc.budget_eur,wc.transfer_eur,wc.league_id,cc.name
                FROM world_clubs wc JOIN club_catalog cc ON cc.id=wc.club_id
                WHERE wc.user_id=? AND wc.slot=? AND wc.club_id=?''',
                (data['user_id'],data['slot'],data['club_id'])).fetchone()
            result['my_club']=dict(budget) if budget else None
            if budget:
                tactic=conn.execute('SELECT tactic FROM game_tactics WHERE user_id=? AND slot=? AND club_id=?',
                    (data['user_id'],data['slot'],data['club_id'])).fetchone()
                result['my_club']['tactic']=tactic['tactic'] if tactic else 'balanced'
                result['my_club']['players']=conn.execute('SELECT COUNT(*) FROM world_players WHERE user_id=? AND slot=? AND club_id=?',
                    (data['user_id'],data['slot'],data['club_id'])).fetchone()[0]
                games=fixture_list(conn,data['user_id'],data['slot'],result['season'],club_id=data['club_id'],limit=120)
                recent=[x for x in games if x['home_goals'] is not None][-4:]
                upcoming=[x for x in games if x['home_goals'] is None][:3]
                result['my_fixtures']=recent+upcoming
        result['world']=standings_preview(conn,data['user_id'],data['slot'],result['season'])
        if phase=='review':
            report=conn.execute('SELECT report_json FROM season_reports WHERE user_id=? AND slot=? AND season=?',
                 (data['user_id'],data['slot'],result['season'])).fetchone()
            result['season_report']=json.loads(report['report_json']) if report else None
    return result

def achievements_for(conn, user_id: int, rows: list) -> list[str]:
    roles = {r['role'] for r in rows}
    metrics_by_role = [(r['role'], json.loads(r['metrics_json'])) for r in rows]
    total = conn.execute('SELECT COUNT(*) AS n FROM history WHERE user_id=?', (user_id,)).fetchone()['n']
    found = []
    checks = {
        'pioneer': bool(rows), 'first_move': total >= 1, 'five_moves': total >= 5,
        'twenty_moves': total >= 20, 'two_paths': len(roles) >= 2, 'all_paths': len(roles) >= 5,
        'goalscorer': any(role == 'player' and m.get('goals',0) >= 3 for role,m in metrics_by_role),
        'strategist': any(role == 'coach' and m.get('wins',0) >= 3 for role,m in metrics_by_role),
        'fair_play': any(role == 'referee' and m.get('correct',0) >= 3 for role,m in metrics_by_role),
        'deal_maker': any(role == 'agent' and m.get('deals',0) >= 3 for role,m in metrics_by_role),
        'club_legend': any(role == 'club' and m.get('trophies',0) >= 1 for role,m in metrics_by_role),
        'first_season':conn.execute('SELECT seasons_completed FROM users WHERE id=?',(user_id,)).fetchone()['seasons_completed']>=1,
        'three_seasons':conn.execute('SELECT seasons_completed FROM users WHERE id=?',(user_id,)).fetchone()['seasons_completed']>=3,
        'first_deal':conn.execute('SELECT COUNT(*) FROM game_transfers WHERE user_id=?',(user_id,)).fetchone()[0]>=1,
        'farewell':conn.execute('SELECT retired_careers FROM users WHERE id=?',(user_id,)).fetchone()['retired_careers']>=1,
    }
    for award_id, achieved in checks.items():
        if achieved:
            result = conn.execute('INSERT OR IGNORE INTO awards(user_id,award_id) VALUES(?,?)', (user_id,award_id))
            if result.rowcount:
                found.append(award_id)
    return found

def make_state(conn, user_id: int) -> dict:
    user = conn.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
    careers = conn.execute('SELECT * FROM careers WHERE user_id=? ORDER BY slot', (user_id,)).fetchall()
    unlocked = {x['award_id'] for x in conn.execute('SELECT award_id FROM awards WHERE user_id=?', (user_id,)).fetchall()}
    actions = conn.execute('SELECT slot,role,title,choice,success,created_at FROM history WHERE user_id=? ORDER BY id DESC LIMIT 8', (user_id,)).fetchall()
    xp = user['xp']
    level = xp // 100 + 1
    return {
      'profile': {'name': user['display_name'], 'username': user['username'], 'xp': xp,
                  'level': level, 'current_level_xp': xp % 100, 'next_level_xp': 100,
                  'seasons_completed':user['seasons_completed'], 'retired_careers':user['retired_careers'],
                  'decisions': conn.execute('SELECT COUNT(*) AS n FROM history WHERE user_id=?',(user_id,)).fetchone()['n']},
      'careers': [career_to_json(row,conn) for row in careers],
      'roles': {role: {k:v for k,v in info.items() if k != 'metrics'} for role,info in ROLES.items()},
      'achievements': [{**item, 'unlocked': item['id'] in unlocked} for item in ACHIEVEMENTS],
      'history': [dict(row) for row in actions], 'max_slots': 5,
      'world_catalog': {'countries':35,'leagues':80,'target_clubs':sum(v['club_slots'] for v in LEAGUES.values()),
         'imported_clubs':conn.execute('SELECT COUNT(*) n FROM club_catalog').fetchone()['n'],
         'imported_players':conn.execute('SELECT COUNT(*) n FROM player_catalog').fetchone()['n'],
         'imported_leagues':conn.execute('SELECT COUNT(DISTINCT league_id) FROM club_catalog').fetchone()[0],
         'full_leagues':conn.execute('''SELECT COUNT(*) FROM (SELECT l.id FROM league_catalog l JOIN club_catalog c ON c.league_id=l.id GROUP BY l.id HAVING COUNT(*)>=MAX(l.intended_clubs,2))''').fetchone()[0],
         'countries_with_clubs':conn.execute('''SELECT COUNT(DISTINCT l.association) FROM club_catalog c JOIN league_catalog l ON l.id=c.league_id''').fetchone()[0],
         'clubs_with_players':conn.execute('SELECT COUNT(DISTINCT club_id) FROM player_catalog').fetchone()[0],
         'rosters':dict(conn.execute("""SELECT
              COALESCE(SUM(CASE WHEN x.cnt>=20 THEN 1 ELSE 0 END),0) AS clubs_20_plus,
              COALESCE(SUM(CASE WHEN x.cnt=0 THEN 1 ELSE 0 END),0) AS clubs_empty,
              COALESCE(SUM(x.cnt),0) AS available_players,
              COALESCE(SUM(CASE WHEN x.verified=1 THEN 1 ELSE 0 END),0) AS official_2026_27
            FROM (SELECT c.id, CASE WHEN vr.club_id IS NOT NULL THEN 1 ELSE 0 END verified,
                 SUM(CASE WHEN p.id IS NOT NULL AND
                   (vr.club_id IS NULL OR p.confirmed_2627=1) THEN 1 ELSE 0 END) cnt
                  FROM club_catalog c LEFT JOIN roster_verified_clubs vr ON c.id=vr.club_id
                  LEFT JOIN player_catalog p ON p.club_id=c.id GROUP BY c.id) x""").fetchone()),
         'source':'offline_static_catalog','snapshot':snapshot_hash()}
    }

@app.get('/api/state')
def state(user: dict = Depends(current_user)):
    with connection() as conn:
        upsert_user(conn,user)
        return make_state(conn,user['id'])

class CreateCareer(BaseModel):
    role: str
    club_id: str | None = None
    name: str = Field(min_length=2, max_length=32)
    place: str = Field(min_length=2, max_length=32)

class Decision(BaseModel):
    event_id: int = Field(ge=0)
    choice_id: int = Field(ge=0, le=2)
    expected_turn: int = Field(ge=0)

def clean_text(value: str):
    result = re.sub(r'\s+', ' ', value).strip()
    if len(result) < 2 or not any(char.isalnum() for char in result):
        raise HTTPException(422, detail='Укажи название длиной от двух символов.')
    return result

@app.post('/api/careers/{slot}/create')
def create_career(slot: int, payload: CreateCareer, user: dict = Depends(current_user)):
    if slot not in range(1,6):
        raise HTTPException(400, detail='Доступно только пять слотов.')
    if payload.role not in ROLES:
        raise HTTPException(422, detail='Неизвестная роль')
    name, place = clean_text(payload.name), clean_text(payload.place)
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        upsert_user(conn,user)
        if payload.club_id is not None:
            if payload.role not in ('player','coach','club'):
                raise HTTPException(422,detail='Реальный клуб можно выбрать для футболиста, тренера или владельца')
            selected=conn.execute('SELECT id,name FROM club_catalog WHERE id=?',(payload.club_id,)).fetchone()
            if not selected:raise HTTPException(422,detail='Выбранного клуба нет в базе')
            place=selected['name']
        existing = conn.execute('SELECT 1 FROM careers WHERE user_id=? AND slot=?',(user['id'],slot)).fetchone()
        if existing:
            raise HTTPException(409, detail='Слот уже занят.')
        initial=json.dumps(ROLES[payload.role]['metrics'],ensure_ascii=False)
        conn.execute('''INSERT INTO careers(user_id,slot,role,name,place,metrics_json,event_index,start_metrics_json,club_id)
                     VALUES(?,?,?,?,?,?,0,?,?)''',
                     (user['id'],slot,payload.role,name,place,initial,initial,payload.club_id))
        refresh_world(conn,user['id'],slot,1)
        new_awards = achievements_for(conn, user['id'], conn.execute('SELECT * FROM careers WHERE user_id=?',(user['id'],)).fetchall())
        return {'state':make_state(conn,user['id']), 'new_awards':new_awards}

@app.post('/api/careers/{slot}/decide')
def decide(slot: int, payload: Decision, user: dict = Depends(current_user)):
    if slot not in range(1,6):
        raise HTTPException(400, detail='Неверный слот')
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        upsert_user(conn,user)
        row = conn.execute('SELECT * FROM careers WHERE user_id=? AND slot=?',(user['id'],slot)).fetchone()
        if row is None:
            raise HTTPException(404, detail='Карьера не найдена')
        role = row['role']
        if row['phase'] != 'playing':
            raise HTTPException(409, detail='Сезон завершён. Открой итоговый отчёт.')
        if payload.event_id != row['event_index'] or payload.expected_turn != row['turns']:
            raise HTTPException(409, detail='Событие уже изменилось. Обнови экран.')
        event = EVENTS[role][row['event_index']]
        if payload.choice_id >= len(event['choices']):
            raise HTTPException(422, detail='Неверный вариант')
        choice = event['choices'][payload.choice_id]
        metrics = json.loads(row['metrics_json'])
        success, delta, summary = resolve(role,row['event_index'],payload.choice_id,metrics)
        xp_gain = 15 if success else 9
        new_turn = row['turns']+1
        next_event = choose_event(role,new_turn,row['event_index'])
        next_season_turn=row['season_turn']+1
        next_phase='ready' if next_season_turn==12 else 'playing'
        # Actually simulate all league fixtures for this season milestone, so standings,
        # player goals and budgets are from persistent matches rather than random end-season tables.
        matches=play_until(conn,user['id'],slot,row['season'],next_season_turn)
        if row['club_id'] and role=='coach':
            standing=conn.execute('SELECT wins,played FROM standings WHERE user_id=? AND slot=? AND season=? AND club_id=?',
                (user['id'],slot,row['season'],row['club_id'])).fetchone()
            if standing:
                metrics['wins']=standing['wins'];metrics['matches']=standing['played']
        if row['club_id'] and role=='player':
            athlete=conn.execute('SELECT appearances,goals FROM world_players WHERE user_id=? AND slot=? AND player_id=?',
                (user['id'],slot,f'career:{user["id"]}:{slot}')).fetchone()
            if athlete:
                metrics['appearances']=athlete['appearances'];metrics['goals']=athlete['goals']
                # Character development immediately affects the next fixture's team power.
                conn.execute('UPDATE world_players SET rating=? WHERE user_id=? AND slot=? AND player_id=?',
                    (max(40,min(92,metrics['skill'])),user['id'],slot,f'career:{user["id"]}:{slot}'))
                delta.pop('goals',None)
        conn.execute('UPDATE careers SET turns=?,season_turn=?,phase=?,metrics_json=?,event_index=? WHERE user_id=? AND slot=?',
                     (new_turn,next_season_turn,next_phase,json.dumps(metrics,ensure_ascii=False),next_event,user['id'],slot))
        conn.execute('INSERT INTO season_actions(user_id,slot,season,turn,title,choice,success,delta_json) VALUES(?,?,?,?,?,?,?,?)',
                     (user['id'],slot,row['season'],next_season_turn,event['title'],choice[0],int(success),json.dumps(delta,ensure_ascii=False)))
        conn.execute('UPDATE users SET xp=xp+? WHERE id=?',(xp_gain,user['id']))
        conn.execute('INSERT INTO history(user_id,slot,role,title,choice,success,changes_json) VALUES(?,?,?,?,?,?,?)',
                     (user['id'],slot,role,event['title'],choice[0],int(success),json.dumps(delta,ensure_ascii=False)))
        awards = achievements_for(conn,user['id'],conn.execute('SELECT * FROM careers WHERE user_id=?',(user['id'],)).fetchall())
        labels = dict(ROLES[role]['stats'])
        return {'result': {'success':success, 'title':'Решение принято' if success else 'Опыт получен',
                            'text':summary+f' Сыграно матчей в чемпионатах: {len(matches)}.', 'xp_gain':xp_gain, 'matches_this_step':len(matches), 'changes':[
                                {'label': labels.get(k, {'appearances':'Матчи','matches':'Матчи','capital':'Капитал','trophies':'Трофеи'}.get(k,k)), 'amount':v}
                                for k,v in delta.items() if v != 0]},
                'new_awards':awards, 'state':make_state(conn,user['id'])}

@app.delete('/api/careers/{slot}')
def delete_career(slot: int, user: dict = Depends(current_user)):
    if slot not in range(1,6):
        raise HTTPException(400, detail='Неверный слот')
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        upsert_user(conn,user)
        result = conn.execute('DELETE FROM careers WHERE user_id=? AND slot=?',(user['id'],slot))
        if not result.rowcount:
            raise HTTPException(404, detail='Слот пуст')
        # Historical profile progress and earned awards survive removing a save slot.
        return {'state':make_state(conn,user['id'])}

@app.get('/api/health')
def health():
    return {'ok':True, 'demo': DEMO_MODE}


@app.get('/api/world/leagues')
def world_leagues(user: dict = Depends(current_user)):
    with connection() as conn:
        rows=conn.execute("""SELECT l.id,l.name,l.country,l.tier,l.intended_clubs,
            COUNT(DISTINCT cc.id) imported,
            COUNT(DISTINCT CASE WHEN p.id IS NOT NULL THEN cc.id ELSE NULL END) rostered_clubs,
            COUNT(DISTINCT p.id) named_players
            FROM league_catalog l LEFT JOIN club_catalog cc ON cc.league_id=l.id
            LEFT JOIN player_catalog p ON p.club_id=cc.id AND
              (NOT EXISTS(SELECT 1 FROM roster_verified_clubs vr WHERE vr.club_id=cc.id)
               OR p.confirmed_2627=1)
            GROUP BY l.id ORDER BY l.association,l.tier""").fetchall()
        manifest_path=BASE/'world_data'/'coverage_manifest.json'
        manifest=json.loads(manifest_path.read_text(encoding='utf-8'))['sources'] if manifest_path.exists() else {}
        audit_path=BASE/'world_data'/'verified_lower_leagues_audit_v06.json'
        audit=json.loads(audit_path.read_text(encoding='utf-8')).get('league_details',{}) if audit_path.exists() else {}
        leagues=[]
        for r in rows:
            d=dict(r)
            d['status']='empty' if d['imported']==0 else 'complete' if d['imported']>=d['intended_clubs'] else 'partial'
            d['source_season']=audit.get(d['id'],{}).get('season') or manifest.get(d['id'],{}).get('season','2026/27' if d['id'] in ('ENG_1','ENG_2','ESP_1','GER_1','ITA_1') else None)
            leagues.append(d)
        return {'leagues':leagues,'source_notice':'Historical seasons are labelled. No automatic live football data access.'}

@app.get('/api/world/clubs')
def world_clubs(league: str, user: dict = Depends(current_user)):
    if league not in LEAGUES:raise HTTPException(404,detail='Лига не найдена')
    with connection() as conn:
        rows=conn.execute("""SELECT id,name,base_budget_eur,base_transfer_eur,
         (SELECT COUNT(*) FROM player_catalog p WHERE p.club_id=cc.id AND
           (NOT EXISTS(SELECT 1 FROM roster_verified_clubs vr WHERE vr.club_id=cc.id)
            OR p.confirmed_2627=1)) players
         FROM club_catalog cc WHERE league_id=? ORDER BY name""",(league,)).fetchall()
        return {'league':LEAGUES[league]['competition'],'clubs':[dict(r) for r in rows],
                'finances_are':'game estimates, not actual club disclosures'}

@app.get('/api/careers/{slot}/table')
def career_standings(slot:int, league: str|None=None,user:dict=Depends(current_user)):
    with connection() as conn:
        row=conn.execute('SELECT * FROM careers WHERE user_id=? AND slot=?',(user['id'],slot)).fetchone()
        if not row:raise HTTPException(404,detail='Карьера не найдена')
        return standings_preview(conn,user['id'],slot,row['season'],league)

@app.post('/api/careers/{slot}/season/finish')
def season_finish(slot:int,user:dict=Depends(current_user)):
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute('SELECT * FROM careers WHERE user_id=? AND slot=?',(user['id'],slot)).fetchone()
        if row is None:raise HTTPException(404,detail='Карьера не найдена')
        if row['phase']!='ready' or row['season_turn']!=12:
            raise HTTPException(409,detail='Завершить сезон можно после всех 12 решений')
        s=simulate_all(conn,user['id'],slot,row['season'],row['club_id'])
        actions=conn.execute('SELECT * FROM season_actions WHERE user_id=? AND slot=? AND season=? ORDER BY turn',
                 (user['id'],slot,row['season'])).fetchall()
        changes={}
        before=json.loads(row['start_metrics_json']);now=json.loads(row['metrics_json'])
        if row['role']=='club' and row['club_id']:
            own=conn.execute('SELECT name FROM club_catalog WHERE id=?',(row['club_id'],)).fetchone()
            if own and any(l['champion']==own['name'] for l in s['league_summaries']):
                now['trophies']=now.get('trophies',0)+1
                conn.execute('UPDATE careers SET metrics_json=? WHERE user_id=? AND slot=?',
                             (json.dumps(now,ensure_ascii=False),user['id'],slot))
        for k,value in now.items():
            if isinstance(value,(int,float)):
                diff=value-before.get(k,value)
                if diff:changes[k]=diff
        football=season_game_stats(conn,user['id'],slot,row['season'],row['club_id'])
        report={'season':row['season'],'period':f'{2026+row["season"]-1}/{2027+row["season"]-1}',
            'name':row['name'],'role':row['role'],'decisions':len(actions),
            'successful':sum(a['success'] for a in actions),'failed':sum(not a['success'] for a in actions),
            'changes':changes,'football':football,'events':[{'title':a['title'],'choice':a['choice'],'success':bool(a['success'])} for a in actions],
            **s}
        conn.execute('INSERT INTO season_reports(user_id,slot,season,report_json) VALUES(?,?,?,?)',
                     (user['id'],slot,row['season'],json.dumps(report,ensure_ascii=False)))
        conn.execute('UPDATE careers SET phase=? WHERE user_id=? AND slot=?',('review',user['id'],slot))
        conn.execute('UPDATE users SET seasons_completed=seasons_completed+1 WHERE id=?',(user['id'],))
        new_awards=achievements_for(conn,user['id'],conn.execute('SELECT * FROM careers WHERE user_id=?',(user['id'],)).fetchall())
        return {'report':report,'new_awards':new_awards,'state':make_state(conn,user['id'])}

@app.post('/api/careers/{slot}/season/advance')
def season_advance(slot:int,user:dict=Depends(current_user)):
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute('SELECT * FROM careers WHERE user_id=? AND slot=?',(user['id'],slot)).fetchone()
        if row is None:raise HTTPException(404,detail='Карьера не найдена')
        if row['phase']!='review':raise HTTPException(409,detail='Сначала ознакомься с итогами сезона')
        season=row['season']+1
        conn.execute("""UPDATE careers SET season=?,season_turn=0,phase='playing',start_metrics_json=metrics_json,
            event_index=0 WHERE user_id=? AND slot=?""",(season,user['id'],slot))
        offseason=ai_transfer_window(conn,user['id'],slot,season,locked_club=row['club_id'] if row['role'] in ('coach','club') else None)
        refresh_world(conn,user['id'],slot,season)
        return {'state':make_state(conn,user['id']),'offseason':offseason}

class RetireCareer(BaseModel):
    confirmation: str

@app.post('/api/careers/{slot}/season/retire')
def season_retire(slot:int,payload:RetireCareer,user:dict=Depends(current_user)):
    if payload.confirmation!='DELETE':raise HTTPException(422,detail='Подтверди удаление карьеры')
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute('SELECT phase FROM careers WHERE user_id=? AND slot=?',(user['id'],slot)).fetchone()
        if row is None:raise HTTPException(404,detail='Слот не найден')
        if row['phase']!='review':raise HTTPException(409,detail='Завершить карьеру через отчёт можно только после сезона')
        conn.execute('DELETE FROM careers WHERE user_id=? AND slot=?',(user['id'],slot))
        conn.execute('UPDATE users SET retired_careers=retired_careers+1 WHERE id=?',(user['id'],))
        new_awards=achievements_for(conn,user['id'],conn.execute('SELECT * FROM careers WHERE user_id=?',(user['id'],)).fetchall())
        return {'state':make_state(conn,user['id']),'new_awards':new_awards}


@app.get('/api/world/clubs/{club_id}')
def world_club_detail(club_id:str,user:dict=Depends(current_user)):
    with connection() as conn:
        club=conn.execute('''SELECT c.id,c.name,c.league_id,c.base_budget_eur,c.base_transfer_eur,
             c.strength,c.source,c.synced_at,l.country,l.name league
             FROM club_catalog c JOIN league_catalog l ON l.id=c.league_id WHERE c.id=?''',(club_id,)).fetchone()
        if club is None:raise HTTPException(404,detail='Клуб не найден')
        players=conn.execute('''SELECT name,position,age,nationality FROM player_catalog pc
         WHERE pc.club_id=? AND (NOT EXISTS(SELECT 1 FROM roster_verified_clubs vr
            WHERE vr.club_id=pc.club_id) OR pc.confirmed_2627=1) ORDER BY name''',(club_id,)).fetchall()
        verified=conn.execute('SELECT source_url,season,verified_players FROM roster_verified_clubs WHERE club_id=?',(club_id,)).fetchone()
        bulk_count=conn.execute("SELECT COUNT(*) FROM player_catalog WHERE club_id=? AND source LIKE '%snapshot 2026-07-%'",(club_id,)).fetchone()[0]
        roster_basis=('official_2026_27' if verified else
                      'historical_2026_07' if bulk_count else
                      'partial_dated' if players else 'no_named_players')
        return {'club':dict(club),'players':[dict(r) for r in players],
                'verified_first_team':dict(verified) if verified else None,
                'roster_basis':roster_basis,'historical_bulk_players':bulk_count,
                'financial_disclaimer':'Game-modeled euro budget, not a disclosed financial statement'}
class TacticChoice(BaseModel):
    tactic: str

@app.post('/api/careers/{slot}/tactic')
def set_tactic(slot:int,payload:TacticChoice,user:dict=Depends(current_user)):
    if payload.tactic not in ('balanced','attack','defend'):
        raise HTTPException(422,detail='Тактика: balanced, attack или defend')
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute('SELECT * FROM careers WHERE user_id=? AND slot=?',(user['id'],slot)).fetchone()
        if not row:raise HTTPException(404,detail='Слот не найден')
        if row['phase']!='playing' or row['role'] not in ('coach','club') or not row['club_id']:
            raise HTTPException(403,detail='Тактику можно менять только тренеру или владельцу клуба во время сезона')
        conn.execute('''INSERT INTO game_tactics(user_id,slot,club_id,tactic) VALUES(?,?,?,?)
          ON CONFLICT(user_id,slot,club_id) DO UPDATE SET tactic=excluded.tactic''',
          (user['id'],slot,row['club_id'],payload.tactic))
        return {'state':make_state(conn,user['id'])}

@app.get('/api/careers/{slot}/fixtures')
def game_schedule(slot:int,league:str|None=None,club:str|None=None,season:int|None=None,user:dict=Depends(current_user)):
    with connection() as conn:
        row=conn.execute('SELECT * FROM careers WHERE user_id=? AND slot=?',(user['id'],slot)).fetchone()
        if not row:raise HTTPException(404,detail='Слот не найден')
        if league and league not in LEAGUES:raise HTTPException(422,detail='Неизвестная лига')
        if club and not conn.execute('SELECT 1 FROM world_clubs WHERE user_id=? AND slot=? AND club_id=?',(user['id'],slot,club)).fetchone():
            raise HTTPException(404,detail='Клуб недоступен')
        selected_season=season or row['season']
        if selected_season<1 or selected_season>row['season']:raise HTTPException(422,detail='Неверный номер сезона')
        return {'fixtures':fixture_list(conn,user['id'],slot,selected_season,league,club or row['club_id'],limit=300),
                'season':selected_season}

@app.get('/api/careers/{slot}/squad')
def game_squad(slot:int,club:str|None=None,user:dict=Depends(current_user)):
    with connection() as conn:
        row=conn.execute('SELECT * FROM careers WHERE user_id=? AND slot=?',(user['id'],slot)).fetchone()
        if not row:raise HTTPException(404,detail='Слот не найден')
        selected=club or row['club_id']
        if not selected:raise HTTPException(422,detail='Выбери клуб')
        if not conn.execute('SELECT 1 FROM world_clubs WHERE user_id=? AND slot=? AND club_id=?',(user['id'],slot,selected)).fetchone():
            raise HTTPException(404,detail='Клуб недоступен')
        clubname=conn.execute('SELECT name FROM club_catalog WHERE id=?',(selected,)).fetchone()[0]
        return {'club_id':selected,'club':clubname,'players':club_roster(conn,user['id'],slot,selected),
                'disclaimer':'Рейтинги, цены и зарплаты смоделированы для игры.'}

@app.get('/api/careers/{slot}/market')
def game_market(slot:int,search:str='',user:dict=Depends(current_user)):
    with connection() as conn:
        row=conn.execute('SELECT * FROM careers WHERE user_id=? AND slot=?',(user['id'],slot)).fetchone()
        if not row:raise HTTPException(404,detail='Слот не найден')
        if row['role'] not in ('coach','club','agent'):raise HTTPException(403,detail='Рынок доступен тренеру, агенту или владельцу')
        players=market_players(conn,user['id'],slot,row['club_id'],search.strip(),limit=40)
        clubs=[dict(x) for x in conn.execute('''SELECT wc.club_id id,cc.name,wc.budget_eur,wc.transfer_eur
             FROM world_clubs wc JOIN club_catalog cc ON cc.id=wc.club_id
             WHERE wc.user_id=? AND wc.slot=? ORDER BY cc.name''',(user['id'],slot)).fetchall()]
        latest=[dict(x) for x in conn.execute('''SELECT t.player_name,t.fee_eur,t.season,t.kind,src.name from_name,dst.name to_name
          FROM game_transfers t JOIN club_catalog src ON src.id=t.from_club JOIN club_catalog dst ON dst.id=t.to_club
          WHERE t.user_id=? AND t.slot=? ORDER BY t.id DESC LIMIT 8''',(user['id'],slot)).fetchall()]
        return {'players':players,'clubs':clubs,'recent_deals':latest,'my_club':row['club_id'],'model':'prices_and_wages_are_fictional'}

class TransferOffer(BaseModel):
    player_id: str
    target_club_id: str
    offer_eur: int = Field(ge=100_000,le=2_000_000_000)

@app.post('/api/careers/{slot}/transfer')
def buy_player(slot:int,payload:TransferOffer,user:dict=Depends(current_user)):
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row=conn.execute('SELECT * FROM careers WHERE user_id=? AND slot=?',(user['id'],slot)).fetchone()
        if not row:raise HTTPException(404,detail='Слот не найден')
        if row['phase']!='playing' or row['role'] not in ('coach','club','agent'):
            raise HTTPException(403,detail='Трансферы доступны только тренеру, агенту и владельцу во время сезона')
        if row['role']!='agent' and (not row['club_id'] or row['club_id']!=payload.target_club_id):
            raise HTTPException(403,detail='Можешь покупать только в свой клуб')
        try:deal=transfer(conn,user['id'],slot,row['season'],row['role'],payload.player_id,payload.target_club_id,payload.offer_eur)
        except ValueError as e:raise HTTPException(409,detail=str(e))
        if row['role']=='agent':
            metrics=json.loads(row['metrics_json']);metrics['deals']=metrics.get('deals',0)+1
            metrics['capital']=metrics.get('capital',0)+max(1,deal['commission_eur']//1_000_000)
            conn.execute('UPDATE careers SET metrics_json=? WHERE user_id=? AND slot=?',
                         (json.dumps(metrics,ensure_ascii=False),user['id'],slot))
        conn.execute('UPDATE users SET xp=xp+20 WHERE id=?',(user['id'],))
        new_awards=achievements_for(conn,user['id'],conn.execute('SELECT * FROM careers WHERE user_id=?',(user['id'],)).fetchall())
        return {'deal':deal,'new_awards':new_awards,'state':make_state(conn,user['id'])}

@app.get('/api/careers/{slot}/archive')
def season_archive(slot:int,user:dict=Depends(current_user)):
    with connection() as conn:
        career=conn.execute('SELECT 1 FROM careers WHERE user_id=? AND slot=?',(user['id'],slot)).fetchone()
        if not career:raise HTTPException(404,detail='Слот не найден')
        rows=conn.execute('''SELECT season,report_json FROM season_reports WHERE user_id=? AND slot=? ORDER BY season DESC''',
                          (user['id'],slot)).fetchall()
        return {'seasons':[{'season':r['season'],'period':json.loads(r['report_json'])['period'],
           'decisions':json.loads(r['report_json'])['decisions'],
           'matches':json.loads(r['report_json']).get('football',{}).get('matches_played',0)} for r in rows]}

@app.get('/api/careers/{slot}/archive/{season}')
def archived_season(slot:int,season:int,user:dict=Depends(current_user)):
    with connection() as conn:
        career=conn.execute('SELECT 1 FROM careers WHERE user_id=? AND slot=?',(user['id'],slot)).fetchone()
        if not career:raise HTTPException(404,detail='Слот не найден')
        row=conn.execute('''SELECT report_json FROM season_reports WHERE user_id=? AND slot=? AND season=?''',
                          (user['id'],slot,season)).fetchone()
        if not row:raise HTTPException(404,detail='Сезон ещё не завершён или удалён')
        return {'report':json.loads(row['report_json'])}
