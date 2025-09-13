#!/bin/bash

# Mirror Test Uninstall Script
# This script removes the mirror-test tool and all associated files

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if running as root
check_root() {
    if [ "$EUID" -eq 0 ]; then
        return 0
    else
        return 1
    fi
}

# Function to detect installation type
detect_installation() {
    local system_installed=false
    local user_installed=false
    
    # Check for system installation
    if [ -f "/usr/local/bin/mirror-test" ] || [ -f "/usr/bin/mirror-test" ]; then
        system_installed=true
    fi
    
    # Check for user installation
    if [ -f "$HOME/.local/bin/mirror-test" ]; then
        user_installed=true
    fi
    
    echo "$system_installed,$user_installed"
}

# Function to remove system installation
remove_system_installation() {
    print_info "Removing system-wide installation..."
    
    # Remove binary
    if [ -f "/usr/local/bin/mirror-test" ]; then
        rm -f "/usr/local/bin/mirror-test"
        print_success "Removed /usr/local/bin/mirror-test"
    fi
    
    if [ -f "/usr/bin/mirror-test" ]; then
        rm -f "/usr/bin/mirror-test"
        print_success "Removed /usr/bin/mirror-test"
    fi
    
    # Remove configuration file
    if [ -f "/etc/mirror-test.yaml" ]; then
        rm -f "/etc/mirror-test.yaml"
        print_success "Removed /etc/mirror-test.yaml"
    fi
    
    # Remove log directory
    if [ -d "/var/log/mirror-test" ]; then
        rm -rf "/var/log/mirror-test"
        print_success "Removed /var/log/mirror-test"
    fi
    
    # Remove build directory
    if [ -d "/var/lib/mirror-test" ]; then
        rm -rf "/var/lib/mirror-test"
        print_success "Removed /var/lib/mirror-test"
    fi
    
    # Remove systemd service
    if [ -f "/etc/systemd/system/mirror-test.service" ]; then
        systemctl stop mirror-test 2>/dev/null || true
        systemctl disable mirror-test 2>/dev/null || true
        rm -f "/etc/systemd/system/mirror-test.service"
        systemctl daemon-reload
        print_success "Removed systemd service"
    fi
    
    # Remove bash completion
    if [ -f "/etc/bash_completion.d/mirror-test" ]; then
        rm -f "/etc/bash_completion.d/mirror-test"
        print_success "Removed bash completion"
    fi
    
    print_success "System-wide installation removed successfully"
}

# Function to remove user installation
remove_user_installation() {
    print_info "Removing user-level installation..."
    
    # Remove binary
    if [ -f "$HOME/.local/bin/mirror-test" ]; then
        rm -f "$HOME/.local/bin/mirror-test"
        print_success "Removed $HOME/.local/bin/mirror-test"
    fi
    
    # Remove configuration directory
    if [ -d "$HOME/.config/mirror-test" ]; then
        rm -rf "$HOME/.config/mirror-test"
        print_success "Removed $HOME/.config/mirror-test"
    fi
    
    # Remove log directory
    if [ -d "$HOME/mirror-test" ]; then
        rm -rf "$HOME/mirror-test"
        print_success "Removed $HOME/mirror-test"
    fi
    
    # Remove user systemd service
    if [ -f "$HOME/.config/systemd/user/mirror-test.service" ]; then
        systemctl --user stop mirror-test 2>/dev/null || true
        systemctl --user disable mirror-test 2>/dev/null || true
        rm -f "$HOME/.config/systemd/user/mirror-test.service"
        systemctl --user daemon-reload
        print_success "Removed user systemd service"
    fi
    
    # Remove bash completion
    if [ -f "$HOME/.bash_completion.d/mirror-test" ]; then
        rm -f "$HOME/.bash_completion.d/mirror-test"
        print_success "Removed user bash completion"
    fi
    
    print_success "User-level installation removed successfully"
}

# Function to clean up containers and images
cleanup_containers() {
    print_info "Cleaning up containers and images..."
    
    # Check if podman is available
    if command -v podman >/dev/null 2>&1; then
        # Remove containers
        local containers=$(podman ps -a --filter "label=mirror-test" --format "{{.ID}}" 2>/dev/null || true)
        if [ -n "$containers" ]; then
            echo "$containers" | xargs podman rm -f 2>/dev/null || true
            print_success "Removed mirror-test containers"
        fi
        
        # Remove images
        local images=$(podman images --filter "label=mirror-test" --format "{{.ID}}" 2>/dev/null || true)
        if [ -n "$images" ]; then
            echo "$images" | xargs podman rmi -f 2>/dev/null || true
            print_success "Removed mirror-test images"
        fi
    else
        print_warning "Podman not found, skipping container cleanup"
    fi
}

