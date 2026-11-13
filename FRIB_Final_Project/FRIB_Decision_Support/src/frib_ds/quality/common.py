"""Shared, bounded reports for deterministic evidence quality checks."""
from __future__ import annotations
import math

DETAIL_LIMIT = 25


def make_issue(code, severity, title, message, *, column=None, rows=None,
               timestamps_s=None, count=None, suggestion="", repair=None):
    if severity not in {"error", "warning", "info"}:
        raise ValueError("Issue severity must be error, warning or info")
    rows = list(rows or [])
    timestamps = [value for value in (timestamps_s or []) if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)]
    return {"code":code, "severity":severity, "title":title, "message":message,
            "column":column, "rows":rows[:DETAIL_LIMIT], "timestamps_s":timestamps[:DETAIL_LIMIT],
            "count":int(count if count is not None else max(len(rows),len(timestamps),1)),
            "suggestion":suggestion, "repair":repair}


def make_report(stage, issues, unit_suggestions=None):
    issues=list(issues)
    summary={severity:sum(issue["severity"]==severity for issue in issues) for severity in ("error","warning","info")}
    status="blocked" if summary["error"] else "review" if summary["warning"] else "ok"
    return {"version":"1.0", "stage":stage, "status":status, "summary":summary,
            "issues":issues, "unit_suggestions":list(unit_suggestions or [])}
