# Mirror Test User Manual
**Version 2.0.0** | **January 2025**

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Installation](#2-installation)
3. [Configuration](#3-configuration)
4. [Usage](#4-usage)
5. [Commands Reference](#5-commands-reference)
6. [Web Interface](#6-web-interface)
7. [Terminal Interface](#7-terminal-interface)
8. [Troubleshooting](#8-troubleshooting)
9. [Examples](#9-examples)
10. [Appendix](#10-appendix)

---

## 1. Introduction

Mirror Test is a comprehensive tool for validating local Linux repository mirrors. It uses container build processes to verify that packages can be accessed and installed from configured mirror servers.

### Key Features
- **Multi-distribution support** - Test Debian, Ubuntu, RHEL, SUSE, Alpine, and more
- **Variable substitution** - Define mirror URLs once, use everywhere
- **Customizable tests** - Configure package manager commands and test packages
- **Dual interface** - Web GUI and terminal CLI with mouse support
- **Automated cleanup** - No residual images left after testing
- **Comprehensive logging** - Detailed logs for debugging

### System Requirements
- Linux operating system
- Podman or Docker installed
- Python 3.6 or higher
- Root access (recommended)
- Minimum 2GB RAM
- 10GB free disk space

---

## 2. Installation

### Quick Install

```bash
# Download and run the setup script
wget https://example.com/setup-mirror-test.sh
chmod +x setup-mirror-test.sh
sudo ./setup-mirror-test.sh
```

### Manual Installation

1. **Install dependencies:**
```bash
# Debian/Ubuntu
sudo apt-get install python3 python3-yaml podman bash-completion

# RHEL/Rocky/AlmaLinux
sudo dnf install python3 python3-pyyaml podman bash-completion

# openSUSE
sudo zypper install python3 python3-PyYAML podman bash-completion
```

2. **Copy files:**
```bash
sudo cp mirror-test /usr/bin/
sudo chmod +x /usr/bin/mirror-test
sudo cp mirror-test-completion /etc/bash_completion.d/mirror-test
```

3. **Create directories:**
```bash
sudo mkdir -p /etc /var/log/mirror-test /var/lib/mirror-test/builds
```

4. **Create configuration:**
```bash
sudo nano /etc/mirror-test.yaml
```

### Enable Autocomplete

```bash
# Reload bash completion
source /etc/bash_completion.d/mirror-test

# Test autocomplete
mirror-test <TAB><TAB>
```

---

## 3. Configuration

### Configuration File Structure

The configuration file `/etc/mirror-test.yaml` has three main sections:

#### Variables Section
Define reusable variables for mirror URLs and settings:

```yaml
variables:
  MIRROR_HOST: "10.10.0.15"
  MIRROR_PROTO: "http"
  MIRROR_BASE: "${MIRROR_PROTO}://${MIRROR_HOST}"
  GPG_CHECK: "0"
```

#### Package Managers Section
Configure how each package manager should be tested:

```yaml
package-managers:
  apt:
    update-command: "apt-get update"
    test-commands:
      - "apt-get install -y --no-install-recommends curl wget"
      - "apt-cache stats"
      - "echo 'APT repository test successful'"
  
  dnf:
    update-command: "dnf makecache"
    test-commands:
      - "dnf install -y dnf-utils"
      - "dnf repolist --all"
      - "echo 'DNF repository test successful'"
```

#### Distributions Section
Define each distribution to test:

```yaml
debian:
  base-image: debian:12
  package-manager: apt
  sources:
    - "deb ${MIRROR_BASE}/debian bookworm main contrib non-free"
  # Optional: Override test commands for this distribution
  test-commands:
    - "apt-get install -y build-essential"
    - "gcc --version"
```

### Using Variables

Variables support nested references:

```yaml
variables:
  DOMAIN: "company.com"
  MIRROR_HOST: "mirror.${DOMAIN}"
  MIRROR_BASE: "http://${MIRROR_HOST}"
```

### Repository Configuration Examples

#### APT (Debian/Ubuntu)
```yaml
sources:
  - "deb ${MIRROR_BASE}/ubuntu jammy main restricted universe multiverse"
  - "deb ${MIRROR_BASE}/ubuntu jammy-updates main restricted universe multiverse"
  - "deb ${MIRROR_BASE}/ubuntu jammy-security main restricted universe multiverse"
```

#### YUM/DNF (RHEL-based)
```yaml
sources:
  - |
    [baseos]
    name=BaseOS
    baseurl=${MIRROR_BASE}/rocky/$releasever/BaseOS/$basearch/os/
    enabled=1
    gpgcheck=0
    
    [appstream]
    name=AppStream
    baseurl=${MIRROR_BASE}/rocky/$releasever/AppStream/$basearch/os/
    enabled=1
    gpgcheck=0
```

#### APK (Alpine)
```yaml
sources:
  - "${MIRROR_BASE}/alpine/v3.19/main"
  - "${MIRROR_BASE}/alpine/v3.19/community"
```

---

## 4. Usage

### Basic Commands

```bash
# Test all distributions
mirror-test

# Test specific distributions
mirror-test debian ubuntu rocky

# Launch web interface
mirror-test gui

# Launch terminal interface
mirror-test cli

# View logs
mirror-test logs debian

# Clean up images
mirror-test cleanup
```

### Command-Line Options

| Option | Description | Example |
|--------|-------------|---------|
| `--config FILE` | Use alternate config | `mirror-test --config /path/to/config.yaml` |
| `--port PORT` | Web interface port | `mirror-test gui --port 8081` |
| `--verbose` | Detailed output | `mirror-test --verbose debian` |
| `--quiet` | Suppress output | `mirror-test --quiet all` |
| `--timeout SEC` | Build timeout | `mirror-test --timeout 1200` |
| `--no-cleanup` | Keep test images | `mirror-test --no-cleanup debian` |
| `--version` | Show version | `mirror-test --version` |
| `--help` | Show help | `mirror-test --help` |

### Exit Codes

- **0** - All tests passed
- **1** - One or more tests failed
- **2** - Configuration error
- **3** - System requirements not met

---

## 5. Commands Reference

### Core Testing Commands

#### `mirror-test [DISTRIBUTIONS...]`
Test specified distributions or all if none specified.

```bash
mirror-test                  # Test all
mirror-test debian           # Test Debian only
mirror-test debian ubuntu    # Test multiple
```

#### `mirror-test cleanup`
Remove all test container images to free disk space.

```bash
mirror-test cleanup
# Output: Cleaned up 5 mirror-test images
```

### Information Commands

#### `mirror-test list`
List all configured distributions.

```bash
mirror-test list
# Output:
# debian-12            debian:12              [apt]
# ubuntu-22-04         ubuntu:22.04           [apt]
# rocky-9              rockylinux:9           [dnf]
```

#### `mirror-test variables`
Show configured variables and their expanded values.

```bash
mirror-test variables
# Output:
# MIRROR_HOST         = 10.10.0.15
# MIRROR_BASE         = http://10.10.0.15
```

#### `mirror-test validate`
Validate configuration file syntax.

```bash
mirror-test validate
# Output: ✓ Configuration is valid
```

### Log Commands

#### `mirror-test logs DISTRIBUTION`
View the latest test logs for a distribution.

```bash
mirror-test logs debian
# Shows full build output and test results
```

#### `mirror-test dockerfile DISTRIBUTION`
Display the generated Dockerfile for a distribution.

```bash
mirror-test dockerfile rocky
# Shows the complete Dockerfile that would be built
```

---

## 6. Web Interface

### Starting the Web Interface

```bash
# Start on default port 8080
mirror-test gui

# Start on custom port
mirror-test gui --port 8081

# Start as a service
systemctl start mirror-test-web
```

### Web Interface Features

- **Distribution Selection** - Multi-select dropdown
- **Real-time Testing** - Watch build progress live
- **Log Viewer** - Separate tabs for output, errors, Dockerfile
- **Keyboard Shortcuts**:
  - `Ctrl+R` - Run test
  - `Ctrl+L` - Load logs
  - `Ctrl+D` - View Dockerfile

### Accessing the Interface

Open your browser to: `http://localhost:8080`

---

## 7. Terminal Interface

### Starting the Terminal Interface

```bash
mirror-test cli
```

### Terminal Interface Features

- **Mouse Support** - Click to select and navigate
- **Keyboard Navigation** - Full keyboard control
- **Multiple Tabs** - Switch between output, errors, Dockerfile, full log
- **Real-time Updates** - See test progress as it happens

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| F1 | Run test |
| F2 | Load logs |
| F3 | View Dockerfile |
| F5 | Refresh |
| F10 or q | Exit |
| Tab | Next tab |
| Shift+Tab | Previous tab |
| ↑/↓ | Scroll |
| Page Up/Down | Fast scroll |
| Space | Select distribution |

### Mouse Actions

- **Click distribution** - Select/deselect
- **Click tab** - Switch view
- **Scroll wheel** - Scroll content

---

## 8. Troubleshooting

### Common Issues

#### Permission Denied
**Problem:** Cannot access podman socket
**Solution:** Run as root or add user to podman group
```bash
sudo usermod -aG podman $USER
```

#### Build Timeout
**Problem:** Tests timing out
**Solution:** Increase timeout value
```bash
mirror-test --timeout 1200 debian
```

#### Repository Connection Failed
**Problem:** Cannot connect to mirror
**Symptoms in logs:**
```
Err:1 http://10.10.0.15/debian bookworm InRelease
  Could not connect to 10.10.0.15:80
```
**Solution:** 
- Check mirror server is running
- Verify network connectivity
- Check firewall rules

#### No Space Left
**Problem:** Disk full during builds
**Solution:** Clean up old images
```bash
mirror-test cleanup
podman system prune -a
```

### Debug Mode

Enable verbose output for detailed debugging:
```bash
mirror-test --verbose debian 2>&1 | tee debug.log
```

### Log Files

Check logs for detailed error information:
```bash
# Latest log for a distribution
cat /var/log/mirror-test/debian_latest.log

# All logs
ls -la /var/log/mirror-test/
```

---

## 9. Examples

### Example 1: Basic Mirror Testing

```yaml
# /etc/mirror-test.yaml
variables:
  MIRROR_HOST: "192.168.1.100"
  MIRROR_BASE: "http://${MIRROR_HOST}"

debian:
  base-image: debian:12
  package-manager: apt
  sources:
    - "deb ${MIRROR_BASE}/debian bookworm main"
```

```bash
# Test the configuration
mirror-test debian
```

### Example 2: Multiple Mirrors with Failover

```yaml
variables:
  PRIMARY: "10.10.0.15"
  BACKUP: "10.10.0.16"
  
debian:
  sources:
    - "deb http://${PRIMARY}/debian bookworm main"
    - "deb http://${BACKUP}/debian bookworm main"
```

### Example 3: Custom Test Commands

```yaml
rocky-web-stack:
  base-image: rockylinux:9
  package-manager: dnf
  sources:
    - |
      [baseos]
      baseurl=${MIRROR_BASE}/rocky/9/BaseOS/x86_64/os/
      enabled=1
  test-commands:
    - "dnf install -y httpd mariadb-server php"
    - "httpd -v"
    - "mysql --version"
    - "php --version"
    - "echo 'LAMP stack validated'"
```

### Example 4: Minimal Quick Test

```yaml
alpine-minimal:
  base-image: alpine:3.19
  package-manager: apk
  sources:
    - "${MIRROR_BASE}/alpine/v3.19/main"
  test-commands:
    - "apk add --no-cache curl"
    - "echo 'Quick test passed'"
```

### Example 5: Environment-Specific Configuration

```bash
# Development environment
MIRROR_HOST=dev-mirror.local mirror-test

# Production environment  
MIRROR_HOST=prod-mirror.company.com mirror-test
```

---

## 10. Appendix

### A. Supported Package Managers

| Package Manager | Distributions | Update Command |
|----------------|---------------|----------------|
| apt | Debian, Ubuntu | apt-get update |
| yum | RHEL 7, CentOS 7 | yum makecache |
| dnf | RHEL 8+, Fedora, Rocky | dnf makecache |
| zypper | openSUSE, SLES | zypper refresh |
| apk | Alpine Linux | apk update |
| tdnf | VMware Photon | tdnf makecache |
| pacman | Arch Linux | pacman -Sy |

### B. Container Base Images

| Distribution | Recommended Image | Alternative Images |
|-------------|-------------------|-------------------|
| Debian 12 | debian:12 | debian:bookworm |
| Debian 11 | debian:11 | debian:bullseye |
| Ubuntu 22.04 | ubuntu:22.04 | ubuntu:jammy |
| Ubuntu 24.04 | ubuntu:24.04 | ubuntu:noble |
| Rocky Linux 9 | rockylinux:9 | rockylinux:9-minimal |
| AlmaLinux 9 | almalinux:9 | almalinux:9-minimal |
| Fedora 39 | fedora:39 | fedora:latest |
| openSUSE Leap | opensuse/leap:15.5 | opensuse/leap:latest |
| Alpine | alpine:3.19 | alpine:latest |

### C. File Locations

| Path | Description |
|------|-------------|
| `/etc/mirror-test.yaml` | Main configuration |
| `/var/log/mirror-test/` | Test logs |
| `/var/lib/mirror-test/builds/` | Dockerfiles |
| `/etc/bash_completion.d/mirror-test` | Autocomplete |
| `/etc/systemd/system/mirror-test-web.service` | Systemd service |

### D. Performance Tips

1. **Use minimal base images** - Reduce download time
2. **Limit test commands** - Only test what's necessary
3. **Run tests in parallel** - Use multiple terminal sessions
4. **Cache base images** - Pre-pull common images
5. **Use local DNS** - Reduce DNS lookup time

### E. Security Considerations

1. **Run as root carefully** - Required for podman but use with caution
2. **Validate mirror URLs** - Ensure HTTPS where possible
3. **Check GPG signatures** - Set `gpgcheck=1` in production
4. **Limit network access** - Use firewall rules for mirror servers
5. **Regular updates** - Keep base images and tools updated

---

## Quick Reference Card

```bash
# Essential Commands
mirror-test                    # Test all
mirror-test debian ubuntu      # Test specific
mirror-test gui                # Web interface
mirror-test cli                # Terminal interface
mirror-test cleanup            # Remove images

# Information
mirror-test list               # List distributions
mirror-test variables          # Show variables
mirror-test validate           # Check config
mirror-test help               # Full help

# Logs and Debugging
mirror-test logs debian        # View logs
mirror-test dockerfile debian  # Show Dockerfile
mirror-test --verbose debian   # Detailed output

# Common Options
--config /path/to/config.yaml  # Alt config
--port 8081                    # Alt port
--timeout 1200                 # Longer timeout
--no-cleanup                   # Keep images
```

---

**End of Manual** | Version 2.0.0 | January 2025
