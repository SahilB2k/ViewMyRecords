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
MANIFEST_FILE = "migration_manifest.json"
DEST_ROOT = "final_storage_flattened"

os.makedirs(DEST_ROOT, exist_ok=True)

# -----------------------------
# LOAD CONFIG
# -----------------------------
def load_config():
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

CONFIG = load_config()

# -----------------------------
# PATH RESOLVER
# -----------------------------
def resolve_target_path(web_hierarchy, filename):
    """
    Transforms the web hierarchy list into a local flattened path.
    1. Skips 'Month' level.
    2. Renames Employee 'Name (ID)' -> 'Name_ID'.
    3. Uses path template.
    """
    
    # Context builder
    context = {}
    
    # 1. Flatten into context
    # Expected Web Hierarchy: [Group, Dept, Status, Year, Month, Employee, SubFolder...]
    # We map them to the keys in 'hierarchy_levels' if possible
    level_names = CONFIG.get("hierarchy_levels", [])
    
    # Safe mapping of values
    for i, level_name in enumerate(level_names):
        if i < len(web_hierarchy):
            context[level_name] = web_hierarchy[i]
        else:
            context[level_name] = "Unknown"

    context["FileName"] = filename

    # 2. Apply Skip Logic (folders_to_skip)
    # We don't remove them from 'context' so much as we ensure the template
    # doesn't use them, OR we can zero them out if the template uses dynamic loops.
    # But here we rely on the template NOT having {{Month}}.
    # Wait, the user manual says: "Explicitly skip/delete the 'Month' level"
    # The config path_template is: "myRecords/{{Group}}/{{Department}}/{{Status}}/{{Year}}/{{Employee}}/{{SubFolder}}/{{FileName}}"
    # It does NOT include {{Month}}, so it is effectively skipped by omission in template.
    
    # 3. Regex Rewrites (Employee Name)
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

    # 4. Interpolate Template
    template = CONFIG.get("path_template", "")
    final_path = template
    for key, val in context.items():
        placeholder = f"{{{{{key}}}}}"
        final_path = final_path.replace(placeholder, str(val))
    
    # Sanitize
    final_path = final_path.replace(":", "").replace("*", "").replace("?", "").replace('"', "").replace("<", "").replace(">", "").replace("|", "")
    
    return os.path.normpath(final_path)

# -----------------------------
# FORM SCRAPER (SIMULATOR)
# -----------------------------
def scrape_form_metadata(page):
    """
    Simulates clicking 'Details' and scraping form fields.
    In a real app, this would navigate to the details page.
    Here we mock it or extract from what's available.
    """
    metadata = {}
    fields_to_extract = CONFIG.get("form_fields_to_extract", [])
    
    # For the PROTOTYPE, we will scrape the metadata div we added earlier
    # and map it to these fields to demonstrate the 'extraction' logic.
    # In a real scenario, we would do:
    # page.click("#btn-details")
    # page.wait_for_selector(".form-details")
    # for field in fields_to_extract: ...
    
    try:
        # Pseudo-extraction from the dummy UI's metadata block
        # We'll just generate dummy values for fields not on the UI to show structure
        metadata["Classification"] = "Internal"
        metadata["Document Date"] = datetime.now().strftime("%Y-%m-%d")
        metadata["Lifespan"] = "10 Years"
        
        # Try to get real values if they exist (simulate form scraping)
        desc_el = page.locator(".description").first
        if desc_el.count() > 0:
            metadata["Remarks"] = desc_el.inner_text()
        else:
            metadata["Remarks"] = "No remarks"

        # Fill rest with placeholder
        for f in fields_to_extract:
            if f not in metadata:
                metadata[f] = "N/A"
                
    except Exception as e:
        print(f"Form scraping error: {e}")
        return {"error": str(e)}
        
    return metadata

