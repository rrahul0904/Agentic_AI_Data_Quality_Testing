# Active source-table scope

The project workspace has two different concepts that must not be combined:

- **Saved project scope**: the source tables the user has added to the project.
- **Active workflow scope**: the one source table currently being inspected or run.

The discovery page renders only assets from the active workflow scope. It never falls back to unscoped or older discovery results. Historical discovery remains persisted with its original table and run scope, but it is not current workflow state.

When the saved state contains selected assets that do not belong to the active source table, the UI fails closed by excluding them from the current selection. Changing the active table clears current selections, analysis scope, and quality-plan scope while retaining historical evidence.

The current discovery count is therefore the count for the active table, not the PostgreSQL catalog count and not the total of all historical discovery runs. The PostgreSQL catalog count is shown separately in the source-table chooser.

Lineage opens on the full accepted project catalog: all accepted flows are combined and accepted top-level objects with no supported relationship remain visible as unconnected nodes. Duplicate rows carrying the same stable asset ID are rendered once while retaining their exact source-table associations. No relationship is invented to make the graph look complete. The table, flow, source, target, layer, and asset-selection controls narrow that view when needed. This is lineage analysis of saved discovery/analysis evidence, not a request to execute every job. Tables without accepted discovery evidence cannot appear until they are discovered. “Selected assets only” remains an explicit narrow view, and an empty selection produces an empty graph.
