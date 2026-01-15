# Unified Data Migration & Ingestion Prototype

A specialized tooling suite designed to automate the extraction, transformation, and loading (ETL) of high-value documents from complex web sources (arXiv, Indian Patent Office) and local staging environments into a structured, queryable storage format.

This system emphasizes **resilience**, **metadata preservation**, and **hierarchy flattening ("squashing")** to optimize for subsequent RAG (Retrieval-Augmented Generation) or archival workflows.

### Run Full Migration Engine (Web Crawl + Form Metadata)
The standard engine that simulates a recursive web crawl, scrapes form metadata, and flattens deep hierarchies by skipping levels (e.g., Month) and renaming folders via Regex.
1. Define rules in `migration-config-full.json`
2. Start server: `python -m http.server 8000`
3. Run: `python full_migration_engine.py`

### Run Optimized Engine (For Scale / 100k+ Files)
Optimized for high-volume migrations with **Resumability** and **Fast Logging**.
- **JSONL Manifest**: Uses `migration_manifest.jsonl` for O(1) append performance.
- **State Awareness**: Skips already migrated files if interrupted.
```bash
python full_migration_engine_optimized.py
```

---

## 📂 Project Structure

```text
migration-prototype/
├── config/                 # Configuration files for structure mapping
│   └── structure_config.json
├── logs/                   # Execution logs (CSV audit trails & errors)
├── metadata/               # Source metadata indices (file_index.json)
├── staging/                # Input location for local file migration
├── web_ui/                 # Prototype dashboard (HTML)
├── full_migration_engine.py   # Full recursive web crawler & path flattener
└── migration-config-full.json # Rules for full migration (regex & skip logic)
```


## 📝 Logging & Auditing

The system maintains a rigorous audit trail in the `logs/` directory:
- **migration_log.csv:** A structured CSV recording `timestamp`, `source_path`, `target_path`, and `index_id` for every moved file.
- **error_log.txt:** Captures detailed stack traces for any failed downloads or transfer errors.
