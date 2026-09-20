#!/usr/bin/env python3
"""FinanceData/marcap based KOSPI/KOSDAQ common-share Top 10 collector."""
from __future__ import annotations

import argparse, json, logging, os, re, sys, tempfile, time
import urllib.error, urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
HISTORY_PATH, LATEST_PATH = ROOT/'dist/data/history.json', ROOT/'dist/data/latest.json'
SECTOR_PATH, FILTER_PATH = ROOT/'scripts/sector_map.json', ROOT/'scripts/filters.json'
SOURCE, KST = 'FinanceData/marcap', ZoneInfo('Asia/Seoul')
RAW_URL = 'https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{year}.parquet'
REQUIRED = {'Date','Rank','Code','Name','Close','Marcap','Stocks','Market','MarketId'}
MARKET_IDS = {'KOSPI':'STK','KOSDAQ':'KSQ'}
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
LOG = logging.getLogger('market-update')

def read_json(path, default):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default

def download_current_data(year):
    errors=[]
    for candidate in (year, year-1):
        url=RAW_URL.format(year=candidate)
        for attempt in range(1,4):
            target=Path(tempfile.gettempdir())/f'marcap-{candidate}-{os.getpid()}.parquet'
            try:
                LOG.info('marcap 다운로드: year=%s attempt=%s',candidate,attempt)
                req=urllib.request.Request(url,headers={'User-Agent':'market-leadership-dashboard/2.0'})
                with urllib.request.urlopen(req,timeout=90) as response,target.open('wb') as out:
                    while chunk:=response.read(1024*1024): out.write(chunk)
                if target.stat().st_size<10_000: raise RuntimeError('다운로드 파일이 비정상적으로 작습니다')
                return target
            except (OSError,urllib.error.URLError,RuntimeError) as exc:
                errors.append(f'{candidate}/{attempt}: {exc}');target.unlink(missing_ok=True);time.sleep(attempt*2)
        LOG.warning('%s년 파일을 가져오지 못했습니다. 이전 연도를 확인합니다.',candidate)
    raise RuntimeError('marcap 다운로드 실패: '+' | '.join(errors))

def load_frames(paths):
    frames=[]
    for path in paths:
        LOG.info('marcap 파일 읽기: %s',path);frames.append(pd.read_parquet(path))
    if not frames: raise RuntimeError('읽을 marcap 파일이 없습니다')
    data=pd.concat(frames,ignore_index=True)
    missing=REQUIRED-set(data.columns)
    if missing: raise RuntimeError('marcap 필수 필드 누락: '+', '.join(sorted(missing)))
    data['Date']=pd.to_datetime(data['Date'],errors='raise').dt.normalize()
    data['Code']=data['Code'].astype(str).str.strip().str.zfill(6)
    data['Name']=data['Name'].astype(str).str.strip()
    for col in ('Close','Marcap','Stocks'): data[col]=pd.to_numeric(data[col],errors='coerce')
    data=data.dropna(subset=['Date','Code','Name','Close','Marcap','Stocks','MarketId'])
    if data.empty: raise RuntimeError('marcap 파일에 유효한 행이 없습니다')
    return data

def compile_filters(config):
    return set(config.get('include_codes',[])),set(config.get('exclude_codes',[])),[(x['reason'],re.compile(x['pattern'],re.I)) for x in config['name_patterns']]

def exclusion_reason(code,name,compiled):
    included,excluded,patterns=compiled
    if code in included:return None
    if code in excluded:return 'explicit_exclusion'
    for reason,pattern in patterns:
        if pattern.search(name):return reason
    return None

def validate_top10(top,market,compiled):
    problems=[]
    if len(top)!=10:problems.append(f'종목 수 {len(top)}')
    if top['Code'].duplicated().any():problems.append('중복 종목코드')
    if not top['MarketId'].eq(MARKET_IDS[market]).all():problems.append('타 시장 종목 포함')
    caps=top['Marcap'].tolist()
    if any(caps[i]<caps[i+1] for i in range(len(caps)-1)):problems.append('시가총액 내림차순 위반')
    forbidden=[f'{r.Code} {r.Name}' for r in top.itertuples() if exclusion_reason(r.Code,r.Name,compiled)]
    if forbidden:problems.append('제외 대상 포함: '+', '.join(forbidden))
    normalized=top['Name'].str.replace(r'(?:\d+)?우(?:B|C|\(전환\))?$','',regex=True)
    if normalized.duplicated().any():problems.append('동일 기업 중복 성격 종목')
    if problems:raise RuntimeError(f"{market} Top 10 검증 실패: {'; '.join(problems)}")

