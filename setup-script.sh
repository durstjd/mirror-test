#!/bin/bash
# setup-mirror-test.sh - Installation script for mirror-test tool
# Version 2.0.0 - With autocomplete and enhanced features

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[+]${NC} $1"
}

print_error() {
    echo -e "${RED}[!]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[*]${NC} $1"
}

print_info() {
    echo -e "${BLUE}[i]${NC} $1"
}

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   print_error "This script must be run as root"
   exit 1
fi

print_status "Starting mirror-test installation (v2.0.0)..."

# Detect distribution
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
    VER=$VERSION_ID
else
    print_error "Cannot detect operating system"
    exit 1
fi

# Install dependencies based on distribution
print_status "Installing dependencies for $OS..."

case $OS in
    debian|ubuntu)
        apt-get update
        apt-get install -y python3 python3-yaml python3-pip podman
        # podman-docker is not always available in Debian/Ubuntu repos
        if apt-cache show podman-docker &>/dev/null; then
            apt-get install -y podman-docker
        else
            print_warning "podman-docker not available, creating alias instead"
            ln -sf /usr/bin/podman /usr/bin/docker || true
        fi
        # Install bash-completion if not present
        apt-get install -y bash-completion
        ;;
    
    fedora)
        dnf install -y python3 python3-pyyaml podman podman-docker bash-completion
        ;;
    
    rhel|centos|rocky|almalinux)
        dnf install -y python3 python3-pyyaml podman podman-docker bash-completion
        # For RHEL/CentOS 7
        if [ "$VER" == "7" ]; then
            yum install -y python3 python3-pyyaml podman bash-completion
        fi
        ;;
    
    opensuse*)
        zypper install -y python3 python3-PyYAML podman bash-completion
        ;;
    
    alpine)
        apk add python3 py3-yaml podman bash-completion
        ;;
    
    arch|manjaro)
        pacman -Sy --noconfirm python python-yaml podman bash-completion
        ;;
    
    *)
        print_error "Unsupported distribution: $OS"
        print_warning "Please install manually: python3, python3-yaml, podman, podman-docker, bash-completion"
        exit 1
        ;;
esac

# Create necessary directories
print_status "Creating directories..."
mkdir -p /etc
mkdir -p /var/log/mirror-test
mkdir -p /var/lib/mirror-test/builds
mkdir -p /usr/bin
mkdir -p /usr/share/man/man1
mkdir -p /etc/bash_completion.d

# Install the main script
print_status "Installing mirror-test executable..."
if [ -f "mirror-test" ]; then
    cp mirror-test /usr/bin/mirror-test
elif [ -f "mirror-test.py" ]; then
    cp mirror-test.py /usr/bin/mirror-test
else
    print_error "mirror-test executable not found in current directory"
    print_warning "Please copy the Python script to /usr/bin/mirror-test manually"
fi

chmod +x /usr/bin/mirror-test

# Install bash completion
print_status "Installing bash completion..."
cat > /etc/bash_completion.d/mirror-test << 'EOF'
# Bash completion for mirror-test
_mirror_test_completions() {
    local cur prev opts base_commands distributions
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    
    base_commands="all gui cli logs dockerfile cleanup list variables validate help"
    opts="--config --port --verbose --quiet --timeout --no-cleanup --version --help -v -q -h"
    
    config_file="/etc/mirror-test.yaml"
    if [[ -f "$config_file" ]]; then
        distributions=$(grep -E '^[a-zA-Z]' "$config_file" | \
                       grep -v '^variables:' | \
                       grep -v '^package-managers:' | \
                       sed 's/:.*//' | \
                       grep -v '^#' | \
                       sort -u | \
                       tr '\n' ' ')
    else
        distributions="debian ubuntu rocky almalinux fedora centos opensuse alpine"
    fi
    
    case "${prev}" in
        mirror-test)
            COMPREPLY=( $(compgen -W "${base_commands} ${distributions} ${opts}" -- ${cur}) )
            return 0
            ;;
        --config)
            COMPREPLY=( $(compgen -f -X '!*.yaml' -- ${cur}) )
            COMPREPLY+=( $(compgen -f -X '!*.yml' -- ${cur}) )
            return 0
            ;;
        --port)
            COMPREPLY=( $(compgen -W "8080 8081 8082 3000 5000 9090" -- ${cur}) )
            return 0
            ;;
        --timeout)
            COMPREPLY=( $(compgen -W "300 600 900 1200 1800" -- ${cur}) )
            return 0
            ;;
        logs|dockerfile)
            COMPREPLY=( $(compgen -W "${distributions}" -- ${cur}) )
            return 0
            ;;
        *)
            COMPREPLY=( $(compgen -W "${base_commands} ${distributions} ${opts}" -- ${cur}) )
            return 0
            ;;
    esac
}
complete -F _mirror_test_completions mirror-test
complete -F _mirror_test_completions mt
EOF

