#!/usr/bin/env python3
"""
mirror-test - Linux Repository Mirror Testing Tool
Tests local repository mirrors for different Linux distributions using Podman build process.
"""

import os
import sys
import json
import yaml
import argparse
import subprocess
import threading
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import tempfile
import shutil

# Web server imports
from http.server import HTTPServer, SimpleHTTPRequestHandler
import socketserver
import webbrowser


# Configuration paths - use user-level defaults
import os
from pathlib import Path

# Default paths (will be overridden by MirrorTester if user config exists)
CONFIG_FILE = "/etc/mirror-test.yaml"
LOG_DIR = "/var/log/mirror-test"
BUILD_DIR = "/var/lib/mirror-test/builds"
WEB_PORT = 8080

# User-level paths
USER_CONFIG = os.path.expanduser("~/.config/mirror-test/mirror-test.yaml")
USER_LOG_DIR = os.path.expanduser("~/mirror-test/logs")
USER_BUILD_DIR = os.path.expanduser("~/mirror-test/builds")

def get_user_paths():
    """Get user-level paths if config exists, otherwise system paths."""
    if os.path.exists(USER_CONFIG):
        return USER_CONFIG, USER_LOG_DIR, USER_BUILD_DIR
    else:
        return CONFIG_FILE, LOG_DIR, BUILD_DIR

def get_paths_for_user():
    """Get paths appropriate for the current user context."""
    # Check if we're running as root
    try:
        # Check if we're running as root
        if os.geteuid() == 0:
            return CONFIG_FILE, LOG_DIR, BUILD_DIR
        else:
            return USER_CONFIG, USER_LOG_DIR, USER_BUILD_DIR
    except AttributeError:
        # os.geteuid() not available, use user paths
        return USER_CONFIG, USER_LOG_DIR, USER_BUILD_DIR

