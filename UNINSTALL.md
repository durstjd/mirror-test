# Mirror Test Uninstall Scripts
**Version 2.1.0** | **September 2025**

This directory contains uninstall scripts for the Mirror Test tool, supporting Linux/Unix environments.

## Available Scripts

### Linux/Unix (Bash)
- **`uninstall.sh`** - Main uninstall script for Linux/Unix systems

## Usage

### Linux/Unix

```bash
# Make executable (if not already)
chmod +x uninstall.sh

# Remove all installations with confirmation
./uninstall.sh

# Remove only user installation without confirmation
./uninstall.sh --user --yes

# Remove only system installation and clean containers
./uninstall.sh --system --cleanup

# Show help
./uninstall.sh --help
```

## Command Line Options

| Option | Description |
|--------|-------------|
| `-h, --help` | Show help message |
| `-s, --system` | Remove only system-wide installation |
| `-u, --user` | Remove only user-level installation |
| `-a, --all` | Remove both system and user installations (default) |
| `-c, --cleanup` | Also clean up containers and images |
| `-y, --yes` | Skip confirmation prompts |

## What Gets Removed

### System-wide Installation
- **Binary**: `/usr/local/bin/mirror-test` or `/usr/bin/mirror-test`
- **Configuration**: `/etc/mirror-test.yaml` or `~/.config/mirror-test/config.yaml`
- **Logs**: `/var/log/mirror-test/` or `~/.local/share/mirror-test/logs/`
- **Builds**: `/var/lib/mirror-test/` or `~/.local/share/mirror-test/builds/`
- **Service**: `/etc/systemd/system/mirror-test.service`
- **Completion**: `/etc/bash_completion.d/mirror-test`

### User-level Installation
- **Binary**: `~/.local/bin/mirror-test`
- **Configuration**: `~/.config/mirror-test/config.yaml`
- **Logs**: `~/.local/share/mirror-test/logs/`
- **Builds**: `~/.local/share/mirror-test/builds/`
- **Service**: `~/.config/systemd/user/mirror-test.service`
- **Completion**: `~/.bash_completion.d/mirror-test`


## Container Cleanup

When using the `--cleanup` (or `-Cleanup`) option, the script will also:

1. **Stop and remove** all containers with the `mirror-test` label
2. **Remove** all images with the `mirror-test` label
3. **Clean up** any associated volumes (if any)

This requires Podman to be installed and accessible.

## Safety Features

- **Confirmation prompts** by default (can be skipped with `--yes` or `-Yes`)
- **Detection** of existing installations before removal
- **Graceful handling** of missing files or directories
- **Error handling** for permission issues
- **Detailed output** showing what was removed

## Examples

### Complete Removal
```bash
# Linux/Unix
./uninstall.sh --cleanup
```

### User-only Removal
```bash
# Linux/Unix
./uninstall.sh --user --yes
```

### System-only Removal
```bash
# Linux/Unix (requires sudo)
sudo ./uninstall.sh --system
```

## Troubleshooting

### Permission Denied (Linux/Unix)
If you get permission denied errors when removing system files, run with `sudo`:

```bash
sudo ./uninstall.sh --system
```


### Container Cleanup Fails
If container cleanup fails, it's usually because:
- Podman is not installed
- Podman is not in the PATH
- Containers/images are in use

The script will continue with file removal even if container cleanup fails.

## Notes

- The scripts are designed to be **safe** and will not remove files that don't belong to mirror-test
- **Backup important data** before running the uninstall script
- After uninstalling, you may need to **restart your shell** or **reload your PATH** to see changes
- The scripts will **detect** what's actually installed and only remove those components
