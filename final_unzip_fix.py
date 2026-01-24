import os
import shutil
import zipfile

ROOT_DIR = "Group or Department_old"

def clean_zip_wrapper(file_path):
    temp_dir = file_path + "_fix_extract"
    try:
        # Check signature manually to be sure
        is_zip = False
        with open(file_path, 'rb') as f:
            if f.read(4) == b'PK\x03\x04':
                is_zip = True
        
        if not is_zip:
            return

        print(f"[Fixing] Found ZIP wrapper: {file_path}")
        os.makedirs(temp_dir, exist_ok=True)
        
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        
        extracted_files = []
        for r, d, f in os.walk(temp_dir):
            for file in f:
                extracted_files.append(os.path.join(r, file))
        
        if not extracted_files:
            print(f"[Warn] Empty ZIP, skipping: {file_path}")
            return

        # Selection logic:
        # 1. Prefer same filename
        # 2. Prefer .pdf
        # 3. Take largest file
        
        target_name = os.path.basename(file_path)
        best_candidate = extracted_files[0]
        
        exact_match = next((f for f in extracted_files if os.path.basename(f) == target_name), None)
        pdf_match = next((f for f in extracted_files if f.endswith('.pdf')), None)
        
        if exact_match:
            best_candidate = exact_match
        elif pdf_match:
            best_candidate = pdf_match
        
        print(f"  -> Replacing with: {os.path.basename(best_candidate)}")
        
        # Overwrite original
        # Remove original file first (it is open? no)
        os.remove(file_path)
        shutil.move(best_candidate, file_path)
        
    except Exception as e:
        print(f"[Error] Failed to fix {file_path}: {e}")
    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

def scan_and_fix():
    for root, dirs, files in os.walk(ROOT_DIR):
        for file in files:
            if file.endswith(".json"): continue
            file_path = os.path.join(root, file)
            clean_zip_wrapper(file_path)

if __name__ == "__main__":
    scan_and_fix()
    print("Final Unzip Pass Complete.")
