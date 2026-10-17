import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Optional

import psycopg
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ConfigDict
from psycopg.rows import dict_row

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tuxops-api")

DB_HOST = os.getenv("DB_HOST", "database")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_USER = os.getenv("POSTGRES_USER", "bubu")
DB_NAME = os.getenv("POSTGRES_DB", DB_USER)
DB_PASSWORD_FILE = os.getenv(
    "POSTGRES_PASSWORD_FILE", "/run/secrets/postgres-passwd.txt"
)


class LabCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    priority: str = Field(default="Средний", min_length=1, max_length=50)
    done: bool = False


class LabPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=120)
    category: Optional[str] = Field(default=None, min_length=1, max_length=80)
    priority: Optional[str] = Field(default=None, min_length=1, max_length=50)
    done: Optional[bool] = None


class LabOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    category: str
    priority: str
    done: bool
    createdAt: datetime


def database_password() -> str:
    secret_path = Path(DB_PASSWORD_FILE)
    if secret_path.is_file():
        password = secret_path.read_text(encoding="utf-8").strip()
        if password:
            return password

    fallback = os.getenv("POSTGRES_PASSWORD")
    if fallback:
        return fallback

    raise RuntimeError(
        f"PostgreSQL password not found. Check file: {DB_PASSWORD_FILE}"
    )


def connect_kwargs() -> dict:
    return {
        "host": DB_HOST,
        "port": DB_PORT,
        "dbname": DB_NAME,
        "user": DB_USER,
        "password": database_password(),
        "connect_timeout": 5,
        "row_factory": dict_row,
    }


async def initialise_database() -> None:
    last_error = None

    for attempt in range(1, 31):
        try:
            async with await psycopg.AsyncConnection.connect(**connect_kwargs()) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS labs (
                            id BIGSERIAL PRIMARY KEY,
                            title VARCHAR(120) NOT NULL,
                            category VARCHAR(80) NOT NULL,
                            priority VARCHAR(50) NOT NULL DEFAULT 'Средний',
                            done BOOLEAN NOT NULL DEFAULT FALSE,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    )

                    # Safe migration if the table already existed in an older version.
                    await cur.execute(
                        """
                        ALTER TABLE labs
                            ADD COLUMN IF NOT EXISTS priority VARCHAR(50)
                            NOT NULL DEFAULT 'Средний'
                        """
                    )
                    await cur.execute(
                        """
                        ALTER TABLE labs
                            ADD COLUMN IF NOT EXISTS done BOOLEAN
                            NOT NULL DEFAULT FALSE
                        """
                    )
                    await cur.execute(
                        """
                        ALTER TABLE labs
                            ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ
                            NOT NULL DEFAULT NOW()
                        """
                    )

                    # Add demo labs only when the table is empty.
                    await cur.execute(
                        """
                        INSERT INTO labs (title, category, priority, done, created_at)
                        SELECT seed.title, seed.category, seed.priority,
                               seed.done, seed.created_at
                        FROM (VALUES
                            (
                                'Собрать backup.service и backup.slice',
                                'Linux', 'Высокий', TRUE,
                                TIMESTAMPTZ '2026-10-08 10:00:00+00'
                            ),
                            (
                                'Исследовать Docker bridge network и gateway',
                                'Networking', 'Высокий', FALSE,
                                TIMESTAMPTZ '2026-10-10 10:00:00+00'
                            ),
                            (
                                'Настроить Nginx reverse proxy для двух приложений',
                                'Nginx', 'Средний', FALSE,
                                TIMESTAMPTZ '2026-10-11 10:00:00+00'
                            ),
                            (
                                'Повторить merge, rebase и cherry-pick',
                                'Git', 'Низкий', FALSE,
                                TIMESTAMPTZ '2026-10-12 10:00:00+00'
                            )
                        ) AS seed(title, category, priority, done, created_at)
                        WHERE NOT EXISTS (SELECT 1 FROM labs)
                        """
                    )

            logger.info("PostgreSQL ready; table 'labs' is available")
            return
        except (psycopg.Error, RuntimeError) as exc:
            last_error = exc
            if attempt == 30:
                break
            logger.warning("Database not ready (attempt %s/30): %s", attempt, exc)
            await asyncio.sleep(2)

    raise RuntimeError("Could not initialise PostgreSQL database") from last_error


@asynccontextmanager
async def lifespan(app: FastAPI):
    await initialise_database()
    yield


app = FastAPI(title="TuxOps — DevOps Lab API", lifespan=lifespan)


async def get_db() -> AsyncIterator[psycopg.AsyncConnection]:
    try:
        async with await psycopg.AsyncConnection.connect(**connect_kwargs()) as conn:
            yield conn
    except psycopg.Error as exc:
        logger.exception("PostgreSQL operation failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database temporarily unavailable",
        ) from exc


@app.get("/api/labs", response_model=list[LabOut])
async def get_labs(conn: psycopg.AsyncConnection = Depends(get_db)):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, title, category, priority, done, created_at AS "createdAt"
            FROM labs
            ORDER BY id
            """
        )
        return await cur.fetchall()


@app.post(
    "/api/labs",
    response_model=LabOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_lab(
    lab: LabCreate,
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO labs (title, category, priority, done)
            VALUES (%s, %s, %s, %s)
            RETURNING id, title, category, priority, done,
                      created_at AS "createdAt"
            """,
            (
                lab.title.strip(),
                lab.category.strip(),
                lab.priority.strip(),
                lab.done,
            ),
        )
        return await cur.fetchone()


@app.patch("/api/labs/{lab_id}", response_model=LabOut)
async def update_lab(
    lab_id: int,
    changes: LabPatch,
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    fields = changes.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="Нет полей для изменения")

    if "title" in fields and fields["title"] is not None:
        fields["title"] = fields["title"].strip()
    if "category" in fields and fields["category"] is not None:
        fields["category"] = fields["category"].strip()
    if "priority" in fields and fields["priority"] is not None:
        fields["priority"] = fields["priority"].strip()

    allowed = {"title", "category", "priority", "done"}
    if any(key not in allowed for key in fields):
        raise HTTPException(status_code=400, detail="Недопустимое поле")

    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, title, category, priority, done,
                   created_at AS "createdAt"
            FROM labs WHERE id = %s
            """,
            (lab_id,),
        )
        current = await cur.fetchone()
        if current is None:
            raise HTTPException(status_code=404, detail="Лабораторка не найдена")

        values = {
            "title": fields.get("title", current["title"]),
            "category": fields.get("category", current["category"]),
            "priority": fields.get("priority", current["priority"]),
            "done": fields.get("done", current["done"]),
        }

        await cur.execute(
            """
            UPDATE labs
            SET title = %s, category = %s, priority = %s, done = %s
            WHERE id = %s
            RETURNING id, title, category, priority, done,
                      created_at AS "createdAt"
            """,
            (
                values["title"],
                values["category"],
                values["priority"],
                values["done"],
                lab_id,
            ),
        )
        return await cur.fetchone()


@app.delete("/api/labs/{lab_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lab(
    lab_id: int,
    conn: psycopg.AsyncConnection = Depends(get_db),
):
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM labs WHERE id = %s RETURNING id", (lab_id,))
        if await cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="Лабораторка не найдена")
    return None


@app.get("/")
async def read_index():
    index_path = Path(__file__).resolve().parent / "index.html"
    if index_path.is_file():
        return FileResponse(index_path)
    raise HTTPException(
        status_code=404,
        detail="Файл index.html не найден рядом с main.py",
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
