"""ChromaDB RAG Manager — Store and query trade reviews for self-learning.

Exports learned patterns from Post-Mortem to a vector database.
Executor queries this before deciding on new trades.
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path

try:
    import chromadb
except ImportError:
    chromadb = None


class RAGManager:
    """Manage trade review embeddings via ChromaDB."""

    def __init__(self, db_path: Optional[str] = None, verbose: bool = False):
        """Init ChromaDB client and collection.

        Args:
            db_path: Directory for ChromaDB. Defaults to .brahmand_data/rag/
            verbose: Print operations
        """
        if chromadb is None:
            raise ImportError("chromadb not installed. Install via: pip install chromadb")

        self.verbose = verbose
        self.db_path = db_path or str(
            Path.home() / "trading_ceo/antariksh/.brahmand_data/rag"
        )
        Path(self.db_path).mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(path=self.db_path)
        self.collection = self.client.get_or_create_collection(
            name="trade_reviews", metadata={"hnsw:space": "cosine"}
        )

        if self.verbose:
            print(f"✓ RAGManager initialized at {self.db_path}")

    def store_trade_review(self, review: Dict) -> str:
        """Store a trade review in ChromaDB.

        Args:
            review: {date, trade_id, strategy, pnl, success, lesson_learned, execution_summary, ...}

        Returns:
            Document ID (for later deletion/update)
        """
        doc_id = f"{review.get('date', datetime.now().strftime('%Y-%m-%d'))}_{review.get('trade_id', 'unknown')}"

        # Text embedding: execution_summary is what gets vectorized
        text = review.get(
            "execution_summary",
            f"Trade {review.get('trade_id')} {review.get('strategy')} "
            f"({review.get('market_regime', 'unknown')} regime) "
            f"— {review.get('lesson_learned', 'no notes')}",
        )

        # Metadata for filtering
        metadata = {
            "date": review.get("date", ""),
            "trade_id": review.get("trade_id", ""),
            "strategy": review.get("strategy", "unknown"),
            "market_regime": review.get("market_regime", "unknown"),
            "success": "yes" if review.get("success") else "no",
            "pnl": str(review.get("pnl", 0)),
        }

        self.collection.upsert(
            ids=[doc_id],
            documents=[text],
            metadatas=[metadata],
        )

        if self.verbose:
            print(f"  ✓ Stored review {doc_id} (strategy={metadata['strategy']})")

        return doc_id

    def query_similar_trades(
        self,
        query_text: str,
        n_results: int = 5,
        strategy_filter: Optional[str] = None,
        regime_filter: Optional[str] = None,
        success_only: bool = False,
    ) -> List[Dict]:
        """Query similar trades from ChromaDB using semantic search.

        Args:
            query_text: Natural language query, e.g., "Iron Fly in sideways market"
            n_results: Number of results to return
            strategy_filter: Filter by strategy (IRON_FLY, CREDIT_SPREAD)
            regime_filter: Filter by market regime (SIDEWAYS, TRENDING)
            success_only: Only return profitable trades

        Returns:
            [{trade_id, strategy, pnl, lesson_learned, similarity_score}, ...]
        """
        where = None

        # Build filter if specified
        if strategy_filter or regime_filter or success_only:
            where = {}
            if strategy_filter:
                where["strategy"] = strategy_filter
            if regime_filter:
                where["market_regime"] = regime_filter
            if success_only:
                where["success"] = "yes"

        try:
            results = self.collection.query(
                query_texts=[query_text],
                n_results=n_results,
                where=where,
            )

            trades = []
            if results["ids"] and len(results["ids"]) > 0:
                for i, doc_id in enumerate(results["ids"][0]):
                    trade = {
                        "doc_id": doc_id,
                        "strategy": (
                            results["metadatas"][0][i].get("strategy", "unknown")
                            if results["metadatas"] and len(results["metadatas"]) > 0
                            else "unknown"
                        ),
                        "pnl": (
                            float(
                                results["metadatas"][0][i].get("pnl", "0")
                                if results["metadatas"] and len(results["metadatas"]) > 0
                                else "0"
                            )
                        ),
                        "market_regime": (
                            results["metadatas"][0][i].get("market_regime", "unknown")
                            if results["metadatas"] and len(results["metadatas"]) > 0
                            else "unknown"
                        ),
                        "success": (
                            results["metadatas"][0][i].get("success", "unknown")
                            == "yes"
                            if results["metadatas"] and len(results["metadatas"]) > 0
                            else False
                        ),
                        "text": results["documents"][0][i] if results["documents"] else "",
                    }
                    trades.append(trade)

            if self.verbose:
                print(
                    f"  ✓ Found {len(trades)} similar trades "
                    f"(strategy={strategy_filter}, regime={regime_filter})"
                )

            return trades

        except Exception as e:
            if self.verbose:
                print(f"  ⚠ Query failed: {e}")
            return []

    def get_all_reviews(self) -> List[Dict]:
        """Get all stored trade reviews."""
        try:
            results = self.collection.get()
            if not results["ids"]:
                return []

            reviews = []
            for i, doc_id in enumerate(results["ids"]):
                reviews.append(
                    {
                        "doc_id": doc_id,
                        "metadata": results["metadatas"][i] if results["metadatas"] else {},
                        "text": results["documents"][i] if results["documents"] else "",
                    }
                )
            return reviews
        except Exception as e:
            if self.verbose:
                print(f"  ⚠ Failed to fetch reviews: {e}")
            return []

    def count_reviews(self) -> int:
        """Count total stored reviews."""
        try:
            return self.collection.count()
        except Exception:
            return 0

    def clear(self) -> None:
        """Clear all reviews (for testing)."""
        try:
            self.client.delete_collection(name="trade_reviews")
            self.collection = self.client.get_or_create_collection(
                name="trade_reviews", metadata={"hnsw:space": "cosine"}
            )
            if self.verbose:
                print("  ✓ Cleared all reviews")
        except Exception as e:
            if self.verbose:
                print(f"  ⚠ Failed to clear: {e}")
