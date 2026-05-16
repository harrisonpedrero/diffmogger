# Symbol Identity Contract

Diffmogger stores symbol facts as language-independent `codebase` graph nodes. File graph facts remain the fallback signal, but scheduler write decisions may only trust symbol facts that resolve to one exact, non-stale owner.

Each symbol node carries `symbol_identity_schema_version: 1` and a stable `symbol_id` derived from the structural fields in this normalized identity. Confidence and resolution are stored with the identity envelope, but they do not change the stable id:

- `language`: extractor language label, for example `Python`, `TypeScript`, `Rust`, `Go`, or `Java`
- `package_name`: package/module root when the language exposes one
- `module_name`: language-native module/package path
- `file_path`: owning file when resolved, or the reference file for unresolved imports
- `qualified_name`: language-native qualified symbol name
- `symbol_kind`: normalized kind such as `class`, `function`, `method`, `component`, `struct`, `interface`, `enum`, `trait`, `record`, `type`, or `import`
- `visibility`: `public`, `private`, `protected`, `internal`, `package`, or `unknown`
- `exported`: language export/public API boolean
- `owning_range`: `start_line`, `start_col`, `end_line`, and `end_col`
- `extractor_confidence`: confidence in the extractor-emitted fact
- `resolution_kind`: `exact`, `inferred`, `ambiguous`, `unresolved`, or `stale`

Python uses AST extraction. JavaScript and TypeScript use conservative import/export and declaration extraction. Rust, Go, and Java extractors emit the same shape with regex-based confidence below AST confidence.

Unresolved external imports are represented as `symbol_kind: import` with `resolution_kind: unresolved`, no `owner_file_path`, and the importing file as `reference_file_path`. Ambiguous and stale symbol matches are advisory scheduler inputs only. They can scope work, but they cannot create direct write ownership unless a direct path or exact non-stale owner match reinforces them.

The incremental index read model stores one `codebase_file_index` row per indexed file in the active graph snapshot. Each row records the content hash, `symbol-index-v1` extractor version, indexed timestamp, language, parse status, owned symbol count, failure reason, and staleness bit. Full refreshes rebuild these rows from the graph; partial refreshes update only changed files; deleted-file refreshes remove the file row and its symbol/import facts. Scheduler impact scoring treats stale symbol evidence as advisory until the file is reindexed.
