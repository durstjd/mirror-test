#!/bin/bash
# setup-mirror-test.sh - Installation script for mirror-test tool
# Version 2.0.0 - With autocomplete and enhanced features
#
# This script supports both system-wide (root) and user-level installation.
# User-level installation is recommended as it requires no root privileges
# and works with user-level Podman.

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

# Check if running as root (optional for user-level installation)
if [[ $EUID -eq 0 ]]; then
   print_warning "Running as root - installing system-wide"
   INSTALL_MODE="system"
else
   print_status "Running as user - installing user-level (recommended)"
   print_info "User-level installation requires no root privileges and works with user-level Podman"
   INSTALL_MODE="user"
fi

print_status "Starting mirror-test installation (v2.0.0)..."

# Function to check Python version
check_python_version() {
    local python_cmd="$1"
    local version_output
    local major_version
    local minor_version
    
    if ! command -v "$python_cmd" &> /dev/null; then
        return 1
    fi
    
    # Get Python version
    version_output=$($python_cmd --version 2>&1)
    if [[ $version_output =~ Python\ ([0-9]+)\.([0-9]+) ]]; then
        major_version=${BASH_REMATCH[1]}
        minor_version=${BASH_REMATCH[2]}
        
        # Check if version is 3.8 or greater
        if [ "$major_version" -eq 3 ] && [ "$minor_version" -ge 8 ]; then
            return 0
        elif [ "$major_version" -gt 3 ]; then
            return 0
        else
            return 1
        fi
    else
        return 1
    fi
}

# Function to find alternative Python versions
find_alternative_python() {
    local alternatives=()
    local python_commands=("python3" "python3.11" "python3.10" "python3.9" "python3.8" "python" "python3.12" "python3.13")
    
    for cmd in "${python_commands[@]}"; do
        if check_python_version "$cmd"; then
            alternatives+=("$cmd")
        fi
    done
    
    printf '%s\n' "${alternatives[@]}"
}

# Check Python version
print_status "Checking Python version..."

# Check if user specified a Python command via environment variable
if [ -n "$PYTHON_CMD" ]; then
    if check_python_version "$PYTHON_CMD"; then
        print_status "Using user-specified Python: $PYTHON_CMD ($($PYTHON_CMD --version))"
    else
        print_error "User-specified Python command '$PYTHON_CMD' is not Python 3.8 or greater"
        print_warning "Current version: $($PYTHON_CMD --version 2>&1)"
        exit 1
    fi
else
    # Try different Python commands in order of preference
    python_commands=("python3" "python" "python3.11" "python3.10" "python3.9" "python3.8")
    PYTHON_CMD=""

    for cmd in "${python_commands[@]}"; do
        if check_python_version "$cmd"; then
            PYTHON_CMD="$cmd"
            print_status "Found Python $($cmd --version) at $cmd"
            break
        fi
    done
fi

