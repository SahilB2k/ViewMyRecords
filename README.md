# Unified Data Migration & Ingestion Prototype

A specialized tooling suite designed to automate the extraction, transformation, and loading (ETL) of high-value documents from complex web sources (arXiv, Indian Patent Office) and local staging environments into a structured, queryable storage format.

This system emphasizes **resilience**, **metadata preservation**, and **hierarchy flattening ("squashing")** to optimize for subsequent RAG (Retrieval-Augmented Generation) or archival workflows.

## 🚀 Key Modules

### 1. arXiv Ingestion Engine (`direct_arxiv_download.py`)
**Targeted extraction of scientific papers with high-fidelity metadata.**

- **Mechanism:** Uses **Playwright** to dynamically traverse arXiv categories (e.g., Computer Science > AI).
- **Smart Squashing:** Flattens the deep 5-level web hierarchy (Archive > Category > Year > Month > Paper) into a streamlined 3-level local structure:
  - `Category_Year_Month` (e.g., `AI_2024_January`)
  - `Record_ID` (e.g., `Paper_2401_12345`)
  - `Files` (`document.pdf`, `metadata.json`)
- **Output:** Downloads the full PDF and generates a rich `metadata.json` containing authors, titles, and discovery timestamps.

### 2. IPO Journal Automation (`ipo_automation.py`)
**Automated retrieval of official journals from the Indian Patent Office.**

- **Mechanism:** Scrapes the IPO tabular interface, parses multiple download parts, and efficiently manages browser pop-ups for file downloads.
- **Stealth Mode:** Implements "Human Mode" heuristics (randomized delays, jitter) to gracefully bypass simple rate-limiting filters.
- **Organization:** `Year_Month` / `Journal_ID` / `Part_Folder`.

### 3. Local Migration Core (`migration_engine.py`)
**Batch processing engine for restructuring local datasets.**

- **Purpose:** Moves files from a raw `staging/` area to a `final_storage/` destination based on strict metadata rules.
- **Configurable:** Driven by `config/structure_config.json` (path rules) and `metadata/file_index.json` (file attributes).
- **Auditing:** Produces detailed CSV logs (`logs/migration_log.csv`) tracking source, destination, timestamp, and success status for every file operation.

---

## 🛠️ Installation & Setup

### Prerequisites
- Python 3.8+
- [Playwright](https://playwright.dev/)

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Install Browser Binaries
Required for the web scrapers (arXiv & IPO):
```bash
playwright install chromium
```

---

## 🏃 Usage

### Run arXiv Ingestion
Starts the browser in visible mode (headless=False) to scrape the latest AI papers.
```bash
python direct_arxiv_download.py
```
> **Output:** `poc_storage/verified_migration/`

### Run IPO Automation
Navigates the IPO journal site and downloads recent patent journal parts.
```bash
python ipo_automation.py
```
> **Output:** `final_storage/` (or configured path)

### Run Local Migration
Processes files currently in `staging/raw_files` according to the metadata index.
```bash
python migration_engine.py
```
> **Output:** `final_storage/` + `logs/migration_log.csv`

---

## 📂 Project Structure

```text
migration-prototype/
├── config/                 # Configuration files for structure mapping
│   └── structure_config.json
├── logs/                   # Execution logs (CSV audit trails & errors)
├── metadata/               # Source metadata indices (file_index.json)
├── poc_storage/            # Output location for automated web ingestion
├── staging/                # Input location for local file migration
├── final_storage/          # Final destination for processed files
├── web_ui/                 # Prototype dashboard (HTML)
├── direct_arxiv_download.py   # arXiv scraper script
├── ipo_automation.py          # IPO journal scraper script
└── migration_engine.py        # Core local migration logic
```

## 📝 Logging & Auditing

The system maintains a rigorous audit trail in the `logs/` directory:
- **migration_log.csv:** A structured CSV recording `timestamp`, `source_path`, `target_path`, and `index_id` for every moved file.
- **error_log.txt:** Captures detailed stack traces for any failed downloads or transfer errors.