# Function to show usage
show_usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -h, --help          Show this help message"
    echo "  -s, --system        Remove only system-wide installation"
    echo "  -u, --user          Remove only user-level installation"
    echo "  -a, --all           Remove both system and user installations (default)"
    echo "  -c, --cleanup       Also clean up containers and images"
    echo "  -y, --yes           Skip confirmation prompts"
    echo ""
    echo "Examples:"
    echo "  $0                  # Remove all installations with confirmation"
    echo "  $0 --user --yes     # Remove user installation without confirmation"
    echo "  $0 --system --cleanup # Remove system installation and clean containers"
}

# Main function
main() {
    local remove_system=false
    local remove_user=false
    local cleanup_containers_flag=false
    local skip_confirm=false
    
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -h|--help)
                show_usage
                exit 0
                ;;
            -s|--system)
                remove_system=true
                shift
                ;;
            -u|--user)
                remove_user=true
                shift
                ;;
            -a|--all)
                remove_system=true
                remove_user=true
                shift
                ;;
            -c|--cleanup)
                cleanup_containers_flag=true
                shift
                ;;
            -y|--yes)
                skip_confirm=true
                shift
                ;;
            *)
                print_error "Unknown option: $1"
                show_usage
                exit 1
                ;;
        esac
    done
    
    # If no specific options, default to removing all
    if [ "$remove_system" = false ] && [ "$remove_user" = false ]; then
        remove_system=true
        remove_user=true
    fi
    
    # Detect current installation
    local installation_info=$(detect_installation)
    local system_installed=$(echo "$installation_info" | cut -d',' -f1)
    local user_installed=$(echo "$installation_info" | cut -d',' -f2)
    
    # Check if anything is installed
    if [ "$system_installed" = false ] && [ "$user_installed" = false ]; then
        print_warning "No mirror-test installation found"
        exit 0
    fi
    
    # Show what will be removed
    echo "Mirror Test Uninstaller"
    echo "======================"
    echo ""
    
    if [ "$remove_system" = true ] && [ "$system_installed" = true ]; then
        echo "System-wide installation found:"
        echo "  • Binary: /usr/local/bin/mirror-test or /usr/bin/mirror-test"
        echo "  • Config: /etc/mirror-test.yaml"
        echo "  • Logs: /var/log/mirror-test"
        echo "  • Builds: /var/lib/mirror-test"
        echo "  • Service: /etc/systemd/system/mirror-test.service"
        echo "  • Completion: /etc/bash_completion.d/mirror-test"
        echo ""
    fi
    
    if [ "$remove_user" = true ] && [ "$user_installed" = true ]; then
        echo "User-level installation found:"
        echo "  • Binary: $HOME/.local/bin/mirror-test"
        echo "  • Config: $HOME/.config/mirror-test"
        echo "  • Logs: $HOME/mirror-test"
        echo "  • Service: $HOME/.config/systemd/user/mirror-test.service"
        echo "  • Completion: $HOME/.bash_completion.d/mirror-test"
        echo ""
    fi
    
    if [ "$cleanup_containers_flag" = true ]; then
        echo "Container cleanup will also be performed"
        echo ""
    fi
    
    # Confirm removal
    if [ "$skip_confirm" = false ]; then
        read -p "Are you sure you want to remove these files? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_info "Uninstall cancelled"
            exit 0
        fi
    fi
    
    # Perform removal
    if [ "$remove_system" = true ] && [ "$system_installed" = true ]; then
        if check_root; then
            remove_system_installation
        else
            print_error "System installation requires root privileges"
            print_info "Run with sudo or use --user flag for user installation only"
            exit 1
        fi
    fi
    
    if [ "$remove_user" = true ] && [ "$user_installed" = true ]; then
        remove_user_installation
    fi
    
    if [ "$cleanup_containers_flag" = true ]; then
        cleanup_containers
    fi
    
    print_success "Uninstall completed successfully!"
    print_info "You may need to restart your shell or run 'source ~/.bashrc' to update PATH"
}

# Run main function
main "$@"