if [ -z "$PYTHON_CMD" ]; then
    print_error "Python 3.8 or greater is required but not found"
    print_warning "Current Python versions found:"
    
    # Check what Python versions are available
    for cmd in python3 python python3.11 python3.10 python3.9 python3.8 python3.7 python3.6; do
        if command -v "$cmd" &> /dev/null; then
            version=$($cmd --version 2>&1)
            print_warning "  $cmd: $version"
        fi
    done
    
    echo
    print_info "To use a different version of Python:"
    print_info "1. Install Python 3.8+ using your package manager:"
    case $OS in
        debian|ubuntu) 
            echo "    sudo apt-get install python3.8 python3.8-venv python3.8-dev"
            echo "    # Or for newer versions:"
            echo "    sudo apt-get install python3.11 python3.11-venv python3.11-dev"
            ;;
        fedora|rhel|centos|rocky|almalinux) 
            echo "    sudo dnf install python3.8 python3.8-devel"
            echo "    # Or for newer versions:"
            echo "    sudo dnf install python3.11 python3.11-devel"
            ;;
        opensuse*) 
            echo "    sudo zypper install python38 python38-devel"
            echo "    # Or for newer versions:"
            echo "    sudo zypper install python311 python311-devel"
            ;;
        alpine) 
            echo "    sudo apk add python3.8 python3.8-dev"
            echo "    # Or for newer versions:"
            echo "    sudo apk add python3.11 python3.11-dev"
            ;;
        arch|manjaro) 
            echo "    sudo pacman -S python python-pip"
            ;;
    esac
    
    print_info "2. Use update-alternatives to manage multiple Python versions:"
    echo "    sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.8 1"
    echo "    sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 2"
    echo "    sudo update-alternatives --config python3"
    
    print_info "3. Or use pyenv to manage Python versions (no sudo required):"
    echo "    curl https://pyenv.run | bash"
    echo "    pyenv install 3.11.0"
    echo "    pyenv global 3.11.0"
    
    print_info "4. Or specify a specific Python version when running this script:"
    echo "    PYTHON_CMD=python3.11 ./setup-script.sh"
    
    echo
    print_error "Installation cannot proceed with Python 3.6 or older"
    exit 1
fi

# Check if the found Python version is 3.6 or older (shouldn't happen due to check above, but extra safety)
python_version=$($PYTHON_CMD --version 2>&1)
if [[ $python_version =~ Python\ ([0-9]+)\.([0-9]+) ]]; then
    major_version=${BASH_REMATCH[1]}
    minor_version=${BASH_REMATCH[2]}
    
    if [ "$major_version" -eq 3 ] && [ "$minor_version" -le 6 ]; then
        print_error "Python 3.6 or older detected: $python_version"
        print_error "Python 3.8 or greater is required"
        exit 1
    fi
fi

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

if [ "$INSTALL_MODE" = "system" ]; then
    # System-wide installation
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
            print_info "Web interface uses built-in Python http.server module"
            exit 1
            ;;
    esac
    
    # Web interface uses built-in Python http.server module - no additional installation needed
    print_status "Web interface uses built-in Python http.server module - no additional dependencies needed"
