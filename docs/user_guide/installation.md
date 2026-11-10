# Install, launch, and update FIScH

[User guide](README.md) · [Next: Your first analysis](first_analysis.md)

Install FIScH, open the GUI, and keep an existing installation working. Start with the requirements, then follow the instructions for your platform. Setup can also install the optional Tad table viewer.

## Requirements

Before starting, you need:

- **Linux or Windows.** A macOS installer is available for testing; Mac
  dependency compatibility and processing still need validation on real hardware.
- **Git installed and available in your terminal.** Check with `git --version`.
  The platform instructions below include installation links.
- **uv is required.** It is a tool that downloads Python and installs the software
  libraries FIScH needs, keeping them together in a dedicated environment. Setup
  installs uv automatically if missing and reuses an existing installation;
  you do not need to install it beforehand.
- **An internet connection** to download submodules, Python, and dependencies.
- **A folder you can write to** for the Git clone and its Python environment.
  Use a Git clone rather than a downloaded ZIP archive.

**Installed automatically:** setup installs **uv** if missing, then uses it to
download **Python 3.12**, create the repository's `.venv`, and install FIScH
dependencies. You do not need to install Python separately. **A GPU is optional.**

An existing uv installation is reused. uv is a required, independent third-party tool;
FIScH does not maintain, update, or uninstall it. The installer uses uv's official
installer and installs it for your user in `~/.local/bin` (on Windows,
`%USERPROFILE%\.local\bin`), without changing shell profiles. No terminal restart
is needed for FIScH installation or launch. To use a newly installed uv directly
in a terminal, add that directory to your PATH. Like the optional Tad viewer,
uv is maintained separately; unlike Tad, uv is mandatory.

## Linux

