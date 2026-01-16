import os
import json
import re
import time
import zipfile
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# -----------------------------
# CREDENTIALS & CONFIG
# -----------------------------
VMR_CORPORATE_ID = os.getenv("VMR_CORPORATE_ID", "tvsm_hr")
VMR_USERNAME = os.getenv("VMR_USERNAME", "tvshr_sahil")
VMR_PASSWORD = os.getenv("VMR_PASSWORD", "Sahil@12")

CONFIG_FILE = "config.json"
OUTPUT_DIR = "vmr_downloads"
METADATA_DIR = os.path.join(OUTPUT_DIR, "_metadata")
ZIP_OUTPUT = "vmr_migration.zip"

# Retry Configuration
MAX_RETRIES = 3
RETRY_DELAY = 3000  # ms - increased
NAVIGATION_TIMEOUT = 30000  # ms - increased
GRID_LOAD_TIMEOUT = 20000  # ms - increased
FILE_WAIT_TIMEOUT = 5000  # ms - new: wait for files to appear

# -----------------------------
# SETUP
# -----------------------------
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {
        "base_url": "https://vmrdev.com/vmr/main.do#"
    }

CONFIG = load_config()

# Create output directories
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(METADATA_DIR, exist_ok=True)

# -----------------------------
# AUTHENTICATION
# -----------------------------
def handle_session_conflict(page_obj):
    """Handles 'Already logged in' / 'Login Here' popups."""
    try:
        login_here_btn = page_obj.locator("text='Login Here'").or_(
            page_obj.locator("a:has-text('Login Here')")
        )
        if login_here_btn.count() > 0:
            print("  [Session Conflict] Clearing conflict...")
            login_here_btn.first.click()
            page_obj.wait_for_load_state("networkidle", timeout=15000)
            page_obj.wait_for_timeout(3000)
            return True
    except:
        pass
    return False

def login_to_vmr(page_obj):
    """Robust login with session conflict handling."""
    login_url = CONFIG.get("base_url")
    print(f"Navigating to login page: {login_url}")
    
    for attempt in range(MAX_RETRIES):
        try:
            page_obj.goto(login_url, wait_until="domcontentloaded", timeout=30000)
            page_obj.wait_for_timeout(2000)
            
            if "main.do" in page_obj.url:
                print("Already logged in!")
                return True
            
            print(f"Attempt {attempt + 1}: Filling credentials...")
            
            page_obj.fill("input[name='corpName']", VMR_CORPORATE_ID)
            page_obj.fill("input[name='corpEmailID']", VMR_USERNAME)
            page_obj.fill("input[name='corpPassword']", VMR_PASSWORD)
            
            submit_btn = page_obj.locator(
                "button[type='submit'], input[type='submit'], input[type='image'][src*='login']"
            )
            if submit_btn.count() > 0:
                submit_btn.first.click()
            else:
                page_obj.press("input[name='corpPassword']", "Enter")
            
            page_obj.wait_for_timeout(3000)
            handle_session_conflict(page_obj)
            
            try:
                page_obj.wait_for_selector("span.mail-sender", timeout=15000)
                print("✓ Login successful!")
                return True
            except:
                if "main.do" in page_obj.url:
                    print("✓ Login successful!")
                    return True
                
        except Exception as e:
            print(f"  Login attempt {attempt + 1} failed: {e}")
            if attempt < MAX_RETRIES - 1:
                page_obj.wait_for_timeout(RETRY_DELAY)
            
    print("✗ Login failed after all retries")
    return False

# -----------------------------
# GRID HELPERS
# -----------------------------
def wait_for_grid(page_obj, timeout=GRID_LOAD_TIMEOUT):
    """Waits for the VMR grid to load with items."""
    try:
        # Wait for grid structure
        page_obj.wait_for_selector("span.mail-sender", timeout=timeout, state="visible")
        page_obj.wait_for_timeout(1500)  # Extra wait for dynamic content
        
        # Check if grid has content
        items = page_obj.locator("span.mail-sender").count()
        if items > 0:
            return True
        
        print("  [Warning] Grid loaded but empty")
        return False
    except:
        print("  [Warning] Grid didn't load in time")
        return False

def get_grid_items(page_obj):
    """Get all folders and files from current grid view."""
    folders = []
    files = []
    
    all_spans = page_obj.locator("span.mail-sender").all()
    
    for span in all_spans:
        try:
            txt = span.inner_text().strip()
            if not txt or txt in ["..", "Up", "Parent Folder"]:
                continue
            
            parent = span.locator("xpath=..")
            onclick = parent.get_attribute("onclick") or ""
            
            if "getFolderandFileList" in onclick:
                folders.append(txt)
            else:
                files.append(txt)
        except:
            continue
    
    return folders, files

# -----------------------------
# NAVIGATION
# -----------------------------
def click_folder(page_obj, folder_name):
    """Clicks a folder in the SPA."""
    handle_session_conflict(page_obj)
    
    folder_locator = page_obj.locator("span.mail-sender").filter(has_text=folder_name)
    if folder_locator.count() == 0:
        folder_locator = page_obj.locator(f"span.mail-sender:has-text('{folder_name}')")
    
    if folder_locator.count() == 0:
        raise Exception(f"Folder not found: {folder_name}")
    
    folder_locator.first.click()
    page_obj.wait_for_load_state("domcontentloaded")
    page_obj.wait_for_timeout(2000)  # Increased wait
    
    # Wait for grid to update
    wait_for_grid(page_obj)
    return True

