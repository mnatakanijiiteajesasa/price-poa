## 6. Intelligence Layer (NLP Capabilities)

Phase 4 of the project introduced the intelligence engine, which provides advanced analytics capabilities. Note that the natural language processing (NLP) parser for extracting product names and locations from free-form user messages has been implemented and is now integrated into the Telegram webhook for fuzzy product matching.

The intelligence engine includes the following components:

- **Anomaly Detection**: Isolation Forest model to detect unusual price spikes or drops.
- **Product Recommendations**: Cosine similarity-based recommender to suggest substitutes or complementary products.
- **Price Correlation Tracking**: Pearson correlation analysis to identify leader-follower relationships between products across stores.
- **Query Trend Aggregation**: Analysis of user search queries to identify trending products and seasonal demand.

These components are orchestrated by the `IntelligenceEngine` class in `intelligence/intelligence_engine.py` and can be invoked via the API endpoints or background workers.

The intelligence components are initialized and maintained via the `initialize_intelligence` and `run_intelligence_maintenance` functions, which train/update models using recent data from the MongoDB database.