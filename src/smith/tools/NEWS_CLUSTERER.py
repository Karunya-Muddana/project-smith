"""
NEWS CLUSTERER — Semantic Text Clustering
-----------------------------------------
Groups news articles or text items by semantic similarity.
Provides cluster metrics and justifications.
"""

from typing import List, Dict, Any
from collections import Counter
import re


def extract_keywords(text: str, top_n: int = 5) -> List[str]:
    """Extract top keywords from text using simple frequency analysis."""
    # Remove common words
    stopwords = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
        'has', 'have', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
        'should', 'may', 'might', 'can', 'this', 'that', 'these', 'those',
        'as', 'it', 'its', 'which', 'who', 'what', 'where', 'when', 'why', 'how'
    }
    
    # Extract words
    words = re.findall(r'\b[a-z]{3,}\b', text.lower())
    words = [w for w in words if w not in stopwords]
    
    # Count frequency
    freq = Counter(words)
    return [word for word, _ in freq.most_common(top_n)]


def calculate_similarity(keywords1: List[str], keywords2: List[str]) -> float:
    """Calculate Jaccard similarity between two keyword sets."""
    set1 = set(keywords1)
    set2 = set(keywords2)
    
    if not set1 or not set2:
        return 0.0
    
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    
    return intersection / union if union > 0 else 0.0


def cluster_articles(articles: List[Dict[str, str]], similarity_threshold: float = 0.3) -> Dict[str, Any]:
    """
    Cluster articles by keyword similarity.
    
    Args:
        articles: List of dicts with 'title' and 'content' or 'snippet'
        similarity_threshold: Minimum similarity to group items
        
    Returns:
        Dict with clusters, metrics, and justifications
    """
    if not articles:
        return {"status": "error", "error": "No articles provided"}
    
    try:
        # Extract keywords for each article
        article_keywords = []
        for article in articles:
            text = article.get('title', '') + ' ' + article.get('content', '') + ' ' + article.get('snippet', '')
            keywords = extract_keywords(text)
            article_keywords.append({
                'article': article,
                'keywords': keywords
            })
        
        # Simple agglomerative clustering
        clusters = []
        assigned = set()
        
        for i, item in enumerate(article_keywords):
            if i in assigned:
                continue
            
            # Start new cluster
            cluster = {
                'items': [item['article']],
                'keywords': item['keywords'].copy(),
                'indices': [i]
            }
            assigned.add(i)
            
            # Find similar items
            for j, other in enumerate(article_keywords):
                if j in assigned or j <= i:
                    continue
                
                sim = calculate_similarity(item['keywords'], other['keywords'])
                if sim >= similarity_threshold:
                    cluster['items'].append(other['article'])
                    cluster['indices'].append(j)
                    # Merge keywords
                    all_keywords = cluster['keywords'] + other['keywords']
                    cluster['keywords'] = list(Counter(all_keywords).most_common(5))
                    cluster['keywords'] = [k[0] for k in cluster['keywords']]
                    assigned.add(j)
            
            clusters.append(cluster)
        
        # Generate theme names from top keywords
        result_clusters = []
        for idx, cluster in enumerate(clusters):
            theme = ' + '.join(cluster['keywords'][:3]).title()
            if not theme:
                theme = f"Cluster {idx + 1}"
            
            result_clusters.append({
                'theme': theme,
                'count': len(cluster['items']),
                'keywords': cluster['keywords'],
                'articles': cluster['items']
            })
        
        # Sort by size
        result_clusters.sort(key=lambda x: x['count'], reverse=True)
        
        return {
            "status": "success",
            "cluster_count": len(result_clusters),
            "total_articles": len(articles),
            "clusters": result_clusters,
            "metrics": {
                "largest_cluster": result_clusters[0]['count'] if result_clusters else 0,
                "smallest_cluster": result_clusters[-1]['count'] if result_clusters else 0,
                "avg_cluster_size": round(len(articles) / len(result_clusters), 1) if result_clusters else 0
            }
        }
        
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ===========================================================================
# SMITH AGENT INTERFACE
# ===========================================================================

def run_clustering_tool(
    articles: List[Dict[str, str]],
    similarity_threshold: float = 0.3
):
    """
    Cluster news articles or text items.
    
    Args:
        articles: List of dicts with 'title' and 'content'/'snippet'
        similarity_threshold: 0.0-1.0, minimum similarity to group (default 0.3)
    """
    return cluster_articles(articles, similarity_threshold)


news_clusterer = run_clustering_tool


METADATA = {
    "name": "news_clusterer",
    "description": "Cluster news articles or text items by semantic similarity. Returns themes, counts, and metrics.",
    "function": "run_clustering_tool",
    "dangerous": False,
    "domain": "computation",
    "output_type": "structured",
    "parameters": {
        "type": "object",
        "properties": {
            "articles": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "snippet": {"type": "string"}
                    }
                },
                "description": "List of articles to cluster"
            },
            "similarity_threshold": {
                "type": "number",
                "default": 0.3,
                "description": "Minimum similarity (0-1) to group items together"
            }
        },
        "required": ["articles"]
    }
}
