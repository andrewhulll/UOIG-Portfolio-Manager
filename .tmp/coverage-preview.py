"""Local-only visual QA: real app/routes, disposable fixture DB, no external APIs."""
import math
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
from datetime import date, timedelta

os.environ['UOIG_FORCE_SQLITE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import src.config as config
folder = tempfile.TemporaryDirectory(prefix='uoig-coverage-preview-')
dbfile = str(Path(folder.name) / 'preview.db')
original_load = config.load_config
def load(path=None):
    cfg = original_load(path); cfg['database'] = dbfile; return cfg
config.load_config = load

from api import main, coverage as routes
from tests.test_coverage_dashboard import seed
from src.ingest import research
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse

conn = sqlite3.connect(dbfile); seed(conn)
for old, ticker, name in [('A', 'MSFT', 'Microsoft Corporation'), ('B', 'OMC', 'Omnicom Group')]:
    for table in ['securities', 'holdings', 'prices', 'fundamentals', 'benchmark_holdings']:
        conn.execute(f'UPDATE {table} SET ticker=? WHERE ticker=?', (ticker, old))
    conn.execute('UPDATE securities SET name=? WHERE ticker=?', (name, ticker))
    for i in range(22):
        d = date(2026, 8, 12) + timedelta(days=i)
        if d.weekday() >= 5: continue
        px = (125 if ticker == 'MSFT' else 92) - i * .2 + math.sin(i * .8)
        conn.execute("INSERT OR IGNORE INTO prices VALUES (?,?,?,?,?)", (ticker, d.isoformat(), px, px, 'yfinance'))
conn.executemany('INSERT INTO watchlist VALUES (?,?,?)', [('dev', t, f'2026-09-10T00:00:0{i}Z') for i,t in enumerate(['PLTR','SNOW','TSM','ASML','SHOP'])])
conn.commit(); conn.close()
main._conn = lambda: sqlite3.connect(dbfile)
main.wc.auth_disabled = lambda: False
main._current = lambda req: (SimpleNamespace(user={'id':'dev','first_name':'Andrew','last_name':'Hull'}, role='member'), None)
member = {'id':'dev','name':'Andrew Hull','role':'member','sectors':['TMT'], 'coverage':[{'ticker':t,'sector':'TMT'} for t in ['MSFT','OMC','TTD']], 'leadSectors':[]}
main.auth_organization.list_members = lambda: {'members':[member]}

def quote(t, **kwargs):
    return {'t':t,'n': {'TTD':'The Trade Desk','PLTR':'Palantir','SNOW':'Snowflake','TSM':'TSMC','ASML':'ASML Holding','SHOP':'Shopify'}.get(t,t),
            'px':164.2,'chg':1.8,'mc':388,'pe':198,'forwardPE':198,'lo':60,'hi':170,
            'volume':1400,'averageVolume':1000,'nextEarnings':'2026-11-03','asOf':'2026-09-10T20:00:00Z','exchange':'NASDAQ','revGrowth':14,'held':False}
main.quote_overview = routes.quote_overview = quote
routes.search_symbols = lambda t, **kwargs: [] if t == 'INVALID' else [{'symbol':t}]
main.live_series = lambda t,p: {'dates':['2026-09-01','2026-09-02','2026-09-03','2026-09-10'], 'close':[150,153,149,164.2]}
def detail(t):
    return {'earnings': {'next':'Oct 28, 2026'}, 'research': {'consensus':{'label':'Buy','total':42,'mean':170}}}
main.closed_snapshot = main.stock_research = routes.closed_snapshot = detail
def news(t):
    return {'news':[{'title':f'{t} management outlines its priorities ahead of quarterly results','publisher':'Company investor relations','ago':'6h ago','link':'https://example.com/research'},
                    {'title':f'{t} market update: analyst estimates and the latest company news','publisher':'Company investor relations','ago':'1d ago','link':'https://example.com/update'}]}
main.stock_news = news
main.stock_thesis = lambda t: {'thesis':{'date':'2026-08-14','analyst':'A. Hull','points':[
    'Enterprise demand and recurring revenue support the long-term investment case.',
    'Margin expansion depends on disciplined execution and improving product mix.',
    'Track capital spending, competitive pressure, and changes to management guidance.']}}
preview = FastAPI()
@preview.get('/api/auth/me')
def auth(): return {'user':{'id':'dev','firstName':'Andrew','lastName':'Hull','name':'Andrew Hull'},'role':'member','canInvite':False}
@preview.get('/__preview')
def scenario(mode='normal'):
    response = RedirectResponse('/coverage'); response.set_cookie('scenario', mode); return response
@preview.middleware('http')
async def scenarios(request: Request, call_next):
    mode = request.cookies.get('scenario', 'normal')
    if mode == 'errors' and request.url.path in ['/api/movers','/api/watchlist']:
        return JSONResponse({'detail':'Preview: simulated temporary failure.'}, status_code=503)
    if mode == 'empty' and request.url.path == '/api/coverage/me':
        return JSONResponse({'tickers':[],'earningsThisWeek':[]})
    return await call_next(request)
preview.mount('/', main.app)
if __name__ == '__main__':
    import uvicorn
    uvicorn.run(preview, host='127.0.0.1', port=5187)
