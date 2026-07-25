#!/usr/bin/env python3
"""
Test script to verify the intelligence module structure and imports.
"""

def test_imports():
    """Test that all modules can be imported correctly."""
    print("Testing intelligence module imports...")

    try:
        # Test main engine import
        from intelligence import intelligence_engine
        print("✓ Main intelligence engine imported successfully")

        # Test anomaly detection
        from intelligence.anomaly_detection.isolation_forest_detector import PriceAnomalyDetector
        print("✓ Anomaly detection module imported successfully")

        # Test product recommendations
        from intelligence.product_recommendations.cosine_similarity_recommender import ProductRecommender
        print("✓ Product recommendations module imported successfully")

        # Test price correlation
        from intelligence.price_correlation.pearson_correlation_tracker import PriceCorrelationTracker
        print("✓ Price correlation module imported successfully")

        # Test query trends
        from intelligence.query_trends.aggregation_pipeline import QueryTrendAggregator
        print("✓ Query trends module imported successfully")

        # Test convenience functions
        from intelligence import (
            get_intelligence_status,
            get_cached_trends,
            are_trends_fresh
        )
        print("✓ Convenience functions imported successfully")

        print("\nAll imports successful! ✓")
        return True

    except ImportError as e:
        print(f"✗ Import error: {e}")
        return False
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        return False

def test_basic_functionality():
    """Test basic functionality of initialized objects."""
    print("\nTesting basic object initialization...")

    try:
        from intelligence.anomaly_detection.isolation_forest_detector import PriceAnomalyDetector
        from intelligence.product_recommendations.cosine_similarity_recommender import ProductRecommender
        from intelligence.price_correlation.pearson_correlation_tracker import PriceCorrelationTracker
        from intelligence.query_trends.aggregation_pipeline import QueryTrendAggregator

        # Test creating instances
        anomaly_detector = PriceAnomalyDetector()
        print("✓ PriceAnomalyDetector instantiated")

        product_recommender = ProductRecommender()
        print("✓ ProductRecommender instantiated")

        correlation_tracker = PriceCorrelationTracker()
        print("✓ PriceCorrelationTracker instantiated")

        trend_aggregator = QueryTrendAggregator()
        print("✓ QueryTrendAggregator instantiated")

        print("All objects created successfully! ✓")
        return True

    except Exception as e:
        print(f"✗ Error creating objects: {e}")
        return False

if __name__ == "__main__":
    print("=" * 50)
    print("INTELLIGENCE MODULE TEST")
    print("=" * 50)

    success1 = test_imports()
    success2 = test_basic_functionality()

    print("\n" + "=" * 50)
    if success1 and success2:
        print("ALL TESTS PASSED! ✓")
        print("The intelligence module structure is ready for use.")
    else:
        print("SOME TESTS FAILED! ✗")
        print("Please check the errors above.")
    print("=" * 50)