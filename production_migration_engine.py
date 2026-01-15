import os
import json
import re
import time
from datetime import datetime
from playwright.sync_api import sync_playwright

# -----------------------------
# CONFIGURATION
# -----------------------------
SERVER_URL = "http://localhost:8000/web_ui/index.html"
CONFIG_FILE = "migration-config-full.json"
QUEUE_FILE = "migration_queue.jsonl"
MANIFEST_FILE = "migration_manifest.jsonl"
DEST_ROOT = "final_storage_flattened"
BATCH_SIZE = 50  # Restart browser every 50 files to prevent memory leaks

os.makedirs(DEST_ROOT, exist_ok=True)

# -----------------------------
# HELPERS
# -----------------------------
def load_config():
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

CONFIG = load_config()

def append_jsonl(filepath, data):
    with open(filepath, "a", encoding="utf-8") as f:
        f.write(json.dumps(data) + "\n")

def load_set_from_jsonl(filepath, key_field):
    """Loads a set of unique keys from a JSONL file."""
    if not os.path.exists(filepath):
        return set()
    s = set()
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        entry = json.loads(line)
                        val = entry.get(key_field)
                        if val:
                            s.add(val)
                    except:
                        pass
    except Exception as e:
        print(f"Error loading {filepath}: {e}")
    return s

# -----------------------------
# PHASE 1: DISCOVERY (CRAWL)
# -----------------------------
def run_discovery():
    print("--- PHASE 1: DISCOVERY ---")
    
    # 1. Identify what's already queued
    queued_urls = load_set_from_jsonl(QUEUE_FILE, "source_url")
    print(f"Existing Queue Size: {len(queued_urls)}")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        
        try:
            page.goto(SERVER_URL)
            page.wait_for_load_state("networkidle")
            
            # SIMULATED RECURSIVE CRAWL
            # In production, this would be a loop over pagination / subfolders
            # Logic: Identify ALL links/files and push to Queue
            
            files = page.locator(".file")
            count = files.count()
            print(f"Discovered {count} potential files.")
            
            new_items = 0
            for i in range(count):
                file_container = files.nth(i)
                
                # EXTRACT IDENTIFIERS FOR QUEUE
                # We need enough info to navigate back OR just the metadata if the link is direct
                filename = file_container.locator("span").first.inner_text().strip()
                
                # Assume we can construct a direct or reproducible identifier
                # Ideally, we scrape the direct 'href'
                download_link = file_container.locator("a[download]")
                if download_link.count() == 0:
                    continue
                    
                href = download_link.get_attribute("href")
                # Make absolute if needed
                full_url = f"{SERVER_URL.rsplit('/', 1)[0]}/{href}"
                
                if full_url in queued_urls:
                    continue
                
                # Scrape Breadcrumbs immediately for context
                group = file_container.get_attribute("data-group") or "DefaultGroup"
                dept = file_container.get_attribute("data-department") or "HR"
                status = file_container.get_attribute("data-category") or "Active"
                year = file_container.get_attribute("data-year") or "2023"
                raw_employee = file_container.get_attribute("data-employee") or "UnknownUser"
                
                # Store Job
                job = {
                    "source_url": full_url, # Unique Key
                    "filename": filename,
                    "metadata_context": {
                        "group": group, 
                        "dept": dept, 
                        "status": status, 
                        "year": year, 
                        "raw_employee": raw_employee
                    },
                    "discovery_timestamp": datetime.now().isoformat()
                }
                
                append_jsonl(QUEUE_FILE, job)
                queued_urls.add(full_url)
                new_items += 1
                
            print(f"Added {new_items} new items to Queue.")
            
        finally:
            browser.close()

