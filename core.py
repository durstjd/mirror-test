"""
Core Mirror Test functionality.
Handles Docker container testing, Dockerfile generation, and build processes.
"""

import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from config import ConfigManager


class MirrorTester:
    """Core mirror testing functionality."""
    
    def __init__(self, config_manager: ConfigManager, cleanup_images: bool = True):
        """Initialize the mirror tester."""
        self.config_manager = config_manager
        self.cleanup_images = cleanup_images
        
        # Set up paths
        self.log_dir = self._get_log_dir()
        self.build_dir = self._get_build_dir()
        
        # Ensure directories exist
        os.makedirs(self.log_dir, exist_ok=True)
        os.makedirs(self.build_dir, exist_ok=True)
    
    def _get_log_dir(self):
        """Get log directory based on config file location."""
        if self.config_manager.config_file.startswith(os.path.expanduser("~")):
            return os.path.expanduser("~/mirror-test/logs")
        else:
            return "/var/log/mirror-test"
    
    def _get_build_dir(self):
        """Get build directory based on config file location."""
        if self.config_manager.config_file.startswith(os.path.expanduser("~")):
            return os.path.expanduser("~/mirror-test/builds")
        else:
            return "/var/lib/mirror-test/builds"
    
    def generate_dockerfile(self, dist_name):
        """Generate a Dockerfile for testing a distribution's repositories."""
        dist_config = self.config_manager.get_distribution_config(dist_name)
        if not dist_config:
            raise ValueError(f"Distribution '{dist_name}' not found in configuration")
        
        base_image = dist_config.get('base-image', dist_config.get('pull', 'debian:12'))
        package_manager = dist_config.get('package-manager', 'apt')
        sources = dist_config.get('sources', [])
        
        # Get package manager configuration
        package_config = self.config_manager.config.get('package-managers', {}).get(package_manager, {})
        update_command = package_config.get('update-command', '')
        default_test_commands = package_config.get('test-commands', [])
        
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
                substituted_source = self.config_manager.substitute_variables(source)
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
                    substituted_cmd = self.config_manager.substitute_variables(cmd)
                    if i > 0:
                        dockerfile += "     "
                    dockerfile += f"{substituted_cmd} && \\\n"
                dockerfile += "     echo 'Repository test successful'\n"
            else:
                dockerfile += "# Basic repository test\n"
                dockerfile += "RUN apt-get install -y --no-install-recommends apt-utils && \\\n"
                dockerfile += "    echo 'Repository test successful'\n"
            
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
                substituted_source = self.config_manager.substitute_variables(source)
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
                    substituted_cmd = self.config_manager.substitute_variables(cmd)
                    if i > 0:
                        dockerfile += "      "
                    dockerfile += f"{substituted_cmd} && \\\n"
                dockerfile += "    echo 'Repository test successful'\n"
            else:
                dockerfile += "# Basic repository test\n"
                if package_manager == 'dnf':
                    dockerfile += "RUN dnf install -y dnf-utils && \\\n"
                else:
                    dockerfile += "RUN yum install -y yum-utils && \\\n"
                dockerfile += "    echo 'Repository test successful'\n"
            
        elif package_manager == 'zypper':
            # openSUSE/SLES
            dockerfile += "# Configure repositories\n"
            dockerfile += "RUN rm -f /etc/zypp/repos.d/* && \\\n"
            
            repo_file = "/etc/zypp/repos.d/mirror-test.repo"
            dockerfile += f"    cat > {repo_file} << 'EOF'\n"
            for source in sources:
                # Substitute variables in source
                substituted_source = self.config_manager.substitute_variables(source)
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
                    substituted_cmd = self.config_manager.substitute_variables(cmd)
                    if i > 0:
                        dockerfile += "    "
                    dockerfile += f"{substituted_cmd} && \\\n"
                dockerfile += "    echo 'Repository test successful'\n"
            else:
                dockerfile += "# Basic repository test\n"
                dockerfile += "RUN zypper --non-interactive install -y zypper && \\\n"
                dockerfile += "    echo 'Repository test successful'\n"
            
        elif package_manager == 'apk':
            # Alpine
            dockerfile += "# Configure repositories\n"
            dockerfile += "RUN > /etc/apk/repositories && \\\n"
            
            for source in sources:
                # Substitute variables in source
                substituted_source = self.config_manager.substitute_variables(source)
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
                    substituted_cmd = self.config_manager.substitute_variables(cmd)
                    if i > 0:
                        dockerfile += "    "
                    dockerfile += f"{substituted_cmd} && \\\n"
                dockerfile += "    echo 'Repository test successful'\n"
            else:
                dockerfile += "# Basic repository test\n"
                dockerfile += "RUN apk add --no-cache curl && \\\n"
                dockerfile += "    echo 'Repository test successful'\n"
        
        else:
            # Generic fallback
            dockerfile += f"# Unknown package manager: {package_manager}\n"
            dockerfile += "RUN echo 'Cannot test - unknown package manager'\n"
        
        # Add final test marker
        dockerfile += "\n# Final validation\n"
        dockerfile += "RUN echo 'All repository tests passed for " + dist_name + "'\n"
        
        return dockerfile
    
    def test_distribution(self, dist_name, timeout=600):
        """Test a specific distribution by building a container."""
        try:
            # Generate Dockerfile
            dockerfile_content = self.generate_dockerfile(dist_name)
            
            # Create temporary directory for build
            with tempfile.TemporaryDirectory() as temp_dir:
                dockerfile_path = os.path.join(temp_dir, "Dockerfile")
                with open(dockerfile_path, 'w') as f:
                    f.write(dockerfile_content)
                
                # Build container
                image_name = f"mirror-test:{dist_name}"
                build_cmd = [
                    "podman", "build", 
                    "-t", image_name,
                    "-f", dockerfile_path,
                    temp_dir
                ]
                
                result = subprocess.run(
                    build_cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout
                )
                
                # Log the build
                self._log_build(dist_name, result.returncode, result.stdout, result.stderr)
                
                # Clean up image if requested
                if self.cleanup_images and result.returncode == 0:
                    subprocess.run(["podman", "rmi", "-f", image_name], 
                                 capture_output=True)
                
                return result.returncode == 0, result.stdout, result.stderr
                
        except subprocess.TimeoutExpired:
            error_msg = f"Build timeout after {timeout} seconds"
            self._log_build(dist_name, 1, "", error_msg)
            return False, "", error_msg
        except Exception as e:
            error_msg = f"Build error: {str(e)}"
            self._log_build(dist_name, 1, "", error_msg)
            return False, "", error_msg
    
    def test_all(self):
        """Test all configured distributions."""
        results = {}
        distributions = self.config_manager.get_distributions()
        
        for dist_name in distributions:
            success, stdout, stderr = self.test_distribution(dist_name)
            results[dist_name] = {
                'success': success,
                'stdout': stdout,
                'stderr': stderr
            }
        
        return results
    
    def _log_build(self, dist_name, return_code, stdout, stderr):
        """Log build results to file."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_file = os.path.join(self.log_dir, f"{dist_name}.log")
        
        with open(log_file, 'a') as f:
            f.write(f"\n=== Build {timestamp} ===\n")
            f.write(f"Return code: {return_code}\n")
            f.write(f"STDOUT:\n{stdout}\n")
            f.write(f"STDERR:\n{stderr}\n")
            f.write("=" * 50 + "\n")
    
    def get_latest_log(self, dist_name):
        """Get the latest build log for a distribution."""
        log_file = os.path.join(self.log_dir, f"{dist_name}.log")
        
        if not os.path.exists(log_file):
            return {'error': 'No logs found for this distribution'}
        
        try:
            with open(log_file, 'r') as f:
                content = f.read()
            
            # Extract the last build
            builds = content.split("=== Build ")[1:]  # Skip the first empty split
            if not builds:
                return {'error': 'No build logs found'}
            
            last_build = builds[-1]
            lines = last_build.split('\n')
            
            # Parse the log
            result = {
                'timestamp': lines[0].split(' ===')[0] if lines else 'Unknown',
                'return_code': None,
                'stdout': '',
                'stderr': '',
                'full': last_build
            }
            
            current_section = None
            for line in lines[1:]:
                if line.startswith("Return code:"):
                    result['return_code'] = int(line.split(": ")[1])
                elif line.startswith("STDOUT:"):
                    current_section = 'stdout'
                elif line.startswith("STDERR:"):
                    current_section = 'stderr'
                elif line.startswith("=" * 50):
                    break
                elif current_section:
                    result[current_section] += line + '\n'
            
            return result
            
        except Exception as e:
            return {'error': f'Error reading log file: {str(e)}'}
    
    def get_dockerfile(self, dist_name):
        """Get the generated Dockerfile for a distribution."""
        return self.generate_dockerfile(dist_name)
