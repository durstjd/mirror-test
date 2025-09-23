"""
Configuration management for Mirror Test.
Handles loading and validation of configuration files.
"""

import os
import yaml
from pathlib import Path


class ConfigManager:
    """Manages configuration loading and validation."""
    
    def __init__(self, config_file: str = None):
        """Initialize configuration manager."""
        if config_file is None:
            config_file = os.path.expanduser("~/.config/mirror-test/mirror-test.yaml")
        
        self.config_file = config_file
        self.config = self.load_config()
    
    def load_config(self):
        """Load configuration from YAML file."""
        if not os.path.exists(self.config_file):
            self.create_default_config()
            
        with open(self.config_file, 'r') as f:
            config = yaml.safe_load(f)
            
        if not config:
            config = {}
        
        # Update the instance variable so get_distributions() uses the new config
        self.config = config
        return config
    
    def create_default_config(self):
        """Create a default configuration file."""
        default_config = {
            'variables': {
                'MIRROR_HOST': 'mirror.local',
                'MIRROR_PROTO': 'http',
                'MIRROR_BASE': '${MIRROR_PROTO}://${MIRROR_HOST}',
                'GPG_CHECK': '0'
            },
            'package-managers': {
                'apt': {
                    'update-command': 'apt-get update',
                    'test-commands': [
                        'apt-get install -y --no-install-recommends curl wget',
                        'apt-cache stats',
                        'echo "APT repository test successful"'
                    ]
                },
                'dnf': {
                    'update-command': 'dnf update -y',
                    'test-commands': [
                        'dnf install -y curl wget',
                        'dnf repolist',
                        'echo "DNF repository test successful"'
                    ]
                }
            },
            'distributions': {
                'debian-12': {
                    'base-image': 'debian:12',
                    'package-manager': 'apt',
                    'sources': [
                        'deb ${MIRROR_BASE}/debian bookworm main',
                        'deb ${MIRROR_BASE}/debian bookworm-updates main',
                        'deb ${MIRROR_BASE}/debian-security bookworm-security main'
                    ]
                }
            }
        }
        
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        
        with open(self.config_file, 'w') as f:
            yaml.dump(default_config, f, default_flow_style=False)
    
    def get_distributions(self):
        """Get list of configured distributions."""
        if 'distributions' not in self.config:
            return []
        return list(self.config['distributions'].keys())
    
    def get_distribution_config(self, dist_name):
        """Get configuration for a specific distribution."""
        if 'distributions' not in self.config:
            return None
        return self.config['distributions'].get(dist_name)
    
    def get_variables(self):
        """Get configuration variables."""
        return self.config.get('variables', {})
    
    def substitute_variables(self, text):
        """Substitute variables in text using configuration."""
        if not isinstance(text, str):
            return text
            
        variables = self.get_variables()
        
        # Perform multiple passes to handle nested variables
        max_passes = 10  # Prevent infinite loops
        for _ in range(max_passes):
            old_text = text
            for var_name, var_value in variables.items():
                text = text.replace(f'${{{var_name}}}', str(var_value))
            
            # If no changes were made, we're done
            if text == old_text:
                break
        
        return text
    
    def validate_config(self):
        """Validate configuration file syntax and structure."""
        errors = []
        warnings = []
        
        if 'variables' not in self.config:
            warnings.append("No variables section found")
        else:
            warnings.append("Variables section found")
        
        if 'package-managers' not in self.config:
            warnings.append("No package-managers section found")
        else:
            warnings.append("Package-managers section found")
        
        distributions = self.get_distributions()
        if not distributions:
            warnings.append("No distributions configured")
        else:
            warnings.append(f"{len(distributions)} distributions configured")
            
            for dist_name in distributions:
                dist_config = self.get_distribution_config(dist_name)
                required_fields = ['base-image', 'package-manager', 'sources']
                missing_fields = [field for field in required_fields if field not in dist_config]
                
                if missing_fields:
                    errors.append(f"{dist_name} missing fields: {', '.join(missing_fields)}")
                else:
                    warnings.append(f"{dist_name} configuration valid")
        
        return errors, warnings
