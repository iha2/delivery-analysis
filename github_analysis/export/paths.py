from __future__ import annotations

import os

from github_analysis.config import default_output_dir


def safe_repo_filename(repo_name: str, start_date: str, end_date: str) -> str:
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in repo_name.strip())
    return f"{safe or 'repo'}_{start_date}_to_{end_date}.tsv"


def _output_dir(output_dir: str | None = None) -> str:
    return os.path.expanduser(output_dir or default_output_dir())


def default_detail_path(
    repo_name: str,
    start_date: str,
    end_date: str,
    *,
    output_dir: str | None = None,
) -> str:
    return os.path.join(
        _output_dir(output_dir),
        safe_repo_filename(repo_name, start_date, end_date),
    )


def default_summary_path(
    repo_name: str,
    start_date: str,
    end_date: str,
    *,
    output_dir: str | None = None,
) -> str:
    stem = safe_repo_filename(repo_name, start_date, end_date).removesuffix(".tsv")
    return os.path.join(_output_dir(output_dir), f"{stem}_person_summary.tsv")


def default_xlsx_path(
    repo_name: str,
    start_date: str,
    end_date: str,
    *,
    output_dir: str | None = None,
) -> str:
    stem = safe_repo_filename(repo_name, start_date, end_date).removesuffix(".tsv")
    return os.path.join(_output_dir(output_dir), f"{stem}.xlsx")


def summary_path_from_detail(detail_path: str) -> str:
    if detail_path.endswith(".tsv"):
        return detail_path[:-4] + "_person_summary.tsv"
    return detail_path + "_person_summary.tsv"


def xlsx_path_from_detail(detail_path: str) -> str:
    if detail_path.endswith(".tsv"):
        return detail_path[:-4] + ".xlsx"
    return detail_path + ".xlsx"


def run_log_path_from_detail(detail_path: str) -> str:
    if detail_path.endswith(".tsv"):
        return detail_path[:-4] + "_run.log"
    return detail_path + "_run.log"


def raw_cache_path_from_detail(detail_path: str) -> str:
    if detail_path.endswith(".tsv"):
        return detail_path[:-4] + "_raw.json"
    return detail_path + "_raw.json"


def paths_from_excel_output(output_path: str) -> tuple[str, str, str]:
    """
    Derive Excel, team summary TSV, and PR detail TSV paths from one output file path.

    Example:
      ~/Documents/may-report.xlsx
        -> ~/Documents/may-report.xlsx
        -> ~/Documents/may-report_person_summary.tsv
        -> ~/Documents/may-report.tsv
    """
    xlsx_path = os.path.expanduser(output_path)
    if not xlsx_path.lower().endswith(".xlsx"):
        xlsx_path = f"{xlsx_path}.xlsx"
    stem = xlsx_path[:-5]
    summary_path = f"{stem}_person_summary.tsv"
    detail_path = f"{stem}.tsv"
    return xlsx_path, summary_path, detail_path


def sibling_paths_from_detail(detail_path: str) -> dict[str, str]:
    return {
        "detail": detail_path,
        "summary": summary_path_from_detail(detail_path),
        "xlsx": xlsx_path_from_detail(detail_path),
        "run_log": run_log_path_from_detail(detail_path),
        "raw_cache": raw_cache_path_from_detail(detail_path),
    }