# -----------------------------
# PHASE 2: EXECUTION (DOWNLOAD)
# -----------------------------
def process_batch(browser, batch_items):
    """Processes a list of queue items in a single browser context."""
    context = browser.new_context()
    page = context.new_page()
    
    for job in batch_items:
        try:
            filename = job["filename"]
            print(f"Processing: {filename}")
            
            # RECONSTRUCT CONTEXT
            meta = job["metadata_context"]
            
            # Logic duplication from previous script (Virtual Path)
            virtual_month = "11_nov" 
            if "(" not in meta["raw_employee"]:
                 virtual_employee_source = f"{meta['raw_employee']} ( 9999 )"
            else:
                 virtual_employee_source = meta["raw_employee"]
            
            web_hierarchy = [
                meta["group"], 
                meta["dept"], 
                meta["status"], 
                meta["year"], 
                virtual_month, 
                virtual_employee_source, 
                "Docs"
            ]
            
            # RESOLVE PATH
            local_path_rel = resolve_target_path(web_hierarchy, filename)
            local_path_abs = os.path.join(DEST_ROOT, local_path_rel)
            
            # DOWNLOAD
            # In a real app, we might need to navigate to 'source_url'
            # But here 'source_url' is the file link (dummy). 
            # If it requires auth, we go to page -> login -> goto link.
            # For this prototype, we'll visit the MAIN PAGE and find the element again?
            # NO, that's inefficient.
            # OPTION A: Direct URL download.
            # OPTION B: Re-navigate (Reliable but slow).
            
            # Let's try Direct URL download if possible.
            # Simulating: We go to the UI to "See" the form, then click download.
            
            # To simulate scraping the FORM, we must visit the page where the file is.
            # We'll treat SERVER_URL as that page.
            page.goto(SERVER_URL) # In prod, this would be specific file details page
            
            # MOCK FORM SCRAPE (Since we are on the list page)
            # Find the element again by filename? (Fragile but works for prototype)
            # Efficient: Use text locator
            file_el = page.locator(f".file:has-text('{filename}')").first
            
            form_data = scrape_form_metadata(file_el)
            
            os.makedirs(os.path.dirname(local_path_abs), exist_ok=True)
            
            # Click Download
            download_btn = file_el.locator("a[download]")
            status = "Unknown"
            
            if download_btn.count() > 0:
                with page.expect_download() as dl_info:
                    download_btn.click()
                download = dl_info.value
                download.save_as(local_path_abs)
                status = "Success"
            else:
                status = "Failed (Link Not Found)"
            
            # LOG MANIFEST
            manifest_entry = {
                "original_filename": filename,
                "local_path": local_path_abs,
                "source_url": job["source_url"],
                "metadata": {
                    "form_fields": form_data,
                    "web_hierarchy": web_hierarchy
                },
                "status": status,
                "processed_at": datetime.now().isoformat()
            }
            append_jsonl(MANIFEST_FILE, manifest_entry)
            
        except Exception as e:
            print(f"Error processing {job['filename']}: {e}")
            # Log failure to manifest so we know
            fail_entry = {"original_filename": job["filename"], "status": f"Failed: {e}"}
            append_jsonl(MANIFEST_FILE, fail_entry)
            
    context.close()

def run_execution():
    print("--- PHASE 2: EXECUTION ---")
    
    # 1. Load what's done
    done_urls = load_set_from_jsonl(MANIFEST_FILE, "source_url")
    print(f"Already Migrated: {len(done_urls)}")
    
    # 2. Load Queue
    queue = []
    if os.path.exists(QUEUE_FILE):
        with open(QUEUE_FILE, "r") as f:
            for line in f:
                if line.strip():
                    queue.append(json.loads(line))
    
    # 3. Filter Todo
    todo = [q for q in queue if q["source_url"] not in done_urls]
    print(f"Pending Items: {len(todo)}")
    
    if not todo:
        print("Nothing to do.")
        return

    # 4. Batch Process with Browser Restart
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        
        for i in range(0, len(todo), BATCH_SIZE):
            batch = todo[i : i + BATCH_SIZE]
            print(f"Starting Batch {i // BATCH_SIZE + 1} (Size: {len(batch)})")
            
            process_batch(browser, batch)
            
            # In a real heavy scenario, we might even restart result 'browser' instance
            # periodically, not just context. But context is usually sufficient.
            
        browser.close()

# -----------------------------
# SHARED LOGIC (COPIED)
# -----------------------------
def resolve_target_path(web_hierarchy, filename):
    # (Same as before)
    context = {}
    level_names = CONFIG.get("hierarchy_levels", [])
    for i, lvl in enumerate(level_names):
        context[lvl] = web_hierarchy[i] if i < len(web_hierarchy) else "Unknown"
    context["FileName"] = filename
    
    # Regex
    rewrites = CONFIG.get("regex_rewrites", {})
    for field, rule in rewrites.items():
        if field in context:
            try:
                context[field] = re.sub(rule["pattern"], rule["replacement"], context[field]).strip()
            except: pass
            
    template = CONFIG.get("path_template", "")
    final_path = template
    for key, val in context.items():
        final_path = final_path.replace(f"{{{{{key}}}}}", str(val))
        
    final_path = final_path.replace(":", "").replace("*", "").replace("?", "")
    return os.path.normpath(final_path)

def scrape_form_metadata(Locator):
    # (Same logic)
    return {"Classification": "Internal", "Simulated": True} 

if __name__ == "__main__":
    # AUTOMATION: Run both phases
    run_discovery()
    run_execution()
