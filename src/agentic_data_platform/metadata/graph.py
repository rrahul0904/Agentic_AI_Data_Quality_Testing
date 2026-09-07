"""Import warehouse/dbt/Airflow metadata and traverse column dependencies."""
import json
from collections import deque
from .index import MetadataIndex
from agentic_data_platform.sql.lineage import column_lineage, render_references


class MetadataGraph(MetadataIndex):
    def __init__(self, path=':memory:'):
        super().__init__(path)
        self.connection.executescript('''
        CREATE TABLE IF NOT EXISTS lineage_edges (
          source TEXT NOT NULL, target TEXT NOT NULL, kind TEXT NOT NULL,
          evidence TEXT NOT NULL, PRIMARY KEY(source,target,kind));
        CREATE INDEX IF NOT EXISTS lineage_target ON lineage_edges(target);
        ''')

    def edge(self, source, target, kind='column', evidence=None):
        self.connection.execute('INSERT OR REPLACE INTO lineage_edges VALUES (?,?,?,?)',
                                (source, target, kind, json.dumps(evidence or {}, sort_keys=True)))
        self.connection.commit()

    def traverse(self, node, direction='downstream', kind=None):
        if direction not in {'upstream', 'downstream'}: raise ValueError('Invalid direction')
        edges = [dict(r) for r in self.connection.execute('SELECT * FROM lineage_edges ORDER BY source,target')]
        graph = {}
        for e in edges:
            if kind and e['kind'] != kind: continue
            a, b = (e['source'], e['target']) if direction == 'downstream' else (e['target'], e['source'])
            graph.setdefault(a, []).append(b)
        seen, queue = {node}, deque([node])
        while queue:
            for child in graph.get(queue.popleft(), []):
                if child not in seen: seen.add(child); queue.append(child)
        return {'node': node, 'direction': direction, 'items': sorted(seen - {node})}

    def import_assets(self, assets, edges=()):
        for asset in assets:
            self.upsert_asset(asset['asset_id'], asset['kind'], asset['name'], asset.get('metadata', {}))
            for column in asset.get('columns', []):
                self.upsert_column(asset['asset_id'], column['name'], column.get('data_type'),
                                   pii=bool(column.get('pii')), metadata=column)
        for edge in edges: self.edge(**edge)
        return {'assets_imported': len(assets), 'edges_imported': len(edges)}

    def import_manifest(self, manifest):
        nodes = {**manifest.get('sources', {}), **manifest.get('nodes', {}), **manifest.get('exposures', {})}
        references = {}
        relations = {}
        for uid, n in nodes.items():
            relation = n.get('relation_name') or n.get('name', uid)
            relations[uid] = relation
            key = f"source:{n.get('source_name')}.{n['name']}" if n.get('resource_type') == 'source' else f"ref:{n.get('name')}"
            references[key] = relation
            references[f"ref:{n.get('package_name')}.{n.get('name')}"] = relation
            self.upsert_asset(uid, 'dbt_' + n.get('resource_type', 'model'), uid, {**n, 'relation': relation})
            for c, meta in n.get('columns', {}).items():
                self.upsert_column(uid, c, meta.get('data_type'), metadata=meta)
        unresolved = []
        for uid, n in nodes.items():
            for dep in n.get('depends_on', {}).get('nodes', []): self.edge(dep, uid, 'asset', {'artifact': 'manifest'})
            sql = n.get('compiled_code') or n.get('compiled_sql') or n.get('raw_code') or n.get('raw_sql')
            if not sql or n.get('resource_type') not in {'model', 'snapshot'}: continue
            result = column_lineage(sql, 'snowflake', references=references)
            if result.get('status') != 'PASS': unresolved.append({'asset': uid, 'result': result})
            for m in result['mappings']:
                if not m['resolved']: continue
                for s in m['sources']:
                    self.edge(f"{s['table']}.{s['column']}".casefold(), f"{relations[uid]}.{m['target_column']}".replace('"','').casefold(),
                              evidence={'model': uid, 'expression': m['expression'], 'sql': render_references(sql, references)})
        return {'assets_imported': len(nodes), 'unresolved': unresolved}

    def summary(self):
        return {'kinds': {r[0]: r[1] for r in self.connection.execute('SELECT kind,count(*) FROM assets GROUP BY kind')},
                'columns': self.connection.execute('SELECT count(*) FROM columns').fetchone()[0],
                'edges': self.connection.execute('SELECT count(*) FROM lineage_edges').fetchone()[0]}

    def unused(self):
        return {'items': [dict(r) for r in self.connection.execute('''SELECT * FROM assets WHERE asset_id NOT IN
            (SELECT source FROM lineage_edges WHERE kind='asset') ORDER BY name''')],
                'scope': 'No indexed downstream dependencies; does not prove absence of external consumers.'}
