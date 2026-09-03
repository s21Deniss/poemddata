import json
import csv

# 1. Put the 'mods.json' you downloaded in the same folder as this script
input_file = "data/mods.json"
output_file = "poe_item_mods_summary.csv"

print("Reading mods.json...")
with open(input_file, "r", encoding="utf-8") as f:
    mods_data = json.load(f)

# 2. Filter and flatten the data to keep it high-density and lightweight
cleaned_mods = []
for mod_key, mod_info in mods_data.items():
    # Only keep item mods (ignore monster, map, or area-specific mods to save space)
    domain = mod_info.get("domain", "")
    if domain != "item":
        continue

    # Flatten stat rolls (e.g., "Life: 10 to 20")
    stats = []
    for stat in mod_info.get("stats", []):
        stat_id = stat.get("id", "")
        stat_min = stat.get("min", "")
        stat_max = stat.get("max", "")
        stats.append(f"{stat_id} ({stat_min} to {stat_max})")
    stats_str = " | ".join(stats)

    # Flatten rollable spawn weights (ignoring tags with 0 weight)
    weights = []
    for weight_entry in mod_info.get("spawn_weights", []):
        tag = weight_entry.get("tag", "")
        weight = weight_entry.get("weight", 0)
        if weight > 0:
            weights.append(f"{tag}:{weight}")
    weights_str = ", ".join(weights)

    cleaned_mods.append({
        "Mod Key": mod_key,
        "Group": mod_info.get("group", ""),
        "Generation Type": mod_info.get("generation_type", ""),
        "Required Level": mod_info.get("required_level", 0),
        "Stats": stats_str,
        "Spawn Weights": weights_str
    })

# 3. Write to a lightweight, clean CSV
print(f"Saving cleaned data to {output_file}...")
fieldnames = ["Mod Key", "Group", "Generation Type", "Required Level", "Stats", "Spawn Weights"]
with open(output_file, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(cleaned_mods)

print("Finished! You can now upload 'poe_item_mods_summary.csv' directly to your notebook sources.")