def extract_top10(day_data,market,compiled):
    rows=day_data[day_data['MarketId'].eq(MARKET_IDS[market])].copy()
    if rows.empty:raise RuntimeError(f'{market} 원본 행이 없습니다')
    reasons=rows.apply(lambda r:exclusion_reason(r['Code'],r['Name'],compiled),axis=1);excluded=reasons.notna()
    counts=reasons[excluded].value_counts().to_dict();eligible=rows[~excluded].copy()
    eligible=eligible[(eligible['Marcap']>0)&(eligible['Stocks']>0)&(eligible['Close']>=0)]
    eligible=eligible.sort_values(['Marcap','Code'],ascending=[False,True]);top=eligible.head(10).copy();top['FinalRank']=range(1,len(top)+1)
    LOG.info('%s 원본=%s 제외=%s(%s) 유효=%s Top10=%s',market,len(rows),int(excluded.sum()),counts,len(eligible),len(top))
    validate_top10(top,market,compiled)
    return top,{'original':len(rows),'excluded':int(excluded.sum()),'reasons':counts,'eligible':len(eligible)}

def make_snapshot(day,market,top,sector_map):
    stocks=[];unmapped=[]
    for row in top.itertuples():
        mapping=sector_map.get(row.Code);sector=mapping['sector'] if mapping else '미분류'
        if not mapping:unmapped.append({'code':row.Code,'name':row.Name})
        stocks.append({'rank':int(row.FinalRank),'code':row.Code,'name':row.Name,'close':int(row.Close),'market_cap':int(row.Marcap),'stocks':int(row.Stocks),'sector':sector})
    return {'date':day.strftime('%Y-%m-%d'),'source':SOURCE,'market':market,'stocks':stocks},unmapped

def atomic_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);payload=json.dumps(value,ensure_ascii=False,separators=(',',':'))
    with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=path.parent,delete=False) as handle:
        handle.write(payload);handle.flush();os.fsync(handle.fileno());temp_name=handle.name
    os.replace(temp_name,path)

def build_and_save(data,backfill_start=None,dry_run=False):
    latest_day=data['Date'].max();LOG.info('실행 시각(KST): %s',datetime.now(KST).isoformat(timespec='seconds'));LOG.info('확인한 최신 marcap 거래일: %s',latest_day.date())
    current=read_json(HISTORY_PATH,{'meta':{},'snapshots':[]});previous=current.get('meta',{}).get('latest_date');LOG.info('기존 저장 최신 거래일: %s',previous or '없음')
    if not backfill_start and not dry_run and previous==latest_day.strftime('%Y-%m-%d') and current.get('meta',{}).get('source')==SOURCE:
        LOG.info('latest market data not available yet 또는 이미 최신 스냅샷 저장됨; 변경 없이 종료');return 0
    compiled=compile_filters(read_json(FILTER_PATH,{}));sector_map=read_json(SECTOR_PATH,{})
    if backfill_start:
        days=sorted(data.loc[data['Date'].ge(pd.Timestamp(backfill_start)),'Date'].unique());base=[]
    else:
        days=[latest_day];base=current.get('snapshots',[]) if current.get('meta',{}).get('source')==SOURCE else []
    new=[];unmapped_all={};quality={}
    for day in days:
        day_data=data[data['Date'].eq(day)]
        for market in ('KOSPI','KOSDAQ'):
            top,stats=extract_top10(day_data,market,compiled);snapshot,unmapped=make_snapshot(day,market,top,sector_map)
            new.append(snapshot);quality[market]=stats
            for item in unmapped:unmapped_all[item['code']]=item
    if unmapped_all:LOG.warning('산업군 미매핑: %s',', '.join(f"{x['code']} {x['name']}" for x in unmapped_all.values()))
    merged={(s['date'],s['market']):s for s in base};merged.update({(s['date'],s['market']):s for s in new});snapshots=sorted(merged.values(),key=lambda s:(s['date'],s['market']))
    generated=datetime.now(KST).isoformat(timespec='seconds');meta={'status':'ready','latest_date':latest_day.strftime('%Y-%m-%d'),'generated_at':generated,'mode':'live','source':SOURCE,'unmapped':list(unmapped_all.values()),'quality':quality}
    history={'meta':meta,'snapshots':snapshots};latest={'meta':meta,'snapshots':[s for s in snapshots if s['date']==meta['latest_date']]}
    if dry_run:LOG.info('DRY RUN: 파일을 변경하지 않았습니다')
    else:
        atomic_json(HISTORY_PATH,history);atomic_json(LATEST_PATH,latest);LOG.info('스냅샷 저장 완료: 거래일=%s 신규=%s 전체=%s',meta['latest_date'],len(new),len(snapshots))
    return 0

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source-file',action='append',type=Path);parser.add_argument('--backfill-start');parser.add_argument('--dry-run',action='store_true');args=parser.parse_args();downloaded=None
    try:
        paths=args.source_file
        if not paths:downloaded=download_current_data(datetime.now(KST).year);paths=[downloaded]
        return build_and_save(load_frames(paths),args.backfill_start,args.dry_run)
    except Exception as exc:
        LOG.exception('수집 실패 — 기존 정상 데이터 유지: %s',exc);return 1
    finally:
        if downloaded:downloaded.unlink(missing_ok=True)

if __name__=='__main__':sys.exit(main())
