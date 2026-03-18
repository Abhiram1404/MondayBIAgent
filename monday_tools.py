"""
Monday.com BI agent tools: get_boards, get_schema, get_unique_values, get_items_filtered, get_items_page, get_random_rows.
Uses live Monday.com GraphQL API only; no preload/cache.

Exceptions (catch these for error handling):
- MondayToolsError: base for all tools errors
- ConfigError: config.yaml missing/invalid
- MondayAPIError: API auth, HTTP, GraphQL, or network failure
- ValidationError: invalid tool arguments

Common warnings when calling Monday API:
- InsecureRequestWarning (urllib3): Shown when MONDAY_SSL_VERIFY=false (HTTPS without cert verification).
  This module suppresses it when SSL verify is disabled. Prefer leaving MONDAY_SSL_VERIFY unset or "true".
- DeprecationWarning: May come from requests/urllib3 or other deps; safe to ignore or upgrade packages.
"""
import json
import logging
import os

import logger  # noqa: F401 — configure logging to logs/app.log
import random
from pathlib import Path
from typing import Any, Optional
from agent_framework import tool
logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import requests
import yaml

# If SSL verification is disabled via MONDAY_SSL_VERIFY, suppress urllib3's
# "InsecureRequestWarning: Unverified HTTPS request is being made" when calling Monday API.
if os.environ.get("MONDAY_SSL_VERIFY", "true").lower() in ("false", "0", "no"):
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

MONDAY_API_URL = "https://api.monday.com/v2"

__all__ = [
    "MondayToolsError",
    "ConfigError",
    "MondayAPIError",
    "ValidationError",
    "get_boards",
    "get_schema",
    "get_unique_values",
    "get_items_filtered",
    "get_items_filtered_by_value_any_column",
    "get_items_page",
    "get_random_rows",
]

# --- Exceptions ---


class MondayToolsError(Exception):
    """Base exception for Monday tools."""


class ConfigError(MondayToolsError):
    """Raised when config.yaml is missing, invalid, or has bad structure."""


class MondayAPIError(MondayToolsError):
    """Raised when Monday.com API call fails (auth, GraphQL errors, HTTP, network)."""


class ValidationError(MondayToolsError):
    """Raised when tool arguments are invalid."""


def _get_token() -> str:
    try:
        token = os.environ.get("MONDAY_API_TOKEN")
        if not token:
            raise MondayAPIError("MONDAY_API_TOKEN is not set")
        return token
    except Exception as e:
        logger.error("_get_token failed: %s", str(e))
        raise


def _ssl_verify() -> bool:
    try:
        v = os.environ.get("MONDAY_SSL_VERIFY", "true").lower()
        return v not in ("false", "0", "no")
    except Exception as e:
        logger.error("_ssl_verify failed: %s", str(e))
        raise


def run_graphql(query: str, variables: Optional[dict] = None) -> dict:
    try:
        try:
            token = _get_token()
        except MondayAPIError:
            raise
        payload = {"query": query}
        if variables:
            payload["variables"] = variables
        try:
            resp = requests.post(
                MONDAY_API_URL,
                json=payload,
                headers={"Authorization": token, "Content-Type": "application/json"},
                verify=_ssl_verify(),
                timeout=60,
            )
            resp.raise_for_status()
        except requests.exceptions.Timeout as e:
            raise MondayAPIError("Request to Monday.com timed out") from e
        except requests.exceptions.ConnectionError as e:
            raise MondayAPIError("Failed to connect to Monday.com") from e
        except requests.exceptions.HTTPError as e:
            msg = str(e)
            if e.response is not None and e.response.text:
                try:
                    err_body = e.response.json()
                    if "errors" in err_body:
                        msg = "Monday API: " + json.dumps(err_body["errors"])
                except (ValueError, KeyError, TypeError):
                    pass
            raise MondayAPIError(msg) from e
        try:
            data = resp.json()
        except json.JSONDecodeError as e:
            raise MondayAPIError("Invalid JSON in Monday.com response") from e
        if "errors" in data and data["errors"]:
            raise MondayAPIError("GraphQL errors: " + json.dumps(data["errors"]))
        return data.get("data", {})
    except Exception as e:
        logger.error("run_graphql failed: %s", str(e))
        raise


def _parse_column_settings(settings: Any) -> list[str]:
    """Extract allowed labels from status/dropdown column settings."""
    try:
        if settings is None:
            return []
        if isinstance(settings, str):
            try:
                settings = json.loads(settings)
            except json.JSONDecodeError:
                return []
        if not isinstance(settings, dict):
            return []
        labels = []
        if "labels" in settings and isinstance(settings["labels"], dict):
            labels = list(settings["labels"].values())
        elif "labels" in settings and isinstance(settings["labels"], list):
            for x in settings["labels"]:
                if isinstance(x, dict) and "name" in x:
                    labels.append(x["name"])
                elif isinstance(x, str):
                    labels.append(x)
        return [str(x).strip() for x in labels if x]
    except Exception as e:
        logger.error("_parse_column_settings failed: %s", str(e))
        raise


