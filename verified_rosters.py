"""2026/27 Premier League registered senior players: sourced static *facts*, no API.

Idempotent overlay for the GLOBAL starting catalogue.  Existing save data lives in
`world_players` and is deliberately never modified.  Player IDs survive moves.
This overlay does not claim to be the exhaustive senior + U21 club squad.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

SOURCE_URL = 'https://www.premierleague.com/en/news/4706139/see-all-the-202627-premier-league-squad-lists'
SOURCE_DATE = '2026-09-03'
FIRST_TEAM = Path(__file__).resolve().parent / 'world_data' / 'premier_league_2026_27_first_team.txt'
FEATURED = Path(__file__).resolve().parent / 'world_data' / 'featured_2026_27_first_team.txt'


def key(name: str) -> str:
    s = unicodedata.normalize('NFKD', name).casefold()
    return ''.join(c for c in s if c.isalnum() and not unicodedata.combining(c))


def official_first_team():
    result = {}
    for line in FIRST_TEAM.read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        club, sep, rest = line.partition('|')
        if not sep:
            raise ValueError('Expected club|name;name in official roster file')
        club = club.strip()
        names = [n.strip() for n in rest.split(';') if n.strip()]
        if not 18 <= len(names) <= 25:
            raise ValueError(f'Expected 18-25 senior players for {club}: {len(names)}')
        ids = [key(n) for n in names]
        if len(set(ids)) != len(ids) or club in result:
            raise ValueError(f'Duplicate club or player in {club}')
        result[club] = names
    if len(result) != 20:
        raise ValueError(f'Expected 20 published Premier League clubs, got {len(result)}')
    flattened = [key(n) for v in result.values() for n in v]
    repeats = [n for n, num in Counter(flattened).items() if num > 1]
    if repeats:
        raise ValueError(f'Two official clubs listed same display name: {repeats}')
    return result



def featured_clubs():
    result = {}
    for line in FEATURED.read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        lid, club, source, raw = line.split('|', 3)
        if lid not in ('ESP_1','GER_1','ITA_1','FRA_1') or not source.startswith('https://'):
            raise ValueError('Invalid featured club or source')
        entries = {}
        for token in raw.split(';'):
            position, name = token.split(':', 1)
            if position not in ('GK','DF','MF','FW') or not name:
                raise ValueError('Invalid position')
            if key(name) in entries:
                raise ValueError('Repeated player in featured club')
            entries[key(name)] = (name, position)
        if not 20 <= len(entries) <= 30:
            raise ValueError(f'Expected 20-30 named players for {club}')
        result[(lid, club)] = (source, entries)
    if len(result) != 9:
        raise ValueError('Expected nine featured clubs')
    return result


def update_verified_catalog(conn):
    """Apply dated roster only to master data; NOT to existing career worlds.

    Exact, accent-insensitive identity matches are safe to reassign.  Duplicate
    ambiguous identities are audited and left untouched instead of guessed.
    All historical (including U21) players remain stored to support old saves.
    The `confirmed_2627` flag controls who STARTS in new PL career saves.
    """
    names = official_first_team()
    featured = featured_clubs()
    columns = {r['name'] for r in conn.execute('PRAGMA table_info(player_catalog)')}
    if 'confirmed_2627' not in columns:
        conn.execute('ALTER TABLE player_catalog ADD COLUMN confirmed_2627 INTEGER NOT NULL DEFAULT 0')
    conn.execute('''CREATE TABLE IF NOT EXISTS roster_verified_clubs(
         club_id TEXT PRIMARY KEY, source_url TEXT NOT NULL, season TEXT NOT NULL,
         verified_players INTEGER NOT NULL)''')
    clubs = {r['name']: r['id'] for r in conn.execute("SELECT id, name FROM club_catalog WHERE league_id='ENG_1'")}
    other_clubs = {(r['league_id'],r['name']):r['id'] for r in conn.execute(
        "SELECT id,league_id,name FROM club_catalog WHERE league_id IN ('ESP_1','GER_1','ITA_1','FRA_1')")}
    if set(featured) - set(other_clubs):
        raise ValueError(f'Unknown featured club: {set(featured)-set(other_clubs)}')
    if set(clubs) != set(names):
        raise ValueError(f'Official league does not match existing 20 clubs: {set(clubs)^set(names)}')
    # Players from previous snapshot not on the registered senior list may still
    # be youth players; they are not deleted, just excluded from NEW PL saves.
    conn.execute('''UPDATE player_catalog SET confirmed_2627=0
        WHERE club_id IN (SELECT id FROM club_catalog WHERE league_id='ENG_1')''')
    stats = dict(clubs=29, published=sum(map(len, names.values())) + sum(len(v[1]) for v in featured.values()), added=0,
                 matched=0, moved=0, ambiguous=[], source_date=SOURCE_DATE)
    rows = conn.execute('SELECT id,club_id,name,position FROM player_catalog').fetchall()
    lookup = defaultdict(list)
    for row in rows:
        lookup[key(row['name'])].append(row)
    # Official full senior lists take priority over any earlier dated snapshots.
    specs = [(clubs[club], club, SOURCE_URL, [(p, None) for p in players])
             for club, players in names.items()]
    specs.extend((other_clubs[(lid, club)], club, source,
                   list(rows.values())) for (lid, club), (source, rows) in featured.items())
    for cid, club, source, players in specs:
        conn.execute('''INSERT INTO roster_verified_clubs(club_id,source_url,season,verified_players)
            VALUES(?,?,?,?) ON CONFLICT(club_id) DO UPDATE SET
            source_url=excluded.source_url, season=excluded.season,
            verified_players=excluded.verified_players''',
            (cid,source,'2026/27',len(players)))
        for name, position in players:
            matches = lookup.get(key(name), [])
            # When a name exists more than once, only use the record already at
            # this club. Never guess which same-named footballer is correct.
            if len(matches) > 1:
                local = [x for x in matches if x['club_id'] == cid]
                if len(local) != 1:
                    stats['ambiguous'].append({'name': name, 'club': club})
                    continue
                row = local[0]
            elif len(matches) == 1:
                row = matches[0]
            else:
                row = None
            if row:
                if row['club_id'] != cid:
                    stats['moved'] += 1
                else:
                    stats['matched'] += 1
                conn.execute('''UPDATE player_catalog SET club_id=?,confirmed_2627=1,
                    position=COALESCE(?,position),synced_at=?, source=? WHERE id=?''',
                    (cid,position, SOURCE_DATE, source + ' (verified first-team 2026/27)', row['id']))
            else:
                uid = 'pl26:' + hashlib.sha256((cid + '|' + key(name)).encode()).hexdigest()[:24]
                conn.execute('''INSERT INTO player_catalog(id,club_id,name,position,age,nationality,
                    provider_id,source,synced_at,confirmed_2627)
                    VALUES(?,?,?,?,NULL,NULL,NULL,?,?,1)''',
                    (uid, cid, name, position, source + ' (verified first-team 2026/27)',SOURCE_DATE))
                lookup[key(name)].append({'id': uid, 'club_id': cid, 'name': name})
                stats['added'] += 1
    return stats