# Note: Directories will be created by MirrorTester based on installation type

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MirrorTester:
    """Main class for testing repository mirrors using Dockerfile builds."""
    
    def __init__(self, config_file: str = None, cleanup_images: bool = True):
        # Determine paths based on config file
        if config_file is None:
            config_file, log_dir, build_dir = get_paths_for_user()
        else:
            # Determine paths based on config file location
            if config_file.startswith(os.path.expanduser("~")):
                log_dir = USER_LOG_DIR
                build_dir = USER_BUILD_DIR
            else:
                log_dir = LOG_DIR
                build_dir = BUILD_DIR
        
        # Store paths for this instance
        self.config_file = config_file
        self.log_dir = log_dir
        self.build_dir = build_dir
        self.config = self.load_config()
        self.results = {}
        self.cleanup_images = cleanup_images
        
        # Ensure directories exist
        Path(self.log_dir).mkdir(parents=True, exist_ok=True)
        Path(self.build_dir).mkdir(parents=True, exist_ok=True)
        
    def load_config(self) -> Dict:
        """Load configuration from YAML file."""
        if not os.path.exists(self.config_file):
            logger.error(f"Configuration file not found: {self.config_file}")
            self.create_default_config()
            
        with open(self.config_file, 'r') as f:
            config = yaml.safe_load(f)
            
        # Handle both old flat structure and new nested structure
        if 'distributions' in config:
            # New nested structure - extract distributions to top level for backward compatibility
            distributions = config.pop('distributions', {})
            # Keep other keys like variables and package-managers
            other_keys = {k: v for k, v in config.items() if k not in ['distributions']}
            config = {**other_keys, **distributions}
            
        return config
    
    def get_distributions(self) -> List[str]:
        """Get list of configured distributions (excluding variables and package-managers)."""
        excluded_keys = {'variables', 'package-managers'}
        return [key for key in self.config.keys() if key not in excluded_keys]
    
    def create_default_config(self):
        """Create a default configuration file."""
        default_config = {
            'debian': {
                'base-image': 'debian:12',
                'package-manager': 'apt',
                'sources': [
                    'deb http://deb.debian.org/debian bookworm main contrib non-free non-free-firmware'
                ]
            },
            'ubuntu': {
                'base-image': 'ubuntu:22.04',
                'package-manager': 'apt',
                'sources': [
                    'deb http://archive.ubuntu.com/ubuntu jammy main restricted universe multiverse'
                ]
            },
            'rocky': {
                'base-image': 'rockylinux:9',
                'package-manager': 'yum',
                'sources': [
                    '[mirror-base]\nname=Mirror Base\nbaseurl=http://mirror.local/rocky/9/BaseOS/x86_64/os/\nenabled=1\ngpgcheck=0'
                ]
            },
            'fedora': {
                'base-image': 'fedora:39',
                'package-manager': 'dnf',
                'sources': [
                    '[mirror]\nname=Mirror\nbaseurl=http://mirror.local/fedora/39/x86_64/\nenabled=1\ngpgcheck=0'
                ]
            },
            'alpine': {
                'base-image': 'alpine:3.19',
                'package-manager': 'apk',
                'sources': [
                    'http://dl-cdn.alpinelinux.org/alpine/v3.19/main',
                    'http://dl-cdn.alpinelinux.org/alpine/v3.19/community'
                ]
            }
        }
        
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        with open(self.config_file, 'w') as f:
            yaml.dump(default_config, f, default_flow_style=False)
        logger.info(f"Created default configuration at {self.config_file}")
    
    def substitute_variables(self, text: str) -> str:
        """Substitute variables in text using the configuration variables."""
        if 'variables' not in self.config:
            return text
        
        variables = self.config['variables']
        
        # Handle nested variable substitution
        max_iterations = 10  # Prevent infinite loops
        for _ in range(max_iterations):
            original_text = text
            for var_name, var_value in variables.items():
                pattern = f"${{{var_name}}}"
                text = text.replace(pattern, str(var_value))
            
            # If no more substitutions were made, we're done
            if text == original_text:
                break
        
        return text
    
    def get_package_manager_config(self, package_manager: str) -> Dict:
        """Get package manager configuration from the config."""
        if 'package-managers' not in self.config:
            return {}
        
        return self.config['package-managers'].get(package_manager, {})
    
    def generate_dockerfile(self, dist_name: str, dist_config: Dict) -> str:
        """Generate a Dockerfile for testing a distribution's repositories."""
        base_image = dist_config.get('base-image', dist_config.get('pull', 'debian:12'))
        package_manager = dist_config.get('package-manager', 'apt')
        sources = dist_config.get('sources', [])
        
        # Get package manager configuration
        pm_config = self.get_package_manager_config(package_manager)
        update_command = pm_config.get('update-command', '')
        default_test_commands = pm_config.get('test-commands', [])
        
        # Get distribution-specific test commands (override package manager defaults)
        dist_test_commands = dist_config.get('test-commands', default_test_commands)
        
        dockerfile = f"FROM {base_image}\n\n"
        dockerfile += "# Mirror test for " + dist_name + "\n"
        dockerfile += "# Generated at " + datetime.now().isoformat() + "\n\n"
        
        if package_manager == 'apt':
            # Debian/Ubuntu
            dockerfile += "# Configure repositories\n"
            dockerfile += "RUN rm -f /etc/apt/sources.list.d/* && \\\n"
            dockerfile += "    echo 'Acquire::Languages \"none\";' > /etc/apt/apt.conf.d/99translations && \\\n"
            dockerfile += "    > /etc/apt/sources.list && \\\n"
            
            for source in sources:
                # Substitute variables in source
                substituted_source = self.substitute_variables(source)
                source_escaped = substituted_source.replace('"', '\\"')
                dockerfile += f'    echo "{source_escaped}" >> /etc/apt/sources.list && \\\n'
            
            dockerfile += "    cat /etc/apt/sources.list\n\n"
            
            # Use package manager update command or default
            if update_command:
                dockerfile += f"# Update package lists\n"
                dockerfile += f"RUN {update_command}\n\n"
            else:
                dockerfile += "# Update package lists\n"
                dockerfile += "RUN apt-get update\n\n"
            
            # Add test commands
            if dist_test_commands:
                dockerfile += "# Run test commands\n"
                dockerfile += "RUN "
                for i, cmd in enumerate(dist_test_commands):
                    substituted_cmd = self.substitute_variables(cmd)
                    if i > 0:
                        dockerfile += "    && "
                    dockerfile += f"{substituted_cmd} \\\n"
                dockerfile += "    && echo 'Repository test successful'\n"
            else:
                dockerfile += "# Basic repository test\n"
                dockerfile += "RUN apt-get install -y --no-install-recommends apt-utils && \\\n"
                dockerfile += "    && echo 'Repository test successful'\n"
            
        elif package_manager in ['yum', 'dnf']:
            # RHEL/CentOS/Rocky/Fedora
            dockerfile += "# Configure repositories\n"
            dockerfile += "RUN rm -f /etc/yum.repos.d/* && \\\n"
            
            # Define shell variables for repository configuration
            dockerfile += "    export releasever=$(rpm -q --qf '%{VERSION}' $(rpm -q --whatprovides redhat-release)) && \\\n"
            dockerfile += "    export basearch=$(uname -m) && \\\n"
            
            # Write repo configuration using echo and redirection
            repo_file = "/etc/yum.repos.d/mirror-test.repo"
            for source in sources:
                # Substitute variables in source
                substituted_source = self.substitute_variables(source)
                # Handle multi-line sources (YAML | syntax)
                if '\n' in substituted_source:
                    # Multi-line source - split into lines and echo each
                    lines = substituted_source.split('\n')
                    for line in lines:
                        if line.strip():  # Skip empty lines
                            escaped_line = line.replace('"', '\\"')
                            dockerfile += f'    echo "{escaped_line}" >> {repo_file} && \\\n'
                else:
                    # Single-line source - echo directly
                    escaped_line = substituted_source.replace('"', '\\"')
                    dockerfile += f'    echo "{escaped_line}" >> {repo_file} && \\\n'
            
            # Remove the trailing && and add final command
            dockerfile += f"    cat {repo_file}\n\n"
            
            # Use package manager update command or default
            if update_command:
                dockerfile += f"# Update package lists\n"
                dockerfile += f"RUN {update_command}\n\n"
            else:
                dockerfile += "# Update package lists\n"
                if package_manager == 'dnf':
                    dockerfile += "RUN dnf makecache\n\n"
                else:
                    dockerfile += "RUN yum makecache\n\n"
            
            # Add test commands
            if dist_test_commands:
                dockerfile += "# Run test commands\n"
                dockerfile += "RUN "
                for i, cmd in enumerate(dist_test_commands):
                    substituted_cmd = self.substitute_variables(cmd)
                    if i > 0:
                        dockerfile += "    && "
                    dockerfile += f"{substituted_cmd} \\\n"
                dockerfile += "    && echo 'Repository test successful'\n"
            else:
                dockerfile += "# Basic repository test\n"
                if package_manager == 'dnf':
                    dockerfile += "RUN dnf install -y dnf-utils && \\\n"
                else:
                    dockerfile += "RUN yum install -y yum-utils && \\\n"
                dockerfile += "    && echo 'Repository test successful'\n"
            
        elif package_manager == 'zypper':
            # openSUSE/SLES
            dockerfile += "# Configure repositories\n"
            dockerfile += "RUN rm -f /etc/zypp/repos.d/* && \\\n"
            
            repo_file = "/etc/zypp/repos.d/mirror-test.repo"
            dockerfile += f"    cat > {repo_file} << 'EOF'\n"
            for source in sources:
                # Substitute variables in source
                substituted_source = self.substitute_variables(source)
                # Handle multi-line sources (YAML | syntax)
                if '\n' in substituted_source:
                    # Multi-line source - write as-is
                    dockerfile += substituted_source + "\n"
                else:
                    # Single-line source - treat as repository section
                    dockerfile += substituted_source + "\n"
            dockerfile += "EOF\n\n"
            
            # Use package manager update command or default
            if update_command:
                dockerfile += f"# Update package lists\n"
                dockerfile += f"RUN {update_command}\n\n"
            else:
                dockerfile += "# Update package lists\n"
                dockerfile += "RUN zypper --non-interactive refresh\n\n"
            
            # Add test commands
            if dist_test_commands:
                dockerfile += "# Run test commands\n"
                dockerfile += "RUN "
                for i, cmd in enumerate(dist_test_commands):
                    substituted_cmd = self.substitute_variables(cmd)
                    if i > 0:
                        dockerfile += "    && "
                    dockerfile += f"{substituted_cmd} \\\n"
                dockerfile += "    && echo 'Repository test successful'\n"
            else:
                dockerfile += "# Basic repository test\n"
                dockerfile += "RUN zypper --non-interactive install -y zypper && \\\n"
                dockerfile += "    && echo 'Repository test successful'\n"
            
        elif package_manager == 'apk':
            # Alpine
            dockerfile += "# Configure repositories\n"
            dockerfile += "RUN > /etc/apk/repositories && \\\n"
            
            for source in sources:
                # Substitute variables in source
                substituted_source = self.substitute_variables(source)
                source_escaped = substituted_source.replace('"', '\\"')
                dockerfile += f'    echo "{source_escaped}" >> /etc/apk/repositories && \\\n'
            
            dockerfile += "    cat /etc/apk/repositories\n\n"
            
            # Use package manager update command or default
            if update_command:
                dockerfile += f"# Update package lists\n"
                dockerfile += f"RUN {update_command}\n\n"
            else:
                dockerfile += "# Update package lists\n"
                dockerfile += "RUN apk update\n\n"
            
            # Add test commands
            if dist_test_commands:
                dockerfile += "# Run test commands\n"
                dockerfile += "RUN "
                for i, cmd in enumerate(dist_test_commands):
                    substituted_cmd = self.substitute_variables(cmd)
                    if i > 0:
                        dockerfile += "    && "
                    dockerfile += f"{substituted_cmd} \\\n"
                dockerfile += "    && echo 'Repository test successful'\n"
            else:
                dockerfile += "# Basic repository test\n"
                dockerfile += "RUN apk add --no-cache curl && \\\n"
                dockerfile += "    && echo 'Repository test successful'\n"
        
        else:
            # Generic fallback
            dockerfile += f"# Unknown package manager: {package_manager}\n"
            dockerfile += "RUN echo 'Cannot test - unknown package manager'\n"
        
        # Add final test marker
        dockerfile += "\n# Final validation\n"
        dockerfile += "RUN echo 'All repository tests passed for " + dist_name + "'\n"
        
        return dockerfile
    
    def test_distribution(self, dist_name: str) -> Tuple[bool, str, str]:
        """Test a specific distribution's repository using podman build."""
        if dist_name not in self.config:
            logger.error(f"Distribution {dist_name} not found in configuration")
            return False, "", f"Distribution {dist_name} not configured"
        
        dist_config = self.config[dist_name]
        
        # Create build directory for this distribution
        build_path = os.path.join(self.build_dir, dist_name)
        os.makedirs(build_path, exist_ok=True)
        
        # Generate Dockerfile
        dockerfile_content = self.generate_dockerfile(dist_name, dist_config)
        dockerfile_path = os.path.join(build_path, "Dockerfile")
        
        with open(dockerfile_path, 'w') as f:
            f.write(dockerfile_content)
        
        # Save Dockerfile for debugging
        dockerfile_backup = os.path.join(build_path, f"Dockerfile.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        with open(dockerfile_backup, 'w') as f:
            f.write(dockerfile_content)
        
        # Run podman build
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        image_tag = f"mirror-test:{dist_name}-{timestamp}"
        build_cmd = [
            "podman", "build",
            "--no-cache",  # Always test fresh
            "-f", dockerfile_path,
            "-t", image_tag,
            "-t", f"mirror-test:{dist_name}",  # Also tag with simple name
            build_path
        ]
        
        logger.info(f"Testing {dist_name} repository using build process...")
        logger.debug(f"Build command: {' '.join(build_cmd)}")
        
        try:
            result = subprocess.run(
                build_cmd,
                capture_output=True,
                text=True,
                timeout=600  # 10 minute timeout
            )
        except subprocess.TimeoutExpired:
            logger.error(f"Build timeout for {dist_name}")
            return False, "", "Build process timeout (>10 minutes)"
        
        # Parse build output for success/failure
        success = result.returncode == 0
        
        # Extract meaningful information from build output
        stdout_lines = result.stdout.split('\n')
        stderr_lines = result.stderr.split('\n')
        
        # Log results
        log_file = os.path.join(self.log_dir, f"{dist_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
        with open(log_file, 'w') as f:
            f.write(f"Distribution: {dist_name}\n")
            f.write(f"Base Image: {dist_config.get('base-image', 'unknown')}\n")
            f.write(f"Package Manager: {dist_config.get('package-manager', 'unknown')}\n")
            f.write(f"Timestamp: {datetime.now().isoformat()}\n")
            f.write(f"Build Command: {' '.join(build_cmd)}\n")
            f.write(f"Return Code: {result.returncode}\n")
            f.write(f"\n--- DOCKERFILE ---\n{dockerfile_content}\n")
            f.write(f"\n--- BUILD OUTPUT ---\n{result.stdout}\n")
            f.write(f"\n--- BUILD ERRORS ---\n{result.stderr}\n")
        
        # Save latest log symlink
        latest_link = os.path.join(self.log_dir, f"{dist_name}_latest.log")
        if os.path.exists(latest_link):
            os.remove(latest_link)
        os.symlink(log_file, latest_link)
        
        # Clean up images to save space (optional)
        if self.cleanup_images:
            if success:
                # Remove both timestamped and simple tags for successful builds
                cleanup_cmd = ["podman", "rmi", "-f", image_tag, f"mirror-test:{dist_name}"]
                subprocess.run(cleanup_cmd, capture_output=True)
                logger.debug(f"Cleaned up images {image_tag} and mirror-test:{dist_name}")
            else:
                # For failed builds, clean up any dangling images that might have been created
                logger.debug(f"Build failed for {dist_name}, cleaning up any dangling images")
                # Clean up dangling images created during failed build
                dangling_cmd = ["podman", "image", "prune", "-f"]
                subprocess.run(dangling_cmd, capture_output=True)
        elif success:
            logger.info(f"Images {image_tag} and mirror-test:{dist_name} kept for inspection")
        else:
            logger.info(f"Failed build for {dist_name}, images not cleaned up for inspection")
        
        return success, result.stdout, result.stderr
    
    def cleanup_dangling_images(self):
        """Clean up dangling images created during failed builds."""
        try:
            # Clean up dangling images
            dangling_cmd = ["podman", "image", "prune", "-f"]
            result = subprocess.run(dangling_cmd, capture_output=True, text=True)
            if result.returncode == 0:
                logger.debug("Cleaned up dangling images")
            else:
                logger.warning(f"Failed to clean up dangling images: {result.stderr}")
        except Exception as e:
            logger.warning(f"Error cleaning up dangling images: {e}")
    
    def test_all(self) -> Dict:
        """Test all configured distributions."""
        results = {}
        for dist_name in self.get_distributions():
            success, stdout, stderr = self.test_distribution(dist_name)
            results[dist_name] = {
                'success': success,
                'stdout': stdout,
                'stderr': stderr,
                'timestamp': datetime.now().isoformat()
            }
            # Clean up dangling images after each test
            if not success:
                self.cleanup_dangling_images()
        return results
    
    def test_specific(self, distributions: List[str]) -> Dict:
        """Test specific distributions."""
        results = {}
        for dist_name in distributions:
            if dist_name in self.config:
                success, stdout, stderr = self.test_distribution(dist_name)
                results[dist_name] = {
                    'success': success,
                    'stdout': stdout,
                    'stderr': stderr,
                    'timestamp': datetime.now().isoformat()
                }
                # Clean up dangling images after each test
                if not success:
                    self.cleanup_dangling_images()
            else:
                logger.warning(f"Distribution {dist_name} not found in configuration")
                results[dist_name] = {
                    'success': False,
                    'stdout': '',
                    'stderr': f'Distribution {dist_name} not configured',
                    'timestamp': datetime.now().isoformat()
                }
        return results
    
    def get_latest_log(self, dist_name: str) -> Dict:
        """Get the latest log for a distribution."""
        # Use the instance's log directory, not the global one
        log_dir = getattr(self, 'log_dir', LOG_DIR)
        latest_log = os.path.join(log_dir, f"{dist_name}_latest.log")
        if not os.path.exists(latest_log):
            return {
                'error': f'No logs found for {dist_name}',
                'stdout': '',
                'stderr': '',
                'dockerfile': ''
            }
        
        with open(latest_log, 'r') as f:
            content = f.read()
        
        # Parse log content
        dockerfile_start = content.find('--- DOCKERFILE ---\n')
        stdout_start = content.find('--- BUILD OUTPUT ---\n')
        stderr_start = content.find('--- BUILD ERRORS ---\n')
        
        dockerfile = ''
        stdout = ''
        stderr = ''
        
        if dockerfile_start != -1 and stdout_start != -1:
            dockerfile = content[dockerfile_start + 19:stdout_start].strip()
        
        if stdout_start != -1 and stderr_start != -1:
            stdout = content[stdout_start + 21:stderr_start].strip()
            stderr = content[stderr_start + 21:].strip()
        
        return {
            'dockerfile': dockerfile,
            'stdout': stdout,
            'stderr': stderr,
            'full': content
        }
    
    def get_dockerfile(self, dist_name: str) -> str:
        """Get the current Dockerfile for a distribution."""
        if dist_name not in self.config:
            return f"# Distribution {dist_name} not configured"
        
        return self.generate_dockerfile(dist_name, self.config[dist_name])


class WebInterface:
    """Web interface for mirror testing."""
    
    def __init__(self, tester: MirrorTester, port: int = WEB_PORT):
        self.tester = tester
        self.port = port
        self.server = None
        self.thread = None
    
    def create_html(self) -> str:
        """Create the HTML interface."""
        # Filter out non-distribution keys (variables, package-managers, etc.)
        excluded_keys = {'variables', 'package-managers'}
        distributions = [key for key in self.tester.config.keys() if key not in excluded_keys]
        
        html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mirror Test - Repository Testing Interface</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
            min-height: 100vh;
            color: #333;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }
        
        .header {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        }
        
        h1 {
            font-size: 2.5em;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 10px;
        }
        
        .subtitle {
            color: #666;
            font-size: 1.1em;
        }
        
        .main-content {
            display: grid;
            grid-template-columns: 300px 1fr;
            gap: 20px;
            margin-bottom: 20px;
        }
        
        .sidebar {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            height: fit-content;
        }
        
        .content-area {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        }
        
        .control-group {
            margin-bottom: 20px;
        }
        
        .control-group label {
            display: block;
            margin-bottom: 8px;
            font-weight: 600;
            color: #444;
        }
        
        select, button {
            width: 100%;
            padding: 12px;
            border-radius: 8px;
            border: 2px solid #e0e0e0;
            font-size: 15px;
            transition: all 0.3s;
            background: white;
        }
        
        select {
            cursor: pointer;
        }
        
        select:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }
        
        button {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            cursor: pointer;
            font-weight: 600;
            margin-bottom: 10px;
            position: relative;
            overflow: hidden;
        }
        
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
        }
        
        button:active {
            transform: translateY(0);
        }
        
        button:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }
        
        .tabs {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            border-bottom: 2px solid #e0e0e0;
        }
        
        .tab {
            padding: 12px 20px;
            background: none;
            border: none;
            color: #666;
            cursor: pointer;
            font-weight: 500;
            transition: all 0.3s;
            position: relative;
        }
        
        .tab:hover {
            color: #667eea;
        }
        
        .tab.active {
            color: #667eea;
        }
        
        .tab.active::after {
            content: '';
            position: absolute;
            bottom: -2px;
            left: 0;
            right: 0;
            height: 2px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }
        
        .tab-content {
            display: none;
            animation: fadeIn 0.3s;
        }
        
        .tab-content.active {
            display: block;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .log-content {
            background: #1e1e1e;
            color: #d4d4d4;
            padding: 20px;
            border-radius: 10px;
            overflow-x: auto;
            max-height: 600px;
            overflow-y: auto;
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            font-size: 13px;
            line-height: 1.6;
            white-space: pre-wrap;
            word-wrap: break-word;
        }
        
        .log-content::-webkit-scrollbar {
            width: 10px;
        }
        
        .log-content::-webkit-scrollbar-track {
            background: #2e2e2e;
        }
        
        .log-content::-webkit-scrollbar-thumb {
            background: #555;
            border-radius: 5px;
        }
        
        .dockerfile {
            background: #2d2d30;
            color: #cccccc;
        }
        
        .dockerfile .keyword {
            color: #569cd6;
            font-weight: bold;
        }
        
        .status {
            padding: 15px;
            border-radius: 10px;
            margin-bottom: 20px;
            display: none;
            animation: slideIn 0.3s ease;
            font-weight: 500;
        }
        
        @keyframes slideIn {
            from { opacity: 0; transform: translateY(-10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .status.success {
            background: linear-gradient(135deg, #84fab0 0%, #8fd3f4 100%);
            color: #0a4f3c;
        }
        
        .status.error {
            background: linear-gradient(135deg, #ff9a9e 0%, #fad0c4 100%);
            color: #721c24;
        }
        
        .status.info {
            background: linear-gradient(135deg, #a8edea 0%, #fed6e3 100%);
            color: #0c5460;
        }
        
        .spinner {
            display: none;
            width: 20px;
            height: 20px;
            border: 3px solid rgba(255,255,255,0.3);
            border-top: 3px solid white;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            position: absolute;
            right: 15px;
            top: 50%;
            transform: translateY(-50%);
        }
        
        @keyframes spin {
            0% { transform: translateY(-50%) rotate(0deg); }
            100% { transform: translateY(-50%) rotate(360deg); }
        }
        
        .loading { opacity: 0.6; }
        
        .build-step {
            margin: 10px 0;
            padding: 10px;
            background: #2d2d30;
            border-left: 3px solid #569cd6;
            border-radius: 5px;
        }
        
        .build-success {
            border-left-color: #4ec9b0;
        }
        
        .build-error {
            border-left-color: #f14c4c;
        }
        
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        
        .stat-card {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 10px;
            text-align: center;
        }
        
        .stat-value {
            font-size: 2em;
            font-weight: bold;
            margin-bottom: 5px;
        }
        
        .stat-label {
            opacity: 0.9;
            font-size: 0.9em;
        }
        
        .success-card {
            background: linear-gradient(135deg, #4ec9b0 0%, #44a08d 100%) !important;
        }
        
        .error-card {
            background: linear-gradient(135deg, #f14c4c 0%, #c44569 100%) !important;
        }
        
        .build-panels {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-top: 30px;
        }
        
        .build-panel {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 20px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            border: 1px solid rgba(255, 255, 255, 0.2);
        }
        
        .build-panel h3 {
            margin: 0 0 15px 0;
            font-size: 1.1em;
            color: #444;
            border-bottom: 2px solid #e0e0e0;
            padding-bottom: 8px;
        }
        
        .build-list {
            max-height: 300px;
            overflow-y: auto;
            padding: 0 5px;
        }
        
        .build-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 10px;
            margin: 5px 0;
            border-radius: 6px;
            font-size: 0.9em;
            transition: all 0.2s;
            width: 95%;
            box-sizing: border-box;
            cursor: pointer;
            user-select: none;
        }
        
        .success-item {
            background: linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%);
            border-left: 4px solid #28a745;
            color: #155724;
        }
        
        .failed-item {
            background: linear-gradient(135deg, #f8d7da 0%, #f5c6cb 100%);
            border-left: 4px solid #dc3545;
            color: #721c24;
        }
        
        .build-item:hover {
            transform: translateX(2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            opacity: 0.9;
        }
        
        .build-item:active {
            transform: translateX(1px);
            box-shadow: 0 2px 6px rgba(0,0,0,0.2);
        }
        
        .build-dist {
            font-weight: 600;
            text-transform: capitalize;
            flex: 1;
            min-width: 0;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        
        .build-date {
            font-size: 0.8em;
            opacity: 0.8;
            flex-shrink: 0;
            margin-left: 8px;
        }
        
        .no-builds {
            text-align: center;
            color: #666;
            font-style: italic;
            padding: 20px;
        }
        
        .build-list::-webkit-scrollbar {
            width: 6px;
        }
        
        .build-list::-webkit-scrollbar-track {
            background: #f1f1f1;
            border-radius: 3px;
        }
        
        .build-list::-webkit-scrollbar-thumb {
            background: #c1c1c1;
            border-radius: 3px;
        }
        
        .build-list::-webkit-scrollbar-thumb:hover {
            background: #a8a8a8;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔧 Mirror Test</h1>
            <div class="subtitle">Linux Repository Mirror Testing via Container Builds</div>
        </div>
        
        <div id="status" class="status"></div>
        
        <div class="main-content">
            <div class="sidebar">
                <div class="control-group">
                    <label for="distribution">Select Distribution:</label>
                    <select id="distribution" multiple size="6">
                        <option value="all" selected>All Distributions</option>
                        """ + ''.join([f'<option value="{d}">{d.title()}</option>' for d in distributions]) + """
                    </select>
                </div>
                
                <button onclick="runTest()" id="testBtn">
                    Run Build Test
                    <span class="spinner" id="testSpinner"></span>
                </button>
                
                <button onclick="loadLogs()" id="logBtn">
                    Load Build Logs
                    <span class="spinner" id="logSpinner"></span>
                </button>
                
                <button onclick="viewDockerfile()">
                    View Dockerfile
                </button>
                
                <button onclick="refreshDistributions()">
                    Refresh List
                </button>
                
                <div class="stats" id="stats" style="margin-top: 20px;">
                    <!-- Stats will be loaded here -->
                </div>
            </div>
            
            <div class="content-area">
                <div class="tabs">
                    <button class="tab active" onclick="switchTab('output')">Build Output</button>
                    <button class="tab" onclick="switchTab('errors')">Errors</button>
                    <button class="tab" onclick="switchTab('dockerfile')">Dockerfile</button>
                    <button class="tab" onclick="switchTab('full')">Full Log</button>
                </div>
                
                <div id="output" class="tab-content active">
                    <pre class="log-content" id="stdout">Select a distribution and click "Run Build Test" to see the build process...</pre>
                </div>
                
                <div id="errors" class="tab-content">
                    <pre class="log-content" id="stderr">No errors to display...</pre>
                </div>
                
                <div id="dockerfile" class="tab-content">
                    <pre class="log-content dockerfile" id="dockerfileContent">Dockerfile will appear here...</pre>
                </div>
                
                <div id="full" class="tab-content">
                    <pre class="log-content" id="fullLog">Complete log will appear here...</pre>
                </div>
                
                <!-- Build Status Panels -->
                <div class="build-panels" style="margin-top: 30px;">
                    <div class="build-panel success-panel">
                        <h3>✅ Successful Builds</h3>
                        <div class="build-list" id="successful-builds">
                            <!-- Successful builds will be loaded here -->
                        </div>
                    </div>
                    
                    <div class="build-panel failed-panel">
                        <h3>❌ Failed Builds</h3>
                        <div class="build-list" id="failed-builds">
                            <!-- Failed builds will be loaded here -->
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        let currentTab = 'output';
        
        function switchTab(tab) {
            // Update tab buttons
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            event.target.classList.add('active');
            
            // Update content
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            document.getElementById(tab).classList.add('active');
            
            currentTab = tab;
        }
        
        function showStatus(message, type) {
            const status = document.getElementById('status');
            status.className = 'status ' + type;
            status.textContent = message;
            status.style.display = 'block';
            
            if (type !== 'error') {
                setTimeout(() => {
                    status.style.display = 'none';
                }, 5000);
            }
        }
        
        function showSpinner(spinnerId, show) {
            document.getElementById(spinnerId).style.display = show ? 'block' : 'none';
        }
        
        async function runTest() {
            const select = document.getElementById('distribution');
            const selected = Array.from(select.selectedOptions).map(opt => opt.value);
            
            if (selected.length === 0) {
                showStatus('Please select at least one distribution', 'error');
                return;
            }
            
            document.getElementById('testBtn').disabled = true;
            showSpinner('testSpinner', true);
            showStatus('Running build tests... This may take a few minutes.', 'info');
            
            try {
                const response = await fetch('/api/test', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({distributions: selected})
                });
                
                const data = await response.json();
                
                let successCount = 0;
                let failCount = 0;
                
                for (const [dist, result] of Object.entries(data.results)) {
                    if (result.success) successCount++;
                    else failCount++;
                }
                
                if (failCount === 0) {
                    showStatus(`All ${successCount} build tests passed successfully!`, 'success');
                } else {
                    showStatus(`${successCount} passed, ${failCount} failed. Check logs for details.`, 'error');
                }
                
                // Auto-load logs for first tested distribution
                if (selected[0] !== 'all' && selected.length === 1) {
                    await loadLogs();
                }
                
                // Update stats
                updateStats();
                
            } catch (error) {
                showStatus('Error running tests: ' + error.message, 'error');
            } finally {
                document.getElementById('testBtn').disabled = false;
                showSpinner('testSpinner', false);
            }
        }
        
        async function loadLogs() {
            const select = document.getElementById('distribution');
            const selected = Array.from(select.selectedOptions).map(opt => opt.value);
            
            if (selected.length === 0 || selected[0] === 'all') {
                showStatus('Please select a specific distribution to view logs', 'error');
                return;
            }
            
            document.getElementById('logBtn').disabled = true;
            showSpinner('logSpinner', true);
            
            const stdout = document.getElementById('stdout');
            const stderr = document.getElementById('stderr');
            const dockerfileContent = document.getElementById('dockerfileContent');
            const fullLog = document.getElementById('fullLog');
            
            stdout.classList.add('loading');
            stderr.classList.add('loading');
            
            try {
                const response = await fetch('/api/logs/' + selected[0]);
                const data = await response.json();
                
                stdout.textContent = data.stdout || 'No build output available';
                stderr.textContent = data.stderr || 'No errors';
                dockerfileContent.textContent = data.dockerfile || 'No Dockerfile available';
                fullLog.textContent = data.full || 'No complete log available';
                
                // Highlight Dockerfile syntax
                highlightDockerfile();
                
                showStatus('Build logs loaded successfully', 'success');
                
                // Update stats to reflect any changes
                updateStats();
            } catch (error) {
                showStatus('Error loading logs: ' + error.message, 'error');
                stdout.textContent = 'Error loading logs';
                stderr.textContent = error.message;
            } finally {
                document.getElementById('logBtn').disabled = false;
                showSpinner('logSpinner', false);
                stdout.classList.remove('loading');
                stderr.classList.remove('loading');
            }
        }
        
        async function viewDockerfile() {
            const select = document.getElementById('distribution');
            const selected = Array.from(select.selectedOptions).map(opt => opt.value);
            
            if (selected.length === 0 || selected[0] === 'all') {
                showStatus('Please select a specific distribution', 'error');
                return;
            }
            
            try {
                const response = await fetch('/api/dockerfile/' + selected[0]);
                const data = await response.json();
                
                document.getElementById('dockerfileContent').textContent = data.dockerfile;
                highlightDockerfile();
                
                // Switch to Dockerfile tab
                document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.tab')[2].classList.add('active');
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                document.getElementById('dockerfile').classList.add('active');
                
                showStatus('Dockerfile generated', 'success');
                
                // Update stats to reflect any changes
                updateStats();
            } catch (error) {
                showStatus('Error generating Dockerfile: ' + error.message, 'error');
            }
        }
        
        function highlightDockerfile() {
            const content = document.getElementById('dockerfileContent');
            let text = content.textContent;
            
            // Simple syntax highlighting for Dockerfiles
            text = text.replace(/(FROM|RUN|COPY|ADD|ENV|WORKDIR|EXPOSE|CMD|ENTRYPOINT|ARG|LABEL|USER|VOLUME|STOPSIGNAL|HEALTHCHECK|SHELL)(\s)/g, 
                '<span class="keyword">$1</span>$2');
            
            content.innerHTML = text;
        }
        
        async function refreshDistributions() {
            try {
                const response = await fetch('/api/distributions');
                const data = await response.json();
                
                const select = document.getElementById('distribution');
                select.innerHTML = '<option value="all">All Distributions</option>';
                
                data.distributions.forEach(dist => {
                    const option = document.createElement('option');
                    option.value = dist;
                    option.textContent = dist.charAt(0).toUpperCase() + dist.slice(1);
                    select.appendChild(option);
                });
                
                showStatus('Distribution list refreshed', 'success');
                updateStats();
            } catch (error) {
                showStatus('Error refreshing distributions: ' + error.message, 'error');
            }
        }
        
        async function updateStats() {
            try {
                const response = await fetch('/api/stats');
                const data = await response.json();
                
                const statsHtml = `
                    <div class="stat-card">
                        <div class="stat-value">${data.total}</div>
                        <div class="stat-label">Total Configured</div>
                    </div>
                    <div class="stat-card">
                        <div class="stat-value">${data.tested}</div>
                        <div class="stat-label">Recently Tested</div>
                    </div>
                    <div class="stat-card success-card">
                        <div class="stat-value">${data.successful.length}</div>
                        <div class="stat-label">Successful Builds</div>
                    </div>
                    <div class="stat-card error-card">
                        <div class="stat-value">${data.failed.length}</div>
                        <div class="stat-label">Failed Builds</div>
                    </div>
                `;
                
                document.getElementById('stats').innerHTML = statsHtml;
                
                // Update the detailed panels
                updateBuildPanels(data.successful, data.failed);
            } catch (error) {
                console.error('Error loading stats:', error);
            }
        }
        
        function updateBuildPanels(successful, failed) {
            // Update successful builds panel
            const successfulHtml = successful.length > 0 ? 
                successful.map(item => `
                    <div class="build-item success-item" onclick="loadLogsForDistribution('${item.dist}')" title="Click to load logs for ${item.dist}">
                        <div class="build-dist">${item.dist}</div>
                        <div class="build-date">${item.date}</div>
                    </div>
                `).join('') : 
                '<div class="no-builds">No successful builds yet</div>';
            
            document.getElementById('successful-builds').innerHTML = successfulHtml;
            
            // Update failed builds panel
            const failedHtml = failed.length > 0 ? 
                failed.map(item => `
                    <div class="build-item failed-item" onclick="loadLogsForDistribution('${item.dist}')" title="Click to load logs for ${item.dist}">
                        <div class="build-dist">${item.dist}</div>
                        <div class="build-date">${item.date}</div>
                    </div>
                `).join('') : 
                '<div class="no-builds">No failed builds</div>';
            
            document.getElementById('failed-builds').innerHTML = failedHtml;
        }
        
        function loadLogsForDistribution(distribution) {
            // Select the distribution in the dropdown
            const select = document.getElementById('distribution');
            const options = select.options;
            
            // Clear current selections
            for (let i = 0; i < options.length; i++) {
                options[i].selected = false;
            }
            
            // Find and select the clicked distribution
            for (let i = 0; i < options.length; i++) {
                if (options[i].value === distribution) {
                    options[i].selected = true;
                    break;
                }
            }
            
            // Load the logs for this distribution
            loadLogs();
            
            // Show a brief status message
            showStatus(`Loading logs for ${distribution}...`, 'info');
        }
        
        // Auto-refresh stats on page load
        window.addEventListener('load', () => {
            updateStats();
            
            // Check for URL parameters
            const urlParams = new URLSearchParams(window.location.search);
            const dist = urlParams.get('dist');
            if (dist) {
                document.getElementById('distribution').value = dist;
                loadLogs();
            }
            
            // Auto-refresh stats every 30 seconds to keep them up-to-date
            setInterval(updateStats, 30000);
        });
        
        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => {
            if (e.ctrlKey || e.metaKey) {
                switch(e.key) {
                    case 'r':
                        e.preventDefault();
                        runTest();
                        break;
                    case 'l':
                        e.preventDefault();
                        loadLogs();
                        break;
                    case 'd':
                        e.preventDefault();
                        viewDockerfile();
                        break;
                }
            }
        });
    </script>
</body>
</html>"""
        return html
    
    def start(self):
        """Start the web server."""
        class RequestHandler(SimpleHTTPRequestHandler):
            tester = self.tester
            parent = self
            
            def do_GET(self):
                if self.path == '/':
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html')
                    self.end_headers()
                    self.wfile.write(self.parent.create_html().encode())
                    
                elif self.path == '/api/distributions':
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    # Filter out non-distribution keys (variables, package-managers, etc.)
                    excluded_keys = {'variables', 'package-managers'}
                    distributions = [key for key in self.tester.config.keys() if key not in excluded_keys]
                    self.wfile.write(json.dumps({'distributions': distributions}).encode())
                    
                elif self.path.startswith('/api/logs/'):
                    dist_name = self.path.split('/')[-1]
                    logs = self.tester.get_latest_log(dist_name)
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(logs).encode())
                    
                elif self.path.startswith('/api/dockerfile/'):
                    dist_name = self.path.split('/')[-1]
                    dockerfile = self.tester.get_dockerfile(dist_name)
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'dockerfile': dockerfile}).encode())
                    
                elif self.path == '/api/debug-stats':
                    # Debug endpoint to show what the logic is detecting
                    excluded_keys = {'variables', 'package-managers'}
                    distributions = [key for key in self.tester.config.keys() if key not in excluded_keys]
                    debug_info = []
                    
                    for dist in distributions:
                        latest_log_path = os.path.join(self.tester.log_dir, f"{dist}_latest.log")
                        if os.path.exists(latest_log_path):
                            try:
                                with open(latest_log_path, 'r', encoding='utf-8') as f:
                                    log_content = f.read()
                                
                                log_lower = log_content.lower()
                                
                                # Check what indicators are found
                                success_found = [ind for ind in [
                                    'all repository tests passed', 'build completed successfully',
                                    'exit code: 0', 'return code: 0', 'build finished successfully',
                                    'test completed successfully', 'mirror test completed'
                                ] if ind in log_lower]
                                
                                failure_found = [ind for ind in [
                                    'exit code: 1', 'exit code: 2', 'exit code: 100', 'exit code: 127',
                                    'return code: 1', 'return code: 2', 'return code: 100', 'return code: 127',
                                    'build failed', 'test failed', 'mirror test failed', 'fatal error',
                                    'critical error', 'build error:', 'test error:',
                                    'command failed with exit code', 'podman build failed', 'docker build failed',
                                    'exit status 100', 'exit status 1', 'exit status 2', 'exit status 127',
                                    'error: building at step', 'while running runtime: exit status',
                                    'error: failed to solve', 'failed to build', 'build process failed'
                                ] if ind in log_lower]
                                
                                # Check last few lines
                                log_lines = log_content.split('\n')
                                last_lines = log_lines[-5:] if len(log_lines) > 5 else log_lines
                                last_content = '\n'.join(last_lines)
                                
                                debug_info.append({
                                    'dist': dist,
                                    'success_indicators': success_found,
                                    'failure_indicators': failure_found,
                                    'last_lines': last_content,
                                    'log_size': len(log_content)
                                })
                            except Exception as e:
                                debug_info.append({
                                    'dist': dist,
                                    'error': str(e)
                                })
                    
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(debug_info, indent=2).encode())
                    
                elif self.path == '/api/stats':
                    # Count distributions and recent tests (exclude non-distribution keys)
                    excluded_keys = {'variables', 'package-managers'}
                    distributions = [key for key in self.tester.config.keys() if key not in excluded_keys]
                    total = len(distributions)
                    tested = 0
                    successful = []
                    failed = []
                    
                    for dist in distributions:
                        latest_log_path = os.path.join(self.tester.log_dir, f"{dist}_latest.log")
                        if os.path.exists(latest_log_path):
                            tested += 1
                            
                            # Read the latest log to determine success/failure
                            try:
                                with open(latest_log_path, 'r', encoding='utf-8') as f:
                                    log_content = f.read()
                                
                                # Get file modification time as test date
                                test_date = datetime.fromtimestamp(os.path.getmtime(latest_log_path)).strftime('%Y-%m-%d %H:%M')
                                
                                # More sophisticated success/failure detection
                                log_lower = log_content.lower()
                                
                                # Check for explicit success indicators
                                success_indicators = [
                                    'all repository tests passed',
                                    'build completed successfully',
                                    'exit code: 0',
                                    'return code: 0',
                                    'build finished successfully',
                                    'test completed successfully',
                                    'mirror test completed'
                                ]
                                
                                # Check for explicit failure indicators (more specific)
                                failure_indicators = [
                                    'exit code: 1',
                                    'exit code: 2', 
                                    'exit code: 100',
                                    'exit code: 127',
                                    'return code: 1',
                                    'return code: 2',
                                    'return code: 100',
                                    'return code: 127',
                                    'build failed',
                                    'test failed',
                                    'mirror test failed',
                                    'fatal error',
                                    'critical error',
                                    'build error:',
                                    'test error:',
                                    'command failed with exit code',
                                    'podman build failed',
                                    'docker build failed',
                                    'exit status 100',
                                    'exit status 1',
                                    'exit status 2',
                                    'exit status 127',
                                    'error: building at step',
                                    'while running runtime: exit status',
                                    'error: failed to solve',
                                    'failed to build',
                                    'build process failed'
                                ]
                                
                                # Check for success and failure indicators
                                is_success = any(indicator in log_lower for indicator in success_indicators)
                                is_failure = any(indicator in log_lower for indicator in failure_indicators)
                                
                                # Priority: Failure indicators override success indicators
                                # This handles cases where a build might have success messages but ultimately failed
                                if is_failure:
                                    failed.append({'dist': dist, 'date': test_date})
                                elif is_success:
                                    successful.append({'dist': dist, 'date': test_date})
                                else:
                                    # If unclear, analyze the log more carefully
                                    log_lines = log_content.split('\n')
                                    
                                    # Check for build container errors in the log
                                    has_container_error = any('error: building at step' in line.lower() or 
                                                            'while running runtime: exit status' in line.lower() or
                                                            'failed to solve' in line.lower() for line in log_lines)
                                    
                                    # Check the last few lines for final status
                                    last_lines = log_lines[-15:] if len(log_lines) > 15 else log_lines
                                    last_content = '\n'.join(last_lines).lower()
                                    
                                    # Look for completion patterns in the end
                                    has_completion = any(pattern in last_content for pattern in [
                                        'build completed', 'test completed', 'finished successfully',
                                        'all tests passed', 'mirror test completed', 'repository test successful'
                                    ])
                                    
                                    # If we have container errors, it's a failure
                                    if has_container_error:
                                        failed.append({'dist': dist, 'date': test_date})
                                    # If we have completion indicators, it's successful
                                    elif has_completion:
                                        successful.append({'dist': dist, 'date': test_date})
                                    else:
                                        # Default to failed if we can't determine success
                                        failed.append({'dist': dist, 'date': test_date})
                                        
                            except Exception as e:
                                # If we can't read the log, assume it's a failure
                                failed.append({'dist': dist, 'date': 'Unknown'})
                    
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        'total': total,
                        'tested': tested,
                        'successful': successful,
                        'failed': failed
                    }).encode())
                    
                else:
                    self.send_error(404)
            
            def do_POST(self):
                if self.path == '/api/test':
                    content_length = int(self.headers['Content-Length'])
                    post_data = self.rfile.read(content_length)
                    data = json.loads(post_data.decode())
                    
                    distributions = data.get('distributions', [])
                    
                    if 'all' in distributions:
                        results = self.tester.test_all()
                    else:
                        results = self.tester.test_specific(distributions)
                    
                    success = all(r['success'] for r in results.values())
                    
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        'success': success,
                        'results': results
                    }).encode())
                else:
                    self.send_error(404)
            
            def log_message(self, format, *args):
                # Suppress default logging
                pass
        
        self.server = HTTPServer(('', self.port), RequestHandler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()
        
        logger.info(f"Web interface started on http://localhost:{self.port}")
        print(f"\n🌐 Web interface available at: http://localhost:{self.port}")
        print(f"📝 Build logs saved to: {self.tester.log_dir}")
        print(f"🔧 Dockerfiles saved to: {self.tester.build_dir}\n")
    
    def stop(self):
        """Stop the web server."""
        if self.server:
            self.server.shutdown()
            self.thread.join()


def run_simple_cli(tester):
    """Simple text-based CLI fallback when curses fails."""
    print("\n" + "="*60)
    print("Mirror Test - Simple Text Interface")
    print("="*60)
    
    while True:
        print("\nAvailable commands:")
        print("1. Test all distributions")
        print("2. Test specific distribution")
        print("3. List distributions")
        print("4. View logs")
        print("5. View Dockerfile")
        print("6. Exit")
        
        try:
            choice = input("\nEnter your choice (1-6): ").strip()
            
            if choice == '1':
                print("\nTesting all distributions...")
                results = tester.test_all()
                print("\nResults:")
                for dist, result in results.items():
                    status = "✓ PASSED" if result['success'] else "✗ FAILED"
                    print(f"  {dist}: {status}")
                    
            elif choice == '2':
                distributions = tester.get_distributions()
                print(f"\nAvailable distributions: {', '.join(distributions)}")
                dist = input("Enter distribution name: ").strip()
                if dist in distributions:
                    print(f"\nTesting {dist}...")
                    success, stdout, stderr = tester.test_distribution(dist)
                    status = "✓ PASSED" if success else "✗ FAILED"
                    print(f"Result: {status}")
                else:
                    print(f"Distribution '{dist}' not found")
                    
            elif choice == '3':
                distributions = tester.get_distributions()
                print(f"\nConfigured distributions: {', '.join(distributions)}")
                
            elif choice == '4':
                distributions = tester.get_distributions()
                print(f"\nAvailable distributions: {', '.join(distributions)}")
                dist = input("Enter distribution name: ").strip()
                if dist in distributions:
                    logs = tester.get_latest_log(dist)
                    print(f"\nLogs for {dist}:")
                    print("-" * 40)
                    print(logs.get('full', 'No logs available'))
                else:
                    print(f"Distribution '{dist}' not found")
                    
            elif choice == '5':
                distributions = tester.get_distributions()
                print(f"\nAvailable distributions: {', '.join(distributions)}")
                dist = input("Enter distribution name: ").strip()
                if dist in distributions:
                    dockerfile = tester.get_dockerfile(dist)
                    print(f"\nDockerfile for {dist}:")
                    print("-" * 40)
                    print(dockerfile)
                else:
                    print(f"Distribution '{dist}' not found")
                    
            elif choice == '6':
                print("Goodbye!")
                break
                
            else:
                print("Invalid choice. Please enter 1-6.")
                
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")




# TUI support removed


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Test local repository mirrors for Linux distributions using Podman builds',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  mirror-test                     # Test all configured distributions
  mirror-test debian              # Test only Debian
  mirror-test debian ubuntu       # Test Debian and Ubuntu
  mirror-test gui                 # Launch web interface
  mirror-test cli                 # Launch simple CLI interface
  mirror-test logs debian         # Show latest logs for Debian
  mirror-test dockerfile debian   # Show generated Dockerfile for Debian
  mirror-test --config /path/to/config.yaml  # Use custom config file
        """
    )
    
    parser.add_argument('command', nargs='*', default=['all'],
                       help='Command or distribution(s) to test')
    parser.add_argument('--config', default=None,
                       help='Path to configuration file')
    parser.add_argument('--port', type=int, default=WEB_PORT,
                       help='Port for web interface (default: 8080)')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose output')
    parser.add_argument('--no-cleanup', action='store_true',
                       help='Do not clean up images after successful builds')
    parser.add_argument('--timeout', type=int, default=600,
                       help='Build timeout in seconds (default: 600)')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Note: User-level podman is supported, no root requirement
    logger.info("Using user-level podman (no root required)")
    
    # Check for podman
    if shutil.which('podman') is None:
        logger.error("Error: podman is not installed or not in PATH")
        sys.exit(1)
    
    # Initialize tester
    tester = MirrorTester(args.config, cleanup_images=not args.no_cleanup)
    
    # Handle commands
    if not args.command or args.command[0] == 'all':
        # Test all distributions
        print("Testing all configured distributions via build process...")
        print("This may take several minutes depending on your mirror speed.\n")
        results = tester.test_all()
        
        print("\n" + "="*60)
        print("BUILD TEST RESULTS:")
        print("="*60)
        for dist, result in results.items():
            status = "✓ PASSED" if result['success'] else "✗ FAILED"
            print(f"{dist.ljust(20)} {status}")
            if not result['success'] and result['stderr']:
                # Extract meaningful error from build output
                error_lines = result['stderr'].split('\n')
                for line in error_lines:
                    if 'error' in line.lower() or 'failed' in line.lower():
                        print(f"  └─ {line.strip()[:80]}")
                        break
        print("="*60)
        
    elif args.command[0] == 'gui':
        # Launch web interface
        web = WebInterface(tester, args.port)
        web.start()
        
        print("Press Ctrl+C to stop the server...")
        print("\nKeyboard shortcuts in web interface:")
        print("  Ctrl+R - Run build test")
        print("  Ctrl+L - Load logs")
        print("  Ctrl+D - View Dockerfile")
        
        try:
            webbrowser.open(f'http://localhost:{args.port}')
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down web server...")
            web.stop()
    
    elif args.command[0] == 'cli':
        # Launch simple CLI interface
        print(" support has been removed. Using simple CLI interface...")
        run_simple_cli(tester)
            
            
    elif args.command[0] == 'list':
        # List all configured distributions
        print("Configured distributions:")
        print("-" * 60)
        print(f"{'Distribution':<20} {'Base Image':<20} {'Package Manager':<15}")
        print("-" * 60)
        
        distributions = tester.get_distributions()
        if not distributions:
            print("No distributions configured")
        else:
            for dist_name in sorted(distributions):
                dist_config = tester.config[dist_name]
                base_image = dist_config.get('base-image', dist_config.get('pull', 'unknown'))
                package_manager = dist_config.get('package-manager', 'unknown')
                print(f"{dist_name:<20} {base_image:<20} {package_manager:<15}")
        
        print(f"\nTotal: {len(distributions)} distributions")
        
    elif args.command[0] == 'variables':
        # Show configured variables and their expanded values
        print("Configuration variables:")
        print("-" * 40)
        
        if 'variables' in tester.config:
            for var_name, var_value in tester.config['variables'].items():
                # Expand variables
                expanded_value = tester.substitute_variables(str(var_value))
                print(f"{var_name:<20} = {expanded_value}")
        else:
            print("No variables configured")
        
        print(f"\nTotal: {len(tester.config.get('variables', {}))} variables")
        
    elif args.command[0] == 'validate':
        # Validate configuration file syntax
        print("Validating configuration...")
        
        try:
            # Test loading configuration
            test_config = tester.load_config()
            
            # Check for required sections
            if 'variables' not in test_config:
                print("⚠️  Warning: No variables section found")
            else:
                print("✓ Variables section found")
            
            if 'package-managers' not in test_config:
                print("⚠️  Warning: No package-managers section found")
            else:
                print("✓ Package-managers section found")
            
            # Check distributions
            distributions = tester.get_distributions()
            if not distributions:
                print("⚠️  Warning: No distributions configured")
            else:
                print(f"✓ {len(distributions)} distributions configured")
                
                # Validate each distribution
                for dist_name in distributions:
                    dist_config = test_config[dist_name]
                    required_fields = ['base-image', 'package-manager', 'sources']
                    missing_fields = [field for field in required_fields if field not in dist_config]
                    
                    if missing_fields:
                        print(f"⚠️  Warning: {dist_name} missing fields: {', '.join(missing_fields)}")
                    else:
                        print(f"✓ {dist_name} configuration valid")
            
            print("\n✓ Configuration is valid")
            
        except Exception as e:
            print(f"✗ Configuration validation failed: {e}")
            sys.exit(1)
            
    elif args.command[0] == 'cleanup':
        # Clean up all mirror-test images and dangling images
        print("Cleaning up all mirror-test images...")
        
        # First, clean up tagged mirror-test images
        cleanup_cmd = ["podman", "images", "-q", "--filter", "reference=mirror-test:*"]
        result = subprocess.run(cleanup_cmd, capture_output=True, text=True)
        
        tagged_count = 0
        if result.stdout:
            images = result.stdout.strip().split('\n')
            for image_id in images:
                if image_id:
                    remove_cmd = ["podman", "rmi", "-f", image_id]
                    rm_result = subprocess.run(remove_cmd, capture_output=True, text=True)
                    if rm_result.returncode == 0:
                        print(f"  ✓ Removed tagged image {image_id[:12]}")
                        tagged_count += 1
                    else:
                        print(f"  ✗ Failed to remove {image_id[:12]}: {rm_result.stderr}")
        
        # Clean up dangling images (untagged images)
        print("\nCleaning up dangling images...")
        dangling_cmd = ["podman", "images", "-q", "--filter", "dangling=true"]
        dangling_result = subprocess.run(dangling_cmd, capture_output=True, text=True)
        
        dangling_count = 0
        if dangling_result.stdout:
            dangling_images = dangling_result.stdout.strip().split('\n')
            for image_id in dangling_images:
                if image_id:
                    remove_cmd = ["podman", "rmi", "-f", image_id]
                    rm_result = subprocess.run(remove_cmd, capture_output=True, text=True)
                    if rm_result.returncode == 0:
                        print(f"  ✓ Removed dangling image {image_id[:12]}")
                        dangling_count += 1
                    else:
                        print(f"  ✗ Failed to remove dangling {image_id[:12]}: {rm_result.stderr}")
        
        # Also prune build cache
        print("\nPruning build cache...")
        prune_cmd = ["podman", "system", "prune", "-f", "--filter", "until=1h"]
        subprocess.run(prune_cmd, capture_output=True)
        print("Build cache pruned")
        
        print(f"\nCleaned up {tagged_count} tagged images and {dangling_count} dangling images")
            
    elif args.command[0] == 'logs':
        # Show logs for specific distribution
        if len(args.command) < 2:
            print("Error: Please specify a distribution for logs")
            sys.exit(1)
            
        dist_name = args.command[1]
        logs = tester.get_latest_log(dist_name)
        
        if 'error' in logs:
            print(f"Error: {logs['error']}")
        else:
            print(f"=== Logs for {dist_name} ===\n")
            print(logs['full'])
            
    elif args.command[0] == 'dockerfile':
        # Show Dockerfile for specific distribution
        if len(args.command) < 2:
            print("Error: Please specify a distribution")
            sys.exit(1)
            
        dist_name = args.command[1]
        dockerfile = tester.get_dockerfile(dist_name)
        print(f"=== Generated Dockerfile for {dist_name} ===\n")
        print(dockerfile)
        
    else:
        # Test specific distributions
        distributions = args.command
        print(f"Testing distributions via build: {', '.join(distributions)}")
        print("This may take several minutes...\n")
        results = tester.test_specific(distributions)
        
        print("\n" + "="*60)
        print("BUILD TEST RESULTS:")
        print("="*60)
        for dist, result in results.items():
            status = "✓ PASSED" if result['success'] else "✗ FAILED"
            print(f"{dist.ljust(20)} {status}")
            if not result['success'] and result['stderr']:
                # Show first error from build
                error_lines = result['stderr'].split('\n')
                for line in error_lines:
                    if 'error' in line.lower() or 'failed' in line.lower():
                        print(f"  └─ {line.strip()[:80]}")
                        break
        print("="*60)
        
        # Show where to find detailed logs
        print(f"\nDetailed build logs saved to: {tester.log_dir}")
        print(f"Dockerfiles saved to: {tester.build_dir}")
        for dist in distributions:
            if dist in results:
                print(f"  • {dist}: {tester.log_dir}/{dist}_latest.log")


if __name__ == "__main__":
    main()