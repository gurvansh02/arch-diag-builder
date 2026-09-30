"""
Diagram storage and retrieval
Manages diagram persistence with draw.io XML storage
"""

import json
import logging
from pathlib import Path
from typing import List, Optional
from datetime import datetime
import uuid

from config.settings import DIAGRAMS_DIR
from config.models import DiagramMetadata

logger = logging.getLogger(__name__)


class DiagramStore:
    """Manages diagram persistence"""
    
    def __init__(self, base_dir: Path = DIAGRAMS_DIR):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_user_dir(self, user_id: str) -> Path:
        """Get or create user's diagrams directory"""
        user_dir = self.base_dir / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir
    
    def _get_diagram_path(self, user_id: str, diagram_id: str, extension: str = ".drawio") -> Path:
        """Get path to diagram file"""
        return self._get_user_dir(user_id) / f"{diagram_id}{extension}"
    
    def _get_metadata_path(self, user_id: str, diagram_id: str) -> Path:
        """Get path to diagram metadata file"""
        return self._get_user_dir(user_id) / f"{diagram_id}_meta.json"
    
    def save_diagram(
        self,
        user_id: str,
        conversation_id: str,
        diagram_type: str,
        drawio_xml: str,
        project_description: str,
        cloud_providers: List[str],
        architectural_pattern: Optional[str] = None,
        diagram_id: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> Optional[DiagramMetadata]:
        """Save diagram and its metadata"""
        try:
            if not diagram_id:
                diagram_id = str(uuid.uuid4())
            
            # Save draw.io XML
            diagram_path = self._get_diagram_path(user_id, diagram_id)
            with open(diagram_path, 'w', encoding='utf-8') as f:
                f.write(drawio_xml)
            
            # Create and save metadata
            metadata = DiagramMetadata(
                diagram_id=diagram_id,
                conversation_id=conversation_id,
                user_id=user_id,
                diagram_type=diagram_type,
                cloud_providers=cloud_providers,
                architectural_pattern=architectural_pattern,
                project_description=project_description,
                drawio_xml=drawio_xml,
                tags=tags or [],
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                version=1
            )
            
            metadata_path = self._get_metadata_path(user_id, diagram_id)
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(
                    json.loads(metadata.model_dump_json()),
                    f,
                    indent=2,
                    default=str
                )
            
            logger.info(f"Saved diagram: {diagram_id} for user: {user_id}")
            return metadata
            
        except Exception as e:
            logger.error(f"Error saving diagram: {e}")
            return None
    
    def load_diagram(self, user_id: str, diagram_id: str) -> Optional[str]:
        """Load diagram XML content"""
        try:
            diagram_path = self._get_diagram_path(user_id, diagram_id)
            
            if not diagram_path.exists():
                logger.warning(f"Diagram not found: {diagram_id}")
                return None
            
            with open(diagram_path, 'r', encoding='utf-8') as f:
                drawio_xml = f.read()
            
            logger.debug(f"Loaded diagram: {diagram_id}")
            return drawio_xml
            
        except Exception as e:
            logger.error(f"Error loading diagram: {e}")
            return None
    
    def load_diagram_metadata(self, user_id: str, diagram_id: str) -> Optional[DiagramMetadata]:
        """Load diagram metadata"""
        try:
            metadata_path = self._get_metadata_path(user_id, diagram_id)
            
            if not metadata_path.exists():
                logger.warning(f"Diagram metadata not found: {diagram_id}")
                return None
            
            with open(metadata_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            metadata = DiagramMetadata(**data)
            logger.debug(f"Loaded diagram metadata: {diagram_id}")
            
            return metadata
            
        except Exception as e:
            logger.error(f"Error loading diagram metadata: {e}")
            return None
    
    def update_diagram(
        self,
        user_id: str,
        diagram_id: str,
        drawio_xml: str,
        tags: Optional[List[str]] = None
    ) -> Optional[DiagramMetadata]:
        """Update existing diagram"""
        try:
            metadata = self.load_diagram_metadata(user_id, diagram_id)
            if not metadata:
                return None
            
            # Update XML
            diagram_path = self._get_diagram_path(user_id, diagram_id)
            with open(diagram_path, 'w', encoding='utf-8') as f:
                f.write(drawio_xml)
            
            # Update metadata
            metadata.drawio_xml = drawio_xml
            metadata.updated_at = datetime.utcnow()
            metadata.version += 1
            if tags:
                metadata.tags = tags
            
            metadata_path = self._get_metadata_path(user_id, diagram_id)
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(
                    json.loads(metadata.model_dump_json()),
                    f,
                    indent=2,
                    default=str
                )
            
            logger.info(f"Updated diagram: {diagram_id}")
            return metadata
            
        except Exception as e:
            logger.error(f"Error updating diagram: {e}")
            return None
    
    def get_user_diagrams(self, user_id: str) -> List[DiagramMetadata]:
        """Get all diagrams for a user"""
        try:
            user_dir = self._get_user_dir(user_id)
            diagrams = []
            
            for metadata_file in user_dir.glob("*_meta.json"):
                try:
                    with open(metadata_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    metadata = DiagramMetadata(**data)
                    diagrams.append(metadata)
                except Exception as e:
                    logger.warning(f"Error loading metadata from {metadata_file}: {e}")
                    continue
            
            # Sort by created_at (newest first)
            diagrams.sort(key=lambda d: d.created_at, reverse=True)
            logger.info(f"Loaded {len(diagrams)} diagrams for user: {user_id}")
            
            return diagrams
            
        except Exception as e:
            logger.error(f"Error getting user diagrams: {e}")
            return []
    
    def get_conversation_diagrams(self, user_id: str, conversation_id: str) -> List[DiagramMetadata]:
        """Get all diagrams for a specific conversation"""
        try:
            user_diagrams = self.get_user_diagrams(user_id)
            conversation_diagrams = [
                d for d in user_diagrams
                if d.conversation_id == conversation_id
            ]
            
            return conversation_diagrams
            
        except Exception as e:
            logger.error(f"Error getting conversation diagrams: {e}")
            return []
    
    def delete_diagram(self, user_id: str, diagram_id: str) -> bool:
        """Delete diagram and its metadata"""
        try:
            diagram_path = self._get_diagram_path(user_id, diagram_id)
            metadata_path = self._get_metadata_path(user_id, diagram_id)
            
            deleted = False
            
            if diagram_path.exists():
                diagram_path.unlink()
                deleted = True
            
            if metadata_path.exists():
                metadata_path.unlink()
                deleted = True
            
            if deleted:
                logger.info(f"Deleted diagram: {diagram_id}")
            
            return deleted
            
        except Exception as e:
            logger.error(f"Error deleting diagram: {e}")
            return False
    
    def search_diagrams(self, user_id: str, query: str) -> List[DiagramMetadata]:
        """Search diagrams by project description or tags"""
        try:
            diagrams = self.get_user_diagrams(user_id)
            results = []
            
            query_lower = query.lower()
            for diagram in diagrams:
                # Search in project description
                if query_lower in diagram.project_description.lower():
                    results.append(diagram)
                    continue
                
                # Search in tags
                if any(query_lower in tag.lower() for tag in diagram.tags):
                    results.append(diagram)
                    continue
                
                # Search in cloud providers
                if any(query_lower in provider.lower() for provider in diagram.cloud_providers):
                    results.append(diagram)
            
            return results
            
        except Exception as e:
            logger.error(f"Error searching diagrams: {e}")
            return []
    
    def get_diagram_stats(self, user_id: str) -> dict:
        """Get statistics about user's diagrams"""
        try:
            diagrams = self.get_user_diagrams(user_id)
            
            stats = {
                "total_diagrams": len(diagrams),
                "by_type": {},
                "by_cloud": {},
                "by_pattern": {},
                "total_versions": sum(d.version for d in diagrams)
            }
            
            for diagram in diagrams:
                # Count by type
                diagram_type = diagram.diagram_type
                stats["by_type"][diagram_type] = stats["by_type"].get(diagram_type, 0) + 1
                
                # Count by cloud
                for cloud in diagram.cloud_providers:
                    stats["by_cloud"][cloud] = stats["by_cloud"].get(cloud, 0) + 1
                
                # Count by pattern
                if diagram.architectural_pattern:
                    pattern = diagram.architectural_pattern
                    stats["by_pattern"][pattern] = stats["by_pattern"].get(pattern, 0) + 1
            
            return stats
            
        except Exception as e:
            logger.error(f"Error getting diagram stats: {e}")
            return {}


# Global instance
diagram_store = DiagramStore()
