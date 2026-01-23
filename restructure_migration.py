import os
import json
import re
import shutil
import csv

def restructure_migration():
    """Restructure the migrated data into a cleaner business hierarchy."""
    
    # Load config
    config_path = "config.json"
    if not os.path.exists(config_path):
        print(f"[Error] Config file not found: {config_path}")
        return
        
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
        
    rules = config.get("restructuring", {})
    source_manifest_path = rules.get("source_manifest", "Group or Department/migration_manifest.json")
    # Physical root folder on disk that actually contains the HR tree.
    # By default we infer it from the folder that holds the manifest (e.g. "Group or Department").
    source_root = os.path.dirname(source_manifest_path)
    target_root = rules.get("target_root", "Group or Department_new")
    folders_to_skip = rules.get("folders_to_skip", [])
    skip_regex = rules.get("skip_regex", "")
    dry_run = rules.get("dry_run", True)
    
    if not os.path.exists(source_manifest_path):
        print(f"[Error] Source manifest not found: {source_manifest_path}")
        return
        
    with open(source_manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
        
    print("=" * 70)
    print("VMR DATA RESTRUCTURING TOOL")
    if dry_run:
        print("[MODE: DRY RUN - No files will be moved]")
    print("=" * 70)
    
    restructured_files = []
    
    for entry in manifest.get("files", []):
        filename = entry["filename"]
        old_path = entry["path"]
        metadata = entry["metadata"]
        
        # Determine relative path starting at the business root ("HR")
        # Manifest path example:
        #   vmr_downloads\HR\Live Employee\1997\11_Nov\E SAHILJADHAV(12345)\Internal Use\MAVROS (1).pdf
        # Actual disk path example:
        #   Group or Department\HR\Live Employee\1997\11_Nov\E SAHILJADHAV(12345)\Internal Use\MAVROS (1).pdf
        # We therefore:
        #   1) Trim everything before "HR"
        #   2) Use that HR-onwards segment both for:
        #        - locating the source file under source_root
        #        - building the new relative structure under target_root
        parts = old_path.split(os.sep)
        try:
            # Find the index of the first folder after the manifest's base directory
            # In this case, we know the structure usually starts with HR
            index = parts.index("HR")
            clean_parts = parts[index:]
        except ValueError:
            print(f"  [Warning] Could not find 'HR' in path: {old_path}")
            continue
            
        # Apply transformation rules
        new_relative_parts = []
        folders_to_skip_lower = [f.lower() for f in folders_to_skip]
        
        for part in clean_parts:
            # Skip file name at the end
            if part == filename:
                continue
                
            # Check if part should be skipped (case-insensitive)
            part_lower = part.lower().strip()
            
            is_skipped = False
            if part_lower in folders_to_skip_lower:
                is_skipped = True
            elif skip_regex and re.match(skip_regex, part):
                is_skipped = True
                
            if not is_skipped:
                new_relative_parts.append(part)
            
        new_relative_path = os.path.join(target_root, *new_relative_parts, filename)
        new_full_path = os.path.join(os.getcwd(), new_relative_path)
        
        print(f"\nProcessing: {filename}")
        print(f"  Old: {old_path}")
        print(f"  New: {new_relative_path}")
        
        if not dry_run:
            # Ensure target directory exists
            os.makedirs(os.path.dirname(new_full_path), exist_ok=True)
            
            # Copy file (using copy2 to preserve timestamps)
            # We intentionally build the source path from:
            #   CWD / source_root / HR\...\filename
            # so that it matches the actual disk layout
            source_full_path = os.path.join(os.getcwd(), source_root, *clean_parts)
            if os.path.exists(source_full_path):
                shutil.copy2(source_full_path, new_full_path)
                print(f"  [Success] Copied successfully")
            else:
                print(f"  [Error] Source file missing: {source_full_path}")
                continue
        
        restructured_files.append({
            "filename": filename,
            "old_path": old_path,
            "new_path": new_relative_path,
            "metadata": metadata
        })
        
    # Generate Indexing Manifest (CSV) for VMR Batch Import
    headers = [
        "File Name", "Classification", "Document Sub Type", "Quick Reference", 
        "Document Date", "Expiry Date", "Offsite Location", "On-Premises Location", 
        "Remarks", "Keywords", "Document Type", "Document SubType Internal", 
        "Lifespan", "Category"
    ]
    
    csv_rows = []
    for entry in restructured_files:
        meta = entry["metadata"]
        row = {
            "File Name": entry["filename"],
            "Classification": meta.get("Classification", ""),
            "Document Sub Type": meta.get("Document Sub Type", ""),
            "Quick Reference": meta.get("Quick Reference", ""),
            "Document Date": meta.get("Document Date", ""),
            "Expiry Date": meta.get("Expiry Date", ""),
            "Offsite Location": meta.get("Offsite Location", ""),
            "On-Premises Location": meta.get("On-Premises Location", ""),
            "Remarks": meta.get("Remarks", ""),
            "Keywords": meta.get("Keywords", ""),
            "Document Type": meta.get("Document Type", ""),
            "Document SubType Internal": meta.get("Document SubType Internal", ""),
            "Lifespan": meta.get("Lifespan", ""),
            "Category": meta.get("Category", "")
        }
        csv_rows.append(row)
        
    csv_path = os.path.join(target_root, "indexing_manifest.csv")
    if not dry_run:
        os.makedirs(target_root, exist_ok=True)
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(csv_rows)
        print(f"\n[Success] Indexing manifest generated: {csv_path}")
    else:
        print(f"\n[Dry Run] Would generate indexing manifest at: {csv_path}")

    # Generate new manifest (JSON)
    new_manifest_v2 = {
        "timestamp": manifest.get("timestamp"),
        "restructured_at": json.dumps(str(os.path.getmtime(config_path))), # just a placeholder for now
        "total_files": len(restructured_files),
        "structure_version": "2.0",
        "files": restructured_files
    }
    
    # Accurate timestamp
    from datetime import datetime
    new_manifest_v2["restructured_at"] = datetime.now().isoformat()
    
    manifest_v2_path = os.path.join(target_root, "manifest_v2_restructured.json")
    if not dry_run:
        with open(manifest_v2_path, "w", encoding="utf-8") as f:
            json.dump(new_manifest_v2, f, indent=2, ensure_ascii=False)
        print(f"\n[Success] Restructuring complete! New manifest saved to: {manifest_v2_path}")
    else:
        print(f"\n[Dry Run] Would save new manifest to: {manifest_v2_path}")

if __name__ == "__main__":
    restructure_migration()