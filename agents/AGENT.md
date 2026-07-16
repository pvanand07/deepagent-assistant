# Workspace Agent Instructions

- Do not rely on `write_file` to overwrite files. If a file with the same name
  already exists, choose a new name or edit the existing file intentionally with
  the appropriate edit tool.
- If invoking the research agent for a query given by user, use the exact query as instruction, do not elaborate, for other research tasks use minimal human language to keep the research task concise. 