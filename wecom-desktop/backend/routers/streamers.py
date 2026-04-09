"""
Streamers router.

Provides endpoints for managing streamer profiles, viewing conversation history
across agents, and AI-powered persona analysis.

Streamers are identified by their unique combination of name + avatar.
One streamer can have multiple conversations with different agents via different devices.
"""

import hashlib
import json
import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services.federated_reads import federated_reads
from wecom_automation.database.schema import get_connection, get_db_path

router = APIRouter()


# ============================================================================
# Pydantic Models
# ============================================================================


class StreamerProfile(BaseModel):
    """Streamer profile - extensible design for future fields."""

    name: Optional[str] = None
    gender: Optional[str] = None
    age: Optional[int] = None
    location: Optional[str] = None
    height: Optional[int] = None
    weight: Optional[int] = None
    education: Optional[str] = None
    occupation: Optional[str] = None
    interests: Optional[List[str]] = None
    social_platforms: Optional[List[str]] = None
    notes: Optional[str] = None
    custom_fields: Optional[Dict[str, Any]] = None


class PersonaDimension(BaseModel):
    """A single dimension in the persona radar chart."""

    name: str
    value: int  # 0-100
    description: Optional[str] = None


class StreamerPersona(BaseModel):
    """AI-generated persona analysis result."""

    id: int
    streamer_id: str
    communication_style: Optional[str] = None
    language_patterns: Optional[List[str]] = None
    tone: Optional[str] = None
    engagement_level: Optional[str] = None
    response_time_pattern: Optional[str] = None
    active_hours: Optional[List[str]] = None
    topics_of_interest: Optional[List[str]] = None
    personality_traits: Optional[List[str]] = None
    dimensions: List[PersonaDimension] = []
    analysis_summary: Optional[str] = None
    recommendations: Optional[List[str]] = None
    analyzed_at: Optional[str] = None
    analyzed_messages_count: int = 0
    model_used: Optional[str] = None


class StreamerConversation(BaseModel):
    """A conversation between a streamer and an agent."""

    id: int  # Customer ID
    agent_name: str
    agent_department: Optional[str] = None
    device_serial: str
    channel: Optional[str] = None
    message_count: int = 0
    last_message_at: Optional[str] = None
    last_message_preview: Optional[str] = None


class StreamerSummary(BaseModel):
    """Summary of a unique streamer (grouped by name + avatar)."""

    id: str  # Hash of name + avatar_url
    name: str
    avatar_url: Optional[str] = None
    conversation_count: int = 0
    total_messages: int = 0
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    agents: List[str] = []
    channels: List[str] = []
    profile: Optional[StreamerProfile] = None
    has_persona: bool = False


class StreamerDetail(BaseModel):
    """Detailed streamer information including profile, conversations, and persona."""

    id: str
    name: str
    avatar_url: Optional[str] = None
    profile: StreamerProfile
    conversations: List[StreamerConversation] = []
    persona: Optional[StreamerPersona] = None
    total_messages: int = 0
    first_interaction: Optional[str] = None
    last_interaction: Optional[str] = None


class AITestRequest(BaseModel):
    """Request to test AI connection."""

    provider: str
    base_url: str
    api_key: str
    model: str


# ============================================================================
# Helper Functions
# ============================================================================


def _open_db(db_path: Optional[str]) -> Tuple[Any, str]:
    """Open the SQLite database."""
    resolved_path = get_db_path(db_path)
    if not resolved_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Database not found at {resolved_path}",
        )
    return get_connection(str(resolved_path)), str(resolved_path)


def _generate_streamer_id(name: str, avatar_url: Optional[str]) -> str:
    """Generate a unique ID for a streamer based on name + avatar."""
    key = f"{name}|{avatar_url or ''}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _ensure_streamer_tables(conn: Any) -> None:
    """Ensure streamer-related tables exist."""
    cursor = conn.cursor()

    # Create streamer_profiles table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS streamer_profiles (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            avatar_url TEXT,
            gender TEXT,
            age INTEGER,
            location TEXT,
            height INTEGER,
            weight INTEGER,
            education TEXT,
            occupation TEXT,
            interests TEXT,  -- JSON array
            social_platforms TEXT,  -- JSON array
            notes TEXT,
            custom_fields TEXT,  -- JSON object
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create streamer_personas table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS streamer_personas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            streamer_id TEXT NOT NULL REFERENCES streamer_profiles(id),
            communication_style TEXT,
            language_patterns TEXT,  -- JSON array
            tone TEXT,
            engagement_level TEXT,
            response_time_pattern TEXT,
            active_hours TEXT,  -- JSON array
            topics_of_interest TEXT,  -- JSON array
            personality_traits TEXT,  -- JSON array
            dimensions TEXT,  -- JSON array of PersonaDimension
            analysis_summary TEXT,
            recommendations TEXT,  -- JSON array
            analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            analyzed_messages_count INTEGER DEFAULT 0,
            model_used TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()


