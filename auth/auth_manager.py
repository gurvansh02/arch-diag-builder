"""
Authentication and user session management
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple
import bcrypt
import uuid

from config.settings import CREDENTIALS_FILE, SESSION_TIMEOUT
from config.models import User
from storage.user_activity_log import log_activity

logger = logging.getLogger(__name__)


class AuthManager:
    """Manages user authentication and session management"""
    
    def __init__(self, credentials_file: Path = CREDENTIALS_FILE):
        self.credentials_file = credentials_file
        self.load_or_create_credentials()
    
    def load_or_create_credentials(self):
        """Load credentials from file or create if doesn't exist"""
        if self.credentials_file.exists():
            try:
                with open(self.credentials_file, 'r', encoding='utf-8') as f:
                    self.users = json.load(f)
                logger.info(f"Loaded {len(self.users)} users from credentials file")
            except Exception as e:
                logger.error(f"Error loading credentials: {e}")
                self.users = {}
        else:
            self.users = {}
            # Create default admin user
            self._create_default_admin()
            self._save_credentials()
    
    def _create_default_admin(self):
        """Create default admin user on first run"""
        try:
            from config.settings import ADMIN_USERNAME, ADMIN_PASSWORD
            
            admin_user = {
                "user_id": str(uuid.uuid4()),
                "username": ADMIN_USERNAME,
                "password_hash": self._hash_password(ADMIN_PASSWORD),
                "is_admin": True,
                "created_at": datetime.utcnow().isoformat(),
                "last_login": None,
                "status": "active",
                "email": "admin@architecture-builder.local"
            }
            
            self.users[ADMIN_USERNAME] = admin_user
            logger.info(f"Created default admin user: {ADMIN_USERNAME}")
            
        except Exception as e:
            logger.error(f"Error creating default admin: {e}")
    
    def _save_credentials(self):
        """Save credentials to file"""
        try:
            # Ensure parent directory exists
            self.credentials_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.credentials_file, 'w', encoding='utf-8') as f:
                json.dump(self.users, f, indent=2, default=str)
            logger.debug("Credentials saved successfully")
        except Exception as e:
            logger.error(f"Error saving credentials: {e}")
    
    @staticmethod
    def _hash_password(password: str) -> str:
        """Hash password using bcrypt"""
        salt = bcrypt.gensalt(rounds=12)
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
    
    @staticmethod
    def _verify_password(password: str, password_hash: str) -> bool:
        """Verify password against hash"""
        try:
            return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
        except Exception as e:
            logger.error(f"Error verifying password: {e}")
            return False
    
    def login(self, username: str, password: str) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Authenticate user.
        Returns: (success, user_id, error_message)
        """
        try:
            if username not in self.users:
                logger.warning(f"Login attempt with non-existent user: {username}")
                log_activity(
                    user_id="unknown",
                    action="login_failed",
                    details={"reason": "user_not_found", "username": username},
                    status="failure"
                )
                return False, None, "Invalid username or password"
            
            user_data = self.users[username]
            
            if not self._verify_password(password, user_data["password_hash"]):
                logger.warning(f"Failed login attempt for user: {username}")
                log_activity(
                    user_id=user_data["user_id"],
                    action="login_failed",
                    details={"reason": "incorrect_password"},
                    status="failure"
                )
                return False, None, "Invalid username or password"
            
            if user_data.get("status") != "active":
                logger.warning(f"Login attempt with inactive user: {username}")
                return False, None, "Account is inactive"
            
            # Update last login
            user_data["last_login"] = datetime.utcnow().isoformat()
            self._save_credentials()
            
            user_id = user_data["user_id"]
            logger.info(f"Successful login for user: {username}")
            log_activity(
                user_id=user_id,
                action="login",
                details={"username": username},
                status="success"
            )
            
            return True, user_id, None
            
        except Exception as e:
            logger.error(f"Login error: {e}")
            return False, None, "An error occurred during login"
    
    def register(self, username: str, password: str, email: Optional[str] = None) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Register new user.
        Returns: (success, user_id, error_message)
        """
        try:
            if username in self.users:
                logger.warning(f"Registration attempt with existing username: {username}")
                return False, None, "Username already exists"
            
            if len(password) < 6:
                return False, None, "Password must be at least 6 characters"
            
            user_id = str(uuid.uuid4())
            new_user = {
                "user_id": user_id,
                "username": username,
                "password_hash": self._hash_password(password),
                "is_admin": False,
                "created_at": datetime.utcnow().isoformat(),
                "last_login": None,
                "status": "active",
                "email": email
            }
            
            self.users[username] = new_user
            self._save_credentials()
            
            logger.info(f"New user registered: {username}")
            log_activity(
                user_id=user_id,
                action="user_registered",
                details={"username": username, "email": email},
                status="success"
            )
            
            return True, user_id, None
            
        except Exception as e:
            logger.error(f"Registration error: {e}")
            return False, None, "An error occurred during registration"
    
    def change_password(self, username: str, old_password: str, new_password: str) -> Tuple[bool, Optional[str]]:
        """
        Change user password.
        Returns: (success, error_message)
        """
        try:
            if username not in self.users:
                return False, "User not found"
            
            user_data = self.users[username]
            
            if not self._verify_password(old_password, user_data["password_hash"]):
                return False, "Old password is incorrect"
            
            if len(new_password) < 6:
                return False, "New password must be at least 6 characters"
            
            user_data["password_hash"] = self._hash_password(new_password)
            self._save_credentials()
            
            logger.info(f"Password changed for user: {username}")
            log_activity(
                user_id=user_data["user_id"],
                action="password_changed",
                details={"username": username},
                status="success"
            )
            
            return True, None
            
        except Exception as e:
            logger.error(f"Error changing password: {e}")
            return False, "An error occurred while changing password"
    
    def get_user(self, username: str) -> Optional[Dict]:
        """Get user data"""
        if username in self.users:
            user_data = self.users[username].copy()
            user_data.pop("password_hash", None)  # Don't return password hash
            return user_data
        return None
    
    def get_all_users(self) -> list:
        """Get all users (admin only)"""
        users = []
        for username, user_data in self.users.items():
            user_copy = user_data.copy()
            user_copy.pop("password_hash", None)
            users.append(user_copy)
        return users
    
    def user_exists(self, username: str) -> bool:
        """Check if user exists"""
        return username in self.users
    
    def is_admin(self, username: str) -> bool:
        """Check if user is admin"""
        if username in self.users:
            return self.users[username].get("is_admin", False)
        return False
    
    def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        """Get user by user_id"""
        for username, user_data in self.users.items():
            if user_data.get("user_id") == user_id:
                user_copy = user_data.copy()
                user_copy.pop("password_hash", None)
                return user_copy
        return None
    
    def get_username_by_id(self, user_id: str) -> Optional[str]:
        """Get username by user_id"""
        for username, user_data in self.users.items():
            if user_data.get("user_id") == user_id:
                return username
        return None


# Global instance
auth_manager = AuthManager()


if __name__ == "__main__":
    # Test authentication
    logging.basicConfig(level=logging.INFO)
    
    # Test login with default admin
    success, user_id, error = auth_manager.login("admin", "admin123")
    print(f"Login test: {success}, User ID: {user_id}, Error: {error}")
