import os
import shutil
import zipfile

ROOT_DIR = "Group or Department_old"

def extract_zip(file_path):
    try:
        temp_dir = file_path + "_temp_extract"
        os.makedirs(temp_dir, exist_ok=True)
        
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
        
        # Find files in extract dir
        extracted_files = []
        for r, d, f in os.walk(temp_dir):
            for file in f:
                extracted_files.append(os.path.join(r, file))
        
        if not extracted_files:
            print(f"[Warn] Empty ZIP: {file_path}")
            shutil.rmtree(temp_dir)
            return

        # Move extracted files to parent dir
        parent_dir = os.path.dirname(file_path)
        for f in extracted_files:
            dest_name = os.path.basename(f)
            dest = os.path.join(parent_dir, dest_name)
            shutil.move(f, dest)
            print(f"[Extracted] {dest_name}")
        
        # Remove original ZIP
        os.remove(file_path)
        shutil.rmtree(temp_dir)
        
    except zipfile.BadZipFile:
        print(f"[Skip] Not a valid ZIP: {file_path}")
    except Exception as e:
        print(f"[Error] Failed to extract {file_path}: {e}")

def fix_nesting():
    # Move Group or Department_old/Group or Department_old/* to Group or Department_old/*
    nested_root = os.path.join(ROOT_DIR, "Group or Department_old")
    if os.path.exists(nested_root):
        print(f"[Info] Found nested root: {nested_root}")
        for item in os.listdir(nested_root):
            src = os.path.join(nested_root, item)
            dst = os.path.join(ROOT_DIR, item)
            if os.path.exists(dst):
                print(f"[Warn] Destination exists, merging: {dst}")
                # Simple merge logic for directories?
                # For now just move and overwrite files
                if os.path.isdir(src):
                    # Recursive merge needed if dst is dir? 
                    # Assuming dst might be empty or partial.
                    # shutil.move(src, dst) might fail if dst exists.
                    pass 
            
            try:
                shutil.move(src, dst)
                print(f"[Moved] {item} -> root")
            except Exception as e:
                print(f"[Error] Moving {item}: {e}")
        
        try:
            os.rmdir(nested_root)
            print("[Info] Removed empty nested folder")
        except:
            print("[Warn] Could not remove nested folder (not empty?)")

def scan_and_fix_zips():
    for root, dirs, files in os.walk(ROOT_DIR):
        for file in files:
            file_path = os.path.join(root, file)
            # Check if it's a zip disguising as something else
            if zipfile.is_zipfile(file_path):
                print(f"[Found ZIP] {file_path}")
                extract_zip(file_path)

if __name__ == "__main__":
    print("Starting Cleanup...")
    fix_nesting()
    print("Fixing ZIPs...")
    scan_and_fix_zips()
    print("Cleanup Complete.")
