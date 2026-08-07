import sqlite3, time
p='/home/trading_ceo/python-trader/varaha/data/capture_nifty.sqlite'
def stats():
    c=sqlite3.connect(p); 
    n=c.execute("select count(*) from option_prices").fetchone()[0]
    t=c.execute("select max(timestamp) from option_prices").fetchone()[0]
    td=c.execute("select count(*) from option_prices where timestamp like '2026-06-30%'").fetchone()[0]
    c.close(); return n,td,t
for i in range(5):
    print(time.strftime('%H:%M:%S'), 'total,today,maxts=', stats(), flush=True)
    time.sleep(20)
