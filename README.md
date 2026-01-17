# VMR Migration Tool

A robust, production-ready automation engine designed to migrate files and metadata from the ViewMyRecords (VMR) platform. This tool crawls the VMR folder structure recursively, downloads every file, extracts comprehensive metadata into sidecar JSON files, and packages everything into a portable ZIP archive.

## 🚀 Key Features

- **Recursive Crawling**: Navigates the entire "Group or Department" folder hierarchy, handling nested subfolders of any depth.
- **Metadata Extraction**: Captures detailed metadata for every file (Classification, Document Type, Expiry Date, Remarks, etc.) and saves it as a JSON sidecar file.
- **Resilient Navigation**: Built with SPA-aware logic to handle breadcrumbs, back-button navigation, and dynamic content loading.
- **Session Management**: Automatically detects and resolves recursive login sessions and "Login Here" conflicts.
- **Manifest Generation**: Creates a `migration_manifest.json` reporting the status of every downloaded file.
- **Automated Archiving**: Zips the entire downloaded dataset into `vmr_migration.zip` for easy transfer.
- **Error Recovery**: Includes retry logic for network timeouts, grid loading failures, and missing elements.

## 📋 Prerequisites

- **Python 3.8+**
- **Playwright**: For browser automation.
- **python-dotenv**: For secure credential management.

## 🛠️ Installation

1.  **Clone the repository** (if applicable) or navigate to the project directory.

2.  **Create a virtual environment** (recommended):
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

3.  **Install dependencies**:
    ```bash
    pip install playwright python-dotenv
    ```

4.  **Install Playwright browsers**:
    ```bash
    playwright install chromium
    ```

## ⚙️ Configuration

### 1. Environment Variables (`.env`)
Create a `.env` file in the project directory (or parent directory) with your VMR credentials. The script looks for keys exactly as defined below:

```ini
VMW_CORPORATE_USERID=your_corporate_id
VRM_USER_NAME=your_username
VMR_USER_PASSWORD=your_password
```

### 2. Application Config (`config.json`)
Optional. Create a `config.json` file to override defaults:

```json
{
  "base_url": "https://vmrdev.com/vmr/main.do#"
}
```

## ▶️ Usage

Run the migration engine:

```bash
python production_migration_engine.py
```

### What to Expect
1.  **Login**: The script will launch a headless browser and log in.
2.  **Navigation**: It will navigate to the "Group or Department" root.
3.  **Crawling**: You will see logs in the console as it enters folders and downloads files.
4.  **Completion**: Upon finishing, it will generate a summary and a ZIP file.

## 📂 Output Structure

After a successful run, your directory will contain:

```text
vmr_downloads/
├── Group or Department/
│   ├── HR/
│   │   ├── Policy.pdf
│   │   └── OfferLetter.docx
│   └── Finance/
│       └── Invoice.pdf
├── _metadata/
│   ├── Group or Department_HR_Policy.pdf.json
│   └── Group or Department_Finance_Invoice.pdf.json
└── migration_manifest.json

vmr_migration.zip  <-- All of the above zipped
```

## 🔧 Troubleshooting

- **Login Failed**: Ensure your credentials in `.env` are correct. The script handles the dual-login conflict, but valid credentials are required.
- **Timeout Errors**: If the VMR site is slow, you can increase `NAVIGATION_TIMEOUT` or `GRID_LOAD_TIMEOUT` in the script configuration constants.
- **Empty Grid**: If the script says "Grid loaded but empty", ensure the account has permissions to view the "Group or Department" folder.