else
    # User-level installation - check if dependencies are available
    print_status "Checking for required dependencies..."
    
    # Check for Python
    if ! command -v python3 &> /dev/null; then
        print_error "Python3 is not installed. Please install it first:"
        print_info "You can install Python3 using one of these methods:"
        case $OS in
            debian|ubuntu) 
                echo "  System package manager (requires sudo):"
                echo "    sudo apt-get install python3 python3-yaml python3-pip"
                echo "    # Web interface uses built-in Python http.server module"
                echo "  Or use pyenv (no sudo required):"
                echo "    curl https://pyenv.run | bash"
                echo "    pyenv install 3.11.0 && pyenv global 3.11.0"
                echo "    # Web interface uses built-in Python http.server module"
                ;;
            fedora|rhel|centos|rocky|almalinux) 
                echo "  System package manager (requires sudo):"
                echo "    sudo dnf install python3 python3-pyyaml python3-pip"
                echo "    # Web interface uses built-in Python http.server module"
                echo "  Or use pyenv (no sudo required):"
                echo "    curl https://pyenv.run | bash"
                echo "    pyenv install 3.11.0 && pyenv global 3.11.0"
                echo "    # Web interface uses built-in Python http.server module"
                ;;
            opensuse*) 
                echo "  System package manager (requires sudo):"
                echo "    sudo zypper install python3 python3-PyYAML python3-pip"
                echo "    # Web interface uses built-in Python http.server module"
                echo "  Or use pyenv (no sudo required):"
                echo "    curl https://pyenv.run | bash"
                echo "    pyenv install 3.11.0 && pyenv global 3.11.0"
                echo "    # Web interface uses built-in Python http.server module"
                ;;
            alpine) 
                echo "  System package manager (requires sudo):"
                echo "    sudo apk add python3 py3-yaml python3-pip"
                echo "    # Web interface uses built-in Python http.server module"
                ;;
            arch|manjaro) 
                echo "  System package manager (requires sudo):"
                echo "    sudo pacman -S python python-yaml python-pip"
                echo "    # Web interface uses built-in Python http.server module"
                echo "  Or use pyenv (no sudo required):"
                echo "    curl https://pyenv.run | bash"
                echo "    pyenv install 3.11.0 && pyenv global 3.11.0"
                echo "    # Web interface uses built-in Python http.server module"
                ;;
        esac
        exit 1
    fi
    
    # Check for podman
    if ! command -v podman &> /dev/null; then
        print_error "Podman is not installed. Please install it first:"
        print_info "You can install Podman using one of these methods:"
        case $OS in
            debian|ubuntu) 
                echo "  System package manager (requires sudo):"
                echo "    sudo apt-get install podman"
                echo "  Or install via snap (no sudo required):"
                echo "    snap install podman"
                echo "  Or use the official installer script:"
                echo "    curl -s https://raw.githubusercontent.com/containers/podman/main/contrib/podmanimage/stable/install_podman.sh | bash"
                ;;
            fedora|rhel|centos|rocky|almalinux) 
                echo "  System package manager (requires sudo):"
                echo "    sudo dnf install podman"
                echo "  Or use the official installer script:"
                echo "    curl -s https://raw.githubusercontent.com/containers/podman/main/contrib/podmanimage/stable/install_podman.sh | bash"
                ;;
            opensuse*) 
                echo "  System package manager (requires sudo):"
                echo "    sudo zypper install podman"
                echo "  Or use the official installer script:"
                echo "    curl -s https://raw.githubusercontent.com/containers/podman/main/contrib/podmanimage/stable/install_podman.sh | bash"
                ;;
            alpine) 
                echo "  System package manager (requires sudo):"
                echo "    sudo apk add podman"
                ;;
            arch|manjaro) 
                echo "  System package manager (requires sudo):"
                echo "    sudo pacman -S podman"
                echo "  Or use the official installer script:"
                echo "    curl -s https://raw.githubusercontent.com/containers/podman/main/contrib/podmanimage/stable/install_podman.sh | bash"
                ;;
        esac
        exit 1
    fi
    
    # Check for PyYAML
    if ! $PYTHON_CMD -c "import yaml" 2>/dev/null; then
        print_warning "PyYAML not found, installing via pip (user-level)..."
        $PYTHON_CMD -m pip install --user pyyaml
        if [ $? -ne 0 ]; then
            print_error "Failed to install PyYAML. Please install it manually:"
            echo "  $PYTHON_CMD -m pip install --user pyyaml"
            echo "  Or with system package manager:"
            case $OS in
                debian|ubuntu) echo "    sudo apt-get install python3-yaml" ;;
                fedora|rhel|centos|rocky|almalinux) echo "    sudo dnf install python3-pyyaml" ;;
                opensuse*) echo "    sudo zypper install python3-PyYAML" ;;
                alpine) echo "    sudo apk add py3-yaml" ;;
                arch|manjaro) echo "    sudo pacman -S python-yaml" ;;
            esac
            exit 1
        fi
    fi
    
    # Web interface uses built-in Python http.server module - no additional dependencies needed
    print_status "Web interface uses built-in Python http.server module - no additional dependencies needed"
    
    print_status "All dependencies found!"
    print_info "User-level installation will create files in:"
    print_info "  Config: ~/.config/mirror-test/"
    print_info "  Logs: ~/mirror-test/logs/"
    print_info "  Builds: ~/mirror-test/builds/"
    print_info "  Binaries: ~/.local/bin/"
    print_warning "Note: Make sure ~/.local/bin is in your PATH:"
    print_warning "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc"
    print_warning "  source ~/.bashrc"
fi

# Create necessary directories
print_status "Creating directories..."

