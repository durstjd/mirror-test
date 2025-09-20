#!/bin/bash

# Mirror Test Offline Setup Script
# This script installs mirror-test using locally available dependencies

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_header() {
    echo -e "${BLUE}================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}================================${NC}"
}

print_header "Mirror Test Offline Installation"

# Check if we're in the right directory
if [ ! -f "mirror-test.py" ]; then
    print_error "mirror-test.py not found. Please run this script from the mirror-test directory."
    exit 1
fi

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
    print_status "To use a different version of Python:"
    print_status "1. Install Python 3.8+ using your package manager:"
    if command -v apt-get &> /dev/null; then
        echo "    sudo apt-get install python3.8 python3.8-venv python3.8-dev"
        echo "    # Or for newer versions:"
        echo "    sudo apt-get install python3.11 python3.11-venv python3.11-dev"
    elif command -v yum &> /dev/null; then
        echo "    sudo yum install python3.8 python3.8-devel"
        echo "    # Or for newer versions:"
        echo "    sudo yum install python3.11 python3.11-devel"
    elif command -v dnf &> /dev/null; then
        echo "    sudo dnf install python3.8 python3.8-devel"
        echo "    # Or for newer versions:"
        echo "    sudo dnf install python3.11 python3.11-devel"
    elif command -v apk &> /dev/null; then
        echo "    sudo apk add python3.8 python3.8-dev"
        echo "    # Or for newer versions:"
        echo "    sudo apk add python3.11 python3.11-dev"
    elif command -v pacman &> /dev/null; then
        echo "    sudo pacman -S python python-pip"
    elif command -v zypper &> /dev/null; then
        echo "    sudo zypper install python38 python38-devel"
        echo "    # Or for newer versions:"
        echo "    sudo zypper install python311 python311-devel"
    fi
    
    print_status "2. Use update-alternatives to manage multiple Python versions:"
    echo "    sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.8 1"
    echo "    sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 2"
    echo "    sudo update-alternatives --config python3"
    
    print_status "3. Or use pyenv to manage Python versions (no sudo required):"
    echo "    curl https://pyenv.run | bash"
    echo "    pyenv install 3.11.0"
    echo "    pyenv global 3.11.0"
    
    print_status "4. Or specify a specific Python version when running this script:"
    echo "    PYTHON_CMD=python3.11 ./offline-setup-script.sh"
    
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

# Install Python dependencies
print_status "Installing Python dependencies..."

# Check if PyYAML is already installed
if $PYTHON_CMD -c "import yaml" 2>/dev/null; then
    print_status "PyYAML is already installed"
else
    print_status "Installing PyYAML..."
    
    # Try to install from local package first
    if [ -f "python-deps/PyYAML-6.0.1.tar.gz" ]; then
        print_status "Installing PyYAML from local package..."
        $PYTHON_CMD -m pip install --user python-deps/PyYAML-6.0.1.tar.gz
    else
        print_warning "Local PyYAML package not found, trying system package manager..."
        
        # Try to install from system package manager
        if command -v apt-get &> /dev/null; then
            print_status "Installing PyYAML via apt-get..."
            sudo apt-get update
            sudo apt-get install -y python3-yaml
        elif command -v yum &> /dev/null; then
            print_status "Installing PyYAML via yum..."
            sudo yum install -y python3-pyyaml
        elif command -v dnf &> /dev/null; then
            print_status "Installing PyYAML via dnf..."
            sudo dnf install -y python3-pyyaml
        elif command -v apk &> /dev/null; then
            print_status "Installing PyYAML via apk..."
            sudo apk add --no-cache py3-yaml
        elif command -v pacman &> /dev/null; then
            print_status "Installing PyYAML via pacman..."
            sudo pacman -S python-yaml
        elif command -v zypper &> /dev/null; then
            print_status "Installing PyYAML via zypper..."
            sudo zypper install -y python3-PyYAML
        else
            print_error "Could not install PyYAML. Please install it manually."
            print_status "You can try: $PYTHON_CMD -m pip install --user PyYAML"
            exit 1
        fi
    fi
fi

# Verify PyYAML installation
if $PYTHON_CMD -c "import yaml" 2>/dev/null; then
    print_status "PyYAML installed successfully"
else
    print_error "PyYAML installation failed"
    exit 1
fi

# Install Podman
print_status "Installing Podman..."

# Check if Podman is already installed
if command -v podman &> /dev/null; then
    print_status "Podman is already installed: $(podman --version)"
