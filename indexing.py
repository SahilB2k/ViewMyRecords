import os
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
import time
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
# 1. Try .env in current directory (Docker/Standard)
load_dotenv()
# 2. Try .env in parent directory (User's local setup)
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

# --- CONFIGURATION ---
CONFIG_FILE = "config.json"
MANIFEST_PATH = "Group or Department_new/manifest_v2_restructured.json"

# Credentials from environment variables
VMR_CORPORATE_ID = os.getenv("VMW_CORPORATE_USERID")
VMR_USERNAME = os.getenv("VRM_USER_NAME")
VMR_PASSWORD = os.getenv("VMR_USER_PASSWORD")

# Timeouts (in milliseconds)
NAVIGATION_TIMEOUT = 30000
GRID_LOAD_TIMEOUT = 15000
METADATA_PANEL_TIMEOUT = 10000
ELEMENT_TIMEOUT = 5000

# Retry Configuration
MAX_RETRIES = 3
RETRY_DELAY = 2000

# --- TRANSLATION MAPS ---
CLASSIFICATION_MAP = {
    "HR - Annual Review": "vmr_HRannualreviewRelated",
    "HR - Current Employment": "vmr_HRcurrentEmploymentRelated",
    "HR - Educational": "vmr_HReducationalRelated",
    "HR - Exit Formalities": "vmr_HRexitRelated",
    "HR - Past Employment": "vmr_HRpastemploymentRelated",
    "HR - Personal / KYC": "vmr_HRpersonalkycRelated",
    "HR - Recruitment": "vmr_HRrecruitmentRelated",
    "HR - Statutory": "vmr_HRstatutoryRelated",
    "HR - Verification": "vmr_HRverificationRelated",
}

CATEGORY_MAP = {
    "Normal": "NORM",
    "Confidential": "CONF",
    "Highly Secure": "HCONF"
}

# Global configuration
CONFIG = {}

# --- LOGGING ---
def log(message, level="INFO"):
    """Enhanced logging with timestamps - only shows important messages"""
    if level in ["SUCCESS", "ERROR", "WARN", "INFO"]:
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] [{level}] {message}")

