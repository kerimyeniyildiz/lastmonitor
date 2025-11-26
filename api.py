import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import psycopg2
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse


def isoformat(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    # Always output timezone-aware ISO string
    if value.tzinfo is None:
        return value.isoformat() + "Z"
    return value.isoformat()


class DB:
    def __init__(self, db_url: str):
        if not db_url:
            raise RuntimeError("DB_URL missing")
        self.db_url = db_url

    def fetch_all(self, query: str, params: tuple) -> List[Dict[str, Any]]:
        with psycopg2.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                cols = [desc.name for desc in cur.description]
                rows = cur.fetchall()
        results: List[Dict[str, Any]] = []
        for row in rows:
            item: Dict[str, Any] = {}
            for idx, col in enumerate(cols):
                val = row[idx]
                if isinstance(val, datetime):
                    val = isoformat(val)
                item[col] = val
            results.append(item)
        return results


def get_db() -> DB:
    return DB(os.environ.get("DB_URL", ""))


def get_token_header(authorization: Optional[str] = Header(None)) -> None:
    expected = os.environ.get("API_TOKEN", "")
    if expected:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Unauthorized")
        token = authorization.split(" ", 1)[1].strip()
        if token != expected:
            raise HTTPException(status_code=401, detail="Unauthorized")


app = FastAPI(title="lastmonitor API", version="0.1.0")


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/tweets")
def list_tweets(
    q: Optional[str] = Query(None, description="Query label stored with tweet"),
    search: Optional[str] = Query(None, description="ILIKE filter on text"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: DB = Depends(get_db),
    _: None = Depends(get_token_header),
) -> JSONResponse:
    filters = []
    params: List[Any] = []
    if q:
        filters.append("query = %s")
        params.append(q)
    if search:
        filters.append("text ILIKE %s")
        params.append(f"%{search}%")
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    sql = f"""
        SELECT tweet_id, query, user_handle, user_name, text, link, tweet_created_at, fetched_at
        FROM tweets
        {where}
        ORDER BY COALESCE(tweet_created_at, fetched_at) DESC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])
    rows = db.fetch_all(sql, tuple(params))
    return JSONResponse(rows)


@app.get("/news")
def list_news(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: DB = Depends(get_db),
    _: None = Depends(get_token_header),
) -> JSONResponse:
    sql = """
        SELECT link, source, news_created_at, fetched_at
        FROM news
        ORDER BY COALESCE(news_created_at, fetched_at) DESC
        LIMIT %s OFFSET %s
    """
    rows = db.fetch_all(sql, (limit, offset))
    return JSONResponse(rows)


@app.get("/stats/daily")
def stats_daily(
    db: DB = Depends(get_db), _: None = Depends(get_token_header)
) -> JSONResponse:
    sql = """
        SELECT
            date(COALESCE(tweet_created_at, fetched_at)) AS day,
            COUNT(*) AS tweets
        FROM tweets
        GROUP BY day
        ORDER BY day DESC
        LIMIT 90
    """
    rows = db.fetch_all(sql, ())
    return JSONResponse(rows)


@app.get("/stats/top-queries")
def stats_top_queries(
    limit: int = Query(20, ge=1, le=100),
    db: DB = Depends(get_db),
    _: None = Depends(get_token_header),
) -> JSONResponse:
    sql = """
        SELECT query, COUNT(*) AS total
        FROM tweets
        GROUP BY query
        ORDER BY total DESC
        LIMIT %s
    """
    rows = db.fetch_all(sql, (limit,))
    return JSONResponse(rows)
