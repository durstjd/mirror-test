#!/usr/bin/env python3
"""
Mirror Test - Main Entry Point
A secure web interface for testing Linux repository mirrors using container builds.
"""

import os
import sys
import argparse
import logging
import shutil
import yaml
from pathlib import Path
from config import ConfigManager
from core import MirrorTester
from cli import CLIInterface

# Global variables for server configuration
LDAPS_CONFIG = None
AUTH_ENABLED = False
SERVER_CONFIG = None
IP_WHITELIST_CONFIG = None
IP_WHITELIST_ENABLED = False
AUDIT_LOG_CONFIG = None
AUDIT_LOGGER = None

# API Configuration
API_KEYS = {}  # In-memory storage for API keys (replace with database in production)
API_VERSION = "v1"
API_SIGNATURE_SECRET = os.environ.get('API_SIGNATURE_SECRET', os.urandom(32).hex())
API_RATE_LIMITS = {
    'api_key': "1000 per hour",
    'api_public': "100 per hour"
}


def load_server_config():
    """Load server configuration from secure file."""
    global LDAPS_CONFIG, AUTH_ENABLED, SERVER_CONFIG, IP_WHITELIST_CONFIG, IP_WHITELIST_ENABLED, AUDIT_LOG_CONFIG, AUDIT_LOGGER
    
    # Try new server config first, fall back to old LDAPS config
    config_file = os.path.expanduser("~/.config/mirror-test/server-config.yaml")
    ldaps_config_file = os.path.expanduser("~/.config/mirror-test/ldaps-config.yaml")
    
    if os.path.exists(config_file):
        print(f"Loading server configuration from {config_file}")
        config_path = config_file
    elif os.path.exists(ldaps_config_file):
        print(f"Loading legacy LDAPS configuration from {ldaps_config_file}")
        print("Consider migrating to server-config.yaml for full configuration options")
        config_path = ldaps_config_file
    else:
        print("Warning: Server configuration not found. Authentication disabled.")
        print(f"Create {config_file} or {ldaps_config_file} to enable authentication.")
        return
    
    try:
        with open(config_path, 'r') as f:
            SERVER_CONFIG = yaml.safe_load(f)
        
        # Handle legacy LDAPS config format
        if 'ldap_server' in SERVER_CONFIG:
            # Legacy format - extract LDAPS config
            LDAPS_CONFIG = SERVER_CONFIG
        else:
            # New format - extract LDAPS config from server config
            LDAPS_CONFIG = SERVER_CONFIG
        
        # Validate required LDAPS configuration
        required_keys = ['ldap_server', 'ldap_port', 'base_dn', 'user_dn_template', 'group_dn']
        missing_keys = [key for key in required_keys if key not in LDAPS_CONFIG]
        
        if missing_keys:
            print(f"Error: Missing required LDAPS configuration: {missing_keys}")
            return
        
        # Set defaults for optional LDAPS configuration
        LDAPS_CONFIG.setdefault('ldap_port', 636)
        LDAPS_CONFIG.setdefault('ldap_use_ssl', True)
        LDAPS_CONFIG.setdefault('ldap_verify_cert', True)
        LDAPS_CONFIG.setdefault('ldap_ca_cert', None)
        LDAPS_CONFIG.setdefault('ldap_timeout', 10)
        LDAPS_CONFIG.setdefault('required_groups', [])
        
        # Load IP whitelist configuration if available
        if 'ip_whitelist' in SERVER_CONFIG:
            IP_WHITELIST_CONFIG = SERVER_CONFIG['ip_whitelist']
            IP_WHITELIST_ENABLED = IP_WHITELIST_CONFIG.get('enabled', False)
            if IP_WHITELIST_ENABLED:
                print("IP whitelist filtering enabled")
            else:
                print("IP whitelist filtering disabled")
        
        # Load audit log configuration if available
        if 'audit_log' in SERVER_CONFIG:
            AUDIT_LOG_CONFIG = SERVER_CONFIG['audit_log']
            if AUDIT_LOG_CONFIG.get('enabled', True):
                print("Audit logging enabled")
            else:
                print("Audit logging disabled")
        else:
            print("Audit logging enabled with default configuration")
        
        AUTH_ENABLED = True
        print("LDAPS authentication enabled")
        
    except Exception as e:
        print(f"Error loading server configuration: {e}")
        print("Authentication disabled")