def navigate_to_path(page_obj, path_list):
    """Navigate to a specific path from root."""
    print(f"  Navigating to: {' > '.join(path_list)}")
    
    # Go to root
    page_obj.goto(CONFIG.get("base_url"), wait_until="domcontentloaded", timeout=30000)
    page_obj.wait_for_timeout(2000)
    handle_session_conflict(page_obj)
    
    if not wait_for_grid(page_obj):
        raise Exception("Failed to load root")
    
    # Navigate through path
    for idx, folder_name in enumerate(path_list):
        print(f"    [{idx + 1}/{len(path_list)}] Entering: {folder_name}")
        click_folder(page_obj, folder_name)
    
    # Extra wait at destination to ensure files load
    page_obj.wait_for_timeout(FILE_WAIT_TIMEOUT)
    return True

# -----------------------------
# METADATA EXTRACTION
# -----------------------------
def extract_file_metadata(page_obj, row):
    """Extract metadata from file info dialog."""
    metadata = {}
    
    try:
        # Click info button
        info_btn = row.locator("a[onclick*='viewDocumentDetails'], img[src*='info'], a[title*='info' i], i.fa-info")
        if info_btn.count() == 0:
            return metadata
        
        info_btn.first.click()
        page_obj.wait_for_timeout(2000)
        
        # Extract all metadata fields
        metadata_fields = [
            "Classification",
            "Document Sub Type",
            "Quick Reference",
            "Document Date",
            "Expiry Date",
            "Lifespan",
            "Offsite Location",
            "On-Premises Location",
            "Remarks",
            "Category",
            "Keywords",
            "doctype"
        ]
        
        for field in metadata_fields:
            try:
                # Try to find label and value
                label = page_obj.locator(f"text='{field}'").or_(
                    page_obj.locator(f"label:has-text('{field}')")
                )
                
                if label.count() > 0:
                    # Get next element (usually contains value)
                    value_elem = label.first.locator("xpath=following-sibling::*[1]")
                    if value_elem.count() > 0:
                        metadata[field] = value_elem.inner_text().strip()
                    else:
                        # Try parent row approach
                        row_elem = label.first.locator("xpath=ancestor::tr[1]")
                        if row_elem.count() > 0:
                            cells = row_elem.locator("td").all()
                            if len(cells) > 1:
                                metadata[field] = cells[1].inner_text().strip()
            except:
                continue
        
        # Close dialog
        page_obj.keyboard.press("Escape")
        page_obj.wait_for_timeout(500)
        
    except Exception as e:
        print(f"    [Warning] Metadata extraction failed: {e}")
    
    return metadata