# --- Tool 1: get_boards ---

CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"


def _load_boards_from_config() -> list[dict]:
    try:
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except FileNotFoundError as e:
            raise ConfigError(f"Config file not found: {CONFIG_PATH}") from e
        except yaml.YAMLError as e:
            raise ConfigError(f"Invalid YAML in config: {e}") from e
        except OSError as e:
            raise ConfigError(f"Cannot read config file: {e}") from e
        entries = data.get("Board_Ids")
        if entries is None:
            raise ConfigError("Config missing 'Board_Ids' key")
        if not isinstance(entries, list):
            raise ConfigError("'Board_Ids' must be a list")
        result = []
        for i, e in enumerate(entries):
            if not isinstance(e, dict):
                raise ConfigError(f"Board_Ids[{i}] must be a dict with 'id' and 'name'")
            if "id" not in e or "name" not in e:
                raise ConfigError(f"Board_Ids[{i}] must have 'id' and 'name'")
            try:
                result.append({"id": int(e["id"]), "name": str(e["name"])})
            except (TypeError, ValueError) as err:
                raise ConfigError(f"Board_Ids[{i}]: invalid id or name: {err}") from err
        return result
    except Exception as e:
        logger.error("_load_boards_from_config failed: %s", str(e))
        raise

@tool(approval_mode="never_require")
def get_boards() -> list[dict]:
    """
    Returns board id and name from config.yaml.
    Pass board_ids to filter; omit to return all boards from config.
    """
    try:
        boards = _load_boards_from_config()
        return [{"id": b["id"], "name": b["name"]} for b in boards]
    except Exception as e:
        logger.error("get_boards failed: %s", str(e))
        raise


# --- Tool 2: get_schema ---

@tool(approval_mode="never_require")
def get_schema(board_ids: list[int]) -> list[dict]:
    """
    Returns columns for each board: id, title, type, and for status/dropdown the list of allowed values from settings.
    """
    try:
        if not isinstance(board_ids, list):
            raise ValidationError("board_ids must be a list")
        if not board_ids:
            raise ValidationError("board_ids cannot be empty")
        try:
            board_ids = [int(b) for b in board_ids]
        except (TypeError, ValueError) as e:
            raise ValidationError("board_ids must contain integers") from e
        query = """
        query ($boardIds: [ID!]) {
          boards(ids: $boardIds) {
            id
            name
            columns {
              id
              title
              type
              settings
            }
          }
        }
        """
        try:
            data = run_graphql(query, {"boardIds": board_ids})
        except MondayAPIError:
            raise
        boards = data.get("boards") or []
        if not boards and board_ids:
            raise MondayAPIError("No boards returned; check board IDs exist and token has access")
        result = []
        for board in boards:
            if not isinstance(board, dict):
                continue
            cols = []
            for c in board.get("columns") or []:
                if not isinstance(c, dict) or "id" not in c or "title" not in c:
                    continue
                allowed = []
                if c.get("type") in ("status", "dropdown", "color"):
                    allowed = _parse_column_settings(c.get("settings"))
                cols.append({
                    "id": c["id"],
                    "title": c["title"],
                    "type": c.get("type", ""),
                    "allowed_values": allowed if allowed else None,
                })
            result.append({
                "board_id": board.get("id"),
                "board_name": board.get("name", ""),
                "columns": cols,
            })
        return result
    except Exception as e:
        logger.error("get_schema failed: %s", str(e))
        raise


# --- Tool 3: get_unique_values ---


def _text_from_column_value(cv: dict, column_id: str) -> Optional[str]:
    """Extract display text for a column value; fallback to value for text columns."""
    try:
        if cv.get("id") != column_id:
            return None
        text = (cv.get("text") or "").strip()
        if text:
            return text
        val = cv.get("value")
        if val is None:
            return None
        if isinstance(val, str):
            try:
                val = json.loads(val)
            except json.JSONDecodeError:
                return val if val else None
        if isinstance(val, dict):
            if "text" in val:
                return str(val["text"]).strip() or None
            if "label" in val:
                return str(val["label"]).strip() or None
            if "name" in val:
                return str(val["name"]).strip() or None
        return str(val).strip() if val else None
    except Exception as e:
        logger.error("_text_from_column_value failed: %s", str(e))
        raise

