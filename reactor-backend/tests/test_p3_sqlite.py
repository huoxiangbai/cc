import asyncio
import sqlite3
import httpx
import pytest
from reactor_backend.adapters.business_db import BusinessDB
from reactor_backend.data_query.sql import resolve


@pytest.fixture
def db(tmp_path):
    path=tmp_path/'business.sqlite'
    with sqlite3.connect(path) as c:
        c.execute('CREATE TABLE sales(category TEXT,amount DECIMAL_TEXT,day DATE,optional TEXT,big INTEGER)')
        c.executemany('INSERT INTO sales VALUES(?,?,?,?,?)',[
            ('中文A','0.10','2026-10-03',None,9007199254740993),
            ('中文A','0.20','2026-10-04','x',7),('B','10.00','2026-10-05','Y',8)])
        c.execute('CREATE TABLE labels(category TEXT,label TEXT)')
        c.executemany('INSERT INTO labels VALUES(?,?)',[('中文A','甲'),('B','乙')])
    return BusinessDB({'type':'sqlite','path':str(path),'timeout':.2},None)


async def test_sqlite_exact_aggregate_and_arithmetic_comparison_order(db):
    data=await db.query('SELECT category,SUM(amount) AS total FROM sales GROUP BY category ORDER BY total')
    assert data['dataList']==[{'category':'中文A','total':.3},{'category':'B','total':10}]
    assert (await db.query('SELECT SUM(amount) FROM sales'))['dataList']==[{'sum(amount)':10.3}]
    assert 'DECIMAL_SUM' in data['executedSql']
    data=await db.query("SELECT amount * 3 AS product FROM sales WHERE amount < 1 ORDER BY amount")
    assert data['dataList']==[{'product':.3},{'product':.6}]


async def test_sqlite_join_cte_union_date_null_unicode_big_integer(db):
    result=await db.query('WITH x AS (SELECT s.category,l.label,s.big,s.day FROM sales s JOIN labels l ON s.category=l.category WHERE s.optional IS NULL) SELECT * FROM x UNION ALL SELECT category,label,9,NULL FROM labels WHERE category=\'B\'')
    assert result['dataList'][0]=={'category':'中文A','label':'甲','big':9007199254740993,'day':'2026-10-03'}
    assert result['dataList'][1]['day'] is None
    assert (await db.query('SELECT CATEGORY FROM SALES LIMIT 1'))['dataList'][0]['category']=='中文A'


async def test_sqlite_catalog_and_sql_models(db):
    assert await db.tables()==['labels','sales']
    fields=await db.columns('sales')
    assert next(f for f in fields if f['name']=='amount')['origin_type']=='DECIMAL_TEXT'
    assert {f['name']:f['origin_type'] for f in await db.columns('SELECT SUM(amount),COUNT(*) FROM sales','sql')}=={'SUM(amount)':'DECIMAL_TEXT','COUNT(*)':'BIGINT'}
    assert [f['name'] for f in await db.columns('SELECT category,big AS id FROM sales','sql')]==['category','id']
    models=[{'modelCode':'m','type':'SQL','content':'SELECT category,amount FROM sales','schemaList':[]}]
    sql,*_=resolve('SELECT * FROM m',models,'sqlite')
    assert len((await db.query(sql))['dataList'])==3
    sql,columns,*_=resolve('SELECT COUNT(*),SUM(amount) FROM m',models,'sqlite')
    result=await db.query(sql)
    assert set(result['dataList'][0])=={column['guid'] for column in columns}
    assert list(result['dataList'][0].values())==[3,10.3]


@pytest.mark.parametrize('sql',['DELETE FROM sales','SELECT 1;SELECT 2',"ATTACH DATABASE '/tmp/foreign.db' AS evil","SELECT load_extension('x')"])
async def test_sqlite_mutation_attach_extension_denied(db,sql):
    with pytest.raises((ValueError,sqlite3.DatabaseError)):await db.query(sql)


async def test_sqlite_missing_file_does_not_create(tmp_path):
    missing=tmp_path/'absent.sqlite'
    with pytest.raises(FileNotFoundError):BusinessDB({'type':'sqlite','path':str(missing)},None)
    assert not missing.exists()


async def test_sqlite_timeout_cancel_releases_connection(db):
    sql='WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<100000000) SELECT SUM(x) FROM n'
    with pytest.raises(TimeoutError):await db.query(sql)
    task=asyncio.create_task(db.query(sql));await asyncio.sleep(.01);task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    assert (await db.query('SELECT 1 AS n'))['dataList']==[{'n':1}]


async def test_sqlite_decimal_precision_failure_is_explicit(db):
    with sqlite3.connect(db.sqlite.path) as c:
        c.execute("INSERT INTO sales(amount) VALUES('9007199254740993.01')")
    with pytest.raises(ValueError,match='precision'):await db.query('SELECT amount FROM sales')
    assert (await db.query('SELECT CAST(amount AS TEXT) AS exact FROM sales WHERE category IS NULL'))['dataList']==[{'exact':'9007199254740993.01'}]
    with sqlite3.connect(db.sqlite.path) as c:c.execute('CREATE TABLE lossy(amount DECIMAL)');c.execute('INSERT INTO lossy VALUES(0.1)')
    with pytest.raises(ValueError,match='REAL storage'):await db.query('SELECT amount FROM lossy')


async def test_decimal_renamed_cte_subquery_union_and_join_type_scope(db):
    for sql in [
        'WITH x AS (SELECT amount AS value FROM sales) SELECT SUM(value) AS total FROM x',
        'SELECT SUM(value) AS total FROM (SELECT amount AS value FROM sales) x',
        'WITH x(value) AS (SELECT amount FROM sales) SELECT SUM(value) AS total FROM x']:
        assert (await db.query(sql))['dataList']==[{'total':10.3}]
    assert (await db.query('SELECT amount AS value FROM sales WHERE category=\'B\' UNION ALL SELECT amount FROM sales WHERE category IS NULL'))['dataList']==[{'value':10}]
    with sqlite3.connect(db.sqlite.path) as c:
        c.execute('ALTER TABLE labels ADD COLUMN amount TEXT');c.execute("UPDATE labels SET amount='文字'")
    assert {f['name']:f['origin_type'] for f in await db.columns('SELECT l.amount AS label,s.amount AS money FROM sales s JOIN labels l ON s.category=l.category','sql')}=={'label':'TEXT','money':'DECIMAL_TEXT'}
    assert (await db.query('SELECT l.amount AS label,s.amount AS money FROM sales s JOIN labels l ON s.category=l.category LIMIT 1'))['dataList']==[{'label':'文字','money':.1}]


async def test_decimal_distinct_grouping_and_alias_collision(db):
    with sqlite3.connect(db.sqlite.path) as c:c.execute("INSERT INTO sales(category,amount) VALUES('相同','0.100')")
    assert (await db.query('SELECT DISTINCT amount FROM sales ORDER BY amount'))['dataList']==[{'amount':.1},{'amount':.2},{'amount':10}]
    assert (await db.query('SELECT amount,COUNT(*) AS n FROM sales GROUP BY amount ORDER BY amount'))['dataList'][0]=={'amount':.1,'n':2}
    result=await db.query('WITH x AS (SELECT amount AS label FROM sales) SELECT l.label FROM x JOIN labels l ON 1=1 ORDER BY l.label LIMIT 1')
    assert result['dataList']==[{'label':'乙'}]