# Create default configuration if it doesn't exist
if [ ! -f /etc/mirror-test.yaml ]; then
    print_status "Creating default configuration..."
    cat > /etc/mirror-test.yaml << 'EOF'
# mirror-test configuration file
# Please update with your local mirror URLs

variables:
  MIRROR_HOST: "mirror.local"
  MIRROR_PROTO: "http"
  MIRROR_BASE: "${MIRROR_PROTO}://${MIRROR_HOST}"

package-managers:
  apt:
    update-command: "apt-get update"
    test-commands:
      - "apt-get install -y --no-install-recommends apt-utils curl"
      - "echo 'APT repository test successful'"
  
  yum:
    update-command: "yum makecache"
    test-commands:
      - "yum install -y yum-utils curl"
      - "echo 'YUM repository test successful'"
  
  dnf:
    update-command: "dnf makecache"
    test-commands:
      - "dnf install -y dnf-utils curl"
      - "echo 'DNF repository test successful'"

debian:
  base-image: debian:12
  package-manager: apt
  sources:
    - "deb ${MIRROR_BASE}/debian bookworm main contrib non-free non-free-firmware"

ubuntu:
  base-image: ubuntu:22.04
  package-manager: apt
  sources:
    - "deb ${MIRROR_BASE}/ubuntu jammy main restricted universe multiverse"

rocky:
  base-image: rockylinux:9
  package-manager: dnf
  sources:
    - |
      [mirror]
      name=Mirror Repository
      baseurl=${MIRROR_BASE}/rocky/9/BaseOS/x86_64/os/
      enabled=1
      gpgcheck=0
EOF
    print_warning "Default configuration created at /etc/mirror-test.yaml"
    print_warning "Please edit it with your local mirror URLs"
fi

# Install systemd service
print_status "Installing systemd service..."
cat > /etc/systemd/system/mirror-test-web.service << 'EOF'
[Unit]
Description=Mirror Test Web Interface
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/bin/mirror-test gui
Restart=on-failure
RestartSec=10
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

# Enable podman socket (required for some operations)
print_status "Enabling podman socket..."
systemctl enable --now podman.socket 2>/dev/null || true

# Create convenience aliases
print_status "Creating convenience aliases..."
cat > /etc/profile.d/mirror-test.sh << 'EOF'
# mirror-test aliases
alias mt='mirror-test'
alias mt-gui='mirror-test gui'
alias mt-cli='mirror-test cli'
alias mt-test='mirror-test all'
alias mt-clean='mirror-test cleanup'
EOF

# Set up log rotation
print_status "Setting up log rotation..."
cat > /etc/logrotate.d/mirror-test << 'EOF'
/var/log/mirror-test/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0644 root root
}
EOF