def _get_or_create_profile(conn: Any, streamer_id: str, name: str, avatar_url: Optional[str]) -> Dict[str, Any]:
    """Get or create a streamer profile."""
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM streamer_profiles WHERE id = ?", (streamer_id,))
    row = cursor.fetchone()

    if row:
        return dict(row)

    # Create new profile
    cursor.execute(
        """
        INSERT INTO streamer_profiles (id, name, avatar_url)
        VALUES (?, ?, ?)
    """,
        (streamer_id, name, avatar_url),
    )
    conn.commit()

    cursor.execute("SELECT * FROM streamer_profiles WHERE id = ?", (streamer_id,))
    return dict(cursor.fetchone())


def _parse_json_field(value: Optional[str]) -> Any:
    """Parse a JSON field, returning None if invalid."""
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    """Safely get a value from a sqlite3.Row object."""
    if row is None:
        return default
    try:
        return row[key] if key in row.keys() else default
    except (KeyError, TypeError):
        return default


# ============================================================================
# Endpoints
# ============================================================================


@router.get("")
async def list_streamers(
    db_path: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None),
):
    """
    List unique streamers grouped by name + avatar.

    Returns streamers with aggregated stats from all their conversations.
    """
    if db_path is None:
        return federated_reads.list_streamers(limit=limit, offset=offset, search=search)

    conn, resolved_path = _open_db(db_path)
    try:
        _ensure_streamer_tables(conn)
        cursor = conn.cursor()

        # Build search condition
        where_clause = ""
        params: List[Any] = []
        if search:
            where_clause = "WHERE c.name LIKE ?"
            params.append(f"%{search}%")

        # Query to get unique streamers with stats
        # Note: We don't have avatar_url in the customers table, so we'll use name only for grouping
        query = f"""
            SELECT 
                c.name,
                MIN(c.created_at) as first_seen,
                MAX(COALESCE(
                    (SELECT MAX(COALESCE(m.timestamp_parsed, m.created_at)) 
                     FROM messages m WHERE m.customer_id = c.id),
                    c.updated_at
                )) as last_seen,
                COUNT(DISTINCT c.id) as conversation_count,
                COALESCE(SUM((SELECT COUNT(*) FROM messages m WHERE m.customer_id = c.id)), 0) as total_messages,
                GROUP_CONCAT(DISTINCT k.name) as agents,
                GROUP_CONCAT(DISTINCT c.channel) as channels
            FROM customers c
            JOIN kefus k ON c.kefu_id = k.id
            {where_clause}
            GROUP BY c.name
            ORDER BY last_seen DESC
            LIMIT ? OFFSET ?
        """

        cursor.execute(query, (*params, limit, offset))
        rows = cursor.fetchall()

        # Count total unique streamers
        count_query = f"""
            SELECT COUNT(DISTINCT c.name) as count
            FROM customers c
            {where_clause}
        """
        cursor.execute(count_query, tuple(params))
        total = cursor.fetchone()["count"]

        # Build response items
        items = []
        for row in rows:
            name = row["name"]
            streamer_id = _generate_streamer_id(name, None)

            # Get profile if exists
            cursor.execute("SELECT * FROM streamer_profiles WHERE id = ?", (streamer_id,))
            profile_row = cursor.fetchone()
            profile = None
            if profile_row:
                profile = StreamerProfile(
                    name=profile_row["name"] if "name" in profile_row.keys() else None,
                    gender=profile_row["gender"] if "gender" in profile_row.keys() else None,
                    age=profile_row["age"] if "age" in profile_row.keys() else None,
                    location=profile_row["location"] if "location" in profile_row.keys() else None,
                    height=profile_row["height"] if "height" in profile_row.keys() else None,
                    weight=profile_row["weight"] if "weight" in profile_row.keys() else None,
                    education=profile_row["education"] if "education" in profile_row.keys() else None,
                    occupation=profile_row["occupation"] if "occupation" in profile_row.keys() else None,
                    interests=_parse_json_field(profile_row["interests"])
                    if "interests" in profile_row.keys()
                    else None,
                    social_platforms=_parse_json_field(profile_row["social_platforms"])
                    if "social_platforms" in profile_row.keys()
                    else None,
                    notes=profile_row["notes"] if "notes" in profile_row.keys() else None,
                    custom_fields=_parse_json_field(profile_row["custom_fields"])
                    if "custom_fields" in profile_row.keys()
                    else None,
                )

            # Check if persona exists
            cursor.execute("SELECT id FROM streamer_personas WHERE streamer_id = ? LIMIT 1", (streamer_id,))
            has_persona = cursor.fetchone() is not None

            agents = [a for a in (row["agents"] or "").split(",") if a]
            channels = [c for c in (row["channels"] or "").split(",") if c]

            items.append(
                StreamerSummary(
                    id=streamer_id,
                    name=name,
                    avatar_url=None,  # No avatar in current schema
                    conversation_count=row["conversation_count"],
                    total_messages=row["total_messages"],
                    first_seen=row["first_seen"],
                    last_seen=row["last_seen"],
                    agents=agents,
                    channels=channels,
                    profile=profile,
                    has_persona=has_persona,
                )
            )

        return {
            "db_path": resolved_path,
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [item.model_dump() for item in items],
        }
    finally:
        conn.close()


