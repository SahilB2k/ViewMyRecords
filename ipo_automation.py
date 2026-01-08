import os
import time
import random
from datetime import datetime
from playwright.sync_api import sync_playwright

# --- STEP 1: THE SQUASHED BRAIN (3 Levels) ---
def generate_ipo_path(base_dir, journal_no_raw, pub_date_raw, part_name):
    """
    Squashes metadata into 3 levels: Year_Month -> Journal_ID -> Part_Folder.
    Ensures zero metadata loss by combining Year and Month.
    """
    # Extract raw data from strings
    journal_id, year = journal_no_raw.split("/")
    
    # LEVEL 1: Combined Metadata (e.g., "2025_December")
    date_obj = datetime.strptime(pub_date_raw, "%d/%m/%Y")
    year_month = date_obj.strftime("%Y_%B") 
    
    # LEVEL 2: Unique Identifier (e.g., "Journal_48")
    journal_folder = f"Journal_{journal_id}"
    
    # LEVEL 3: Category / Section (e.g., "Part_I")
    part_folder = part_name.strip().replace(" ", "_")
    
    # Build the squashed path
    return os.path.join(base_dir, year_month, journal_folder, part_folder)

# --- STEP 2: THE AUTOMATION ENGINE ---
def run_automation():
    with sync_playwright() as p:
        # Launch browser with a human-like signature
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        # Increased timeout for slow government servers
        page.set_default_timeout(90000)

        print("Opening IPO Journal website...")
        try:
            # Navigate using 'load' state for stability
            page.goto("https://search.ipindia.gov.in/IPOJournal/Journal/Patent", wait_until="load")
            page.wait_for_selector("table", state="visible", timeout=60000)
            print("Page and Table loaded successfully.")
        except Exception as e:
            print(f"Initial load failed: {e}")
            browser.close()
            return

        # Scrape all rows
        rows = page.locator("table tbody tr").all()
        print(f"Total rows found: {len(rows)}")

        # Process the first 5 rows for this run
        for i, row in enumerate(rows[:5]):
            cells = row.locator("td")
            
            try:
                # Extract Text Metadata
                journal_no = cells.nth(1).inner_text().strip()      
                pub_date = cells.nth(2).inner_text().strip()        
                print(f"\n--- Row {i+1}: Journal {journal_no} ---")
                
                # Locate links in the Download column
                download_cell = cells.nth(4)
                pdf_links = download_cell.get_by_text("Part").all()
                print(f"Found {len(pdf_links)} PDF parts.")

                for link in pdf_links:
                    part_name = link.inner_text().strip()
                    if not part_name: continue
                    
                    # Generate the 3-level path
                    target_path = generate_ipo_path("final_storage", journal_no, pub_date, part_name)
                    os.makedirs(target_path, exist_ok=True)
                    
                    # Handle the Popup (New Tab)
                    try:
                        print(f"  -> Opening {part_name}...")
                        with page.context.expect_page() as popup_info:
                            link.click()
                        
                        pdf_page = popup_info.value
                        pdf_page.wait_for_load_state("load")
                        
                        # Save the PDF file into the squashed hierarchy
                        save_name = f"{part_name.replace(' ', '_')}.pdf"
                        final_file_path = os.path.join(target_path, save_name)
                        
                        pdf_page.pdf(path=final_file_path) 
                        print(f"     Successfully saved: {final_file_path}")
                        
                        pdf_page.close() # Maintain browser speed

                    except Exception as download_err:
                        print(f"     Error saving {part_name}: {download_err}")

                # --- HUMAN MODE DELAY ---
                if i < 4: # Don't wait after the very last row
                    wait_time = random.uniform(4, 8)
                    print(f"\n[Human Mode] Waiting {wait_time:.2f} seconds before next row...")
                    time.sleep(wait_time)

            except Exception as row_err:
                print(f"Skipping row {i+1} due to error: {row_err}")

        print("\nSUCCESS: All files processed in 3-level hierarchy.")
        browser.close()

if __name__ == "__main__":
    run_automation()