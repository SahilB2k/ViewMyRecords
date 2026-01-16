import os
import json
import re
import time
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# -----------------------------
# CREDENTIALS & CONFIG
# -----------------------------
VMR_CORPORATE_ID = os.getenv("VMR_CORPORATE_ID", "tvsm_hr")
VMR_USERNAME = os.getenv("VMR_USERNAME", "tvshr_sahil")
VMR_PASSWORD = os.getenv("VMR_PASSWORD", "Sahil@12")

CONFIG_FILE = "config.json"
QUEUE_FILE = "migration_queue.jsonl"
MANIFEST_FILE = "migration_manifest.jsonl"
VISITED_FOLDERS_FILE = "visited_folders.jsonl"
BATCH_SIZE = 50

# Retry Configuration
MAX_RETRIES = 3
RETRY_DELAY = 2000  # ms
NAVIGATION_TIMEOUT = 20000  # ms
ELEMENT_TIMEOUT = 15000  # ms

# -----------------------------
# SETUP
# -----------------------------
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    # Default config if file doesn't exist
    return {
        "base_url": "https://your-vmr-url.com/login.do"
    }

CONFIG = load_config()

def append_jsonl(filepath, data):
    """Append to JSONL file."""
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")

def load_visited_folders():
    """Loads all visited folder paths from persistent log."""
    visited = set()
    
    if not os.path.exists(VISITED_FOLDERS_FILE):
        return visited
    
    try:
        with open(VISITED_FOLDERS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        entry = json.loads(line)
                        path = entry.get("path")
                        if path:
                            visited.add(tuple(path))
                    except:
                        pass
    except:
        pass
    
    return visited

def mark_folder_visited(path_list):
    """Records a folder path as visited in persistent storage."""
    append_jsonl(VISITED_FOLDERS_FILE, {
        "path": list(path_list),
        "timestamp": datetime.now().isoformat()
    })

def load_existing_jobs():
    """Load all existing jobs with full path as key."""
    jobs = {}
    
    if not os.path.exists(QUEUE_FILE):
        return jobs
    
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        entry = json.loads(line)
                        hierarchy = entry.get("hierarchy_raw", [])
                        job_key = tuple(hierarchy)
                        jobs[job_key] = entry
                    except:
                        pass
    except:
        pass
    
    return jobs

def load_downloaded_files():
    """Load set of successfully downloaded files."""
    downloaded = set()
    
    if not os.path.exists(MANIFEST_FILE):
        return downloaded
    
    try:
        with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        entry = json.loads(line)
                        if entry.get("status") == "Success":
                            hierarchy = entry.get("hierarchy_raw")
                            if hierarchy:
                                downloaded.add(tuple(hierarchy))
                            else:
                                downloaded.add(entry.get("filename"))
                    except:
                        pass
    except:
        pass
    
    return downloaded

# -----------------------------
# AUTHENTICATION & INTERSTITIALS
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
            try:
                page_obj.wait_for_selector("span.mail-sender", timeout=10000)
            except:
                pass
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
                    print("✓ Login successful (on main.do)!")
                    return True
                
        except Exception as e:
            print(f"  Login attempt {attempt + 1} failed: {e}")
            if attempt < MAX_RETRIES - 1:
                page_obj.wait_for_timeout(RETRY_DELAY)
            
    print("✗ Login failed after all retries")
    return False

# -----------------------------
# PATH RESOLUTION
# -----------------------------
def resolve_vmr_path(web_hierarchy, filename):
    """Path rules: Skip 'Internal Use', regex cleanup, flatten Month+Employee"""
    levels = []
    for raw in web_hierarchy:
        clean = re.sub(r'\s+', ' ', raw).strip()
        if clean == "Internal Use":
            continue
        
        clean = re.sub(r'(.*?)\s*\(\s*(\d+)\s*\)', r'\1_\2', clean)
        clean = re.sub(r'[<>:"/\\|?*]', '_', clean).replace(' ', '_')
        levels.append(clean)
    
    if len(levels) >= 3:
        employee = levels.pop()
        month = levels.pop()
        flattened = f"{month}_{employee}"
        levels.append(flattened)
    
    final_path = os.path.join(*levels, filename)
    return os.path.normpath(final_path)

# -----------------------------
# SPA NAVIGATION HELPERS
# -----------------------------
def wait_for_grid(page_obj, timeout=10000):
    """Waits for the VMR grid to load."""
    try:
        page_obj.locator("span.mail-sender").first.wait_for(state="visible", timeout=timeout)
        page_obj.wait_for_timeout(800)
        return True
    except:
        print("  [Warning] Grid didn't load in time")
        return False

def click_folder(page_obj, folder_name, timeout=ELEMENT_TIMEOUT):
    """Clicks a folder in the SPA."""
    if handle_session_conflict(page_obj):
        page_obj.wait_for_timeout(2000)
    
    folder_locator = page_obj.locator("span.mail-sender").filter(has_text=folder_name)
    if folder_locator.count() == 0:
        folder_locator = page_obj.locator(f"span.mail-sender:has-text('{folder_name}')")
    if folder_locator.count() == 0:
        folder_locator = page_obj.get_by_text(folder_name, exact=False)
    
    if folder_locator.count() == 0:
        raise Exception(f"Folder not found: {folder_name}")
    
    folder_locator.first.click(timeout=timeout)
    page_obj.wait_for_load_state("domcontentloaded")
    page_obj.wait_for_timeout(1200)
    return True

def navigate_up_one_level(page_obj):
    """Navigate back using breadcrumbs or back button."""
    try:
        breadcrumbs = page_obj.locator("a.breadcrumb, .breadcrumb a, div.breadcrumb span").all()
        if len(breadcrumbs) >= 2:
            print("  [SPA Nav] Using breadcrumb to go up")
            breadcrumbs[-2].click()
            page_obj.wait_for_timeout(1000)
            return True
    except Exception as e:
        print(f"  Breadcrumb navigation failed: {e}")
    
    try:
        up_folder = page_obj.locator("span.mail-sender").filter(has_text=re.compile(r"^\.\.$|^Up$|^Parent", re.I))
        if up_folder.count() > 0:
            print("  [SPA Nav] Using '..' folder to go up")
            up_folder.first.click()
            page_obj.wait_for_timeout(1000)
            return True
    except Exception as e:
        print(f"  '..' folder navigation failed: {e}")
    
    try:
        print("  [SPA Nav] Using browser back button")
        page_obj.go_back(wait_until="domcontentloaded")
        page_obj.wait_for_timeout(1500)
        return True
    except Exception as e:
        print(f"  Back button failed: {e}")
    
    return False

def navigate_to_root_spa(page_obj):
    """Navigate to root without breaking SPA state."""
    print("  [SPA Nav] Returning to root...")
    
    try:
        breadcrumbs = page_obj.locator("a.breadcrumb, .breadcrumb a").all()
        if breadcrumbs:
            breadcrumbs[0].click()
            page_obj.wait_for_timeout(1500)
            return True
    except:
        pass
    
    try:
        for _ in range(10):
            if page_obj.locator("span.mail-sender").filter(has_text="Group or Department").count() > 0:
                print("  [SPA Nav] Found root!")
                return True
            page_obj.go_back(wait_until="domcontentloaded")
            page_obj.wait_for_timeout(800)
    except:
        pass
    
    return False

def reset_to_path_spa(page_obj, path_list):
    """SPA-AWARE RESET: Navigate to target path."""
    print(f"[SPA Reset] Target: {' > '.join(path_list)}")
    
    for attempt in range(MAX_RETRIES):
        try:
            if not navigate_to_root_spa(page_obj):
                print("  [Warning] Couldn't navigate to root via SPA, trying hard reset...")
                page_obj.goto(CONFIG.get("base_url"), wait_until="domcontentloaded", timeout=30000)
                page_obj.wait_for_timeout(3000)
                handle_session_conflict(page_obj)
            
            if not wait_for_grid(page_obj, timeout=10000):
                raise Exception("Grid didn't load at root")
            
            for idx, folder_name in enumerate(path_list):
                print(f"  [{idx + 1}/{len(path_list)}] Entering: {folder_name}")
                handle_session_conflict(page_obj)
                
                if not wait_for_grid(page_obj):
                    raise Exception(f"Grid didn't load before entering: {folder_name}")
                
                click_folder(page_obj, folder_name)
            
            print("  ✓ SPA Reset successful")
            return True
            
        except Exception as e:
            print(f"    SPA Reset attempt {attempt + 1} failed: {e}")
            if attempt < MAX_RETRIES - 1:
                page_obj.wait_for_timeout(RETRY_DELAY)
    
    print("  ✗ SPA Reset failed after all retries")
    return False

# -----------------------------
# DISCOVERY (PHASE 1) - COMPLETE CRAWL
# -----------------------------
def crawl_recursive(page_obj, current_path_names, existing_jobs, visited_paths, max_depth=10):
    """
    FIXED: Recursively crawls ALL folders at each level.
    """
    if len(current_path_names) > max_depth:
        print(f"  [Max Depth] Skipping: {' > '.join(current_path_names)}")
        return
    
    current_path_tuple = tuple(current_path_names)
    if current_path_tuple in visited_paths:
        print(f"  [Already Crawled] Skipping: {' > '.join(current_path_names)}")
        return
    
    print(f"\n[Crawling] {' > '.join(current_path_names)}")
    
    handle_session_conflict(page_obj)
    
    if not wait_for_grid(page_obj):
        print("  [Error] Grid failed to load, skipping this branch")
        return
    
    # CRITICAL FIX: Snapshot ALL items BEFORE any navigation
    all_spans = page_obj.locator("span.mail-sender").all()
    folder_names = []
    file_names = []
    
    for span in all_spans:
        try:
            txt = span.inner_text().strip()
            if not txt or txt in ["..", "Up", "Parent Folder"]:
                continue
            
            parent = span.locator("xpath=..")
            onclick = parent.get_attribute("onclick") or ""
            
            if "getFolderandFileList" in onclick:
                folder_names.append(txt)
            else:
                file_names.append(txt)
        except:
            continue
    
    print(f"  Found: {len(folder_names)} folders, {len(file_names)} files")
    
    # Queue all files
    files_queued = 0
    for fname in file_names:
        if fname in ["My Records", "My Activity", "Group or Department"]:
            continue
        
        job_key = tuple(current_path_names + [fname])
        
        if job_key in existing_jobs:
            continue
        
        job = {
            "source_url": page_obj.url,
            "filename": fname,
            "hierarchy_raw": list(current_path_names) + [fname],
            "discovery_timestamp": datetime.now().isoformat()
        }
        append_jsonl(QUEUE_FILE, job)
        existing_jobs[job_key] = job
        files_queued += 1
        print(f"    + Queued: {fname}")
    
    if files_queued > 0:
        print(f"  ✓ Queued {files_queued} new files")
    
    # CRITICAL FIX: Process ALL folders in the snapshot
    print(f"  [Subfolders] Will process {len(folder_names)} folders: {folder_names}")
    
    for idx, folder in enumerate(folder_names):
        target_path = list(current_path_names) + [folder]
        target_path_tuple = tuple(target_path)
        
        if target_path_tuple in visited_paths:
            print(f"  [{idx+1}/{len(folder_names)}] Already crawled: {folder}")
            continue
        
        print(f"\n  [{idx+1}/{len(folder_names)}] ===== ENTERING SUBFOLDER: {folder} =====")
        
        # Navigate to this subfolder
        enter_success = False
        for attempt in range(MAX_RETRIES):
            try:
                # CRITICAL: Always start from current level before entering subfolder
                if attempt > 0:
                    print(f"    Retry {attempt}: Resetting to current path first...")
                    if not reset_to_path_spa(page_obj, current_path_names):
                        raise Exception("Failed to reset to current path")
                
                click_folder(page_obj, folder)
                enter_success = True
                break
            except Exception as e:
                print(f"    Attempt {attempt + 1} to enter '{folder}' failed: {e}")
                if attempt < MAX_RETRIES - 1:
                    page_obj.wait_for_timeout(RETRY_DELAY)
        
        if not enter_success:
            print(f"    [Error] Failed to enter '{folder}' after {MAX_RETRIES} attempts, skipping")
            # CRITICAL: Reset to current level before trying next sibling
            reset_to_path_spa(page_obj, current_path_names)
            continue
        
        # Recurse into subfolder
        crawl_recursive(page_obj, target_path, existing_jobs, visited_paths, max_depth)
        
        # CRITICAL: Always navigate back to CURRENT level after each subfolder
        print(f"  [Exit] Returning from '{folder}' to: {' > '.join(current_path_names)}")
        
        # STRATEGY 1: Try simple back navigation first
        nav_success = navigate_up_one_level(page_obj)
        
        # STRATEGY 2: If back failed, do full reset to current level
        if not nav_success:
            print(f"    [Warning] Simple nav failed, doing full reset to current level")
            nav_success = reset_to_path_spa(page_obj, current_path_names)
        
        # STRATEGY 3: If still failed, verify we're at the right place
        if not nav_success:
            print(f"    [Critical] All navigation failed after '{folder}'")
            # Last resort: try to continue anyway, grid might still be correct
        else:
            # Verify grid loaded at current level
            if not wait_for_grid(page_obj):
                print(f"    [Warning] Grid didn't load after returning, resetting...")
                reset_to_path_spa(page_obj, current_path_names)
        
        page_obj.wait_for_timeout(800)
        
        print(f"  [{idx+1}/{len(folder_names)}] ===== COMPLETED: {folder} =====\n")
    
    # Mark current folder as fully crawled
    print(f"  [Folder Complete] Finished all branches of: {' > '.join(current_path_names)}")
    mark_folder_visited(current_path_names)
    visited_paths.add(current_path_tuple)

def run_discovery():
    """Phase 1: Discover ALL files in VMR recursively."""
    print("=" * 60)
    print("PHASE 1: DISCOVERY (COMPLETE RECURSIVE CRAWL)")
    print("=" * 60)
    
    print("\nLoading existing progress...")
    
    visited_paths = load_visited_folders()
    existing_jobs = load_existing_jobs()
    
    print(f"✓ Loaded {len(existing_jobs)} existing jobs")
    print(f"✓ Loaded {len(visited_paths)} visited folder paths")
    
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = context.new_page()
        
        if not login_to_vmr(page):
            print("✗ Login failed, aborting discovery")
            browser.close()
            return
        
        print("\nEntering root folder...")
        if not wait_for_grid(page):
            print("✗ Grid didn't load, aborting")
            browser.close()
            return
        
        try:
            click_folder(page, "Group or Department")
        except Exception as e:
            print(f"✗ Failed to enter root: {e}")
            browser.close()
            return
        
        crawl_recursive(page, ["Group or Department"], existing_jobs, visited_paths)
        
        browser.close()
    
    print("\n" + "=" * 60)
    print(f"✓ DISCOVERY COMPLETE")
    print(f"  Total files queued: {len(existing_jobs)}")
    print(f"  Total folders crawled: {len(visited_paths)}")
    print("=" * 60)

# -----------------------------
# EXECUTION (PHASE 2) - FIXED DOWNLOAD
# -----------------------------
def download_file(page_obj, job):
    """Downloads a single file with FIXED download button handling."""
    filename = job['filename']
    hierarchy = job.get("hierarchy_raw", [])[:-1]
    
    print(f"\n[Downloading] {filename}")
    print(f"  Path: {' > '.join(hierarchy)}")
    
    if not reset_to_path_spa(page_obj, hierarchy):
        raise Exception("Failed to navigate to target folder")
    
    if not wait_for_grid(page_obj):
        raise Exception("Grid didn't load")
    
    # Find file row
    row = page_obj.locator("tr").filter(has_text=filename)
    if row.count() == 0:
        row = page_obj.locator("tr").filter(has_text=re.compile(re.escape(filename[:20]), re.I))
    if row.count() == 0:
        span = page_obj.locator("span.mail-sender").filter(has_text=filename)
        if span.count() > 0:
            row = span.first.locator("xpath=ancestor::tr")
    if row.count() == 0:
        raise Exception(f"File row not found: {filename}")
    
    row = row.first
    
    # CRITICAL FIX: Select checkbox and WAIT for toolbar to enable
    print("  Selecting file...")
    checkbox = row.locator("input[type='checkbox']")
    if checkbox.count() > 0:
        checkbox.first.check()
        # WAIT for download button to become enabled
        page_obj.wait_for_timeout(2000)  # Increased wait
        print("  ✓ File selected")
    
    # Extract metadata (optional)
    metadata = {}
    try:
        info_btn = row.locator("a[onclick*='viewDocumentDetails'], img[src*='info'], a[title*='info' i], i.fa-info")
        if info_btn.count() > 0:
            info_btn.first.click()
            page_obj.wait_for_timeout(2000)
            
            labels = page_obj.locator("label, .prop-label, td.label").all()
            for label_elem in labels:
                try:
                    label_text = label_elem.inner_text().strip(': ')
                    value_elem = label_elem.locator("xpath=following-sibling::*[1]")
                    if value_elem.count() > 0:
                        value_text = value_elem.inner_text().strip()
                        metadata[label_text] = value_text
                except:
                    pass
            
            page_obj.keyboard.press("Escape")
            page_obj.wait_for_timeout(500)
    except Exception as e:
        print(f"  [Warning] Metadata extraction failed: {e}")
    
    # Resolve local path
    local_path = resolve_vmr_path(hierarchy, filename)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    
    # CRITICAL FIX: Better download button detection
    print("  Looking for download button...")
    
    # Strategy 1: Direct ID selector
    dl_btn = page_obj.locator("a#multipleFile_download")
    
    # Strategy 2: Find enabled download icon
    if dl_btn.count() == 0 or not dl_btn.first.is_visible():
        dl_btn = page_obj.locator("i.fa-download.mutiplefiledownloadiconclr").locator("xpath=ancestor::a")
    
    # Strategy 3: Any download link with icon
    if dl_btn.count() == 0:
        dl_btn = page_obj.locator("a[onclick*='downloadMultipleFiles'], a[title*='Download']")
    
    if dl_btn.count() == 0:
        raise Exception("Download button not found after selection")
    
    # Verify button is visible and enabled
    try:
        dl_btn.first.wait_for(state="visible", timeout=5000)
        print(f"  ✓ Download button found and visible")
    except:
        print(f"  [Warning] Download button may not be visible, trying anyway...")
    
    # DOWNLOAD
    print("  Initiating download...")
    try:
        with page_obj.expect_download(timeout=60000) as download_info:
            # Click with force to bypass any overlay issues
            dl_btn.first.click(force=True, timeout=10000)
            page_obj.wait_for_timeout(1000)
        
        download = download_info.value
        download.save_as(local_path)
        print(f"  ✓ Saved to: {local_path}")
        
    except Exception as e:
        print(f"  [Error] Download failed: {e}")
        # Try fallback: just click and wait
        dl_btn.first.click(force=True)
        page_obj.wait_for_timeout(5000)
        
        if not os.path.exists(local_path):
            raise Exception(f"Download failed: {e}")
    
    # Save metadata
    if metadata:
        metadata_path = local_path + ".json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
    
    return {
        "filename": filename,
        "hierarchy_raw": job.get("hierarchy_raw"),
        "local_path": local_path,
        "status": "Success",
        "metadata_extracted": len(metadata) > 0,
        "timestamp": datetime.now().isoformat()
    }

def process_batch(browser, batch_items):
    """Process a batch of downloads."""
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        accept_downloads=True
    )
    page = context.new_page()
    
    if not login_to_vmr(page):
        print("✗ Batch login failed")
        context.close()
        return
    
    for job in batch_items:
        result = None
        for attempt in range(MAX_RETRIES):
            try:
                result = download_file(page, job)
                print(f"  ✓ Success!")
                break
            except Exception as e:
                print(f"  Attempt {attempt + 1} failed: {e}")
                if attempt < MAX_RETRIES - 1:
                    page.wait_for_timeout(RETRY_DELAY)
                else:
                    result = {
                        "filename": job.get('filename'),
                        "hierarchy_raw": job.get('hierarchy_raw'),
                        "status": f"Failed: {str(e)}",
                        "timestamp": datetime.now().isoformat()
                    }
        
        if result:
            append_jsonl(MANIFEST_FILE, result)
    
    context.close()

