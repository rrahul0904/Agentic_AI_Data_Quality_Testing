# Active source-table scope

The project workspace has two different concepts that must not be combined:

- **Saved project scope**: the source tables the user has added to the project.
- **Active workflow scope**: the one source table currently being inspected or run.

The discovery page renders only assets from the active workflow scope. It never falls back to unscoped or older discovery results. Historical discovery remains persisted with its original table and run scope, but it is not current workflow state.

When the saved state contains selected assets that do not belong to the active source table, the UI fails closed by excluding them from the current selection. Changing the active table clears current selections, analysis scope, and quality-plan scope while retaining historical evidence.

The current discovery count is therefore the count for the active table, not the PostgreSQL catalog count and not the total of all historical discovery runs. The PostgreSQL catalog count is shown separately in the source-table chooser.
