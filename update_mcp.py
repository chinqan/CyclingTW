import json

config_path = "/Users/chinqan-mac/.gemini/antigravity/mcp_config.json"

with open(config_path, "r") as f:
    config = json.load(f)

if "mcpServers" not in config:
    config["mcpServers"] = {}

config["mcpServers"]["openroute-mcp"] = {
    "command": "/opt/anaconda3/bin/openroute-mcp",
    "args": [
        "--data-folder",
        "/Users/chinqan-mac/Documents/CyclingTW/data"
    ],
    "env": {
        "OPENROUTESERVICE_API_KEY": "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6ImI3MDMxMjljMjY1ODQzMGViYTc5NzI4Y2EzNWQwZDc0IiwiaCI6Im11cm11cjY0In0="
    }
}

with open(config_path, "w") as f:
    json.dump(config, f, indent=2)

print("Added openroute-mcp to mcp_config.json")
