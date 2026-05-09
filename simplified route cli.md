# Python script for mission plan simplification
_Exported on 5/9/2026 at 00:46:01 EDT from Cursor (3.1.17)_

---

**User**

create a python execute in windows cli that get a list of point or mision plan and give the simplified one 

---

**Cursor**

Exploring the codebase for mission-plan formats and any existing simplification logic.



Reading the existing simplification module to reuse it in a CLI.



Adding `simplify_lat_lon_path` to reuse the mission simplifier's RDP logic, creating `cli_simplify_route.py`, and registering a `pyproject.toml` entry point for Windows-friendly execution.



Here’s what was added and how to run it on Windows.

### What you have now

1. **`simplify_lat_lon_path`** in ```36:62:/mnt/hgfs/codes/tr/backend/src/uav_route/simplify.py``` — applies the same prefilter + RDP as ```simplify_mission```, but for plain `(lat, lon)` lists.

2. **`cli_simplify_route.py`** — CLI that reads JSON and writes simplified JSON.

3. **Console script** `uav-simplify-mission` in `backend/pyproject.toml` (after install).

### Windows usage

From the `backend` folder (after install):

```bat
cd path\to\your\backend
pip install -e .
```

Then either:

```bat
uav-simplify-mission -i route.json -o simple.json
```

Or without installing (adjust paths):

```bat
set PYTHONPATH=%CD%\src
python -m uav_route.cli_simplify_route -i route.json -o simple.json
```

### Supported inputs

| Shape | Example |
|--------|---------|
| Mission | `{"mission":[{"seq":0,"command":16,"lat":..., "lon":..., ...}, ...]}` |
| Points object | `{"points": [[lat, lon], ...]}` |
| Points array | `[[lat, lon], ...]` top-level JSON array |
| GeoJSON | `FeatureCollection` with one `LineString` |

Use **`--lonlat`** if pairs are `[lon, lat]`. Tune density with **`--rdp-epsilon-m`** (meters; larger ⇒ fewer points), **`--min-separation-m`**, **`--min-turn-deg`**. For plain paths, **`--format geojson`** or **`json-array`** changes the output shape.

Mission output is always `{"mission": [...]}` with updated `seq` fields, matching ```load_mission_json``` in `mission.py`.

---

**User**

i want single exe file to call it from other python source or c# application

---

**Cursor**

Adding a PyInstaller spec and hardening the CLI for frozen (single-file) execution so we can build a Windows `.exe` and invoke it from Python or C#.



Adding a PyInstaller spec and Windows build script, skipping path bootstrap when frozen, and returning proper exit codes on failure for subprocess callers.



Updating the PyInstaller spec to match current PyInstaller (PYZ uses only `a.pure`; EXE bundles `a.binaries` and `a.datas`).



Here’s what was added so you can ship **one Windows `.exe`** and call it from Python or C#.

### Build (must run on **Windows**)

From the `backend` folder:

```bat
packaging\build_uav_simplify_exe.bat
```

Or manually:

```bat
pip install ".[exe]"
pyinstaller packaging\uav_simplify_mission.spec --clean --noconfirm
```

Artifact: **`backend\dist\uav-simplify-mission.exe`** (single-file console app).

Optional deps are in `pyproject.toml` under **`[project.optional-dependencies] exe`** (`pyinstaller>=6`).

### Repo changes

| File | Purpose |
|------|--------|
| `backend/packaging/uav_simplify_mission.spec` | PyInstaller one-file spec |
| `backend/packaging/build_uav_simplify_exe.bat` | Install `[exe]` + build |
| `cli_simplify_route.py` | Skips `sys.path` hacks when **frozen**; **exit codes** for callers |

**Exit codes:** `0` OK, `1` bad args / missing file / `ValueError`, `2` invalid JSON, `3` other failures.

### Calling from Python

```python
import subprocess

subprocess.run(
    [r"C:\path\to\uav-simplify-mission.exe", "-i", "in.json", "-o", "out.json"],
    check=True,
)
```

If the project is installed as a package on that machine, you can skip the exe:

```python
from uav_route.cli_simplify_route import main
main(["-i", "in.json", "-o", "out.json"])
```

### Calling from C# (.NET)

```csharp
var psi = new ProcessStartInfo
{
    FileName = @"C:\path\to\uav-simplify-mission.exe",
    ArgumentList = { "-i", @"C:\data\in.json", "-o", @"C:\data\out.json" },
    UseShellExecute = false,
    RedirectStandardOutput = true,
    RedirectStandardError = true,
    CreateNoWindow = true,
};
using var p = Process.Start(psi)!;
string err = p.StandardError.ReadToEnd();
string stdout = p.StandardOutput.ReadToEnd();
p.WaitForExit();
if (p.ExitCode != 0)
    throw new InvalidOperationException($"uav-simplify-mission exit {p.ExitCode}: {err}");
```

PyInstaller **targets the OS that runs the build**, so the exe must be produced on Windows for Windows hosts. Cross-building a Windows exe from Linux needs Wine/Wine-cross or a Windows CI runner.

