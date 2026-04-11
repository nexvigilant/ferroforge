import json
import os
import sys
import re

sys.path.insert(0, '/home/matthew/ferroforge/scripts')
from rsk_pool import catalog

cat = catalog()
micrograms = [m for m in cat['catalog'] if m.get('has_interface') and m.get('pass') and m.get('nodes', 0) > 4]

config_path = '/home/matthew/ferroforge/configs/microgram.json'
with open(config_path, 'r') as f:
    config = json.load(f)

existing_tools = {t['name'] for t in config['tools']}
new_tools_added = []

for m in micrograms:
    tool_name = "run-" + m['name']
    if tool_name in existing_tools:
        continue
    
    parameters = []
    typed_inputs = m.get('typed_inputs', {})
    for inp in m.get('inputs', []):
        t = typed_inputs.get(inp, "string")
        if t in ("int", "integer"): json_t = "integer"
        elif t in ("float", "number"): json_t = "number"
        elif t in ("bool", "boolean"): json_t = "boolean"
        else: json_t = "string"
        
        parameters.append({
            "name": inp,
            "type": json_t,
            "description": f"Input parameter: {inp}",
            "required": True
        })
        
    output_props = {
        "success": {"type": "boolean"},
        "steps": {"type": "array", "description": "Execution trace"}
    }
    typed_outputs = m.get('typed_outputs', {})
    for out in m.get('outputs', []):
        t = typed_outputs.get(out, "string")
        if t in ("int", "integer"): json_t = "integer"
        elif t in ("float", "number"): json_t = "number"
        elif t in ("bool", "boolean"): json_t = "boolean"
        else: json_t = "string"
        output_props[out] = {"type": json_t, "description": f"Output parameter: {out}"}
        
    tool_def = {
        "name": tool_name,
        "description": m.get('description', f"Run microgram {m['name']}"),
        "parameters": parameters,
        "outputSchema": {
            "type": "object",
            "properties": output_props,
            "required": ["success"] + m.get('outputs', [])
        },
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False
        }
    }
    config['tools'].append(tool_def)
    new_tools_added.append((tool_name, m['name']))

with open(config_path, 'w') as f:
    json.dump(config, f, indent=2)

print(f"Added {len(new_tools_added)} tools to microgram.json")

proxy_path = '/home/matthew/ferroforge/scripts/microgram_proxy.py'
with open(proxy_path, 'r') as f:
    proxy_lines = f.readlines()

out_lines = []
in_single_tools = False
for line in proxy_lines:
    if line.startswith("SINGLE_TOOLS = {"):
        in_single_tools = True
        out_lines.append(line)
        continue
    if in_single_tools and line.strip() == "}":
        in_single_tools = False
        # Inject new tools before closing brace
        for tool_name, m_name in new_tools_added:
            out_lines.append(f'    "{tool_name}": "{m_name}",\n')
        out_lines.append(line)
        continue
    out_lines.append(line)

with open(proxy_path, 'w') as f:
    f.writelines(out_lines)

print("Updated microgram_proxy.py")