else
    print_status "Installing Podman..."
    
    # Try to install from local package first
    PODMAN_TAR=$(ls system-deps/podman-*.tar.gz 2>/dev/null | head -1)
    if [ -n "$PODMAN_TAR" ]; then
        print_status "Installing Podman from local package: $PODMAN_TAR"
        tar -xzf "$PODMAN_TAR" -C /tmp/
        sudo cp /tmp/podman-remote-static-* /usr/local/bin/podman
        sudo chmod +x /usr/local/bin/podman
        print_status "Podman installed successfully"
    else
        print_warning "Local Podman package not found, trying system package manager..."
        
        # Try to install from system package manager
        if command -v apt-get &> /dev/null; then
            print_status "Installing Podman via apt-get..."
            sudo apt-get update
            sudo apt-get install -y podman
        elif command -v yum &> /dev/null; then
            print_status "Installing Podman via yum..."
            sudo yum install -y podman
        elif command -v dnf &> /dev/null; then
            print_status "Installing Podman via dnf..."
            sudo dnf install -y podman
        elif command -v apk &> /dev/null; then
            print_status "Installing Podman via apk..."
            sudo apk add --no-cache podman
        elif command -v pacman &> /dev/null; then
            print_status "Installing Podman via pacman..."
            sudo pacman -S podman
        elif command -v zypper &> /dev/null; then
            print_status "Installing Podman via zypper..."
            sudo zypper install -y podman
        else
            print_warning "Could not install Podman via package manager."
            print_status "Please install Podman manually from: https://podman.io/getting-started/installation"
        fi
    fi
fi

# Verify Podman installation
if command -v podman &> /dev/null; then
    print_status "Podman installed successfully: $(podman --version)"
else
    print_warning "Podman installation failed or not found"
    print_status "You may need to install Podman manually"
fi

# Install mirror-test
print_status "Installing mirror-test..."

# Determine installation directory
if [ -w "/usr/local/bin" ]; then
    BIN_DIR="/usr/local/bin"
else
    BIN_DIR="$HOME/.local/bin"
    mkdir -p "$BIN_DIR"
    export PATH="$BIN_DIR:$PATH"
fi

# Copy mirror-test.py to bin directory and update shebang
print_status "Installing mirror-test to $BIN_DIR..."
cp mirror-test.py "$BIN_DIR/mirror-test"
# Update the shebang to use the detected Python command
sed -i "1s|#!/usr/bin/env python3|#!/usr/bin/env $PYTHON_CMD|" "$BIN_DIR/mirror-test"
print_status "Updated shebang to use $PYTHON_CMD"
chmod +x "$BIN_DIR/mirror-test"

# Create symlink for mt command
ln -sf "$BIN_DIR/mirror-test" "$BIN_DIR/mt"

# Install bash completion
print_status "Installing bash completion..."
if [ -f "bash-autocomplete.sh" ]; then
    COMPLETION_DIR="/etc/bash_completion.d"
    if [ -d "$COMPLETION_DIR" ] && [ -w "$COMPLETION_DIR" ]; then
        cp bash-autocomplete.sh "$COMPLETION_DIR/mirror-test"
        print_status "Bash completion installed to $COMPLETION_DIR"
    else
        print_warning "Cannot install bash completion to $COMPLETION_DIR (permission denied)"
        print_status "You can manually install it by copying bash-autocomplete.sh to your completion directory"
    fi
fi

# Create log directory
print_status "Creating log directory..."
LOG_DIR="$HOME/.local/share/mirror-test/logs"
mkdir -p "$LOG_DIR"

# Create configuration directory
print_status "Creating configuration directory..."
CONFIG_DIR="$HOME/.config/mirror-test"
mkdir -p "$CONFIG_DIR"

# Copy example configuration
if [ -f "config-examples/full-config-example.yaml" ]; then
    if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
        cp config-examples/full-config-example.yaml "$CONFIG_DIR/config.yaml"
        print_status "Example configuration copied to $CONFIG_DIR/config.yaml"
    else
        print_status "Configuration file already exists at $CONFIG_DIR/config.yaml"
    fi
fi

# Test installation
print_status "Testing installation..."
if "$BIN_DIR/mirror-test" --help &>/dev/null; then
    print_status "Installation successful!"
else
    print_error "Installation test failed"
    exit 1
fi

# Display usage information
print_header "Installation Complete!"

print_status "Mirror Test has been installed successfully!"
print_status ""
print_status "Usage:"
print_status "  mirror-test --help          # Show help"
print_status "  mirror-test gui             # Start web interface"
print_status "  mirror-test test <dist>     # Test specific distribution"
print_status "  mirror-test test-all        # Test all distributions"
print_status "  mirror-test cleanup         # Clean up container images"
print_status ""
print_status "Configuration:"
print_status "  Edit: $CONFIG_DIR/config.yaml"
print_status "  Logs: $LOG_DIR/"
print_status ""
print_status "Quick start:"
print_status "  1. Edit configuration: nano $CONFIG_DIR/config.yaml"
print_status "  2. Start web interface: mirror-test gui"
print_status "  3. Open browser to: http://localhost:8080"
print_status ""

# Check if PATH needs to be updated
if [ "$BIN_DIR" = "$HOME/.local/bin" ]; then
    print_warning "Note: $BIN_DIR is not in your PATH"
    print_status "Add this line to your ~/.bashrc or ~/.profile:"
    print_status "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    print_status "Then run: source ~/.bashrc"
fi

print_status "Offline installation completed successfully!"

