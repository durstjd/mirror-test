# Mirror Test
**Version 2.2.0** | **September 2025**

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [Requirements](#2-requirements)
3. [Installation](#3-installation)
4. [Configuration](#4-configuration)
5. [Usage](#5-usage)
6. [Commands Reference](#6-commands-reference)
7. [Troubleshooting](#7-troubleshooting)
8. [Examples](#8-examples)
9. [Appendix](#9-appendix)

---

## 1. Introduction

Mirror Test is a comprehensive tool for validating local Linux repository mirrors. This modular version provides a clean, maintainable architecture with separate modules for core functionality, CLI interface, and web interface.

### Key Features
- **Modular Architecture** - Clean separation of concerns with independent modules
- **Multi-distribution support** - Test Debian, Ubuntu, RHEL, SUSE, Alpine, and more
- **Variable substitution** - Define mirror URLs once, use everywhere
- **Customizable tests** - Configure package manager commands and test packages
- **Modern web interface** - Responsive web GUI with real-time updates
- **Simple CLI interface** - Clean command-line interface for automation
- **Build status tracking** - Visual panels showing successful and failed builds
- **Automated cleanup** - No residual images left after testing
- **Comprehensive logging** - Detailed logs for debugging
- **Optional security features** - LDAPS authentication, API keys, audit logging
- **Graceful degradation** - Works with or without optional dependencies

### System Requirements
- Linux operating system
- Podman
- Python 3.8 or higher
- PyYAML library
- Root access (/etc/sub{uid,gid} configuration)
- Minimum 2GB RAM
- 10GB free disk space

### Project Structure
```
mirror-test/
├── __init__.py                    # Package initialization
├── main.py                       # Main entry point
├── config.py                     # Configuration management
├── core.py                       # Core testing functionality
├── cli.py                        # Command-line interface
├── web.py                        # Web interface
├── security.py                   # Security and authentication
├── setup.py                      # Package setup
├── requirements.txt              # Python dependencies
├── full-config-example.yaml      # Complete configuration example
├── server-config-example.yaml    # Server configuration example
├── bash-autocomplete.sh          # Bash completion script
├── build_linux.sh                # Linux build script
├── SSL-SETUP-GUIDE.md           # SSL setup instructions
└── README.md                     # This file
```

---

## 2. Requirements

### Core Dependencies (Required)
- **Python 3.8+** - Core runtime
- **PyYAML** - Configuration file parsing
- **Podman** - Container runtime for testing

### Web Interface Dependencies (Optional)
- **Flask** - Web framework
- **Flask-Limiter** - Rate limiting
- **Flask-WTF** - Form handling
- **Flask-CORS** - Cross-origin resource sharing

### Security Dependencies (Optional)
- **python-ldap** - LDAP authentication support

### Installation Methods
```bash
# Core installation only
pip install -r requirements.txt

# With all optional dependencies
pip install -e .[all]

# Development installation
pip install -e .
```

---

## 3. Installation

### From Release
```
mirror-test --install
```

### From Git
```
git clone https://github.com/durstjd/mirror-test.git
cd mirror-test
chmod +X build_linux.sh
./build_linux.sh
./dist/mirror-test --install
```

### From Source

```bash
# Clone the repository
git clone <repository-url>
cd mirror-test

# Install in development mode
pip install -e .

# Or install with all optional dependencies
pip install -e .[all]
```

### System Installation

```bash
# Install system-wide
sudo pip install -e .

# Install for current user only
pip install --user -e .
```

### Enable Bash Completion

```bash
# Copy completion script
sudo cp bash-autocomplete.sh /etc/bash_completion.d/mirror-test

# Reload bash completion
source /etc/bash_completion.d/mirror-test

# Test autocomplete
mirror-test <TAB><TAB>
```

### SSL Certificate Setup (Optional)

For LDAPS authentication and HTTPS web interface, see the [SSL Setup Guide](SSL-SETUP-GUIDE.md) for detailed instructions on:
- Adding LDAP server certificates to system trust store
- Configuring self-signed certificates for web interface
- Troubleshooting SSL certificate issues

---

## 4. Configuration

### Configuration File Structure

The configuration file `~/.config/mirror-test/mirror-test.yaml` has three main sections:

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
distributions:
  debian-12:
    base-image: "debian:12"
    package-manager: "apt"
    sources:
      - "deb ${MIRROR_BASE}/debian bookworm main"
      - "deb ${MIRROR_BASE}/debian bookworm-updates main"
      - "deb ${MIRROR_BASE}/debian-security bookworm-security main"
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
    baseurl=${MIRROR_BASE}/rhel/8/x86_64/baseos
    enabled=1
    gpgcheck=${GPG_CHECK}
```

#### Zypper (SUSE)
```yaml
sources:
  - |
    [main]
    name=Main Repository
    baseurl=${MIRROR_BASE}/sles/15/x86_64/
    enabled=1
    gpgcheck=${GPG_CHECK}
```

### Server Configuration (Optional)

For web interface with security features, create `~/.config/mirror-test/server-config.yaml`:

```yaml
# Web server settings
host: "0.0.0.0"
port: 5000
debug: false

# SSL settings (optional)
ssl_cert: "/path/to/cert.pem"
ssl_key: "/path/to/key.pem"

# Authentication settings (optional)
auth:
  enabled: false
  ldap_server: "ldap://ldap.company.com"
  ldap_base_dn: "dc=company,dc=com"
  ldap_user_dn: "cn=admin,dc=company,dc=com"
  ldap_password: "password"

# API settings
api:
  rate_limit: "100 per minute"
  api_keys:
    - "your-api-key-here"

# Security settings
security:
  audit_log: true
  ip_whitelist: []
  cors_origins: ["*"]
```

---

## 5. Usage

### Basic Commands

```bash
# Test all configured distributions
mirror-test

# Test specific distributions
mirror-test debian-12 ubuntu-22

# Launch web interface
mirror-test gui

# Launch interactive CLI
mirror-test cli

# List configured distributions
mirror-test list

# Show configuration variables
mirror-test variables

# Validate configuration
mirror-test validate

# Clean up Podman images
mirror-test cleanup
```

### Web Interface

```bash
# Start web server
mirror-test gui

# Start with custom port
mirror-test gui --port 9000

# Start with SSL
mirror-test gui --ssl-cert cert.pem --ssl-key key.pem

# Start with auto-open browser
mirror-test gui --open-browser
```

### Interactive CLI Mode

```bash
# Launch interactive CLI
mirror-test cli

# Available commands in CLI mode:
# - test <distribution> - Test specific distribution
# - test-all - Test all distributions
# - list - List configured distributions
# - logs <distribution> - View logs
# - dockerfile <distribution> - View generated containerfile
# - cleanup - Clean up images
# - exit - Exit CLI mode
```

---

## 6. Commands Reference

### Core Commands

| Command | Description | Options |
|---------|-------------|---------|
| `mirror-test` | Test all distributions | `--verbose`, `--config` |
| `mirror-test <dist>` | Test specific distribution | `--verbose`, `--config` |
| `mirror-test gui` | Launch web interface | `--port`, `--host`, `--ssl-cert`, `--ssl-key` |
| `mirror-test cli` | Launch interactive CLI | `--config` |
| `mirror-test list` | List configured distributions | `--config` |
| `mirror-test variables` | Show configuration variables | `--config` |
| `mirror-test validate` | Validate configuration | `--config` |
| `mirror-test cleanup` | Clean up Podman images | `--all` |
| `mirror-test logs <dist>` | View logs for distribution | `--config` |
| `mirror-test dockerfile <dist>` | View generated Containerfile | `--config` |
| `mirror-test refresh` | Refresh bash completion | |

### Web Interface Commands

| Command | Description |
|---------|-------------|
| `mirror-test gui` | Start web interface |
| `mirror-test gui --port 9000` | Start on custom port |
| `mirror-test gui --ssl-cert cert.pem --ssl-key key.pem` | Start with SSL |
| `mirror-test gui --open-browser` | Start and open browser |

### Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| `--config <file>` | Use custom config file | `~/.config/mirror-test/mirror-test.yaml` |
| `--verbose` | Enable verbose output | `False` |
| `--port <port>` | Web interface port | `5000` |
| `--host <host>` | Web interface host | `0.0.0.0` |
| `--ssl-cert <file>` | SSL certificate file | `None` |
| `--ssl-key <file>` | SSL private key file | `None` |
| `--open-browser` | Open browser automatically | `False` |

---

## 7. Troubleshooting

### Common Issues

#### Container Runtime Issues
```bash
# Check if Podman is running
podman info

# Test container creation
podman run --rm quay.io/podman/hello

# Check Podman version
podman version

# Check if user has proper subuid/subgid configuration
cat /etc/subuid
cat /etc/subgid
```

#### Permission Issues
```bash
# Check if user has proper subuid/subgid configuration
cat /etc/subuid | grep $USER
cat /etc/subgid | grep $USER

# If not configured, add user to subuid/subgid (requires root)
sudo usermod --add-subuids 100000-165535 $USER
sudo usermod --add-subgids 100000-165535 $USER

# Log out and back in, then test
podman run --rm quay.io/podman/hello
```

#### Configuration Issues
```bash
# Validate configuration
mirror-test validate

# Check configuration syntax
python -c "import yaml; yaml.safe_load(open('~/.config/mirror-test/mirror-test.yaml'))"

# Test specific distribution
mirror-test <distribution> --verbose
```

#### Web Interface Issues
```bash
# Check if port is available
netstat -tlnp | grep :5000

# Test with different port
mirror-test gui --port 9000

# Check Flask dependencies
python -c "import flask; print('Flask available')"
```

#### SSL Certificate Issues
```bash
# Check certificate validity
openssl x509 -in cert.pem -text -noout

# Test SSL connection
openssl s_client -connect localhost:5000 -servername localhost
```

### Debug Mode

Enable verbose output for detailed debugging:

```bash
# Test with verbose output
mirror-test --verbose

# Web interface with debug mode
FLASK_DEBUG=1 mirror-test gui
```

### Log Files

Logs are stored in:
- **CLI output**: Console output
- **Web interface**: Console output or log files
- **Container logs**: Available through Podman (`podman logs <container_id>`)

---

## 8. Examples

### Basic Configuration Example

```yaml
# ~/.config/mirror-test/mirror-test.yaml
variables:
  MIRROR_HOST: "mirror.company.com"
  MIRROR_PROTO: "https"
  MIRROR_BASE: "${MIRROR_PROTO}://${MIRROR_HOST}"
  GPG_CHECK: "1"

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

distributions:
  debian-12:
    base-image: "debian:12"
    package-manager: "apt"
    sources:
      - "deb ${MIRROR_BASE}/debian bookworm main contrib non-free"
      - "deb ${MIRROR_BASE}/debian bookworm-updates main contrib non-free"
      - "deb ${MIRROR_BASE}/debian-security bookworm-security main contrib non-free"
  
  ubuntu-22:
    base-image: "ubuntu:22.04"
    package-manager: "apt"
    sources:
      - "deb ${MIRROR_BASE}/ubuntu jammy main restricted universe multiverse"
      - "deb ${MIRROR_BASE}/ubuntu jammy-updates main restricted universe multiverse"
      - "deb ${MIRROR_BASE}/ubuntu jammy-security main restricted universe multiverse"
  
  rocky-8:
    base-image: "rockylinux:8"
    package-manager: "dnf"
    sources:
      - |
        [baseos]
        name=BaseOS
        baseurl=${MIRROR_BASE}/rocky/8/BaseOS/x86_64/os/
        enabled=1
        gpgcheck=${GPG_CHECK}
```

### Advanced Configuration Example

```yaml
# ~/.config/mirror-test/mirror-test.yaml
variables:
  MIRROR_HOST: "mirror.company.com"
  MIRROR_PROTO: "https"
  MIRROR_BASE: "${MIRROR_PROTO}://${MIRROR_HOST}"
  GPG_CHECK: "1"
  ARCH: "x86_64"

package-managers:
  apt:
    update-command: "apt-get update"
    test-commands:
      - "apt-get install -y --no-install-recommends curl wget build-essential"
      - "apt-cache stats"
      - "gcc --version"
      - "echo 'APT repository test successful'"
  
  dnf:
    update-command: "dnf makecache"
    test-commands:
      - "dnf install -y dnf-utils gcc make"
      - "dnf repolist --all"
      - "gcc --version"
      - "echo 'DNF repository test successful'"

distributions:
  debian-12:
    base-image: "debian:12"
    package-manager: "apt"
    sources:
      - "deb ${MIRROR_BASE}/debian bookworm main contrib non-free"
      - "deb ${MIRROR_BASE}/debian bookworm-updates main contrib non-free"
      - "deb ${MIRROR_BASE}/debian-security bookworm-security main contrib non-free"
    # Override test commands for this distribution
    test-commands:
      - "apt-get install -y build-essential"
      - "gcc --version"
      - "make --version"
      - "echo 'Debian 12 build tools test successful'"
  
  ubuntu-22:
    base-image: "ubuntu:22.04"
    package-manager: "apt"
    sources:
      - "deb ${MIRROR_BASE}/ubuntu jammy main restricted universe multiverse"
      - "deb ${MIRROR_BASE}/ubuntu jammy-updates main restricted universe multiverse"
      - "deb ${MIRROR_BASE}/ubuntu jammy-security main restricted universe multiverse"
  
  rocky-8:
    base-image: "rockylinux:8"
    package-manager: "dnf"
    sources:
      - |
        [baseos]
        name=BaseOS
        baseurl=${MIRROR_BASE}/rocky/8/BaseOS/${ARCH}/os/
        enabled=1
        gpgcheck=${GPG_CHECK}
        
        [appstream]
        name=AppStream
        baseurl=${MIRROR_BASE}/rocky/8/AppStream/${ARCH}/os/
        enabled=1
        gpgcheck=${GPG_CHECK}
```

### Web Interface with Security

```yaml
# ~/.config/mirror-test/server-config.yaml
host: "0.0.0.0"
port: 5000
debug: false

# SSL settings
ssl_cert: "/etc/ssl/certs/mirror-test.crt"
ssl_key: "/etc/ssl/private/mirror-test.key"

# Authentication settings
auth:
  enabled: true
  ldap_server: "ldaps://ldap.company.com:636"
  ldap_base_dn: "dc=company,dc=com"
  ldap_user_dn: "cn=admin,dc=company,dc=com"
  ldap_password: "secure-password"

# API settings
api:
  rate_limit: "100 per minute"
  api_keys:
    - "your-secure-api-key-here"

# Security settings
security:
  audit_log: true
  ip_whitelist: ["10.0.0.0/8", "192.168.0.0/16"]
  cors_origins: ["https://mirror.company.com"]
```

---

## 9. Appendix

### Module Architecture

#### Core Modules
- **`config.py`**: Configuration management and validation
- **`core.py`**: Core mirror testing functionality using containers
- **`security.py`**: Security features including LDAP authentication

#### Interface Modules
- **`cli.py`**: Command-line interface and interactive mode
- **`web.py`**: Flask web interface and API endpoints
- **`main.py`**: Main entry point and argument parsing

### Key Classes

#### ConfigManager
Handles YAML configuration loading and validation:
```python
from config import ConfigManager

config = ConfigManager('~/.config/mirror-test/mirror-test.yaml')
distributions = config.get_distributions()
variables = config.get_variables()
```

#### MirrorTester
Core testing functionality using Podman containers:
```python
from core import MirrorTester

tester = MirrorTester(config)
result = tester.test_distribution('debian-12')
```

#### WebInterface
Flask web application:
```python
from web import WebInterface

app = WebInterface(config)
app.run(host='0.0.0.0', port=5000)
```

### Building Executables

#### Quick Build
```bash
# Linux build
./build_linux.sh
```

#### Manual Build
```bash
# Install PyInstaller
pip install pyinstaller

# Build executable
pyinstaller --onefile --name mirror-test --strip \
    --exclude-module tkinter --exclude-module matplotlib \
    --exclude-module numpy --exclude-module pandas \
    --hidden-import flask --hidden-import flask_limiter \
    --hidden-import flask_wtf --hidden-import flask_cors \
    main.py
```

### Development

#### Running Tests
```bash
# Test core functionality
python -m mirror_test.core

# Test CLI interface
python -m mirror_test.cli

# Test web interface
python -m mirror_test.web
```

#### Debug Mode
```bash
# Enable Flask debug mode
export FLASK_DEBUG=1
mirror-test gui

# Enable verbose output
mirror-test --verbose
```

### License

MIT License - see LICENSE file for details.

### Support

For issues and questions:
- Check the troubleshooting section above
- Review configuration examples
- Enable verbose output for debugging
- Check Podman container logs (`podman logs <container_id>`)

---

**Mirror Test - Modular Version v2.2.0**  
*September 2025*