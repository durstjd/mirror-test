"""
Web interface for Mirror Test.
Handles Flask web application, API endpoints, and authentication.
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

# Optional Flask imports
try:
    from flask import Flask, render_template_string, request, jsonify, session, redirect, url_for, flash, g
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    from flask_wtf.csrf import CSRFProtect
    from flask_cors import CORS
    from werkzeug.utils import secure_filename
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

# Optional LDAP imports
try:
    import ldap
    LDAP_AVAILABLE = True
except ImportError:
    LDAP_AVAILABLE = False

import threading
from security import SecurityManager


class WebInterface:
    """Web interface for Mirror Test using Flask."""
    
    def __init__(self, config_manager, tester):
        """Initialize web interface."""
        self.config_manager = config_manager
        self.tester = tester
        self.security_manager = SecurityManager()
        
        if not FLASK_AVAILABLE:
            raise ImportError("Flask is not available. Install Flask dependencies.")
        
        # Initialize build history storage
        self.build_history_file = os.path.expanduser("~/.config/mirror-test/build_history.json")
        self._ensure_build_history_file()
        
        # Clean up any orphaned build history entries on startup
        self._cleanup_orphaned_build_history()
        
        self.app = None
        self._setup_flask_app()
        
        # Server configuration will be loaded in start_server() when needed
    
    def _setup_flask_app(self):
        """Setup Flask application with all configurations."""
        self.app = Flask(__name__)
        
        # Basic Flask configuration
        self.app.config.update(
            SECRET_KEY=os.urandom(24),
            SESSION_COOKIE_SECURE=False,  # Will be updated based on SSL
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE='Lax',
            SESSION_PERMANENT=True,
            PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
            WTF_CSRF_TIME_LIMIT=None,  # Disable CSRF token expiration
            WTF_CSRF_SSL_STRICT=False  # Allow CSRF on HTTP for development
        )
        
        # Initialize extensions
        self.csrf = CSRFProtect(self.app)
        self.limiter = Limiter(
            app=self.app,
            key_func=get_remote_address,
            default_limits=["1000 per hour", "100 per minute"]
        )
        
        # Add CSRF token to all templates
        @self.app.context_processor
        def inject_csrf_token():
            from flask_wtf.csrf import generate_csrf
            return dict(csrf_token=generate_csrf)
        
        # CORS configuration
        CORS(self.app, 
             origins=[
                 "https://mirror-test.company.com",
                 "https://admin.company.com",
                 "https://localhost:8443",
                 "http://localhost:8080",
                 "http://localhost:3000",
                 "http://127.0.0.1:8080",
                 "http://127.0.0.1:3000"
             ],
             methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
             allow_headers=[
                 'Content-Type', 
                 'X-API-Key', 
                 'X-API-Version', 
                 'X-API-Signature', 
                 'X-API-Timestamp', 
                 'X-API-Nonce',
                 'Authorization',
                 'X-Requested-With'
             ],
             supports_credentials=True,
             max_age=3600
        )
        
        # Server configuration will be loaded in start_server() when needed
        
        # Setup middleware
        self._setup_middleware()
        
        # Setup routes
        self._setup_routes()
    
    def _get_current_user(self):
        """Get the current authenticated user with fallback."""
        if not FLASK_AVAILABLE:
            return 'system'
        
        # Check if user is authenticated
        if not session.get('authenticated'):
            return 'anonymous'
        
        # Get user from session
        user = session.get('user')
        if user:
            return user
        
        # Fallback to other session keys
        username = session.get('username')
        if username:
            return username
        
        return 'unknown'
    
    def _render_main_page(self):
        """Render the main page with distributions."""
        distributions = self.config_manager.get_distributions()
        auth_enabled = self.security_manager.auth_enabled
        return render_template_string(self._get_html_template(), 
                                   distributions=distributions, 
                                   auth_enabled=auth_enabled)
    
    def _render_audit_logs_page(self):
        """Render the audit logs page."""
        auth_enabled = self.security_manager.auth_enabled
        return render_template_string(self._get_audit_logs_template(), 
                                   auth_enabled=auth_enabled)
    
    def _ensure_build_history_file(self):
        """Ensure build history JSON file exists."""
        os.makedirs(os.path.dirname(self.build_history_file), exist_ok=True)
        if not os.path.exists(self.build_history_file):
            with open(self.build_history_file, 'w') as f:
                json.dump({"builds": []}, f, indent=2)
    
    def _load_build_history(self):
        """Load build history from JSON file."""
        try:
            with open(self.build_history_file, 'r') as f:
                data = json.load(f)
                return data.get('builds', [])
        except (FileNotFoundError, json.JSONDecodeError):
            return []
    
    def _save_build_history(self, builds):
        """Save build history to JSON file."""
        try:
            with open(self.build_history_file, 'w') as f:
                json.dump({"builds": builds}, f, indent=2)
        except Exception as e:
            self.logger.error(f"Error saving build history: {e}")
    
    def _add_build_to_history(self, distribution, success, stderr="", stdout=""):
        """Add a build result to the history, ensuring only one entry per distribution."""
        builds = self._load_build_history()
        
        # Remove any existing entries for this distribution
        builds = [build for build in builds if build.get("distribution") != distribution]
        
        # Add the new build entry
        builds.append({
            "distribution": distribution,
            "timestamp": datetime.now().isoformat(),
            "success": success,
            "stderr": stderr,
            "stdout": stdout
        })
        
        # Clean up history for distributions that are no longer configured
        configured_distributions = self.config_manager.get_distributions()
        builds = [build for build in builds if build.get("distribution") in configured_distributions]
        
        # Keep only last 100 builds to prevent file from growing too large
        builds = builds[-100:]
        self._save_build_history(builds)
    
    def _cleanup_orphaned_build_history(self):
        """Remove build history entries for distributions that are no longer configured."""
        builds = self._load_build_history()
        configured_distributions = self.config_manager.get_distributions()
        
        # Filter out builds for distributions that are no longer configured
        cleaned_builds = [build for build in builds if build.get("distribution") in configured_distributions]
        
        # Only save if there were changes
        if len(cleaned_builds) != len(builds):
            self._save_build_history(cleaned_builds)
            self.logger.info(f"Cleaned up {len(builds) - len(cleaned_builds)} orphaned build history entries")
    
    def _load_server_config(self):
        """Load server configuration for authentication and security."""
        import yaml
        import os
        
        config_file = os.path.expanduser("~/.config/mirror-test/server-config.yaml")
        
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    self.server_config = yaml.safe_load(f)
                print(f"Loaded server configuration from {config_file}")
            except Exception as e:
                print(f"Error loading server configuration: {e}")
                self.server_config = None
        else:
            print(f"Server configuration not found: {config_file}")
            self.server_config = None
        
        # Extract LDAPS configuration
        if self.server_config:
            # Check if LDAPS config is at root level or under 'ldaps' section
            if 'ldap_server' in self.server_config:
                self.ldaps_config = self.server_config
                self.auth_enabled = True
                print(f"LDAPS authentication enabled (root level): {self.server_config.get('ldap_server')}")
            elif 'ldaps' in self.server_config and 'ldap_server' in self.server_config['ldaps']:
                self.ldaps_config = self.server_config['ldaps']
                self.auth_enabled = True
                print(f"LDAPS authentication enabled (ldaps section): {self.server_config['ldaps'].get('ldap_server')}")
            else:
                self.ldaps_config = None
                self.auth_enabled = False
                print("LDAPS authentication disabled: No LDAPS configuration found")
        else:
            self.ldaps_config = None
            self.auth_enabled = False
            print("LDAPS authentication disabled: No server configuration loaded")
    
    def _update_security_manager(self, server_config):
        """Update security manager with server configuration."""
        # Extract LDAPS configuration
        if server_config:
            # Check if LDAPS config is at root level or under 'ldaps' section
            if 'ldap_server' in server_config:
                self.ldaps_config = server_config
                self.auth_enabled = True
                print(f"LDAPS authentication enabled (root level): {server_config.get('ldap_server')}")
            elif 'ldaps' in server_config and 'ldap_server' in server_config['ldaps']:
                self.ldaps_config = server_config['ldaps']
                self.auth_enabled = True
                print(f"LDAPS authentication enabled (ldaps section): {server_config['ldaps'].get('ldap_server')}")
            else:
                self.ldaps_config = None
                self.auth_enabled = False
                print("LDAPS authentication disabled: No LDAPS configuration found")
        else:
            self.ldaps_config = None
            self.auth_enabled = False
            print("LDAPS authentication disabled: No server configuration loaded")
        
        # Update security manager with our configuration
        if hasattr(self, 'ldaps_config') and self.ldaps_config:
            self.security_manager.ldaps_config = self.ldaps_config
            self.security_manager.auth_enabled = self.auth_enabled
            print(f"Updated SecurityManager with LDAPS config: {self.ldaps_config.get('ldap_server')}")
        
        # Update security manager with server configuration for audit logging
        if hasattr(self, 'server_config') and self.server_config:
            self.security_manager.server_config = self.server_config
            print("Audit logging initialized with server configuration")
    
    def _setup_middleware(self):
        """Setup middleware for security."""
        # IP Whitelist middleware
        @self.app.before_request
        def check_ip_whitelist_middleware():
            """Check IP whitelist before processing any request."""
            if not self.security_manager.check_ip_whitelist():
                ip_address = self.security_manager._get_real_ip()
                self.app.logger.warning(f"IP address {ip_address} blocked by whitelist")
                return jsonify({
                    'error': 'Access denied',
                    'message': 'Your IP address is not authorized to access this resource'
                }), 403
    
    def _login_required(self, f):
        """Decorator to require authentication."""
        def decorated_function(*args, **kwargs):
            print(f"Login required check: auth_enabled={self.security_manager.auth_enabled}, session_authenticated={session.get('authenticated')}")
            if not self.security_manager.auth_enabled:
                # If auth is disabled, allow access but show warning
                flash('Authentication is disabled. Running in open mode.', 'warning')
                return f(*args, **kwargs)
            
            if not session.get('authenticated'):
                print("Redirecting to login - not authenticated")
                return redirect(url_for('login'))
            print("Access granted - authenticated")
            return f(*args, **kwargs)
        decorated_function.__name__ = f.__name__
        return decorated_function
    
    def _setup_routes(self):
        """Setup all Flask routes."""
        
        @self.app.route('/')
        def index():
            """Main web interface."""
            # Check authentication if enabled
            if self.security_manager.auth_enabled:
                if not session.get('authenticated'):
                    return redirect(url_for('login'))
            
            # Log page access
            self.security_manager.log_audit_event(
                event_type='web_access',
                user=self._get_current_user(),
                action='main_page_access',
                success=True
            )
            
            return self._render_main_page()
        
        @self.app.route('/audit-logs')
        def audit_logs():
            """Audit logs page."""
            # Check authentication if enabled
            if self.security_manager.auth_enabled:
                if not session.get('authenticated'):
                    return redirect(url_for('login'))
            
            # Log audit log page access
            self.security_manager.log_audit_event(
                event_type='audit_access',
                user=self._get_current_user(),
                action='audit_logs_page_access',
                success=True
            )
            
            return self._render_audit_logs_page()
        
        @self.app.route('/api/distributions', methods=['GET', 'OPTIONS'])
        @self.app.route('/api/v1/distributions', methods=['GET', 'OPTIONS'])
        @self.limiter.limit("60 per minute")
        @self.csrf.exempt
        @self._login_required
        def api_distributions():
            """Get distributions from config file."""
            print(f"api_distributions() called - Method: {request.method}")
            if request.method == 'OPTIONS':
                return self._handle_cors_preflight()
            
            try:
                print("Getting distributions from config manager...")
                # Log API access
                self.security_manager.log_audit_event(
                    event_type='api_access',
                    user=self._get_current_user(),
                    action='distributions_api_access',
                    success=True
                )
                
                # Force reload of config file to get latest changes
                self.config_manager.load_config()
                distributions = self.config_manager.get_distributions()
                print(f"Found {len(distributions)} distributions: {distributions}")
                return jsonify({'distributions': distributions})
            except Exception as e:
                print(f"Error in api_distributions: {e}")
                self.app.logger.error(f"Error getting distributions: {e}")
                return jsonify({'error': 'Failed to get distributions'}), 500
        
        @self.app.route('/api/test', methods=['POST', 'OPTIONS'])
        @self.app.route('/api/v1/test', methods=['POST', 'OPTIONS'])
        @self.limiter.limit("10 per minute")
        @self.csrf.exempt
        @self._login_required
        def api_test():
            """Run build tests."""
            if request.method == 'OPTIONS':
                return self._handle_cors_preflight()
            
            try:
                # Debug: Log the raw request data
                self.app.logger.debug(f"Raw request data: {request.get_data()}")
                self.app.logger.debug(f"Content-Type: {request.content_type}")
                
                data = request.get_json()
                self.app.logger.debug(f"Parsed JSON data: {data}")
                
                if not data:
                    return jsonify({'error': 'No JSON data received'}), 400
                
                distributions = data.get('distributions', [])
                
                if not distributions:
                    return jsonify({'error': 'No distributions specified'}), 400
                
                results = {}
                for dist_name in distributions:
                    # Log test execution start
                    self.security_manager.log_audit_event(
                        event_type='test_execution',
                        user=self._get_current_user(),
                        action='test_started',
                        details={'distribution': dist_name},
                        success=True
                    )
                    
                    success, stdout, stderr = self.tester.test_distribution(dist_name)
                    results[dist_name] = {
                        'success': success,
                        'stdout': stdout,
                        'stderr': stderr
                    }
                    
                    # Log test execution completion
                    self.security_manager.log_audit_event(
                        event_type='test_execution',
                        user=self._get_current_user(),
                        action='test_completed',
                        details={'distribution': dist_name, 'success': success},
                        success=success
                    )
                    
                    # Save build result to history
                    self._add_build_to_history(dist_name, success, stderr, stdout)
                
                return jsonify({'results': results})
            except Exception as e:
                self.app.logger.error(f"Error running tests: {e}")
                return jsonify({'error': 'Internal server error'}), 500
        
        @self.app.route('/api/logs/<dist_name>', methods=['GET', 'OPTIONS'])
        @self.limiter.limit("30 per minute")
        @self.csrf.exempt
        @self._login_required
        def api_logs(dist_name):
            """Get logs for a specific distribution."""
            if request.method == 'OPTIONS':
                return self._handle_cors_preflight()
            
            try:
                # Log API access
                self.security_manager.log_audit_event(
                    event_type='api_access',
                    user=self._get_current_user(),
                    action='logs_api_access',
                    details={'distribution': dist_name},
                    success=True
                )
                
                self.app.logger.debug(f"Getting logs for distribution: {dist_name}")
                logs = self.tester.get_latest_log(dist_name)
                self.app.logger.debug(f"Logs retrieved successfully for {dist_name}")
                return jsonify(logs)
            except Exception as e:
                self.app.logger.error(f"Error getting logs for {dist_name}: {e}")
                return jsonify({'error': f'Logs not found: {str(e)}'}), 404
        
        @self.app.route('/api/dockerfile/<dist_name>', methods=['GET', 'OPTIONS'])
        @self.limiter.limit("30 per minute")
        @self.csrf.exempt
        @self._login_required
        def api_dockerfile(dist_name):
            """Get Dockerfile for a specific distribution."""
            if request.method == 'OPTIONS':
                return self._handle_cors_preflight()
            
            try:
                # Log API access
                self.security_manager.log_audit_event(
                    event_type='api_access',
                    user=self._get_current_user(),
                    action='dockerfile_api_access',
                    details={'distribution': dist_name},
                    success=True
                )
                
                self.app.logger.debug(f"Getting dockerfile for distribution: {dist_name}")
                dockerfile = self.tester.get_dockerfile(dist_name)
                self.app.logger.debug(f"Dockerfile generated successfully for {dist_name}")
                return jsonify({'dockerfile': dockerfile})
            except Exception as e:
                self.app.logger.error(f"Error getting dockerfile for {dist_name}: {e}")
                return jsonify({'error': f'Dockerfile not found: {str(e)}'}), 404
        
        @self.app.route('/api/stats', methods=['GET', 'OPTIONS'])
        @self.limiter.limit("60 per minute")
        @self.csrf.exempt
        @self._login_required
        def api_stats():
            """Get build statistics."""
            if request.method == 'OPTIONS':
                return self._handle_cors_preflight()
            
            try:
                distributions = self.config_manager.get_distributions()
                builds = self._load_build_history()
                
                # Calculate statistics from build history
                now = datetime.now()
                yesterday = now - timedelta(hours=24)
                
                recent_builds = 0
                successful_builds = 0
                failed_builds = 0
                
                for build in builds:
                    build_time = datetime.fromisoformat(build['timestamp'])
                    if build_time > yesterday:
                        recent_builds += 1
                    
                    if build['success']:
                        successful_builds += 1
                    else:
                        failed_builds += 1
                
                return jsonify({
                    'total_distributions': len(distributions),
                    'recent_builds': recent_builds,
                    'successful_builds': successful_builds,
                    'failed_builds': failed_builds,
                    'distributions': distributions
                })
            except Exception as e:
                self.app.logger.error(f"Error getting stats: {e}")
                return jsonify({'error': 'Stats not available'}), 500
        
        @self.app.route('/api/build-history', methods=['GET', 'OPTIONS'])
        @self.limiter.limit("60 per minute")
        @self.csrf.exempt
        @self._login_required
        def api_build_history():
            """Get build history for panels."""
            if request.method == 'OPTIONS':
                return self._handle_cors_preflight()
            
            try:
                # Clean up orphaned entries before returning
                self._cleanup_orphaned_build_history()
                builds = self._load_build_history()
                return jsonify({'builds': builds})
            except Exception as e:
                self.app.logger.error(f"Error getting build history: {e}")
                return jsonify({'error': 'Build history not available'}), 500
        
        # Authentication routes (only if auth is enabled)
        if self.security_manager.auth_enabled:
            @self.app.route('/login', methods=['GET', 'POST'])
            @self.limiter.limit("5 per minute")
            def login():
                """Login page."""
                if request.method == 'POST':
                    username = request.form.get('username', '').strip()
                    password = request.form.get('password', '')
                
                    if not username or not password:
                        flash('Username and password are required', 'error')
                        return render_template_string(self._get_login_template())
                
                    # Validate username format
                    if not re.match(r'^[a-zA-Z0-9._-]+$', username):
                        flash('Invalid username format', 'error')
                        return render_template_string(self._get_login_template())
                
                    # Authenticate against LDAPS
                    success, result = self.security_manager.authenticate_ldaps(username, password)
                    
                    if success:
                        session['user'] = result['username']
                        session['display_name'] = result['display_name']
                        session['email'] = result['email']
                        session['groups'] = result['groups']
                        session['authenticated'] = True
                        session['session_id'] = str(uuid.uuid4())
                        session.permanent = True
                        
                        # Log successful login
                        self.security_manager.log_audit_event(
                            event_type='authentication',
                            user=result['username'],
                            action='login_success',
                            details={'display_name': result['display_name'], 'groups': result['groups']},
                            success=True
                        )
                        
                        flash(f'Welcome, {result["display_name"]}!', 'success')
                        return redirect(url_for('index'))
                    else:
                        # Log failed login attempt
                        self.security_manager.log_audit_event(
                            event_type='authentication',
                            user=username,
                            action='login_failed',
                            details={'reason': result},
                            success=False
                        )
                        
                        flash(result, 'error')
                
                return render_template_string(self._get_login_template())
            
            @self.app.route('/logout')
            def logout():
                """Logout user."""
                # Log logout event
                if session.get('authenticated'):
                    self.security_manager.log_audit_event(
                        event_type='authentication',
                        user=self._get_current_user(),
                        action='logout',
                        success=True
                    )
                
                session.clear()
                flash('You have been logged out', 'info')
                return redirect(url_for('login'))
        
        # API Management Endpoints
        @self.app.route('/api/v1/keys', methods=['GET', 'OPTIONS'])
        @self.limiter.limit("30 per minute")
        def api_list_keys():
            """List all API keys (admin only)."""
            if request.method == 'OPTIONS':
                return self._handle_cors_preflight()
            
            # Check authentication
            if not session.get('authenticated'):
                return jsonify({'error': 'Authentication required'}), 401
            
            # Check admin permissions
            user_groups = session.get('groups', [])
            if 'admin' not in user_groups and 'mirror-test-admin' not in user_groups:
                return jsonify({'error': 'Admin permissions required'}), 403
            
            keys_info = []
            for key_id, key_data in self.security_manager.api_keys.items():
                keys_info.append({
                    'key_id': key_id,
                    'name': key_data['name'],
                    'permissions': key_data['permissions'],
                    'created': key_data['created'],
                    'last_used': key_data['last_used'],
                    'usage_count': key_data['usage_count']
                })
            
            return jsonify({'keys': keys_info})
        
        @self.app.route('/api/v1/keys', methods=['POST', 'OPTIONS'])
        @self.limiter.limit("10 per minute")
        def api_create_key():
            """Create a new API key."""
            if request.method == 'OPTIONS':
                return self._handle_cors_preflight()
            
            # Check authentication
            if not session.get('authenticated'):
                return jsonify({'error': 'Authentication required'}), 401
            
            data = request.get_json()
            name = data.get('name', '').strip()
            permissions = data.get('permissions', ['read'])
            
            if not name:
                return jsonify({'error': 'Name is required'}), 400
            
            key_id, api_key = self.security_manager.generate_api_key(name, permissions)
            
            return jsonify({
                'key_id': key_id,
                'api_key': api_key,
                'name': name,
                'permissions': permissions
            }), 201
        
        @self.app.route('/api/v1/keys/<key_id>', methods=['DELETE', 'OPTIONS'])
        @self.limiter.limit("10 per minute")
        def api_revoke_key(key_id):
            """Revoke an API key."""
            if request.method == 'OPTIONS':
                return self._handle_cors_preflight()
            
            # Check authentication
            if not session.get('authenticated'):
                return jsonify({'error': 'Authentication required'}), 401
            
            if key_id not in self.security_manager.api_keys:
                return jsonify({'error': 'API key not found'}), 404
            
            del self.security_manager.api_keys[key_id]
            return jsonify({'message': 'API key revoked'})
        
        # Audit Log Endpoints
        @self.app.route('/api/v1/audit-logs', methods=['GET', 'OPTIONS'])
        @self.limiter.limit("60 per minute")
        def api_audit_logs():
            """Get audit logs with filtering options."""
            if request.method == 'OPTIONS':
                return self._handle_cors_preflight()
            
            # Check authentication only if enabled
            if self.security_manager.auth_enabled and not session.get('authenticated'):
                return jsonify({'error': 'Authentication required'}), 401
            
            # Get query parameters
            limit = int(request.args.get('limit', 100))
            offset = int(request.args.get('offset', 0))
            event_type = request.args.get('event_type')
            user = request.args.get('user')
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            status = request.args.get('status')
            
            # Get logs with filtering
            logs = self.security_manager.get_audit_logs(
                limit=limit,
                offset=offset,
                event_type=event_type,
                user=user,
                start_date=start_date,
                end_date=end_date,
                status=status
            )
            
            # Get total count of all logs (without pagination) for proper pagination info
            all_logs = self.security_manager.get_audit_logs(
                limit=0,  # 0 means no limit
                offset=0,
                event_type=event_type,
                user=user,
                start_date=start_date,
                end_date=end_date,
                status=status
            )
            
            return jsonify({
                'logs': logs,
                'total': len(all_logs),
                'limit': limit,
                'offset': offset
            })
        
        @self.app.route('/api/v1/audit-stats', methods=['GET', 'OPTIONS'])
        @self.limiter.limit("30 per minute")
        def api_audit_stats():
            """Get audit log statistics."""
            if request.method == 'OPTIONS':
                return self._handle_cors_preflight()
            
            # Check authentication only if enabled
            if self.security_manager.auth_enabled and not session.get('authenticated'):
                return jsonify({'error': 'Authentication required'}), 401
            
            stats = self.security_manager.get_audit_stats()
            return jsonify(stats)
        
        # IP Whitelist Endpoint
        @self.app.route('/api/v1/ip-whitelist', methods=['GET', 'OPTIONS'])
        @self.limiter.limit("30 per minute")
        def api_ip_whitelist_status():
            """Get IP whitelist status and configuration."""
            if request.method == 'OPTIONS':
                return self._handle_cors_preflight()
            
            # Check authentication
            if not session.get('authenticated'):
                return jsonify({'error': 'Authentication required'}), 401
            
            config = {}
            if self.security_manager.ip_whitelist_config:
                config = {
                    'mode': self.security_manager.ip_whitelist_config.get('mode', 'allow'),
                    'allow': self.security_manager.ip_whitelist_config.get('allow', []),
                    'deny': self.security_manager.ip_whitelist_config.get('deny', []),
                    'bypass_ips': self.security_manager.ip_whitelist_config.get('bypass_ips', [])
                }
            
            return jsonify({
                'enabled': self.security_manager.ip_whitelist_enabled,
                'config': config
            })
    
    def _handle_cors_preflight(self):
        """Handle CORS preflight OPTIONS requests."""
        return jsonify({}), 200
    
    def _get_login_template(self):
        """Get the login template."""
        return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mirror Test - Login</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .login-container {
            background: white;
            padding: 2rem;
            border-radius: 8px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
            width: 100%;
            max-width: 400px;
        }
        .login-header {
            text-align: center;
            margin-bottom: 2rem;
        }
        .login-header h1 {
            color: #2c3e50;
            margin: 0;
        }
        .form-group {
            margin-bottom: 1rem;
        }
        .form-group label {
            display: block;
            margin-bottom: 0.5rem;
            color: #555;
            font-weight: 500;
        }
        .form-group input {
            width: 100%;
            padding: 0.75rem;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 1rem;
            box-sizing: border-box;
        }
        .form-group input:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 2px rgba(102, 126, 234, 0.2);
        }
        .btn {
            width: 100%;
            padding: 0.75rem;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 4px;
            font-size: 1rem;
            cursor: pointer;
            transition: background 0.3s;
        }
        .btn:hover {
            background: #5a6fd8;
        }
        .alert {
            padding: 0.75rem;
            margin-bottom: 1rem;
            border-radius: 4px;
            border: 1px solid transparent;
        }
        .alert-error {
            background: #f8d7da;
            border-color: #f5c6cb;
            color: #721c24;
        }
        .alert-success {
            background: #d4edda;
            border-color: #c3e6cb;
            color: #155724;
        }
        .alert-info {
            background: #d1ecf1;
            border-color: #bee5eb;
            color: #0c5460;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="login-header">
            <h1>Mirror Test</h1>
            <p>Please log in to continue</p>
        </div>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <form method="POST">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
            <div class="form-group">
                <label for="username">Username</label>
                <input type="text" id="username" name="username" required>
            </div>
            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" required>
            </div>
            <button type="submit" class="btn">Login</button>
        </form>
    </div>
</body>
</html>
        """
    
    def _get_html_template(self):
        """Get the HTML template for the web interface."""
        return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mirror Test - Repository Testing Interface</title>
    <style>
        :root {
            --primary-gradient: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            --secondary-gradient: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            --success-gradient: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            --warning-gradient: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%);
            --error-gradient: linear-gradient(135deg, #fa709a 0%, #fee140 100%);
            
            --bg-primary: #0f0f23;
            --bg-secondary: #1a1a2e;
            --bg-tertiary: #16213e;
            --bg-card: rgba(255, 255, 255, 0.05);
            
            /* Button gradients - Dark mode (default) */
            --btn-1-gradient: linear-gradient(135deg, #0f172a 0%, #1e2a5e 33%, #1e3a8a 66%, #1e40af 100%);
            --btn-1-hover-gradient: linear-gradient(135deg, #1e2a5e 0%, #1e3a8a 33%, #1e40af 66%, #2563eb 100%);
            --btn-1-color: rgba(255, 255, 255, 0.8);
            --btn-1-hover-color: #ffffff;
            --btn-1-border: rgba(255, 255, 255, 0.2);
            --btn-1-hover-border: rgba(255, 255, 255, 0.4);
            
            --btn-2-gradient: linear-gradient(135deg, #1e2a5e 0%, #1e3a8a 33%, #1e40af 66%, #2563eb 100%);
            --btn-2-hover-gradient: linear-gradient(135deg, #1e3a8a 0%, #1e40af 33%, #2563eb 66%, #3b82f6 100%);
            --btn-2-color: rgba(255, 255, 255, 0.8);
            --btn-2-hover-color: #ffffff;
            --btn-2-border: rgba(255, 255, 255, 0.2);
            --btn-2-hover-border: rgba(255, 255, 255, 0.4);
            
            --btn-3-gradient: linear-gradient(135deg, #1e3a8a 0%, #1e40af 33%, #2563eb 66%, #1d4ed8 100%);
            --btn-3-hover-gradient: linear-gradient(135deg, #1e40af 0%, #2563eb 33%, #1d4ed8 66%, #3730a3 100%);
            --btn-3-color: rgba(255, 255, 255, 0.8);
            --btn-3-hover-color: #ffffff;
            --btn-3-border: rgba(255, 255, 255, 0.2);
            --btn-3-hover-border: rgba(255, 255, 255, 0.4);
            
            --btn-4-gradient: linear-gradient(135deg, #2563eb 0%, #1d4ed8 33%, #3730a3 66%, #553c9a 100%);
            --btn-4-hover-gradient: linear-gradient(135deg, #1d4ed8 0%, #3730a3 33%, #553c9a 66%, #6b46c1 100%);
            --btn-4-color: rgba(255, 255, 255, 0.8);
            --btn-4-hover-color: #ffffff;
            --btn-4-border: rgba(255, 255, 255, 0.2);
            --btn-4-hover-border: rgba(255, 255, 255, 0.4);
            
            --btn-5-gradient: linear-gradient(135deg, #1d4ed8 0%, #3730a3 33%, #553c9a 66%, #6b46c1 100%);
            --btn-5-hover-gradient: linear-gradient(135deg, #3730a3 0%, #553c9a 33%, #6b46c1 66%, #7c3aed 100%);
            --btn-5-color: rgba(255, 255, 255, 0.8);
            --btn-5-hover-color: #ffffff;
            --btn-5-border: rgba(255, 255, 255, 0.2);
            --btn-5-hover-border: rgba(255, 255, 255, 0.4);
            
            --btn-6-gradient: linear-gradient(135deg, #3730a3 0%, #553c9a 33%, #6b46c1 66%, #7c3aed 100%);
            --btn-6-hover-gradient: linear-gradient(135deg, #553c9a 0%, #6b46c1 33%, #7c3aed 66%, #8b5cf6 100%);
            --btn-6-color: rgba(255, 255, 255, 0.8);
            --btn-6-hover-color: #ffffff;
            --btn-6-border: rgba(255, 255, 255, 0.2);
            --btn-6-hover-border: rgba(255, 255, 255, 0.4);
            
            --bg-card-hover: rgba(255, 255, 255, 0.08);
            
            --text-primary: #ffffff;
            --text-secondary: #b8b8d1;
            --text-muted: #8b8ba7;
            
            --border-color: rgba(255, 255, 255, 0.1);
            --border-hover: rgba(255, 255, 255, 0.2);
            
            --shadow-sm: 0 2px 8px rgba(0, 0, 0, 0.1);
            --shadow-md: 0 4px 16px rgba(0, 0, 0, 0.2);
            --shadow-lg: 0 8px 32px rgba(0, 0, 0, 0.3);
            --shadow-xl: 0 16px 64px rgba(0, 0, 0, 0.4);
        }
        
        [data-theme="light"] {
            --bg-primary: #e2e8f0;
            --bg-secondary: #f1f5f9;
            --bg-tertiary: #cbd5e1;
            --bg-card: rgba(255, 255, 255, 0.8);
            --bg-card-hover: rgba(255, 255, 255, 0.9);
            
            /* Button gradients - Light mode */
            --btn-1-gradient: linear-gradient(135deg, #1e3a8a 0%, #1e40af 33%, #2563eb 66%, #3b82f6 100%);
            --btn-1-hover-gradient: linear-gradient(135deg, #1e40af 0%, #2563eb 33%, #3b82f6 66%, #60a5fa 100%);
            --btn-1-color: rgba(255, 255, 255, 0.9);
            --btn-1-hover-color: #ffffff;
            --btn-1-border: rgba(255, 255, 255, 0.3);
            --btn-1-hover-border: rgba(255, 255, 255, 0.5);
            
            --btn-2-gradient: linear-gradient(135deg, #1e40af 0%, #2563eb 33%, #3b82f6 66%, #60a5fa 100%);
            --btn-2-hover-gradient: linear-gradient(135deg, #2563eb 0%, #3b82f6 33%, #60a5fa 66%, #93c5fd 100%);
            --btn-2-color: rgba(255, 255, 255, 0.9);
            --btn-2-hover-color: #ffffff;
            --btn-2-border: rgba(255, 255, 255, 0.3);
            --btn-2-hover-border: rgba(255, 255, 255, 0.5);
            
            --btn-3-gradient: linear-gradient(135deg, #2563eb 0%, #3b82f6 33%, #60a5fa 66%, #93c5fd 100%);
            --btn-3-hover-gradient: linear-gradient(135deg, #3b82f6 0%, #60a5fa 33%, #93c5fd 66%, #bfdbfe 100%);
            --btn-3-color: rgba(255, 255, 255, 0.9);
            --btn-3-hover-color: #ffffff;
            --btn-3-border: rgba(255, 255, 255, 0.3);
            --btn-3-hover-border: rgba(255, 255, 255, 0.5);
            
            --btn-4-gradient: linear-gradient(135deg, #3b82f6 0%, #60a5fa 33%, #93c5fd 66%, #bfdbfe 100%);
            --btn-4-hover-gradient: linear-gradient(135deg, #60a5fa 0%, #93c5fd 33%, #bfdbfe 66%, #dbeafe 100%);
            --btn-4-color: rgba(255, 255, 255, 0.9);
            --btn-4-hover-color: #ffffff;
            --btn-4-border: rgba(255, 255, 255, 0.3);
            --btn-4-hover-border: rgba(255, 255, 255, 0.5);
            
            --btn-5-gradient: linear-gradient(135deg, #60a5fa 0%, #93c5fd 33%, #bfdbfe 66%, #dbeafe 100%);
            --btn-5-hover-gradient: linear-gradient(135deg, #93c5fd 0%, #bfdbfe 33%, #dbeafe 66%, #eff6ff 100%);
            --btn-5-color: rgba(255, 255, 255, 0.9);
            --btn-5-hover-color: #ffffff;
            --btn-5-border: rgba(255, 255, 255, 0.3);
            --btn-5-hover-border: rgba(255, 255, 255, 0.5);
            
            --btn-6-gradient: linear-gradient(135deg, #93c5fd 0%, #bfdbfe 33%, #dbeafe 66%, #eff6ff 100%);
            --btn-6-hover-gradient: linear-gradient(135deg, #bfdbfe 0%, #dbeafe 33%, #eff6ff 66%, #f8fafc 100%);
            --btn-6-color: rgba(255, 255, 255, 0.9);
            --btn-6-hover-color: #ffffff;
            --btn-6-border: rgba(255, 255, 255, 0.3);
            --btn-6-hover-border: rgba(255, 255, 255, 0.5);
            
            --text-primary: #1e293b;
            --text-secondary: #475569;
            --text-muted: #64748b;
            
            --border-color: rgba(0, 0, 0, 0.1);
            --border-hover: rgba(0, 0, 0, 0.2);
        }
        
        * { 
            margin: 0; 
            padding: 0; 
            box-sizing: border-box; 
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Inter', Oxygen, Ubuntu, sans-serif;
            background: var(--bg-primary);
            min-height: 100vh;
            color: var(--text-primary);
            transition: all 0.3s ease;
            overflow-x: hidden;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }
        
        .header {
            background: var(--bg-card);
            backdrop-filter: blur(20px);
            border-radius: 20px;
            padding: 20px 40px;
            margin-bottom: 30px;
            box-shadow: var(--shadow-lg);
            border: 1px solid var(--border-color);
            position: relative;
            overflow: hidden;
        }
        
        .header-stats-inline {
            flex: 1;
            display: flex;
            justify-content: center;
            align-items: center;
            margin: 0px 0px;
        }
        
        .header-stats-inline .stats-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
            max-width: 600px;
            align-items: center;
            align-self: center;
        }
        
        .header-stats-inline .stat-card {
            padding: 12px 16px;
            min-width: 120px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
        }
        
        .header-stats-inline .stat-value {
            font-size: 1.4em;
            font-weight: 700;
        }
        
        .header-stats-inline .stat-label {
            font-size: 0.8em;
            opacity: 0.8;
        }
        
        .header::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 4px;
            background: var(--primary-gradient);
        }
        
        .header-content {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 20px;
            height: 100%;
        }
        
        .header-left {
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: flex-start;
        }
        
        .header-left h1 {
            font-size: 3em;
            margin-bottom: 10px;
            font-weight: 800;
            letter-spacing: -0.02em;
            display: flex;
            justify-content: space-between;
            align-items: center;
            width: 100%;
        }
        
        .header-left h1 .penguin {
            color: var(--text-primary);
        }
        
        .header-left h1 .title-text {
            background: var(--primary-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        
        .subtitle {
            color: var(--text-secondary);
            font-size: 1.2em;
            font-weight: 500;
            text-align: right;
            align-self: flex-end;
        }
        
        .header-right {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .theme-toggle {
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-radius: 50px;
            padding: 8px;
            cursor: pointer;
            transition: all 0.3s ease;
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 14px;
            font-weight: 600;
            color: var(--text-secondary);
            align-self: center;
            height: fit-content;
        }
        
        .theme-toggle:hover {
            background: var(--bg-card-hover);
            border-color: var(--border-hover);
            transform: translateY(-2px);
        }
        
        .logout-button {
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-radius: 50px;
            padding: 8px 16px;
            cursor: pointer;
            transition: all 0.3s ease;
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 14px;
            font-weight: 600;
            color: var(--text-secondary);
            align-self: center;
            height: fit-content;
            box-shadow: var(--shadow-sm);
        }
        
        .logout-button:hover {
            background: var(--bg-card-hover);
            border-color: var(--border-hover);
            transform: translateY(-2px);
            box-shadow: var(--shadow-md);
        }
        
        .theme-icon {
            font-size: 18px;
            transition: transform 0.3s ease;
        }
        
        .main-content {
            display: grid;
            grid-template-columns: 350px 1fr;
            gap: 30px;
            margin-bottom: 30px;
        }
        
        .sidebar {
            background: var(--bg-card);
            backdrop-filter: blur(20px);
            border-radius: 20px;
            padding: 30px;
            box-shadow: var(--shadow-lg);
            border: 1px solid var(--border-color);
            height: fit-content;
            position: sticky;
            top: 20px;
        }
        
        .sidebar h3 {
            color: var(--text-primary);
            font-size: 1.2em;
            font-weight: 700;
            margin-bottom: 3px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .sidebar h3::before {
            content: '';
            width: 4px;
            height: 3px;
            background: var(--primary-gradient);
            border-radius: 2px;
        }
        
        .control-group {
            margin-bottom: 8px;
            width: 100%;
        }
        
        .control-group label {
            display: block;
            margin-bottom: 10px;
            font-weight: 600;
            color: var(--text-secondary);
            font-size: 0.9em;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .distribution-list {
            background: var(--bg-tertiary);
            border-radius: 12px;
            border: 1px solid var(--border-color);
            max-height: 300px;
            overflow-y: auto;
            margin-bottom: 20px;
            overflow-x: hidden;
        }
        
        .distribution-item {
            padding: 12px 16px;
            border-bottom: 1px solid var(--border-color);
            cursor: pointer;
            transition: all 0.3s ease;
            display: flex;
            align-items: center;
            gap: 10px;
            font-weight: 500;
            color: var(--text-secondary);
            position: relative;
        }
        
        .distribution-item:last-child {
            border-bottom: none;
        }
        
        .distribution-item:hover {
            background: var(--bg-card-hover);
            color: var(--text-primary);
            transform: translateX(4px);
        }
        
        .distribution-item.selected {
            background: var(--primary-gradient);
            color: white;
            transform: translateX(4px);
        }
        
        .distribution-item .dist-icon {
            width: 20px;
            height: 20px;
            background: var(--primary-gradient);
            border-radius: 4px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 10px;
            color: white;
            font-weight: bold;
        }
        
        .distribution-item.selected .dist-icon {
            background: rgba(255, 255, 255, 0.2);
        }
        
        .distribution-item.multi-selected {
            border-left: 3px solid var(--primary-gradient);
            background: var(--bg-card-hover);
        }
        
        .distribution-item.multi-selected .dist-icon {
            background: var(--primary-gradient);
            color: white;
        }
        
        
        .stats-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
            margin-bottom: 0px;
        }
        
        .stat-card {
            background: var(--bg-tertiary);
            border-radius: 12px;
            padding: 16px;
            text-align: center;
            border: 1px solid var(--border-color);
            transition: all 0.3s ease;
        }
        
        .stat-card:hover {
            transform: translateY(-2px);
            box-shadow: var(--shadow-md);
        }
        
        .stat-value {
            font-size: 1.8em;
            font-weight: 800;
            margin-bottom: 4px;
            background: var(--primary-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        
        .stat-label {
            font-size: 0.8em;
            color: var(--text-muted);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .stat-card.success .stat-value {
            background: var(--success-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        
        .stat-card.error .stat-value {
            background: var(--error-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        
        .build-panels {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin-top: 30px;
        }
        
        .build-panel {
            background: var(--bg-card);
            backdrop-filter: blur(20px);
            border-radius: 16px;
            padding: 20px;
            box-shadow: var(--shadow-lg);
            border: 1px solid var(--border-color);
        }
        
        .build-panel h3 {
            margin: 0 0 3px 0;
            font-size: 1.1em;
            color: var(--text-primary);
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .build-list {
            max-height: 250px;
            overflow-y: auto;
            padding: 0 5px;
        }
        
        .build-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 12px;
            margin: 6px 0;
            border-radius: 8px;
            font-size: 0.85em;
            transition: all 0.3s ease;
            cursor: pointer;
            user-select: none;
            border: 1px solid var(--border-color);
        }
        
        .success-item {
            background: linear-gradient(135deg, rgba(16, 185, 129, 0.1) 0%, rgba(16, 185, 129, 0.05) 100%);
            border-color: rgba(16, 185, 129, 0.3);
            color: #10b981;
        }
        
        .failed-item {
            background: linear-gradient(135deg, rgba(239, 68, 68, 0.1) 0%, rgba(239, 68, 68, 0.05) 100%);
            border-color: rgba(239, 68, 68, 0.3);
            color: #ef4444;
        }
        
        .build-item:hover {
            transform: translateX(4px);
            box-shadow: var(--shadow-sm);
        }
        
        .build-dist {
            font-weight: 600;
            flex: 1;
            min-width: 0;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        
        .build-date {
            font-size: 0.75em;
            opacity: 0.8;
            flex-shrink: 0;
            margin-left: 8px;
        }
        
        .no-builds {
            text-align: center;
            color: var(--text-muted);
            font-style: italic;
            padding: 20px;
        }
        
        .content-area {
            background: var(--bg-card);
            backdrop-filter: blur(20px);
            border-radius: 20px;
            padding: 30px;
            box-shadow: var(--shadow-lg);
            border: 1px solid var(--border-color);
        }
        
        .tabs {
            display: flex;
            gap: 8px;
            margin-bottom: 25px;
            border-bottom: 2px solid var(--border-color);
            padding-bottom: 0;
        }
        
        .tab {
            padding: 12px 20px;
            background: none;
            border: none;
            color: var(--text-muted);
            cursor: pointer;
            font-weight: 600;
            font-size: 0.9em;
            transition: all 0.3s ease;
            position: relative;
            border-radius: 8px 8px 0 0;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .tab:hover {
            color: var(--text-primary);
            background: var(--bg-tertiary);
        }
        
        .tab.active {
            color: var(--text-primary);
            background: var(--bg-tertiary);
        }
        
        .tab.active::after {
            content: '';
            position: absolute;
            bottom: -2px;
            left: 0;
            right: 0;
            height: 3px;
            background: var(--primary-gradient);
            border-radius: 2px 2px 0 0;
        }
        
        .tab-content {
            display: none;
            animation: fadeIn 0.3s ease;
        }
        
        .tab-content.active {
            display: block;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .log-content {
            background: var(--bg-tertiary);
            color: var(--text-primary);
            padding: 20px;
            border-radius: 12px;
            overflow-x: auto;
            max-height: 500px;
            overflow-y: auto;
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            font-size: 13px;
            line-height: 1.6;
            white-space: pre-wrap;
            word-wrap: break-word;
            border: 1px solid var(--border-color);
        }
        
        .log-content::-webkit-scrollbar {
            width: 8px;
        }
        
        .log-content::-webkit-scrollbar-track {
            background: var(--bg-secondary);
        }
        
        .log-content::-webkit-scrollbar-thumb {
            background: var(--border-color);
            border-radius: 4px;
        }
        
        .log-content::-webkit-scrollbar-thumb:hover {
            background: var(--border-hover);
        }
        
        .status {
            padding: 16px 20px;
            border-radius: 12px;
            margin-bottom: 20px;
            display: none;
            animation: slideIn 0.3s ease;
            font-weight: 600;
            border: 1px solid;
        }
        
        @keyframes slideIn {
            from { opacity: 0; transform: translateY(-10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .status.success {
            background: linear-gradient(135deg, rgba(16, 185, 129, 0.1) 0%, rgba(16, 185, 129, 0.05) 100%);
            color: #10b981;
            border-color: rgba(16, 185, 129, 0.3);
        }
        
        .status.error {
            background: linear-gradient(135deg, rgba(239, 68, 68, 0.1) 0%, rgba(239, 68, 68, 0.05) 100%);
            color: #ef4444;
            border-color: rgba(239, 68, 68, 0.3);
        }
        
        .status.info {
            background: linear-gradient(135deg, rgba(59, 130, 246, 0.1) 0%, rgba(59, 130, 246, 0.05) 100%);
            color: #3b82f6;
            border-color: rgba(59, 130, 246, 0.3);
        }
        
        .spinner {
            display: none;
            width: 16px;
            height: 16px;
            border: 2px solid var(--border-color);
            border-top: 2px solid var(--text-primary);
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin-left: 8px;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        .controls {
            display: flex;
            gap: 15px;
            margin-bottom: 30px;
            flex-wrap: wrap;
        }
        
        .btn {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 25%, #9f7aea 50%, #805ad5 75%, #6b46c1 100%);
            color: var(--text-primary);
            border: 1px solid rgba(255, 255, 255, 0.2);
            padding: 12px 24px;
            border-radius: 8px;
            cursor: pointer;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Inter', Oxygen, Ubuntu, sans-serif;
            font-weight: 600;
            font-size: 0.9em;
            transition: all 0.2s ease;
            position: relative;
            overflow: hidden;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            width: 100%;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }
        
        .btn::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent);
            transition: left 0.5s;
        }
        
        .btn:hover::before {
            left: 100%;
        }
        
        .btn:hover {
            background: linear-gradient(135deg, #764ba2 0%, #9f7aea 25%, #805ad5 50%, #6b46c1 75%, #553c9a 100%);
            border-color: rgba(255, 255, 255, 0.4);
            transform: translateY(-1px);
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15);
        }
        
        .btn:active {
            transform: translateY(-1px);
        }
        
        /* Single gradient flowing across all buttons - Overlapping colors for smooth transition */
        .btn-1 {
            background: var(--btn-1-gradient);
            color: var(--btn-1-color);
            border: 1px solid var(--btn-1-border);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Inter', Oxygen, Ubuntu, sans-serif;
            font-weight: 600;
            font-size: 0.9em;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .btn-1:hover {
            background: var(--btn-1-hover-gradient);
            color: var(--btn-1-hover-color);
            border-color: var(--btn-1-hover-border);
        }
        
        .btn-2 {
            background: var(--btn-2-gradient);
            color: var(--btn-2-color);
            border: 1px solid var(--btn-2-border);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Inter', Oxygen, Ubuntu, sans-serif;
            font-weight: 600;
            font-size: 0.9em;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .btn-2:hover {
            background: var(--btn-2-hover-gradient);
            color: var(--btn-2-hover-color);
            border-color: var(--btn-2-hover-border);
        }
        
        .btn-3 {
            background: var(--btn-3-gradient);
            color: var(--btn-3-color);
            border: 1px solid var(--btn-3-border);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Inter', Oxygen, Ubuntu, sans-serif;
            font-weight: 600;
            font-size: 0.9em;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .btn-3:hover {
            background: var(--btn-3-hover-gradient);
            color: var(--btn-3-hover-color);
            border-color: var(--btn-3-hover-border);
        }
        
        .btn-4 {
            background: var(--btn-4-gradient);
            color: var(--btn-4-color);
            border: 1px solid var(--btn-4-border);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Inter', Oxygen, Ubuntu, sans-serif;
            font-weight: 600;
            font-size: 0.9em;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .btn-4:hover {
            background: var(--btn-4-hover-gradient);
            color: var(--btn-4-hover-color);
            border-color: var(--btn-4-hover-border);
        }
        
        .btn-5 {
            background: var(--btn-5-gradient);
            color: var(--btn-5-color);
            border: 1px solid var(--btn-5-border);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Inter', Oxygen, Ubuntu, sans-serif;
            font-weight: 600;
            font-size: 0.9em;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .btn-5:hover {
            background: var(--btn-5-hover-gradient);
            color: var(--btn-5-hover-color);
            border-color: var(--btn-5-hover-border);
        }
        
        .btn-6 {
            background: var(--btn-6-gradient);
            color: var(--btn-6-color);
            border: 1px solid var(--btn-6-border);
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Inter', Oxygen, Ubuntu, sans-serif;
            font-weight: 600;
            font-size: 0.9em;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .btn-6:hover {
            background: var(--btn-6-hover-gradient);
            color: var(--btn-6-hover-color);
            border-color: var(--btn-6-hover-border);
        }
        
        /* Legacy button classes for compatibility */
        .btn-secondary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-color: rgba(255, 255, 255, 0.3);
        }
        
        .btn-secondary:hover {
            background: linear-gradient(135deg, #764ba2 0%, #9f7aea 100%);
            border-color: rgba(255, 255, 255, 0.4);
        }
        
        .btn-success {
            background: linear-gradient(135deg, #9f7aea 0%, #805ad5 100%);
            border-color: rgba(255, 255, 255, 0.3);
        }
        
        .btn-success:hover {
            background: linear-gradient(135deg, #805ad5 0%, #6b46c1 100%);
            border-color: rgba(255, 255, 255, 0.4);
        }
        
        .btn-warning {
            background: linear-gradient(135deg, #805ad5 0%, #6b46c1 100%);
            border-color: rgba(255, 255, 255, 0.3);
        }
        
        .btn-warning:hover {
            background: linear-gradient(135deg, #6b46c1 0%, #553c9a 100%);
            border-color: rgba(255, 255, 255, 0.4);
        }
        
        .btn-error {
            background: var(--error-gradient);
        }
        
        .distributions {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .distribution-card {
            background: var(--bg-card);
            border-radius: 16px;
            padding: 24px;
            box-shadow: var(--shadow-sm);
            border: 1px solid var(--border-color);
            transition: all 0.3s ease;
            position: relative;
            overflow: hidden;
        }
        
        .distribution-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 3px;
            background: var(--primary-gradient);
            transform: scaleX(0);
            transition: transform 0.3s ease;
        }
        
        .distribution-card:hover {
            transform: translateY(-8px);
            box-shadow: var(--shadow-lg);
            border-color: var(--border-hover);
        }
        
        .distribution-card:hover::before {
            transform: scaleX(1);
        }
        
        .distribution-card h3 {
            margin-bottom: 3px;
            color: var(--text-primary);
            font-size: 1.4em;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .dist-icon {
            width: 24px;
            height: 24px;
            background: var(--primary-gradient);
            border-radius: 6px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
            color: white;
            font-weight: bold;
        }
        
        .card-actions {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        
        .btn-small {
            padding: 8px 16px;
            font-size: 12px;
            border-radius: 8px;
            flex: 1;
            min-width: 80px;
        }
        
        .results {
            margin-top: 30px;
            padding: 24px;
            background: var(--bg-tertiary);
            border-radius: 16px;
            border: 1px solid var(--border-color);
            display: none;
            animation: slideUp 0.3s ease;
        }
        
        @keyframes slideUp {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .results h3 {
            margin-bottom: 20px;
            color: var(--text-primary);
            font-size: 1.3em;
            font-weight: 700;
        }
        
        .result-item {
            display: flex;
            align-items: center;
            padding: 12px 16px;
            margin-bottom: 8px;
            background: var(--bg-card);
            border-radius: 12px;
            border: 1px solid var(--border-color);
            transition: all 0.3s ease;
        }
        
        .result-item:hover {
            background: var(--bg-card-hover);
            transform: translateX(4px);
        }
        
        .status-indicator {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            margin-right: 12px;
            flex-shrink: 0;
        }
        
        .status-indicator.success {
            background: #10b981;
            box-shadow: 0 0 10px rgba(16, 185, 129, 0.3);
        }
        
        .status-indicator.error {
            background: #ef4444;
            box-shadow: 0 0 10px rgba(239, 68, 68, 0.3);
        }
        
        .status-indicator.loading {
            background: #3b82f6;
            animation: pulse 1.5s infinite;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.7; transform: scale(1.1); }
        }
        
        .result-text {
            flex: 1;
            font-weight: 600;
        }
        
        .success { color: #10b981; }
        .error { color: #ef4444; }
        .loading { color: #3b82f6; }
        
        .footer {
            text-align: center;
            margin-top: 50px;
            padding: 30px;
            color: var(--text-muted);
            font-size: 14px;
        }
        
        .footer a {
            color: var(--text-secondary);
            text-decoration: none;
            font-weight: 600;
            transition: color 0.3s ease;
        }
        
        .footer a:hover {
            color: var(--text-primary);
        }
        
        .loading-spinner {
            display: inline-block;
            width: 20px;
            height: 20px;
            border: 2px solid var(--border-color);
            border-radius: 50%;
            border-top-color: var(--text-primary);
            animation: spin 1s linear infinite;
            margin-right: 8px;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: var(--text-muted);
        }
        
        .empty-state h3 {
            font-size: 1.5em;
            margin-bottom: 3px;
            color: var(--text-secondary);
        }
        
        .empty-state p {
            font-size: 1.1em;
        }
        
        /* Responsive Design */
        @media (max-width: 1024px) {
            .main-content {
                grid-template-columns: 1fr;
                gap: 20px;
            }
            
            .sidebar {
                position: static;
                order: 2;
            }
            
            .content-area {
                order: 1;
            }
        }
        
        @media (max-width: 768px) {
            .container { padding: 15px; }
            .header { padding: 25px; }
            .header-content { flex-direction: column; text-align: center; }
            .header-left h1 { font-size: 2.2em; }
            .header-stats-inline { margin: 20px 0; }
            .header-stats-inline .stats-grid { grid-template-columns: 1fr 1fr; gap: 10px; }
            .main-content { grid-template-columns: 1fr; }
            .sidebar { order: 2; }
            .content-area { order: 1; }
            .build-panels { grid-template-columns: 1fr; }
            .stats-grid { grid-template-columns: 1fr 1fr; }
            .tabs { flex-wrap: wrap; }
            .tab { flex: 1; min-width: 120px; }
        }
        
        @media (max-width: 480px) {
            .stats-grid { grid-template-columns: 1fr; }
            .header-stats-inline .stats-grid { grid-template-columns: 1fr; }
            .header-stats-inline .stat-card { padding: 8px 12px; min-width: auto; }
            .tab { font-size: 0.8em; padding: 10px 12px; }
            .distribution-item { padding: 10px 12px; }
            .build-item { padding: 8px 10px; font-size: 0.8em; }
        }
        
        /* Scrollbar Styling */
        ::-webkit-scrollbar {
            width: 8px;
        }
        
        ::-webkit-scrollbar-track {
            background: var(--bg-secondary);
        }
        
        ::-webkit-scrollbar-thumb {
            background: var(--border-color);
            border-radius: 4px;
        }
        
        ::-webkit-scrollbar-thumb:hover {
            background: var(--border-hover);
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="header-content">
                <div class="header-left">
                    <h1><span class="penguin">🐧</span><span class="title-text">Mirror Test</span></h1>
                    <p class="subtitle">Repository Testing Interface</p>
                </div>
                
                <!-- Inline Stats -->
                <div class="header-stats-inline">
                    <div class="stats-grid" id="stats">
                        <div class="stat-card">
                            <div class="stat-value" id="total-distributions">0</div>
                            <div class="stat-label">Configured</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-value" id="recent-tests">0</div>
                            <div class="stat-label">Recent (24h)</div>
                        </div>
                        <div class="stat-card success">
                            <div class="stat-value" id="successful-builds">0</div>
                            <div class="stat-label">Successful</div>
                        </div>
                        <div class="stat-card error">
                            <div class="stat-value" id="failed-builds">0</div>
                            <div class="stat-label">Failed</div>
                        </div>
                    </div>
                </div>
                
                <div class="header-right">
                    <div class="theme-toggle" onclick="toggleTheme()">
                        <span class="theme-icon">🌙</span>
                        <span id="theme-text">Dark Mode</span>
                    </div>
                    {% if auth_enabled and session.authenticated %}
                    <div class="logout-button" onclick="logout()">
                        <span class="logout-icon">🚪</span>
                        <span>Logout</span>
                    </div>
                    {% endif %}
                </div>
            </div>
        </div>
        
        <div id="status" class="status"></div>
        
        <div class="main-content">
            <div class="sidebar">
                <h3>Distributions</h3>
                <p style="font-size: 0.8em; color: var(--text-secondary); margin-bottom: 10px; font-style: italic;">
                    Ctrl+Click for multiple selections
                </p>
                <div class="distribution-list" id="distribution-list">
                    {% for dist in distributions %}
                    <div class="distribution-item" data-dist="{{ dist }}" onclick="selectDistribution(event, '{{ dist }}')">
                        <span class="dist-icon">{{ dist[0].upper() }}</span>
                        {{ dist }}
                    </div>
                    {% endfor %}
                </div>
                
                <div class="control-group">
                    <button class="btn btn-1" onclick="runTest()" id="testBtn">
                        Run Build Test
                        <span class="spinner" id="testSpinner"></span>
                    </button>
                </div>
                
                <div class="control-group">
                    <button class="btn btn-2" onclick="runSelectedTests()" id="testSelectedBtn" style="display: none;">
                        Run Selected Tests
                        <span class="spinner" id="testSelectedSpinner"></span>
                    </button>
                </div>
                
                <div class="control-group">
                    <button class="btn btn-2" onclick="runTestAll()" id="testAllBtn">
                        Test All Distributions
                        <span class="spinner" id="testAllSpinner"></span>
                    </button>
                </div>
                
                <div class="control-group">
                    <button class="btn btn-3" onclick="loadLogs()" id="logBtn">
                        Load Build Logs
                        <span class="spinner" id="logSpinner"></span>
                    </button>
                </div>
                
                <div class="control-group">
                    <button class="btn btn-4" onclick="viewDockerfile()">
                        View Dockerfile
                    </button>
                </div>
                
                
                <div class="control-group">
                    <button class="btn btn-5" onclick="refreshDistributions()">
                        Refresh List
                    </button>
                </div>
                
                <div class="control-group">
                    <a href="/audit-logs" class="btn btn-6" style="text-decoration: none; display: block; text-align: center;">
                        📊 Audit Logs
                    </a>
                </div>
            </div>
            
            <div class="content-area">
                <div class="tabs">
                    <button class="tab active" onclick="switchTab('output', event)">Build Output</button>
                    <button class="tab" onclick="switchTab('errors', event)">Errors</button>
                    <button class="tab" onclick="switchTab('dockerfile', event)">Dockerfile</button>
                    <button class="tab" onclick="switchTab('full', event)">Full Log</button>
                </div>
                
                <div id="output" class="tab-content active">
                    <pre class="log-content" id="stdout">Select a distribution and click "Run Build Test" to see the build process...</pre>
                </div>
                
                <div id="errors" class="tab-content">
                    <pre class="log-content" id="stderr">No errors to display...</pre>
                </div>
                
                <div id="dockerfile" class="tab-content">
                    <pre class="log-content" id="dockerfileContent">Dockerfile will appear here...</pre>
                </div>
                
                <div id="full" class="tab-content">
                    <pre class="log-content" id="fullLog">Complete log will appear here...</pre>
                </div>
                
                <!-- Build Status Panels -->
                <div class="build-panels">
                    <div class="build-panel">
                        <h3>✅ Successful Builds</h3>
                        <div class="build-list" id="successful-builds-list">
                            <div class="no-builds">No successful builds yet</div>
                        </div>
                    </div>
                    
                    <div class="build-panel">
                        <h3>❌ Failed Builds</h3>
                        <div class="build-list" id="failed-builds-list">
                            <div class="no-builds">No failed builds yet</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="footer">
            <p>Mirror Test v2.2.0 | <a href="https://github.com/durstjd/mirror-test" target="_blank">💻 github.com/durstjd/mirror-test</a></p>
        </div>
    </div>

    <script>
        async function testAll() {
            const resultsDiv = document.getElementById('results');
            const contentDiv = document.getElementById('results-content');
            
            resultsDiv.style.display = 'block';
            contentDiv.innerHTML = '<p class="loading">Testing all distributions...</p>';
            
            try {
                // First get the current list of distributions
                const distResponse = await fetch('/api/distributions');
                const distData = await distResponse.json();
                
                if (!distData.distributions || distData.distributions.length === 0) {
                    contentDiv.innerHTML = '<p class="error">No distributions found</p>';
                    return;
                }
                
                const response = await fetch('/api/test', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        distributions: distData.distributions
                    })
                });
                
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                
                const data = await response.json();
                
                if (data.error) {
                    contentDiv.innerHTML = `<p class="error">Error: ${data.error}</p>`;
                    return;
                }
                
                let html = '<h4>Test Results:</h4>';
                for (const [dist, result] of Object.entries(data.results)) {
                    const status = result.success ? '✓ PASSED' : '✗ FAILED';
                    const statusClass = result.success ? 'success' : 'error';
                    html += `<p class="${statusClass}"><strong>${dist}:</strong> ${status}</p>`;
                    if (!result.success && result.stderr) {
                        html += `<p style="margin-left: 20px; color: #666;">${result.stderr.substring(0, 200)}...</p>`;
                    }
                }
                
                contentDiv.innerHTML = html;
            } catch (error) {
                console.error('Test error:', error);
                contentDiv.innerHTML = `<p class="error">Error: ${error.message}</p>`;
            }
        }
        
        async function testDistribution(distName) {
            const resultsDiv = document.getElementById('results');
            const contentDiv = document.getElementById('results-content');
            
            resultsDiv.style.display = 'block';
            contentDiv.innerHTML = `<p class="loading">Testing ${distName}...</p>`;
            
            try {
                const response = await fetch('/api/test', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        distributions: [distName]
                    })
                });
                
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                
                const data = await response.json();
                
                if (data.error) {
                    contentDiv.innerHTML = `<p class="error">Error: ${data.error}</p>`;
                    return;
                }
                
                const result = data.results[distName];
                
                const status = result.success ? '✓ PASSED' : '✗ FAILED';
                const statusClass = result.success ? 'success' : 'error';
                
                let html = `<h4>Test Result for ${distName}:</h4>`;
                html += `<p class="${statusClass}"><strong>${distName}:</strong> ${status}</p>`;
                
                if (!result.success && result.stderr) {
                    html += `<p><strong>Error:</strong></p>`;
                    html += `<pre style="background: #f0f0f0; padding: 10px; border-radius: 4px;">${result.stderr}</pre>`;
                }
                
                contentDiv.innerHTML = html;
            } catch (error) {
                console.error('Test error:', error);
                contentDiv.innerHTML = `<p class="error">Error: ${error.message}</p>`;
            }
        }
        
        async function viewLogs(distName) {
            try {
                const response = await fetch(`/api/logs/${distName}`);
                const data = await response.json();
                
                if (data.error) {
                    alert(`Error: ${data.error}`);
                    return;
                }
                
                const logWindow = window.open('', '_blank', 'width=800,height=600');
                logWindow.document.write(`
                    <html>
                        <head><title>Logs for ${distName}</title></head>
                        <body>
                            <h2>Logs for ${distName}</h2>
                            <pre style="white-space: pre-wrap; font-family: monospace;">${data.full}</pre>
                        </body>
                    </html>
                `);
            } catch (error) {
                alert(`Error: ${error.message}`);
            }
        }
        
        async function viewDockerfile(distName = null) {
            const targetDist = distName || selectedDistribution;
            
            if (!targetDist) {
                showStatus('Please select a distribution first', 'error');
                return;
            }
            
            try {
                const response = await fetch(`/api/dockerfile/${targetDist}`);
                const data = await response.json();
                
                if (data.error) {
                    showStatus(`Error: ${data.error}`, 'error');
                    return;
                }
                
                document.getElementById('dockerfileContent').textContent = data.dockerfile || 'No Dockerfile available';
                highlightDockerfile();
                switchTab('dockerfile');
                
            } catch (error) {
                console.error('Dockerfile error:', error);
                showStatus(`Error: ${error.message}`, 'error');
            }
        }
        
        async function runTestAll() {
            document.getElementById('testAllBtn').disabled = true;
            showSpinner('testAllSpinner', true);
            showStatus('Testing all distributions... This may take several minutes.', 'info');
            
            try {
                // First get the current list of distributions
                const distResponse = await fetch('/api/distributions');
                const distData = await distResponse.json();
                
                if (!distData.distributions || distData.distributions.length === 0) {
                    showStatus('No distributions found', 'error');
                    return;
                }
                
                const response = await fetch('/api/test', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({distributions: distData.distributions})
                });
                
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                
                const data = await response.json();
                
                if (data.error) {
                    showStatus(`Error: ${data.error}`, 'error');
                    return;
                }
                
                let successCount = 0;
                let failCount = 0;
                
                for (const [dist, result] of Object.entries(data.results)) {
                    if (result.success) successCount++;
                    else failCount++;
                    
                    // Add to build history
                    addToBuildHistory(dist, result.success, result.stderr);
                }
                
                if (failCount === 0) {
                    showStatus(`All ${successCount} build tests passed successfully!`, 'success');
                } else {
                    showStatus(`${successCount} passed, ${failCount} failed. Check logs for details.`, 'error');
                }
                
                // Update stats
                updateStats();
                
            } catch (error) {
                console.error('Test all error:', error);
                showStatus(`Error: ${error.message}`, 'error');
            } finally {
                document.getElementById('testAllBtn').disabled = false;
                showSpinner('testAllSpinner', false);
            }
        }
        
        // Theme toggle functionality
        function toggleTheme() {
            const body = document.body;
            const themeIcon = document.querySelector('.theme-icon');
            const themeText = document.getElementById('theme-text');
            
            if (body.getAttribute('data-theme') === 'light') {
                body.removeAttribute('data-theme');
                themeIcon.textContent = '🌙';
                themeText.textContent = 'Dark Mode';
                localStorage.setItem('theme', 'dark');
            } else {
                body.setAttribute('data-theme', 'light');
                themeIcon.textContent = '☀️';
                themeText.textContent = 'Light Mode';
                localStorage.setItem('theme', 'light');
            }
        }
        
        function logout() {
            if (confirm('Are you sure you want to logout?')) {
                window.location.href = '/logout';
            }
        }
        
        // Load saved theme on page load
        document.addEventListener('DOMContentLoaded', function() {
            const savedTheme = localStorage.getItem('theme');
            if (savedTheme === 'light') {
                document.body.setAttribute('data-theme', 'light');
                document.querySelector('.theme-icon').textContent = '☀️';
                document.getElementById('theme-text').textContent = 'Light Mode';
            }
        });
        
        // Enhanced loading states
        function showLoading(buttonId) {
            const spinner = document.getElementById(buttonId);
            if (spinner) {
                spinner.style.display = 'inline-block';
            }
        }
        
        function hideLoading(buttonId) {
            const spinner = document.getElementById(buttonId);
            if (spinner) {
                spinner.style.display = 'none';
            }
        }
        
        async function refreshDistributions() {
            console.log('refreshDistributions() called');
            try {
                console.log('Fetching /api/distributions...');
                const response = await fetch('/api/distributions');
                console.log('Response status:', response.status);
                
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                
                const data = await response.json();
                console.log('Received data:', data);
                
                const distributionList = document.getElementById('distribution-list');
                let html = '';
                
                for (const dist of data.distributions) {
                    html += `
                        <div class="distribution-item" data-dist="${dist}" onclick="selectDistribution(event, '${dist}')">
                            <span class="dist-icon">${dist[0].toUpperCase()}</span>
                            ${dist}
                        </div>
                    `;
                }
                
                distributionList.innerHTML = html;
                updateStats();
                showStatus('Distribution list refreshed successfully', 'success');
                
            } catch (error) {
                console.error('Refresh error:', error);
                showStatus(`Error refreshing distributions: ${error.message}`, 'error');
            }
        }
        
        function showStats() {
            alert('Statistics feature coming soon!');
        }
        
        function showHelp() {
            alert('Help documentation coming soon!');
        }
        
        // New sidebar functionality
        let currentTab = 'output';
        let selectedDistribution = null;
        let selectedDistributions = new Set();
        let buildHistory = [];
        
        function switchTab(tab, event) {
            // Update tab buttons
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            if (event && event.target) {
                event.target.classList.add('active');
            } else {
                // Fallback: find the tab button by tab name
                document.querySelectorAll('.tab').forEach(t => {
                    if (t.textContent.toLowerCase().includes(tab.toLowerCase())) {
                        t.classList.add('active');
                    }
                });
            }
            
            // Update content
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            document.getElementById(tab).classList.add('active');
            
            currentTab = tab;
        }
        
        function selectDistribution(event, distName) {
            const isCtrlClick = event.ctrlKey || event.metaKey; // Support both Ctrl and Cmd (Mac)
            const distItem = document.querySelector(`[data-dist="${distName}"]`);
            
            if (isCtrlClick) {
                // Ctrl+click: toggle selection
                if (selectedDistributions.has(distName)) {
                    // Deselect
                    selectedDistributions.delete(distName);
                    distItem.classList.remove('selected', 'multi-selected');
                } else {
                    // Select
                    selectedDistributions.add(distName);
                    distItem.classList.add('selected', 'multi-selected');
                }
                // Update selectedDistribution to the first selected item for single-item operations
                selectedDistribution = selectedDistributions.size > 0 ? Array.from(selectedDistributions)[0] : null;
                updateSelectedCount();
            } else {
                // Regular click: single selection
                document.querySelectorAll('.distribution-item').forEach(item => {
                    item.classList.remove('selected', 'multi-selected');
                });
                
                if (distItem) {
                    distItem.classList.add('selected');
                }
                
                selectedDistribution = distName;
                selectedDistributions.clear();
                selectedDistributions.add(distName);
                updateSelectedCount();
            }
            
            // Clear previous content
            document.getElementById('stdout').textContent = 'Select a distribution and click "Run Build Test" to see the build process...';
            document.getElementById('stderr').textContent = 'No errors to display...';
            document.getElementById('dockerfileContent').textContent = 'Dockerfile will appear here...';
            document.getElementById('fullLog').textContent = 'Complete log will appear here...';
        }
        
        function updateSelectedCount() {
            const testBtn = document.getElementById('testBtn');
            const testSelectedBtn = document.getElementById('testSelectedBtn');
            const count = selectedDistributions.size;
            
            if (count > 1) {
                // Multiple selections: show "Run Selected Tests" button
                testBtn.style.display = 'none';
                testSelectedBtn.style.display = 'block';
                testSelectedBtn.textContent = `Run Selected Tests (${count})`;
                testSelectedBtn.disabled = false;
            } else if (count === 1) {
                // Single selection: show "Run Build Test" button
                testBtn.style.display = 'block';
                testSelectedBtn.style.display = 'none';
                testBtn.disabled = false;
            } else {
                // No selections: show "Run Build Test" button but disabled
                testBtn.style.display = 'block';
                testSelectedBtn.style.display = 'none';
                testBtn.disabled = true;
            }
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
            const spinner = document.getElementById(spinnerId);
            if (spinner) {
                spinner.style.display = show ? 'inline-block' : 'none';
            }
        }
        
        function highlightDockerfile() {
            const content = document.getElementById('dockerfileContent');
            if (!content) return;
            
            let text = content.textContent;
            
            // Simple syntax highlighting for Dockerfiles
            text = text.replace(/(FROM|RUN|COPY|ADD|ENV|WORKDIR|EXPOSE|CMD|ENTRYPOINT|ARG|LABEL|USER|VOLUME|STOPSIGNAL|HEALTHCHECK|SHELL)(\s)/g, 
                '<span class="keyword">$1</span>$2');
            
            content.innerHTML = text;
        }
        
        async function runTest() {
            if (!selectedDistribution) {
                showStatus('Please select a distribution first', 'error');
                return;
            }
            
            document.getElementById('testBtn').disabled = true;
            showSpinner('testSpinner', true);
            showStatus('Running build test... This may take a few minutes.', 'info');
            
            try {
                const response = await fetch('/api/test', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({distributions: [selectedDistribution]})
                });
                
                const data = await response.json();
                
                if (data.error) {
                    showStatus(`Error: ${data.error}`, 'error');
                    return;
                }
                
                const result = data.results[selectedDistribution];
                
                if (result.success) {
                    showStatus(`Build test for ${selectedDistribution} passed successfully!`, 'success');
                } else {
                    showStatus(`Build test for ${selectedDistribution} failed. Check logs for details.`, 'error');
                }
                
                // Update build history
                addToBuildHistory(selectedDistribution, result.success, result.stderr);
                
                // Auto-load logs
                await loadLogs();
                
                // Update stats
                updateStats();
                
            } catch (error) {
                console.error('Test error:', error);
                showStatus(`Error: ${error.message}`, 'error');
            } finally {
                document.getElementById('testBtn').disabled = false;
                showSpinner('testSpinner', false);
            }
        }
        
        async function runSelectedTests() {
            if (selectedDistributions.size === 0) {
                showStatus('Please select at least one distribution first', 'error');
                return;
            }
            
            document.getElementById('testSelectedBtn').disabled = true;
            showSpinner('testSelectedSpinner', true);
            showStatus(`Running build tests for ${selectedDistributions.size} distributions... This may take several minutes.`, 'info');
            
            try {
                const distributions = Array.from(selectedDistributions);
                const response = await fetch('/api/test', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({distributions: distributions})
                });
                
                const data = await response.json();
                
                if (data.error) {
                    showStatus(`Error: ${data.error}`, 'error');
                    return;
                }
                
                // Process results
                let successCount = 0;
                let failCount = 0;
                let allOutput = '';
                let allErrors = '';
                
                for (const dist of distributions) {
                    const result = data.results[dist];
                    if (result) {
                        // Update build history
                        addToBuildHistory(dist, result.success, result.stderr);
                        
                        if (result.success) {
                            successCount++;
                        } else {
                            failCount++;
                        }
                        
                        // Accumulate output
                        allOutput += `=== ${dist} ===\n${result.stdout || 'No output available'}\n\n`;
                        allErrors += `=== ${dist} ===\n${result.stderr || 'No errors'}\n\n`;
                    }
                }
                
                // Display combined results
                document.getElementById('stdout').textContent = allOutput || 'No output available';
                document.getElementById('stderr').textContent = allErrors || 'No errors';
                
                // Clear logs and dockerfile for multi-test
                document.getElementById('dockerfileContent').textContent = 'Dockerfile view not available for multiple distributions';
                document.getElementById('fullLog').textContent = 'Full log view not available for multiple distributions';
                
                if (failCount === 0) {
                    showStatus(`All ${successCount} build tests completed successfully!`, 'success');
                } else if (successCount === 0) {
                    showStatus(`All ${failCount} build tests failed. Check the errors tab for details.`, 'error');
                } else {
                    showStatus(`${successCount} tests succeeded, ${failCount} tests failed. Check the output for details.`, 'warning');
                }
                
                // Update stats
                updateStats();
                
            } catch (error) {
                console.error('Error running selected tests:', error);
                showStatus('Error running selected tests: ' + error.message, 'error');
            } finally {
                document.getElementById('testSelectedBtn').disabled = false;
                showSpinner('testSelectedSpinner', false);
            }
        }
        
        async function loadLogs() {
            if (!selectedDistribution) {
                showStatus('Please select a distribution first', 'error');
                return;
            }
            
            document.getElementById('logBtn').disabled = true;
            showSpinner('logSpinner', true);
            
            try {
                // Fetch logs and Dockerfile in parallel
                const [logsResponse, dockerfileResponse] = await Promise.all([
                    fetch(`/api/logs/${selectedDistribution}`),
                    fetch(`/api/dockerfile/${selectedDistribution}`)
                ]);
                
                const logsData = await logsResponse.json();
                const dockerfileData = await dockerfileResponse.json();
                
                if (logsData.error) {
                    showStatus(`Error: ${logsData.error}`, 'error');
                    return;
                }
                
                // Update all log displays
                document.getElementById('stdout').textContent = logsData.stdout || 'No output available';
                document.getElementById('stderr').textContent = logsData.stderr || 'No errors';
                document.getElementById('fullLog').textContent = logsData.full || 'No complete log available';
                
                // Update Dockerfile content
                if (dockerfileData.error) {
                    document.getElementById('dockerfileContent').textContent = 'No Dockerfile available';
                } else {
                    document.getElementById('dockerfileContent').textContent = dockerfileData.dockerfile || 'No Dockerfile available';
                }
                
                // Highlight Dockerfile syntax
                highlightDockerfile();
                
                // Don't switch tabs - stay on current tab
                
            } catch (error) {
                console.error('Log error:', error);
                showStatus(`Error: ${error.message}`, 'error');
            } finally {
                document.getElementById('logBtn').disabled = false;
                showSpinner('logSpinner', false);
            }
        }
        
        function addToBuildHistory(distName, success, stderr) {
            const build = {
                dist: distName,
                success: success,
                timestamp: new Date(),
                stderr: stderr
            };
            
            // Remove any existing entries for this distribution
            buildHistory = buildHistory.filter(b => b.dist !== distName);
            
            // Add the new build entry
            buildHistory.unshift(build);
            
            // Keep only last 50 builds
            if (buildHistory.length > 50) {
                buildHistory = buildHistory.slice(0, 50);
            }
            
            updateBuildLists();
        }
        
        async function updateBuildLists() {
            try {
                const response = await fetch('/api/build-history');
                if (!response.ok) {
                    throw new Error('Failed to fetch build history');
                }
                
                const data = await response.json();
                const builds = data.builds || [];
                
                const successfulList = document.getElementById('successful-builds-list');
                const failedList = document.getElementById('failed-builds-list');
                
                const successful = builds.filter(b => b.success);
                const failed = builds.filter(b => !b.success);
                
                // Update successful builds
                if (successful.length === 0) {
                    successfulList.innerHTML = '<div class="no-builds">No successful builds yet</div>';
                } else {
                    let html = '';
                    successful.slice(0, 10).forEach(build => {
                        const date = new Date(build.timestamp).toLocaleString();
                        html += `
                            <div class="build-item success-item" onclick="loadBuildLogs('${build.distribution}')">
                                <span class="build-dist">${build.distribution}</span>
                                <span class="build-date">${date}</span>
                            </div>
                        `;
                    });
                    successfulList.innerHTML = html;
                }
                
                // Update failed builds
                if (failed.length === 0) {
                    failedList.innerHTML = '<div class="no-builds">No failed builds yet</div>';
                } else {
                    let html = '';
                    failed.slice(0, 10).forEach(build => {
                        const date = new Date(build.timestamp).toLocaleString();
                        html += `
                            <div class="build-item failed-item" onclick="loadBuildLogs('${build.distribution}')">
                                <span class="build-dist">${build.distribution}</span>
                                <span class="build-date">${date}</span>
                            </div>
                        `;
                    });
                    failedList.innerHTML = html;
                }
                
            } catch (error) {
                console.error('Error fetching build history:', error);
                // Fallback to in-memory data
                const successfulList = document.getElementById('successful-builds-list');
                const failedList = document.getElementById('failed-builds-list');
                
                const successful = buildHistory.filter(b => b.success);
                const failed = buildHistory.filter(b => !b.success);
                
                // Update successful builds
                if (successful.length === 0) {
                    successfulList.innerHTML = '<div class="no-builds">No successful builds yet</div>';
                } else {
                    let html = '';
                    successful.slice(0, 10).forEach(build => {
                        const date = build.timestamp.toLocaleString();
                        html += `
                            <div class="build-item success-item" onclick="loadBuildLogs('${build.dist}')">
                                <span class="build-dist">${build.dist}</span>
                                <span class="build-date">${date}</span>
                            </div>
                        `;
                    });
                    successfulList.innerHTML = html;
                }
                
                // Update failed builds
                if (failed.length === 0) {
                    failedList.innerHTML = '<div class="no-builds">No failed builds yet</div>';
                } else {
                    let html = '';
                    failed.slice(0, 10).forEach(build => {
                        const date = build.timestamp.toLocaleString();
                        html += `
                            <div class="build-item failed-item" onclick="loadBuildLogs('${build.dist}')">
                                <span class="build-dist">${build.dist}</span>
                                <span class="build-date">${date}</span>
                            </div>
                        `;
                    });
                    failedList.innerHTML = html;
                }
            }
        }
        
        function loadBuildLogs(distName) {
            // Create a synthetic event to simulate a regular click (not Ctrl+click)
            const syntheticEvent = {
                ctrlKey: false,
                metaKey: false
            };
            selectDistribution(syntheticEvent, distName);
            loadLogs();
        }
        
        async function updateStats() {
            try {
                const response = await fetch('/api/stats');
                if (!response.ok) {
                    throw new Error('Failed to fetch stats');
                }
                
                const data = await response.json();
                
                // Update the stat cards with server data
                document.getElementById('total-distributions').textContent = data.total_distributions || 0;
                document.getElementById('recent-tests').textContent = data.recent_builds || 0;
                document.getElementById('successful-builds').textContent = data.successful_builds || 0;
                document.getElementById('failed-builds').textContent = data.failed_builds || 0;
                
            } catch (error) {
                console.error('Error fetching stats:', error);
                // Fallback to in-memory data if server fails
                const now = new Date();
                const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000);
                
                const recent = buildHistory.filter(b => b.timestamp > yesterday);
                const successful = buildHistory.filter(b => b.success);
                const failed = buildHistory.filter(b => !b.success);
                
                // Get total distributions from the list
                const totalDistributions = document.querySelectorAll('.distribution-item').length;
                
                // Update the stat cards
                document.getElementById('total-distributions').textContent = totalDistributions;
                document.getElementById('recent-tests').textContent = recent.length;
                document.getElementById('successful-builds').textContent = successful.length;
                document.getElementById('failed-builds').textContent = failed.length;
            }
        }
        
        // Initialize on page load
        document.addEventListener('DOMContentLoaded', function() {
            updateStats();
            updateBuildLists();
        });
    </script>
</body>
</html>
        """
    
    def _get_audit_logs_template(self):
        """Get the HTML template for the audit logs page."""
        return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Audit Logs - Mirror Test</title>
    <style>
        :root {
            --primary-gradient: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            --secondary-gradient: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            --success-gradient: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
            --warning-gradient: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%);
            --error-gradient: linear-gradient(135deg, #fa709a 0%, #fee140 100%);
            
            --bg-primary: #0f0f23;
            --bg-secondary: #1a1a2e;
            --bg-tertiary: #16213e;
            --bg-card: rgba(255, 255, 255, 0.05);
            --bg-card-hover: rgba(255, 255, 255, 0.08);
            
            --text-primary: #ffffff;
            --text-secondary: #b8b8d1;
            --text-muted: #8b8ba7;
            
            --border-color: rgba(255, 255, 255, 0.1);
            --border-hover: rgba(255, 255, 255, 0.2);
            
            --shadow-sm: 0 2px 8px rgba(0, 0, 0, 0.1);
            --shadow-md: 0 4px 16px rgba(0, 0, 0, 0.2);
            --shadow-lg: 0 8px 32px rgba(0, 0, 0, 0.3);
            --shadow-xl: 0 16px 64px rgba(0, 0, 0, 0.4);
        }
        
        [data-theme="light"] {
            --bg-primary: #e2e8f0;
            --bg-secondary: #f1f5f9;
            --bg-tertiary: #cbd5e1;
            --bg-card: rgba(255, 255, 255, 0.8);
            --bg-card-hover: rgba(255, 255, 255, 0.9);
            
            /* Button gradients - Light mode */
            --btn-1-gradient: linear-gradient(135deg, #1e3a8a 0%, #1e40af 33%, #2563eb 66%, #3b82f6 100%);
            --btn-1-hover-gradient: linear-gradient(135deg, #1e40af 0%, #2563eb 33%, #3b82f6 66%, #60a5fa 100%);
            --btn-1-color: rgba(255, 255, 255, 0.9);
            --btn-1-hover-color: #ffffff;
            --btn-1-border: rgba(255, 255, 255, 0.3);
            --btn-1-hover-border: rgba(255, 255, 255, 0.5);
            
            --btn-2-gradient: linear-gradient(135deg, #1e40af 0%, #2563eb 33%, #3b82f6 66%, #60a5fa 100%);
            --btn-2-hover-gradient: linear-gradient(135deg, #2563eb 0%, #3b82f6 33%, #60a5fa 66%, #93c5fd 100%);
            --btn-2-color: rgba(255, 255, 255, 0.9);
            --btn-2-hover-color: #ffffff;
            --btn-2-border: rgba(255, 255, 255, 0.3);
            --btn-2-hover-border: rgba(255, 255, 255, 0.5);
            
            --btn-3-gradient: linear-gradient(135deg, #2563eb 0%, #3b82f6 33%, #60a5fa 66%, #93c5fd 100%);
            --btn-3-hover-gradient: linear-gradient(135deg, #3b82f6 0%, #60a5fa 33%, #93c5fd 66%, #bfdbfe 100%);
            --btn-3-color: rgba(255, 255, 255, 0.9);
            --btn-3-hover-color: #ffffff;
            --btn-3-border: rgba(255, 255, 255, 0.3);
            --btn-3-hover-border: rgba(255, 255, 255, 0.5);
            
            --btn-4-gradient: linear-gradient(135deg, #3b82f6 0%, #60a5fa 33%, #93c5fd 66%, #bfdbfe 100%);
            --btn-4-hover-gradient: linear-gradient(135deg, #60a5fa 0%, #93c5fd 33%, #bfdbfe 66%, #dbeafe 100%);
            --btn-4-color: rgba(255, 255, 255, 0.9);
            --btn-4-hover-color: #ffffff;
            --btn-4-border: rgba(255, 255, 255, 0.3);
            --btn-4-hover-border: rgba(255, 255, 255, 0.5);
            
            --btn-5-gradient: linear-gradient(135deg, #60a5fa 0%, #93c5fd 33%, #bfdbfe 66%, #dbeafe 100%);
            --btn-5-hover-gradient: linear-gradient(135deg, #93c5fd 0%, #bfdbfe 33%, #dbeafe 66%, #eff6ff 100%);
            --btn-5-color: rgba(255, 255, 255, 0.9);
            --btn-5-hover-color: #ffffff;
            --btn-5-border: rgba(255, 255, 255, 0.3);
            --btn-5-hover-border: rgba(255, 255, 255, 0.5);
            
            --btn-6-gradient: linear-gradient(135deg, #93c5fd 0%, #bfdbfe 33%, #dbeafe 66%, #eff6ff 100%);
            --btn-6-hover-gradient: linear-gradient(135deg, #bfdbfe 0%, #dbeafe 33%, #eff6ff 66%, #f8fafc 100%);
            --btn-6-color: rgba(255, 255, 255, 0.9);
            --btn-6-hover-color: #ffffff;
            --btn-6-border: rgba(255, 255, 255, 0.3);
            --btn-6-hover-border: rgba(255, 255, 255, 0.5);
            
            --text-primary: #1e293b;
            --text-secondary: #475569;
            --text-muted: #64748b;
            
            --border-color: rgba(0, 0, 0, 0.1);
            --border-hover: rgba(0, 0, 0, 0.2);
        }
        
        * { 
            margin: 0; 
            padding: 0; 
            box-sizing: border-box; 
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Inter', Oxygen, Ubuntu, sans-serif;
            background: var(--bg-primary);
            min-height: 100vh;
            color: var(--text-primary);
            transition: all 0.3s ease;
            overflow-x: hidden;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }
        
        .header {
            background: var(--bg-card);
            backdrop-filter: blur(20px);
            border-radius: 20px;
            padding: 20px 40px;
            margin-bottom: 30px;
            box-shadow: var(--shadow-lg);
            border: 1px solid var(--border-color);
            position: relative;
            overflow: hidden;
        }
        
        .header::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 4px;
            background: var(--primary-gradient);
        }
        
        .header-content {
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 20px;
        }
        
        .header-left h1 {
            font-size: 3em;
            margin-bottom: 10px;
            font-weight: 800;
            letter-spacing: -0.02em;
            display: flex;
            justify-content: space-between;
            align-items: center;
            width: 100%;
        }
        
        .header-left .penguin {
            color: var(--text-primary);
        }
        
        .header-left .title-text {
            background: var(--primary-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        
        .subtitle {
            color: var(--text-secondary);
            font-size: 1.2em;
            font-weight: 500;
            text-align: right;
            align-self: flex-end;
        }
        
        .header-right {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .theme-toggle, .back-button {
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-radius: 50px;
            padding: 8px 16px;
            cursor: pointer;
            transition: all 0.3s ease;
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 14px;
            font-weight: 600;
            color: var(--text-secondary);
            align-self: center;
            height: fit-content;
            text-decoration: none;
        }
        
        .theme-toggle:hover, .back-button:hover {
            background: var(--bg-card-hover);
            border-color: var(--border-hover);
            transform: translateY(-2px);
        }
        
        .logout-button {
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-radius: 50px;
            padding: 8px 16px;
            cursor: pointer;
            transition: all 0.3s ease;
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 14px;
            font-weight: 600;
            color: var(--text-secondary);
            align-self: center;
            height: fit-content;
            box-shadow: var(--shadow-sm);
        }
        
        .logout-button:hover {
            background: var(--bg-card-hover);
            border-color: var(--border-hover);
            transform: translateY(-2px);
            box-shadow: var(--shadow-md);
        }
        
        .audit-controls {
            background: var(--bg-card);
            backdrop-filter: blur(20px);
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: var(--shadow-md);
            border: 1px solid var(--border-color);
        }
        
        .filters {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        
        .filter-group {
            display: flex;
            flex-direction: column;
            gap: 5px;
        }
        
        .filter-group label {
            font-size: 12px;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .filter-group input, .filter-group select {
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 8px 10px;
            color: var(--text-primary);
            font-size: 13px;
            transition: all 0.3s ease;
        }
        
        .filter-group input:focus, .filter-group select:focus {
            outline: none;
            border-color: var(--border-hover);
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }
        
        .filter-actions {
            display: flex;
            gap: 10px;
            align-items: center;
            justify-content: flex-end;
            flex-wrap: wrap;
        }
        
        .btn {
            background: var(--primary-gradient);
            border: none;
            border-radius: 8px;
            padding: 10px 20px;
            color: white;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            font-size: 14px;
        }
        
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: var(--shadow-md);
        }
        
        .btn-secondary {
            background: var(--bg-tertiary);
            color: var(--text-primary);
            border: 1px solid var(--border-color);
        }
        
        .btn-secondary:hover {
            background: var(--bg-card-hover);
            border-color: var(--border-hover);
        }
        
        .audit-stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        
        .stat-card {
            background: var(--bg-card);
            backdrop-filter: blur(20px);
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            box-shadow: var(--shadow-sm);
            border: 1px solid var(--border-color);
            transition: all 0.3s ease;
        }
        
        .stat-card:hover {
            transform: translateY(-2px);
            box-shadow: var(--shadow-md);
        }
        
        .stat-value {
            font-size: 2em;
            font-weight: 700;
            margin-bottom: 5px;
        }
        
        .stat-label {
            font-size: 12px;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .audit-logs {
            background: var(--bg-card);
            backdrop-filter: blur(20px);
            border-radius: 15px;
            padding: 20px;
            box-shadow: var(--shadow-md);
            border: 1px solid var(--border-color);
        }
        
        .log-entry {
            background: var(--bg-tertiary);
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 10px;
            border-left: 4px solid var(--border-color);
            transition: all 0.3s ease;
        }
        
        .log-entry:hover {
            background: var(--bg-card-hover);
            transform: translateX(5px);
        }
        
        .log-entry.success {
            border-left-color: #10b981;
        }
        
        .log-entry.error {
            border-left-color: #ef4444;
        }
        
        .log-entry.warning {
            border-left-color: #f59e0b;
        }
        
        .log-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }
        
        .log-timestamp {
            font-size: 12px;
            color: var(--text-muted);
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
        }
        
        .log-type {
            background: var(--bg-secondary);
            color: var(--text-primary);
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
        }
        
        .log-details {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 10px;
            font-size: 14px;
        }
        
        .log-detail {
            display: flex;
            flex-direction: column;
            gap: 2px;
        }
        
        .log-detail-label {
            font-size: 11px;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .log-detail-value {
            color: var(--text-primary);
            font-weight: 500;
        }
        
        .loading {
            text-align: center;
            padding: 40px;
            color: var(--text-muted);
        }
        
        .no-logs {
            text-align: center;
            padding: 40px;
            color: var(--text-muted);
        }
        
        .pagination {
            display: flex;
            justify-content: center;
            gap: 10px;
            margin-top: 20px;
        }
        
        .page-btn {
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 8px 12px;
            color: var(--text-primary);
            cursor: pointer;
            transition: all 0.3s ease;
        }
        
        .page-btn:hover {
            background: var(--bg-card-hover);
            border-color: var(--border-hover);
        }
        
        .page-btn.active {
            background: var(--primary-gradient);
            color: white;
            border-color: transparent;
        }
        
        .page-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        
        @media (max-width: 768px) {
            .container { padding: 15px; }
            .header { padding: 20px; }
            .header-content { flex-direction: column; text-align: center; }
            .filters { 
                grid-template-columns: 1fr; 
                gap: 10px;
            }
            .filter-actions { 
                justify-content: center; 
                flex-wrap: wrap;
                gap: 8px;
            }
            .audit-stats { grid-template-columns: repeat(2, 1fr); }
            .log-details { grid-template-columns: 1fr; }
        }
        
        @media (max-width: 480px) {
            .filters {
                grid-template-columns: 1fr;
                gap: 8px;
            }
            .filter-actions {
                flex-direction: column;
                align-items: stretch;
            }
            .btn {
                width: 100%;
                margin-bottom: 5px;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="header-content">
                <div class="header-left">
                    <h1><span class="penguin">🐧</span><span class="title-text">Audit Logs</span></h1>
                    <p class="subtitle">Security and Activity Monitoring</p>
                </div>
                
                <div class="header-right">
                    <a href="/" class="back-button">
                        <span>←</span>
                        <span>Back to Main</span>
                    </a>
                    <div class="theme-toggle" onclick="toggleTheme()">
                        <span class="theme-icon">🌙</span>
                        <span id="theme-text">Dark Mode</span>
                    </div>
                    {% if auth_enabled and session.authenticated %}
                    <div class="logout-button" onclick="logout()">
                        <span class="logout-icon">🚪</span>
                        <span>Logout</span>
                    </div>
                    {% endif %}
                </div>
            </div>
        </div>
        
        <div class="audit-controls">
            <div class="filters">
                <div class="filter-group">
                    <label for="event-type">Event Type</label>
                    <select id="event-type">
                        <option value="">All Events</option>
                        <option value="authentication">Authentication</option>
                        <option value="api_access">API Access</option>
                        <option value="test_execution">Test Execution</option>
                        <option value="system">System</option>
                    </select>
                </div>
                <div class="filter-group">
                    <label for="user-filter">User</label>
                    <input type="text" id="user-filter" placeholder="Filter by user...">
                </div>
                <div class="filter-group">
                    <label for="status-filter">Status</label>
                    <select id="status-filter">
                        <option value="">All Status</option>
                        <option value="success">Success</option>
                        <option value="failure">Failure</option>
                    </select>
                </div>
                <div class="filter-group">
                    <label for="date-from">From Date</label>
                    <input type="datetime-local" id="date-from">
                </div>
                <div class="filter-group">
                    <label for="date-to">To Date</label>
                    <input type="datetime-local" id="date-to">
                </div>
            </div>
            <div class="filter-actions">
                <button class="btn" onclick="applyFilters()">Apply</button>
                <button class="btn btn-secondary" onclick="clearFilters()">Clear</button>
                <button class="btn btn-secondary" onclick="refreshLogs()">Refresh</button>
            </div>
        </div>
        
        <div class="audit-stats" id="audit-stats">
            <div class="stat-card">
                <div class="stat-value" id="total-events">0</div>
                <div class="stat-label">Total Events</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="success-rate">0%</div>
                <div class="stat-label">Success Rate</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="auth-events">0</div>
                <div class="stat-label">Auth Events</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="api-events">0</div>
                <div class="stat-label">API Events</div>
            </div>
        </div>
        
        <div class="audit-logs">
            <div id="logs-container">
                <div class="loading">Loading audit logs...</div>
            </div>
            <div class="pagination" id="pagination" style="display: none;">
                <button class="page-btn" id="prev-page" onclick="changePage(-1)">Previous</button>
                <span id="page-info">Page 1 of 1</span>
                <button class="page-btn" id="next-page" onclick="changePage(1)">Next</button>
            </div>
        </div>
    </div>
    
    <script>
        let currentPage = 1;
        let totalPages = 1;
        let currentFilters = {};
        
        // Theme toggle functionality
        function toggleTheme() {
            const body = document.body;
            const themeIcon = document.querySelector('.theme-icon');
            const themeText = document.getElementById('theme-text');
            
            if (body.getAttribute('data-theme') === 'light') {
                body.removeAttribute('data-theme');
                themeIcon.textContent = '🌙';
                themeText.textContent = 'Dark Mode';
                localStorage.setItem('theme', 'dark');
            } else {
                body.setAttribute('data-theme', 'light');
                themeIcon.textContent = '☀️';
                themeText.textContent = 'Light Mode';
                localStorage.setItem('theme', 'light');
            }
        }
        
        function logout() {
            if (confirm('Are you sure you want to logout?')) {
                window.location.href = '/logout';
            }
        }
        
        // Load saved theme on page load
        document.addEventListener('DOMContentLoaded', function() {
            const savedTheme = localStorage.getItem('theme');
            if (savedTheme === 'light') {
                document.body.setAttribute('data-theme', 'light');
                document.querySelector('.theme-icon').textContent = '☀️';
                document.getElementById('theme-text').textContent = 'Light Mode';
            }
            
            loadAuditStats();
            loadAuditLogs();
        });
        
        async function loadAuditStats() {
            try {
                const response = await fetch('/api/v1/audit-stats');
                const stats = await response.json();
                
                document.getElementById('total-events').textContent = stats.total_events || 0;
                document.getElementById('success-rate').textContent = Math.round(stats.success_rate || 0) + '%';
                document.getElementById('auth-events').textContent = stats.events_by_type?.authentication || 0;
                document.getElementById('api-events').textContent = stats.events_by_type?.api_access || 0;
            } catch (error) {
                console.error('Error loading audit stats:', error);
            }
        }
        
        async function loadAuditLogs() {
            try {
                const params = new URLSearchParams({
                    limit: 20,
                    offset: (currentPage - 1) * 20,
                    ...currentFilters
                });
                
                const response = await fetch(`/api/v1/audit-logs?${params}`);
                const data = await response.json();
                
                displayLogs(data.logs || []);
                updatePagination(data.total || 0);
            } catch (error) {
                console.error('Error loading audit logs:', error);
                document.getElementById('logs-container').innerHTML = 
                    '<div class="no-logs">Error loading audit logs. Please try again.</div>';
            }
        }
        
        function displayLogs(logs) {
            const container = document.getElementById('logs-container');
            
            if (logs.length === 0) {
                container.innerHTML = '<div class="no-logs">No audit logs found.</div>';
                return;
            }
            
            const logsHtml = logs.map(log => {
                const timestamp = new Date(log.timestamp).toLocaleString();
                const successClass = log.success ? 'success' : 'error';
                const typeClass = log.event_type || 'system';
                
                return `
                    <div class="log-entry ${successClass}">
                        <div class="log-header">
                            <span class="log-timestamp">${timestamp}</span>
                            <span class="log-type">${typeClass}</span>
                        </div>
                        <div class="log-details">
                            <div class="log-detail">
                                <div class="log-detail-label">User</div>
                                <div class="log-detail-value">${log.user || 'system'}</div>
                            </div>
                            <div class="log-detail">
                                <div class="log-detail-label">Action</div>
                                <div class="log-detail-value">${log.action || 'Unknown'}</div>
                            </div>
                            <div class="log-detail">
                                <div class="log-detail-label">IP Address</div>
                                <div class="log-detail-value">${log.ip_address || 'Unknown'}</div>
                            </div>
                            <div class="log-detail">
                                <div class="log-detail-label">Status</div>
                                <div class="log-detail-value">${log.success ? 'Success' : 'Failed'}</div>
                            </div>
                            ${log.details ? `
                            <div class="log-detail" style="grid-column: 1 / -1;">
                                <div class="log-detail-label">Details</div>
                                <div class="log-detail-value">${JSON.stringify(log.details, null, 2)}</div>
                            </div>
                            ` : ''}
                        </div>
                    </div>
                `;
            }).join('');
            
            container.innerHTML = logsHtml;
        }
        
        function updatePagination(total) {
            totalPages = Math.ceil(total / 20);
            const pagination = document.getElementById('pagination');
            const pageInfo = document.getElementById('page-info');
            const prevBtn = document.getElementById('prev-page');
            const nextBtn = document.getElementById('next-page');
            
            if (totalPages <= 1) {
                pagination.style.display = 'none';
                return;
            }
            
            pagination.style.display = 'flex';
            pageInfo.textContent = `Page ${currentPage} of ${totalPages}`;
            prevBtn.disabled = currentPage <= 1;
            nextBtn.disabled = currentPage >= totalPages;
        }
        
        function changePage(direction) {
            const newPage = currentPage + direction;
            if (newPage >= 1 && newPage <= totalPages) {
                currentPage = newPage;
                loadAuditLogs();
            }
        }
        
        function applyFilters() {
            currentFilters = {
                event_type: document.getElementById('event-type').value,
                user: document.getElementById('user-filter').value,
                status: document.getElementById('status-filter').value,
                start_date: document.getElementById('date-from').value,
                end_date: document.getElementById('date-to').value
            };
            
            // Remove empty filters
            Object.keys(currentFilters).forEach(key => {
                if (!currentFilters[key]) {
                    delete currentFilters[key];
                }
            });
            
            currentPage = 1;
            loadAuditLogs();
        }
        
        function clearFilters() {
            document.getElementById('event-type').value = '';
            document.getElementById('user-filter').value = '';
            document.getElementById('status-filter').value = '';
            document.getElementById('date-from').value = '';
            document.getElementById('date-to').value = '';
            currentFilters = {};
            currentPage = 1;
            loadAuditLogs();
        }
        
        function refreshLogs() {
            loadAuditStats();
            loadAuditLogs();
        }
    </script>
</body>
</html>
        """
    
    def start(self, args):
        """Start the Flask web server."""
        if not FLASK_AVAILABLE:
            print("Error: Flask is not available. Web interface cannot be launched.")
            return False
        
        # Check if port was specified via command line
        # Since --port has a default value, we need to check if it was actually provided
        import sys
        self._port_specified = '--port' in sys.argv
        port = getattr(args, 'port', 8080)
        debug = getattr(args, 'debug', False)
        ssl_cert = getattr(args, 'ssl_cert', None)
        ssl_key = getattr(args, 'ssl_key', None)
        ssl_context = getattr(args, 'ssl_context', None)
        open_browser = getattr(args, 'open_browser', False)
        
        # Load server configuration for port, SSL, and security settings
        import yaml
        import os
        config_file = os.path.expanduser("~/.config/mirror-test/server-config.yaml")
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    server_config = yaml.safe_load(f)
                
                # Store server config for security manager
                self.server_config = server_config
                
                # Use server port if no port was specified via command line
                server_port = server_config.get('server', {}).get('port')
                if server_port and not self._port_specified:
                    port = server_port
                    print(f"Using server port from configuration: {port}")
                else:
                    print(f"Port specified via command line: {self._port_specified}, using port: {port}")
                
                # Check SSL configuration (only if not already set via command line)
                if not ssl_cert and not ssl_key:
                    ssl_config = server_config.get('ssl', {})
                    if ssl_config.get('enabled', False):
                        ssl_cert = ssl_config.get('cert_file')
                        ssl_key = ssl_config.get('key_file')
                        print(f"SSL enabled from server configuration: {ssl_cert}")
                
                # Update security manager with server configuration
                self._update_security_manager(server_config)
                
            except Exception as e:
                print(f"Error loading server config: {e}")
        else:
            print(f"Server configuration not found: {config_file}")
            self.server_config = None
        
        # If no server config was loaded, try to load SSL config from command line args
        if not ssl_cert and not ssl_key:
            # This block is now empty since we moved the SSL logic above
            pass
        
        # Handle SSL configuration
        if ssl_cert and ssl_key:
            self.app.config['SESSION_COOKIE_SECURE'] = True
            print("SSL enabled: Session cookies will be secure-only")
            
            if open_browser:
                def open_browser_delayed():
                    time.sleep(1.5)
                    webbrowser.open(f'https://localhost:{port}')
                
                browser_thread = threading.Thread(target=open_browser_delayed)
                browser_thread.daemon = True
                browser_thread.start()
            
            self.app.run(host='0.0.0.0', port=port, debug=debug, 
                        ssl_context=(ssl_cert, ssl_key))
        else:
            self.app.config['SESSION_COOKIE_SECURE'] = False
            print("Warning: Running without SSL - session cookies not secure")
            
            if open_browser:
                def open_browser_delayed():
                    time.sleep(1.5)
                    webbrowser.open(f'http://localhost:{port}')
                
                browser_thread = threading.Thread(target=open_browser_delayed)
                browser_thread.daemon = True
                browser_thread.start()
            
            self.app.run(host='0.0.0.0', port=port, debug=debug)
        
        return True
