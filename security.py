"""
Security module for Mirror Test.
Handles LDAPS authentication, API security, IP whitelisting, audit logging, and CORS.
"""

import os
import sys
import json
import re
import ssl
import hashlib
import hmac
import base64
import uuid
import ipaddress
import logging
import logging.handlers
from datetime import timedelta, datetime
from pathlib import Path

# Optional LDAP imports
try:
    import ldap
    LDAP_AVAILABLE = True
except ImportError:
    LDAP_AVAILABLE = False

# Optional Flask imports
try:
    from flask import request, session, g
    from flask_limiter.util import get_remote_address
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False


class SecurityManager:
    """Manages all security features for Mirror Test."""
    
    def __init__(self):
        """Initialize security manager."""
        self.ldaps_config = None
        self.auth_enabled = False
        self.server_config = None
        self.ip_whitelist_config = None
        self.ip_whitelist_enabled = False
        self.audit_log_config = None
        self.audit_logger = None
        self.api_keys = {}
        self.api_version = "1.0"
        self.api_signature_secret = os.urandom(32)
        
        # API rate limits
        self.api_rate_limits = {
            'api_key': "1000 per hour",
            'api_public': "100 per hour",
            'api_auth': "10 per minute"
        }
        
        # Load configuration
        self._load_server_config()
    
    def _load_server_config(self):
        """Load server configuration from secure config file."""
        # Try new server config first, fall back to old LDAPS config
        server_config_file = os.path.expanduser("~/.config/mirror-test/server-config.yaml")
        ldaps_config_file = os.path.expanduser("~/.config/mirror-test/ldaps-config.yaml")
        
        if os.path.exists(server_config_file):
            try:
                import yaml
                with open(server_config_file, 'r') as f:
                    self.server_config = yaml.safe_load(f)
                print(f"Loaded server configuration from {server_config_file}")
            except Exception as e:
                print(f"Error loading server config: {e}")
                self.server_config = None
        elif os.path.exists(ldaps_config_file):
            try:
                import yaml
                with open(ldaps_config_file, 'r') as f:
                    self.ldaps_config = yaml.safe_load(f)
                print(f"Loading legacy LDAPS configuration from {ldaps_config_file}")
            except Exception as e:
                print(f"Error loading LDAPS config: {e}")
                self.ldaps_config = None
        else:
            print("Warning: Server configuration not found. Authentication disabled.")
            print("Create ~/.config/mirror-test/server-config.yaml or ~/.config/mirror-test/ldaps-config.yaml to enable authentication.")
        
        # Load LDAPS configuration
        if self.server_config and 'ldaps' in self.server_config:
            self.ldaps_config = self.server_config['ldaps']
        elif self.ldaps_config:
            # Migrate old config format
            self.ldaps_config.setdefault('ldap_use_ssl', True)
        
        # Load IP whitelist configuration
        if self.server_config and 'ip_whitelist' in self.server_config:
            self.ip_whitelist_config = self.server_config['ip_whitelist']
            self.ip_whitelist_enabled = self.ip_whitelist_config.get('enabled', False)
        
        # Load audit log configuration
        if self.server_config and 'audit_log' in self.server_config:
            self.audit_log_config = self.server_config['audit_log']
            self._setup_audit_logging()
        
        # Enable authentication if LDAPS is configured
        self.auth_enabled = bool(self.ldaps_config and LDAP_AVAILABLE)
    
    def _setup_audit_logging(self):
        """Setup audit logging configuration."""
        if not self.audit_log_config or not self.audit_log_config.get('enabled', True):
            return
        
        # Create audit logger
        self.audit_logger = logging.getLogger('mirror_test_audit')
        self.audit_logger.setLevel(logging.INFO)
        
        # Remove existing handlers
        for handler in self.audit_logger.handlers[:]:
            self.audit_logger.removeHandler(handler)
        
        # Create log directory
        log_dir = os.path.expanduser(self.audit_log_config.get('log_dir', '~/.local/log/mirror-test'))
        os.makedirs(log_dir, exist_ok=True)
        
        # Create file handler with rotation
        log_file = os.path.join(log_dir, 'audit.log')
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=self.audit_log_config.get('max_size', 10 * 1024 * 1024),  # 10MB
            backupCount=self.audit_log_config.get('backup_count', 5)
        )
        
        # Apply append-only attribute (chattr +a) for security if enabled
        if self.audit_log_config.get('append_only', True):  # Default to True for security
            self._apply_append_only_attribute(log_file)
        
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        
        # Add handler to logger
        self.audit_logger.addHandler(file_handler)
        
        # Log audit system startup
        self.log_audit_event(
            event_type='system',
            user='system',
            action='audit_logging_started',
            success=True
        )
    
    def _apply_append_only_attribute(self, log_file):
        """Apply append-only attribute (chattr +a) to audit log file for security."""
        try:
            import subprocess
            import stat
            
            # Check if the file exists
            if not os.path.exists(log_file):
                # Create an empty file first
                with open(log_file, 'w') as f:
                    f.write('')
            
            # Apply chattr +a (append-only attribute)
            result = subprocess.run(['chattr', '+a', log_file], 
                                  capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                print(f"✓ Applied append-only attribute to audit log: {log_file}")
                print("  Audit log is now protected against tampering (chattr +a)")
            else:
                print(f"⚠ Warning: Could not apply append-only attribute to {log_file}")
                print(f"  Error: {result.stderr}")
                print("  Audit logging will continue without tamper protection")
                print("  To enable protection, run as root or check chattr availability")
                
        except subprocess.TimeoutExpired:
            print(f"⚠ Warning: Timeout applying append-only attribute to {log_file}")
            print("  Audit logging will continue without tamper protection")
        except FileNotFoundError:
            print(f"⚠ Warning: chattr command not found - append-only attribute not applied")
            print("  Audit logging will continue without tamper protection")
            print("  Install util-linux package or run on a system with chattr support")
        except Exception as e:
            print(f"⚠ Warning: Error applying append-only attribute: {e}")
            print("  Audit logging will continue without tamper protection")
    
    def log_audit_event(self, event_type, user, action, details=None, ip_address=None, success=True):
        """Log an audit event."""
        if not self.audit_logger:
            return
        
        # Get IP address if not provided
        if not ip_address and FLASK_AVAILABLE:
            ip_address = self._get_real_ip()
        
        # Create audit entry
        audit_entry = {
            'timestamp': datetime.utcnow().isoformat(),
            'event_type': event_type,
            'user': user,
            'action': action,
            'details': details,
            'ip_address': ip_address,
            'success': success
        }
        
        # Log the event
        self.audit_logger.info(json.dumps(audit_entry))
    
    def _get_real_ip(self):
        """Get the real IP address of the client, considering proxies."""
        if not FLASK_AVAILABLE:
            return 'unknown'
        
        try:
            # Check for forwarded headers (common with reverse proxies)
            forwarded_for = request.headers.get('X-Forwarded-For')
            if forwarded_for:
                return forwarded_for.split(',')[0].strip()
            
            real_ip = request.headers.get('X-Real-IP')
            if real_ip:
                return real_ip
            
            # Fall back to remote address
            return request.remote_addr or 'unknown'
        except RuntimeError:
            # Working outside of request context
            return 'system'
    
    def authenticate_ldaps(self, username, password):
        """Authenticate user against LDAPS server."""
        if not self.ldaps_config or not LDAP_AVAILABLE:
            return False, "LDAPS not configured or unavailable"
        
        try:
            import ssl
            
            # Create LDAP connection
            ldap_server = self.ldaps_config['ldap_server']
            ldap_port = self.ldaps_config.get('ldap_port', 636)
            
            print(f"Connecting to LDAP server: {ldap_server}:{ldap_port}")
            print(f"LDAPS config: {self.ldaps_config}")
            
            # Always enforce SSL certificate verification for security
            verify_cert = self.ldaps_config.get('ldap_verify_cert', True)
            if not verify_cert:
                print("WARNING: ldap_verify_cert is set to false, but SSL verification will be enforced for security")
                print("To use self-signed certificates, configure proper certificate trust instead")
            
            print(f"Certificate verification setting: {verify_cert}")
            
            # Always create secure SSL context with full verification
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False  # Disable hostname verification for IP connections
            ssl_context.verify_mode = ssl.CERT_REQUIRED
            
            # Configure certificate trust if specified
            ca_cert = self.ldaps_config.get('ldap_ca_cert')
            print(f"DEBUG: ca_cert from config: {ca_cert}")
            
            if ca_cert:
                # Expand the path to handle ~ and relative paths
                expanded_ca_cert = os.path.expanduser(ca_cert)
                print(f"DEBUG: expanded_ca_cert: {expanded_ca_cert}")
                
                if os.path.exists(expanded_ca_cert):
                    print(f"Using custom certificate: {expanded_ca_cert}")
                    
                    # Verify the certificate file is readable
                    try:
                        with open(expanded_ca_cert, 'r') as f:
                            cert_content = f.read()
                            print(f"Certificate file is readable ({len(cert_content)} bytes)")
                            
                            # Check if this looks like a server certificate (not CA)
                            if "dc01.SEANCOHMER.COM" in cert_content or "SEANCOHMER" in cert_content:
                                print("Detected server certificate - using for direct verification")
                                # For server certificates, we need to disable hostname verification
                                # since we're verifying against the certificate directly
                                ssl_context.check_hostname = False
                                print("Disabled hostname verification for server certificate")
                                
                                # Load as CA certificate for verification
                                ssl_context.load_verify_locations(expanded_ca_cert)
                                print("Loaded server certificate for verification")
                            else:
                                print("Certificate appears to be a CA certificate")
                                ssl_context.load_verify_locations(expanded_ca_cert)
                                print("Loaded CA certificate for verification")
                    except Exception as e:
                        print(f"Warning: Could not read certificate file: {e}")
                else:
                    print(f"ERROR: Certificate file not found: {expanded_ca_cert}")
                    print("Falling back to system default CA certificates")
            else:
                print("Using system default CA certificates")
            
            print("SSL certificate verification ENABLED - using secure context")
            
            # Debug: Show how to extract the correct certificate
            if ca_cert and os.path.exists(os.path.expanduser(ca_cert)):
                print(f"\nTo verify your LDAP server certificate, run:")
                print(f"openssl s_client -connect {ldap_server}:{ldap_port} -showcerts < /dev/null 2>/dev/null | openssl x509 -outform PEM")
                print(f"Compare the output with your CA certificate file: {os.path.expanduser(ca_cert)}")
                print("The certificates should match for verification to work.\n")
            
            # Connect to LDAP server
            conn = ldap.initialize(f"ldaps://{ldap_server}:{ldap_port}")
            print("LDAP connection initialized")
            
            # Set basic LDAP options
            conn.set_option(ldap.OPT_REFERRALS, 0)
            conn.set_option(ldap.OPT_PROTOCOL_VERSION, 3)
            print("Basic LDAP options set")
            
            # Set the SSL context first (before other SSL options)
            try:
                conn.set_option(ldap.OPT_X_TLS_CTX, ssl_context)
                print("SSL context set successfully")
            except Exception as e:
                print(f"Warning: Could not set SSL context: {e}")
                # Continue without SSL context - some LDAP libraries handle SSL differently
            
            # Always enforce SSL certificate verification
            conn.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_DEMAND)
            print("SSL certificate verification set to DEMAND (secure)")
            
            conn.set_option(ldap.OPT_X_TLS, ldap.OPT_X_TLS_DEMAND)
            conn.set_option(ldap.OPT_DEBUG_LEVEL, 0)
            
            print("SSL/TLS options set")
            
            # Bind with user credentials
            base_dn = self.ldaps_config.get('ldap_base_dn', self.ldaps_config.get('base_dn'))
            user_dn_template = self.ldaps_config.get('user_dn_template', 'uid={username},{base_dn}')
            user_dn = user_dn_template.format(username=username, base_dn=base_dn)
            
            print(f"Attempting LDAP bind with user_dn: {user_dn}")
            conn.simple_bind_s(user_dn, password)
            
            # Get user attributes
            user_attrs = self._get_user_attributes(conn, user_dn)
            user_groups = self._get_user_groups(conn, user_dn)
            
            # Close connection
            conn.unbind_s()
            
            return True, {
                'username': username,
                'display_name': user_attrs.get('displayName', [username])[0],
                'email': user_attrs.get('mail', [''])[0],
                'groups': user_groups
            }
            
        except ldap.INVALID_CREDENTIALS:
            return False, "Invalid username or password"
        except ldap.SERVER_DOWN:
            return False, "LDAP server is not available"
        except ssl.SSLCertVerificationError as e:
            return False, f"SSL certificate verification failed: {str(e)}"
        except ssl.SSLError as e:
            return False, f"SSL error: {str(e)}"
        except Exception as e:
            return False, f"Authentication error: {str(e)}"
    
    def _get_user_attributes(self, conn, user_dn):
        """Get user attributes from LDAP."""
        try:
            result = conn.search_s(user_dn, ldap.SCOPE_BASE, '(objectClass=*)', ['displayName', 'mail'])
            if result:
                return result[0][1]
        except:
            pass
        return {}
    
    def _get_user_groups(self, conn, user_dn):
        """Get user groups from LDAP."""
        try:
            groups = []
            base_dn = self.ldaps_config.get('ldap_base_dn', self.ldaps_config.get('base_dn'))
            group_base = self.ldaps_config.get('ldap_group_base_dn', base_dn)
            filter_str = f"(&(objectClass=groupOfNames)(member={user_dn}))"
            
            result = conn.search_s(group_base, ldap.SCOPE_SUBTREE, filter_str, ['cn'])
            for dn, attrs in result:
                if 'cn' in attrs:
                    groups.append(attrs['cn'][0].decode('utf-8'))
        except:
            pass
        return groups
    
    def is_ip_in_whitelist(self, ip_address, whitelist_config):
        """Check if IP address is in whitelist."""
        if not whitelist_config:
            return True
        
        try:
            ip = ipaddress.ip_address(ip_address)
        except ValueError:
            return False
        
        # Check allow list
        allow_list = whitelist_config.get('allow', [])
        for allowed in allow_list:
            try:
                if '/' in allowed:
                    # CIDR notation
                    network = ipaddress.ip_network(allowed, strict=False)
                    if ip in network:
                        return True
                else:
                    # Single IP
                    if ip == ipaddress.ip_address(allowed):
                        return True
            except ValueError:
                continue
        
        # Check deny list
        deny_list = whitelist_config.get('deny', [])
        for denied in deny_list:
            try:
                if '/' in denied:
                    # CIDR notation
                    network = ipaddress.ip_network(denied, strict=False)
                    if ip in network:
                        return False
                else:
                    # Single IP
                    if ip == ipaddress.ip_address(denied):
                        return False
            except ValueError:
                continue
        
        # Default behavior based on mode
        mode = whitelist_config.get('mode', 'allow')
        return mode == 'allow'
    
    def check_ip_whitelist(self):
        """Check if the current request's IP is allowed."""
        if not self.ip_whitelist_enabled or not self.ip_whitelist_config:
            return True
        
        ip_address = self._get_real_ip()
        return self.is_ip_in_whitelist(ip_address, self.ip_whitelist_config)
    
    def generate_api_key(self, name, permissions=None):
        """Generate a new API key."""
        if permissions is None:
            permissions = ['read']
        
        key_id = str(uuid.uuid4())
        api_key = base64.urlsafe_b64encode(os.urandom(32)).decode('utf-8')
        
        self.api_keys[key_id] = {
            'name': name,
            'key': api_key,
            'permissions': permissions,
            'created': datetime.utcnow().isoformat(),
            'last_used': None,
            'usage_count': 0
        }
        
        return key_id, api_key
    
    def validate_api_key(self, api_key):
        """Validate an API key."""
        for key_id, key_data in self.api_keys.items():
            if key_data['key'] == api_key:
                # Update usage stats
                key_data['last_used'] = datetime.utcnow().isoformat()
                key_data['usage_count'] += 1
                return key_id, key_data
        return None, None
    
    def check_api_permission(self, permissions, required_permission):
        """Check if API key has required permission."""
        return required_permission in permissions
    
    def log_api_access(self, endpoint, method, user, ip, status_code, api_key_id=None):
        """Log API access for monitoring."""
        self.log_audit_event(
            event_type='api_access',
            user=user,
            action=f'{method} {endpoint}',
            details={'status_code': status_code, 'api_key_id': api_key_id},
            ip_address=ip,
            success=200 <= status_code < 400
        )
    
    def get_audit_logs(self, limit=100, offset=0, event_type=None, user=None, start_date=None, end_date=None, status=None):
        """Get audit logs with filtering."""
        if not self.audit_log_config or not self.audit_log_config.get('enabled', True):
            return []
        
        log_file = os.path.join(
            os.path.expanduser(self.audit_log_config.get('log_dir', '~/.local/log/mirror-test')),
            'audit.log'
        )
        
        if not os.path.exists(log_file):
            return []
        
        logs = []
        try:
            with open(log_file, 'r') as f:
                lines = f.readlines()
            
            # Parse ALL logs first, then apply filtering and pagination
            for line in reversed(lines):  # Read all lines, most recent first
                try:
                    # Extract JSON from formatted log line
                    # Format: "2025-09-21 02:38:29 - INFO - {json_data}"
                    line = line.strip()
                    if ' - INFO - ' in line:
                        json_start = line.find(' - INFO - ') + len(' - INFO - ')
                        json_data = line[json_start:]
                        log_entry = json.loads(json_data)
                    else:
                        # Try parsing the whole line as JSON (for backward compatibility)
                        log_entry = json.loads(line)
                    
                    # Apply filters
                    if event_type and log_entry.get('event_type') != event_type:
                        continue
                    if user and log_entry.get('user') != user:
                        continue
                    if start_date and log_entry.get('timestamp') < start_date:
                        continue
                    if end_date and log_entry.get('timestamp') > end_date:
                        continue
                    if status is not None:
                        # Handle status filtering: 'success', 'failure', or boolean
                        if status == 'success' and not log_entry.get('success', False):
                            continue
                        elif status == 'failure' and log_entry.get('success', False):
                            continue
                        elif status in [True, False] and log_entry.get('success') != status:
                            continue
                    
                    logs.append(log_entry)
                        
                except json.JSONDecodeError:
                    continue
            
            # Apply pagination after filtering
            if offset > 0:
                logs = logs[offset:]
            if limit > 0:  # Only apply limit if it's greater than 0
                logs = logs[:limit]
                
        except Exception:
            pass
        
        return logs
    
    def get_audit_stats(self):
        """Get audit log statistics."""
        if not self.audit_log_config or not self.audit_log_config.get('enabled', True):
            return {}
        
        logs = self.get_audit_logs(limit=1000)  # Get more logs for stats
        
        stats = {
            'total_events': len(logs),
            'events_by_type': {},
            'events_by_user': {},
            'success_rate': 0,
            'recent_events': logs[:10]  # Last 10 events
        }
        
        success_count = 0
        for log in logs:
            # Count by type
            event_type = log.get('event_type', 'unknown')
            stats['events_by_type'][event_type] = stats['events_by_type'].get(event_type, 0) + 1
            
            # Count by user
            user = log.get('user', 'unknown')
            stats['events_by_user'][user] = stats['events_by_user'].get(user, 0) + 1
            
            # Count successes
            if log.get('success', False):
                success_count += 1
        
        if logs:
            stats['success_rate'] = (success_count / len(logs)) * 100
        
        return stats