# -----------------------------
# DOWNLOAD FUNCTIONS
# -----------------------------
def download_file_with_metadata(page_obj, filename, file_path, folder_path):
    """Download a single file and its metadata."""
    print(f"    Downloading: {filename}")
    
    try:
        # Wait a bit more to ensure files are visible
        page_obj.wait_for_timeout(1000)
        
        # Find file row - multiple strategies
        row = None
        
        # Strategy 1: Exact text match
        row_locator = page_obj.locator("tr").filter(has_text=filename)
        if row_locator.count() > 0:
            row = row_locator.first
        
        # Strategy 2: Partial match
        if not row:
            row_locator = page_obj.locator("tr").filter(has_text=re.compile(re.escape(filename[:20]), re.I))
            if row_locator.count() > 0:
                row = row_locator.first
        
        # Strategy 3: Find via span and get parent row
        if not row:
            span = page_obj.locator("span.mail-sender").filter(has_text=filename)
            if span.count() > 0:
                row = span.first.locator("xpath=ancestor::tr")
                if row.count() > 0:
                    row = row.first
        
        if not row:
            print(f"      ✗ File not visible in grid: {filename}")
            return None
        
        # Extract metadata first
        metadata = extract_file_metadata(page_obj, row)
        
        # Select checkbox
        checkbox = row.locator("input[type='checkbox']")
        if checkbox.count() > 0:
            checkbox.first.check()
            page_obj.wait_for_timeout(2000)  # Wait for toolbar to enable
        
        # Find and click download button
        dl_btn = page_obj.locator("a#multipleFile_download")
        
        if dl_btn.count() == 0 or not dl_btn.first.is_visible():
            dl_btn = page_obj.locator("i.fa-download.mutiplefiledownloadiconclr").locator("xpath=ancestor::a")
        
        if dl_btn.count() == 0:
            print(f"      ✗ Download button not found")
            return None
        
        # Download file
        try:
            with page_obj.expect_download(timeout=60000) as download_info:
                dl_btn.first.click(force=True)
                page_obj.wait_for_timeout(1000)
            
            download = download_info.value
            download.save_as(file_path)
            print(f"      ✓ Downloaded: {filename}")
            
        except Exception as e:
            print(f"      ✗ Download failed: {e}")
            return None
        
        # Save metadata
        if metadata:
            metadata_file = os.path.join(
                METADATA_DIR,
                folder_path.replace(os.sep, "_") + "_" + filename + ".json"
            )
            with open(metadata_file, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        # Uncheck to prepare for next file
        if checkbox.count() > 0:
            checkbox.first.uncheck()
            page_obj.wait_for_timeout(500)
        
        return {
            "filename": filename,
            "path": file_path,
            "metadata": metadata,
            "status": "success"
        }
        
    except Exception as e:
        print(f"      ✗ Error downloading {filename}: {e}")
        return None

def download_folder_recursive(page_obj, current_path, output_base, results):
    """Recursively download all files in a folder and its subfolders."""
    
    path_str = " > ".join(current_path)
    print(f"\n[Processing] {path_str}")
    
    # Get current folder contents
    folders, files = get_grid_items(page_obj)
    print(f"  Found: {len(folders)} folders, {len(files)} files")
    
    # Create local folder structure
    local_folder = os.path.join(output_base, *current_path[1:])  # Skip "Group or Department"
    os.makedirs(local_folder, exist_ok=True)
    
    # Download all files in current folder
    if files:
        print(f"  Downloading {len(files)} files...")
        for filename in files:
            if filename in ["My Records", "My Activity", "Group or Department"]:
                continue
            
            file_path = os.path.join(local_folder, filename)
            relative_path = os.path.relpath(file_path, output_base)
            
            result = download_file_with_metadata(page_obj, filename, file_path, relative_path)
            if result:
                results.append(result)
    
    # Process subfolders
    if folders:
        print(f"  Processing {len(folders)} subfolders...")
        for idx, folder in enumerate(folders):
            print(f"\n  [{idx+1}/{len(folders)}] Entering: {folder}")
            
            try:
                # Enter subfolder
                click_folder(page_obj, folder)
                
                # Recurse
                download_folder_recursive(
                    page_obj,
                    current_path + [folder],
                    output_base,
                    results
                )
                
                # Navigate back - use back button
                print(f"  Returning to: {path_str}")
                page_obj.go_back(wait_until="domcontentloaded")
                page_obj.wait_for_timeout(2000)
                
                # Verify we're back
                if not wait_for_grid(page_obj):
                    print("  [Warning] Grid didn't load after back, resetting...")
                    navigate_to_path(page_obj, current_path)
                
            except Exception as e:
                print(f"  [Error] Failed to process subfolder '{folder}': {e}")
                # Try to recover by navigating back to current path
                try:
                    navigate_to_path(page_obj, current_path)
                except:
                    print("  [Critical] Failed to recover, skipping remaining subfolders")
                    break

# -----------------------------
# MAIN MIGRATION FUNCTION
# -----------------------------
def run_migration():
    """Main migration: Download entire folder structure with metadata."""
    
    print("=" * 70)
    print("VMR COMPLETE MIGRATION TOOL")
    print("Downloads full folder structure with metadata")
    print("=" * 70)
    
    results = []
    
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            accept_downloads=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = context.new_page()
        
        # Login
        if not login_to_vmr(page):
            print("✗ Login failed, aborting")
            browser.close()
            return
        
        # Navigate to root folder
        print("\nNavigating to root folder...")
        if not wait_for_grid(page):
            print("✗ Grid didn't load")
            browser.close()
            return
        
        try:
            click_folder(page, "Group or Department")
        except Exception as e:
            print(f"✗ Failed to enter root: {e}")
            browser.close()
            return
        
        # Start recursive download
        try:
            download_folder_recursive(
                page,
                ["Group or Department"],
                OUTPUT_DIR,
                results
            )
        except Exception as e:
            print(f"\n✗ Migration error: {e}")
        
        browser.close()
    
    # Create summary report
    print("\n" + "=" * 70)
    print("MIGRATION SUMMARY")
    print("=" * 70)
    print(f"Total files downloaded: {len(results)}")
    print(f"Output directory: {OUTPUT_DIR}")
    print(f"Metadata directory: {METADATA_DIR}")
    
    # Save results manifest
    manifest_file = os.path.join(OUTPUT_DIR, "migration_manifest.json")
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "total_files": len(results),
            "files": results
        }, f, indent=2, ensure_ascii=False)
    
    print(f"Manifest saved: {manifest_file}")
    
    # Create ZIP archive
    print(f"\nCreating ZIP archive: {ZIP_OUTPUT}")
    try:
        with zipfile.ZipFile(ZIP_OUTPUT, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(OUTPUT_DIR):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, OUTPUT_DIR)
                    zipf.write(file_path, arcname)
        
        print(f"✓ ZIP created successfully: {ZIP_OUTPUT}")
        print(f"  Size: {os.path.getsize(ZIP_OUTPUT) / 1024 / 1024:.2f} MB")
    except Exception as e:
        print(f"✗ Failed to create ZIP: {e}")
    
    print("\n✓ Migration complete!")

# -----------------------------
# ENTRY POINT
# -----------------------------
if __name__ == "__main__":
    run_migration()