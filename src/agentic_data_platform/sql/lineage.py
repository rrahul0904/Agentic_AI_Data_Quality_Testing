"""Scope-aware SQLGlot lineage with explicit unresolved evidence."""
import re
import sqlglot
from sqlglot import exp
from sqlglot.lineage import lineage
from sqlglot.optimizer.scope import traverse_scope

DIALECTS = {'postgresql': 'postgres', 'sqlserver': 'tsql', 'ansi': None, 'spark': 'spark'}


def dialect_name(dialect):
    return DIALECTS.get(dialect, dialect)


def render_references(sql, references=None):
    references = references or {}
    def replace(match):
        kind, body = match.groups()
        parts = re.findall(r"['\"]([^'\"]+)['\"]", body)
        key = '.'.join(parts)
        if not parts:
            raise ValueError('Dynamic dbt reference requires compiled SQL')
        return references.get(f'{kind}:{key}', references.get(key, key))
    result = re.sub(r'\{\{\s*(ref|source)\((.*?)\)\s*\}\}', replace, sql)
    result = re.sub(r'\{\{\s*config\(.*?\)\s*\}\}', '', result, flags=re.S)
    if '{{' in result or '{%' in result:
        raise ValueError('Unresolved Jinja: supply dbt compiled_code')
    return result


def table_lineage(sql, dialect=None, references=None):
    try:
        trees = sqlglot.parse(render_references(sql, references), read=dialect_name(dialect))
        reads, writes = set(), set()
        for tree in filter(None, trees):
            for scope in traverse_scope(tree) or []:
                for _, source in scope.sources.items():
                    if isinstance(source, exp.Table):
                        reads.add('.'.join(p.sql() for p in source.parts))
            if isinstance(tree, (exp.Create, exp.Insert, exp.Merge, exp.Update, exp.Delete)):
                target = tree.this
                if isinstance(target, exp.Schema): target = target.this
                if isinstance(target, exp.Table): writes.add('.'.join(p.sql() for p in target.parts))
        return {'parseable': True, 'tables': sorted(reads), 'reads': sorted(reads), 'writes': sorted(writes)}
    except (ValueError, sqlglot.errors.SqlglotError) as exc:
        return {'parseable': False, 'tables': [], 'error': str(exc)}


def column_lineage(sql, dialect=None, schema=None, sources=None, references=None):
    try:
        rendered = render_references(sql, references)
        trees = [t for t in sqlglot.parse(rendered, read=dialect_name(dialect)) if t]
        if len(trees) != 1: raise ValueError('Column lineage requires exactly one statement')
        tree = trees[0]
        if isinstance(tree, (exp.Create, exp.Insert)): tree = tree.expression
        if not isinstance(tree, exp.Query): raise ValueError('Statement has no query projection')
        names = [p.alias_or_name for p in tree.selects]
        if len(names) != len(set(names)): raise ValueError('Duplicate output names prevent unambiguous lineage')
        nodes = lineage(None, tree, schema=schema, sources=sources, dialect=dialect_name(dialect))
        mappings, unresolved = [], []
        for name, node in nodes.items():
            leaves = set()
            missing = []
            for leaf in node.walk():
                if isinstance(leaf.expression, exp.Table):
                    table = '.'.join(p.sql() for p in leaf.expression.parts)
                    column = leaf.name.rsplit('.', 1)[-1].strip('"`')
                    leaves.add((table, column))
                    if column == '*': missing.append('Star requires schema metadata')
                elif isinstance(leaf.expression, exp.Placeholder):
                    missing.append(leaf.name)
            if name == '*': missing.append('Star requires schema metadata')
            mapping = {'target_column': name, 'sources': [{'table': t, 'column': c} for t, c in sorted(leaves)],
                       'expression': node.expression.sql(), 'resolved': not missing}
            mappings.append(mapping)
            unresolved.extend({'column': name, 'reason': reason} for reason in missing)
        return {'parseable': True, 'status': 'PARTIAL' if unresolved else 'PASS',
                'tables': sorted({s['table'] for m in mappings for s in m['sources']}),
                'mappings': mappings, 'unresolved': unresolved, 'semantics': 'value lineage; filters and joins are table dependencies'}
    except (ValueError, sqlglot.errors.SqlglotError) as exc:
        return {'parseable': False, 'status': 'ERROR', 'mappings': [], 'error': str(exc)}