1. Install [Git](https://git-scm.com/downloads/linux).
   Open a terminal and check that Git is available:

   ```bash
   git --version
   ```

2. Clone FIScH into a folder you can write to, then run the installer:

   ```bash
   git clone https://github.com/BennyGinger/fisch.git
   cd fisch
   bash install_linux.sh
   ```

   If you already cloned the repository, open a terminal in its main folder
   and run only `bash install_linux.sh`. Use the terminal command;
   double-clicking a shell script may open it in a text editor.

3. Wait for the installation to finish. Answer the optional **Tad** viewer
   prompt, then press Enter to close. Open **FIScH** from your Applications menu.
   You can also run `bash startup/launch_linux.sh` from the repository folder.

## Windows

1. Install [Git for Windows](https://git-scm.com/downloads/win).
   Open a new PowerShell window after installation and check Git:

   ```powershell
   git --version
   ```

2. Clone FIScH into a folder you can write to:

   ```powershell
   git clone https://github.com/BennyGinger/fisch.git
   cd fisch
   .\install_win.bat
   ```

   If you already cloned the repository, double-click **install_win.bat** in
   its main folder, or run `.\install_win.bat` from PowerShell in that folder.

3. Wait for the installation to finish. Answer the optional **Tad** viewer
   prompt, then press Enter to close. Open **FIScH** from the Start menu or
   the desktop shortcut.

## macOS (experimental)

1. Install [Git](https://git-scm.com/downloads/mac), then open Terminal and check
   `git --version`. If macOS asks to install Command Line Tools, finish that first.

2. Clone FIScH and run the Mac installer:

   ```bash
   git clone https://github.com/BennyGinger/fisch.git
   cd fisch
   bash install_macos.sh
   ```

   For an existing clone, run `bash install_macos.sh` from its main folder.
   uv and Python are downloaded automatically when missing. Keep the terminal
   output and `startup/logs/install.log` if dependencies or verification fail.

3. After successful installation, double-click `FIScH.command` in your home
   folder's `Applications` directory. It opens a terminal for startup and updates.
   Alternatively, run `bash startup/launch_macos.sh` from the repository folder.
   Install optional Tad separately from [its website](https://www.tadviewer.com/).

This installer uses the same dependency and import checks as Linux and Windows.
Apple Silicon/Intel compatibility and Apple GPU acceleration have not yet been
validated; providing this script does not guarantee every backend works on a Mac.

Interactive installers wait for **Enter** before finishing, so you can read the
result. No `--pause` flag is needed; unattended runs do not wait for input.

Run the FIScH installers as your normal user, without `sudo` or **Run as
administrator**. Use a Git clone rather than a downloaded ZIP; the installer
fetches the required submodules automatically. Keep the repository folder
after installation, since the shortcuts launch FIScH from there.

If installation fails, read the terminal message and
`startup/logs/install.log` (if created), fix the reported problem, and rerun
the same installer. See [installation details](#installation-details) for
optional settings, updates, and repair.

## Optional Tad installation

**Tad** is a separate desktop application for viewing tables. FIScH saves its
measurement results as **Parquet (`.parquet`) files**, which Tad lets you open
and inspect without writing Python code.

Tad setup is included with the FIScH installer. After FIScH installs, the terminal
offers to install Tad too. If you accept, it downloads Tad and keeps its files
and licence notices alongside FIScH under `startup/tools/Tad`. An existing
discoverable Tad installation is reused. Tad is developed independently of
FIScH; FIScH does not manage its updates.

On Linux, this local installation is outside APT and needs no package hold.
If you separately install Tad's `.deb`, run `sudo apt-mark hold tad` afterward
to prevent Ubuntu from replacing it with an unrelated package of the same name.

To use it, **double-click a Parquet file in the FIScH run browser**. Tad opens in
its own window. **Tad is optional:** skipping it, or a failed Tad installation,
does not prevent FIScH from processing images or saving measurements. If Tad is
unavailable, it can be downloaded manually from [Tad's website](https://www.tadviewer.com/). As another
alternative, the user can use
[Data Wrangler for Visual Studio Code](https://marketplace.visualstudio.com/items?itemName=ms-toolsai.datawrangler)
to inspect Parquet files.

Automatic installation supports **x86-64 Linux and Windows**, using Tad 0.14.0.
On macOS, or if you prefer a separate installation, download it from
[Tad's website](https://www.tadviewer.com/).
Use `--with-tad` to install without the prompt, or `--without-tad` to skip it.
Unattended installation skips Tad unless requested; automatic FIScH updates
also skip this optional setup.

## Installation details

The installer downloads and updates all submodules to the versions recorded by
your FIScH checkout before running ordinary `uv sync`. After pulling FIScH in an
existing clone, rerunning setup also updates clean, older submodules. Local
module edits or independent commits stop installation without being discarded.
It then checks GUI/backend imports and model-cache write access, and creates a
per-user Applications-menu entry on Linux, Start-menu and desktop shortcuts on Windows,
or a `~/Applications/FIScH.command` launcher on macOS. It does
not run the pipeline or request model weights. Model downloads happen on first
use. GPU availability is reported without making it an installation requirement.
Run as your normal user, rather than as administrator or with `sudo`.

On Windows, installation also marks dot-prefixed files and folders directly
inside the checkout (including `.git` and `.venv`) as hidden. `uv.lock` and
`pyproject.toml` remain visible; installation clears their Hidden attribute if
an earlier installer hid them. FIScH marks its
`.pipeline` metadata folders as hidden when creating or accessing them, keeping
their logs and caches out of ordinary Explorer views. Existing folders are
handled when next used; no drive-wide scan is performed. Hidden items remain
accessible through Explorer's **Hidden items** option. Failure to set the
attribute does not stop installation or processing. Linux behavior is unchanged.

Progress and subprocess errors are saved to `startup/logs/install.log`. If a
step fails, correct the reported problem and rerun the installer. Submodules
with local edits or independent commits cause setup to stop before changing
their checkouts. Clean, older modules are fetched and updated to the commits
required by the FIScH checkout; local work is not reset or discarded. If `uv sync`
changes the lockfile, the installer reports it for review.

Use `bash install_linux.sh --no-shortcut`, `bash install_macos.sh --no-shortcut`,
or `install_win.bat --no-shortcut`
to omit shortcuts. If an existing FIScH shortcut points to another checkout,
the installer asks before replacing it, after the new installation passes its
checks. The old folder is left untouched. Rerunning in the same location
refreshes that user's shortcut. Separate OS users should use their own writable
checkouts and environments.

Deleting a development checkout removes its code and `.venv`; save local work
and data first, including changes inside submodules. Per-user model/uv caches
and the shortcut remain. A fresh clone and installation recreate the environment
and can repoint the shortcut. If moving a checkout, recreate its `.venv` at the
new location and rerun the installer; virtual environments are not portable.

## Upgrade an existing FITS 4 installation to FIScH 5

Close FITS and open a terminal in its existing checkout. Save any local work,
including work inside submodules. If `.gitmodules` still lists `fits_io`, run
`git submodule deinit -- fits_io` before pulling. This retires that checkout so
the installer can initialize `scope_io` at the new path.

```bash
git remote set-url origin https://github.com/BennyGinger/fisch.git
git pull --ff-only
```

Run the installer for your platform from the updated checkout
(`bash install_linux.sh`, `bash install_macos.sh`, or `install_win.bat` on
Windows). This one-time installer step updates the environment and replaces the
old shortcut for this checkout. Then open FIScH from the new shortcut. The
FITS 4 launcher in memory still expects the old package name, so use these
steps for the transition to 5.0.0. Later FIScH versions use the startup update
prompt described below.

## Startup updates and repair

Menu/desktop shortcuts and the launchers check the configured upstream GitHub
repository's latest published stable release on startup. Only published releases
with an `X.Y.Z` tag count as updates; ordinary commits, tags without a release,
drafts, and prereleases do not. The check fetches only that FIScH release tag, without checking
submodule remotes or changing the working checkout. If an update is available,
the prompt shows the available and current version numbers. Choose **Yes** to
update or **Skip** to keep the current version. **Details** starts collapsed;
opening it expands the window downward to show the GitHub release description.
Closing the prompt also keeps the current version. If the network check fails, a working installation opens
with its current version; the failed check is recorded in the update log.

Updates require a clean checkout and a fast-forward from the installed commit.
Local edits, untracked files, conflicting module commits, or divergent history
disable automatic updating. FIScH never stashes, resets, deletes local work, or
advances modules independently of their recorded commits. Developer branches
and checkouts without a configured main/master upstream on GitHub skip automatic
checks. Checkouts already ahead of the release are left unchanged.

The prompt closes before installation starts. An independent process then
updates FIScH to the selected release's exact commit, initializes/synchronizes the pinned
submodules, runs the installer checks, and refreshes this checkout's existing
shortcuts. Progress appears in a terminal window (Linux requires an installed
GNOME Terminal, Konsole, or xterm when launching from a desktop shortcut).
The GUI opens only after verification succeeds. Installing an update can take
time when dependency downloads are needed.

The supervisor/updater use uv's managed Python outside `.venv`, so they remain
available if FIScH's environment needs repair. The installed Python path is saved
under `startup/logs/`; no extra virtual environment is created. A missing
environment, changed dependency receipt, or interrupted update offers **Repair
and launch**. If Qt itself cannot import, Windows's native dialog or Linux's
`zenity` provides a fallback; console launch remains available for repair.

An interrupted update retains its selected commit and can be retried. There is
no automatic rollback: one checkout and one `.venv` are updated in place. If a
step fails, inspect `startup/logs/update.log` and `install.log`; application
output is captured in `launcher.log`. The progress terminal offers retry after
fixing the reported issue. Local edits made during an interrupted update still
require manual reconciliation; they are never discarded automatically.

One supervised FIScH session per checkout is allowed. Close FIScH completely
before updating; the updater also checks the application lease used by direct
`uv run fisch-gui` launches. Independent viewer commands should be closed too.

For troubleshooting, append `--skip-update-check` to a launcher to skip the
network check, `--repair` to offer synchronization, or `--check-only` to print
the available update as JSON without opening the GUI. Direct `uv run fisch-gui`
continues to launch without the startup update check.

After first pulling the updater changes, rerun the OS installer once. This
records the independent Python path and refreshes shortcuts to use `startup/`.

Manual launchers live together in `startup/`:

- Linux: `startup/launch_linux.sh`.
- macOS: `startup/launch_macos.sh` (experimental).
- Windows: `startup/launch_win.vbs` opens without a console;
  `startup/launch_win.bat` keeps a console available for troubleshooting.

These enter the independent startup supervisor, which opens the GUI in the
checkout's `.venv`. After updating from the old root-level launchers, refresh
shortcuts by rerunning the OS installer.

## Refreshing the Linux shortcut

On Ubuntu, install an Applications-menu launcher with the FIScH logo:

```bash
.venv/bin/python startup/shortcuts.py
```

Search for **FIScH** in Applications, then pin it to your favourites if desired.
The launcher checks for updates before opening this checkout's GUI. Ordinary
launches do not open a terminal; accepted updates/repairs show terminal progress.
Rerun the installer if you move the repository.
