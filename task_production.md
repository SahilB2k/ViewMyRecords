# Tasks: Production Scale Architecture

- [ ] Create `production_migration_engine.py` <!-- id: 0 -->
    - [ ] **Phase 1: Discovery** (`discover_files`): Crawl the web hierarchy and populate `migration_queue.jsonl`. <!-- id: 1 -->
    - [ ] **Phase 2: Execution** (`process_queue`): Read from Queue, Download in Batches of 50, Restart Browser. <!-- id: 2 -->
    - [ ] **Resumability**: Skip items already in `migration_manifest.jsonl`. <!-- id: 3 -->
- [ ] Verify the decoupled workflow. <!-- id: 4 -->
