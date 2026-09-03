import json
import os

# ==========================================
# CONFIGURATION
# ==========================================
INPUT_FILE = "data/mods.json"             # Put your downloaded RePoE JSON file here
OUTPUT_FILE = "poe_item_mods_summary.md" # The clean Markdown file to upload

# OPTIONAL FILTER: Keeps file sizes lightweight (<10MB) for the AI notebook.
# Set this to True for mods.json to strip monster/atlas mods and keep only player gear.
ONLY_KEEP_PLAYER_ITEM_MODS = True 
# ==========================================

def clean_key(key):
    """Converts snake_case_labels into Polished Capital Case labels."""
    return " ".join(word.capitalize() for word in key.split("_"))

def format_value(val):
    """Recursively flattens lists, dicts, and None values into clean strings."""
    if isinstance(val, list):
        if not val:
            return "None"
        # If it's a list of dictionaries (like spawn_weights or stats)
        if all(isinstance(item, dict) for item in val):
            formatted_items = []
            for item in val:
                inner_str = ", ".join(f"{k}: {v}" for k, v in item.items())
                formatted_items.append(f"[{inner_str}]")
            return " | ".join(formatted_items)
        return ", ".join(str(x) for x in val)
    
    elif isinstance(val, dict):
        return ", ".join(f"{k}: {v}" for k, v in val.items())
    
    elif val is None or val == "":
        return "None"
    
    return str(val)

def convert_json_to_md():
    if not os.path.exists(INPUT_FILE):
        print(f"Error: Could not find '{INPUT_FILE}' in this directory.")
        return

    print(f"Reading {INPUT_FILE}...")
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    print("Processing and dynamically flattening database...")
    md_lines = []
    
    # Corrected tuple split extraction with 
    title = os.path.splitext(os.path.basename(INPUT_FILE)).replace("_", " ").title()
    md_lines.append(f"# Path of Exile {title} Database\n")
    md_lines.append(f"Auto-generated from raw `{INPUT_FILE}` data. Flattened for clean AI context indexing.\n\n---\n")

    # If the JSON is a dictionary of items (like mods.json, gems.json, base_items.json)
    if isinstance(data, dict):
        for item_key, item_info in data.items():
            if not isinstance(item_info, dict):
                md_lines.append(f"### Entry: {item_key}\n* **Value**: {format_value(item_info)}\n\n")
                continue

            # Optional Mods.json filter to drastically reduce file size
            if ONLY_KEEP_PLAYER_ITEM_MODS and INPUT_FILE.startswith("mods"):
                if item_info.get("domain") != "item":
                    continue

            md_lines.append(f"### Entry: {item_key}\n")
            
            # Dynamically read and print every single key-value pair so nothing is missed
            for k, v in item_info.items():
                label = clean_key(k)
                formatted_val = format_value(v)
                md_lines.append(f"* **{label}**: {formatted_val}\n")
            md_lines.append("\n")

    # If the JSON is a flat list of items
    elif isinstance(data, list):
        for index, item_info in enumerate(data):
            if isinstance(item_info, dict):
                header = item_info.get("id") or item_info.get("name") or item_info.get("key") or f"Index {index}"
                md_lines.append(f"### Entry: {header}\n")
                for k, v in item_info.items():
                    label = clean_key(k)
                    formatted_val = format_value(v)
                    md_lines.append(f"* **{label}**: {formatted_val}\n")
            else:
                md_lines.append(f"### Entry {index}\n* **Value**: {format_value(item_info)}\n")
            md_lines.append("\n")

    print(f"Saving to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.writelines(md_lines)
        
    print("Finished successfully!")

if __name__ == "__main__":
    convert_json_to_md()