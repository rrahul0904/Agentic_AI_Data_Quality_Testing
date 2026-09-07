"""Public SQL intelligence API, preserving existing call signatures."""
import sqlglot
from .lineage import column_lineage, table_lineage, dialect_name
from .rules import analyze


def review_sql(sql, dialect=None, schema=None):
    try:
        trees = [t for t in sqlglot.parse(sql, read=dialect_name(dialect)) if t]
        if not trees: raise ValueError('SQL is empty')
        findings = [dict(f, statement_index=i) for i, tree in enumerate(trees) for f in analyze(tree, schema)]
        return {'parseable': True, 'dialect': dialect or 'ansi', 'statement_type': trees[0].key.upper(),
                'statement_count': len(trees), 'tables': table_lineage(sql, dialect).get('tables', []),
                'findings': findings, 'status': 'FAIL' if any(f['severity'] in {'ERROR', 'CRITICAL'} for f in findings) else 'PASS'}
    except (ValueError, sqlglot.errors.SqlglotError) as exc:
        return {'parseable': False, 'status': 'FAIL', 'dialect': dialect or 'ansi', 'tables': [],
                'findings': [{'rule_id': 'SQL_PARSE', 'severity': 'ERROR', 'message': str(exc),
                              'line': None, 'column': None, 'evidence': sql, 'recommendation': 'Correct syntax/dialect.'}]}


def sql_lineage(sql, dialect=None, **kwargs):
    return {**column_lineage(sql, dialect, **kwargs), 'review': review_sql(sql, dialect)}


def column_upstream(sql, column, dialect=None, **kwargs):
    result = column_lineage(sql, dialect, **kwargs)
    return {**result, 'column': column, 'upstream': [m for m in result['mappings'] if m['target_column'].casefold() == column.casefold()]}


def column_downstream(sql, column, dialect=None, **kwargs):
    result = column_lineage(sql, dialect, **kwargs)
    return {**result, 'column': column, 'downstream': [m for m in result['mappings'] if any(
        column.casefold() in {s['column'].casefold(), f"{s['table']}.{s['column']}".casefold()} for s in m['sources'])]}
