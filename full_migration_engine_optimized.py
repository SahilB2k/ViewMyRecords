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
MANIFEST_FILE = "migration_manifest.jsonl" # CHANGED to .jsonl
DEST_ROOT = "final_storage_flattened"

os.makedirs(DEST_ROOT, exist_ok=True)

# -----------------------------
# GLOBAL STATE (FOR RESUMABILITY)
# -----------------------------
MIGRATED_FILES = set()

# -----------------------------
# LOAD CONFIG & STATE
# -----------------------------
def load_config():
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def load_migration_state():
    """Reads the existing manifest to build a set of already processed files."""
    if not os.path.exists(MANIFEST_FILE):
        return set()
    
    migrated = set()
    print("Loading migration state from manifest...")
    try:
        with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        entry = json.loads(line)
                        # tracking by original filename for simplicity in this prototype
                        # in prod, use a unique ID or full source path
                        if entry.get("status") == "Success":
                            migrated.add(entry.get("original_filename"))
                    except:
                        pass
    except Exception as e:
        print(f"Error loading state: {e}")
    
    print(f"Resuming: {len(migrated)} files already migrated.")
    return migrated

CONFIG = load_config()
MIGRATED_FILES = load_migration_state()

# -----------------------------
# PATH RESOLVER
# -----------------------------
def resolve_target_path(web_hierarchy, filename):
    context = {}
    level_names = CONFIG.get("hierarchy_levels", [])
    
    for i, level_name in enumerate(level_names):
        if i < len(web_hierarchy):
            context[level_name] = web_hierarchy[i]
        else:
            context[level_name] = "Unknown"

    context["FileName"] = filename

    rewrites = CONFIG.get("regex_rewrites", {})
    for field, rule in rewrites.items():
        if field in context:
            original_val = context[field]
            pattern = rule["pattern"]
            replacement = rule["replacement"]
            try:
                new_val = re.sub(pattern, replacement, original_val)
                context[field] = new_val.strip()
            except Exception as e:
                print(f"Regex error for {field}: {e}")

    template = CONFIG.get("path_template", "")
    final_path = template
    for key, val in context.items():
        placeholder = f"{{{{{key}}}}}"
        # Only replace if the key exists in our context
        final_path = final_path.replace(placeholder, str(val))
    
    final_path = final_path.replace(":", "").replace("*", "").replace("?", "").replace('"', "").replace("<", "").replace(">", "").replace("|", "")
    
    return os.path.normpath(final_path)

# -----------------------------
# FORM SCRAPER (SIMULATOR)
# -----------------------------
def scrape_form_metadata(page):
    metadata = {}
    fields_to_extract = CONFIG.get("form_fields_to_extract", [])
    
    try:
        metadata["Classification"] = "Internal"
        metadata["Document Date"] = datetime.now().strftime("%Y-%m-%d")
        metadata["Lifespan"] = "10 Years"
        
        desc_el = page.locator(".description").first
        if desc_el.count() > 0:
            metadata["Remarks"] = desc_el.inner_text()
        else:
            metadata["Remarks"] = "No remarks"

        for f in fields_to_extract:
            if f not in metadata:
                metadata[f] = "N/A"
                
    except Exception as e:
        print(f"Form scraping error: {e}")
        return {"error": str(e)}
        
    return metadata

# -----------------------------
# AUDIT LOGGING (OPTIMIZED)
# -----------------------------
def log_manifest(entry):
    """Appends a single line to the JSONL file (O(1) operation)."""
    with open(MANIFEST_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

# -----------------------------
# RECURSIVE ENGINE
# -----------------------------
def run_full_migration():
    print("Starting Optimized Full Migration Engine...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        # Optimization: In a long run, restart context every N files to free memory
        context = browser.new_context()
        page = context.new_page()
        
        try:
            page.goto(SERVER_URL)
            page.wait_for_load_state("networkidle")
            
            files = page.locator(".file")
            count = files.count()
            print(f"Found {count} files discovered by crawler.")
            
            for i in range(count):
                file_container = files.nth(i)
                filename = file_container.locator("span").first.inner_text().strip()
                
                # RESUMABILITY CHECK
                if filename in MIGRATED_FILES:
                    print(f"Skipping {filename} (Already Migrated)")
                    continue
                
                # Existing Logic...
                group = file_container.get_attribute("data-group") or "DefaultGroup"
                dept = file_container.get_attribute("data-department") or "HR"
                status = file_container.get_attribute("data-category") or "Active"
                year = file_container.get_attribute("data-year") or "2023"
                
                virtual_month = "11_nov" 
                raw_employee = file_container.get_attribute("data-employee") or "UnknownUser"
                if "(" not in raw_employee:
                     virtual_employee_source = f"{raw_employee} ( 9999 )"
                else:
                     virtual_employee_source = raw_employee

                virtual_subfolder = "Docs"
                web_hierarchy = [group, dept, status, year, virtual_month, virtual_employee_source, virtual_subfolder]
                
                print(f"\nProcessing: {filename}")
                
                form_data = scrape_form_metadata(file_container)
                
                local_path_rel = resolve_target_path(web_hierarchy, filename)
                local_path_abs = os.path.join(DEST_ROOT, local_path_rel)
                
                os.makedirs(os.path.dirname(local_path_abs), exist_ok=True)
                
                download_btn = file_container.locator("a[download]")
                status = "Unknown"
                if download_btn.count() > 0:
                    try:
                        with page.expect_download() as dl_info:
                            download_btn.click()
                        download = dl_info.value
                        download.save_as(local_path_abs)
                        status = "Success"
                    except Exception as e:
                        status = f"Failed: {e}"
                        print(f"  Download Error: {e}")
                else:
                    status = "Skipped (No Link)"
                
                # Update Manifest & In-Memory State
                manifest_entry = {
                    "original_filename": filename,
                    "local_path": local_path_abs,
                    "metadata": {
                        "web_hierarchy_raw": web_hierarchy,
                        "form_fields": form_data,
                        "audit": {
                            "timestamp": datetime.now().isoformat()
                        }
                    },
                    "status": status
                }
                log_manifest(manifest_entry)
                
                if status == "Success":
                    MIGRATED_FILES.add(filename)
        
        except Exception as e:
            print(f"Global Error: {e}")
            import traceback
            traceback.print_exc()
            
        finally:
            browser.close()
            print(f"\nOptimized Migration Batch Complete. Manifest: {MANIFEST_FILE}")

if __name__ == "__main__":
    run_full_migration()
