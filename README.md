# VMR Crawler Stability Refinement

This project aims to finalize and stabilize the VMR (ViewMyRecords) crawler for production.

## Features
- SPA-aware navigation (breadcrumbs, back-button, ".." folder)
- Session conflict handling ("Login Here" button)
- Resilient folder and file detection
- Recursive discovery with duplicate prevention
- Metadata extraction (sidecar JSON files)
- Batch processing and error recovery

## Prerequisites
- Python 3.8+
- Playwright (`pip install playwright` then `playwright install`)

## Usage
1. Set environment variables: `VMR_CORPORATE_ID`, `VMR_USERNAME`, `VMR_PASSWORD`.
2. Run the script: `python production_migration_engine.py`.
