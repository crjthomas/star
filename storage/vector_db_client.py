"""Vector database client for ChromaDB."""
import chromadb
from typing import List, Dict, Any, Optional
from chromadb.config import Settings
from utils.logger import get_logger
from utils.helpers import get_env_var

logger = get_logger(__name__)

class VectorDBClient:
    """ChromaDB client for news embeddings."""
    
    def __init__(self):
        self.client: Optional[chromadb.ClientAPI] = None
        self.collection: Optional[chromadb.Collection] = None
        
    async def connect(self):
        """Connect to ChromaDB."""
        host = get_env_var("CHROMADB_HOST", "localhost")
        port = int(get_env_var("CHROMADB_PORT", "8010"))  # 8010 to match docker-compose (8000 = webhook)
        
        self.client = chromadb.HttpClient(
            host=host,
            port=port,
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )
        
        # Get or create collection for news embeddings
        self.collection = self.client.get_or_create_collection(
            name="news_embeddings",
            metadata={"description": "News article embeddings for similarity search"}
        )
        
        logger.info("Vector database connected")
    
    async def add_news_embeddings(
        self,
        ids: List[str],
        embeddings: List[List[float]],
        metadatas: List[Dict[str, Any]],
        documents: List[str]
    ):
        """Add news embeddings to the collection.
        
        Args:
            ids: Unique identifiers for each document
            embeddings: Vector embeddings
            metadatas: Metadata dictionaries (must include ticker, title, url, published_at)
            documents: Original text documents
        """
        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents
        )
        logger.debug(f"Added {len(ids)} news embeddings")
    
    async def query_similar_news(
        self,
        query_embedding: List[float],
        ticker: Optional[str] = None,
        n_results: int = 10,
        filter_dict: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Query similar news articles.
        
        Args:
            query_embedding: Query vector embedding
            ticker: Optional ticker to filter by
            n_results: Number of results to return
            filter_dict: Additional filters
            
        Returns:
            Dictionary with ids, distances, metadatas, documents
        """
        where = filter_dict or {}
        if ticker:
            where["ticker"] = ticker.upper()
        
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where if where else None
        )
        
        return results
    
    async def get_by_ids(self, ids: List[str]) -> Dict[str, Any]:
        """Get embeddings by IDs.
        
        Args:
            ids: List of IDs to retrieve
            
        Returns:
            Dictionary with ids, metadatas, documents
        """
        results = self.collection.get(ids=ids)
        return results

