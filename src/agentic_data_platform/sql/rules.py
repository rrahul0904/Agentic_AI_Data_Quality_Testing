"""AST rules. Findings describe risks, not query-plan or cardinality guarantees."""
from collections import Counter
from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope


def analyze(tree, schema=None):
    findings = []

    def emit(rule, node, message, recommendation, severity='WARN'):
        positions = [n.meta for n in node.walk() if n.meta.get('line')]
        pos = min(positions, key=lambda p: (p['line'], p.get('col', 0))) if positions else {}
        findings.append(dict(rule_id=rule, severity=severity, message=message,
                             line=pos.get('line'), column=pos.get('col'), evidence=node.sql(),
                             recommendation=recommendation))

    for select in tree.find_all(exp.Select):
        projections = select.expressions
        if any(p.is_star for p in projections):
            emit('SELECT_STAR', select, 'Wildcard projection couples output to schema.', 'Project explicit columns.')
        names = Counter(p.alias_or_name for p in projections if p.alias_or_name)
        if any(v > 1 for v in names.values()):
            emit('DUPLICATE_OUTPUT_COLUMNS', select, 'Output names are duplicated.', 'Assign unique aliases.', 'ERROR')
        expressions = Counter(p.unalias().sql() for p in projections)
        if any(v > 1 for v in expressions.values()):
            emit('DUPLICATE_PROJECTIONS', select, 'An expression is projected repeatedly.', 'Remove redundant projections.')
        if select.args.get('distinct'):
            emit('EXPENSIVE_DISTINCT', select, 'DISTINCT may require a global hash or sort.', 'Verify the intended grain.', 'INFO')
        joins = select.args.get('joins', [])
        seen = set()
        for join in joins:
            kind = str(join.args.get('kind', '')).upper()
            predicate = join.args.get('on') or join.args.get('using')
            natural = str(join.args.get('method', '')).upper() == 'NATURAL'
            if not predicate and not natural:
                emit('CARTESIAN_JOIN', join, 'Join can produce a Cartesian product.', 'Add the intended join predicate.', 'ERROR')
                if kind != 'CROSS':
                    emit('MISSING_JOIN_PREDICATE', join, 'Join has no ON or USING clause.', 'Specify matching keys.', 'ERROR')
            if kind == 'CROSS' and not select.args.get('limit'):
                emit('UNBOUNDED_CROSS_JOIN', join, 'Cross join has no output bound.', 'Estimate the product of input row counts.')
            on = join.args.get('on')
            if on and not any(isinstance(n, exp.EQ) for n in on.walk()):
                emit('JOIN_FANOUT_RISK', join, 'Non-equality join may produce high fanout.', 'Verify cardinality with a query plan.')
            signature = (join.this.sql(), on.sql() if on else '')
            if signature in seen:
                emit('DUPLICATE_JOIN', join, 'Identical join repeated.', 'Verify whether this join is redundant.')
            seen.add(signature)
        group = select.args.get('group')
        has_agg = any(p.find(exp.AggFunc) and not p.find(exp.Window) for p in projections)
        if group or has_agg:
            grouped = {g.sql() for g in group.expressions} if group else set()
            for p in projections:
                if p.find(exp.Column) and not p.find(exp.AggFunc) and not p.find(exp.Window):
                    if p.unalias().sql() not in grouped and p.alias_or_name not in grouped:
                        emit('BAD_GROUP_BY', p, 'Projection may not be grouped or aggregated.', 'Include it in GROUP BY or aggregate it.', 'ERROR')
        if select.args.get('order') and select.parent and not select.args.get('limit'):
            if isinstance(select.parent, (exp.CTE, exp.Subquery)):
                emit('ORDER_BY_INEFFICIENCY', select.args['order'], 'Inner ORDER BY may be discarded.', 'Order at the consumer unless limiting rows.', 'INFO')
        from_ = select.args.get('from_')
        if from_ and isinstance(from_.this, exp.Table) and from_.this.name.lower().startswith(('fact_', 'fct_')):
            if not select.args.get('where') and not select.args.get('limit'):
                emit('UNFILTERED_FACT_SCAN', select, 'Fact relation is scanned without a filter.', 'Filter partition or date columns.')
        where = select.args.get('where')
        if where:
            for comparison in where.find_all(exp.Predicate):
                if isinstance(comparison.this, (exp.Func, exp.Cast)) and comparison.this.find(exp.Column):
                    emit('NON_SARGABLE_PREDICATE', comparison, 'Function on filtered column may prevent pruning.', 'Compare the raw column to a transformed constant.')

    # SQLGlot has represented NOT IN differently across dialects/releases (for example,
    # a Not wrapper, an In flag, or a predicate rendered by a wider parent expression).
    # Detect it from the canonical SQL emitted by the parsed AST, but require an actual In
    # node so string literals/comments containing the phrase cannot trigger this rule.
    canonical_sql = ' '.join(tree.sql().upper().split())
    has_not_in = any(True for _ in tree.find_all(exp.In)) and (
        ' NOT IN ' in f' {canonical_sql} ' or ' NOT IN(' in f' {canonical_sql} '
    )
    if has_not_in:
        target = next(tree.find_all(exp.In), tree)
        emit('NULL_NOT_IN', target,
             'NULL in NOT IN input can reject all rows.',
             'Use NOT EXISTS or exclude NULL input.')

    for node in tree.walk():
        if isinstance(node, (exp.Delete, exp.Update)) and not node.args.get('where'):
            emit('UNBOUNDED_DML', node, 'DELETE/UPDATE has no WHERE.', 'Add a bounded predicate.', 'ERROR')
        if isinstance(node, (exp.Drop, exp.TruncateTable)):
            emit('UNSAFE_DDL', node, 'Destructive DDL.', 'Require an approved recovery plan.', 'CRITICAL')
        if isinstance(node, exp.Merge):
            on = node.args.get('on')
            if not on or not on.find(exp.Column) or not on.find(exp.EQ):
                emit('UNSAFE_MERGE', node, 'MERGE lacks a verifiable equality key.', 'Match unique keys and validate source uniqueness.', 'ERROR')
        if isinstance(node, exp.Div):
            right = node.right
            safe = isinstance(right, exp.Nullif) or (isinstance(right, exp.Literal) and not right.is_string and float(right.this) != 0)
            if not safe:
                emit('UNSAFE_DIVISION', node, 'Denominator may be zero.', 'Use NULLIF(denominator, 0).')
        if isinstance(node, exp.Window):
            spec = node.args.get('spec')
            if not node.args.get('partition_by') or (spec and 'UNBOUNDED' in spec.sql().upper()):
                emit('UNBOUNDED_WINDOW', node, 'Window can process an entire relation or partition.', 'Verify partition size and bound the frame.')
        if isinstance(node, exp.Table) and '*' in node.name:
            emit('WILDCARD_TABLE_SCAN', node, 'Wildcard relation can scan many tables.', 'Filter table suffix or use explicit tables.')
        if isinstance(node, exp.Func):
            name = node.name.upper() if isinstance(node, exp.Anonymous) else node.sql_name().upper()
            if name in {'RAND', 'RANDOM', 'CURRENT_TIMESTAMP', 'CURRENT_DATE', 'UUID', 'UUID_STRING'}:
                emit('NON_DETERMINISTIC', node, 'Time/random function makes output non-repeatable.', 'Pass a fixed run timestamp or seed.')
            if isinstance(node, exp.Anonymous):
                emit('UNSUPPORTED_DIALECT_FUNCTION', node, f'Function {name} is unresolved (possibly a UDF).', 'Verify the function exists in the target warehouse.', 'INFO')
                emit('FUNCTION_PORTABILITY', node, 'Unresolved function requires a portability check.', 'Supply a target implementation before migration.', 'INFO')
        if isinstance(node, (exp.EQ, exp.NEQ)) and (isinstance(node.left, exp.Null) or isinstance(node.right, exp.Null)):
            emit('NULL_SEMANTICS', node, 'Equality comparison with NULL evaluates UNKNOWN.', 'Use IS NULL or IS NOT NULL.', 'ERROR')
        if isinstance(node, (exp.EQ, exp.GT, exp.LT, exp.GTE, exp.LTE)):
            if isinstance(node.left, exp.Literal) and isinstance(node.right, exp.Literal) and node.left.is_string != node.right.is_string:
                emit('IMPLICIT_CAST', node, 'Mixed string/numeric comparison uses implicit coercion.', 'Use explicit typed literals.')
        if isinstance(node, (exp.Qualify, exp.Pivot)):
            emit('WAREHOUSE_SPECIFIC_SYNTAX', node, 'Construct needs target-dialect validation.', 'Transpile and compile against the destination.', 'INFO')
        if isinstance(node, exp.Subquery):
            depth, parent = 0, node.parent
            while parent:
                depth += isinstance(parent, exp.Subquery)
                parent = parent.parent
            if depth >= 2:
                emit('NESTED_SUBQUERY_COMPLEXITY', node, 'Three or more nested subquery levels.', 'Separate transformations into named steps.', 'INFO')
    for scope in traverse_scope(tree) or []:
        if scope.is_correlated_subquery:
            emit('CORRELATED_SUBQUERY', scope.expression, 'Subquery references an outer scope.', 'Inspect plan for repeated execution.')
        if len(scope.selected_sources) > 1:
            for c in scope.columns:
                if not c.table:
                    emit('AMBIGUOUS_REFERENCE', c, 'Unqualified reference in a multi-source scope.', 'Qualify the column with its relation alias.')
        used = {t.name.casefold() for t in scope.tables}
        # Count references in sibling CTE bodies as well as the parent query.
        for _, cte_scope in scope.cte_sources.items():
            used.update(t.name.casefold() for t in cte_scope.tables)
        with_ = scope.expression.args.get('with_')
        if with_:
            for cte in with_.expressions:
                if cte.alias_or_name.casefold() not in used:
                    emit('UNUSED_CTE', cte, 'CTE is not referenced.', 'Remove dead transformation logic.', 'INFO')
    return findings
