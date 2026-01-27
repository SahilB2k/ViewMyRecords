import os
import json
import re
import time
import zipfile
import shutil
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from dotenv import load_dotenv

# Load environment variables from .env file (in parent directory)
load_dotenv() # Load from .env in current directory (Docker/Standard)

# -----------------------------
# CREDENTIALS & CONFIG
# -----------------------------
# Use keys exactly as defined in your .env file
VMR_CORPORATE_ID = os.getenv("VMW_CORPORATE_USERID")
VMR_USERNAME = os.getenv("VRM_USER_NAME")
VMR_PASSWORD = os.getenv("VMR_USER_PASSWORD")

CONFIG_FILE = "config.json"
OUTPUT_DIR = "Group or Department_old"
METADATA_DIR = os.path.join(OUTPUT_DIR, "_metadata")
ZIP_OUTPUT = "vmr_migration.zip"

# Retry Configuration
MAX_RETRIES = 3
RETRY_DELAY = 3000  # ms - increased
NAVIGATION_TIMEOUT = 60000  # ms - increased
GRID_LOAD_TIMEOUT = 60000  # ms - increased
FILE_WAIT_TIMEOUT = 10000  # ms - new: wait for files to appear

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

class ManifestLogger:
    """Helper to log migration results incrementally to disk to save memory."""
    def __init__(self, output_dir):
        self.log_file = os.path.join(output_dir, "results.jsonl")
        # Clear existing log if any
        if os.path.exists(self.log_file):
            os.remove(self.log_file)
            
    def log(self, entry):
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            
    def get_all_results(self):
        results = []
        if os.path.exists(self.log_file):
            with open(self.log_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        results.append(json.loads(line))
        return results

def sanitize_filename(filename):
    """Sanitize filename to be OS-safe."""
    # Replace illegal characters
    name = re.sub(r'[\\/*?:"<>|]', "_", filename)
    # Trim and remove trailing dots or spaces
    name = name.strip().rstrip(". ")
    if not name:
        name = "unnamed_file_" + str(int(time.time()))
    return name

def get_unique_local_path(directory, filename):
    """Generate a unique local path to avoid overwriting files, case-insensitively."""
    base_name = sanitize_filename(filename)
    name, ext = os.path.splitext(base_name)
    
    # Path length safeguard (Windows limit is 260)
    # 240 is a safe threshold to account for deep directory hierarchy
    if len(os.path.join(directory, base_name)) > 240:
        print(f"      [Warning] Path too long, truncating filename...")
        name = name[:(240 - len(directory) - len(ext) - 10)] # leave room for extension and counter
        base_name = name + ext

    counter = 0
    while True:
        suffix = f" ({counter})" if counter > 0 else ""
        candidate = f"{name}{suffix}{ext}"
        full_path = os.path.join(directory, candidate)
        
        # Check if any file exists in directory that matches candidate case-insensitively
        exists = False
        if os.path.exists(directory):
            for existing_item in os.listdir(directory):
                if existing_item.lower() == candidate.lower():
                    exists = True
                    break
        
        if not exists:
            return full_path
        counter += 1

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

def ensure_logged_in(page_obj):
    """Verifies session and re-logs in if necessary."""
    try:
        # Check if we're still on a page with the VMR grid or mailbox
        if page_obj.locator("span.mail-sender").count() > 0:
            return True
        
        # If we see login fields, we've been logged out
        if page_obj.locator("input[name='corpPassword']").count() > 0:
            print("  [Session] Session expired, re-logging in...")
            return login_to_vmr(page_obj)
            
        # Try to handle conflict and check again
        handle_session_conflict(page_obj)
        if page_obj.locator("span.mail-sender").count() > 0:
            return True
            
        # Catch-all: Re-navigate and login
        print("  [Session] Verification failed, attempting recovery...")
        return login_to_vmr(page_obj)
    except:
        return login_to_vmr(page_obj)

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
    """Get all folders and files from current grid view with counts for duplicates."""
    folders = []
    files = []
    file_counts = {}
    
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
                # Track occurrence for duplicate filenames in the grid
                occurrence = file_counts.get(txt, 0)
                files.append((txt, occurrence))
                file_counts[txt] = occurrence + 1
        except:
            continue
    
    return folders, files

def get_total_pages(page_obj):
    """Detect total pages in the current grid."""
    try:
        # Check for pagination text like "Page 1 of 5" or just find max page link
        pagination_text = page_obj.locator(".pagination-info, .grid-pagination").inner_text()
        match = re.search(r"of\s+(\d+)", pagination_text)
        if match:
            return int(match.group(1))
        
        # Fallback: check manual page buttons
        page_buttons = page_obj.locator("a[onclick*='gotoPage']").all()
        max_page = 1
        for btn in page_buttons:
            btn_text = btn.inner_text().strip()
            if btn_text.isdigit():
                max_page = max(max_page, int(btn_text))
        return max_page
    except:
        return 1

def navigate_to_page(page_obj, page_num):
    """Navigate to a specific page of the grid."""
    if page_num == 1:
        return True
    
    try:
        page_btn = page_obj.locator(f"a[onclick*='gotoPage({page_num})']").or_(
            page_obj.locator(f"a:has-text('{page_num}')")
        )
        if page_btn.count() > 0:
            page_btn.first.click()
            page_obj.wait_for_timeout(2000)
            wait_for_grid(page_obj)
            return True
    except:
        pass
    return False
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
def extract_file_metadata(page_obj, row_locator, filename):
    """Extract metadata from file info dialog using the provided row locator."""
    metadata = {}
    
    try:
        print(f"      Extracting metadata...")
        
        # Strategy 1: Look for info button inside the row
        info_anchor = row_locator.locator("a[onclick*='showRecordIndexingView']")
        
        if info_anchor.count() == 0:
            print(f"      [Warning] Info button not found in row for {filename}")
            return None # Return None instead of {}
        
        # Click the first matching info button
        print(f"      [DEBUG] Clicking info button...")
        info_anchor.first.click()
        page_obj.wait_for_timeout(3000)
        
        # Wait for the metadata panel to appear
        panel = page_obj.locator("#indexingDiv2")
        if panel.count() == 0 or not panel.is_visible():
            print(f"      [Warning] Metadata panel did not appear")
            return None # Return None instead of {}
        
        print(f"      Metadata panel opened successfully")
        
        # Dynamic Extraction: All inputs and selects in the panel
        try:
            # Mapping of friendly names (if we can find them via labels) or IDs
            # For VMR, we'll try to get the 'id' of the elements
            inputs = page_obj.locator("#indexingDiv2 input, #indexingDiv2 select").all()
            
            for element in inputs:
                try:
                    element_id = element.get_attribute("id")
                    if not element_id or element_id in ["property_save", "property_cancel"]:
                        continue
                    
                    tag_name = element.evaluate("el => el.tagName")
                    
                    if tag_name == "SELECT":
                        # Get selected text if possible, else value
                        try:
                            value = element.evaluate("el => el.options[el.selectedIndex].text")
                            if value == "Select":
                                value = ""
                        except:
                            value = element.evaluate("el => el.value")
                    else:
                        value = element.input_value()
                    
                    if value and value.strip():
                        # Map IDs back to a readable name if possible, else just use the ID
                        friendly_name = element_id.replace("vmr_", "").replace("_", " ").title()
                        metadata[friendly_name] = value.strip()
                        
                        # Special Case: Track the exact ID for the manifest v2
                        metadata[f"_id_{element_id}"] = value.strip()
                    else:
                        # Return explicit None (Null) for empty fields
                        friendly_name = element_id.replace("vmr_", "").replace("_", " ").title()
                        metadata[friendly_name] = None
                        metadata[f"_id_{element_id}"] = None
                except:
                    continue
        except Exception as e:
            print(f"      [Debug] Dynamic metadata extraction failed: {e}")
            
        print(f"      Extracted {len(metadata)} metadata fields (dynamic)")
        
        # DEBUG: Print each field and its type
        for key, value in metadata.items():
            print(f"        {key}: {type(value).__name__} = {value}")
        
        # Close the metadata panel
        try:
            cancel_btn = page_obj.locator("#property_cancel")
            if cancel_btn.count() > 0 and cancel_btn.is_visible():
                cancel_btn.click()
                page_obj.wait_for_timeout(1000)
                print(f"      Metadata panel closed")
        except:
            # Fallback: try JavaScript
            try:
                page_obj.evaluate("handleRightContainerAction(true, false)")
                page_obj.wait_for_timeout(1000)
            except:
                pass
        
    except Exception as e:
        print(f"      [Warning] Metadata extraction failed: {e}")
        # Try to close panel
        try:
            page_obj.locator("#property_cancel").click()
            page_obj.wait_for_timeout(500)
        except:
            pass
        return None # Return None on exception
    
    return metadata if metadata else None # Return None if nothing extracted
# -----------------------------
# DOWNLOAD FUNCTIONS
# -----------------------------
def download_file_with_metadata(page_obj, filename, occurrence, directory_path, folder_rel_path):
    """Download a single file and its metadata, handling remote duplicates."""
    # 1. Determine local path uniquely
    file_path = get_unique_local_path(directory_path, filename)
    safe_filename = os.path.basename(file_path)
    
    if safe_filename != filename:
        print(f"    Target: {filename} (Index: {occurrence}) -> Local: {safe_filename}")
    else:
        print(f"    Downloading: {filename} (Index: {occurrence})")
    
    try:
        # Find file row - using index (occurrence) for identical names
        row = None
        
        # Strategy 1: nth locator for the specific occurrence
        rows = page_obj.locator("tr").filter(has_text=filename)
        if rows.count() > occurrence:
            row = rows.nth(occurrence)
        
        if not row:
            # Strategy 2: Fallback to all spans if row filtering is weird
            spans = page_obj.locator("span.mail-sender").filter(has_text=filename)
            match_index = 0
            for i in range(spans.count()):
                s = spans.nth(i)
                if s.inner_text().strip() == filename:
                    if match_index == occurrence:
                        row = s.locator("xpath=ancestor::tr").first if s.locator("xpath=ancestor::tr").count() > 0 else s.locator("xpath=ancestor::li").first
                        break
                    match_index += 1
        
        if not row:
            print(f"      ✗ File instance {occurrence} not found in grid: {filename}")
            return {
                "filename": filename,
                "occurrence": occurrence,
                "status": "failed",
                "error": "Not found in grid",
                "metadata": None
            }

        # Extract metadata USING THE ROW LOCATOR
        metadata = extract_file_metadata(page_obj, row, filename)
        
        # Select checkbox
        checkbox = row.locator("input[type='checkbox']")
        if checkbox.count() > 0:
            checkbox.first.check()
            page_obj.wait_for_timeout(2000)
        
        # Find and click download button
        dl_btn = page_obj.locator("a#multipleFile_download")
        if dl_btn.count() == 0 or not dl_btn.first.is_visible():
            dl_btn = page_obj.locator("i.fa-download.mutiplefiledownloadiconclr").locator("xpath=ancestor::a")
        
        if dl_btn.count() == 0:
            print(f"      ✗ Download button not found")
            return {
                "filename": filename,
                "occurrence": occurrence,
                "status": "failed",
                "error": "Download button missing",
                "metadata": metadata
            }
        
        # Download file
        try:
            with page_obj.expect_download(timeout=60000) as download_info:
                dl_btn.first.click(force=True)
                page_obj.wait_for_timeout(500)
                ok_btn = page_obj.locator("button[data-bb-handler='confirm'], button.btn-primary:has-text('OK')")
                if ok_btn.count() > 0 and ok_btn.first.is_visible():
                    ok_btn.first.click()
            
            download = download_info.value
            download.save_as(file_path)
            
            # AUTO-EXTRACTION LOGIC: VMR often wraps single files in ZIPs
            if zipfile.is_zipfile(file_path):
                print(f"      [Info] ZIP wrapping detected, extracting...")
                temp_extract_dir = os.path.join(OUTPUT_DIR, "temp_extract_" + str(int(time.time())))
                os.makedirs(temp_extract_dir, exist_ok=True)
                try:
                    with zipfile.ZipFile(file_path, 'r') as zip_ref:
                        zip_ref.extractall(temp_extract_dir)
                    extracted_files = []
                    for root, dirs, files in os.walk(temp_extract_dir):
                        for f in files:
                            extracted_files.append(os.path.join(root, f))
                    if extracted_files:
                        best_match = extracted_files[0]
                        for f in extracted_files:
                            if os.path.basename(f) == filename:
                                best_match = f
                                break
                        os.remove(file_path)
                        shutil.move(best_match, file_path)
                        print(f"      ✓ Extracted: {filename}")
                finally:
                    if os.path.exists(temp_extract_dir):
                        shutil.rmtree(temp_extract_dir)
            else:
                print(f"      ✓ Downloaded: {filename}")
            
        except Exception as e:
            print(f"      ✗ Download failed: {e}")
            return {
                "filename": filename,
                "occurrence": occurrence,
                "status": "failed",
                "error": str(e),
                "metadata": metadata
            }
        
        # Save metadata to disk
        if metadata:
            meta_rel_dir = os.path.dirname(folder_rel_path)
            meta_full_dir = os.path.join(METADATA_DIR, meta_rel_dir)
            os.makedirs(meta_full_dir, exist_ok=True)
            metadata_file = os.path.join(meta_full_dir, filename + ".json")
            with open(metadata_file, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        # Uncheck
        if checkbox.count() > 0:
            checkbox.first.uncheck()
        
        return {
            "filename": filename,
            "path": file_path,
            "metadata": metadata,
            "status": "success"
        }
        
    except Exception as e:
        print(f"      ✗ Error processing {filename}: {e}")
        return {
            "filename": filename,
            "occurrence": occurrence,
            "status": "failed",
            "error": str(e),
            "metadata": None
        }

def download_folder_recursive(page_obj, current_path, output_base, manifest_logger):
    """Recursively download all files in a folder and its subfolders with pagination support."""
    
    # Session recovery check
    ensure_logged_in(page_obj)
    
    path_str = " > ".join(current_path)
    print(f"\n[Processing] {path_str}")
    
    total_pages = get_total_pages(page_obj)
    if total_pages > 1:
        print(f"  [Info] Folder has {total_pages} pages")
    
    relative_parts = current_path[1:]
    local_folder = os.path.join(output_base, *relative_parts)
    os.makedirs(local_folder, exist_ok=True)
    
    # Track which folders we've seen on which pages to process them after files
    all_subfolders = [] # List of (folder_name, page_idx)
    
    for page_idx in range(1, total_pages + 1):
        if total_pages > 1:
            print(f"  [Page {page_idx}/{total_pages}]")
            navigate_to_page(page_obj, page_idx)
            
        # Get items for current page
        folders, files_with_occ = get_grid_items(page_obj)
        
        # Store folders for later recursion
        for f in folders:
            all_subfolders.append((f, page_idx))
            
        # Download all files on this page
        if files_with_occ:
            for filename, occurrence in files_with_occ:
                if filename in ["My Records", "My Activity", "Group or Department"]:
                    continue
                
                # Session recovery check before each download
                ensure_logged_in(page_obj)
                
                # relative_path passed for metadata reconstruction
                relative_path = os.path.join(*relative_parts, filename) if relative_parts else filename
                
                result = download_file_with_metadata(
                    page_obj, 
                    filename, 
                    occurrence, 
                    local_folder, 
                    relative_path
                )
                if result:
                    manifest_logger.log(result)
    
    # Process subfolders (re-navigating to the correct page if necessary)
    if all_subfolders:
        print(f"  Processing {len(all_subfolders)} subfolders...")
        for idx, (folder, page_idx) in enumerate(all_subfolders):
            print(f"\n  [{idx+1}/{len(all_subfolders)}] Entering: {folder} (from page {page_idx})")
            
            try:
                # Ensure we are on the correct page to click the folder
                if total_pages > 1:
                    navigate_to_page(page_obj, page_idx)
                
                # Enter subfolder
                click_folder(page_obj, folder)
                
                # Recurse
                download_folder_recursive(
                    page_obj,
                    current_path + [folder],
                    output_base,
                    manifest_logger
                )
                
                # Navigate back - use back button
                print(f"  Returning to: {path_str}")
                page_obj.go_back(wait_until="domcontentloaded")
                page_obj.wait_for_timeout(2000)
                
                # Verify we're back and on the right page
                if not wait_for_grid(page_obj):
                    print("  [Warning] Grid didn't load after back, resetting...")
                    navigate_to_path(page_obj, current_path)
                    if total_pages > 1:
                        navigate_to_page(page_obj, page_idx)
                else:
                    # If we have multiple pages, we might need to verify we returned to page_idx
                    # (VMR usually returns to the first page on 'back')
                    if total_pages > 1:
                        navigate_to_page(page_obj, page_idx)
                
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
    
    manifest_logger = ManifestLogger(OUTPUT_DIR)
    
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
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
            click_folder(page, "Group or Department_old")
        except Exception as e:
            print(f"✗ Failed to enter root: {e}")
            browser.close()
            return
        
        # Start recursive download
        try:
            download_folder_recursive(
                page,
                ["Group or Department_old"],
                OUTPUT_DIR,
                manifest_logger
            )
        except Exception as e:
            print(f"\n✗ Migration error: {e}")
        finally:
            browser.close()
    
    # Consolidate results from JSONL to final manifest
    results = manifest_logger.get_all_results()
    
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