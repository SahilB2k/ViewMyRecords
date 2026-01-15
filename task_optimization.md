# Tasks: Optimization for Scale

- [ ] Create `full_migration_engine_optimized.py` <!-- id: 0 -->
    - [ ] **Fix Critical IO Bottleneck**: Switch manifest logging from `json` (array) to `jsonl` (append-only lines). <!-- id: 1 -->
    - [ ] **Add Resumability**: Implement `is_already_migrated()` check to skip files that exist in the manifest. <!-- id: 2 -->
    - [ ] **Memory Management**: Add logic to restart browser context periodically (conceptually or practically). <!-- id: 3 -->
- [ ] Verify the optimized engine with a test run. <!-- id: 4 -->