@router.delete("/{streamer_id}")
async def delete_streamer(
    streamer_id: str,
    db_path: Optional[str] = Query(None),
):
    """
    Delete a streamer and all associated data.

    This deletes:
    - All customers (conversations) with this streamer's name
    - All messages in those conversations (CASCADE)
    - All images in those messages (CASCADE)
    - The streamer_profile entry
    - All streamer_personas entries

    This operation is irreversible, but data can be re-synced from the device.
    """
    if db_path is None:
        return federated_reads.delete_streamer(streamer_id)

    conn, resolved_path = _open_db(db_path)
    try:
        _ensure_streamer_tables(conn)
        cursor = conn.cursor()

        # First, find the streamer name from the ID
        cursor.execute("SELECT name FROM streamer_profiles WHERE id = ?", (streamer_id,))
        profile_row = cursor.fetchone()

        if profile_row:
            name = profile_row["name"]
        else:
            # Try to find by checking all customers and matching the ID
            cursor.execute("SELECT DISTINCT name FROM customers")
            found_name = None
            for row in cursor.fetchall():
                if _generate_streamer_id(row["name"], None) == streamer_id:
                    found_name = row["name"]
                    break

            if not found_name:
                raise HTTPException(status_code=404, detail="Streamer not found")

            name = found_name

        # Get stats before deletion
        cursor.execute(
            """
            SELECT 
                COUNT(DISTINCT c.id) as conversation_count,
                COALESCE(SUM((SELECT COUNT(*) FROM messages m WHERE m.customer_id = c.id)), 0) as message_count
            FROM customers c
            WHERE c.name = ?
        """,
            (name,),
        )
        stats = cursor.fetchone()
        conversation_count = stats["conversation_count"] if stats else 0
        message_count = stats["message_count"] if stats else 0

        # Check if profile and persona exist
        cursor.execute("SELECT COUNT(*) as count FROM streamer_profiles WHERE id = ?", (streamer_id,))
        has_profile = cursor.fetchone()["count"] > 0

        cursor.execute("SELECT COUNT(*) as count FROM streamer_personas WHERE streamer_id = ?", (streamer_id,))
        persona_count = cursor.fetchone()["count"]

        # Delete all customers with this streamer name (cascades to messages, images)
        cursor.execute("DELETE FROM customers WHERE name = ?", (name,))

        # Delete streamer profile and personas
        cursor.execute("DELETE FROM streamer_personas WHERE streamer_id = ?", (streamer_id,))
        cursor.execute("DELETE FROM streamer_profiles WHERE id = ?", (streamer_id,))

        conn.commit()

        return {
            "success": True,
            "message": f"Deleted streamer '{name}' and all associated data",
            "deleted": {
                "streamer_id": streamer_id,
                "streamer_name": name,
                "conversations_removed": conversation_count,
                "messages_removed": message_count,
                "profile_removed": has_profile,
                "personas_removed": persona_count,
            },
            "db_path": resolved_path,
        }
    finally:
        conn.close()