# Create man page
print_status "Creating man page..."
cat > /usr/share/man/man1/mirror-test.1 << 'EOF'
.TH MIRROR-TEST 1 "January 2025" "Version 2.0.0" "Mirror Test Manual"
.SH NAME
mirror-test \- Test local repository mirrors for Linux distributions
.SH SYNOPSIS
.B mirror-test
[\fIOPTIONS\fR] [\fICOMMAND\fR] [\fIDISTRIBUTIONS\fR...]
.SH DESCRIPTION
Tests repository mirrors by building Docker/Podman containers with custom repository configurations.
.SH COMMANDS
.TP
.B all
Test all configured distributions (default)
.TP
.B gui
Launch web interface
.TP
.B cli
Launch terminal interface with mouse support
.TP
.B logs \fIDIST\fR
Show latest test logs for a distribution
.TP
.B dockerfile \fIDIST\fR
Display generated Dockerfile
.TP
.B cleanup
Remove all mirror-test container images
.TP
.B list
List all configured distributions
.TP
.B variables
Show configured variables
.TP
.B validate
Validate configuration file syntax
.TP
.B help
Show help message
.SH OPTIONS
.TP
.B \-\-config \fIFILE\fR
Use alternate configuration file
.TP
.B \-\-port \fIPORT\fR
Set port for web interface (default: 8080)
.TP
.B \-v, \-\-verbose
Enable verbose output
.TP
.B \-q, \-\-quiet
Suppress non-error output
.TP
.B \-\-timeout \fISECONDS\fR
Set build timeout (default: 600)
.TP
.B \-\-no\-cleanup
Don't remove images after testing
.TP
.B \-\-version
Show version information
.TP
.B \-h, \-\-help
Show help message
.SH FILES
.TP
.I /etc/mirror-test.yaml
Main configuration file
.TP
.I /var/log/mirror-test/
Test logs directory
.TP
.I /var/lib/mirror-test/builds/
Dockerfile storage directory
.SH EXIT STATUS
.TP
.B 0
All tests passed successfully
.TP
.B 1
One or more tests failed
.TP
.B 2
Configuration error
.TP
.B 3
System requirements not met
.SH EXAMPLES
.TP
Test all distributions:
.B mirror-test
.TP
Test specific distributions:
.B mirror-test debian ubuntu
.TP
Launch web interface:
.B mirror-test gui
.TP
View logs:
.B mirror-test logs debian
.SH AUTHOR
Created for testing local Linux repository mirrors
.SH SEE ALSO
podman(1), docker(1), dockerfile(5)
EOF

# Test installation
print_status "Testing installation..."
if /usr/bin/mirror-test --version &>/dev/null; then
    print_status "Installation successful!"
else
    print_error "Installation test failed"
    print_warning "Trying to fix Python dependencies..."
    pip3 install pyyaml 2>/dev/null || true
fi

# Reload bash completion
print_status "Reloading bash completion..."
if [ -f /etc/bash_completion ]; then
    . /etc/bash_completion
elif [ -f /usr/share/bash-completion/bash_completion ]; then
    . /usr/share/bash-completion/bash_completion
fi

# Print summary
echo
echo "======================================"
echo -e "${GREEN}Installation Complete!${NC}"
echo "======================================"
echo
echo "Version: 2.0.0"
echo "Config:  /etc/mirror-test.yaml"
echo "Logs:    /var/log/mirror-test/"
echo "Builds:  /var/lib/mirror-test/builds/"
echo
echo "Quick Start:"
echo "1. Edit configuration: nano /etc/mirror-test.yaml"
echo "2. Set your mirror:    Update MIRROR_HOST variable"
echo "3. Test mirrors:       mirror-test"
echo "4. View results:       mirror-test gui  (or cli for terminal)"
echo
echo "Commands:"
echo "  mirror-test              - Test all distributions"
echo "  mirror-test debian       - Test specific distribution"
echo "  mirror-test gui          - Web interface (http://localhost:8080)"
echo "  mirror-test cli          - Terminal interface with mouse"
echo "  mirror-test logs debian  - View test logs"
echo "  mirror-test help         - Show detailed help"
echo
echo "Autocomplete: Press TAB after typing 'mirror-test' for suggestions"
echo
echo "Aliases available:"
echo "  mt         - Short for mirror-test"
echo "  mt-gui     - Launch GUI"
echo "  mt-cli     - Launch CLI"
echo "  mt-test    - Test all"
echo "  mt-clean   - Clean images"
echo
echo "To enable the web service permanently:"
echo "  systemctl enable --now mirror-test-web"
echo
print_info "Tip: Source /etc/profile.d/mirror-test.sh or restart shell for aliases"#!/bin/bash
# setup-mirror-test.sh - Installation script for mirror-test tool

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[+]${NC} $1"
}

print_error() {
    echo -e "${RED}[!]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[*]${NC} $1"
}

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   print_error "This script must be run as root"
   exit 1
fi

print_status "Starting mirror-test installation..."

# Detect distribution
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
    VER=$VERSION_ID
else
    print_error "Cannot detect operating system"
    exit 1
fi

# Install dependencies based on distribution
print_status "Installing dependencies for $OS..."

