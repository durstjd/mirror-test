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

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    print_error "Python 3 is not installed. Please install Python 3 first."
    print_status "Install Python 3 using your system package manager:"
    if command -v apt-get &> /dev/null; then
        echo "  sudo apt-get install -y python3"
    elif command -v yum &> /dev/null; then
        echo "  sudo yum install -y python3"
    elif command -v dnf &> /dev/null; then
        echo "  sudo dnf install -y python3"
    elif command -v apk &> /dev/null; then
        echo "  sudo apk add --no-cache python3"
    elif command -v pacman &> /dev/null; then
        echo "  sudo pacman -S python"
    elif command -v zypper &> /dev/null; then
        echo "  sudo zypper install -y python3"
    fi
    exit 1
fi

# Check Python version
PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
print_status "Found Python $PYTHON_VERSION"

# Install Python dependencies
print_status "Installing Python dependencies..."

# Check if PyYAML is already installed
if python3 -c "import yaml" 2>/dev/null; then
    print_status "PyYAML is already installed"
else
    print_status "Installing PyYAML..."
    
    # Try to install from local package first
    if [ -f "python-deps/PyYAML-6.0.1.tar.gz" ]; then
        print_status "Installing PyYAML from local package..."
        pip3 install --user python-deps/PyYAML-6.0.1.tar.gz
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
            print_status "You can try: pip3 install --user PyYAML"
            exit 1
        fi
    fi
fi

# Verify PyYAML installation
if python3 -c "import yaml" 2>/dev/null; then
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

# Copy mirror-test.py to bin directory
print_status "Installing mirror-test to $BIN_DIR..."
cp mirror-test.py "$BIN_DIR/mirror-test"
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