@tool(approval_mode="never_require")
def get_unique_values(
    board_id: int,
    column_id: str,
    limit: int = 100,
) -> list[str]:
    """
    Fetches items from the board and returns distinct values for the given column.
    Use for mapping user language (e.g. 'energy') to actual values (e.g. 'Power').
    Default limit=500 so status values that appear on later rows (e.g. 'Partially Billed')
    are not missed when the board has many items.
    """
    try:
        try:
            board_id = int(board_id)
        except (TypeError, ValueError) as e:
            raise ValidationError("board_id must be an integer") from e
        if not column_id or not isinstance(column_id, str):
            raise ValidationError("column_id must be a non-empty string")
        if not isinstance(limit, int) or limit < 1:
            raise ValidationError("limit must be a positive integer")
        limit = min(limit, 100)
        query = """
        query ($boardId: [ID!], $limit: Int!) {
          boards(ids: $boardId) {
            items_page(limit: $limit) {
              items {
                column_values {
                  id
                  text
                  value
                }
              }
            }
          }
        }
        """
        try:
            data = run_graphql(query, {"boardId": [board_id], "limit": limit})
        except MondayAPIError:
            raise
        boards = data.get("boards") or []
        if not boards:
            raise MondayAPIError("No board returned; check board_id and token access")
        seen: set[str] = set()
        for board in boards:
            page = board.get("items_page") or {}
            for item in page.get("items", []):
                for cv in item.get("column_values", []):
                    t = _text_from_column_value(cv, column_id)
                    if t and t not in seen:
                        seen.add(t)
        return sorted(seen)
    except Exception as e:
        logger.error("get_unique_values failed: %s", str(e))
        raise


# --- Tool 4: get_items_filtered ---

@tool(approval_mode="never_require")
def get_items_filtered(
    board_id: int,
    column_filters: list[dict],
    columns_to_return: Optional[list[str]] = None,
    limit: int = 500,
    cursor: Optional[str] = None,
) -> dict:
    """
    Fetches items matching column filters. column_filters: [{"column_id": "status", "column_values": ["Done"]}].
    Returns { "items": [...], "cursor": next_cursor or null }.
    items are normalized to list of dicts with column id -> text value.

    Limit is applied AFTER filtering: Monday returns up to `limit` matching items per page
    (not "first 500 items then filter"). Use cursor to get further pages of matches.
    """
    try:
        board_id = int(board_id)
        
        
        limit = min(limit, 500)
        
        if cursor:
            if not isinstance(cursor, str) or not cursor.strip():
                raise ValidationError("cursor must be a non-empty string")
            query = """
            query ($cursor: String!, $limit: Int!) {
              next_items_page(cursor: $cursor, limit: $limit) {
                cursor
                items {
                  id
                  name
                  column_values {
                    id
                    text
                    value
                  }
                }
              }
            }
            """
            data = run_graphql(query, {"cursor": cursor, "limit": limit})
            page = data.get("next_items_page") or {}
        else:
            columns_var = [
                {"column_id": str(f["column_id"]), "column_values": [str(v) for v in f["column_values"]]}
                for f in column_filters
            ]
            query = """
            query ($boardId: ID!, $limit: Int!, $columns: [ItemsPageByColumnValuesQuery!]) {
              items_page_by_column_values(
                board_id: $boardId
                limit: $limit
                columns: $columns
              ) {
                cursor
                items {
                  id
                  name
                  column_values {
                    id
                    text
                    value
                  }
                }
              }
            }
            """
            data = run_graphql(query, {
                "boardId": board_id,
                "limit": limit,
                "columns": columns_var,
            })
            page = data.get("items_page_by_column_values") or {}
        

        items_raw = page.get("items", [])
        next_cursor = page.get("cursor")

        def normalize_item(item: dict) -> dict:
            row = {"id": item.get("id"), "name": item.get("name") or ""}
            want = set(columns_to_return) if columns_to_return else None
            for cv in item.get("column_values", []):
                cid = cv.get("id")
                if want is not None and cid not in want:
                    continue
                t = _text_from_column_value(cv, cid)
                if cid:
                    row[cid] = t
            return row

        items = [normalize_item(i) for i in items_raw]
        return {"items": items, "cursor": next_cursor}
    except Exception as e:
        logger.error("get_items_filtered failed: %s", str(e))
        raise


# --- Tool 4b: get_items_filtered_by_value_any_column (OR across columns) ---