# -----------------------------
# AUDIT LOGGING
# -----------------------------
def log_manifest(entry):
    data = []
    if os.path.exists(MANIFEST_FILE):
        try:
            with open(MANIFEST_FILE, "r") as f:
                data = json.load(f)
        except:
             data = []
    data.append(entry)
    with open(MANIFEST_FILE, "w") as f:
        json.dump(data, f, indent=4)

# -----------------------------
# RECURSIVE ENGINE
# -----------------------------
def run_full_migration():
    print("Starting Full Migration Engine...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        
        try:
            page.goto(SERVER_URL)
            page.wait_for_load_state("networkidle")
            
            # Since the dummy UI is flat, we simulate the "Virtual Recursive Crawl"
            # by parsing the breadcrumb data attributes we added to index.html.
            # In a real app, we would: for link in page.locator("a.folder"): link.click()... recursive(page)
            
            files = page.locator(".file")
            count = files.count()
            print(f"Found {count} files to process recursively.")
            
            for i in range(count):
                file_container = files.nth(i)
                filename = file_container.locator("span").first.inner_text().strip()
                
                # 1. BUILD VIRTUAL PATH from Breadcrumbs (Data Attributes)
                # Simulating the crawl depth: Group > Dept > Category > Year > Employee
                # Note: 'Category' in UI maps to 'Status' in our thinking, but let's see configs.
                # Config has [Group, Department, Status, Year, Month, Employee, SubFolder]
                
                group = file_container.get_attribute("data-group") or "DefaultGroup"
                dept = file_container.get_attribute("data-department") or "HR"
                status = file_container.get_attribute("data-category") or "Active"
                year = file_container.get_attribute("data-year") or "2023"
                
                # Simulate Month & Employee (ID) which might be missing in simple UI
                # We inject a dummy month to test the "Skipping" logic
                virtual_month = "11_nov" 
                
                # We inject an Employee with ID to test "Regex Renaming"
                # If UI has "Alice Smith", we transform it to "Alice Smith ( 12345 )" to test the regex
                raw_employee = file_container.get_attribute("data-employee") or "UnknownUser"
                if "(" not in raw_employee:
                     # Simulate the source format "Name (ID)"
                     virtual_employee_source = f"{raw_employee} ( 9999 )"
                else:
                     virtual_employee_source = raw_employee

                virtual_subfolder = "Docs"
                
                # The Full Web Hierarchy as discovered by the "Crawler"
                web_hierarchy = [group, dept, status, year, virtual_month, virtual_employee_source, virtual_subfolder]
                
                print(f"\n[{i+1}/{count}] Found: {filename}")
                print(f"  Web Path: {web_hierarchy}")
                
                # 2. FORM METADATA EXTRACTION
                # Simulate opening details
                form_data = scrape_form_metadata(file_container)
                print(f"  Form Data: {json.dumps(form_data)[:60]}...")
                
                # 3. RESOLVE TARGET PATH
                local_path_rel = resolve_target_path(web_hierarchy, filename)
                local_path_abs = os.path.join(DEST_ROOT, local_path_rel)
                
                print(f"  Resolved: {local_path_abs}")
                
                # 4. DOWNLOAD & SAVE
                # Create folders
                os.makedirs(os.path.dirname(local_path_abs), exist_ok=True)
                
                download_btn = file_container.locator("a[download]")
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
                
                # 5. MANIFEST LOG
                manifest_entry = {
                    "original_filename": filename,
                    "local_path": local_path_abs,
                    "metadata": {
                        "web_hierarchy_raw": web_hierarchy,
                        "form_fields": form_data,
                        "audit": {
                            "original_month_skipped": virtual_month,
                            "download_timestamp": datetime.now().isoformat(),
                            "source_url": page.url
                        }
                    },
                    "status": status
                }
                log_manifest(manifest_entry)
        
        except Exception as e:
            print(f"Global Error: {e}")
            import traceback
            traceback.print_exc()
            
        finally:
            browser.close()
            print(f"\nFull Migration Complete. check {MANIFEST_FILE}")

if __name__ == "__main__":
    run_full_migration()