def run_execution():
    """Phase 2: Download all queued files."""
    print("\n" + "=" * 60)
    print("PHASE 2: EXECUTION")
    print("=" * 60)
    
    downloaded_set = load_downloaded_files()
    existing_jobs = load_existing_jobs()
    
    todo = []
    for job_key, job in existing_jobs.items():
        if job_key not in downloaded_set:
            todo.append(job)
    
    print(f"\nTotal queued: {len(existing_jobs)}")
    print(f"Already downloaded: {len(downloaded_set)}")
    print(f"Remaining: {len(todo)}")
    
    if not todo:
        print("\n✓ All files already downloaded!")
        return
    
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        
        for i in range(0, len(todo), BATCH_SIZE):
            batch = todo[i:i + BATCH_SIZE]
            batch_num = i // BATCH_SIZE + 1
            total_batches = (len(todo) + BATCH_SIZE - 1) // BATCH_SIZE
            
            print(f"\n{'='*60}")
            print(f"[Batch {batch_num}/{total_batches}] Processing {len(batch)} files...")
            print('='*60)
            process_batch(browser, batch)
        
        browser.close()
    
    print("\n" + "=" * 60)
    print("✓ EXECUTION COMPLETE")
    print("=" * 60)

# -----------------------------
# MAIN
# -----------------------------
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("VMR MIGRATION TOOL - FIXED VERSION")
    print("Complete Traversal + Fixed Download")
    print("=" * 60)
    
    run_discovery()
    run_execution()
    
    print("\n✓ Migration complete!")
    print(f"  Queue: {QUEUE_FILE}")
    print(f"  Manifest: {MANIFEST_FILE}")
    print(f"  Visited Log: {VISITED_FOLDERS_FILE}")