@tool(approval_mode="never_require")
def get_items_filtered_by_value_any_column(
    board_id: int,
    column_ids: list[str],
    column_value: str,
    columns_to_return: Optional[list[str]] = None,
    limit_per_page: int = 500,
) -> dict:
    """
    Fetches items where ANY of the given columns equals the given value.
    Use when the same status (e.g. "Partially Billed") can appear in multiple
    columns on the board; filtering only one column undercounts.

    limit_per_page is applied AFTER filtering (max matching items per API page).
    Calls get_items_filtered once per column (with full pagination), merges
    by item id, and returns {"items": [...], "cursor": None}.
    """
    try:
        board_id = int(board_id)
        if not column_ids or not isinstance(column_ids, list):
            raise ValidationError("column_ids must be a non-empty list")
        column_ids = [str(cid) for cid in column_ids]
        if not column_value or not isinstance(column_value, str):
            raise ValidationError("column_value must be a non-empty string")
        limit_per_page = min(max(1, limit_per_page), 500)
        seen_ids: set[str] = set()
        merged: list[dict] = []
        for cid in column_ids:
            cursor: Optional[str] = None
            while True:
                if cursor is None:
                    page = get_items_filtered(
                        board_id=board_id,
                        column_filters=[{"column_id": cid, "column_values": [column_value]}],
                        columns_to_return=columns_to_return,
                        limit=limit_per_page,
                    )
                else:
                    page = get_items_filtered(
                        board_id=board_id,
                        column_filters=[{"column_id": cid, "column_values": [column_value]}],
                        columns_to_return=columns_to_return,
                        limit=limit_per_page,
                        cursor=cursor,
                    )
                for item in page.get("items") or []:
                    iid = item.get("id")
                    if iid and iid not in seen_ids:
                        seen_ids.add(iid)
                        merged.append(item)
                cursor = page.get("cursor") if page.get("cursor") else None
                if not cursor:
                    break
        return {"items": merged, "cursor": None}
    except Exception as e:
        logger.error("get_items_filtered_by_value_any_column failed: %s", str(e))
        raise


# --- Tool 5: get_items_page ---

@tool(approval_mode="never_require")
def get_items_page(
    board_id: int,
    limit: int = 500,
    cursor: Optional[str] = None,
) -> dict:
    """
    Fallback: fetch one page of items without column filter (e.g. when filter column type is unsupported).
    Returns { "items": [...], "cursor": next_cursor or null }.
    """
    try:
        try:
            board_id = int(board_id)
        except (TypeError, ValueError) as e:
            raise ValidationError("board_id must be an integer") from e
        if not isinstance(limit, int) or limit < 1:
            raise ValidationError("limit must be a positive integer")
        limit = min(limit, 500)
        if cursor and (not isinstance(cursor, str) or not cursor.strip()):
            raise ValidationError("cursor must be a non-empty string")
        try:
            if cursor:
                query = """
                query ($cursor: String!, $limit: Int!) {
                  next_items_page(cursor: $cursor, limit: $limit) {
                    cursor
                    items {
                      id
                      name
                      column_values {
                        id
                        text
                        value
                      }
                    }
                  }
                }
                """
                data = run_graphql(query, {"cursor": cursor, "limit": limit})
                page = data.get("next_items_page") or {}
            else:
                query = """
                query ($boardId: [ID!], $limit: Int!) {
                  boards(ids: $boardId) {
                    items_page(limit: $limit) {
                      cursor
                      items {
                        id
                        name
                        column_values {
                          id
                          text
                          value
                        }
                      }
                    }
                  }
                }
                """
                data = run_graphql(query, {"boardId": [board_id], "limit": limit})
                boards = data.get("boards") or []
                if not boards:
                    raise MondayAPIError("No board returned; check board_id and token access")
                page = boards[0].get("items_page", {}) if boards else {}
        except MondayAPIError:
            raise

        items_raw = page.get("items", [])
        next_cursor = page.get("cursor")

        def normalize_item(item: dict) -> dict:
            row = {"id": item.get("id"), "name": item.get("name") or ""}
            for cv in item.get("column_values", []):
                cid = cv.get("id")
                t = _text_from_column_value(cv, cid)
                if cid:
                    row[cid] = t
            return row

        items = [normalize_item(i) for i in items_raw]
        return {"items": items, "cursor": next_cursor}
    except Exception as e:
        logger.error("get_items_page failed: %s", str(e))
        raise


# --- Tool 6: get_random_rows ---

@tool(approval_mode="never_require")
def get_random_rows(board_id: int, limit: int = 5) -> dict:
    """
    Fetches a page of items from the board, then returns up to `limit` rows chosen at random.
    Returns {"items": [...]}. If the board has fewer items than limit, returns all.
    """
    try:
        try:
            board_id = int(board_id)
        except (TypeError, ValueError) as e:
            raise ValidationError("board_id must be an integer") from e
        if not isinstance(limit, int) or limit < 1:
            raise ValidationError("limit must be a positive integer")
        limit = min(limit, 100)
        # Fetch up to 100 rows to sample from (API max per page is 500)
        page = get_items_page(board_id=board_id, limit=100)
        items = page.get("items", [])
        if len(items) <= limit:
            chosen = items
        else:
            chosen = random.sample(items, limit)
        return {"items": chosen}
    except Exception as e:
        logger.error("get_random_rows failed: %s", str(e))
        raise
    
    
    