@router.get("/{streamer_id}")
async def get_streamer_detail(
    streamer_id: str,
    db_path: Optional[str] = Query(None),
):
    """
    Get detailed information for a streamer including profile, conversations, and persona.
    """
    if db_path is None:
        return federated_reads.get_streamer_detail(streamer_id)

    conn, resolved_path = _open_db(db_path)
    try:
        _ensure_streamer_tables(conn)
        cursor = conn.cursor()

        # Find the streamer name from the ID
        # First check if we have a profile with this ID
        cursor.execute("SELECT name, avatar_url FROM streamer_profiles WHERE id = ?", (streamer_id,))
        profile_row = cursor.fetchone()

        if profile_row:
            name = profile_row["name"]
            avatar_url = profile_row["avatar_url"]
        else:
            # Try to find by checking all customers and matching the ID
            cursor.execute("SELECT DISTINCT name FROM customers")
            found_name = None
            for row in cursor.fetchall():
                if _generate_streamer_id(row["name"], None) == streamer_id:
                    found_name = row["name"]
                    break

            if not found_name:
                raise HTTPException(status_code=404, detail="Streamer not found")

            name = found_name
            avatar_url = None
            # Create the profile
            _get_or_create_profile(conn, streamer_id, name, avatar_url)

        # Get all conversations for this streamer
        cursor.execute(
            """
            SELECT 
                c.id,
                c.channel,
                c.last_message_preview,
                k.name as agent_name,
                k.department as agent_department,
                d.serial as device_serial,
                (SELECT COUNT(*) FROM messages m WHERE m.customer_id = c.id) as message_count,
                (SELECT MAX(COALESCE(m.timestamp_parsed, m.created_at)) 
                 FROM messages m WHERE m.customer_id = c.id) as last_message_at
            FROM customers c
            JOIN kefus k ON c.kefu_id = k.id
            JOIN kefu_devices kd ON k.id = kd.kefu_id
            JOIN devices d ON kd.device_id = d.id
            WHERE c.name = ?
            ORDER BY last_message_at DESC
        """,
            (name,),
        )

        conversations = []
        total_messages = 0
        first_interaction = None
        last_interaction = None

        for row in cursor.fetchall():
            conv = StreamerConversation(
                id=row["id"],
                agent_name=row["agent_name"],
                agent_department=row["agent_department"],
                device_serial=row["device_serial"],
                channel=row["channel"],
                message_count=row["message_count"],
                last_message_at=row["last_message_at"],
                last_message_preview=row["last_message_preview"],
            )
            conversations.append(conv)
            total_messages += row["message_count"]

            if row["last_message_at"]:
                if not last_interaction or row["last_message_at"] > last_interaction:
                    last_interaction = row["last_message_at"]

        # Get first interaction
        cursor.execute(
            """
            SELECT MIN(COALESCE(m.timestamp_parsed, m.created_at)) as first_at
            FROM messages m
            JOIN customers c ON m.customer_id = c.id
            WHERE c.name = ?
        """,
            (name,),
        )
        first_row = cursor.fetchone()
        if first_row and first_row["first_at"]:
            first_interaction = first_row["first_at"]

        # Get profile
        cursor.execute("SELECT * FROM streamer_profiles WHERE id = ?", (streamer_id,))
        profile_row = cursor.fetchone()
        profile = StreamerProfile()
        if profile_row:
            profile = StreamerProfile(
                name=_row_get(profile_row, "name"),
                gender=_row_get(profile_row, "gender"),
                age=_row_get(profile_row, "age"),
                location=_row_get(profile_row, "location"),
                height=_row_get(profile_row, "height"),
                weight=_row_get(profile_row, "weight"),
                education=_row_get(profile_row, "education"),
                occupation=_row_get(profile_row, "occupation"),
                interests=_parse_json_field(_row_get(profile_row, "interests")),
                social_platforms=_parse_json_field(_row_get(profile_row, "social_platforms")),
                notes=_row_get(profile_row, "notes"),
                custom_fields=_parse_json_field(_row_get(profile_row, "custom_fields")),
            )

        # Get persona
        cursor.execute(
            """
            SELECT * FROM streamer_personas 
            WHERE streamer_id = ? 
            ORDER BY analyzed_at DESC 
            LIMIT 1
        """,
            (streamer_id,),
        )
        persona_row = cursor.fetchone()
        persona = None
        if persona_row:
            persona = StreamerPersona(
                id=persona_row["id"],
                streamer_id=persona_row["streamer_id"],
                communication_style=_row_get(persona_row, "communication_style"),
                language_patterns=_parse_json_field(_row_get(persona_row, "language_patterns")),
                tone=_row_get(persona_row, "tone"),
                engagement_level=_row_get(persona_row, "engagement_level"),
                response_time_pattern=_row_get(persona_row, "response_time_pattern"),
                active_hours=_parse_json_field(_row_get(persona_row, "active_hours")),
                topics_of_interest=_parse_json_field(_row_get(persona_row, "topics_of_interest")),
                personality_traits=_parse_json_field(_row_get(persona_row, "personality_traits")),
                dimensions=_parse_json_field(_row_get(persona_row, "dimensions")) or [],
                analysis_summary=_row_get(persona_row, "analysis_summary"),
                recommendations=_parse_json_field(_row_get(persona_row, "recommendations")),
                analyzed_at=_row_get(persona_row, "analyzed_at"),
                analyzed_messages_count=_row_get(persona_row, "analyzed_messages_count", 0),
                model_used=_row_get(persona_row, "model_used"),
            )

        detail = StreamerDetail(
            id=streamer_id,
            name=name,
            avatar_url=avatar_url,
            profile=profile,
            conversations=[c.model_dump() for c in conversations],
            persona=persona.model_dump() if persona else None,
            total_messages=total_messages,
            first_interaction=first_interaction,
            last_interaction=last_interaction,
        )

        return {
            "db_path": resolved_path,
            "streamer": detail.model_dump(),
        }
    finally:
        conn.close()


