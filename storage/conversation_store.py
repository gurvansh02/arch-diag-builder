"""
Conversation storage and retrieval
Manages conversation history with JSON file storage
"""

import json
import logging
from pathlib import Path
from typing import List, Optional
from datetime import datetime
import uuid

from config.settings import CONVERSATIONS_DIR
from config.models import Conversation, Message

logger = logging.getLogger(__name__)


class ConversationStore:
    """Manages conversation persistence"""
    
    def __init__(self, base_dir: Path = CONVERSATIONS_DIR):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_user_dir(self, user_id: str) -> Path:
        """Get or create user's conversation directory"""
        user_dir = self.base_dir / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir
    
    def _get_conversation_path(self, user_id: str, conversation_id: str) -> Path:
        """Get path to conversation file"""
        return self._get_user_dir(user_id) / f"{conversation_id}.json"
    
    def create_conversation(
        self,
        user_id: str,
        title: str,
        conversation_id: Optional[str] = None
    ) -> Conversation:
        """Create new conversation"""
        try:
            if not conversation_id:
                conversation_id = str(uuid.uuid4())
            
            conversation = Conversation(
                conversation_id=conversation_id,
                user_id=user_id,
                title=title,
                messages=[],
                diagram_ids=[],
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                is_archived=False
            )
            
            # Save immediately
            self.save_conversation(conversation)
            logger.info(f"Created conversation: {conversation_id} for user: {user_id}")
            
            return conversation
            
        except Exception as e:
            logger.error(f"Error creating conversation: {e}")
            raise
    
    def save_conversation(self, conversation: Conversation) -> bool:
        """Save conversation to file"""
        try:
            conversation.updated_at = datetime.utcnow()
            path = self._get_conversation_path(conversation.user_id, conversation.conversation_id)
            
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(
                    json.loads(conversation.model_dump_json()),
                    f,
                    indent=2,
                    default=str
                )
            
            logger.debug(f"Saved conversation: {conversation.conversation_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving conversation: {e}")
            return False
    
    def load_conversation(self, user_id: str, conversation_id: str) -> Optional[Conversation]:
        """Load conversation from file"""
        try:
            path = self._get_conversation_path(user_id, conversation_id)
            
            if not path.exists():
                logger.warning(f"Conversation not found: {conversation_id}")
                return None
            
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            conversation = Conversation(**data)
            logger.debug(f"Loaded conversation: {conversation_id}")
            
            return conversation
            
        except Exception as e:
            logger.error(f"Error loading conversation: {e}")
            return None
    
    def add_message(
        self,
        user_id: str,
        conversation_id: str,
        role: str,
        content: str,
        message_type: str = "text",
        metadata: Optional[dict] = None
    ) -> Optional[Message]:
        """Add message to conversation"""
        try:
            conversation = self.load_conversation(user_id, conversation_id)
            if not conversation:
                logger.error(f"Conversation not found: {conversation_id}")
                return None
            
            message = Message(
                role=role,
                content=content,
                type=message_type,
                metadata=metadata or {}
            )
            
            conversation.messages.append(message)
            self.save_conversation(conversation)
            
            logger.debug(f"Added message to conversation: {conversation_id}")
            return message
            
        except Exception as e:
            logger.error(f"Error adding message: {e}")
            return None
    
    def add_diagram_to_conversation(
        self,
        user_id: str,
        conversation_id: str,
        diagram_id: str
    ) -> bool:
        """Add diagram reference to conversation"""
        try:
            conversation = self.load_conversation(user_id, conversation_id)
            if not conversation:
                return False
            
            if diagram_id not in conversation.diagram_ids:
                conversation.diagram_ids.append(diagram_id)
                self.save_conversation(conversation)
            
            return True
            
        except Exception as e:
            logger.error(f"Error adding diagram to conversation: {e}")
            return False
    
    def get_all_conversations(self, user_id: str) -> List[Conversation]:
        """Get all conversations for a user"""
        try:
            user_dir = self._get_user_dir(user_id)
            conversations = []
            
            for conv_file in user_dir.glob("*.json"):
                try:
                    with open(conv_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    conversation = Conversation(**data)
                    conversations.append(conversation)
                except Exception as e:
                    logger.warning(f"Error loading conversation from {conv_file}: {e}")
                    continue
            
            # Sort by updated_at (newest first)
            conversations.sort(key=lambda c: c.updated_at, reverse=True)
            logger.info(f"Loaded {len(conversations)} conversations for user: {user_id}")
            
            return conversations
            
        except Exception as e:
            logger.error(f"Error getting conversations: {e}")
            return []
    
    def archive_conversation(self, user_id: str, conversation_id: str) -> bool:
        """Archive a conversation"""
        try:
            conversation = self.load_conversation(user_id, conversation_id)
            if not conversation:
                return False
            
            conversation.is_archived = True
            self.save_conversation(conversation)
            
            logger.info(f"Archived conversation: {conversation_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error archiving conversation: {e}")
            return False
    
    def delete_conversation(self, user_id: str, conversation_id: str) -> bool:
        """Delete a conversation"""
        try:
            path = self._get_conversation_path(user_id, conversation_id)
            
            if path.exists():
                path.unlink()
                logger.info(f"Deleted conversation: {conversation_id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error deleting conversation: {e}")
            return False
    
    def get_conversation_summary(self, conversation: Conversation) -> dict:
        """Get summary of conversation"""
        return {
            "id": conversation.conversation_id,
            "title": conversation.title,
            "message_count": len(conversation.messages),
            "diagram_count": len(conversation.diagram_ids),
            "created_at": conversation.created_at.isoformat(),
            "updated_at": conversation.updated_at.isoformat(),
            "is_archived": conversation.is_archived,
            "last_message_type": conversation.messages[-1].type if conversation.messages else None
        }
    
    def search_conversations(self, user_id: str, query: str) -> List[Conversation]:
        """Search conversations by title or content"""
        try:
            conversations = self.get_all_conversations(user_id)
            results = []
            
            query_lower = query.lower()
            for conv in conversations:
                # Search in title
                if query_lower in conv.title.lower():
                    results.append(conv)
                    continue
                
                # Search in messages
                for message in conv.messages:
                    if query_lower in message.content.lower():
                        results.append(conv)
                        break
            
            return results
            
        except Exception as e:
            logger.error(f"Error searching conversations: {e}")
            return []


# Global instance
conversation_store = ConversationStore()