if [ "$INSTALL_MODE" = "system" ]; then
    # System-wide directories
    mkdir -p /etc
    mkdir -p /var/log/mirror-test
    mkdir -p /var/lib/mirror-test/builds
    mkdir -p /usr/bin
    mkdir -p /usr/share/man/man1
    mkdir -p /etc/bash_completion.d
    
    # Set configuration and log paths
    CONFIG_DIR="/etc"
    LOG_DIR="/var/log/mirror-test"
    BUILD_DIR="/var/lib/mirror-test/builds"
    BIN_DIR="/usr/bin"
    MAN_DIR="/usr/share/man/man1"
    COMPLETION_DIR="/etc/bash_completion.d"
    PROFILE_DIR="/etc/profile.d"
else
    # User-level directories
    mkdir -p ~/.config/mirror-test
    mkdir -p ~/mirror-test/logs
    mkdir -p ~/mirror-test/builds
    mkdir -p ~/.local/bin
    mkdir -p ~/.local/share/man/man1
    mkdir -p ~/.bash_completion.d
    
    # Set configuration and log paths
    CONFIG_DIR="$HOME/.config/mirror-test"
    LOG_DIR="$HOME/mirror-test/logs"
    BUILD_DIR="$HOME/mirror-test/builds"
    BIN_DIR="$HOME/.local/bin"
    MAN_DIR="$HOME/.local/share/man/man1"
    COMPLETION_DIR="$HOME/.bash_completion.d"
    PROFILE_DIR="$HOME/.config/mirror-test"
    mkdir -p "$PROFILE_DIR"
fi

# Install the main script
print_status "Installing mirror-test executable..."
if [ -f "mirror-test" ]; then
    cp mirror-test "$BIN_DIR/mirror-test"
elif [ -f "mirror-test.py" ]; then
    # Copy the Python script and update the shebang to use the detected Python command
    cp mirror-test.py "$BIN_DIR/mirror-test"
    # Update the shebang to use the detected Python command
    sed -i "1s|#!/usr/bin/env python3|#!/usr/bin/env $PYTHON_CMD|" "$BIN_DIR/mirror-test"
    print_info "Updated shebang to use $PYTHON_CMD"
else
    print_error "mirror-test executable not found in current directory"
    print_warning "Please copy the Python script to $BIN_DIR/mirror-test manually"
fi

chmod +x "$BIN_DIR/mirror-test"

# Create mt-cli wrapper
print_status "Creating mt-cli wrapper..."
if [ -f "mt-cli" ]; then
    cp mt-cli "$BIN_DIR/mt-cli"
    chmod +x "$BIN_DIR/mt-cli"
fi

