"""
Admin user management and system operations
"""

import json
import logging
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from config.settings import (
    CREDENTIALS_FILE,
    USER_DATA_DIR,
    ACTIVITY_LOGS_DIR,
)
from auth.auth_manager import auth_manager, AuthManager
from storage.user_activity_log import get_activity_logs, clear_old_logs
from config.model_fallback import model_fallback

logger = logging.getLogger(__name__)


class AdminManager:
    """Manages admin operations and system administration"""
    
    def __init__(self):
        self.auth = auth_manager
    
    # ==================== User Management ====================
    
    def create_user(self, username: str, password: str, email: Optional[str] = None, is_admin: bool = False) -> Tuple[bool, Optional[str]]:
        """Create new user (admin only)"""
        try:
            success, user_id, error = self.auth.register(username, password, email)
            
            if success and is_admin:
                # Make user admin
                self.auth.users[username]["is_admin"] = True
                self.auth._save_credentials()
                logger.info(f"Created admin user: {username}")
            
            return success, error
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            return False, str(e)
    
    def delete_user(self, username: str) -> Tuple[bool, Optional[str]]:
        """Delete user and their data"""
        try:
            if username not in self.auth.users:
                return False, "User not found"
            
            # Get user_id before deletion
            user_id = self.auth.users[username]["user_id"]
            
            # Delete user credentials
            del self.auth.users[username]
            self.auth._save_credentials()
            
            # Delete user data directories
            user_conversations = Path(USER_DATA_DIR) / "conversations" / user_id
            user_diagrams = Path(USER_DATA_DIR) / "diagrams" / user_id
            user_uploads = Path(USER_DATA_DIR) / "uploads" / user_id
            
            for directory in [user_conversations, user_diagrams, user_uploads]:
                if directory.exists():
                    shutil.rmtree(directory)
            
            logger.info(f"Deleted user: {username}")
            return True, None
            
        except Exception as e:
            logger.error(f"Error deleting user: {e}")
            return False, str(e)
    
    def update_user_status(self, username: str, status: str) -> Tuple[bool, Optional[str]]:
        """Update user status (active, inactive, suspended)"""
        try:
            if username not in self.auth.users:
                return False, "User not found"
            
            if status not in ["active", "inactive", "suspended"]:
                return False, "Invalid status"
            
            self.auth.users[username]["status"] = status
            self.auth._save_credentials()
            
            logger.info(f"Updated user status: {username} -> {status}")
            return True, None
            
        except Exception as e:
            logger.error(f"Error updating user status: {e}")
            return False, str(e)
    
    def toggle_admin_status(self, username: str) -> Tuple[bool, Optional[str]]:
        """Toggle admin status for user"""
        try:
            if username not in self.auth.users:
                return False, "User not found"
            
            current_status = self.auth.users[username].get("is_admin", False)
            self.auth.users[username]["is_admin"] = not current_status
            self.auth._save_credentials()
            
            new_status = self.auth.users[username]["is_admin"]
            logger.info(f"Toggled admin status for {username}: {new_status}")
            return True, None
            
        except Exception as e:
            logger.error(f"Error toggling admin status: {e}")
            return False, str(e)
    
    def get_all_users_with_stats(self) -> List[Dict]:
        """Get all users with their statistics"""
        users = []
        try:
            for user_data in self.auth.get_all_users():
                user_id = user_data["user_id"]
                
                # Count conversations
                conversations_dir = Path(USER_DATA_DIR) / "conversations" / user_id
                diagrams_count = 0
                if conversations_dir.exists():
                    diagrams_count = len(list(conversations_dir.glob("*.json")))
                
                user_data["diagrams_created"] = diagrams_count
                users.append(user_data)
                
        except Exception as e:
            logger.error(f"Error getting users with stats: {e}")
        
        return users
    
    # ==================== System Health & Monitoring ====================
    
    def get_system_health(self) -> Dict:
        """Get system health information"""
        try:
            health = {
                "timestamp": datetime.utcnow().isoformat(),
                "status": "healthy",
                "models": {},
                "storage": {},
                "activity": {}
            }
            
            # Check model availability
            health["models"] = model_fallback.model_availability
            
            # Check storage usage
            try:
                total_size = sum(f.stat().st_size for f in USER_DATA_DIR.rglob('*') if f.is_file())
                health["storage"]["total_mb"] = round(total_size / (1024 * 1024), 2)
                health["storage"]["conversations_mb"] = self._get_dir_size("conversations")
                health["storage"]["diagrams_mb"] = self._get_dir_size("diagrams")
                health["storage"]["uploads_mb"] = self._get_dir_size("uploads")
            except Exception as e:
                logger.warning(f"Error calculating storage: {e}")
            
            # Activity stats
            try:
                activity_logs = get_activity_logs(limit=1000)
                today_activities = [
                    log for log in activity_logs
                    if log.get("timestamp", "").startswith(datetime.utcnow().date().isoformat())
                ]
                health["activity"]["total_logs"] = len(activity_logs)
                health["activity"]["today"] = len(today_activities)
            except Exception as e:
                logger.warning(f"Error getting activity stats: {e}")
            
            return health
            
        except Exception as e:
            logger.error(f"Error getting system health: {e}")
            return {"status": "error", "error": str(e)}
    
    def _get_dir_size(self, dir_name: str) -> float:
        """Get size of directory in MB"""
        try:
            dir_path = Path(USER_DATA_DIR) / dir_name
            if dir_path.exists():
                size = sum(f.stat().st_size for f in dir_path.rglob('*') if f.is_file())
                return round(size / (1024 * 1024), 2)
        except Exception as e:
            logger.debug(f"Error getting {dir_name} size: {e}")
        return 0.0
    
    # ==================== Model Configuration ====================
    
    def refresh_model_availability(self) -> Dict[str, bool]:
        """Refresh and check all model availability"""
        return model_fallback.refresh_model_availability()
    
    def get_model_configuration(self) -> Dict:
        """Get current model configuration"""
        return model_fallback.get_model_info()
    
    # ==================== Data Management ====================
    
    def get_admin_dashboard_stats(self) -> Dict:
        """Get comprehensive admin dashboard statistics"""
        try:
            users = self.auth.get_all_users()
            
            # Count total conversations and diagrams
            total_conversations = 0
            total_diagrams = 0
            for user in users:
                user_id = user["user_id"]
                conversations_dir = Path(USER_DATA_DIR) / "conversations" / user_id
                diagrams_dir = Path(USER_DATA_DIR) / "diagrams" / user_id
                
                if conversations_dir.exists():
                    total_conversations += len(list(conversations_dir.glob("*.json")))
                if diagrams_dir.exists():
                    total_diagrams += len(list(diagrams_dir.glob("*.drawio")))
            
            # Get activity stats
            activity_logs = get_activity_logs(limit=10000)
            today = datetime.utcnow().date()
            today_logins = [
                log for log in activity_logs
                if log.get("action") == "login" and 
                log.get("timestamp", "").startswith(today.isoformat())
            ]
            
            stats = {
                "total_users": len(users),
                "active_users": sum(1 for u in users if u.get("status") == "active"),
                "admin_users": sum(1 for u in users if u.get("is_admin")),
                "total_conversations": total_conversations,
                "total_diagrams": total_diagrams,
                "logins_today": len(today_logins),
                "total_activity_logs": len(activity_logs),
                "system_health": self.get_system_health()
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"Error getting dashboard stats: {e}")
            return {"error": str(e)}
    
    def cleanup_old_data(self, days: int = 90) -> Tuple[int, str]:
        """
        Clean up old data (conversations, diagrams, uploads)
        Returns: (number_of_items_deleted, status_message)
        """
        try:
            deleted_count = 0
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            # Clean old conversations
            conversations_dir = Path(USER_DATA_DIR) / "conversations"
            if conversations_dir.exists():
                for user_dir in conversations_dir.iterdir():
                    if user_dir.is_dir():
                        for conv_file in user_dir.glob("*.json"):
                            if datetime.fromtimestamp(conv_file.stat().st_mtime) < cutoff_date:
                                conv_file.unlink()
                                deleted_count += 1
            
            # Clean old diagrams
            diagrams_dir = Path(USER_DATA_DIR) / "diagrams"
            if diagrams_dir.exists():
                for user_dir in diagrams_dir.iterdir():
                    if user_dir.is_dir():
                        for diagram_file in user_dir.glob("*"):
                            if datetime.fromtimestamp(diagram_file.stat().st_mtime) < cutoff_date:
                                if diagram_file.is_file():
                                    diagram_file.unlink()
                                    deleted_count += 1
            
            # Clean old activity logs
            clear_old_logs(days)
            
            message = f"Cleaned up {deleted_count} old items from {days} days ago"
            logger.info(message)
            return deleted_count, message
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            return 0, f"Error during cleanup: {str(e)}"
    
    def backup_data(self, backup_path: Optional[Path] = None) -> Tuple[bool, str]:
        """Create backup of all user data"""
        try:
            if backup_path is None:
                backup_path = Path(USER_DATA_DIR) / "backups" / f"backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
            
            backup_path.mkdir(parents=True, exist_ok=True)
            
            # Copy all user data
            for item in USER_DATA_DIR.iterdir():
                if item.is_dir() and item.name != "backups":
                    destination = backup_path / item.name
                    if destination.exists():
                        shutil.rmtree(destination)
                    shutil.copytree(item, destination)
            
            logger.info(f"Data backed up to: {backup_path}")
            return True, f"Backup created at: {backup_path}"
            
        except Exception as e:
            logger.error(f"Error creating backup: {e}")
            return False, f"Error creating backup: {str(e)}"
    
    def export_user_activity(self, user_id: Optional[str] = None) -> Tuple[bool, str]:
        """Export user activity logs"""
        try:
            logs = get_activity_logs()
            
            if user_id:
                logs = [log for log in logs if log.get("user_id") == user_id]
            
            export_file = Path(USER_DATA_DIR) / f"activity_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
            
            with open(export_file, 'w') as f:
                json.dump(logs, f, indent=2, default=str)
            
            logger.info(f"Activity logs exported to: {export_file}")
            return True, str(export_file)
            
        except Exception as e:
            logger.error(f"Error exporting activity: {e}")
            return False, str(e)


# Global instance
admin_manager = AdminManager()


if __name__ == "__main__":
    # Test admin operations
    logging.basicConfig(level=logging.INFO)
    
    # Get dashboard stats
    stats = admin_manager.get_admin_dashboard_stats()
    print("Dashboard Stats:")
    print(json.dumps(stats, indent=2))
