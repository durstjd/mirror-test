"""
Command Line Interface for Mirror Test.
Handles all CLI commands and interactive interface.
"""

import os
import sys
import subprocess
import webbrowser
import time
import threading
from config import ConfigManager
from core import MirrorTester


class CLIInterface:
    """Command line interface for Mirror Test."""
    
    def __init__(self, config_file=None, cleanup_images=True):
        """Initialize CLI interface."""
        self.config_manager = ConfigManager(config_file)
        self.tester = MirrorTester(self.config_manager, cleanup_images)
    
    def run_command(self, command, args=None):
        """Run a CLI command."""
        if not command or command[0] == 'all':
            return self._test_all()
        elif command[0] == 'gui':
            return self._launch_gui(args)
        elif command[0] == 'cli':
            return self._launch_interactive_cli()
        elif command[0] == 'list':
            return self._list_distributions()
        elif command[0] == 'variables':
            return self._show_variables()
        elif command[0] == 'validate':
            return self._validate_config()
        elif command[0] == 'cleanup':
            return self._cleanup_images()
        elif command[0] == 'logs':
            if len(command) < 2:
                print("Error: Please specify a distribution for logs")
                return False
            return self._show_logs(command[1])
        elif command[0] == 'dockerfile':
            if len(command) < 2:
                print("Error: Please specify a distribution")
                return False
            return self._show_dockerfile(command[1])
        elif command[0] == 'refresh':
            return self._refresh_completion()
        else:
            # Test specific distributions
            return self._test_distributions(command)
    
    def _test_all(self):
        """Test all configured distributions."""
        print("Testing all configured distributions via build process...")
        print("This may take several minutes depending on your mirror speed.\n")
        
        results = self.tester.test_all()
        
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
        return True
    
    def _test_distributions(self, distributions):
        """Test specific distributions."""
        print(f"Testing distributions via build: {', '.join(distributions)}")
        print("This may take several minutes...\n")
        
        results = {}
        for dist in distributions:
            if dist in self.config_manager.config.get('distributions', {}):
                success, stdout, stderr = self.tester.test_distribution(dist)
                results[dist] = {
                    'success': success,
                    'stdout': stdout,
                    'stderr': stderr
                }
            else:
                print(f"Warning: Distribution '{dist}' not found in configuration")
                results[dist] = {
                    'success': False,
                    'stdout': '',
                    'stderr': f"Distribution '{dist}' not found in configuration"
                }
        
        print("\n" + "="*60)
        print("BUILD TEST RESULTS:")
        print("="*60)
        for dist, result in results.items():
            status = "✓ PASSED" if result['success'] else "✗ FAILED"
            print(f"{dist.ljust(20)} {status}")
            if not result['success'] and result['stderr']:
                error_lines = result['stderr'].split('\n')
                for line in error_lines:
                    if 'error' in line.lower() or 'failed' in line.lower():
                        print(f"  └─ {line.strip()[:80]}")
                        break
        print("="*60)
        return True
    
    def _launch_gui(self, args):
        """Launch web interface."""
        try:
            from web import WebInterface
            web_interface = WebInterface(self.config_manager, self.tester)
            return web_interface.start(args)
        except ImportError:
            print("Error: Flask is not available. Web interface cannot be launched.")
            print("Install Flask dependencies: pip install flask flask-limiter flask-wtf flask-cors")
            return False
    
    def _launch_interactive_cli(self):
        """Launch interactive CLI interface."""
        print("Launching simple CLI interface...")
        self._run_interactive_cli()
        return True
    
    def _run_interactive_cli(self):
        """Run the interactive CLI interface."""
        while True:
            try:
                print("\n" + "="*50)
                print("Mirror Test - Interactive CLI")
                print("="*50)
                print("1. Test all distributions")
                print("2. Test specific distribution")
                print("3. List distributions")
                print("4. View logs")
                print("5. View Dockerfile")
                print("6. Exit")
                print("-" * 50)
                
                choice = input("Enter your choice (1-6): ").strip()
                
                if choice == '1':
                    self._test_all()
                    
                elif choice == '2':
                    distributions = self.config_manager.get_distributions()
                    if not distributions:
                        print("No distributions configured")
                        continue
                        
                    print("\nAvailable distributions:")
                    for i, dist in enumerate(sorted(distributions), 1):
                        print(f"{i}. {dist}")
                    
                    try:
                        dist_choice = input("\nEnter distribution number or name: ").strip()
                        if dist_choice.isdigit():
                            dist_index = int(dist_choice) - 1
                            if 0 <= dist_index < len(distributions):
                                dist_name = sorted(distributions)[dist_index]
                            else:
                                print("Invalid choice")
                                continue
                        else:
                            dist_name = dist_choice
                            if dist_name not in distributions:
                                print(f"Distribution '{dist_name}' not found")
                                continue
                        
                        print(f"\nTesting {dist_name}...")
                        success, stdout, stderr = self.tester.test_distribution(dist_name)
                        status = "✓ PASSED" if success else "✗ FAILED"
                        print(f"\n{status}")
                        if not success and stderr:
                            print(f"Error: {stderr[:200]}...")
                            
                    except (ValueError, KeyboardInterrupt):
                        print("Invalid input")
                        continue
                        
                elif choice == '3':
                    self._list_distributions()
                    
                elif choice == '4':
                    distributions = self.config_manager.get_distributions()
                    if not distributions:
                        print("No distributions configured")
                        continue
                        
                    print("\nAvailable distributions:")
                    for i, dist in enumerate(sorted(distributions), 1):
                        print(f"{i}. {dist}")
                    
                    try:
                        dist_choice = input("\nEnter distribution number or name: ").strip()
                        if dist_choice.isdigit():
                            dist_index = int(dist_choice) - 1
                            if 0 <= dist_index < len(distributions):
                                dist_name = sorted(distributions)[dist_index]
                            else:
                                print("Invalid choice")
                                continue
                        else:
                            dist_name = dist_choice
                            if dist_name not in distributions:
                                print(f"Distribution '{dist_name}' not found")
                                continue
                        
                        self._show_logs(dist_name)
                        
                    except (ValueError, KeyboardInterrupt):
                        print("Invalid input")
                        continue
                        
                elif choice == '5':
                    distributions = self.config_manager.get_distributions()
                    if not distributions:
                        print("No distributions configured")
                        continue
                        
                    print("\nAvailable distributions:")
                    for i, dist in enumerate(sorted(distributions), 1):
                        print(f"{i}. {dist}")
                    
                    try:
                        dist_choice = input("\nEnter distribution number or name: ").strip()
                        if dist_choice.isdigit():
                            dist_index = int(dist_choice) - 1
                            if 0 <= dist_index < len(distributions):
                                dist_name = sorted(distributions)[dist_index]
                            else:
                                print("Invalid choice")
                                continue
                        else:
                            dist_name = dist_choice
                            if dist_name not in distributions:
                                print(f"Distribution '{dist_name}' not found")
                                continue
                        
                        self._show_dockerfile(dist_name)
                        
                    except (ValueError, KeyboardInterrupt):
                        print("Invalid input")
                        continue
                        
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
    
    def _list_distributions(self):
        """List all configured distributions."""
        print("Configured distributions:")
        print("-" * 60)
        print(f"{'Distribution':<20} {'Base Image':<20} {'Package Manager':<15}")
        print("-" * 60)
        
        distributions = self.config_manager.get_distributions()
        if not distributions:
            print("No distributions configured")
        else:
            for dist_name in sorted(distributions):
                dist_config = self.config_manager.get_distribution_config(dist_name)
                base_image = dist_config.get('base-image', dist_config.get('pull', 'unknown'))
                package_manager = dist_config.get('package-manager', 'unknown')
                print(f"{dist_name:<20} {base_image:<20} {package_manager:<15}")
        
        print(f"\nTotal: {len(distributions)} distributions")
    
    def _show_variables(self):
        """Show configured variables and their expanded values."""
        print("Configuration variables:")
        print("-" * 40)
        
        variables = self.config_manager.get_variables()
        if not variables:
            print("No variables configured")
        else:
            for var_name, var_value in variables.items():
                expanded_value = self.config_manager.substitute_variables(str(var_value))
                print(f"{var_name:<20} = {expanded_value}")
        
        print(f"\nTotal: {len(variables)} variables")
    
    def _validate_config(self):
        """Validate configuration file syntax."""
        print("Validating configuration...")
        
        errors, warnings = self.config_manager.validate_config()
        
        for warning in warnings:
            if warning.startswith("✓"):
                print(f"✓ {warning[2:]}")
            elif warning.startswith("⚠️"):
                print(f"⚠️  {warning[3:]}")
            else:
                print(f"⚠️  Warning: {warning}")
        
        for error in errors:
            print(f"✗ Error: {error}")
        
        if not errors:
            print("\n✓ Configuration is valid")
            return True
        else:
            print(f"\n✗ Configuration validation failed with {len(errors)} errors")
            return False
    
    def _cleanup_images(self):
        """Clean up all mirror-test images and dangling images."""
        print("Cleaning up all mirror-test images...")
        
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
        
        print("\nPruning build cache...")
        prune_cmd = ["podman", "system", "prune", "-f", "--filter", "until=1h"]
        subprocess.run(prune_cmd, capture_output=True)
        print("Build cache pruned")
        
        print(f"\nCleaned up {tagged_count} tagged images and {dangling_count} dangling images")
        return True
    
    def _show_logs(self, dist_name):
        """Show logs for specific distribution."""
        logs = self.tester.get_latest_log(dist_name)
        
        if 'error' in logs:
            print(f"Error: {logs['error']}")
        else:
            print(f"=== Logs for {dist_name} ===\n")
            print(logs['full'])
    
    def _show_dockerfile(self, dist_name):
        """Show Dockerfile for specific distribution."""
        try:
            dockerfile = self.tester.get_dockerfile(dist_name)
            print(f"=== Generated Dockerfile for {dist_name} ===\n")
            print(dockerfile)
        except Exception as e:
            print(f"Error: {e}")
    
    def _refresh_completion(self):
        """Refresh bash completion."""
        print("Refreshing bash completion...")
        completion_script = os.path.expanduser("~/.bash_completion.d/mirror-test")
        if os.path.exists(completion_script):
            try:
                result = subprocess.run(['bash', '-c', f'source "{completion_script}"'], 
                                      capture_output=True, text=True)
                if result.returncode == 0:
                    print("✓ Bash completion refreshed successfully.")
                else:
                    print(f"⚠ Warning: Completion script had issues: {result.stderr}")
            except Exception as e:
                print(f"⚠ Warning: Could not refresh completion: {e}")
        else:
            print("⚠ Warning: Completion script not found at ~/.bash_completion.d/mirror-test")
            print("  Run the setup script to install completion: ./install.sh")
        return True
