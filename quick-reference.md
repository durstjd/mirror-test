# Mirror Test Quick Reference Card v2.0

## Essential Commands
```bash
mirror-test                    # Test all distributions
mirror-test debian ubuntu      # Test specific distributions  
mirror-test gui                # Web interface (port 8080)
mirror-test cli                # Terminal interface with mouse
mirror-test cleanup            # Remove all test images
mirror-test help               # Show detailed help
```

## Information Commands
```bash
mirror-test list               # List configured distributions
mirror-test variables          # Show variables and values
mirror-test validate           # Validate configuration syntax
mirror-test logs debian        # View latest test logs
mirror-test dockerfile rocky   # Display generated Dockerfile
```

## Command-Line Options
```bash
--config FILE      # Use alternate configuration file
--port PORT        # Web interface port (default: 8080)
--verbose, -v      # Enable verbose output
--quiet, -q        # Suppress non-error output  
--timeout SECONDS  # Build timeout (default: 600)
--no-cleanup       # Don't remove images after testing
--version          # Show version information
--help, -h         # Show help message
```

## Configuration File Structure
```yaml
# /etc/mirror-test.yaml
variables:
  MIRROR_HOST: "10.10.0.15"
  MIRROR_BASE: "http://${MIRROR_HOST}"

package-managers:
  apt:
    update-command: "apt-get update"
    test-commands:
      - "apt-get install -y curl"

debian:
  base-image: debian:12
  package-manager: apt
  sources:
    - "deb ${MIRROR_BASE}/debian bookworm main"
  test-commands:  # Optional override
    - "apt-get install -y build-essential"
```

## Web Interface Shortcuts
- **Ctrl+R** - Run build test
- **Ctrl+L** - Load logs  
- **Ctrl+D** - View Dockerfile
- **URL**: http://localhost:8080

## CLI Interface Shortcuts
- **F1** - Run test
- **F2** - Load logs
- **F3** - View Dockerfile
- **F5** - Refresh
- **F10/q** - Exit
- **Tab** - Switch tabs
- **Space** - Select distribution
- **↑/↓** - Scroll
- **Mouse** - Click to select

## File Locations
- Config: `/etc/mirror-test.yaml`
- Logs: `/var/log/mirror-test/`
- Builds: `/var/lib/mirror-test/builds/`
- Service: `/etc/systemd/system/mirror-test-web.service`

## Systemd Service
```bash
systemctl start mirror-test-web    # Start web interface
systemctl enable mirror-test-web   # Enable at boot
systemctl status mirror-test-web   # Check status
systemctl stop mirror-test-web     # Stop service
```

## Troubleshooting
```bash
# Check logs for errors
tail -f /var/log/mirror-test/debian_latest.log

# Run with verbose output
mirror-test --verbose debian

# Validate configuration
mirror-test validate

# Clean up disk space
mirror-test cleanup
podman system prune -a

# Test with longer timeout
mirror-test --timeout 1200 debian
```

## Package Manager Commands
| Manager | Distros | Update | Test Package |
|---------|---------|--------|--------------|
| apt | Debian/Ubuntu | apt-get update | apt-utils |
| yum | RHEL 7/CentOS 7 | yum makecache | yum-utils |
| dnf | RHEL 8+/Rocky | dnf makecache | dnf-utils |
| zypper | openSUSE | zypper refresh | curl |
| apk | Alpine | apk update | curl |

## Variables Examples
```yaml
# Simple
MIRROR_HOST: "192.168.1.100"
MIRROR_BASE: "http://${MIRROR_HOST}"

# With ports
MIRROR_PORT: "8080"
MIRROR_BASE: "http://${MIRROR_HOST}:${MIRROR_PORT}"

# Multiple mirrors
PRIMARY: "mirror1.local"
BACKUP: "mirror2.local"
```

## Exit Codes
- **0** - All tests passed
- **1** - Tests failed
- **2** - Config error
- **3** - System requirements not met

## Aliases (after install)
```bash
mt          # mirror-test
mt-gui      # mirror-test gui
mt-cli      # mirror-test cli
mt-test     # mirror-test all
mt-clean    # mirror-test cleanup
```

---
*Version 2.0.0 | Files: /etc/mirror-test.yaml | Logs: /var/log/mirror-test/*