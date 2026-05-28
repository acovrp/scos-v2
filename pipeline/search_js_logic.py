import re
import os

index_path = r"C:\Users\User\Downloads\pwa-push\index.html"
out_path = r"C:\Users\User\Downloads\scos-v2\data\js_logic_found.txt"

# Clear file first
open(out_path, "w", encoding="utf-8").close()

with open(index_path, 'r', encoding='utf-8', errors='ignore') as f:
    content = f.read()

# Let's search for "function" declarations
matches = re.finditer(r"function\s+(\w+)\s*\(", content)
for m in matches:
    name = m.group(1)
    start_pos = m.start()
    snippet = content[start_pos:start_pos+3000]
    if any(keyword in snippet for keyword in ["applySnapshot", "channels", "adSpend", "weeklyCube"]):
        with open(out_path, "a", encoding="utf-8") as f_out:
            f_out.write(f"--- Function {name} ---\n")
            lines = snippet.split("\n")
            f_out.write("\n".join(lines[:45]))
            f_out.write("\n...\n" + "="*50 + "\n")

print("Done. Output written to:", out_path)