@router.put("/{streamer_id}/profile")
async def update_streamer_profile(
    streamer_id: str,
    profile: StreamerProfile,
    db_path: Optional[str] = Query(None),
):
    """
    Update a streamer's profile information.
    """
    if db_path is None:
        return federated_reads.update_streamer_profile(streamer_id, profile.model_dump())

    conn, resolved_path = _open_db(db_path)
    try:
        _ensure_streamer_tables(conn)
        cursor = conn.cursor()

        # Check if profile exists
        cursor.execute("SELECT id FROM streamer_profiles WHERE id = ?", (streamer_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Streamer profile not found")

        # Update profile
        cursor.execute(
            """
            UPDATE streamer_profiles SET
                gender = COALESCE(?, gender),
                age = COALESCE(?, age),
                location = COALESCE(?, location),
                height = COALESCE(?, height),
                weight = COALESCE(?, weight),
                education = COALESCE(?, education),
                occupation = COALESCE(?, occupation),
                interests = COALESCE(?, interests),
                social_platforms = COALESCE(?, social_platforms),
                notes = COALESCE(?, notes),
                custom_fields = COALESCE(?, custom_fields),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """,
            (
                profile.gender,
                profile.age,
                profile.location,
                profile.height,
                profile.weight,
                profile.education,
                profile.occupation,
                json.dumps(profile.interests) if profile.interests else None,
                json.dumps(profile.social_platforms) if profile.social_platforms else None,
                profile.notes,
                json.dumps(profile.custom_fields) if profile.custom_fields else None,
                streamer_id,
            ),
        )
        conn.commit()

        return {"success": True, "message": "Profile updated"}
    finally:
        conn.close()


@router.post("/{streamer_id}/analyze-persona")
async def analyze_streamer_persona(
    streamer_id: str,
    db_path: Optional[str] = Query(None),
):
    """
    Analyze a streamer's persona using AI based on their conversation history.

    This endpoint:
    1. Gathers all messages from this streamer's conversations
    2. Sends them to the configured AI provider for analysis
    3. Stores the resulting persona analysis
    """
    if db_path is None:
        return await federated_reads.analyze_streamer_persona(streamer_id)

    conn, resolved_path = _open_db(db_path)
    try:
        _ensure_streamer_tables(conn)
        cursor = conn.cursor()

        # Get streamer name
        cursor.execute("SELECT name FROM streamer_profiles WHERE id = ?", (streamer_id,))
        profile_row = cursor.fetchone()
        if not profile_row:
            raise HTTPException(status_code=404, detail="Streamer not found")

        name = profile_row["name"]

        # Get all messages from this streamer (not from kefu)
        cursor.execute(
            """
            SELECT m.content, m.message_type, m.timestamp_parsed, m.timestamp_raw
            FROM messages m
            JOIN customers c ON m.customer_id = c.id
            WHERE c.name = ? AND m.is_from_kefu = 0 AND m.content IS NOT NULL
            ORDER BY COALESCE(m.timestamp_parsed, m.created_at) ASC
            LIMIT 500
        """,
            (name,),
        )

        messages = [dict(row) for row in cursor.fetchall()]

        if len(messages) < 5:
            raise HTTPException(status_code=400, detail="Not enough messages for analysis (minimum 5 required)")

        # Prepare message content for analysis
        message_texts = [m["content"] for m in messages if m["content"]]

        # Call AI for analysis
        try:
            from services.ai_analysis import analyze_streamer_persona as run_ai_analysis

            analysis_result = await run_ai_analysis(name, message_texts)
        except ImportError:
            # Fallback to mock analysis if service not available
            analysis_result = _mock_persona_analysis(name, message_texts)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"AI analysis failed: {str(e)}")

        # Store the persona
        cursor.execute(
            """
            INSERT INTO streamer_personas (
                streamer_id, communication_style, language_patterns, tone,
                engagement_level, response_time_pattern, active_hours,
                topics_of_interest, personality_traits, dimensions,
                analysis_summary, recommendations, analyzed_messages_count, model_used
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                streamer_id,
                analysis_result.get("communication_style"),
                json.dumps(analysis_result.get("language_patterns", [])),
                analysis_result.get("tone"),
                analysis_result.get("engagement_level"),
                analysis_result.get("response_time_pattern"),
                json.dumps(analysis_result.get("active_hours", [])),
                json.dumps(analysis_result.get("topics_of_interest", [])),
                json.dumps(analysis_result.get("personality_traits", [])),
                json.dumps(analysis_result.get("dimensions", [])),
                analysis_result.get("analysis_summary"),
                json.dumps(analysis_result.get("recommendations", [])),
                len(messages),
                analysis_result.get("model_used", "unknown"),
            ),
        )
        conn.commit()

        return {
            "success": True,
            "message": f"Analyzed {len(messages)} messages",
            "persona_id": cursor.lastrowid,
        }
    finally:
        conn.close()


@router.post("/test-ai")
async def test_ai_connection(request: AITestRequest):
    """
    Test the AI provider connection with the given settings.
    """
    start_time = time.time()

    try:
        import httpx

        # Build the appropriate endpoint based on provider
        if request.provider == "deepseek":
            url = f"{request.base_url}/chat/completions"
        elif request.provider == "openai":
            url = f"{request.base_url}/v1/chat/completions"
        else:
            url = f"{request.base_url}/chat/completions"

        headers = {
            "Authorization": f"Bearer {request.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": request.model,
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 10,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload, headers=headers)

        latency_ms = int((time.time() - start_time) * 1000)

        if response.status_code == 200:
            return {
                "success": True,
                "message": "Connected successfully",
                "latency_ms": latency_ms,
            }
        else:
            error_detail = response.json().get("error", {}).get("message", response.text)
            return {
                "success": False,
                "error": f"API error: {error_detail}",
                "latency_ms": latency_ms,
            }

    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        return {
            "success": False,
            "error": str(e),
            "latency_ms": latency_ms,
        }


def _mock_persona_analysis(name: str, messages: List[str]) -> Dict[str, Any]:
    """
    Generate a mock persona analysis for testing purposes.
    Used when AI service is not available.
    """
    return {
        "communication_style": "Casual and friendly",
        "language_patterns": ["使用表情符号", "简短回复", "口语化表达"],
        "tone": "Warm and approachable",
        "engagement_level": "High - responds quickly and engages actively",
        "response_time_pattern": "Most active during evening hours",
        "active_hours": ["18:00-22:00", "12:00-14:00"],
        "topics_of_interest": ["直播内容", "粉丝互动", "收入变现"],
        "personality_traits": ["外向", "热情", "好奇心强"],
        "dimensions": [
            {"name": "外向性", "value": 75, "description": "善于表达,喜欢互动"},
            {"name": "开放性", "value": 68, "description": "愿意尝试新事物"},
            {"name": "尽责性", "value": 55, "description": "一般的时间管理能力"},
            {"name": "宜人性", "value": 82, "description": "友好且合作"},
            {"name": "情绪稳定性", "value": 60, "description": "情绪波动正常"},
        ],
        "analysis_summary": f"基于 {len(messages)} 条消息的分析，{name} 展现出热情友好的沟通风格，积极参与对话，善于使用表情符号和口语化表达。主要活跃在晚间时段，对直播相关话题表现出浓厚兴趣。",
        "recommendations": [
            "在晚间18:00-22:00时段联系效果更好",
            "使用轻松友好的语气进行沟通",
            "可以适当使用表情符号增加亲和力",
            "建议围绕直播变现话题展开深入讨论",
        ],
        "model_used": "mock",
    }
