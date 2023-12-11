import logging
from typing import List, Tuple
import numpy as np
from haystack.nodes.base import BaseComponent
from haystack.schema import Document
from sklearn.base import TransformerMixin
from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.cluster import AgglomerativeClustering
from sklearn.cluster import DBSCAN
from typing import Optional, Any
from collections import defaultdict, Counter

from sklearn.base import TransformerMixin

logger = logging.getLogger(__name__)


class DenseTransformer(TransformerMixin):
    def fit(self, X, y=None, **fit_params):
        return self

    def transform(self, X, y=None, **fit_params):
        return X.todense()


class CountTransformerClustering(BaseComponent):
    outgoing_edges = 1

    def __init__(
        self,
        min_cluster_size: int = 2,
        embedder: Optional[Any] = None,
        separator_for_cluster_texts: str = "\n",
        **kwargs,
    ):
        """
        Use sklearn to vectorize and cluster documents.
        :param separator_for_single_summary: If `generate_single_summary=True` in `predict()`, we need to join all docs
                                             into a single text. This separator appears between those subsequent docs.
        """
        # save init parameters to enable export of component config as YAML
        self.separator_for_cluster_texts = separator_for_cluster_texts
        self.min_cluster_size = min_cluster_size

        from sklearn.pipeline import Pipeline

        vectorizer = CountVectorizer(
            preprocessor=None, tokenizer=None, analyzer=lambda x: x
        )
        clustering = AgglomerativeClustering(
            n_clusters=None,
            affinity="cos",
            linkage="complete",
            distance_threshold=0.3,
        )

        self.pipeline = Pipeline(
            [
                (
                    "count_vectorizer",
                    vectorizer,
                ),
                ("to_dense", DenseTransformer()),
                ("agg_clustering", clustering),
            ]
        )
        self.embedder = embedder
        self.clustering = DBSCAN(**kwargs)

    def run(self, documents: List[Document]):  # type: ignore

        results: dict = {
            "documents": [],
            "n_total_documents": len(documents),
            "n_clusters": 0,
            "n_documents": 0,
        }

        if documents:
            (
                results["documents"],
                results["n_clusters"],
                results["n_documents"],
            ) = self.predict(documents=documents)

        return results, "output_1"

    def predict(
        self,
        documents: List[Document],
    ) -> Tuple[List[Document], int, int]:
        """
        Produce the clustering for the supplied documents.
        These document can for example be retrieved via the Retriever.
        :param documents: Related documents (e.g. coming from a retriever) that the answer shall be conditioned on.
        :return: List of Documents, where Document.text contains the concatenated text of clusters and Document.meta["ids"]
                 ids of the original documents
        """
        if len(documents) == 0:
            raise AttributeError(
                "Summarizer needs at least one document to produce a summary."
            )

        cluster_documents = [
            list(set([ent.lower() for ent in doc.meta.get("concepts", [])]))
            for doc in documents
        ]
        clusters = self.pipeline.fit(cluster_documents)[-1].labels_
        n_clusters = np.unique(clusters).size
        cluster_counts = Counter(clusters)

        other_cluster = []

        keyword_document_clusters = defaultdict(lambda: list())
        for cluster, document in zip(clusters, documents):
            if cluster_counts[cluster] < self.min_cluster_size:
                other_cluster.append(document)
                continue
            keyword_document_clusters[cluster].append(document)

        document_clusters = defaultdict(lambda: list())
        for (
            keyword_cluster,
            keyword_document_cluster,
        ) in keyword_document_clusters.items():

            contents = [doc.content for doc in keyword_document_cluster]
            document_embeddings = self.embedder.encode(
                contents, convert_to_tensor=True
            ).cpu()

            clusters = self.clustering.fit(document_embeddings).labels_
            n_clusters = len(list(set(clusters)))
            logger.info(
                f"{n_clusters} clusters for {len(documents)} documents: {clusters}"
            )
            for cluster, document in zip(clusters, keyword_document_cluster):
                if cluster < 0:
                    other_cluster.append(document)
                    continue
                document_clusters[(keyword_cluster, cluster)].append(document)

        result: List[Document] = []
        document_clusters = list(document_clusters.values())
        n_documents = 0
        n_clusters = len(document_clusters)
        logger.info(f"{n_clusters} filtered clusters for {len(documents)} documents")
        for document_cluster in document_clusters:
            n_documents += len(document_cluster)
            context: List[str] = [doc.content for doc in document_cluster]
            # Documents order is very important to produce summary.
            # Different order of same documents produce different summary.
            context_text = self.separator_for_cluster_texts.join(context)
            cur_doc = Document(
                content=context_text,
                meta={
                    "documents": [doc.to_dict() for doc in document_cluster],
                },
            )
            result.append(cur_doc)

        result.sort(key=lambda x: len(x.meta["documents"]), reverse=True)

        if other_cluster:
            result.append(
                Document(
                    content="",
                    meta={
                        "documents": [doc.to_dict() for doc in other_cluster],
                    },
                )
            )

        return result, n_clusters, n_documents