# Install bash completion
print_status "Installing bash completion..."
cat > "$COMPLETION_DIR/mirror-test" << 'EOF'
# Bash completion for mirror-test
_mirror_test_completions() {
    local cur prev opts base_commands distributions
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    
    base_commands="all gui cli refresh logs dockerfile cleanup list variables validate help"
    opts="--config --port --verbose --quiet --timeout --no-cleanup --version --help -v -q -h"
    
    # Get distributions from config file using Python (refreshed on every run)
    distributions=""
    config_file="$HOME/.config/mirror-test/mirror-test.yaml"
    if [ -f "$config_file" ]; then
        distributions=$(python3 -c "
import yaml
import sys
try:
    with open('$config_file', 'r') as f:
        config = yaml.safe_load(f)
    if config and 'distributions' in config and isinstance(config['distributions'], dict):
        print(' '.join(config['distributions'].keys()))
    elif config:
        # Fallback for flat structure, exclude known system keys
        excluded_keys = {'variables', 'package-managers', 'distributions'}
        dist_keys = [key for key in config.keys() 
                    if key not in excluded_keys and isinstance(key, str)]
        print(' '.join(dist_keys))
except Exception as e:
    pass
" 2>/dev/null)
    fi
    
    # Use default distributions if none found
    if [ -z "$distributions" ]; then
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
        gui|cli|cleanup|all|list|variables|validate|help|refresh)
            COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
            return 0
            ;;
        -*)
            COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
            return 0
            ;;
        *)
            # Check if we're completing distribution names
            local found_command=false
            
            # Find if a command has been specified
            for (( i=1; i < ${#COMP_WORDS[@]}-1; i++ )); do
                if [[ " ${base_commands} " =~ " ${COMP_WORDS[$i]} " ]]; then
                    found_command=true
                    break
                fi
            done
            
            if [[ "$found_command" == false ]]; then
                # No command yet, might be listing distributions to test
                COMPREPLY=( $(compgen -W "${distributions} ${opts}" -- ${cur}) )
            else
                # Command already specified, show options
                COMPREPLY=( $(compgen -W "${opts}" -- ${cur}) )
            fi
            return 0
            ;;
    esac
}
complete -F _mirror_test_completions mirror-test
complete -F _mirror_test_completions mt
EOF

# Create default configuration if it doesn't exist
if [ ! -f "$CONFIG_DIR/mirror-test.yaml" ]; then
    print_status "Creating default configuration..."
    cat > "$CONFIG_DIR/mirror-test.yaml" << 'EOF'
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
    print_warning "Default configuration created at $CONFIG_DIR/mirror-test.yaml"
    print_warning "Please edit it with your local mirror URLs"
fi

# Install systemd service
if [ "$INSTALL_MODE" = "system" ]; then
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
else
    print_status "Installing user systemd service..."
    mkdir -p ~/.config/systemd/user
    cat > ~/.config/systemd/user/mirror-test-web.service << EOF
[Unit]
Description=Mirror Test Web Interface
After=network.target

[Service]
Type=simple
ExecStart=$BIN_DIR/mirror-test gui
Restart=on-failure
RestartSec=10
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

[Install]
WantedBy=default.target
EOF

    systemctl --user daemon-reload
fi

# Enable podman socket (required for some operations)
if [ "$INSTALL_MODE" = "system" ]; then
    print_status "Enabling podman socket..."
    systemctl enable --now podman.socket 2>/dev/null || true
else
    print_status "Enabling user podman socket..."
    systemctl --user enable --now podman.socket 2>/dev/null || true
fi

# Create convenience aliases
print_status "Creating convenience aliases..."
cat > "$PROFILE_DIR/mirror-test.sh" << 'EOF'
# mirror-test aliases
alias mt='mirror-test'
alias mt-gui='mirror-test gui'
alias mt-cli='mirror-test cli'
alias mt-test='mirror-test all'
alias mt-clean='mirror-test cleanup'
EOF

# Set up log rotation
if [ "$INSTALL_MODE" = "system" ]; then
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
cat > "$MAN_DIR/mirror-test.1" << 'EOF'
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
Launch simple CLI interface
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
fi

# Test installation
print_status "Testing installation..."
if "$BIN_DIR/mirror-test" --help &>/dev/null; then
    print_status "Installation successful!"
else
    print_error "Installation test failed"
    if [ "$INSTALL_MODE" = "user" ]; then
        print_warning "Trying to fix Python dependencies..."
        $PYTHON_CMD -m pip install --user pyyaml 2>/dev/null || true
        # Web interface uses built-in Python http.server module
    else
        print_warning "Trying to fix Python dependencies..."
        $PYTHON_CMD -m pip install pyyaml 2>/dev/null || true
        # Web interface uses built-in Python http.server module
    fi
fi

# Reload bash completion
print_status "Reloading bash completion..."
if [ "$INSTALL_MODE" = "system" ]; then
    if [ -f /etc/bash_completion ]; then
        . /etc/bash_completion
    elif [ -f /usr/share/bash-completion/bash_completion ]; then
        . /usr/share/bash-completion/bash_completion
    fi
else
    if [ -f ~/.bash_completion ]; then
        . ~/.bash_completion
    fi
    print_info "Add 'source ~/.bash_completion.d/mirror-test' to your ~/.bashrc for autocomplete"
fi

# Print summary
echo
echo "======================================"
echo -e "${GREEN}Installation Complete!${NC}"
echo "======================================"
echo
if [ "$INSTALL_MODE" = "user" ]; then
    echo -e "${GREEN}✓ User-level installation (no root required)${NC}"
    echo "  All files installed to user directories"
    echo "  Works with user-level Podman"
    echo
fi
echo "Version: 2.0.0"
echo "Config:  $CONFIG_DIR/mirror-test.yaml"
echo "Logs:    $LOG_DIR/"
echo "Builds:  $BUILD_DIR/"
echo
echo "Quick Start:"
echo "1. Edit configuration: nano $CONFIG_DIR/mirror-test.yaml"
echo "2. Set your mirror:    Update MIRROR_HOST variable"
echo "3. Test mirrors:       $BIN_DIR/mirror-test"
echo "4. View results:       $BIN_DIR/mirror-test gui  (web interface)"
echo
echo "Commands:"
echo "  $BIN_DIR/mirror-test              - Test all distributions"
echo "  $BIN_DIR/mirror-test debian       - Test specific distribution"
echo "  $BIN_DIR/mirror-test gui          - Web interface (http://localhost:8080)"
echo "  $BIN_DIR/mirror-test cli          - Simple CLI interface"
echo "  $BIN_DIR/mirror-test logs debian  - View test logs"
echo "  $BIN_DIR/mirror-test help         - Show detailed help"
echo
echo "CLI Features (mirror-test cli):"
echo "  • Simple text-based interface for terminal users"
echo "  • Interactive menu system for easy navigation"
echo "  • View test results and logs directly in terminal"
echo "  • Keyboard navigation (arrow keys, enter, q to quit)"
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
if [ "$INSTALL_MODE" = "system" ]; then
    echo "To enable the web service permanently:"
    echo "  systemctl enable --now mirror-test-web"
else
    echo "To enable the user web service permanently:"
    echo "  systemctl --user enable --now mirror-test-web"
    echo "  loginctl enable-linger $USER  # Enable user services at boot"
fi
echo
if [ "$INSTALL_MODE" = "system" ]; then
    print_info "Tip: Source /etc/profile.d/mirror-test.sh or restart shell for aliases"
else
    print_info "Tip: Add 'source $PROFILE_DIR/mirror-test.sh' to your ~/.bashrc for aliases"
fi

# Configure subuid/subgid for Podman rootless mode
print_status "Configuring Podman rootless mode..."

# Check if user is already in subuid/subgid files
if grep -q "^$USER:" /etc/subuid 2>/dev/null && grep -q "^$USER:" /etc/subgid 2>/dev/null; then
    print_info "User $USER already configured for rootless Podman"
else
    print_warning "User $USER needs to be added to subuid/subgid files for rootless Podman"
    print_info "This allows Podman to run containers without root privileges"
    echo
    
    # Try to configure automatically with sudo
    if command -v sudo >/dev/null 2>&1; then
        print_info "Attempting to configure subuid/subgid automatically..."
        if sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 "$USER" 2>/dev/null; then
            print_status "Successfully configured subuid/subgid for user $USER"
            print_info "Running podman system migrate to apply changes..."
            podman system migrate 2>/dev/null || true
            print_warning "You may need to log out and log back in for changes to take effect"
        else
            print_error "Failed to configure subuid/subgid automatically"
            print_warning "Please run the following commands as root:"
            echo "  sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 $USER"
            echo "  podman system migrate"
            echo
            print_warning "After running these commands, log out and log back in for changes to take effect"
        fi
    else
        print_error "sudo not available - cannot configure subuid/subgid automatically"
        print_warning "Please run the following commands as root:"
        echo "  usermod --add-subuids 100000-165535 --add-subgids 100000-165535 $USER"
        echo "  podman system migrate"
        echo
        print_warning "After running these commands, log out and log back in for changes to take effect"
    fi
fi

echo
echo
