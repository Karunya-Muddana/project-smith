"""
Test Orchestrator Loading
--------------------------
Simple test to verify the orchestrator loads without errors.
"""

import pytest


def test_orchestrator_imports():
    """Verify orchestrator module imports successfully."""
    try:
        from smith.core.orchestrator import smith_orchestrator

        assert smith_orchestrator is not None
    except ImportError as e:
        pytest.fail(f"Failed to import orchestrator: {e}")


def test_orchestrator_callable():
    """Verify orchestrator function is callable."""
    from smith.core.orchestrator import smith_orchestrator

    assert callable(smith_orchestrator)


def test_orchestrator_has_required_functions():
    """Verify orchestrator module has required functions."""
    from smith.core import orchestrator

    # Check for main orchestrator function
    assert hasattr(orchestrator, "smith_orchestrator")

    # Check for reset function (used in testing)
    assert hasattr(orchestrator, "reset_services")


def test_reset_services_works():
    """Verify reset_services function works without errors."""
    from smith.core.orchestrator import reset_services

    try:
        reset_services()
        # Should complete without raising exceptions
    except Exception as e:
        pytest.fail(f"reset_services raised an exception: {e}")


def test_orchestrator_initialization():
    """Verify orchestrator can be initialized (but not executed)."""
    from smith.core.orchestrator import smith_orchestrator, reset_services

    # Reset services to clean state
    reset_services()

    try:
        # Create the generator (this initializes but doesn't run)
        gen = smith_orchestrator("test query")

        # Verify it's a generator
        assert hasattr(gen, "__next__")

        # Don't actually run it - just verify it initializes
    except Exception as e:
        pytest.fail(f"Orchestrator initialization failed: {e}")
    finally:
        reset_services()
