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

# Configuration paths
CONFIG_FILE = "/etc/mirror-test.yaml"
LOG_DIR = "/var/log/mirror-test"
BUILD_DIR = "/var/lib/mirror-test/builds"
WEB_PORT = 8080

# Ensure directories exist
Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
Path(BUILD_DIR).mkdir(parents=True, exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MirrorTester:
    """Main class for testing repository mirrors using Dockerfile builds."""
    
    def __init__(self, config_file: str = CONFIG_FILE):
        self.config_file = config_file
        self.config = self.load_config()
        self.results = {}
        
    def load_config(self) -> Dict:
        """Load configuration from YAML file."""
        if not os.path.exists(self.config_file):
            logger.error(f"Configuration file not found: {self.config_file}")
            self.create_default_config()
            
        with open(self.config_file, 'r') as f:
            return yaml.safe_load(f)
    
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
    
    def generate_dockerfile(self, dist_name: str, dist_config: Dict) -> str:
        """Generate a Dockerfile for testing a distribution's repositories."""
        base_image = dist_config.get('base-image', dist_config.get('pull', 'debian:12'))
        package_manager = dist_config.get('package-manager', 'apt')
        sources = dist_config.get('sources', [])
        
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
                source_escaped = source.replace('"', '\\"')
                dockerfile += f'    echo "{source_escaped}" >> /etc/apt/sources.list && \\\n'
            
            dockerfile += "    cat /etc/apt/sources.list\n\n"
            dockerfile += "# Test repository access\n"
            dockerfile += "RUN apt-get update && \\\n"
            dockerfile += "    apt-get install -y --no-install-recommends apt-utils && \\\n"
            dockerfile += "    echo 'Repository test successful'\n"
            
        elif package_manager in ['yum', 'dnf']:
            # RHEL/CentOS/Rocky/Fedora
            dockerfile += "# Configure repositories\n"
            dockerfile += "RUN rm -f /etc/yum.repos.d/* && \\\n"
            
            # Write repo configuration
            repo_file = "/etc/yum.repos.d/mirror-test.repo"
            dockerfile += f"    cat > {repo_file} << 'EOF'\n"
            for source in sources:
                dockerfile += source + "\n"
            dockerfile += "EOF\n\n"
            
            dockerfile += "# Test repository access\n"
            if package_manager == 'dnf':
                dockerfile += "RUN dnf makecache && \\\n"
                dockerfile += "    dnf install -y dnf-utils && \\\n"
                dockerfile += "    echo 'Repository test successful'\n"
            else:
                dockerfile += "RUN yum makecache && \\\n"
                dockerfile += "    yum install -y yum-utils && \\\n"
                dockerfile += "    echo 'Repository test successful'\n"
            
        elif package_manager == 'zypper':
            # openSUSE/SLES
            dockerfile += "# Configure repositories\n"
            dockerfile += "RUN rm -f /etc/zypp/repos.d/* && \\\n"
            
            repo_file = "/etc/zypp/repos.d/mirror-test.repo"
            dockerfile += f"    cat > {repo_file} << 'EOF'\n"
            for source in sources:
                dockerfile += source + "\n"
            dockerfile += "EOF\n\n"
            
            dockerfile += "# Test repository access\n"
            dockerfile += "RUN zypper --non-interactive refresh && \\\n"
            dockerfile += "    zypper --non-interactive install -y zypper && \\\n"
            dockerfile += "    echo 'Repository test successful'\n"
            
        elif package_manager == 'apk':
            # Alpine
            dockerfile += "# Configure repositories\n"
            dockerfile += "RUN > /etc/apk/repositories && \\\n"
            
            for source in sources:
                source_escaped = source.replace('"', '\\"')
                dockerfile += f'    echo "{source_escaped}" >> /etc/apk/repositories && \\\n'
            
            dockerfile += "    cat /etc/apk/repositories\n\n"
            dockerfile += "# Test repository access\n"
            dockerfile += "RUN apk update && \\\n"
            dockerfile += "    apk add --no-cache curl && \\\n"
            dockerfile += "    echo 'Repository test successful'\n"
        
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
        build_path = os.path.join(BUILD_DIR, dist_name)
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
        build_cmd = [
            "podman", "build",
            "--no-cache",  # Always test fresh
            "-f", dockerfile_path,
            "-t", f"mirror-test:{dist_name}",
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
        log_file = os.path.join(LOG_DIR, f"{dist_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
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
        latest_link = os.path.join(LOG_DIR, f"{dist_name}_latest.log")
        if os.path.exists(latest_link):
            os.remove(latest_link)
        os.symlink(log_file, latest_link)
        
        # Clean up successful build images to save space (optional)
        if success:
            cleanup_cmd = ["podman", "rmi", "-f", f"mirror-test:{dist_name}"]
            subprocess.run(cleanup_cmd, capture_output=True)
        
        return success, result.stdout, result.stderr
    
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
        latest_log = os.path.join(LOG_DIR, f"{dist_name}_latest.log")
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
        distributions = list(self.tester.config.keys())
        
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
                `;
                
                document.getElementById('stats').innerHTML = statsHtml;
            } catch (error) {
                console.error('Error loading stats:', error);
            }
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
                    distributions = list(self.tester.config.keys())
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
                    
                elif self.path == '/api/stats':
                    # Count distributions and recent tests
                    total = len(self.tester.config)
                    tested = 0
                    for dist in self.tester.config.keys():
                        if os.path.exists(os.path.join(LOG_DIR, f"{dist}_latest.log")):
                            tested += 1
                    
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        'total': total,
                        'tested': tested
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
        print(f"📝 Build logs saved to: {LOG_DIR}")
        print(f"🔧 Dockerfiles saved to: {BUILD_DIR}\n")
    
    def stop(self):
        """Stop the web server."""
        if self.server:
            self.server.shutdown()
            self.thread.join()


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
  mirror-test logs debian         # Show latest logs for Debian
  mirror-test dockerfile debian   # Show generated Dockerfile for Debian
  mirror-test --config /path/to/config.yaml  # Use custom config file
        """
    )
    
    parser.add_argument('command', nargs='*', default=['all'],
                       help='Command or distribution(s) to test')
    parser.add_argument('--config', default=CONFIG_FILE,
                       help='Path to configuration file')
    parser.add_argument('--port', type=int, default=WEB_PORT,
                       help='Port for web interface (default: 8080)')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Enable verbose output')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Check if running as root (recommended for podman operations)
    if os.geteuid() != 0:
        logger.warning("Warning: Not running as root. Some operations may fail.")
    
    # Check for podman
    if shutil.which('podman') is None:
        logger.error("Error: podman is not installed or not in PATH")
        sys.exit(1)
    
    # Initialize tester
    tester = MirrorTester(args.config)
    
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
            
    elif args.command[0] == 'cleanup':
        # Clean up all mirror-test images
        print("Cleaning up all mirror-test images...")
        cleanup_cmd = ["podman", "images", "-q", "--filter", "reference=mirror-test:*"]
        result = subprocess.run(cleanup_cmd, capture_output=True, text=True)
        
        if result.stdout:
            images = result.stdout.strip().split('\n')
            for image_id in images:
                if image_id:
                    remove_cmd = ["podman", "rmi", "-f", image_id]
                    rm_result = subprocess.run(remove_cmd, capture_output=True, text=True)
                    if rm_result.returncode == 0:
                        print(f"  ✓ Removed image {image_id[:12]}")
                    else:
                        print(f"  ✗ Failed to remove {image_id[:12]}: {rm_result.stderr}")
            print(f"\nCleaned up {len(images)} mirror-test images")
        else:
            print("No mirror-test images found to clean up")
        
        # Also prune dangling build cache
        print("\nPruning build cache...")
        prune_cmd = ["podman", "system", "prune", "-f", "--filter", "until=1h"]
        subprocess.run(prune_cmd, capture_output=True)
        print("Build cache pruned")
            
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
        print(f"\nDetailed build logs saved to: {LOG_DIR}")
        print(f"Dockerfiles saved to: {BUILD_DIR}")
        for dist in distributions:
            if dist in results:
                print(f"  • {dist}: {LOG_DIR}/{dist}_latest.log")


if __name__ == "__main__":
    main()