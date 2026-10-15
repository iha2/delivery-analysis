import importlib

import pytest

PAIRS = [
    ("github_analysis.time_utils", "delivery_analysis.core.time_utils"),
    ("github_analysis.config", "delivery_analysis.connectors.github.config"),
    ("github_analysis.models", "delivery_analysis.connectors.github.models"),
    ("github_analysis.repo", "delivery_analysis.connectors.github.repo"),
    ("github_analysis.logging.run_log", "delivery_analysis.runlog"),
    ("github_analysis.github.client", "delivery_analysis.connectors.github.client"),
    ("github_analysis.github.preflight", "delivery_analysis.connectors.github.preflight"),
    ("github_analysis.github.pulls", "delivery_analysis.connectors.github.pulls"),
    ("github_analysis.catalog.search", "delivery_analysis.connectors.github.search"),
    ("github_analysis.analysis.pr_builder", "delivery_analysis.connectors.github.pr_builder"),
    ("github_analysis.analysis.reviews", "delivery_analysis.connectors.github.reviews"),
    ("github_analysis.analysis.summaries", "delivery_analysis.connectors.github.summaries"),
    (
        "github_analysis.analysis.authored_activity",
        "delivery_analysis.connectors.github.authored_activity",
    ),
    ("github_analysis.cache.raw_store", "delivery_analysis.connectors.github.raw_store"),
    ("github_analysis.pipeline.runner", "delivery_analysis.connectors.github.runner"),
]


@pytest.mark.parametrize("old,new", PAIRS)
def test_old_path_is_the_new_module(old, new):
    assert importlib.import_module(old) is importlib.import_module(new)


def test_private_names_survive_the_shim():
    from delivery_analysis.connectors.github.runner import _fetch_pr_detail as new_name
    from github_analysis.pipeline.runner import _fetch_pr_detail as old_name

    assert old_name is new_name


def test_pure_activity_logic_is_shared_with_core():
    from delivery_analysis.core import activity
    from github_analysis.analysis import authored_activity as old

    assert old.counts_merged_in_window is activity.counts_merged_in_window
    assert old.is_open_at_month_end is activity.is_open_at_month_end


def test_legacy_package_exports_still_work():
    import github_analysis

    assert github_analysis.RepositoryRef("org", "repo").slug == "org/repo"
