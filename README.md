# Open-Custom Visuals for Open WebUI

Open-Custom Visuals lets Open WebUI respond with visual and interactive content when a chart, diagram, data explainer, or interactive layout is clearer than plain text. Some visuals are generated from uploaded tabular data. Others are custom-built for the user's exact prompt as inline HTML, SVG, and JavaScript.

Two companion actions are included so users can reopen a finished visual or keep/export it after the reply is complete.

<video src="./banner.mp4" controls muted loop playsinline style="max-width: 100%;"></video>

## Included Files

| File | Install In Open WebUI | Purpose |
| --- | --- | --- |
| [`tool.py`](./tool.py) | `Workspace -> Tools` | Main tool that streams or renders inline visuals |
| [`SKILL.md`](./SKILL.md) | `Workspace -> Skills` | Instructions that teach the model how to build good visuals |
| [`open_visual_action.py`](./open_visual_action.py) | `Admin Panel -> Functions` | Action button that reopens a visual from a message |
| [`keep_visual_action.py`](./keep_visual_action.py) | `Admin Panel -> Functions` | Action button for copying/downloading/exporting a visual |

## Prerequisites

- Open WebUI `0.6.0` or newer
- A model that can use custom tools
- Native function calling enabled if you want the model to lazy-load the attached skill automatically

Recommended permissions:

- `Workspace > Tools Access` and `Tools Import`
- `Workspace > Skills Access`
- Admin access for `Functions`

## Package Requirements

No extra pip packages are required for this bundle.

- The files use Python standard-library modules plus Open WebUI runtime dependencies such as `fastapi` and `pydantic`.
- There is no separate `requirements.txt` to install before importing these files into Open WebUI.

## Important Setup Note

For the best live inline experience, enable:

- `Settings -> Interface -> Iframe Same-Origin Access`

If this setting stays off:

- live streaming inside the inline iframe is limited
- the tool falls back to a guidance card instead of full live rendering
- `Open Visual` can still reconstruct the finished visual from the saved message
- `Keep Visual` can still run page-context export actions

## Installation

Install each file in the correct Open WebUI section. Do not paste the action files into `Tools`, and do not place `SKILL.md` in `Knowledge`.

### 1. Install the Tool

1. Open Open WebUI.
2. Go to `Workspace -> Tools`.
3. Create a new tool or import a local file.
4. Paste or upload [`tool.py`](./tool.py).
5. Save it.
6. Confirm the tool appears as `Open-Custom Visuals`.
7. Enable the tool if your instance uses per-tool activation.

### 2. Install the Skill

1. Go to `Workspace -> Skills`.
2. Click `Import` and select [`SKILL.md`](./SKILL.md), or create a new skill and paste the file contents.
3. Save the skill.
4. If you create it manually instead of importing the file, make sure the **Skill ID** is exactly `open_custom_visuals`.

Why the ID matters:

- the tool instructs the model to load this skill by calling `view_skill("open_custom_visuals")`
- if the Skill ID does not match, the model will not find the instructions automatically

### 3. Install the Two Action Functions

Each action file must be saved as its own Function.

1. Go to `Admin Panel -> Functions`.
2. Create or import a function for [`open_visual_action.py`](./open_visual_action.py).
3. Review the code and click `Save`.
4. Make sure Open WebUI detects it as an `Action`.
5. Turn the function on.
6. Repeat the same process for [`keep_visual_action.py`](./keep_visual_action.py).

### 4. Attach Everything to Your Model

1. Go to `Workspace -> Models`.
2. Edit the model that should support inline visuals.
3. In the `Tools` section, enable `Open-Custom Visuals`.
4. In the `Skills` section, attach `open_custom_visuals`.
5. In the `Actions` section, attach:
   - `Open Visual`
   - `Keep Visual`
6. Save the model.

### 5. Final Check

Open a chat with that model and ask for a chart, diagram, or interactive explainer. If the tool, skill, and actions were installed in the correct sections, the model can render inline visuals and the message toolbar should show the included actions.

## How To Use

- Ask naturally for a chart, diagram, flow, comparison, dashboard, or data explainer.
- Upload CSV, TSV, JSON, or markdown-table data if you want the visual built from attached data.
- Use `Open Visual` on a message to reopen the visual.
- Use `Keep Visual` to copy or export the result.

If model-attached skill loading is unavailable in your setup, mention the skill manually in chat with `$open_custom_visuals`.

## Data Handling

Attached tabular data is normalized before it is exposed to the visual runtime.

- Maximum parsed text: `5 MB`
- Maximum rows: `10,000`
- Maximum columns: `100`

Supported structured inputs:

- `.csv`
- `.tsv`
- `.json`
- markdown tables in `.md`, `.markdown`, or `.txt`
