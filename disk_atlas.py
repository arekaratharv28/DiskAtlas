import os
import argparse
import pandas as pd
import plotly.express as px
import webbrowser

def format_size(size_bytes):
    """Dynamically formats bytes into MB or GB."""
    if size_bytes == 0:
        return "0 MB"
    size_mb = size_bytes / (1024 * 1024)
    if size_mb >= 1024:
        size_gb = size_mb / 1024
        return f"{size_gb:.2f} GB"
    return f"{size_mb:.2f} MB"

def get_dir_size(path, exclude_keywords):
    """Recursively calculates folder size, dodging locked system files and excluded paths."""
    total = 0
    try:
        for entry in os.scandir(path):
            if any(keyword in entry.path for keyword in exclude_keywords):
                continue
                
            try:
                if entry.is_file(follow_symlinks=False):
                    total += entry.stat().st_size
                elif entry.is_dir(follow_symlinks=False):
                    total += get_dir_size(entry.path, exclude_keywords)
            except (PermissionError, FileNotFoundError, OSError):
                pass 
    except (PermissionError, FileNotFoundError, OSError):
        pass
    return total

def scan_drive(root_path, exclude_keywords, max_depth, current_depth=0):
    """Scans and builds the hierarchy using unique absolute paths."""
    data = []
    try:
        for entry in os.scandir(root_path):
            if any(keyword in entry.path for keyword in exclude_keywords):
                continue

            try:
                entry_id = entry.path
                parent_id = root_path
                entry_name = entry.name
                
                if entry.is_file(follow_symlinks=False):
                    size = entry.stat().st_size
                    data.append({"ID": entry_id, "Parent": parent_id, "Name": entry_name, "Size": size, "Is_Dir": False})
                    
                elif entry.is_dir(follow_symlinks=False):
                    size = get_dir_size(entry.path, exclude_keywords)
                    data.append({"ID": entry_id, "Parent": parent_id, "Name": entry_name, "Size": size, "Is_Dir": True})
                    
                    if current_depth < max_depth:
                        data.extend(scan_drive(entry.path, exclude_keywords, max_depth, current_depth + 1))
            except (PermissionError, FileNotFoundError, OSError):
                pass
    except (PermissionError, FileNotFoundError, OSError):
        pass
    return data

def get_ai_advice(df, advisor_type, ai_model=None):
    """Generates relatable advice based on the largest files using AI."""
    if advisor_type == "none":
        return "AI Advisor is disabled. Run with <code>--ai-advisor online</code> or <code>--ai-advisor local</code> to get smart space management tips!"
        
    print(f"\n🧠 Consulting the {advisor_type} AI advisor... (This might take a few seconds)")
    
    top_items = df.sort_values(by="Size", ascending=False).head(20)
    data_str = ""
    for _, row in top_items.iterrows():
        data_str += f"- {row['Name']} (Path: {row['ID']}): {format_size(row['Size'])}\n"
    
    prompt = f"""You are a snarky, relatable, but genuinely helpful digital janitor. 
The user is running out of disk space. Here are their largest files and folders (do NOT hallucinate file paths, only use the ones provided):
{data_str}

Give them a brief, fun, and personalized summary (2-3 short paragraphs) on what's eating their space. 
Call out specific things like node_modules, huge game folders, cache, or videos if you see them. 
Give them direct advice on what to delete, move to an external drive, or ignore (like system files).
Format your response in plain text with emojis where appropriate. Do not use markdown headers."""

    if advisor_type == "online":
        model_name = ai_model if ai_model else "gemini-2.5-flash"
        try:
            from google import genai
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                return "<strong>Missing API Key:</strong> To use the online advisor, please set the <code>GEMINI_API_KEY</code> environment variable."
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            return response.text.replace("\n", "<br>")
        except Exception as e:
            return f"Failed to get advice from Gemini using model '{model_name}': {e}"
            
    elif advisor_type == "local":
        model_name = ai_model if ai_model else "llama3.2"
        try:
            import requests
            res = requests.post("http://localhost:11434/api/generate", json={
                "model": model_name, 
                "prompt": prompt,
                "stream": False
            })
            if res.status_code == 200:
                return res.json().get("response", "").replace("\n", "<br>")
            else:
                return f"Ollama returned an error: {res.text}. Make sure it's running with the '{model_name}' model."
        except Exception as e:
            return f"Failed to connect to local Ollama: {e}<br><br>Make sure Ollama is installed and running."
            
    return "Unknown AI advisor type."

