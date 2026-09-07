import pytest
from agentic_data_platform.sql.intelligence import review_sql, column_lineage
from agentic_data_platform.sql.lineage import table_lineage
from agentic_data_platform.metadata.graph import MetadataGraph

@pytest.mark.parametrize('dialect', ['snowflake','bigquery','redshift','postgres','oracle','databricks','spark','duckdb'])
def test_dialects(dialect):
    assert review_sql('SELECT a.id FROM accounts a WHERE a.id = 1', dialect)['parseable']

@pytest.mark.parametrize('sql,rule', [
    ('select * from x','SELECT_STAR'), ('select a.id from a join b','MISSING_JOIN_PREDICATE'),
    ('delete from x','UNBOUNDED_DML'), ('update x set a=1','UNBOUNDED_DML'),
    ('truncate table x','UNSAFE_DDL'), ('drop table x','UNSAFE_DDL'),
    ('select a/0 from x','UNSAFE_DIVISION'), ('select distinct a from x','EXPENSIVE_DISTINCT'),
    ('select a as x, b as x from t','DUPLICATE_OUTPUT_COLUMNS'), ('select a as x, a as y from t','DUPLICATE_PROJECTIONS'),
    ('select sum(a) over () from x','UNBOUNDED_WINDOW'), ('select a from x where a = NULL','NULL_SEMANTICS'),
    ('select a from x where a not in (1,null)','NULL_NOT_IN'), ('select random()','NON_DETERMINISTIC'),
    ('with x as (select 1) select 2','UNUSED_CTE'), ('select a, sum(b) from x','BAD_GROUP_BY'),
    ('select * from fact_sales','UNFILTERED_FACT_SCAN'), ('select a from x where lower(a)=\'a\'','NON_SARGABLE_PREDICATE'),
    ('select * from a cross join b','UNBOUNDED_CROSS_JOIN'), ('select a.id from a join b on a.id > b.id','JOIN_FANOUT_RISK'),
    ('select id from a join b on a.id=b.id','AMBIGUOUS_REFERENCE'),
    ('select (select b.id from b where b.id=a.id) as v from a','CORRELATED_SUBQUERY'),
    ('select foo(a) from t','UNSUPPORTED_DIALECT_FUNCTION'),
    ('select * from (select * from a order by id) q','ORDER_BY_INEFFICIENCY'),
    ("select 1 where '1'=1",'IMPLICIT_CAST'),
    ('merge into a using b on true when matched then delete','UNSAFE_MERGE'),
])
def test_rule_evidence(sql,rule):
    result=review_sql(sql)
    assert result['parseable'],result
    finding=next(f for f in result['findings'] if f['rule_id']==rule)
    assert {'line','column','evidence','recommendation','severity'} <= finding.keys()
    assert finding['evidence'] and finding['recommendation']

def test_multi_statement_and_safe_division():
    assert review_sql('select 1; delete from x')['status']=='FAIL'
    for denominator in ('NULLIF(b,0)','2'):
        assert not any(f['rule_id']=='UNSAFE_DIVISION' for f in review_sql(f'select a/{denominator} from t')['findings'])
    assert not review_sql('')['parseable']

def test_nested_lineage_and_case_window():
    sql='''with a as (select id, amount from raw.orders), b as
    (select id as guest, cast(amount as decimal) as value from a)
    select guest, case when value>0 then sum(value) over(partition by guest) else 0 end as total from b'''
    result=column_lineage(sql)
    assert result['status']=='PASS',result
    assert {'table':'raw.orders','column':'id'} in result['mappings'][0]['sources']
    assert {'table':'raw.orders','column':'amount'} in result['mappings'][1]['sources']
    assert table_lineage(sql)['tables']==['raw.orders']

def test_star_schema_and_ambiguous():
    assert column_lineage('select * from x',schema={'x':{'id':'INT','value':'TEXT'}})['status']=='PASS'
    assert column_lineage('select * from x')['status']=='PARTIAL'
    assert column_lineage('select id from a join b on a.id=b.id')['status']=='PARTIAL'
    assert column_lineage('select id, id from a')['status']=='ERROR'
    assert column_lineage('{{ arbitrary_macro() }}')['status']=='ERROR'

def test_manifest_column_graph(tmp_path):
    g=MetadataGraph(tmp_path/'index.sqlite')
    n=lambda name,code,deps: {'name':name,'resource_type':'model','raw_code':code,'depends_on':{'nodes':deps}}
    result=g.import_manifest({'nodes':{'model.x.stage':n('stage',"select id as guest from {{ source('raw','orders') }}",[]),
                                    'model.x.mart':n('mart',"select guest as guest_key from {{ ref('stage') }}",['model.x.stage'])}})
    assert not result['unresolved']
    assert g.traverse('raw.orders.id')['items']==['mart.guest_key','stage.guest']
    assert g.traverse('mart.guest_key','upstream')['items']==['raw.orders.id','stage.guest']