def progress_bar(current, total, prefix='', suffix='', length=50):
    """Display a progress bar"""
    percent = 100 * (current / float(total))
    filled = int(length * current // total)
    bar = '█' * filled + '░' * (length - filled)
    print(f'\r{prefix} |{bar}| {current}/{total} [{percent:.1f}%] {suffix}', end='', flush=True)
    if current == total:
        print()

# --- CONFIGURATION LOADING ---
def load_config():
    """Load configuration from config.json"""
    global CONFIG
    
    if not os.path.exists(CONFIG_FILE):
        log(f"Config file not found: {CONFIG_FILE}", "ERROR")
        log("Please create config.json with your credentials", "ERROR")
        return False
    
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            CONFIG = json.load(f)
        
        log("✓ Configuration loaded successfully", "SUCCESS")
        return True
        
    except Exception as e:
        log(f"Failed to load config: {e}", "ERROR")
        return False

# --- SESSION MANAGEMENT ---
def handle_session_conflict(page):
    """Handles 'Already logged in' / 'Login Here' popups."""
    try:
        login_here_btn = page.locator("text='Login Here'").or_(
            page.locator("a:has-text('Login Here')")
        )
        if login_here_btn.count() > 0 and login_here_btn.first.is_visible():
            log("Session conflict detected - clicking 'Login Here'", "WARN")
            login_here_btn.first.click()
            page.wait_for_timeout(3000)
            return True
    except:
        pass
    return False

def auto_login(page):
    """Automated login to VMR using environment credentials with session conflict handling"""
    try:
        page.wait_for_timeout(2000)
        
        # Check if already logged in
        if page.locator("#addFolder-link").count() > 0:
            log("Already logged in!", "SUCCESS")
            return True
        
        # Handle session conflict if present
        handle_session_conflict(page)
        
        # Fill Corporate ID
        corp_id_selectors = [
            "input[name='corpName']",
            "input[name='corpId']",
            "input[id='corpId']",
            "input[placeholder*='Corporate']"
        ]
        
        for selector in corp_id_selectors:
            try:
                corp_field = page.locator(selector)
                if corp_field.count() > 0:
                    corp_field.first.fill(VMR_CORPORATE_ID)
                    break
            except:
                continue
        
        # Fill Username
        username_selectors = [
            "input[name='corpEmailID']",
            "input[name='username']",
            "input[name='j_username']",
            "input[id='username']",
            "input[type='text']"
        ]
        
        for selector in username_selectors:
            try:
                username_field = page.locator(selector)
                if username_field.count() > 0:
                    username_field.first.fill(VMR_USERNAME)
                    break
            except:
                continue
        
        # Fill Password
        password_selectors = [
            "input[name='corpPassword']",
            "input[name='password']",
            "input[name='j_password']",
            "input[id='password']",
            "input[type='password']"
        ]
        
        for selector in password_selectors:
            try:
                password_field = page.locator(selector)
                if password_field.count() > 0:
                    password_field.first.fill(VMR_PASSWORD)
                    break
            except:
                continue
        
        page.wait_for_timeout(500)
        
        # Click login button
        login_btn_selectors = [
            "button[type='submit']",
            "input[type='submit']",
            "input[type='image'][src*='login']",
            "button:has-text('Login')",
            "button:has-text('Sign In')",
            "input[value='Login']"
        ]
        
        for selector in login_btn_selectors:
            try:
                login_btn = page.locator(selector)
                if login_btn.count() > 0 and login_btn.first.is_visible():
                    login_btn.first.click()
                    break
            except:
                continue
        
        # Wait for login to complete
        page.wait_for_timeout(3000)
        
        # Handle session conflict after login
        handle_session_conflict(page)
        
        # Wait for dashboard
        try:
            page.wait_for_selector("#addFolder-link", timeout=15000)
            log("✓ Login successful!", "SUCCESS")
            page.wait_for_timeout(2000)
            return True
        except:
            # Check if we're on main page despite timeout
            if "main.do" in page.url:
                log("✓ Login successful!", "SUCCESS")
                page.wait_for_timeout(2000)
                return True
            raise
        
    except Exception as e:
        log(f"Auto-login failed: {e}", "ERROR")
        log("Please check your .env credentials", "ERROR")
        return False

# --- NAVIGATION HELPERS ---
def wait_for_grid_stable(page, timeout=GRID_LOAD_TIMEOUT):
    """Wait for grid to load and stabilize"""
    try:
        page.wait_for_selector("span.mail-sender", timeout=timeout, state="visible")
        page.wait_for_timeout(1000)
        count = page.locator("span.mail-sender").count()
        return count > 0
    except:
        return False

def navigate_to_root(page):
    """Navigate to root folder reliably"""
    for attempt in range(MAX_RETRIES):
        try:
            home_selectors = [
                "a[href='#']",
                ".logo",
                "#home-link",
                "a.brand"
            ]
            
            for selector in home_selectors:
                try:
                    home_link = page.locator(selector).first
                    if home_link.count() > 0:
                        home_link.click()
                        page.wait_for_timeout(2000)
                        break
                except:
                    continue
            
            page.goto(CONFIG.get('base_url', ''), wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT)
            page.wait_for_timeout(2000)
            
            handle_session_conflict(page)
            
            if wait_for_grid_stable(page):
                root_folders = [
                    "My Records", 
                    "Group or Department", 
                    "My Activity", 
                    "Group or Department_new",
                    "Shared Records"
                ]
                
                for folder in root_folders:
                    if page.locator(f"span.mail-sender:has-text('{folder}')").count() > 0:
                        return True
            
            if attempt < MAX_RETRIES - 1:
                page.wait_for_timeout(RETRY_DELAY)
                
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                log(f"Failed to reach root: {e}", "ERROR")
            
    return False

def click_folder_by_name(page, folder_name):
    """Click a folder with multiple fallback strategies"""
    handle_session_conflict(page)
    
    if not wait_for_grid_stable(page):
        return False
    
    # Strategy 1: Exact match using onclick attribute
    try:
        folder_link = page.locator(f"a[onclick*='{folder_name}']")
        if folder_link.count() > 0:
            folder_link.first.click()
            page.wait_for_timeout(2500)
            handle_session_conflict(page)
            
            if wait_for_grid_stable(page):
                return True
    except:
        pass
    
    # Strategy 2: Exact text match
    try:
        spans = page.locator("span.mail-sender").all()
        for span in spans:
            try:
                text = span.inner_text().strip()
                if text == folder_name:
                    parent_link = span.locator("xpath=ancestor::a").first
                    parent_link.click()
                    page.wait_for_timeout(2500)
                    handle_session_conflict(page)
                    
                    if wait_for_grid_stable(page):
                        return True
            except:
                continue
    except:
        pass
    
    # Strategy 3: Partial text match
    try:
        spans = page.locator("span.mail-sender").all()
        for span in spans:
            try:
                text = span.inner_text().strip()
                if folder_name in text or text in folder_name:
                    parent_link = span.locator("xpath=ancestor::a").first
                    parent_link.click()
                    page.wait_for_timeout(2500)
                    handle_session_conflict(page)
                    
                    if wait_for_grid_stable(page):
                        return True
            except:
                continue
    except:
        pass
    
    log(f"✗ Folder not found: '{folder_name}'", "ERROR")
    return False

def navigate_to_path(page, path_list):
    """Navigate through folder path from root"""
    if not path_list:
        return navigate_to_root(page)
    
    for attempt in range(MAX_RETRIES):
        try:
            if not navigate_to_root(page):
                raise Exception("Failed to reach root")
            
            for folder_name in path_list:
                if not click_folder_by_name(page, folder_name):
                    raise Exception(f"Failed at folder: {folder_name}")
                page.wait_for_timeout(1000)
            
            page.wait_for_timeout(2000)
            
            if wait_for_grid_stable(page):
                return True
            
        except Exception as e:
            if attempt == MAX_RETRIES - 1:
                log(f"Navigation failed: {e}", "ERROR")
            if attempt < MAX_RETRIES - 1:
                page.wait_for_timeout(RETRY_DELAY)
    
    return False

# --- FILE OPERATIONS ---
def find_file_by_name(page, filename):
    """Find file in current folder"""
    handle_session_conflict(page)
    wait_for_grid_stable(page)
    
    file_span = page.locator(f"span.mail-sender:text-is('{filename}')")
    
    if file_span.count() == 0:
        file_span = page.locator(f"span.mail-sender:has-text('{filename}')")
    
    if file_span.count() > 0:
        return file_span.first
    
    log(f"✗ File not found: '{filename}'", "ERROR")
    return None

def open_file_metadata_panel(page, filename):
    """Open metadata panel for a file"""
    file_span = find_file_by_name(page, filename)
    if not file_span:
        return False
    
    try:
        parent_li = file_span.locator("xpath=ancestor::li").first
        
        info_btn = None
        
        selectors = [
            "a[onclick*='showRecordIndexingView']",
            "a[title='Index File']",
            "a[title*='Index']",
            "i.fa-info",
            "li.pdli a"
        ]
        
        for selector in selectors:
            try:
                btn = parent_li.locator(selector).first
                if btn.count() > 0:
                    info_btn = btn
                    
                    if selector == "i.fa-info":
                        info_btn = btn.locator("xpath=ancestor::a").first
                    
                    break
            except:
                continue
        
        if not info_btn:
            log("Info button not found", "ERROR")
            return False
        
        info_btn.click()
        page.wait_for_timeout(2000)
        
        try:
            page.wait_for_selector("#rightContainer", timeout=METADATA_PANEL_TIMEOUT, state="visible")
            page.wait_for_timeout(1000)
            page.wait_for_selector("#fileContentType", timeout=ELEMENT_TIMEOUT, state="visible")
            return True
        except Exception as e:
            log(f"Metadata panel did not appear: {e}", "ERROR")
            return False
            
    except Exception as e:
        log(f"Failed to open panel: {e}", "ERROR")
        return False

def close_metadata_panel(page):
    """Close metadata panel"""
    try:
        cancel_btn = page.locator("#property_cancel")
        if cancel_btn.count() > 0 and cancel_btn.is_visible():
            cancel_btn.click()
            page.wait_for_timeout(1000)
            return True
    except:
        pass
    
    try:
        page.evaluate("handleRightContainerAction(true, false)")
        page.wait_for_timeout(500)
        return True
    except:
        pass
    
    return False

def fill_metadata(page, metadata, filename):
    """Fill metadata fields from manifest"""
    changes = 0
    
    try:
        # 1. Classification
        classification = metadata.get("Classification")
        if classification and classification in CLASSIFICATION_MAP:
            tech_class = CLASSIFICATION_MAP[classification]
            try:
                page.select_option("#fileContentType", value=tech_class)
                page.wait_for_timeout(1500)
                changes += 1
            except:
                pass
        
        # 2. Document Sub Type
        doc_subtype = metadata.get("Document Sub Type") or metadata.get("Document SubType Internal")
        if doc_subtype:
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
                try:
                    if page.locator(dropdown_id).is_visible(timeout=1000):
                        page.select_option(dropdown_id, value=doc_subtype)
                        changes += 1
                        break
                except:
                    continue
        
        # 3. Simple text fields
        text_fields = {
            "Quick Reference": "#vmr_quickref",
            "Document Date": "#vmr_docdate",
            "Expiry Date": "#vmr_expirydate",
            "Offsite Location": "#vmr_geotag",
            "On-Premises Location": "#vmr_offpremise",
            "Remarks": "#vmr_remarks",
            "Keywords": "#vmr_keywords",
            "Document Type": "#vmr_doctype"
        }
        
        for field_name, selector in text_fields.items():
            value = metadata.get(field_name, "")
            if value:
                try:
                    page.fill(selector, str(value))
                    changes += 1
                except:
                    pass
        
        # 4. Lifespan
        lifespan = metadata.get("Lifespan")
        if lifespan:
            try:
                page.select_option("#vmr_doclifespan", value=str(lifespan))
                changes += 1
            except:
                pass
        
        # 5. Category
        category = metadata.get("Category")
        if category and category in CATEGORY_MAP:
            try:
                cat_value = CATEGORY_MAP[category]
                page.select_option("#vmr_category", value=cat_value)
                changes += 1
            except:
                pass
        
        # SAVE
        if changes > 0:
            save_btn = page.locator("#property_save")
            
            if save_btn.is_visible():
                save_btn.click()
                page.wait_for_timeout(2000)
                
                try:
                    ok_btn = page.locator("button[data-bb-handler='confirm'], button:has-text('OK')")
                    if ok_btn.is_visible(timeout=3000):
                        ok_btn.click()
                        page.wait_for_timeout(1000)
                except:
                    pass
                
                # Validation: Wait for panel to disappear
                try:
                    page.wait_for_selector("#rightContainer", state="hidden", timeout=10000)
                    return True
                except:
                    # If panel still exists, try to find an error message
                    error_selectors = [
                        ".bootbox-body",                # Common for popups
                        ".alert-danger",                # Bootstrap style
                        ".error-text",                  # General
                        "#property_error_msg",          # Specific ID
                        "span[style*='color: red']",    # Inline style errors
                        "div[class*='error']"           # Class-based errors
                    ]
                    
                    error_found = "Unknown error - Panel did not close"
                    for selector in error_selectors:
                        try:
                            msg_element = page.locator(selector).first
                            if msg_element.is_visible(timeout=500):
                                error_found = msg_element.inner_text().strip()
                                break
                        except:
                            continue
                    
                    log(f"✗ Save failed for '{filename}': {error_found}", "ERROR")
                    return False
            else:
                log(f"✗ Save button not visible for '{filename}'", "ERROR")
                return False
        else:
            # No changes to save, consider it a success as the state is already correct
            return True
        
    except Exception as e:
        log(f"Error filling metadata: {e}", "ERROR")
        return False

# --- MAIN PROCESSING ---
def process_single_file(page, filename, metadata, path_list):
    """Process a single file - navigate, find, and update metadata"""
    # Defensive check: ensure metadata is always a dictionary
    if metadata is None:
        metadata = {}
        
    try:
        if not navigate_to_path(page, path_list):
            return False
        
        if not find_file_by_name(page, filename):
            return False
        
        if not open_file_metadata_panel(page, filename):
            return False
        
        success = fill_metadata(page, metadata, filename)
        
        close_metadata_panel(page)
        
        page.wait_for_timeout(1000)
        return success
        
    except Exception as e:
        log(f"Unexpected error: {e}", "ERROR")
        close_metadata_panel(page)
        return False

def split_manifest_path(path):
    """Split manifest path into folders and filename"""
    p = Path(path)
    parts = list(p.parts)
    
    technical_folders = [
        'vmr_downloads', 
        'restructured_output', 
        'vmr_test'
    ]
    
    if parts and parts[0] in technical_folders:
        parts = parts[1:]
    
    folders = parts[:-1]
    filename = parts[-1] if parts else ""
    
    return folders, filename

# --- MAIN FUNCTION ---
def migrate_vmr():
    """Main migration function"""
    print("\n" + "="*70)
    print("VMR METADATA MIGRATION - AUTOMATED PROCESSING")
    print("="*70 + "\n")
    
    # Load configuration
    if not load_config():
        return
    
    # Verify environment credentials
    if not VMR_CORPORATE_ID or not VMR_USERNAME or not VMR_PASSWORD:
        log("Environment credentials not found in .env file", "ERROR")
        log("Please ensure .env file contains:", "ERROR")
        log("  VMW_CORPORATE_USERID=your_corporate_id", "ERROR")
        log("  VRM_USER_NAME=your_username", "ERROR")
        log("  VMR_USER_PASSWORD=your_password", "ERROR")
        return
    
    log(f"Using credentials from .env file", "INFO")
    log(f"Corporate ID: {VMR_CORPORATE_ID}", "INFO")
    log(f"Username: {VMR_USERNAME}", "INFO")
    
    # Load manifest
    log(f"Loading manifest: {MANIFEST_PATH}", "INFO")
    
    if not os.path.exists(MANIFEST_PATH):
        log(f"Manifest not found: {MANIFEST_PATH}", "ERROR")
        return
    
    with open(MANIFEST_PATH, 'r', encoding='utf-8') as f:
        manifest = json.load(f)
    
    files = manifest.get('files', [])
    log(f"Loaded {len(files)} files from manifest\n", "INFO")
    
    if not files:
        log("No files in manifest", "ERROR")
        return
    
    # Launch browser
    with sync_playwright() as p:
        log("Launching browser...", "INFO")
        
        browser = p.chromium.launch(
            headless=True,
            slow_mo=50
        )
        
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        
        page = context.new_page()
        
        # Navigate and login
        base_url = CONFIG.get('base_url')
        log(f"Navigating to: {base_url}", "INFO")
        page.goto(base_url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT)
        page.wait_for_timeout(2000)
        
        # Login with automated credentials
        if not auto_login(page):
            log("Login failed - please check your .env credentials", "ERROR")
            browser.close()
            return
        
        # Verify at root
        if not navigate_to_root(page):
            log("Could not reach root", "ERROR")
            browser.close()
            return
        
        # Process files
        print("\n" + "="*70)
        print("PROCESSING FILES")
        print("="*70 + "\n")
        
        success_count = 0
        fail_count = 0
        skip_count = 0
        
        for idx, entry in enumerate(files, start=1):
            filename = entry.get('filename')
            metadata = entry.get('metadata', {}) or {}
            manifest_path = entry.get('new_path') or entry.get('path') or entry.get('old_path')
            
            # Update progress bar
            progress_bar(idx, len(files), prefix='Progress:', suffix=f'Processing: {filename[:40]}...', length=40)
            
            if not filename or not metadata:
                skip_count += 1
                continue
            
            # Parse path
            folders, fname = split_manifest_path(manifest_path)
            
            # Process file
            if process_single_file(page, fname, metadata, folders):
                success_count += 1
            else:
                fail_count += 1
                log(f"✗ Failed: {filename}", "ERROR")
            
            page.wait_for_timeout(500)
        
        # Summary
        print("\n" + "="*70)
        print("MIGRATION COMPLETE")
        print("="*70)
        print(f"Total files: {len(files)}")
        print(f"✓ Success: {success_count}")
        print(f"✗ Failed: {fail_count}")
        print(f"⊘ Skipped: {skip_count}")
        if len(files) > 0:
            print(f"Success rate: {(success_count/len(files)*100):.1f}%")
        print("="*70 + "\n")
        
        log("Browser will remain open for review", "INFO")
        log("Press Ctrl+C to close and exit", "INFO")
        
        try:
            page.wait_for_timeout(300000)
        except KeyboardInterrupt:
            log("Closing browser...", "INFO")
        
        browser.close()

if __name__ == "__main__":
    migrate_vmr()