def main():
    parser = argparse.ArgumentParser(description="DiskAtlas: An interactive and AI-powered disk space analyzer.")
    parser.add_argument("--drive", type=str, default=".", help="The directory or drive to scan (default: current directory)")
    parser.add_argument("--depth", type=int, default=5, help="Maximum depth for the treemap hierarchy (default: 5)")
    parser.add_argument("--min-size", type=int, default=100, help="Minimum item size in MB to display (default: 100)")
    parser.add_argument("--exclude", nargs="*", default=["GoogleDrive", "OneDrive"], help="List of folder names/keywords to exclude")
    parser.add_argument("--ai-advisor", choices=["none", "online", "local"], default="none", help="Use AI to analyze and suggest cleanup (default: none)")
    parser.add_argument("--ai-model", type=str, default=None, help="Specific model to use (e.g., gemini-1.5-pro for online, qwen2.5 for local)")
    args = parser.parse_args()

    root_target = os.path.abspath(args.drive)
    print(f"🔍 Scanning {root_target}... (Threshold: {args.min_size} MB)")
    print(f"🚫 Excluding: {', '.join(args.exclude)}")
    print("⏳ This may take a while depending on the size of the directory...")

    # 1. Collect Data
    disk_data = scan_drive(root_target, args.exclude, args.depth)

    # 2. Add Root Node
    root_size = sum(item["Size"] for item in disk_data if item["Parent"] == root_target)
    disk_data.append({"ID": root_target, "Parent": "", "Name": root_target, "Size": root_size, "Is_Dir": True})

    # 3. Clean & Process
    df = pd.DataFrame(disk_data)
    if df.empty:
        print("No data found or permission denied.")
        return

    # Keep root and large items
    is_large = (df["Size"] >= args.min_size * 1024 * 1024) | (df["ID"] == root_target)
    df_filtered = df[is_large].copy()

    # Create Filler nodes (Cross-platform compatible)
    filler_nodes = []
    for _, row in df_filtered.iterrows():
        if row["Is_Dir"]:
            parent_id = row["ID"]
            surviving_children = df_filtered[df_filtered["Parent"] == parent_id]
            sum_children = surviving_children["Size"].sum()
            missing_space = row["Size"] - sum_children
            
            if missing_space > (1024 * 1024):
                filler_nodes.append({
                    "ID": os.path.join(parent_id, "_Small_Files"),
                    "Parent": parent_id,
                    "Name": f"Small Files (<{args.min_size}MB)",
                    "Size": missing_space,
                    "Is_Dir": False
                })

    df_final = pd.concat([df_filtered, pd.DataFrame(filler_nodes)], ignore_index=True)
    
    # Format labels dynamically for the plot
    df_final["Formatted Size"] = df_final["Size"].apply(format_size)

    # 4. Generate AI Advice
    ai_advice = get_ai_advice(df_final, args.ai_advisor, args.ai_model)

    # 5. Build Treemap Figure
    print("🎨 Building the Interactive Dashboard...")
    fig = px.treemap(
        df_final,
        ids='ID',
        names='Name',
        parents='Parent',
        values='Size',
        custom_data=['Formatted Size', 'ID'],
        color='Size',
        color_continuous_scale='YlOrRd'
    )

    # Customize hover and layout for a transparent, adaptive theme
    fig.update_traces(
        hovertemplate="<b>%{label}</b><br>Size: %{customdata[0]}<br>Path: %{customdata[1]}<extra></extra>",
        textinfo="label+value",
        texttemplate="<b>%{label}</b><br>%{customdata[0]}",
        marker=dict(line=dict(color='rgba(0,0,0,0.2)', width=1))
    )
    fig.update_layout(
        margin=dict(t=0, l=0, r=0, b=0),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        font=dict(family="'Segoe UI', Roboto, Helvetica, Arial, sans-serif")
    )

    # Generate Plotly HTML div
    plotly_div = fig.to_html(full_html=False, include_plotlyjs='cdn')

    # 6. Construct the UI HTML
    html_template = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>DiskAtlas Dashboard</title>
        <style>
            :root {{
                --bg-main: #ffffff;
                --bg-sidebar: #f8fafc;
                --bg-content: #ffffff;
                --text-main: #1e293b;
                --text-muted: #64748b;
                --border-color: #e2e8f0;
                --accent: #ef4444;
                --shadow: rgba(0,0,0,0.05);
            }}
            
            [data-theme="dark"] {{
                --bg-main: #0f172a;
                --bg-sidebar: #1e293b;
                --bg-content: #0f172a;
                --text-main: #f8fafc;
                --text-muted: #94a3b8;
                --border-color: #334155;
                --accent: #fb923c;
                --shadow: rgba(0,0,0,0.5);
            }}

            body {{ font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: var(--bg-main); color: var(--text-main); margin: 0; display: flex; height: 100vh; overflow: hidden; transition: background 0.3s, color 0.3s; }}
            .sidebar {{ width: 380px; background-color: var(--bg-sidebar); padding: 25px; overflow-y: auto; box-shadow: 2px 0 10px var(--shadow); z-index: 10; display: flex; flex-direction: column; gap: 20px; border-right: 1px solid var(--border-color); transition: background 0.3s, border 0.3s; }}
            .main-content {{ flex-grow: 1; padding: 15px; display: flex; flex-direction: column; background-color: var(--bg-content); transition: background 0.3s; }}
            .plotly-container {{ flex-grow: 1; border-radius: 12px; overflow: hidden; background: var(--bg-sidebar); box-shadow: 0 4px 6px var(--shadow); border: 1px solid var(--border-color); transition: background 0.3s, border 0.3s; }}
            
            .header-container {{ display: flex; justify-content: space-between; align-items: center; }}
            h1 {{ font-size: 28px; margin: 0; color: var(--accent); font-weight: 700; letter-spacing: -0.5px; display: flex; align-items: center; gap: 10px; }}
            h2 {{ font-size: 16px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 1px; border-bottom: 1px solid var(--border-color); padding-bottom: 8px; margin: 0; }}
            
            .theme-toggle {{ background: none; border: 1px solid var(--border-color); color: var(--text-main); font-size: 18px; cursor: pointer; padding: 6px 10px; border-radius: 8px; transition: 0.2s; }}
            .theme-toggle:hover {{ background: var(--border-color); }}
            
            .stats-grid {{ display: grid; grid-template-columns: 1fr; gap: 15px; }}
            .stat-box {{ background: var(--bg-sidebar); padding: 16px; border-radius: 10px; border: 1px solid var(--border-color); border-left: 4px solid var(--accent); transition: background 0.3s, border 0.3s; }}
            .stat-value {{ font-size: 24px; font-weight: bold; color: var(--text-main); margin-top: 4px; transition: color 0.3s; }}
            .stat-label {{ font-size: 13px; color: var(--text-muted); font-weight: 500; transition: color 0.3s; }}
            .ai-advice {{ background-color: var(--bg-sidebar); padding: 20px; border-radius: 10px; font-size: 15px; line-height: 1.6; border: 1px solid var(--border-color); color: var(--text-main); box-shadow: 0 1px 2px var(--shadow); transition: background 0.3s, border 0.3s, color 0.3s; }}
            .footer {{ margin-top: auto; font-size: 12px; color: var(--text-muted); text-align: center; padding-top: 20px; transition: color 0.3s; }}
        </style>
    </head>
    <body>
        <div class="sidebar">
            <div class="header-container">
                <h1>🧹 DiskAtlas</h1>
                <button class="theme-toggle" id="theme-btn" title="Toggle Dark/Light Mode">🌓</button>
            </div>
            
            <div class="stats-grid">
                <div class="stat-box">
                    <div class="stat-label">Directory Scanned</div>
                    <div class="stat-value" style="font-size: 18px; word-break: break-all;">{root_target}</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">Total Size Found</div>
                    <div class="stat-value" style="color: var(--accent);">{format_size(root_size)}</div>
                </div>
                <div class="stat-box">
                    <div class="stat-label">Large Items (>{args.min_size}MB)</div>
                    <div class="stat-value">{len(df_final[df_final["Name"] != f"Small Files (<{args.min_size}MB)"])}</div>
                </div>
            </div>
            
            <h2>AI Storage Advisor</h2>
            <div class="ai-advice">
                {ai_advice}
            </div>

            <div class="footer">
                DiskAtlas CLI &bull; Generated Dashboard
            </div>
        </div>
        <div class="main-content">
            <div class="plotly-container" id="plot-container">
                {plotly_div}
            </div>
        </div>

        <script>
            // Theme toggling logic
            const themeBtn = document.getElementById('theme-btn');
            
            // Auto-detect system theme
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            if (prefersDark) {{
                document.documentElement.setAttribute('data-theme', 'dark');
            }}

            themeBtn.addEventListener('click', () => {{
                const currentTheme = document.documentElement.getAttribute('data-theme');
                const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
                document.documentElement.setAttribute('data-theme', newTheme);
                
                // Update Plotly text color based on theme
                const plotlyGraph = document.querySelector('.plotly-graph-div');
                if (plotlyGraph) {{
                    const fontColor = newTheme === 'dark' ? '#ffffff' : '#1e293b';
                    Plotly.relayout(plotlyGraph, {{ 'font.color': fontColor }});
                }}
            }});
            
            // Set initial plotly font color
            setTimeout(() => {{
                const plotlyGraph = document.querySelector('.plotly-graph-div');
                if (plotlyGraph && document.documentElement.getAttribute('data-theme') === 'dark') {{
                    Plotly.relayout(plotlyGraph, {{ 'font.color': '#ffffff' }});
                }}
            }}, 500);
        </script>
    </body>
    </html>
    """

    output_file = "disk_dashboard.html"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html_template)
        
    print(f"✨ Done! Opening your beautiful new dashboard: {output_file}")
    webbrowser.open('file://' + os.path.realpath(output_file))

if __name__ == "__main__":
    main()