case $OS in
    debian|ubuntu)
        apt-get update
        apt-get install -y python3 python3-yaml podman
        # podman-docker is not always available in Debian/Ubuntu repos
        if apt-cache show podman-docker &>/dev/null; then
            apt-get install -y podman-docker
        else
            print_warning "podman-docker not available, creating alias instead"
            ln -sf /usr/bin/podman /usr/bin/docker || true
        fi
        ;;
    
    fedora)
        dnf install -y python3 python3-pyyaml podman podman-docker
        ;;
    
    rhel|centos|rocky|almalinux)
        dnf install -y python3 python3-pyyaml podman podman-docker
        # For RHEL/CentOS 7
        if [ "$VER" == "7" ]; then
            yum install -y python3 python3-pyyaml podman
        fi
        ;;
    
    opensuse*)
        zypper install -y python3 python3-PyYAML podman
        ;;
    
    alpine)
        apk add python3 py3-yaml podman
        ;;
    
    *)
        print_error "Unsupported distribution: $OS"
        print_warning "Please install manually: python3, python3-yaml, podman, podman-docker"
        exit 1
        ;;
esac

# Create necessary directories
print_status "Creating directories..."
mkdir -p /etc
mkdir -p /var/log/mirror-test
mkdir -p /usr/bin

# Install the main script
print_status "Installing mirror-test executable..."
if [ -f "mirror-test" ]; then
    cp mirror-test /usr/bin/mirror-test
else
    print_error "mirror-test executable not found in current directory"
    print_warning "Please copy the Python script to /usr/bin/mirror-test manually"
fi

chmod +x /usr/bin/mirror-test

# Create default configuration if it doesn't exist
if [ ! -f /etc/mirror-test.yaml ]; then
    print_status "Creating default configuration..."
    cat > /etc/mirror-test.yaml << 'EOF'
# Default mirror-test configuration
# Please update with your local mirror URLs

debian:
  pull: debian:12
  source-path: /etc/apt/sources.list
  sources:
    - "deb http://deb.debian.org/debian bookworm main contrib non-free non-free-firmware"

ubuntu:
  pull: ubuntu:22.04
  source-path: /etc/apt/sources.list
  sources:
    - "deb http://archive.ubuntu.com/ubuntu jammy main restricted universe multiverse"

rocky:
  pull: rockylinux:9
  source-path: /etc/yum.repos.d/mirror.repo
  sources:
    - |
      [mirror]
      name=Mirror Repository
      baseurl=http://mirror.local/rocky/9/BaseOS/x86_64/os/
      enabled=1
      gpgcheck=0
EOF
    print_warning "Default configuration created at /etc/mirror-test.yaml"
    print_warning "Please edit it with your local mirror URLs"
fi

# Install systemd service
print_status "Installing systemd service..."
cat > /etc/systemd/system/mirror-test-web.service << 'EOF'
[Unit]
Description=Mirror Test Web Interface
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/bin/mirror-test gui
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload

# Enable podman socket (required for some operations)
print_status "Enabling podman socket..."
systemctl enable --now podman.socket || true

# Create a simple wrapper script for convenience
print_status "Creating wrapper script..."
cat > /usr/local/bin/mirror-test-all << 'EOF'
#!/bin/bash
# Quick test all mirrors
echo "Testing all configured mirrors..."
/usr/bin/mirror-test all
EOF
chmod +x /usr/local/bin/mirror-test-all

# Set up log rotation
print_status "Setting up log rotation..."
cat > /etc/logrotate.d/mirror-test << 'EOF'
/var/log/mirror-test/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0644 root root
}
EOF

# Test installation
print_status "Testing installation..."
if /usr/bin/mirror-test --help &>/dev/null; then
    print_status "Installation successful!"
else
    print_error "Installation test failed"
    exit 1
fi

# Print summary
echo
echo "======================================"
echo -e "${GREEN}Installation Complete!${NC}"
echo "======================================"
echo
echo "Next steps:"
echo "1. Edit /etc/mirror-test.yaml with your mirror URLs"
echo "2. Run 'mirror-test' to test all mirrors"
echo "3. Run 'mirror-test gui' to start the web interface"
echo "4. Or enable the web service: systemctl enable --now mirror-test-web"
echo
echo "Commands:"
echo "  mirror-test              - Test all distributions"
echo "  mirror-test debian       - Test specific distribution"
echo "  mirror-test gui          - Start web interface"
echo "  mirror-test logs debian  - View logs for distribution"
echo
echo "Web interface will be available at: http://localhost:8080"
echo