"""Strict, deterministic offline catalog import. Zero network calls or football APIs."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from world import LEAGUES, game_budgets

PACK_DIR = Path(__file__).resolve().parent/'world_data'/'packs'

class PackError(ValueError):
    pass

def _name(value, what, max_length=130):
    if not isinstance(value,str) or not value.strip() or len(value.strip())>max_length or any(ord(ch)<32 for ch in value):
        raise PackError(f'Invalid {what}')
    return value.strip()

def _stable_id(prefix, text):
    return prefix+':'+hashlib.sha256(text.encode('utf-8')).hexdigest()[:18]

def parse_pack(path):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data,dict) or data.get('format')!='velton-offline-1' or not isinstance(data.get('clubs'),list):
        raise PackError('Expected {format:"velton-offline-1",clubs:[...]}')
    if len(data['clubs'])>10_000:raise PackError('Pack exceeds 10,000 clubs')
    clubs=[];club_ids=set();names=set();player_ids=set()
    for item in data['clubs']:
        if not isinstance(item,dict):raise PackError('Club must be an object')
        lid=_name(item.get('league_id'),'league ID',50)
        if lid not in LEAGUES:raise PackError('Unknown league '+lid)
        name=_name(item.get('name'),'club name')
        cid=_name(item.get('id') or _stable_id('offline',lid+'|'+name),'club ID')
        tag=(lid,name.casefold())
        if cid in club_ids or tag in names:raise PackError('Duplicated club '+name)
        club_ids.add(cid);names.add(tag)
        source=_name(item.get('source'),'source',1024)
        strength=item.get('strength')
        if strength is not None and (type(strength)!=int or not 35<=strength<=95):
            raise PackError('Strength must be an integer 35..95')
        if strength is None:
            strength=57+int.from_bytes(hashlib.sha256(cid.encode()).digest()[:2],'big')%26
        players=[];seen_names=set()
        if not isinstance(item.get('players',[]),list) or len(item.get('players',[]))>250:
            raise PackError('Invalid roster length')
        for player in item.get('players',[]):
            if not isinstance(player,dict):raise PackError('Player must be an object')
            pn=_name(player.get('name'),'player name')
            if pn.casefold() in seen_names:raise PackError('Duplicate player name within club: '+pn)
            seen_names.add(pn.casefold())
            pid=_name(player.get('id') or _stable_id('offline-player',cid+'|'+pn),'player ID')
            if pid in player_ids:raise PackError('Duplicate player ID '+pid)
            player_ids.add(pid)
            pos=player.get('position');pos=_name(pos,'position',24) if pos is not None else None
            age=player.get('age');age=age if type(age)==int and 14<=age<=55 else None
            nationality=player.get('nationality');nationality=_name(nationality,'nationality',70) if nationality else None
            ps=_name(player.get('source') or source,'player source',1024)
            players.append((pid,cid,pn,pos,age,nationality,ps))
        clubs.append((cid,lid,name,strength,source,players))
    return clubs

def apply_pack(conn,path,dry_run=False):
    clubs=parse_pack(path)  # validate the ENTIRE pack before a single insert
    stats={'clubs_in_pack':len(clubs),'players_in_pack':sum(len(c[-1]) for c in clubs),'added_clubs':0,'added_players':0,'conflicts':0}
    for cid,lid,name,strength,src,players in clubs:
        by_id=conn.execute('SELECT id,league_id,name FROM club_catalog WHERE id=?',(cid,)).fetchone()
        by_name=conn.execute('SELECT id,league_id,name FROM club_catalog WHERE league_id=? AND lower(name)=lower(?)',(lid,name)).fetchone()
        if by_id and (by_id['league_id']!=lid or by_id['name'].casefold()!=name.casefold()):
            stats['conflicts']+=1
            continue
        if by_id and by_name and by_id['id']!=by_name['id']:
            stats['conflicts']+=1
            continue
        existing=by_id or by_name
        actual_id=existing['id'] if existing else cid
        if not existing:
            stats['added_clubs']+=1
            if not dry_run:
                budget,transfer=game_budgets(lid,strength)
                conn.execute('''INSERT INTO club_catalog (id,league_id,name,provider_id,strength,base_budget_eur,base_transfer_eur,source,synced_at)
                VALUES(?,?,?,?,?,?,?,?,?)''',(cid,lid,name,None,strength,budget,transfer,src,'2026-11-15'))
        for pid,club_id,pn,pos,age,nationality,ps in players:
            found_id=conn.execute('SELECT id,club_id,name FROM player_catalog WHERE id=?',(pid,)).fetchone()
            found_name=conn.execute('SELECT id FROM player_catalog WHERE club_id=? AND lower(name)=lower(?)',(actual_id,pn)).fetchone()
            if found_id:
                if found_id['club_id']!=actual_id or found_id['name'].casefold()!=pn.casefold():stats['conflicts']+=1
                continue
            if found_name:continue
            stats['added_players']+=1
            if not dry_run:
                conn.execute('''INSERT INTO player_catalog (id,club_id,name,position,age,nationality,provider_id,source,synced_at)
                 VALUES(?,?,?,?,?,?,?,?,?)''',(pid,actual_id,pn,pos,age,nationality,None,ps,'2026-11-15'))
    return stats

def seed_local_catalog(conn):
    result=[]
    for path in sorted(PACK_DIR.glob('*.json')):
        result.append({'pack':path.name,**apply_pack(conn,path)})
    return result


def snapshot_hash():
    digest=hashlib.sha256()
    for p in sorted(PACK_DIR.glob('*.json')):
        digest.update(p.name.encode());digest.update(p.read_bytes())
    return digest.hexdigest()[:16]
