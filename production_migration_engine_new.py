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
# Load environment variables
# 1. Try .env in current directory (Docker/Standard)
load_dotenv()
# 2. Try .env in parent directory (User's local setup)
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

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
def extract_file_metadata(page_obj, filename):
    """Extract metadata from file info dialog by finding the file in the grid."""
    metadata = {}
    
    try:
        print(f"      Extracting metadata...")
        
        # Find the file by filename in the grid
        file_span = page_obj.locator("span.mail-sender").filter(has_text=filename)
        
        if file_span.count() == 0:
            print(f"      [Warning] Could not locate file in grid: {filename}")
            return metadata
        
        # Try multiple strategies to find the parent container with the info button
        info_anchor = None
        
        # Strategy 1: Look for parent li with class 'pdli '
        parent_li = file_span.first.locator("xpath=ancestor::li[@class='pdli ']")
        if parent_li.count() > 0:
            info_anchor = parent_li.locator("a[onclick*='showRecordIndexingView']")
        
        # Strategy 2: Look for parent li without specific class
        if not info_anchor or info_anchor.count() == 0:
            parent_li = file_span.first.locator("xpath=ancestor::li")
            if parent_li.count() > 0:
                info_anchor = parent_li.first.locator("a[onclick*='showRecordIndexingView']")
        
        # Strategy 3: Look in parent tr (table row)
        if not info_anchor or info_anchor.count() == 0:
            parent_tr = file_span.first.locator("xpath=ancestor::tr")
            if parent_tr.count() > 0:
                info_anchor = parent_tr.first.locator("a[onclick*='showRecordIndexingView']")
        
        # Strategy 4: Search nearby in the DOM
        if not info_anchor or info_anchor.count() == 0:
            # Look for any info button in the same row/container
            info_anchor = page_obj.locator("a[onclick*='showRecordIndexingView']").filter(has_text="")
        
        if not info_anchor or info_anchor.count() == 0:
            print(f"      [Warning] Info button not found for file")
            return metadata
        
        # Click the first matching info button
        print(f"      [DEBUG] Clicking info button...")
        info_anchor.first.click()
        page_obj.wait_for_timeout(3000)
        
        # Wait for the metadata panel to appear
        panel = page_obj.locator("#indexingDiv2")
        if panel.count() == 0 or not panel.is_visible():
            print(f"      [Warning] Metadata panel did not appear")
            return metadata
        
        print(f"      Metadata panel opened successfully")
        
        # Extract Classification
        try:
            selected_option = page_obj.locator("#fileContentType option[selected]")
            if selected_option.count() == 0:
                # Try to get the currently selected value
                selected_value = page_obj.locator("#fileContentType").evaluate("el => el.value")
                if selected_value and selected_value != "select":
                    selected_text = page_obj.locator(f"#fileContentType option[value='{selected_value}']").inner_text()
                    metadata["Classification"] = selected_text
            else:
                classification = selected_option.inner_text()
                if classification != "Select":
                    metadata["Classification"] = classification
        except Exception as e:
            print(f"      [Debug] Classification extraction failed: {e}")
        
        # Extract Document Sub Type - try multiple dropdown IDs
        try:
            dropdown_ids = [
                "#vmr_hrrecruitmentdropdown",
                "#vmr_hrannualreviewdropdown", 
                "#vmr_hrcurrentemploymentdropdown",
                "#vmr_hreducationaldropdown",
                "#vmr_hrexitdropdown",
                "#vmr_hrpastemploymentdropdown",
                "#vmr_hrpersonalkycdropdown",
                "#vmr_hrstatutorydropdown",
                "#vmr_hrverificationdropdown"
            ]
            
            for dropdown_id in dropdown_ids:
                if page_obj.locator(dropdown_id).count() > 0:
                    selected_val = page_obj.locator(dropdown_id).evaluate("el => el.value")
                    if selected_val:
                        metadata["Document Sub Type"] = selected_val
                        break
        except Exception as e:
            print(f"      [Debug] Document Sub Type extraction failed: {e}")
        
        # Extract input field values
        field_mappings = {
            "Quick Reference": "#vmr_quickref",
            "Document Date": "#vmr_docdate",
            "Expiry Date": "#vmr_expirydate",
            "Offsite Location": "#vmr_geotag",
            "On-Premises Location": "#vmr_offpremise",
            "Remarks": "#vmr_remarks",
            "Keywords": "#vmr_keywords",
            "Document Type": "#vmr_doctype",
            "Document SubType Internal": "#vmr_docsubtype"
        }
        
        for field_name, selector in field_mappings.items():
            try:
                if page_obj.locator(selector).count() > 0:
                    value = page_obj.locator(selector).input_value()
                    if value and value.strip():
                        metadata[field_name] = value.strip()
            except Exception as e:
                print(f"      [Debug] {field_name} extraction failed: {e}")
        
        # Extract Lifespan
        try:
            if page_obj.locator("#vmr_doclifespan").count() > 0:
                lifespan_value = page_obj.locator("#vmr_doclifespan").evaluate("el => el.value")
                if lifespan_value and lifespan_value != "0":
                    metadata["Lifespan"] = lifespan_value
        except Exception as e:
            print(f"      [Debug] Lifespan extraction failed: {e}")
        
        # Extract Category
        try:
            if page_obj.locator("#vmr_category").count() > 0:
                category_value = page_obj.locator("#vmr_category").evaluate("el => el.value")
                if category_value:
                    # Get the text of the selected option
                    category_text = page_obj.locator(f"#vmr_category option[value='{category_value}']").inner_text()
                    metadata["Category"] = category_text
        except Exception as e:
            print(f"      [Debug] Category extraction failed: {e}")
        
        print(f"      Extracted {len(metadata)} metadata fields")
        
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
    
    return metadata
# -----------------------------
# DOWNLOAD FUNCTIONS
# -----------------------------
def download_file_with_metadata(page_obj, filename, file_path, folder_path):
    """Download a single file and its metadata."""
    print(f"    Downloading: {filename}")
    
    try:

        metadata = extract_file_metadata(page_obj, filename)

        # SAFETY CHECK: Remove any Locator objects that might have snuck in
        clean_metadata = {}
        for key, value in metadata.items():
            if str(type(value).__name__) == "Locator":
                print(f"      [WARNING] Removing Locator object from key: {key}")
                continue
            clean_metadata[key] = value
        metadata = clean_metadata
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
                page_obj.wait_for_timeout(500)
                
                # Click OK button in the download confirmation modal
                ok_btn = page_obj.locator("button[data-bb-handler='confirm'], button.btn-primary:has-text('OK')")
                if ok_btn.count() > 0 and ok_btn.first.is_visible():
                    ok_btn.first.click()
                    page_obj.wait_for_timeout(500)
            
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
                    
                    # Find the most likely correct file in the extracted contents
                    # Look for exact match first, then same extension, then just any file
                    extracted_files = []
                    for root, dirs, files in os.walk(temp_extract_dir):
                        for f in files:
                            extracted_files.append(os.path.join(root, f))
                    
                    if extracted_files:
                        # Find best match
                        best_match = extracted_files[0]
                        for f in extracted_files:
                            if os.path.basename(f) == filename:
                                best_match = f
                                break
                        
                        # Replace the ZIP with the actual file
                        os.remove(file_path)
                        shutil.move(best_match, file_path)
                        print(f"      ✓ Extracted and saved: {filename}")
                    else:
                        print(f"      ✗ ZIP was empty!?")
                        
                finally:
                    # Clean up temp directory
                    if os.path.exists(temp_extract_dir):
                        shutil.rmtree(temp_extract_dir)
            else:
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