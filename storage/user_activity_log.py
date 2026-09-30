"""
User activity logging system
Tracks all user actions for auditing and monitoring
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from config.settings import ACTIVITY_LOGS_DIR
from config.models import ActivityLog

logger = logging.getLogger(__name__)


# Ensure activity logs directory exists
ACTIVITY_LOGS_DIR.mkdir(parents=True, exist_ok=True)
ACTIVITY_LOG_FILE = ACTIVITY_LOGS_DIR / "activity.jsonl"


def log_activity(
    user_id: str,
    action: str,
    details: Optional[Dict] = None,
    status: str = "success",
    error_message: Optional[str] = None
) -> bool:
    """
    Log user activity to file (append-only JSONL format)
    
    Args:
        user_id: ID of the user performing the action
        action: Type of action (login, create_diagram, review, etc.)
        details: Additional details about the action
        status: success, failure, warning
        error_message: Error message if applicable
    
    Returns:
        True if logged successfully, False otherwise
    """
    try:
        activity = ActivityLog(
            user_id=user_id,
            action=action,
            details=details or {},
            status=status,
            error_message=error_message
        )
        
        # Append to JSONL file
        with open(ACTIVITY_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(activity.model_dump_json() + '\n')
        
        logger.debug(f"Logged activity: {user_id} - {action}")
        return True
        
    except Exception as e:
        logger.error(f"Error logging activity: {e}")
        return False


def get_activity_logs(
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    status: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = 1000
) -> List[Dict]:
    """
    Retrieve activity logs with filtering
    
    Args:
        user_id: Filter by user ID
        action: Filter by action type
        status: Filter by status
        start_date: Filter from this date
        end_date: Filter until this date
        limit: Maximum number of records to return
    
    Returns:
        List of activity logs matching criteria
    """
    try:
        logs = []
        
        if not ACTIVITY_LOG_FILE.exists():
            return logs
        
        with open(ACTIVITY_LOG_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                
                try:
                    log_entry = json.loads(line)
                    
                    # Apply filters
                    if user_id and log_entry.get("user_id") != user_id:
                        continue
                    if action and log_entry.get("action") != action:
                        continue
                    if status and log_entry.get("status") != status:
                        continue
                    
                    # Date filtering
                    if start_date or end_date:
                        log_timestamp = datetime.fromisoformat(log_entry.get("timestamp", ""))
                        if start_date and log_timestamp < start_date:
                            continue
                        if end_date and log_timestamp > end_date:
                            continue
                    
                    logs.append(log_entry)
                    
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON in activity log")
                    continue
        
        # Return most recent logs first
        logs.reverse()
        return logs[:limit]
        
    except Exception as e:
        logger.error(f"Error reading activity logs: {e}")
        return []


def get_user_activity_summary(user_id: str, days: int = 30) -> Dict:
    """
    Get summary of user's recent activities
    
    Args:
        user_id: User ID to get summary for
        days: Number of days to look back
    
    Returns:
        Dictionary with activity summary
    """
    try:
        start_date = datetime.utcnow() - timedelta(days=days)
        logs = get_activity_logs(
            user_id=user_id,
            start_date=start_date,
            limit=10000
        )
        
        summary = {
            "total_actions": len(logs),
            "action_counts": {},
            "status_counts": {
                "success": 0,
                "failure": 0,
                "warning": 0
            },
            "first_action": None,
            "last_action": None,
            "actions_by_date": {}
        }
        
        for log in logs:
            # Count by action
            action = log.get("action", "unknown")
            summary["action_counts"][action] = summary["action_counts"].get(action, 0) + 1
            
            # Count by status
            status = log.get("status", "unknown")
            if status in summary["status_counts"]:
                summary["status_counts"][status] += 1
            
            # Track first and last
            if not summary["last_action"]:  # Most recent (logs are reversed)
                summary["last_action"] = log.get("timestamp")
            summary["first_action"] = log.get("timestamp")
            
            # Group by date
            date_str = log.get("timestamp", "").split("T")[0]
            summary["actions_by_date"][date_str] = summary["actions_by_date"].get(date_str, 0) + 1
        
        return summary
        
    except Exception as e:
        logger.error(f"Error getting activity summary: {e}")
        return {}


def clear_old_logs(days: int = 90) -> int:
    """
    Delete activity logs older than specified days
    
    Args:
        days: Delete logs older than this many days
    
    Returns:
        Number of logs deleted
    """
    try:
        if not ACTIVITY_LOG_FILE.exists():
            return 0
        
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        deleted_count = 0
        remaining_logs = []
        
        with open(ACTIVITY_LOG_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    log_entry = json.loads(line)
                    log_timestamp = datetime.fromisoformat(log_entry.get("timestamp", ""))
                    
                    if log_timestamp >= cutoff_date:
                        remaining_logs.append(line)
                    else:
                        deleted_count += 1
                except:
                    remaining_logs.append(line)
        
        # Write back non-deleted logs
        with open(ACTIVITY_LOG_FILE, 'w', encoding='utf-8') as f:
            f.writelines(remaining_logs)
        
        logger.info(f"Cleared {deleted_count} old activity logs (older than {days} days)")
        return deleted_count
        
    except Exception as e:
        logger.error(f"Error clearing old logs: {e}")
        return 0


def export_logs_to_csv(user_id: Optional[str] = None) -> Optional[Path]:
    """
    Export activity logs to CSV format
    
    Args:
        user_id: If provided, export only this user's logs
    
    Returns:
        Path to exported CSV file, or None if error
    """
    try:
        import csv
        
        logs = get_activity_logs(user_id=user_id, limit=10000)
        
        if not logs:
            logger.warning("No logs to export")
            return None
        
        export_file = ACTIVITY_LOGS_DIR / f"activity_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
        
        with open(export_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=[
                "timestamp", "user_id", "action", "status", "error_message"
            ])
            writer.writeheader()
            
            for log in logs:
                writer.writerow({
                    "timestamp": log.get("timestamp"),
                    "user_id": log.get("user_id"),
                    "action": log.get("action"),
                    "status": log.get("status"),
                    "error_message": log.get("error_message", "")
                })
        
        logger.info(f"Logs exported to: {export_file}")
        return export_file
        
    except Exception as e:
        logger.error(f"Error exporting logs: {e}")
        return None