def main():
    """Main entry point for Mirror Test."""
    parser = argparse.ArgumentParser(
        description='Mirror Test - Complete CLI and Web Interface',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  mirror-test --install           # Install default configuration files
  mirror-test                     # Test all configured distributions
  mirror-test debian              # Test only Debian
  mirror-test debian ubuntu       # Test Debian and Ubuntu
  mirror-test gui                 # Launch web interface
  mirror-test cli                 # Launch simple CLI interface
  mirror-test refresh             # Refresh bash completion
  mirror-test logs debian         # Show latest logs for Debian
  mirror-test dockerfile debian   # Show generated Dockerfile for Debian
  mirror-test --config /path/to/config.yaml  # Use custom config file
        """
    )
    
    parser.add_argument('command', nargs='*', default=['all'],
                       help='Command or distribution(s) to test')
    parser.add_argument('--config', default=None,
                       help='Path to configuration file')
    parser.add_argument('--port', type=int, default=8080,
                       help='Port for web interface (default: 8080)')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose output')
    parser.add_argument('--no-cleanup', action='store_true',
                       help='Do not clean up images after successful builds')
    parser.add_argument('--timeout', type=int, default=600,
                       help='Build timeout in seconds (default: 600)')
    parser.add_argument('--quiet', '-q', action='store_true',
                       help='Quiet mode (suppress output)')
    parser.add_argument('--version', action='version', version='Mirror Test 2.2.0')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('--open-browser', action='store_true', help='Open browser automatically')
    parser.add_argument('--ssl-cert', type=str, help='Path to SSL certificate file (.pem or .crt)')
    parser.add_argument('--ssl-key', type=str, help='Path to SSL private key file (.pem or .key)')
    parser.add_argument('--ssl-context', type=str, help='Path to SSL context file (cert+key combined)')
    parser.add_argument('--ssl-only', action='store_true', help='Require SSL certificates to start server')
    parser.add_argument('--install', action='store_true', help='Install default configuration files and directories')
    
    args = parser.parse_args()
    
    # Handle install command
    if args.install:
        return install_setup()
    
    # Setup logging
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Initialize configuration and CLI interface
    config_manager = ConfigManager(args.config)
    cli_interface = CLIInterface(args.config, cleanup_images=not args.no_cleanup)
    
    # Handle CLI commands
    try:
        success = cli_interface.run_command(args.command, args)
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def install_dependencies():
    """Install optional Python dependencies."""
    import subprocess
    
    # List of optional dependencies
    dependencies = [
        ("flask", "Flask web framework"),
        ("flask-limiter", "Flask rate limiting"),
        ("flask-wtf", "Flask CSRF protection"),
        ("flask-cors", "Flask CORS support"),
        ("python-ldap", "LDAP authentication support")
    ]
    
    for package, description in dependencies:
        print(f"Checking {package}...")
        try:
            # Try to import the package to see if it's already installed
            if package == "python-ldap":
                import ldap
                print(f"✓ {package} ({description}) is already installed")
            elif package == "flask":
                import flask
                print(f"✓ {package} ({description}) is already installed")
            elif package == "flask-limiter":
                import flask_limiter
                print(f"✓ {package} ({description}) is already installed")
            elif package == "flask-wtf":
                import flask_wtf
                print(f"✓ {package} ({description}) is already installed")
            elif package == "flask-cors":
                import flask_cors
                print(f"✓ {package} ({description}) is already installed")
        except ImportError:
            print(f"Installing {package} ({description})...")
            try:
                result = subprocess.run([
                    sys.executable, "-m", "pip", "install", package
                ], capture_output=True, text=True, timeout=60)
                
                if result.returncode == 0:
                    print(f"✓ Successfully installed {package}")
                else:
                    print(f"⚠ Warning: Failed to install {package}")
                    print(f"  Error: {result.stderr}")
                    print(f"  You can install it manually: pip install {package}")
            except subprocess.TimeoutExpired:
                print(f"⚠ Warning: Timeout installing {package}")
                print(f"  You can install it manually: pip install {package}")
            except Exception as e:
                print(f"⚠ Warning: Error installing {package}: {e}")
                print(f"  You can install it manually: pip install {package}")


def install_setup():
    """Install default configuration files and directories."""
    print("Mirror Test - Installation Setup")
    print("=" * 40)
    
    # Install Python dependencies
    print("Installing Python dependencies...")
    install_dependencies()
    
    # Define paths
    home_dir = Path.home()
    config_dir = home_dir / ".config" / "mirror-test"
    log_dir = home_dir / "mirror-test" / "logs"
    build_dir = home_dir / "mirror-test" / "builds"
    bash_completion_dir = home_dir / ".bash_completion.d"
    
    # Create directories
    print("Creating directories...")
    directories = [config_dir, log_dir, build_dir, bash_completion_dir]
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
        print(f"✓ Created: {directory}")
    
    # Create configuration files
    print("\nCreating configuration files...")
    
    # Main configuration file
    main_config = config_dir / "mirror-test.yaml"
    if not main_config.exists():
        copy_config_file("full-config-example.yaml", main_config)
        print(f"✓ Created: {main_config}")
    else:
        print(f"⚠ Already exists: {main_config}")
    
    # Server configuration file
    server_config = config_dir / "server-config.yaml"
    if not server_config.exists():
        copy_config_file("server-config-example.yaml", server_config)
        print(f"✓ Created: {server_config}")
    else:
        print(f"⚠ Already exists: {server_config}")
    
    # Install bash completion
    print("\nInstalling bash completion...")
    bash_completion_file = bash_completion_dir / "mirror-test"
    if not bash_completion_file.exists():
        install_bash_completion(bash_completion_file)
        print(f"✓ Installed: {bash_completion_file}")
    else:
        print(f"⚠ Already exists: {bash_completion_file}")
    
    # Install executable
    print("\nInstalling executable...")
    bin_dir = home_dir / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    executable_path = bin_dir / "mirror-test"
    
    # Check if we're running from a compiled executable
    if getattr(sys, 'frozen', False):
        # We're running from a PyInstaller executable
        current_exe = Path(sys.executable)
        if current_exe.exists() and current_exe.is_file():
            # Copy ourselves to the target location
            shutil.copy2(current_exe, executable_path)
            executable_path.chmod(0o755)
            print(f"✓ Installed compiled executable: {executable_path}")
            print(f"  Source: {current_exe}")
        else:
            print("❌ Error: Cannot locate the current executable")
            print("  This should not happen. Please report this issue.")
            return
    else:
        # We're running from Python source code
        print("❌ Error: This installation requires a compiled executable")
        print("  The --install command should only be run from a compiled mirror-test binary.")
        print("  Please download the compiled version and run it directly.")
        print("  If you have the source code, build it first with:")
        print("    python build_linux_simple.py")
        return
    
    # Install man page
    print("\nInstalling man page...")
    man_dir = home_dir / ".local" / "share" / "man" / "man1"
    man_dir.mkdir(parents=True, exist_ok=True)
    man_page = man_dir / "mirror-test.1"
    if not man_page.exists():
        create_man_page(man_page)
        print(f"✓ Installed man page: {man_page}")
    else:
        print(f"⚠ Already exists: {man_page}")
    
    # Create mt-cli wrapper
    print("\nCreating mt-cli wrapper...")
    mt_cli_path = bin_dir / "mt-cli"
    if not mt_cli_path.exists():
        create_mt_cli_wrapper(mt_cli_path)
        print(f"✓ Created mt-cli wrapper: {mt_cli_path}")
    else:
        print(f"⚠ Already exists: {mt_cli_path}")
    
    # Create convenience aliases
    print("\nCreating convenience aliases...")
    profile_dir = home_dir / ".config" / "mirror-test"
    aliases_file = profile_dir / "mirror-test.sh"
    if not aliases_file.exists():
        create_convenience_aliases(aliases_file)
        print(f"✓ Created convenience aliases: {aliases_file}")
    else:
        print(f"⚠ Already exists: {aliases_file}")
    
    # Create user systemd service
    print("\nCreating systemd service...")
    systemd_user_dir = home_dir / ".config" / "systemd" / "user"
    systemd_user_dir.mkdir(parents=True, exist_ok=True)
    systemd_service = systemd_user_dir / "mirror-test-web.service"
    if not systemd_service.exists():
        create_systemd_service(systemd_service, executable_path)
        print(f"✓ Created systemd service: {systemd_service}")
    else:
        print(f"⚠ Already exists: {systemd_service}")
    
    # Set up log rotation
    print("\nSetting up log rotation...")
    logrotate_dir = home_dir / ".config" / "logrotate.d"
    logrotate_dir.mkdir(parents=True, exist_ok=True)
    logrotate_config = logrotate_dir / "mirror-test"
    if not logrotate_config.exists():
        create_logrotate_config(logrotate_config, log_dir)
        print(f"✓ Created log rotation config: {logrotate_config}")
    else:
        print(f"⚠ Already exists: {logrotate_config}")
    
    print("\n" + "=" * 40)
    print("✓ Installation completed successfully!")
    print(f"Configuration directory: {config_dir}")
    print(f"Log directory: {log_dir}")
    print(f"Build directory: {build_dir}")
    print(f"Bash completion: {bash_completion_file}")
    print(f"Executable: {executable_path}")
    print(f"mt-cli wrapper: {mt_cli_path}")
    print(f"Man page: {man_page}")
    print(f"Convenience aliases: {aliases_file}")
    print(f"Systemd service: {systemd_service}")
    print(f"Log rotation: {logrotate_config}")
    print("\nNext steps:")
    print("1. Add ~/.local/bin to your PATH if not already there:")
    print("   echo 'export PATH=\"$HOME/.local/bin:$PATH\"' >> ~/.bashrc")
    print("   source ~/.bashrc")
    print("2. Load convenience aliases:")
    print("   echo 'source ~/.config/mirror-test/mirror-test.sh' >> ~/.bashrc")
    print("   source ~/.bashrc")
    print("3. Edit configuration files as needed")
    print("4. Run 'mirror-test --help' to see available commands")
    print("5. Run 'man mirror-test' to view the manual page")
    print("6. Run 'mirror-test gui' to start the web interface")
    print("7. Use 'mt' as a shortcut for 'mirror-test'")
    print("8. Enable systemd service: systemctl --user enable mirror-test-web.service")
    
    return 0


def copy_config_file(source_filename, target_file):
    """Copy a configuration file from the built-in examples."""
    script_dir = Path(__file__).parent
    source_file = script_dir / source_filename
    
    if source_file.exists():
        shutil.copy2(source_file, target_file)
    else:
        raise FileNotFoundError(f"Configuration file not found: {source_file}")


def install_bash_completion(bash_completion_file):
    """Install bash completion script."""
    # Get the current script directory to find bash-autocomplete.sh
    script_dir = Path(__file__).parent
    source_file = script_dir / "bash-autocomplete.sh"
    
    if source_file.exists():
        # Copy the sophisticated bash completion script
        shutil.copy2(source_file, bash_completion_file)
        # Make it executable
        bash_completion_file.chmod(0o755)
    else:
        # Create a basic completion script if source not found
        completion_content = """# Mirror Test Bash Completion
_mirror_test_completion() {
    local cur prev opts
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    
    opts="all gui refresh cli list variables validate cleanup logs dockerfile --help --version --config --port --verbose --quiet --debug --install"
    
    if [[ ${cur} == -* ]]; then
        COMPREPLY=($(compgen -W "${opts}" -- ${cur}))
        return 0
    fi
}

complete -F _mirror_test_completion mirror-test
"""
        bash_completion_file.write_text(completion_content)
        bash_completion_file.chmod(0o755)




def create_man_page(man_page_path):
    """Create a man page for mirror-test."""
    man_content = """.TH MIRROR-TEST 1 "January 2025" "Version 2.0.0" "Mirror Test Manual"
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
.TP
.B \-\-ssl\-cert \fIFILE\fR
SSL certificate file for web interface
.TP
.B \-\-ssl\-key \fIFILE\fR
SSL private key file for web interface
.TP
.B \-\-ssl\-context \fIFILE\fR
Combined SSL context file (cert+key)
.TP
.B \-\-ssl\-only
Require SSL certificates to start server
.TP
.B \-\-debug
Enable debug mode
.TP
.B \-\-open\-browser
Open browser automatically
.TP
.B \-\-install
Install default configuration files and directories
.SH FILES
.TP
.I ~/.config/mirror-test/mirror-test.yaml
Main configuration file
.TP
.I ~/mirror-test/logs/
Test logs directory
.TP
.I ~/mirror-test/builds/
Dockerfile storage directory
.TP
.I ~/.config/mirror-test/server-config.yaml
Server configuration file
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
.TP
Generate Dockerfile:
.B mirror-test dockerfile debian
.TP
Start with SSL:
.B mirror-test gui --ssl-cert cert.pem --ssl-key key.pem
.SH AUTHOR
Created for testing local Linux repository mirrors
.SH SEE ALSO
podman(1), docker(1), dockerfile(5)
"""
    
    man_page_path.write_text(man_content)


def create_mt_cli_wrapper(mt_cli_path):
    """Create mt-cli wrapper script."""
    script_dir = Path(__file__).parent
    python_exe = sys.executable
    module_dir = script_dir.absolute()
    
    mt_cli_content = f"""#!/bin/bash
# mt-cli wrapper - Short alias for mirror-test cli

# Change to the module directory
cd "{module_dir}"

# Call the Python main module with cli command
{python_exe} main.py cli "$@"
"""
    
    mt_cli_path.write_text(mt_cli_content)
    mt_cli_path.chmod(0o755)


def create_convenience_aliases(aliases_file):
    """Create convenience aliases script."""
    aliases_content = """# mirror-test aliases
alias mt='mirror-test'
alias mt-gui='mirror-test gui'
alias mt-cli='mirror-test cli'
alias mt-test='mirror-test all'
alias mt-clean='mirror-test cleanup'
alias mt-logs='mirror-test logs'
alias mt-dockerfile='mirror-test dockerfile'
alias mt-list='mirror-test list'
alias mt-vars='mirror-test variables'
alias mt-validate='mirror-test validate'
"""
    
    aliases_file.write_text(aliases_content)


def create_systemd_service(service_file, executable_path):
    """Create systemd user service file."""
    service_content = f"""[Unit]
Description=Mirror Test Web Interface
After=network.target

[Service]
Type=simple
User=%i
ExecStart={executable_path} gui --port 8080
Restart=always
RestartSec=10
Environment=HOME=%h

[Install]
WantedBy=default.target
"""
    
    service_file.write_text(service_content)


def create_logrotate_config(logrotate_file, log_dir):
    """Create log rotation configuration."""
    logrotate_content = f"""{log_dir}/*.log {{
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 644 $USER $USER
}}
"""
    
    logrotate_file.write_text(logrotate_content)


# Load server configuration
load_server_config()


if __name__ == '__main__':
    main()
